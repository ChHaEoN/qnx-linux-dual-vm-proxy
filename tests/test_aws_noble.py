"""scripts/aws/ on an Ubuntu 24.04 image (Phase 3b / A6, 2026-10-08).

The bare-metal session moves from an Ubuntu 22.04 image to a 24.04 one, so that the instance's
archive gives the QEMU release the Orin runs since its upgrade. What moves with it is tested here,
against stubs:

  - the image the driver launches by default, read off the launch's argv;
  - user-data installs ipxe-qemu beside qemu-system-arm and qemu-utils, and no longer says what
    this image does on a panic: `setup` reads that from the running kernel;
  - `setup` prints the host's facts before any check, and writes host-facts.txt as soon as the
    record has a directory, so a setup that stops on a new kernel has already said which kernel;
    the facts gain the tick handler's name as kallsyms has it, CONFIG_HZ, and whether the KVM
    counters read;
  - METAL_QEMU_PKG, the package version a session expects: `launch` and `run setup` refuse one
    that is not a package version, and `setup` refuses a host with another version before it
    makes a record, so a corrected value can be given to a second `run setup`;
  - the vsomeip build gets the versioned Boost 1.74 packages, as the Orin has them, and a job
    count and a memory cap sized to the host;
  - the two redactors: redact-aws.sh keeps a digit run whose length is a multiple of 12 and masks
    an IPv6 address by the rule the scan after the fetch refuses on, and the driver's red() keeps
    a 12-digit run inside a longer token;
  - (2026-10-10) the two self-termination nets: user-data arms a monotonic timer first, schedules
    the wall-clock poweroff after a bounded wait for the clock to be synchronised, and records
    what it read at each arming; its per-boot script arms both again after a reboot; `wait`
    proves both and prints the record before it decides.

Nothing here contacts AWS or a board. `setup` runs for real, against stub id, ip, sudo, uname,
nproc, lsmod, dpkg-query, lscpu and qemu-system-aarch64 and a made-up /proc and /sys. User-data
and its per-boot script run for real too, against stub systemd-run, shutdown, systemctl,
timedatectl, timeout, date, sleep, apt-get and usermod on a made-up root, with nothing else on
their PATH. Every value is made up, in the shape a host gives it (a kernel release, a Debian package
version, a kallsyms line, a kernel command line); every identifier is a documentation value. The
bash, the path helper and the driver's rig are tests/test_aws_tooling.py's.

What these tests do NOT show: that the image launches, what its kernel calls the tick handler,
that its KVM counters read, that vsomeip builds there, or anything about a guest; nor that
systemd on an instance answers as the stubs do, that its clock is ever stepped, or that either
net fires. Those are the rehearsal session's to show.
"""
import gzip
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile

import pytest

import test_aws_tooling as aws

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GC = os.path.join(REPO, "orin-native", "gpu-concurrency")
AWSDIR = os.path.join(REPO, "scripts", "aws")
DRIVER = os.path.join(AWSDIR, "drive-metal.sh")
REMOTE = os.path.join(AWSDIR, "remote-ladder.sh")
USERDATA = os.path.join(AWSDIR, "userdata.sh")
CAPTURE = os.path.join(AWSDIR, "capture.py")
README = os.path.join(AWSDIR, "README.md")
ENV_EXAMPLE = os.path.join(AWSDIR, ".env.example")
REDACT = os.path.join(GC, "redact-aws.sh")
LIB = os.path.join(GC, "lib-measure.sh")
PROVISION = os.path.join(REPO, "scripts", "orin", "provision-orin-r39.sh")
BASH = aws.BASH
needs_bash = aws.needs_bash
rig = aws.rig          # the driver against stub aws, ssh and scp

sys.path.insert(0, GC)
import tick_trace as tkt  # noqa: E402

NOBLE_AMI = "ami-0d9429f78b33241cd"
JAMMY_AMI = "ami-02153ae97d7504246"
# Made up, in the shapes the instance gives: `uname -r`, and dpkg's version of qemu-system-arm on
# Ubuntu 24.04, which has the word "ubuntu" inside it.
KERNEL = "9.8.0-1234-example"
QEMU_PKG = "1:9.8.7+ds-0ubuntu1.23"
OTHER_QEMU_PKG = "1:9.8.7+ds-0ubuntu1.24"
LOCKDOWN = "[none] integrity confidentiality"


def _text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _msys(p):
    """A path the scripts can hand to tar: Git's tar reads C: in C:/x as a host name."""
    p = os.path.abspath(str(p)).replace("\\", "/")
    if os.name == "nt" and re.match(r"^[A-Za-z]:/", p):
        return "/" + p[0].lower() + p[2:]
    return p


def _stub(d, name, body):
    aws._write(d / name, "#!/usr/bin/env bash\n" + body, newline=True)
    os.chmod(str(d / name), 0o755)


# --------------------------------------------------------------------------
# the image the driver launches


@needs_bash
@pytest.mark.parametrize("given,want", [(None, NOBLE_AMI), ("ami-0abcdef1234567890", "ami-0abcdef1234567890")])
def test_launch_asks_for_the_noble_image_unless_metal_ami_names_another(rig, given, want):
    """The default is the pin; nothing else says which image a session ran on until the stamp
    does. Read off the argv, as the shutdown behaviour is."""
    run, _state, _ = rig
    r, log = run("launch", **({} if given is None else {"METAL_AMI": given}))
    assert r.returncode == 0, r.stdout + r.stderr
    sent = [ln for ln in log.splitlines() if "run-instances" in ln]
    assert len(sent) == 1, log
    assert re.search(r"--image-id (\S+) ", sent[0]).group(1) == want, sent[0]
    assert JAMMY_AMI not in log, "the Ubuntu 22.04 image is no longer what a launch asks for"


def test_the_drivers_default_image_is_the_noble_one_and_says_so():
    driver = _text(DRIVER)
    m = re.search(r'^AMI="\$\{METAL_AMI:-(ami-[0-9a-f]+)\}"\s+# (\S+) \(public\)$', driver, re.M)
    assert m, "drive-metal.sh no longer sets its default image in the form this test reads"
    assert m.group(1) == NOBLE_AMI
    assert m.group(2) == "ubuntu-noble-24.04-arm64-server-20260923", "the comment names the image the id is"
    assert JAMMY_AMI not in driver, "the Ubuntu 22.04 image's id is gone from the driver"
    example = _text(ENV_EXAMPLE)
    assert "Ubuntu 24.04 arm64" in example and "22.04" not in example
    assert "METAL_QEMU_PKG" in example, "the optional expectation is named where the others are"
    assert "METAL_QEMU_PKG" in driver.split("set -euo pipefail")[0], "and in the driver's header"


# --------------------------------------------------------------------------
# userdata.sh


def _install_words(body):
    """The words of user-data's one package install, continuation lines joined."""
    joined = body.replace("\\\n", " ")
    lines = [ln.split() for ln in joined.splitlines() if re.match(r"^apt-get\b.*\binstall\b", ln.strip())]
    assert len(lines) == 1, "user-data installs its packages in one call"
    return lines[0]


def test_userdata_installs_ipxe_qemu_beside_qemu_without_recommends():
    """qemu-system-arm only recommends ipxe-qemu, and the install is --no-install-recommends, so
    the package has to be named. With it both hosts carry the same three QEMU packages; the
    Orin's qemu-efi-aarch64 is not among them, and the comment says which and why."""
    body = _text(USERDATA)
    words = _install_words(body)
    assert "--no-install-recommends" in words
    for pkg in ("qemu-system-arm", "qemu-utils", "ipxe-qemu"):
        assert words.count(pkg) == 1, pkg
    assert "qemu-efi-aarch64" not in words
    comment = "\n".join(ln for ln in body.splitlines() if ln.startswith("#"))
    assert "ipxe-qemu" in comment and "qemu-efi-aarch64" in comment


def test_no_file_says_what_this_image_does_on_a_panic():
    """user-data and the README said "this AMI boots with panic=-1": a statement about one image,
    carried over to the next unread. What a panic does is now read from the running kernel by
    `setup` (the test below); the texts say why the deadline is on disk, and where to look."""
    for path in (USERDATA, README):
        text = _text(path)
        assert "this AMI boots with" not in re.sub(r"[#\s]+", " ", text), path
        assert "host-facts.txt" in text, "%s names where the session records it" % path
    assert "kernel.panic" in _text(USERDATA)


# --------------------------------------------------------------------------
# setup, run for real against stubs


SETUP_STUBS = {
    "id": 'echo "tester adm kvm"',
    # No bridge until the bridge script has "run" (the sudo stub leaves the marker).
    "ip": '\n'.join(['case "$*" in',
                     '  "link show "*) [ "${STUB_BRIDGE:-up}" = up ] || [ -e "$STUB_DIR/bridge-made" ] || exit 1 ;;',
                     '  *"-br addr"*) echo "br0 UP 192.168.100.1/24" ;;',
                     'esac', 'exit 0']),
    # STUB_SUDO_ASKS: a host whose sudo wants a password (`sudo -n` fails, plain sudo goes on).
    # STUB_NO_DEBUGFS: no /sys/kernel/debug/kvm to look at. STUB_BAD_COUNTER: the counters, by
    # name and space-separated, that debugfs refuses.
    "sudo": '\n'.join(['printf \'%s\\n\' "$*" >> "$STUB_DIR/sudo.log"',
                       'if [ "${1:-}" = -n ]; then',
                       '  [ -z "${STUB_SUDO_ASKS:-}" ] || { echo "sudo: a password is required" >&2; exit 1; }',
                       '  shift',
                       'fi',
                       'case "${1:-}" in',
                       '  bash) case "${2:-}" in *setup-bridge.sh) : > "$STUB_DIR/bridge-made" ;; esac ;;',
                       '  test) [ -z "${STUB_NO_DEBUGFS:-}" ] || exit 1 ;;',
                       '  cat)',
                       '    c="${2##*/}"',
                       '    case " ${STUB_BAD_COUNTER:-} " in',
                       '      *" $c "*) echo "cat: $2: Operation not permitted" >&2; exit 1 ;;',
                       '    esac',
                       '    echo 7 ;;',
                       'esac', 'exit 0']),
    "uname": 'case "${1:-}" in -r) echo "$STUB_KERNEL" ;; -v) echo "#1 SMP made up" ;; *) echo Linux ;; esac',
    "nproc": 'echo "${STUB_NPROC:-16}"',
    "lsmod": '\n'.join(['echo "Module                  Size  Used by"',
                        '[ -e "$STUB_DIR/bridge-made" ] && echo "br_netfilter           32768  0"', 'exit 0']),
    # STUB_QEMU_PKG_LATER: what every call after the first answers (a package that changed
    # while setup ran).
    "dpkg-query": '\n'.join(['printf \'%s\\n\' "$*" >> "$STUB_DIR/dpkg-query.log"',
                             'v="${STUB_QEMU_PKG:-}"',
                             'if [ -n "${STUB_QEMU_PKG_LATER:-}" ] && [ "$(grep -c . "$STUB_DIR/dpkg-query.log")" -gt 1 ]; then',
                             '  v="$STUB_QEMU_PKG_LATER"',
                             'fi',
                             'if [ -z "$v" ]; then',
                             '  echo "dpkg-query: no packages found matching qemu-system-arm" >&2; exit 1',
                             'fi', 'printf \'%s\' "$v"']),
    "lscpu": "exit 0",
    "qemu-system-aarch64": 'echo "QEMU emulator version 9.8.7 (made up)"',
}
SCRUB = ("K", "LADDER_ENV", "METAL_QEMU_PKG", "REHEARSAL", "PROC_ROOT", "SYS_ROOT", "KCONFIG_GZ", "KCONFIG_BOOT",
         "STUB_BAD_COUNTER", "STUB_BRIDGE", "STUB_NPROC", "STUB_NO_DEBUGFS", "STUB_SUDO_ASKS", "STUB_QEMU_PKG_LATER")


def _counters():
    m = re.search(r'^KVM_COUNTERS="([^"]+)"$', _text(LIB), re.M)
    assert m, "lib-measure.sh no longer sets KVM_COUNTERS on one line, which setup reads"
    return m.group(0), m.group(1).split()


class Host:
    """A session directory W as `upload` leaves it, on a made-up host."""

    def __init__(self, tmp_path, handlers=("tick_nohz_highres_handler",), hz="250", config="boot",
                 cmdline_panic="-1", sysctl_panic="-1", inputs=True, ifs_sha=None, bare=False, repo_tar=True):
        """cmdline_panic: the value of the command line's panic= word, None for no such word, or a
        tuple for several words in that order."""
        self.tmp = tmp_path
        self.w = tmp_path / "a1"
        self.rec = self.w / "rec"
        self.stub = tmp_path / "stub"
        self.proc = tmp_path / "proc"
        self.sys = tmp_path / "sys"
        self.boot_config = tmp_path / "boot" / "config-made-up"
        (self.w / "img").mkdir(parents=True)
        self.stub.mkdir()
        for name, body in SETUP_STUBS.items():
            _stub(self.stub, name, body)
        # /proc and /sys
        syms = ["0000000000000000 T tick_handle_periodic", "0000000000000000 t tick_sched_handle",
                "0000000000000000 t tick_nohz_handler_made_up", "0000000000000000 t kvm_bg_timer_expire\t[kvm]"]
        syms[2:2] = ["0000000000000000 t %s" % h for h in handlers]
        aws._write(self.proc / "kallsyms", "\n".join(syms))
        panics = () if cmdline_panic is None else (cmdline_panic,) if isinstance(cmdline_panic, str) else cmdline_panic
        words = ["BOOT_IMAGE=/boot/vmlinuz-" + KERNEL, "root=PARTUUID=00000000-0000-4000-8000-000000000000", "ro"]
        # a panic= word is not always the last one of a command line
        words += ["panic=" + p for p in panics[:-1]] + ["console=ttyS0"] + ["panic=" + p for p in panics[-1:]]
        aws._write(self.proc / "cmdline", " ".join(words))
        if sysctl_panic is not None:
            aws._write(self.proc / "sys" / "kernel" / "panic", sysctl_panic)
        aws._write(self.sys / "kernel" / "security" / "lockdown", LOCKDOWN)
        text = "CONFIG_HZ_250=y\n" + ("" if hz is None else "CONFIG_HZ=%s\n" % hz) + "CONFIG_HZ_PERIODIC=n\n"
        if config == "boot":
            aws._write(self.boot_config, text, newline=False)
        elif config == "gz":
            with gzip.open(str(self.proc / "config.gz"), "wb") as f:
                f.write(text.encode())
        if bare:           # a host that has none of the files the facts are read from
            shutil.rmtree(str(self.proc))
            shutil.rmtree(str(self.sys))
            self.proc.mkdir()
            self.sys.mkdir()
        # what upload sends
        counters_line, self.counters = _counters()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for rel, body in (("orin-native/gpu-concurrency/latency_probe.py", "# made up\n"),
                              ("orin-native/gpu-concurrency/build-monitor-native.sh", "exit 0\n"),
                              ("orin-native/gpu-concurrency/lib-measure.sh", counters_line + "\n"),
                              ("scripts/setup-bridge.sh", "exit 0\n")):
                info = tarfile.TarInfo(rel)
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body.encode()))
        if repo_tar:
            (self.w / "repo.tar").write_bytes(buf.getvalue())
        (self.w / "img" / "ifs-stamp.bin").write_bytes(b"made-up image")
        with gzip.open(str(self.w / "img" / "disk-qemu.gz"), "wb") as f:
            f.write(b"made-up disk")
        shutil.copy(REMOTE, str(self.w / "remote-ladder.sh"))
        shutil.copy(CAPTURE, str(self.w / "capture.py"))
        if inputs:
            sha = {n: hashlib.sha256((self.w / n).read_bytes()).hexdigest() for n in ("remote-ladder.sh", "capture.py")}
            aws._write(self.w / "inputs.env", "\n".join([
                "IFS_NAME=ifs-stamp.bin",
                "IFS_SHA256=" + (ifs_sha or hashlib.sha256(b"made-up image").hexdigest()),
                "DISK_SHA256=" + hashlib.sha256(b"made-up disk").hexdigest(),
                "REMOTE_LADDER_SHA256=" + sha["remote-ladder.sh"],
                "CAPTURE_SHA256=" + sha["capture.py"],
                "REPO_COMMIT=" + "e" * 40]))

    def env(self, **over):
        e = {k: v for k, v in os.environ.items() if k not in SCRUB}
        e.update(W=_msys(self.w), HOME=_msys(self.tmp / "home"), REHEARSAL="1", STUB_DIR=_msys(self.stub),
                 STUB_KERNEL=KERNEL, STUB_QEMU_PKG=QEMU_PKG, PROC_ROOT=_msys(self.proc), SYS_ROOT=_msys(self.sys),
                 KCONFIG_BOOT=_msys(self.boot_config), PATH=aws._path_with(self.stub))
        for k, v in over.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = str(v)
        return e

    def setup(self, **over):
        return subprocess.run([BASH, _msys(self.w / "remote-ladder.sh"), "setup"], capture_output=True, text=True,
                              timeout=300, env=self.env(**over))

    def facts(self):
        return (self.rec / "host-facts.txt").read_text(encoding="utf-8")


def _printed(out):
    """The host facts setup printed, as a dict."""
    return dict(ln[len("host fact: "):].split("=", 1) for ln in out.splitlines() if ln.startswith("host fact: "))


def _section(facts, title):
    """The lines of one "== title" section of host-facts.txt."""
    lines = facts.splitlines()
    at = [i for i, ln in enumerate(lines) if ln == "== " + title]
    assert len(at) == 1, (title, facts)
    out = []
    for ln in lines[at[0] + 1:]:
        if ln.startswith("== "):
            break
        out.append(ln)
    return out


def test_setups_handler_names_are_the_reports():
    """`setup` prints the facts before the repository is unpacked, so it cannot read
    tick_trace.py's list and carries the three names itself. This holds the two equal."""
    m = re.search(r'^TICK_HANDLERS="([^"]+)"', _text(REMOTE), re.M)
    assert m, "remote-ladder.sh no longer sets TICK_HANDLERS on one line"
    assert tuple(m.group(1).split()) == tkt.TICK_HANDLERS


@needs_bash
@pytest.mark.parametrize("handlers,want", [
    (("tick_sched_timer",), "tick_sched_timer"),
    (("tick_nohz_highres_handler",), "tick_nohz_highres_handler"),
    (("tick_nohz_handler",), "tick_nohz_handler"),
    ((), "unknown"),
    # Two of the names in one kernel. Mainline up to 6.6 defines both of these: tick_sched_timer is
    # the tick's hrtimer function there, and tick_nohz_handler the low-resolution handler, a
    # different function from the one that took the name later. Read from mainline's source, not
    # from a running kernel of that series. Said as found, in kallsyms' order, never chosen between.
    (("tick_nohz_handler", "tick_sched_timer"), "tick_nohz_handler,tick_sched_timer"),
    # A name kallsyms lists twice (a module's own static function may carry it) is said once.
    (("tick_nohz_highres_handler", "tick_nohz_highres_handler"), "tick_nohz_highres_handler"),
    (("tick_sched_timer", "tick_nohz_handler", "tick_sched_timer"), "tick_sched_timer,tick_nohz_handler"),
])
def test_setup_prints_the_hosts_facts_and_writes_them_with_the_handler_and_hz(tmp_path, handlers, want):
    host = Host(tmp_path, handlers=handlers)
    r = host.setup()
    assert r.returncode == 0, r.stdout + r.stderr
    got = _printed(r.stdout)
    assert got == {"kernel_release": KERNEL, "config_hz": "250", "config_hz_source": _msys(host.boot_config),
                   "tick_handler": want, "lockdown": LOCKDOWN, "kvm_counters": "readable", "qemu_pkg": QEMU_PKG,
                   "qemu_pkg_expected": "unset", "cmdline_panic": "-1", "kernel_panic": "-1"}, r.stdout
    facts = host.facts()
    assert _section(facts, "tick handler (kallsyms)") == ["tick_handler=" + want]
    assert _section(facts, "kvm counters (read before any check)") == ["kvm_counters=readable"]
    assert _section(facts, "CONFIG_HZ") == ["config_hz=250", "config_hz_source=" + _msys(host.boot_config)]
    # what the file held before, still there
    assert _section(facts, "uname -r") == [KERNEL]
    assert _section(facts, "lockdown") == [LOCKDOWN]
    assert _section(facts, "qemu package") == ["qemu_pkg=" + QEMU_PKG]
    assert _section(facts, "qemu package expected (METAL_QEMU_PKG)") == ["qemu_pkg_expected=unset"]
    assert _section(facts, "panic") == ["cmdline_panic=-1", "kernel_panic=-1"]
    assert _section(facts, "nproc") == ["16"]
    (cmdline,) = _section(facts, "cmdline")
    assert "PARTUUID=<partuuid>" in cmdline and "00000000-0000-4000-8000" not in cmdline
    for title in ("uname -v", "transparent_hugepage", "br_netfilter", "bridge ports (port master)", "kvm halt_poll",
                  "lscpu -e", "cache sharing, cpu0-5"):
        _section(facts, title)
    # a faked host says it is one, on the terminal and in the record
    assert "WARNING: PROC_ROOT overridden" in r.stdout and "WARNING: SYS_ROOT overridden" in r.stdout
    assert _section(facts, "read under") == ["proc_root=" + _msys(host.proc), "sys_root=" + _msys(host.sys)]
    assert "setup done: 16 cores, kernel %s, QEMU emulator version 9.8.7" % KERNEL in r.stdout


@needs_bash
@pytest.mark.parametrize("config,hz,want,source", [
    ("gz", "250", "250", "gz"),          # the Orin's shape: /proc/config.gz
    ("boot", "1000", "1000", "boot"),    # another HZ is said, not judged: the harnesses' guard judges
    ("boot", None, "unread", "unread"),  # a config without the line
    ("none", "250", "unread", "unread"),  # no config to read at all
])
def test_setup_reads_config_hz_where_the_library_reads_it(tmp_path, config, hz, want, source):
    host = Host(tmp_path, hz=hz, config=config)
    r = host.setup()
    assert r.returncode == 0, r.stdout + r.stderr
    src = {"gz": _msys(host.proc / "config.gz"), "boot": _msys(host.boot_config), "unread": "unread"}[source]
    got = _printed(r.stdout)
    assert (got["config_hz"], got["config_hz_source"]) == (want, src), r.stdout
    assert _section(host.facts(), "CONFIG_HZ") == ["config_hz=" + want, "config_hz_source=" + src]


@needs_bash
def test_a_host_with_nothing_to_read_gets_through_setup_with_every_fact_said_as_unread(tmp_path):
    """The facts are read, never required: no kallsyms, no kernel config, no command line, no
    lockdown file, no kernel.panic and no QEMU package stop nothing here. What stops a session
    is a check (a counter, METAL_QEMU_PKG), and each of those says so itself."""
    host = Host(tmp_path, config="none", bare=True)
    r = host.setup(STUB_QEMU_PKG="")
    assert r.returncode == 0 and "setup done" in r.stdout, r.stdout + r.stderr
    assert _printed(r.stdout) == {"kernel_release": KERNEL, "config_hz": "unread", "config_hz_source": "unread",
                                  "tick_handler": "unknown", "lockdown": "absent", "kvm_counters": "readable",
                                  "qemu_pkg": "none", "qemu_pkg_expected": "unset", "cmdline_panic": "absent",
                                  "kernel_panic": "unread"}, r.stdout
    facts = host.facts()
    assert _section(facts, "tick handler (kallsyms)") == ["tick_handler=unknown"]
    assert _section(facts, "CONFIG_HZ") == ["config_hz=unread", "config_hz_source=unread"]
    assert _section(facts, "panic") == ["cmdline_panic=absent", "kernel_panic=unread"]
    assert _section(facts, "read under") == ["proc_root=" + _msys(host.proc), "sys_root=" + _msys(host.sys)]


@needs_bash
def test_the_facts_are_printed_before_the_first_check_can_stop_setup(tmp_path):
    """No inputs.env: the first check of all stops setup, and the facts are already out."""
    host = Host(tmp_path, inputs=False)
    r = host.setup()
    assert r.returncode != 0 and "inputs.env (drive-metal.sh upload writes it)" in r.stderr, r.stdout + r.stderr
    assert _printed(r.stdout)["tick_handler"] == "tick_nohz_highres_handler", r.stdout
    assert _printed(r.stdout)["kernel_release"] == KERNEL
    assert not host.rec.exists(), "a setup refused before its record directory makes none"


@needs_bash
def test_a_leftover_record_is_refused_and_not_written_into(tmp_path):
    host = Host(tmp_path)
    host.rec.mkdir()
    r = host.setup()
    assert r.returncode != 0 and "a leftover; use a fresh W" in r.stderr, r.stdout + r.stderr
    assert _printed(r.stdout)["kernel_release"] == KERNEL
    assert os.listdir(str(host.rec)) == [], "nothing is written into a record setup did not make"


@needs_bash
@pytest.mark.parametrize("which", ["first", "last"])
def test_a_counter_that_does_not_read_stops_setup_and_still_leaves_the_facts(tmp_path, which):
    """The failure a new kernel is most likely to bring: debugfs refuses a KVM counter. Until
    2026-10-08 host-facts.txt was written after that check, so the setup that most needed to
    say which kernel it met left nothing."""
    host = Host(tmp_path)
    bad = host.counters[0 if which == "first" else -1]
    r = host.setup(STUB_BAD_COUNTER=bad)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "KVM counter %s unreadable" % bad in r.stderr and "lockdown: " + LOCKDOWN in r.stderr, r.stderr
    assert "setup done" not in r.stdout
    got = _printed(r.stdout)
    assert (got["kernel_release"], got["config_hz"], got["tick_handler"], got["lockdown"], got["qemu_pkg"]) == \
        (KERNEL, "250", "tick_nohz_highres_handler", LOCKDOWN, QEMU_PKG), r.stdout
    facts = host.facts()
    assert _section(facts, "tick handler (kallsyms)") == ["tick_handler=tick_nohz_highres_handler"]
    assert _section(facts, "CONFIG_HZ")[0] == "config_hz=250"
    assert _section(facts, "uname -r") == [KERNEL] and _section(facts, "qemu package") == ["qemu_pkg=" + QEMU_PKG]
    # and it was already said as a fact, before any check, and is in the file
    assert got["kvm_counters"] == "unreadable:" + bad, r.stdout
    assert _section(facts, "kvm counters (read before any check)") == ["kvm_counters=unreadable:" + bad]


@needs_bash
@pytest.mark.parametrize("case,env,want,stops_on", [
    ("all-read", {}, "readable", None),
    ("one-refused", {"STUB_BAD_COUNTER": 2}, "unreadable:{2}", "KVM counter {2} unreadable"),
    ("three-refused", {"STUB_BAD_COUNTER": (0, 5, -1)}, "unreadable:{0},{5},{-1}", "KVM counter {0} unreadable"),
    # nothing to look at: the fact is not "unreadable", which would say debugfs refused a file
    ("no-debugfs", {"STUB_NO_DEBUGFS": "1"}, "unread", None),
    ("sudo-asks", {"STUB_SUDO_ASKS": "1"}, "unread", "passwordless sudo is required"),
    ("no-tarball", {}, "unread", None),
])
def test_setup_says_whether_the_kvm_counters_read_before_any_check(tmp_path, case, env, want, stops_on):
    """Whether debugfs gives the KVM counters is what a fallback is planned from, so it is read as
    a FACT at the top, with the others: best effort, never a reason to stop there. The names are
    the uploaded tarball's own list (lib-measure.sh's KVM_COUNTERS), the ones the check further
    down reads; that check still stops setup on a counter that does not read."""
    host = Host(tmp_path, repo_tar=(case != "no-tarball"))
    names = host.counters

    def fill(s):
        return re.sub(r"\{(-?\d+)\}", lambda m: names[int(m.group(1))], s)

    env = {k: " ".join(names[i] for i in v) if isinstance(v, tuple) else names[v] if isinstance(v, int) else v
           for k, v in env.items()}
    r = host.setup(**env)
    got = _printed(r.stdout)
    assert got["kvm_counters"] == fill(want), r.stdout + r.stderr
    # the fact is printed with the others, ahead of the first line of any check
    out = r.stdout.splitlines()
    assert out.index("host fact: kvm_counters=" + fill(want)) < min(
        [i for i, ln in enumerate(out) if "artefacts verified" in ln or "KVM counters readable" in ln] or [len(out)])
    if case == "no-tarball":
        assert r.returncode != 0, "there is nothing to unpack"
        return
    assert _section(host.facts(), "kvm counters (read before any check)") == ["kvm_counters=" + fill(want)]
    if stops_on is None:
        assert r.returncode == 0 and "setup done" in r.stdout, r.stdout + r.stderr
    else:
        assert r.returncode != 0 and fill(stops_on) in r.stderr and "setup done" not in r.stdout, r.stdout + r.stderr


@needs_bash
def test_a_wrong_package_and_a_refused_counter_together_stop_on_the_package_with_the_counter_said(tmp_path):
    """Both at once: setup refuses on the package, before it makes a record, and the operator
    has still learnt that a counter does not read, which is what the fallback is planned from."""
    host = Host(tmp_path)
    bad = host.counters[3]
    r = host.setup(METAL_QEMU_PKG=OTHER_QEMU_PKG, STUB_BAD_COUNTER=bad)
    assert r.returncode != 0 and "METAL_QEMU_PKG expects" in r.stderr, r.stdout + r.stderr
    assert "KVM counter %s unreadable" % bad not in r.stderr and r.stderr.count("FATAL") == 1, \
        "the counter check was never reached: " + r.stderr
    assert _printed(r.stdout)["kvm_counters"] == "unreadable:" + bad
    assert "(KVM counters: unreadable:%s)" % bad in r.stderr, "the refusal repeats it: " + r.stderr
    assert not host.rec.exists()


@needs_bash
def test_the_facts_file_is_there_before_any_later_check_and_again_once_the_bridge_is_up(tmp_path):
    """Written as soon as the record has a directory: a setup that stops at the first check
    after that (an image whose hash differs) leaves it. And written again once the bridge is up,
    so a setup that goes on records the bridge the run uses (the stubs load br_netfilter with
    it, which is what the file can show)."""
    early = Host(tmp_path / "early", ifs_sha="0" * 64)
    r = early.setup(STUB_BRIDGE="none")
    assert r.returncode != 0 and "ifs-stamp.bin hash mismatch" in r.stderr, r.stdout + r.stderr
    assert _section(early.facts(), "br_netfilter") == ["0"]
    assert _section(early.facts(), "tick handler (kallsyms)") == ["tick_handler=tick_nohz_highres_handler"]
    late = Host(tmp_path / "late")
    r = late.setup(STUB_BRIDGE="none")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "setup-bridge.sh" in (late.stub / "sudo.log").read_text()
    assert _section(late.facts(), "br_netfilter") == ["1"]


@needs_bash
@pytest.mark.parametrize("cmdline,sysctl,says,warns", [
    ("-1", "-1", "a host panic reboots this kernel", False),
    ("30", "30", "a host panic reboots this kernel", False),
    (None, "0", "a host panic HALTS this kernel", True),
    ("0", "0", "a host panic HALTS this kernel", True),
    (None, None, "what this kernel does on a panic could not be read", True),
    # Two panic= words: the kernel takes the last one given, and so does the fact.
    (("0", "-1"), "-1", "a host panic reboots this kernel", False),
    (("-1", "0"), "0", "a host panic HALTS this kernel", True),
])
def test_setup_says_what_a_panic_does_on_this_kernel(tmp_path, cmdline, sysctl, says, warns):
    """kernel.panic, read from the running kernel: non-zero reboots, and the per-boot script
    re-arms the deadline; zero halts, and a halted host runs no timer. Said, never assumed from
    the image, and not a reason to stop: the README says what the deadline cannot bound."""
    host = Host(tmp_path, cmdline_panic=cmdline, sysctl_panic=sysctl)
    r = host.setup()
    assert r.returncode == 0, r.stdout + r.stderr
    line = [ln for ln in r.stdout.splitlines() if says in ln]
    assert len(line) == 1, r.stdout
    assert ("WARNING" in line[0]) is warns, line[0]
    word = cmdline[-1] if isinstance(cmdline, tuple) else cmdline
    assert _printed(r.stdout)["cmdline_panic"] == (word or "absent"), r.stdout
    assert _section(host.facts(), "panic") == ["cmdline_panic=" + (word or "absent"),
                                               "kernel_panic=" + (sysctl or "unread")]


@needs_bash
@pytest.mark.parametrize("expected,found,ok", [
    (OTHER_QEMU_PKG, QEMU_PKG, False),      # the archive moved on, or the other host did
    (QEMU_PKG, None, False),                # no such package on this host
    (QEMU_PKG, QEMU_PKG, True),
    (None, QEMU_PKG, True),                 # unset: nothing is expected
    ("", QEMU_PKG, True),                   # empty is unset
    (None, None, True),
])
def test_metal_qemu_pkg_stops_setup_when_dpkg_has_another_version_and_only_then(tmp_path, expected, found, ok):
    """The twin's control is one QEMU package build on both hosts. user-data installs the day's
    qemu-system-arm, the Orin keeps the one it has, and nothing failed when they parted."""
    host = Host(tmp_path)
    r = host.setup(METAL_QEMU_PKG=expected, STUB_QEMU_PKG=found or "")
    out = r.stdout + r.stderr
    got = _printed(r.stdout)
    assert got["qemu_pkg"] == (found or "none") and got["qemu_pkg_expected"] == (expected or "unset"), r.stdout
    differs = "qemu-system-arm is '%s' here and METAL_QEMU_PKG expects '%s'" % (found or "none", expected)
    if ok:
        assert r.returncode == 0 and "setup done" in r.stdout, out
        assert "METAL_QEMU_PKG expects" not in out, "nothing warns when nothing differs"
        facts = host.facts()
        assert _section(facts, "qemu package") == ["qemu_pkg=" + (found or "none")]
        assert _section(facts, "qemu package expected (METAL_QEMU_PKG)") == ["qemu_pkg_expected=" + (expected or "unset")]
    else:
        assert r.returncode != 0 and "setup done" not in r.stdout, out
        assert differs in r.stderr, out
        # said at the top as well, with the facts, whichever check then stops setup first
        warned = [ln for ln in r.stdout.splitlines() if "WARNING: " + differs in ln]
        assert len(warned) == 1 and "before it makes a record" in warned[0], r.stdout
        # a refusal like the four checks before it: no record directory, and nothing unpacked
        assert not host.rec.exists(), "a setup refused on METAL_QEMU_PKG leaves no record behind"
        assert not (host.w / "repo").exists() and "artefacts verified" not in r.stdout
        # the session has still learnt whether the counters read
        assert got["kvm_counters"] == "readable" and "(KVM counters: readable)" in r.stderr, out
    assert "qemu-system-arm" in (host.stub / "dpkg-query.log").read_text()


@needs_bash
def test_a_setup_refused_on_metal_qemu_pkg_can_be_run_again_with_the_value_corrected(tmp_path):
    """A mistyped METAL_QEMU_PKG (a missing epoch here) is known at the top of setup. Until this
    was a refusal before the record directory, setup ran on through the unpack, the bridge and
    the counters and stopped last, with rec/ made: the corrected run was then refused a leftover,
    and the driver gives a session one W, so a typo cost the billed session."""
    host = Host(tmp_path)
    r = host.setup(METAL_QEMU_PKG=QEMU_PKG.split(":", 1)[1])
    assert r.returncode != 0 and "METAL_QEMU_PKG expects '%s'" % QEMU_PKG.split(":", 1)[1] in r.stderr, r.stdout + r.stderr
    assert sorted(os.listdir(str(host.w))) == ["capture.py", "img", "inputs.env", "remote-ladder.sh", "repo.tar"], \
        "W is as upload left it"
    assert not (host.tmp / "home").exists(), "and nothing was put in the home directory"
    r = host.setup(METAL_QEMU_PKG=QEMU_PKG)
    assert r.returncode == 0 and "setup done" in r.stdout, r.stdout + r.stderr
    assert "a leftover" not in r.stdout + r.stderr
    assert _section(host.facts(), "qemu package expected (METAL_QEMU_PKG)") == ["qemu_pkg_expected=" + QEMU_PKG]


@needs_bash
@pytest.mark.parametrize("expected,later,ok", [
    (QEMU_PKG, OTHER_QEMU_PKG, False),      # upgraded under a setup that had passed the refusal
    (QEMU_PKG, QEMU_PKG, True),
    (None, OTHER_QEMU_PKG, True),           # nothing expected: nothing is read again
])
def test_a_qemu_package_that_changes_while_setup_runs_stops_it_at_the_end(tmp_path, expected, later, ok):
    """The refusal at the top compares what dpkg said then. The package timers are stopped only
    by quiesce, after setup, so setup's last act is the same comparison on a fresh read."""
    host = Host(tmp_path)
    r = host.setup(METAL_QEMU_PKG=expected, STUB_QEMU_PKG_LATER=later)
    out = r.stdout + r.stderr
    calls = (host.stub / "dpkg-query.log").read_text().splitlines()
    assert "KVM counters readable" in r.stdout, out
    if ok:
        assert r.returncode == 0 and "setup done" in r.stdout, out
    else:
        assert r.returncode != 0 and "setup done" not in r.stdout, out
        assert "qemu-system-arm is now '%s' and METAL_QEMU_PKG expects '%s'" % (later, expected) in r.stderr, out
        assert "changed while setup ran" in r.stderr, out
    assert len(calls) == (1 if expected is None else 2), calls


@needs_bash
def test_the_driver_passes_metal_qemu_pkg_to_setup_and_to_no_other_phase(rig):
    run, state, stub = rig
    aws._launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")
    r, _ = run("run", "setup", METAL_QEMU_PKG=QEMU_PKG)
    assert r.returncode == 0, r.stdout + r.stderr
    r, _ = run("run", "quiesce", METAL_QEMU_PKG=QEMU_PKG)
    assert r.returncode == 0, r.stdout + r.stderr
    r, _ = run("run", "setup")
    assert r.returncode == 0, r.stdout + r.stderr
    log = (stub / "ssh.log").read_text().splitlines()
    assert len(log) == 3, log
    assert "METAL_QEMU_PKG=" + QEMU_PKG in log[0] and "remote-ladder.sh setup" in log[0], log[0]
    assert "METAL_QEMU_PKG" not in log[1] and "remote-ladder.sh quiesce" in log[1], log[1]
    assert "METAL_QEMU_PKG" not in log[2], log[2]


@needs_bash
@pytest.mark.parametrize("bad", ["1:9.8.7 reboot", "1:9.8.7;reboot", "$(reboot)", "-1:9.8.7", "1:9.8.7'x"])
def test_the_driver_refuses_a_metal_qemu_pkg_that_is_not_a_package_version(rig, bad):
    run, state, stub = rig
    aws._launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")
    r, _ = run("run", "setup", METAL_QEMU_PKG=bad)
    assert r.returncode != 0 and "is not a package version" in r.stdout + r.stderr, r.stdout + r.stderr
    assert not (stub / "ssh.log").exists(), "nothing may reach the instance"


@needs_bash
@pytest.mark.parametrize("bad", ["package-version", "1:9.8.7 reboot", "$(reboot)", "-1:9.8.7"])
def test_launch_refuses_a_metal_qemu_pkg_that_is_not_a_package_version_before_any_aws_call(rig, bad):
    """METAL_QEMU_PKG is next read at `run setup`, on an instance that is billed by then. Its
    shape is known before anything is: `launch` checks it as it checks the key-pair and group
    names. "package-version" is the placeholder .env.example carried until 2026-10-08."""
    run, state, stub = rig
    r, log = run("launch", METAL_QEMU_PKG=bad)
    assert r.returncode != 0 and "is not a package version" in r.stdout + r.stderr, r.stdout + r.stderr
    assert log == "" and not (stub / "aws.log").exists(), "no aws call may be made: " + log
    assert not [f for f in ("id", "token", "lock", "launched") if (state / f).exists()], os.listdir(str(state))


@needs_bash
@pytest.mark.parametrize("given", [QEMU_PKG, QEMU_PKG.split(":", 1)[1], "1:9.8.7~rc1+ds-0ubuntu1", None, ""])
def test_launch_goes_on_with_a_well_formed_metal_qemu_pkg_or_none_and_sends_it_nowhere(rig, given):
    """Only the shape is checked at launch: whether it is the right version is the instance's to
    say, at `run setup`. The value is no part of the launch."""
    run, state, _ = rig
    r, log = run("launch", **({} if given is None else {"METAL_QEMU_PKG": given}))
    assert r.returncode == 0 and (state / "vol").exists(), r.stdout + r.stderr
    assert "run-instances" in log and "METAL_QEMU_PKG" not in log and (not given or given not in log), log


def _between(text, start, end):
    """The part of `text` from the line holding `start` up to the line holding `end`."""
    a = text.index(start)
    return text[a:text.index(end, a)]


def test_metal_qemu_pkg_is_among_the_values_to_check_before_launch_and_is_not_kept_in_the_file():
    """It is one session's expectation, the other host's package version on the day: exported for
    the session as a session's own METAL_REPO_TAR is, and not kept in .env.local, where the last
    session's value would be the next one's."""
    readme = _text(README)
    check = _between(readme, "**Check these before `launch`", "`run-instances` itself rejects")
    mine = [i for i in check.split("\n- ")[1:] if i.startswith("`METAL_QEMU_PKG`")]
    assert len(mine) == 1, "the README's list of what to check before launch has no item for it"
    assert "Export it for the session" in mine[0] and ".env.local" in mine[0], mine[0]
    assert "`launch` validates only\n`METAL_KEY_NAME` and `METAL_SG_NAME`;" not in check, "launch now checks its shape too"
    example = _text(ENV_EXAMPLE)
    assert "METAL_QEMU_PKG" in example
    assert not re.search(r"^\s*#?\s*METAL_QEMU_PKG=", example, re.M), ".env.example still offers a line to fill in"
    assert "package-version" not in example, "a placeholder the driver would refuse"
    header = _text(DRIVER).split("set -euo pipefail")[0]
    said = header[header.index("METAL_QEMU_PKG"):]
    assert "environment or .env.local" not in said, "the driver's header still says it may be kept in the file"


_FACT_LINES = ["host fact: kernel_release=" + KERNEL, "host fact: config_hz=250",
               "host fact: config_hz_source=/boot/config-" + KERNEL, "host fact: tick_handler=tick_nohz_highres_handler",
               "host fact: tick_handler=tick_nohz_handler,tick_sched_timer", "host fact: lockdown=" + LOCKDOWN,
               "host fact: kvm_counters=readable", "host fact: kvm_counters=unread",
               "host fact: kvm_counters=unreadable:exits,halt_poll_success_ns,halt_wait_ns",
               "host fact: qemu_pkg=" + QEMU_PKG, "host fact: qemu_pkg_expected=" + OTHER_QEMU_PKG,
               "host fact: cmdline_panic=-1", "host fact: kernel_panic=-1"]


@needs_bash
@pytest.mark.parametrize("login", [None, "ubuntu"])
def test_the_printed_facts_reach_the_transcript_as_they_were_printed(monkeypatch, login):
    """Everything the instance prints passes the driver's red(). None of these lines holds an
    identity, so each comes through whole; a package version it took for an address, or a kernel
    release it took for an id, would cost the rehearsal the facts it is run to get.

    red() also masks the login of whoever runs the driver, and Ubuntu's package versions hold the
    word "ubuntu", a common login: so the login is given here and not taken from the host the
    test runs on (the second case is such a host)."""
    if login is not None:
        monkeypatch.setenv("USER", login)
        monkeypatch.setenv("USERNAME", login)
    r = aws._sourced("red", env={"USER": "tester", "USERNAME": "tester"}, stdin="\n".join(_FACT_LINES) + "\n")
    assert r.returncode == 0 and r.stdout.splitlines() == _FACT_LINES, (r.stdout, r.stderr)


@needs_bash
def test_red_masks_the_operators_own_login_wherever_it_stands_a_package_version_included():
    """What the case above keeps out of the way, pinned as it is: on an operator's machine whose
    login is "ubuntu" the transcript shows the package version with the word masked. A
    transcript is never data, and the README says so."""
    r = aws._sourced("red", env={"USER": "ubuntu", "USERNAME": "ubuntu"}, stdin="host fact: qemu_pkg=" + QEMU_PKG + "\n")
    assert r.returncode == 0 and r.stdout == "host fact: qemu_pkg=1:9.8.7+ds-0<local>1.23\n", (r.stdout, r.stderr)
    said = _between(_text(README), "## What `run setup` says about the host", "## What keeps identifiers out of the repo")
    said = re.sub(r"\s+", " ", said)
    assert "`red()` masks the operator's own login wherever it stands" in said and "package version" in said, \
        "the README does not say it where it says what `run setup` prints"


@needs_bash
def test_the_new_facts_come_through_a_capture_unchanged(tmp_path):
    """host-facts.txt is a text file: capture.py sends it through the redactor, and the fetch
    scans what comes back. The new lines hold no identity and must read the same afterwards."""
    rec, pub = aws._rec(tmp_path), tmp_path / "pub"
    facts = "\n".join(["== qemu package", "qemu_pkg=" + QEMU_PKG, "== qemu package expected (METAL_QEMU_PKG)",
                       "qemu_pkg_expected=" + OTHER_QEMU_PKG, "== tick handler (kallsyms)",
                       "tick_handler=tick_nohz_highres_handler", "== CONFIG_HZ", "config_hz=250",
                       "config_hz_source=/boot/config-" + KERNEL, "== panic", "cmdline_panic=-1", "kernel_panic=-1",
                       "== read under", "proc_root=/proc", "sys_root=/sys",
                       "== kvm counters (read before any check)", "kvm_counters=unreadable:exits,halt_poll_success_ns"])
    aws._write(rec / "host-facts.txt", facts)
    r = aws._capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (pub / "host-facts.txt").read_text(encoding="utf-8") == facts + "\n"
    lk = subprocess.run([aws.PY, aws.LEAKSCAN, str(pub)], capture_output=True, text=True)
    assert lk.returncode == 0, lk.stdout


# --------------------------------------------------------------------------
# the vsomeip build: Boost 1.74 as on the Orin, and a build sized to the host


def _someip_w(tmp_path, mem_kb, build_info=None):
    aws._inputs_env(tmp_path)
    g = tmp_path / "repo" / "orin-native" / "gpu-concurrency"
    s = tmp_path / "repo" / "orin-native" / "someip"
    for d in (g, s):
        d.mkdir(parents=True)
    for h in ("run-someip.sh", "run-someip0.sh"):
        aws._write(g / h, "exit 0")
    aws._write(s / "someip_vprobe.cpp", "// made up")
    aws._write(s / "build-vsomeip.sh",
               'printf \'%s\\n\' "JOBS=${JOBS:-unset}" "MEM_MAX=${MEM_MAX:-unset}" "PREFIX=$PREFIX" "SRC=$SRC" > "$W/build-env.txt"')
    stub = tmp_path / "stub"
    stub.mkdir()
    _stub(stub, "sudo", 'printf \'%s\\n\' "$*" >> "$STUB_DIR/sudo.log"\nexit 0')
    _stub(stub, "nproc", 'echo "${STUB_NPROC:-16}"')
    proc = tmp_path / "proc"
    if mem_kb is not None:
        aws._write(proc / "meminfo", "MemTotal:       %d kB\nMemFree:          123456 kB\nSwapTotal:             0 kB" % mem_kb)
    else:
        proc.mkdir()
    return stub, proc


def _someip(tmp_path, phase, mem_kb=32 * 1024 * 1024 - 400000, **env):
    stub, proc = _someip_w(tmp_path, mem_kb)
    e = {k: v for k, v in os.environ.items() if k not in SCRUB}
    e.update(W=_msys(tmp_path), HOME=_msys(tmp_path / "home"), STUB_DIR=_msys(stub), PROC_ROOT=_msys(proc),
             PATH=aws._path_with(stub))
    if phase == "harness":
        e["LADDER_ENV"] = "HARNESS=run-someip0.sh IMAGE=ifs-kick.bin"
    e.update({k: str(v) for k, v in env.items()})
    r = subprocess.run([BASH, REMOTE, phase], capture_output=True, text=True, timeout=120, env=e)
    sudo = (stub / "sudo.log").read_text().splitlines() if (stub / "sudo.log").exists() else []
    built = dict(ln.split("=", 1) for ln in (tmp_path / "build-env.txt").read_text().splitlines()) \
        if (tmp_path / "build-env.txt").exists() else None
    return r, sudo, built


@needs_bash
@pytest.mark.parametrize("phase", ["someip", "harness"])
def test_the_vsomeip_build_gets_the_versioned_boost_packages_as_the_orin_has_them(tmp_path, phase):
    """Boost 1.74 is the Boost behind every held SOME/IP record, and on Ubuntu 24.04 the plain
    -dev names are a later Boost. The four names are the Orin's provisioning script's own."""
    r, sudo, built = _someip(tmp_path, phase)
    out = r.stdout + r.stderr
    install = [ln.split() for ln in sudo if " apt-get install " in " " + ln + " "]
    assert len(install) == 1, (sudo, out)
    pkgs = [w for w in install[0][install[0].index("install") + 1:] if not w.startswith("-")]
    m = re.search(r'^PKGS_someip="([^"]+)"$', _text(PROVISION), re.M)
    assert m, "provision-orin-r39.sh no longer lists its someip family on one line"
    orin = m.group(1).split()
    assert orin == ["libboost1.74-dev", "libboost-system1.74-dev", "libboost-thread1.74-dev", "libboost-filesystem1.74-dev"]
    assert pkgs == ["build-essential", "cmake", "git"] + orin, pkgs
    assert not [p for p in pkgs if re.match(r"^libboost(-[a-z]+)*-dev$", p)], "an unversioned Boost -dev package is still asked for"
    # The line names packages a host may already have (git, and on the Orin all of them): none may
    # be moved to its candidate by being named, which is the Orin's provisioning rule too.
    assert "--no-upgrade" in install[0][:install[0].index("build-essential")], install[0]
    assert built is not None, "the build script was reached: " + out


@needs_bash
@pytest.mark.parametrize("mem_kb,nproc,jobs,mem", [
    (32 * 1024 * 1024 - 400000, 16, "7", "15G"),     # a host of a1.metal's shape
    (64 * 1024 * 1024, 4, "4", "32G"),               # never more jobs than cores
    (8 * 1024 * 1024 - 300000, 6, "1", "3G"),        # a host of the Orin's shape
    (4 * 1024 * 1024, 2, "1", "2G"),                 # the smallest host that gives one job its share
    (3 * 1024 * 1024, 2, "unset", "unset"),          # too small for that: the build script's own defaults
    (None, 16, "unset", "unset"),                    # memory unread: the same
])
def test_the_vsomeip_build_is_sized_to_the_host(tmp_path, mem_kb, nproc, jobs, mem):
    """build-vsomeip.sh runs its build under a memory cap (MEM_MAX), by default the one its two
    jobs on the Orin run under. This phase used to ask for one job a core, which on a sixteen-core
    host is sixteen compilers under that cap. Both are now sized to the host at the Orin's ratio:
    the cap is half the host's memory in whole GiB, and one job goes with every 2 GiB of it, never
    more than one a core. A host that cannot give one job that share is not sized at all."""
    r, _sudo, built = _someip(tmp_path, "someip", mem_kb=mem_kb, STUB_NPROC=nproc)
    assert built is not None, r.stdout + r.stderr
    assert (built["JOBS"], built["MEM_MAX"]) == (jobs, mem), built
    assert built["PREFIX"] == _msys(tmp_path) + "/vsomeip/3.4.10" and built["SRC"] == _msys(tmp_path) + "/vsomeip/src-3.4.10"
    said = [ln for ln in r.stdout.splitlines() if "vsomeip build:" in ln]
    assert len(said) == 1 and (("JOBS=%s MEM_MAX=%s" % (jobs, mem)) in said[0] or (jobs == "unset" and "own defaults" in said[0])), \
        r.stdout
    # The size is read from $PROC_ROOT/meminfo: a faked one is announced here as in setup, so a
    # build sized to a made-up host cannot pass for one sized to this host.
    warned = [i for i, ln in enumerate(r.stdout.splitlines()) if "WARNING: PROC_ROOT overridden to " + _msys(tmp_path / "proc") in ln]
    assert len(warned) == 1 and warned[0] < r.stdout.splitlines().index(said[0]), r.stdout


def test_the_capture_comment_names_the_package_version_user_empty_protects():
    """USER is emptied for the capture because the login, "ubuntu", stands inside the QEMU
    package's version. The comment said so with the 22.04 package's string alone."""
    text = _text(REMOTE)
    at = text.index("USER= python3")
    comment = text[text.rindex("\n\t# USER empty", 0, at):at]
    assert "0ubuntu" in comment and "24.04" in comment, comment


# --------------------------------------------------------------------------
# redact-aws.sh: a digit run whose length is a multiple of 12 (found 2026-10-04)

# A reply frame as hex text (64 bytes as 128 hex characters, zero-padded), with made-up values. Its
# trailing digit run is 84 characters long, seven times twelve.
_FRAME = "0700000000000000" "4a1b2c3d" "af000000" "1f0168ea684d" + "0" * 36 + "04" + "0" * 46
_AWKS = ["awk"] + (["mawk"] if shutil.which("mawk") else [])   # Ubuntu's awk on the instance is mawk


def _frame(run):
    """A 128-hex frame whose trailing digit run is `run` characters long, with a letter before it."""
    return (_FRAME[:44] + "c" * 84)[:128 - run] + "0" * run


def _redacted(text, awk):
    r = subprocess.run([BASH, REDACT], input=text.encode(), capture_output=True, timeout=60,
                       env=dict(os.environ, USER="", AWK=awk, PATH=aws._path_with()))
    assert r.returncode == 0, r.stderr
    return r.stdout.decode()


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
@pytest.mark.parametrize("line,want", [
    ("x" + "0" * 24, None),                          # None: the line comes back as it went in
    ("n 123456789012123456789012,", None),
    ("n " + "123456789012" * 3, None),
    ('{"frame":"%s","reason":0}' % _FRAME, None),
    (_frame(24), None),
    (_frame(36), None),
    ("x" + "0" * 25, None),
    ("iam user 123456789012 here", "iam user <account> here"),
    ("the account is 111122223333.", "the account is <account>."),
    ("123456789012 111122223333", "<account> <account>"),
    ("x" + "0" * 24 + " then 111122223333", "x" + "0" * 24 + " then <account>"),
    ("on i-0123456789abcdef0,i-0123456789abcdef0", "on <instance-id>,<instance-id>"),
], ids=["24-digits", "24-digits-comma", "36-digits-eol", "frame-in-json", "frame-run-24", "frame-run-36", "25-digits",
        "id-in-words", "id-then-period", "two-ids", "run-then-id", "two-instance-ids"])
def test_the_redactor_keeps_a_digit_run_whose_length_is_a_multiple_of_12_and_still_masks_an_id(awk, line, want):
    """mask() read the character before a match as "" whenever the match began at the head of what was
    left, so after a kept 12-digit match the next 12 digits of the same run were masked when the run then ended:
    x and 24 zeros came back as x, 12 zeros and <account>. Both directions, under every awk here."""
    assert _redacted(line + "\n", awk) == (line if want is None else want) + "\n"


@needs_bash
def test_the_redactors_selftest_pins_the_run_and_fails_on_the_rule_as_it_was(tmp_path):
    """The capture phase runs the selftest before it redacts anything, on the instance's own awk:
    it is the check that stands between a broken redactor and a record. So it has to bite: on a
    copy whose mask() reads the character before a match the old way, it must fail, and name
    the run."""
    r = subprocess.run([BASH, REDACT, "selftest"], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, PATH=aws._path_with()))
    assert r.returncode == 0 and "PASS -- both directions" in r.stdout, r.stdout + r.stderr
    assert "preserved direction, a digit run a multiple of 12 long:" in r.stdout
    assert "masked direction, after a kept run:" in r.stdout
    now = "before = (pos > 1) ? substr(rest, pos - 1, 1) : prev"
    was = 'before = (pos > 1) ? substr(rest, pos - 1, 1) : ""'
    src = _text(REDACT)
    assert src.count(now) == 1, "mask() no longer reads the character before a match in the form this test reverts"
    old = tmp_path / "redact-aws.sh"
    aws._write(old, src.replace(now, was), newline=False)
    r = subprocess.run([BASH, _msys(old), "selftest"], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, PATH=aws._path_with()))
    assert r.returncode != 0 and "SELFTEST FAILED" in r.stdout, r.stdout + r.stderr
    for label in ("24 digits", "24 digits, comma", "36 digits, EOL", "reply frame"):
        assert "FAIL [%s] dropped" % label in r.stdout, r.stdout
    assert "LEAKED" not in r.stdout, "the old rule masked too much; it leaked nothing"


# --------------------------------------------------------------------------
# redact-aws.sh: IPv6 (2026-10-08)

# Documentation addresses (RFC 3849's prefix), link-local ones and made-up words. None is a host's.
_V6_MASKED = [
    ("inet6 fe80::1%ens5 scope link", "inet6 <ipv6>%ens5 scope link"),
    ("ssh to [2001:db8::1]:22 now", "ssh to [<ipv6>]:22 now"),
    ("peer ::ffff:203.0.113.7 said", "peer <ipv6><ip> said"),
    ("route 2001:db8:0:0:0:0:0:1 dev", "route <ipv6> dev"),
    ("a 2001:0db8:0000:0000:0000:0000:0000:0001 b", "a <ipv6> b"),
    ("ADDR FE80::ABCD:1 UP", "ADDR <ipv6> UP"),
    ("2001:db8::2", "<ipv6>"),
    ("src=2001:db8::2,dst=2001:db8::3;", "src=<ipv6>,dst=<ipv6>;"),
    ("listening on [::]:7100 and ::1", "listening on [<ipv6>]:7100 and <ipv6>"),   # the scan refuses these two as well
    # The scan's own limit, and so the redactor's: a scope whose two names are hex digits only
    # and that stands alone is an address by every rule here.
    ("ns a::b here", "ns <ipv6> here"),
]
# Masked by the redactor, and differently by the driver's red(), which keeps no address at all.
_V6_MASKED_REDACTOR_ONLY = [
    ("fe80::5054:ff:fe11:1111 then fe80::5054:ff:fe11:1112", "fe80::5054:ff:fe11:1111 then <ipv6>"),
]
_V6_KEPT = [
    "guest link fe80::5054:ff:fe11:1111/64 scope link",       # the guest's own, from its fixed MAC
    "guest link FE80::5054:FF:FE11:1111 up",
    "mac=52:54:00:11:11:11 set",                               # six pairs: a MAC, and the guest's
    "time 13:20:34 and 2026-10-08T13:20:34Z",
    "qemu 1:9.8.7+ds-0example1.23 installed",                  # a package version's epoch
    "  TRACE_DATE:: Sun Sep 27 08:20:16 2026 TRACE_CYCLES_PER_SEC:: 31250000",
    "in client_endpoint_impl::send, a lone request waits",
    "std::string and x_::1 and tcp::7100",                     # glued to a word: not an address
    "kvm:kvm_mmio and sched:sched_switch fired",
    "ratio 1:2:3 and 12:34:56:78 and 1:2:3:4:5",               # no :: and under five colons
    "sum ab12cd34ef:1:2 of 12345:6:7:8:9:a",                   # a group of five hex digits
    "nine 1:2:3:4:5:6:7:8:9 groups",
]


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
@pytest.mark.parametrize("line,want", _V6_MASKED + _V6_MASKED_REDACTOR_ONLY + [(k, k) for k in _V6_KEPT])
def test_the_redactor_masks_an_ipv6_address_and_keeps_what_only_looks_like_one(awk, line, want):
    """The redactor masked IPv4 only. An instance's own IPv6 address in a text file of the record
    (a link-local one in an error line is enough) went into pub.tgz, and the scan after the fetch
    then refused the whole capture: nothing leaked, but the session's capture was not clean.
    Masked by the scan's own rule; what the scan lets through, the redactor leaves alone."""
    assert _redacted(line + "\n", awk) == want + "\n"


def _scan_ipv6(tmp_path, lines):
    """Which of `lines` leakscan.py refuses as holding an IPv6 address: one file a line, one run."""
    d = tmp_path / "scan"
    for i, ln in enumerate(lines):
        aws._write(d / ("%03d.log" % i), ln)
    r = subprocess.run([aws.PY, aws.LEAKSCAN, str(d)], capture_output=True, text=True)
    hit = {int(m.group(1)) for m in re.finditer(r"^LEAK (\d+)\.log: ipv6 ", r.stdout, re.M)}
    return [i in hit for i in range(len(lines))]


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
def test_the_redactors_ipv6_rule_is_the_scans(tmp_path, awk):
    """Held in step with leakscan.py, both ways, over every line above: the redactor writes
    <ipv6> into a line exactly when the scan would refuse that line for an IPv6 address, and the
    scan finds none in anything the redactor has been through."""
    lines = [ln for ln, _ in _V6_MASKED + _V6_MASKED_REDACTOR_ONLY] + _V6_KEPT
    out = _redacted("\n".join(lines) + "\n", awk).splitlines()
    assert len(out) == len(lines)
    refused = _scan_ipv6(tmp_path / "before", lines)
    assert refused == [ln in dict(_V6_MASKED + _V6_MASKED_REDACTOR_ONLY) for ln in lines], \
        "the scan and this test's two lists disagree: " + repr([ln for ln, r in zip(lines, refused) if r])
    assert ["<ipv6>" in o for o in out] == refused
    assert not any(_scan_ipv6(tmp_path / "after", out)), out


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
@pytest.mark.parametrize("line,want", _V6_MASKED)
def test_red_and_the_redactor_agree_on_an_ipv6_address(awk, line, want):
    r = aws._sourced("red", env={"USER": "tester", "USERNAME": "tester"}, stdin=line + "\n")
    assert r.returncode == 0 and r.stdout == want + "\n" == _redacted(line + "\n", awk), (r.stdout, line)


@needs_bash
@pytest.mark.parametrize("line,red_says", [
    ("guest link fe80::5054:ff:fe11:1111/64 scope link", "guest link <ipv6>/64 scope link"),
    ("in client_endpoint_impl::send, a lone request waits", "in client_endpoint_impl<ipv6>send, a lone request waits"),
])
def test_red_masks_more_ipv6_shapes_than_the_redactor_which_handles_data(line, red_says):
    """The redactor's output is a record: it keeps the guest's own address and a C++ scope. red()'s
    is a transcript, never data, and masks both."""
    r = aws._sourced("red", env={"USER": "tester", "USERNAME": "tester"}, stdin=line + "\n")
    assert r.returncode == 0 and r.stdout == red_says + "\n", (r.stdout, r.stderr)
    assert _redacted(line + "\n", "awk") == line + "\n"


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
@pytest.mark.parametrize("path", [REMOTE, CAPTURE])
def test_the_instance_side_scripts_come_through_the_redactor_as_they_are(awk, path):
    """setup copies remote-ladder.sh and capture.py into the record's tooling/, and the capture
    publishes them through the redactor beside the hashes they were uploaded under. A comment in
    either that the redactor rewrote (an address written out as an example would do it) would
    publish a copy that no longer has its hash."""
    text = _text(path)
    assert _redacted(text, awk) == text


def test_the_redactors_selftest_pins_the_ipv6_rule_and_its_comments_name_no_host_as_it_no_longer_is():
    text = _text(REDACT)
    for label in ("link-local v6", "bracketed v6", "mapped v6", "guest link-local", "clock time", "c++ scope"):
        assert re.search(r'^\tcheck "%s"' % re.escape(label), text, re.M), "the selftest has no %r line" % label
    # The capture phase runs the selftest under the login "ubuntu", which the redactor masks: a
    # line that must be kept may not hold the word.
    kept = [ln for ln in text.splitlines() if re.match(r'^\tcheck "', ln) and ln.rstrip().endswith(" 1")]
    assert kept and not [ln for ln in kept if "ubuntu" in ln], "a kept selftest line holds the instance's login"
    note = _between(text, "# NO {n} INTERVALS EITHER.", "set -euo pipefail")
    assert "Ubuntu 22.04's default awk on the\n# Orin and on a stock a1.metal, does not" not in note, \
        "the note still names the two hosts as running the release they have left"
    assert "22.04" in note and "at the time" in note, note


def test_the_remote_ladders_header_lists_setups_steps_in_the_order_it_takes_them():
    """The one-line summary at the top: the host's facts come first, not last, and the
    METAL_QEMU_PKG refusal is among the steps."""
    header = _text(REMOTE).split("\nset -euo pipefail")[0]
    entry = re.sub(r"\s*\n#\s+", " ", _between(header, "#   setup ", "#   quiesce "))
    steps = [s.strip() for s in entry.split("setup", 1)[1].split(",")]
    assert steps[0].startswith("host facts"), steps
    assert [i for i, s in enumerate(steps) if "METAL_QEMU_PKG" in s] == [1], steps
    assert steps[-1].startswith("KVM counters readable"), steps
    assert "its last check is METAL_QEMU_PKG" not in re.sub(r"\s*\n#\s*", " ", header), "it is no longer the last"


def test_the_readme_says_which_names_setup_may_print_for_the_tick_handler():
    """"One of the three names or unknown" left a kernel with two of them out."""
    section = _between(_text(README), "## What `run setup` says about the host", "## What keeps identifiers out of the repo")
    said = re.sub(r"\s+", " ", section)
    assert "more than one" in said and "comma-separated" in said, section
    assert "kvm_counters" in said and "unreadable:" in said and "`unread`" in said, "the counters fact is not described"
    assert "last check" not in said, "METAL_QEMU_PKG is no longer setup's last check"
    keeps = re.sub(r"\s+", " ", _between(_text(README), "## What keeps identifiers out of the repo", "## What it does not do"))
    assert "IPv6" in keeps, "the README does not say what the redactor does with an IPv6 address"


# --------------------------------------------------------------------------
# red(): a 12-digit run inside a longer token (found 2026-10-04)

# red() and a sha256 that holds 12 digits in a row. upload prints inputs.txt through red(), and its
# 12-digit rule took any such run between a letter and a letter: about 1 sha256 in 35 printed with <account> in it.
_SHA12_MID = "ab123456789012cd" + "ef" * 24      # 64 hex characters, exactly 12 digits in a row, inside
_SHA12_HEAD = "123456789012" + "ab" * 26         # at the token's head
_SHA12_TAIL = "ab" * 26 + "123456789012"         # at its tail
_RED_KEPT = ["capture.py " + _SHA12_MID, "repo.tar " + _SHA12_HEAD, "disk " + _SHA12_TAIL,
             "ifs ifs-stamp.bin %s here" % _SHA12_TAIL, "build123456789012x"]
_RED_MASKED = [("iam user 123456789012 here", "iam user <account> here"),
               ("the account is 111122223333.", "the account is <account>."),
               ("owner=(444455556666),", "owner=(<account>),"),
               ("123456789012 111122223333", "<account> <account>"),
               ("file x %s then 111122223333" % _SHA12_MID, "file x %s then <account>" % _SHA12_MID)]
# red() masks more than the redactor at - and _: its output is a transcript, never data.
_RED_STRICTER = [("bucket-123456789012-us-east-1", "bucket-<account>-us-east-1"),
                 ("acct_123456789012_x", "acct_<account>_x")]


@needs_bash
@pytest.mark.parametrize("line,want", [(k, k) for k in _RED_KEPT] + _RED_MASKED + _RED_STRICTER)
def test_red_keeps_a_12_digit_run_inside_a_longer_token_and_masks_a_standalone_one(line, want):
    """A sha256 holding 12 digits in a row printed as ab<account>cd...; a run beside a letter or digit is part
    of a token and stays (want is the line itself), and a standalone run, one beside punctuation, - or _, is still
    masked."""
    r = aws._sourced("red", stdin=line + "\n")
    assert r.returncode == 0 and r.stdout == want + "\n", (r.stdout, r.stderr)


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
@pytest.mark.parametrize("line", _RED_KEPT + [m for m, _ in _RED_MASKED])
def test_red_and_the_redactor_agree_on_a_12_digit_run_inside_a_token_and_on_a_standalone_one(awk, line):
    """red() and redact-aws.sh keep the same 12-digit runs inside a token and mask the same standalone ones."""
    r = aws._sourced("red", stdin=line + "\n")
    assert r.returncode == 0 and r.stdout == _redacted(line + "\n", awk), (r.stdout, line)


# --------------------------------------------------------------------------
# The two self-termination nets (2026-10-10)
#
# A scheduled shutdown is a wall-clock time, and so is the deadline user-data writes to disk: a
# step of the instance's clock after they are set moves the time left by the size of the step.
# So user-data arms a monotonic timer first, schedules the wall-clock poweroff only after a
# bounded wait for the clock to be synchronised, and records what it read at each arming; `wait`
# proves both nets and prints the record before it decides.
#
# userdata.sh runs here for real, on a made-up instance: a `root` directory, a wall clock and an
# uptime kept in files, and a stub for every program the script runs. Its PATH holds the stub
# directory and NOTHING else, so no systemd-run, shutdown, timedatectl, systemctl or timeout of the
# machine the tests run on can be reached, whatever the script under test does; the tools it really
# needs (cat, chmod, head, mkdir, mv, touch) are wrappers in that directory. The script that runs
# is a copy whose absolute paths are made relative to the made-up root, and nothing else in it is
# changed. The stubs answer as the programs' documentation and source say they do (systemd 255,
# coreutils' timeout); none of it was run on an instance.


def _ud_const(name):
    m = re.search(r"^%s=(\S+)$" % name, _text(USERDATA), re.M)
    assert m, "userdata.sh no longer sets %s on a line of its own" % name
    return m.group(1)


NETS_MIN = int(_ud_const("MIN"))
NET = "qnx-metal-monotonic"
ARM_WALL = 1_790_000_000      # made up: the wall clock when user-data starts, in epoch seconds
ARM_UP = 41                   # made up: the uptime then, in seconds
_ROOTED = ("/var/lib/", "/proc/uptime", "/run/systemd/")
_REAL_TOOLS = ("cat", "chmod", "head", "mkdir", "mv", "touch")
_NET_COMMANDS = ("systemd-run", "shutdown", "systemctl", "timedatectl", "poweroff", "halt", "reboot")
SH = shutil.which("sh", path=aws._path_with()) or BASH      # dash on Ubuntu, as cloud-init runs the per-boot script
# Git Bash on NTFS has no execute bit: a file that starts with #! is executable there, whatever chmod said.
needs_mode_bits = pytest.mark.skipif(os.name == "nt", reason="no execute bit on this filesystem: a #! file is always -x here")

_ADVANCE = r'''advance() {   # $1 seconds: both clocks move
  local w u
  w=$(<"$WORLD/wall"); echo $((w + $1)) > "$WORLD/wall"
  if [ -e "$WORLD/root/proc/uptime" ]; then
    read -r u _ < "$WORLD/root/proc/uptime"
    echo "$(( ${u%%.*} + $1 )).00 0.00" > "$WORLD/root/proc/uptime"
  fi
}
'''
NET_STUBS = {
    "date": r'''[ "$*" = "+%s" ] || { echo "stub date: asked for '$*'" >&2; exit 2; }
echo "$(<"$WORLD/wall")"
''',
    # The first sleep also notes what was on disk when the wait began. A script that never stops
    # waiting is stopped here, long after any bound. STUB_UPTIME_JUMP_S: at the first sleep the
    # uptime alone moves by so many seconds more (an instance that stood still, or an uptime
    # that is wrong: neither is expected, both are what the two clamps on the minutes are for).
    "sleep": _ADVANCE + r'''n=$(( $(<"$WORLD/sleeps") + 1 )); echo "$n" > "$WORLD/sleeps"
if [ "$n" -gt 80 ]; then echo "$n" > "$WORLD/runaway"; kill -9 "$PPID"; exit 1; fi
if [ "$n" = 1 ]; then
  d=absent; [ -e "$WORLD/root/var/lib/qnx-metal-deadline" ] && d=$(<"$WORLD/root/var/lib/qnx-metal-deadline")
  p=no; [ -e "$WORLD/root/var/lib/cloud/scripts/per-boot/qnx-metal-deadline.sh" ] && p=yes
  s=no; [ -e "$WORLD/root/run/systemd/shutdown/scheduled" ] && s=yes
  printf 'deadline=%s\nperboot=%s\nscheduled=%s\n' "$d" "$p" "$s" > "$WORLD/at-first-sleep"
  if [ -n "${STUB_UPTIME_JUMP_S:-}" ]; then
    read -r u _ < "$WORLD/root/proc/uptime"
    echo "$(( ${u%%.*} + STUB_UPTIME_JUMP_S )).00 0.00" > "$WORLD/root/proc/uptime"
  fi
fi
case "$1" in ''|*[!0-9]*) echo "stub sleep: '$1'" >&2; exit 2 ;; esac
advance "$1"
''',
    # coreutils' timeout, as far as the scripts use it: whole seconds, then the command. A stub
    # cannot end a command that stands still, so it tells the command how long it has
    # (STUB_UNDER_TIMEOUT) and the stub command ends itself with timeout's own status, 124.
    "timeout": r'''case "${1:-}" in ''|*[!0-9]*) echo "stub timeout: duration '${1:-}'" >&2; exit 125 ;; esac
lim=$1; shift
STUB_UNDER_TIMEOUT=$lim exec "$@"
''',
    # STUB_SYNC_AFTER: how many reads say "no" before one says "yes"; "never"; "broken" (the
    # read fails); "hang" (the read never returns: under timeout it is cut at timeout's seconds,
    # without it the script stands there for good, which here ends the script and leaves a
    # mark); or "kill" (the instance dies at the first read, to show what is on disk then).
    # STUB_JUMP_AT, STUB_JUMP_S: at that read the wall clock is stepped by so many seconds, the
    # uptime is not. STUB_SLOW_S: every read takes that long, or timeout's seconds if shorter.
    "timedatectl": _ADVANCE + r'''case " $* " in *" show "*NTPSynchronized*) ;; *) echo "stub timedatectl: asked for '$*'" >&2; exit 2 ;; esac
n=$(( $(<"$WORLD/syncreads") + 1 )); echo "$n" > "$WORLD/syncreads"
lim="${STUB_UNDER_TIMEOUT:-}"
case "${STUB_SYNC_AFTER:-0}" in
  kill) echo "$n" > "$WORLD/killed"; kill -9 "$(<"$WORLD/pid")"; exit 1 ;;
  hang)
    if [ -z "$lim" ]; then echo "$n" > "$WORLD/hung"; kill -9 "$(<"$WORLD/pid")"; exit 1; fi
    advance "$lim"; exit 124 ;;
esac
if [ -n "${STUB_SLOW_S:-}" ]; then
  if [ -n "$lim" ] && [ "$STUB_SLOW_S" -gt "$lim" ]; then advance "$lim"; exit 124; fi
  advance "$STUB_SLOW_S"
fi
if [ "${STUB_JUMP_AT:-0}" = "$n" ]; then w=$(<"$WORLD/wall"); echo $((w + STUB_JUMP_S)) > "$WORLD/wall"; fi
v=no
case "${STUB_SYNC_AFTER:-0}" in
  broken) echo "Failed to query server: stub" >&2; exit 1 ;;
  never) ;;
  *) [ "$n" -le "$STUB_SYNC_AFTER" ] || v=yes ;;
esac
case " $* " in *" --value "*) echo "$v" ;; *) echo "NTPSynchronized=$v" ;; esac
''',
    # A transient timer: the stub keeps the time since boot at which it elapses, as systemd does
    # for either form, and refuses a unit name that is taken.
    "systemd-run": r'''[ "${STUB_SDRUN:-ok}" = ok ] || { echo "Failed to start transient timer unit: stub refuses" >&2; exit 1; }
unit="" at=""
for a in "$@"; do
  case "$a" in
    --unit=*) unit="${a#--unit=}" ;;
    --on-boot=*) at="${a#--on-boot=}" ;;
    --on-active=*) read -r u _ < "$WORLD/root/proc/uptime"; at=$(( ${u%%.*} + ${a#--on-active=} )) ;;
  esac
done
case "$at" in ''|*[!0-9]*) echo "stub systemd-run: no time in '$*'" >&2; exit 1 ;; esac
[ -n "$unit" ] || { echo "stub systemd-run: no unit in '$*'" >&2; exit 1; }
[ ! -e "$WORLD/timer-$unit" ] || { echo "Failed to start transient timer unit: Unit $unit.timer already exists." >&2; exit 1; }
echo "$at" > "$WORLD/timer-$unit"
''',
    # logind keeps ONE scheduled shutdown, as an absolute wall-clock time, in a file under /run:
    # a second schedule replaces the first. STUB_SHUTDOWN: refuse (every call), refuse-later
    # (every call but the first).
    "shutdown": r'''n=$(( $(<"$WORLD/shutdowns") + 1 )); echo "$n" > "$WORLD/shutdowns"
case "${STUB_SHUTDOWN:-ok}" in
  ok) ;;
  refuse-later) [ "$n" = 1 ] || { echo "Failed to schedule shutdown: stub refuses" >&2; exit 1; } ;;
  *) echo "Failed to schedule shutdown: stub refuses" >&2; exit 1 ;;
esac
[ "${1:-}" = -h ] || { echo "stub shutdown: asked for '$*'" >&2; exit 2; }
case "${2:-}" in
  now) echo now > "$WORLD/poweroff-now" ;;
  +*)
    m="${2#+}"
    case "$m" in ''|*[!0-9]*) echo "stub shutdown: time '$2'" >&2; exit 2 ;; esac
    w=$(<"$WORLD/wall")
    printf 'USEC=%s\nWARN_WALL=1\nMODE=poweroff\nUID=0\n' "$(( (w + m * 60) * 1000000 ))" > "$WORLD/root/run/systemd/shutdown/scheduled" ;;
  *) echo "stub shutdown: time '${2:-}'" >&2; exit 2 ;;
esac
''',
    # `systemctl show` of the timer unit: its state, and the time since boot at which it elapses
    # printed as systemd prints a time span.
    "systemctl": r'''span() {
  local s=$1 out=""
  [ "$s" -gt 0 ] || { echo 0; return; }
  [ $((s / 3600)) -eq 0 ] || out="$((s / 3600))h"
  [ $((s % 3600 / 60)) -eq 0 ] || out="${out:+$out }$((s % 3600 / 60))min"
  [ $((s % 60)) -eq 0 ] || out="${out:+$out }$((s % 60))s"
  echo "$out"
}
if [ "${1:-}" = show ]; then
  for unit; do :; done
  f="$WORLD/timer-${unit%.timer}"
  if [ -e "$f" ]; then echo "ActiveState=active"; echo "NextElapseUSecMonotonic=$(span "$(<"$f")")"
  else echo "ActiveState=inactive"; echo "NextElapseUSecMonotonic=0"; fi
fi
exit 0
''',
    "apt-get": '[ "${STUB_APT:-ok}" = ok ] || { echo "E: stub apt-get fails" >&2; exit 100; }\n',
    "usermod": "exit 0\n",
}


def _code(text):
    """The lines of a shell text that are not comments."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _rooted(text):
    """`text` with the absolute paths it reads and writes made relative to ./root; any other
    absolute path in its code would reach the machine the test runs on, and is refused."""
    for p in _ROOTED:
        text = text.replace(p, "root" + p)
    other = [m for m in re.findall(r"(?<![\w.}$!-])/[A-Za-z][\w./-]*", _code(text)) if m != "/dev/null"]
    assert not other, "an absolute path the made-up root does not hold: %s" % other
    return text


class World:
    """A made-up instance for user-data, its per-boot script and the read `wait` makes."""

    def __init__(self, tmp_path, sdrun="ok", shutdown="ok", sync_after="0", jump_at=0, jump_s=0, slow_s=None,
                 apt="ok", up=ARM_UP, wall=ARM_WALL, timeout="ok", uptime_jump_s=None):
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.root = tmp_path / "root"
        self.inst = self.root / "var" / "lib" / "cloud" / "instance"
        self.perboot_path = self.root / "var" / "lib" / "cloud" / "scripts" / "per-boot" / "qnx-metal-deadline.sh"
        self.bin.mkdir()
        self.inst.mkdir(parents=True)                       # cloud-init makes it before user-data runs
        (self.root / "run" / "systemd" / "shutdown").mkdir(parents=True)
        (self.root / "proc").mkdir()
        if up is not None:
            aws._write(self.root / "proc" / "uptime", "%d.00 0.00" % up)
        for name, value in (("wall", wall), ("sleeps", 0), ("syncreads", 0), ("shutdowns", 0)):
            aws._write(tmp_path / name, str(value))
        aws._write(tmp_path / "calls.log", "", newline=False)
        log = 'printf \'%%s\\n\' "%s $*" >> "$WORLD/calls.log"\n'
        for name, body in NET_STUBS.items():
            if (name == "systemd-run" and sdrun == "absent") or (name == "timeout" and timeout == "absent"):
                continue
            aws._write(self.bin / name, "#!/bin/bash\n" + log % name + body, newline=False)
            os.chmod(str(self.bin / name), 0o755)
        for name in _REAL_TOOLS:
            real = shutil.which(name, path=aws._path_with())
            assert real, "no %s on this machine for the stub directory" % name
            aws._write(self.bin / name, "#!/bin/bash\n" + log % name + 'exec "%s" "$@"\n' % _msys(real), newline=False)
            os.chmod(str(self.bin / name), 0o755)
        self.stub_env = {"STUB_SDRUN": "ok" if sdrun in ("ok", "absent") else sdrun, "STUB_SHUTDOWN": shutdown,
                         "STUB_SYNC_AFTER": sync_after, "STUB_JUMP_AT": str(jump_at), "STUB_JUMP_S": str(jump_s),
                         "STUB_APT": apt}
        if slow_s is not None:
            self.stub_env["STUB_SLOW_S"] = str(slow_s)
        if uptime_jump_s is not None:
            self.stub_env["STUB_UPTIME_JUMP_S"] = str(uptime_jump_s)

    def env(self, **over):
        e = {k: v for k, v in os.environ.items() if not k.startswith("STUB_")}
        # The stub directory and nothing else: the one thing that keeps a script under test away
        # from this machine's own shutdown, timer and clock commands.
        e.update(self.stub_env, PATH=str(self.bin), WORLD=_msys(self.tmp))
        e.update({k: str(v) for k, v in over.items()})
        assert os.pathsep not in e["PATH"]
        return e

    def _run(self, argv, **over):
        return subprocess.run(argv, cwd=str(self.tmp), capture_output=True, text=True, timeout=180, env=self.env(**over))

    def userdata(self):
        aws._write(self.tmp / "userdata.sh", _rooted(_text(USERDATA)), newline=False)
        # The script's own pid is noted first, and exec keeps it: the stubs that stand for an
        # instance that dies, or for a read that never returns, end the script by that pid.
        return self._run([BASH, "-c", 'echo $$ > "$WORLD/pid"; exec "$BASH" userdata.sh'])

    def perboot(self, **over):
        return self._run([SH, "root/var/lib/cloud/scripts/per-boot/qnx-metal-deadline.sh"], **over)

    def read(self):
        """The one command `wait` runs on the instance, run here on the made-up root."""
        r = aws._sourced('printf %s "$ARMING_READ"')
        assert r.returncode == 0 and r.stdout.strip(), "drive-metal.sh has no ARMING_READ: %s" % r.stderr
        assert "\n" not in r.stdout.strip(), "the read is one line: a multi-line argument may not survive every ssh"
        aws._write(self.tmp / "read.sh", _rooted(r.stdout), newline=True)
        return self._run([BASH, "read.sh"]).stdout

    # -- what is on the made-up instance
    def calls(self, *names):
        lines = [ln.rstrip() for ln in (self.tmp / "calls.log").read_text(encoding="utf-8").splitlines()]
        return [ln for ln in lines if not names or ln.split(" ", 1)[0] in names]

    def ran_away(self):
        """A wait that did not end: the stub sleep, or a read that never returned, stopped the script."""
        return (self.tmp / "runaway").exists() or (self.tmp / "hung").exists()

    def armed(self):
        p = self.inst / "SHUTDOWN_ARMED"
        return p.read_text(encoding="utf-8").split() if p.exists() else None

    def facts_lines(self):
        return (self.root / "var" / "lib" / "qnx-metal-arming").read_text(encoding="utf-8").splitlines()

    def facts(self):
        return dict(ln.split("=", 1) for ln in self.facts_lines())

    def deadline(self):
        return int((self.root / "var" / "lib" / "qnx-metal-deadline").read_text(encoding="utf-8").strip())

    def sched(self):
        p = self.root / "run" / "systemd" / "shutdown" / "scheduled"
        return dict(ln.split("=", 1) for ln in p.read_text(encoding="utf-8").splitlines()) if p.exists() else None

    def timer(self):
        p = self.tmp / ("timer-" + NET)
        return int(p.read_text(encoding="utf-8")) if p.exists() else None

    def first_sleep(self):
        return dict(ln.split("=", 1) for ln in (self.tmp / "at-first-sleep").read_text(encoding="utf-8").splitlines())

    # -- time passing, and a reboot
    def advance(self, seconds):
        wall = int((self.tmp / "wall").read_text(encoding="utf-8"))
        aws._write(self.tmp / "wall", str(wall + seconds))
        up = int((self.root / "proc" / "uptime").read_text(encoding="utf-8").split(".")[0])
        aws._write(self.root / "proc" / "uptime", "%d.00 0.00" % (up + seconds))

    def reboot(self, wall, up=23):
        """What a reboot empties: /run, with the pending shutdown, and the manager's transient units."""
        for p in (self.root / "run" / "systemd" / "shutdown" / "scheduled", self.tmp / ("timer-" + NET)):
            if p.exists():
                p.unlink()
        aws._write(self.tmp / "wall", str(wall))
        aws._write(self.root / "proc" / "uptime", "%d.00 0.00" % up)
        aws._write(self.tmp / "calls.log", "", newline=False)


def _wait_consts():
    return int(_ud_const("SYNC_WAIT_S")), int(_ud_const("SYNC_POLL_S"))


def _read_s():
    """The seconds user-data gives one read of the clock's state."""
    return int(_ud_const("SYNC_READ_S"))


def _left(spent_s):
    """Whole minutes of the session left once so many seconds of it are spent, rounded down."""
    return NETS_MIN - (spent_s + 59) // 60


def test_the_nets_constants_are_what_the_design_asks_for():
    """The session's minutes are the driver's; the wait for the clock is bounded by a named
    constant in tens of seconds; the unit, the facts file and the deadline have one name each in
    user-data, in the per-boot script it writes, and in the read `wait` makes."""
    body, driver = _text(USERDATA), _text(DRIVER)
    wait_s, poll_s = _wait_consts()
    assert 10 <= wait_s <= 90 and 1 <= poll_s <= 10 and poll_s < wait_s, (wait_s, poll_s)
    # One read of the clock's state is bounded too, by coreutils' timeout, in user-data and in
    # the driver's read: both ask systemd over a bus, and a bus that does not answer must hold
    # up neither the wall-clock schedule nor `wait`.
    assert 2 <= _read_s() <= 20 and _read_s() < wait_s
    assert _code(body).count('timeout "$SYNC_READ_S" timedatectl show -p NTPSynchronized') == 1
    assert "timedatectl" not in _code(body).replace('timeout "$SYNC_READ_S" timedatectl', ""), "no read of it without a bound"
    held = re.findall(r"; timeout (\d+) (?:systemctl show -p ActiveState -p NextElapseUSecMonotonic |timedatectl show -p NTPSynchronized;)", driver)
    assert len(held) == 2 and all(5 <= int(s) <= 60 for s in held), held          # 0 would be no bound at all
    assert len(re.findall(r"\b(?:systemctl|timedatectl) show\b", _code(driver))) == 2, "no read of either without a bound"
    assert _ud_const("NET") == NET and body.count("--unit=" + NET + " ") == 1, "the per-boot script arms the same unit"
    assert re.search(r"^MONO_UNIT=%s\.timer$" % re.escape(NET), driver, re.M), "and `wait` reads that unit"
    for name in ("FACTS", "DEADLINE"):
        path = _ud_const(name)
        assert path.startswith("/var/lib/qnx-metal-"), path
    assert re.search(r"; head -c \d+ %s'" % re.escape(_ud_const("FACTS")), driver), \
        "`wait` reads the file user-data writes, and no more of it than a record can be"
    assert body.count(_ud_const("DEADLINE")) >= 2, "the per-boot script reads the deadline user-data writes"
    assert _ud_const("PERBOOT") in driver
    # The window `wait` holds the wall-clock poweroff to, where it is computed and where it is said.
    d = re.search(r'SHUTDOWN_MIN_EXPECTED="\$\{SHUTDOWN_MIN_EXPECTED:-(\d+)\}"', driver)
    assert d and int(d.group(1)) == NETS_MIN
    assert '[ "$left" -gt $((SHUTDOWN_MIN_EXPECTED - 30)) ] && [ "$left" -le $((SHUTDOWN_MIN_EXPECTED + 1)) ]' in driver
    lo, hi = NETS_MIN - 29, NETS_MIN + 1
    assert "poweroff is %d-%d minutes ahead" % (lo, hi) in re.sub(r"\s*\n#\s*", " ", body), "user-data's header says another window"
    assert "a poweroff %d%s%d minutes ahead" % (lo, chr(0x2013), hi) in re.sub(r"\s+", " ", _text(README)), \
        "the README says another window"
    # Nothing that arms a net or records it runs under `set -e`: until there were two nets that
    # was one line, and the older test's "set -e after the first shutdown -h" covered it.
    code = _code(body).splitlines()
    assert code.count("set -e") == 1
    assert code.index("set -e") > max(i for i, ln in enumerate(code) if "systemd-run" in ln or "shutdown -h" in ln or '"$FACTS"' in ln), \
        "set -e must not stop a net, the wait, or the record"
    # User-data is sent whole in the launch call, which takes 16 KiB of it and no more.
    assert len(body.encode("utf-8")) < 16384 and body.isascii()


def test_no_net_command_is_called_by_an_absolute_path_and_the_timer_is_not_an_on_active_one():
    """The stub directory can only stand in for the machine's own commands if the scripts find
    them through PATH. And the timer is --on-boot, a time since boot: systemd takes "now" as the
    base of an --on-active timer again when the manager re-reads its units (timer_coldplug, then
    the TIMER_ACTIVE case of timer_enter_waiting, in systemd 255's timer.c), so a daemon-reload,
    which a package's install script may run, would start that one counting afresh."""
    r = aws._sourced('printf %s "$ARMING_READ"') if BASH else None
    texts = [_text(USERDATA)] + ([r.stdout] if r is not None else [])
    for text in texts:
        code = _code(text)
        assert not re.search(r"/(%s)\b" % "|".join(_NET_COMMANDS), code.replace("/run/systemd/shutdown/", "")), text[:60]
    code = _code(_text(USERDATA))
    assert "--on-active" not in code and code.count("--on-boot=") == 2, "user-data's timer and the per-boot script's"


@needs_bash
@pytest.mark.parametrize("sync_after,sleeps,ended,said", [
    ("0", 0, "synchronised", ("yes", "yes")),        # synchronised when user-data starts
    ("3", 3, "synchronised", ("no", "yes")),         # after a few polls
    ("never", None, "bound", ("no", "no")),          # never: the bound ends the wait
    ("broken", None, "bound", ("unknown", "unknown")),   # the read itself fails: the bound again
])
def test_userdata_arms_the_monotonic_net_first_and_schedules_the_wall_clock_one_after_a_bounded_wait(
        tmp_path, sync_after, sleeps, ended, said):
    w = World(tmp_path, sync_after=sync_after)
    r = w.userdata()
    assert r.returncode == 0 and not w.ran_away(), r.stdout + r.stderr
    wait_s, poll_s = _wait_consts()
    n = -(-wait_s // poll_s) if sleeps is None else sleeps
    slept = n * poll_s
    calls = w.calls()
    # 1. The monotonic net is the first program user-data runs: a timer that elapses when the time
    #    since boot reaches the uptime at arming plus the session's minutes, and powers off.
    assert calls[0] == "systemd-run --quiet --unit=%s --on-boot=%d --timer-property=AccuracySec=1s systemctl poweroff" % (
        NET, ARM_UP + NETS_MIN * 60), calls[:4]
    assert w.calls("systemd-run") == calls[:1] and w.timer() == ARM_UP + NETS_MIN * 60
    # 2. The wait is bounded.
    assert w.calls("sleep") == ["sleep %d" % poll_s] * n and slept < wait_s + poll_s, w.calls("sleep")
    assert len(w.calls("timedatectl")) == n + 1, "one read at the arming, one after every sleep"
    assert w.calls("timeout") == ["timeout %d timedatectl show -p NTPSynchronized" % _read_s()] * (n + 1), "each read bounded"
    # 3. The wall-clock poweroff is scheduled once, after the wait, for what is left of the
    #    session; the deadline on disk is the same moment's.
    at = [i for i, c in enumerate(calls) if c.startswith("shutdown ")]
    assert len(at) == 1, w.calls("shutdown")
    assert at[0] > max(i for i, c in enumerate(calls) if c.split(" ", 1)[0] in ("sleep", "timedatectl"))
    left = _left(slept)
    assert calls[at[0]].startswith("shutdown -h +%d auto-terminate" % left), calls[at[0]]
    assert w.sched() == {"USEC": str((ARM_WALL + slept + left * 60) * 1_000_000), "WARN_WALL": "1", "MODE": "poweroff", "UID": "0"}
    assert w.deadline() == ARM_WALL + slept + left * 60
    assert [c.split(" ", 1)[0] for c in calls[at[0] + 1:at[0] + 2]] == ["mv"] and len(w.calls("mv")) == 1, \
        "the deadline is put in place whole (a new file, then mv), right after the schedule it belongs to"
    assert w.armed() == ["monotonic", "wall-clock"]
    # 4. The facts of both moments.
    assert w.facts_lines() == [
        "minutes=%d" % NETS_MIN, "arm_wall=%d" % ARM_WALL, "arm_uptime=%d" % ARM_UP, "arm_synced=" + said[0],
        "arm_net=monotonic", "sched_wall=%d" % (ARM_WALL + slept), "sched_uptime=%d" % (ARM_UP + slept),
        "sched_synced=" + said[1], "sync_wait=" + ended, "sync_wait_s=%d" % slept, "sched_left_min=%d" % left,
        "deadline=%d" % (ARM_WALL + slept + left * 60), "sched_net=wall-clock"]
    # 5. Nothing is installed before both nets are there, and readiness is still written last.
    assert min(i for i, c in enumerate(calls) if c.startswith("apt-get ")) > at[0]
    assert (w.inst / "PROVISIONED").exists() and not (w.inst / "PROVISION_FAILED").exists()
    assert os.access(str(w.perboot_path), os.X_OK)


@needs_bash
def test_the_reboot_safety_is_on_disk_before_the_wait_begins_and_no_wall_clock_schedule_is(tmp_path):
    """A reboot during the wait must be bounded too, so the deadline (as the first read gives it)
    and the per-boot script are written before it, as they always were at that point. The
    wall-clock poweroff is not scheduled until the wait is over: scheduled on a clock that is then
    stepped forward by more than the session, it would fire at once."""
    w = World(tmp_path, sync_after="2")
    r = w.userdata()
    assert r.returncode == 0, r.stdout + r.stderr
    assert w.first_sleep() == {"deadline": str(ARM_WALL + NETS_MIN * 60), "perboot": "yes", "scheduled": "no"}
    assert w.timer() is not None, "the monotonic net is what holds meanwhile"


@needs_bash
@pytest.mark.parametrize("sdrun,armed", [("ok", ["monotonic"]), ("refuses", ["wall-clock"])])
def test_an_instance_that_dies_at_the_first_read_of_the_clocks_state_has_its_reboot_safety_on_disk(tmp_path, sdrun, armed):
    """The first thing user-data asks of the system after the first net is whether the clock is
    synchronised: a bus call, which can stand still or go wrong as the lines before it cannot.
    So the deadline and the per-boot script are on disk before it, where they stood before there
    were two nets: an instance that dies there and comes up again is bounded by the remainder."""
    w = World(tmp_path, sdrun=sdrun, sync_after="kill")
    w.userdata()
    assert (w.tmp / "killed").read_text(encoding="utf-8").split() == ["1"], "the stub ended user-data at its first read"
    assert not (w.inst / "PROVISIONED").exists() and w.calls("sleep") == [] and w.calls("apt-get") == []
    assert w.armed() == armed
    assert w.deadline() == ARM_WALL + NETS_MIN * 60
    assert w.perboot_path.exists() and os.access(str(w.perboot_path), os.X_OK), "installed, and executable"
    assert w.perboot_path.read_text(encoding="utf-8").rstrip().endswith('re-armed after a reboot"'), "written whole"
    # ... and a reboot two minutes later arms both nets again for what is left.
    w.reboot(wall=ARM_WALL + 120)
    r = w.perboot()
    assert w.calls("shutdown") == ["shutdown -h +%d auto-terminate: session deadline, re-armed after a reboot" % (NETS_MIN - 2)], r.stderr
    assert w.timer() == (23 + (NETS_MIN - 2) * 60 if sdrun == "ok" else None)


@needs_bash
def test_a_read_of_the_clocks_state_that_never_returns_is_cut_at_its_bound_and_the_schedule_is_still_made(tmp_path):
    """The read asks systemd-timedated over a bus. One that never answers is cut by timeout at
    SYNC_READ_S, says "unknown", and the wait ends at its bound as it does for a clock that is
    never synchronised: the wall-clock poweroff is scheduled all the same."""
    wait_s, poll_s = _wait_consts()
    read_s = _read_s()
    w = World(tmp_path, sync_after="hang")
    r = w.userdata()
    assert r.returncode == 0 and not w.ran_away(), r.stdout + r.stderr
    n = len(w.calls("sleep"))
    spent = (n + 1) * read_s + n * poll_s
    assert spent - read_s - poll_s < wait_s <= spent < wait_s + read_s + poll_s, (n, spent)
    facts = w.facts()
    assert (facts["arm_synced"], facts["sched_synced"], facts["sync_wait"]) == ("unknown", "unknown", "bound")
    assert facts["sched_uptime"] == str(ARM_UP + spent)
    assert w.calls("shutdown") == ["shutdown -h +%d auto-terminate: A6 ladder session budget" % _left(spent)]
    assert w.armed() == ["monotonic", "wall-clock"] and (w.inst / "PROVISIONED").exists()


@needs_bash
def test_without_timeout_the_read_says_unknown_and_the_wait_still_ends_at_its_bound(tmp_path):
    """coreutils is on every image; were its timeout missing all the same, the read gives
    nothing, which is "unknown", and nothing else changes: both nets, the wait at its bound."""
    wait_s, poll_s = _wait_consts()
    w = World(tmp_path, timeout="absent")
    r = w.userdata()
    assert r.returncode == 0 and not w.ran_away(), r.stdout + r.stderr
    n = -(-wait_s // poll_s)
    assert w.calls("timedatectl") == [] and len(w.calls("sleep")) == n
    facts = w.facts()
    assert (facts["arm_synced"], facts["sched_synced"], facts["sync_wait"]) == ("unknown", "unknown", "bound")
    assert w.armed() == ["monotonic", "wall-clock"] and w.timer() == ARM_UP + NETS_MIN * 60 and w.sched() is not None


@needs_bash
@pytest.mark.parametrize("jump_s", [2000, -1500])
def test_a_wall_clock_that_jumps_between_the_arming_and_the_schedule(tmp_path, jump_s):
    """The clock is stepped when it is first synchronised, forward or backward. The schedule and
    the deadline come from the reads taken after the wait, so both are right by the stepped
    clock; the monotonic net was armed before the step and nothing touches it again."""
    _wait_s, poll_s = _wait_consts()
    w = World(tmp_path, sync_after="2", jump_at=3, jump_s=jump_s)      # the third read says yes, and steps
    r = w.userdata()
    assert r.returncode == 0 and not w.ran_away(), r.stdout + r.stderr
    slept = 2 * poll_s
    left = _left(slept)
    later = ARM_WALL + slept + jump_s
    assert w.calls("shutdown") == ["shutdown -h +%d auto-terminate: A6 ladder session budget" % left]
    assert w.sched()["USEC"] == str((later + left * 60) * 1_000_000), "the schedule is from the later read"
    assert w.deadline() == later + left * 60, "and so is the deadline on disk"
    assert w.deadline() != ARM_WALL + NETS_MIN * 60 and w.deadline() != ARM_WALL + left * 60, "not from the first"
    facts = w.facts()
    assert (facts["arm_wall"], facts["sched_wall"]) == (str(ARM_WALL), str(later))
    assert (facts["arm_uptime"], facts["sched_uptime"]) == (str(ARM_UP), str(ARM_UP + slept)), "the uptime did not jump"
    # The monotonic net: armed once, for the same time since boot, and never asked about again.
    assert w.timer() == ARM_UP + NETS_MIN * 60
    assert len(w.calls("systemd-run")) == 1 and w.calls("systemctl") == []
    assert not [c for c in w.calls("shutdown") if " -c" in c], "nothing is cancelled"


@needs_bash
@pytest.mark.parametrize("sdrun", ["absent", "refuses"])
def test_without_systemd_run_the_wall_clock_poweroff_is_scheduled_at_once_as_it_was(tmp_path, sdrun):
    """systemd-run missing, or refusing: the old first command runs at once, so the instance
    never has less of a net than it had before there were two. SHUTDOWN_ARMED says which net
    exists. After the wait the schedule is made again from the later reads: logind keeps one
    scheduled shutdown and a second replaces it, with no moment between them without one."""
    _wait_s, poll_s = _wait_consts()
    w = World(tmp_path, sdrun=sdrun, sync_after="2", jump_at=3, jump_s=2000)
    r = w.userdata()
    assert r.returncode == 0 and not w.ran_away(), r.stdout + r.stderr
    calls = w.calls()
    if sdrun == "refuses":
        assert calls[0].startswith("systemd-run ") and len(w.calls("systemd-run")) == 1
        calls = calls[1:]
    else:
        assert w.calls("systemd-run") == []
    assert calls[0] == "shutdown -h +%d auto-terminate: A6 ladder session budget" % NETS_MIN, calls[:3]
    assert w.first_sleep()["scheduled"] == "yes", "at once: there before the wait"
    assert w.timer() is None
    slept = 2 * poll_s
    left = _left(slept)
    later = ARM_WALL + slept + 2000
    assert w.calls("shutdown") == ["shutdown -h +%d auto-terminate: A6 ladder session budget" % m for m in (NETS_MIN, left)]
    assert w.sched()["USEC"] == str((later + left * 60) * 1_000_000) and w.deadline() == later + left * 60
    assert w.armed() == ["wall-clock"]
    facts = w.facts()
    assert (facts["arm_net"], facts["sched_net"]) == ("wall-clock", "wall-clock")
    assert (w.inst / "PROVISIONED").exists()


@needs_bash
@pytest.mark.parametrize("shutdown,armed,nets", [
    ("refuse", None, ("none", "failed")),                 # neither net: no SHUTDOWN_ARMED at all
    ("refuse-later", ["wall-clock"], ("wall-clock", "failed")),   # the second schedule refused: the first stands
])
def test_a_shutdown_that_refuses_is_said_and_never_recorded_as_a_net(tmp_path, shutdown, armed, nets):
    w = World(tmp_path, sdrun="refuses", shutdown=shutdown, sync_after="1")
    r = w.userdata()
    assert r.returncode == 0, r.stdout + r.stderr
    assert w.armed() == armed
    facts = w.facts()
    assert (facts["arm_net"], facts["sched_net"]) == nets
    if shutdown == "refuse-later":
        assert w.sched()["USEC"] == str((ARM_WALL + NETS_MIN * 60) * 1_000_000), "the schedule made at once is still the one"


@needs_bash
def test_a_refused_wall_clock_schedule_leaves_the_monotonic_net_and_says_so(tmp_path):
    w = World(tmp_path, shutdown="refuse")
    r = w.userdata()
    assert r.returncode == 0, r.stdout + r.stderr
    assert w.armed() == ["monotonic"] and w.sched() is None and w.timer() == ARM_UP + NETS_MIN * 60
    assert w.facts()["sched_net"] == "failed"


@needs_bash
def test_a_slow_read_of_the_clock_does_not_stretch_the_wait_past_its_bound(tmp_path):
    """The wait is bounded twice: by the seconds it has slept, and by the uptime it has spent.
    A read that takes long (a bus that is slow to answer, here just under the read's own bound)
    therefore costs one read past the bound, not one for every poll."""
    wait_s, poll_s = _wait_consts()
    slow = _read_s() - 2
    assert slow > poll_s
    w = World(tmp_path, sync_after="never", slow_s=slow)
    r = w.userdata()
    assert r.returncode == 0 and not w.ran_away(), r.stdout + r.stderr
    n = len(w.calls("sleep"))
    spent = (n + 1) * slow + n * poll_s
    assert spent - slow - poll_s < wait_s <= spent, "it stops at the first poll that finds the bound passed"
    assert n < -(-wait_s // poll_s), "far fewer polls than the count alone allows"
    facts = w.facts()
    assert (facts["sched_uptime"], facts["sync_wait"]) == (str(ARM_UP + spent), "bound")
    assert facts["sched_left_min"] == str(_left(spent)), "the minutes left are counted on the uptime, not on the sleeps"
    assert w.calls("shutdown") == ["shutdown -h +%d auto-terminate: A6 ladder session budget" % _left(spent)]


@needs_bash
def test_an_uptime_that_cannot_be_read_still_arms_both_nets(tmp_path):
    """Nothing before the first net may stop it. With no uptime the timer is set for the session's
    minutes since boot, which is earlier than asked and never later; the wait is bounded by its
    count, and the minutes left are counted on the seconds slept."""
    wait_s, poll_s = _wait_consts()
    w = World(tmp_path, up=None, sync_after="never")
    r = w.userdata()
    assert r.returncode == 0 and not w.ran_away(), r.stdout + r.stderr
    assert w.calls()[0].startswith("systemd-run ") and "--on-boot=%d " % (NETS_MIN * 60) in w.calls()[0]
    n = -(-wait_s // poll_s)
    assert len(w.calls("sleep")) == n
    facts = w.facts()
    assert (facts["arm_uptime"], facts["sched_uptime"]) == ("unread", "unread")
    assert facts["sched_left_min"] == str(_left(n * poll_s)) and w.armed() == ["monotonic", "wall-clock"]


@needs_bash
@pytest.mark.parametrize("world,minutes", [
    # The uptime says two hours went by in the wait: the session is spent, and the poweroff is
    # still a schedule shutdown takes (one minute), not a time in the past.
    ({"sync_after": "never", "uptime_jump_s": 7200}, 1),
    # The uptime says less than at the arming: never more than the session's minutes.
    ({"sync_after": "1", "up": 5000, "uptime_jump_s": -1200}, NETS_MIN),
])
def test_the_minutes_left_are_held_between_one_and_the_sessions_minutes(tmp_path, world, minutes):
    """Neither is expected of a kernel whose uptime is right; the two clamps are there so that an
    uptime that is wrong cannot make the wall-clock schedule one shutdown refuses, or a longer one
    than the session."""
    w = World(tmp_path, **world)
    r = w.userdata()
    assert r.returncode == 0 and not w.ran_away(), r.stdout + r.stderr
    assert w.calls("shutdown") == ["shutdown -h +%d auto-terminate: A6 ladder session budget" % minutes]
    facts = w.facts()
    assert (facts["sched_left_min"], facts["sched_net"]) == (str(minutes), "wall-clock")
    assert w.deadline() == int(facts["sched_wall"]) + minutes * 60 and w.armed() == ["monotonic", "wall-clock"]


@needs_bash
def test_a_failed_install_leaves_both_nets_and_the_facts(tmp_path):
    w = World(tmp_path, apt="fail")
    r = w.userdata()
    assert r.returncode != 0
    assert (w.inst / "PROVISION_FAILED").exists() and not (w.inst / "PROVISIONED").exists()
    assert w.armed() == ["monotonic", "wall-clock"] and w.sched() is not None and w.timer() is not None
    assert w.facts()["sched_net"] == "wall-clock"


# -- the per-boot script, after a reboot


def _rebooted(tmp_path, ahead_s, up=23, **world):
    """user-data has run; then a reboot, with the wall clock `ahead_s` short of the deadline."""
    w = World(tmp_path, **world)
    r = w.userdata()
    assert r.returncode == 0, r.stdout + r.stderr
    deadline = w.deadline()
    assert deadline == ARM_WALL + NETS_MIN * 60
    w.reboot(wall=deadline - ahead_s, up=up)
    return w


@needs_bash
@pytest.mark.parametrize("ahead_s,left,mono_min", [
    (40 * 60 + 10, 40, 40),                 # before the deadline: both nets for the remainder
    (60, 1, 1),
    (NETS_MIN * 60, NETS_MIN, NETS_MIN),
    # A wall clock that is behind at the reboot: the wall-clock time is the deadline as written,
    # which the clock reaches once it is set; the monotonic net is never armed for more than the
    # session's minutes, whatever the clock says.
    (300 * 60, 300, NETS_MIN),
])
def test_after_a_reboot_before_the_deadline_the_per_boot_script_arms_both_nets_again(tmp_path, ahead_s, left, mono_min):
    w = _rebooted(tmp_path, ahead_s)
    r = w.perboot()
    assert r.returncode == 0, r.stdout + r.stderr
    assert w.calls("systemd-run") == [
        "systemd-run --quiet --unit=%s --on-boot=%d --timer-property=AccuracySec=1s systemctl poweroff" % (NET, 23 + mono_min * 60)]
    assert w.calls("shutdown") == ["shutdown -h +%d auto-terminate: session deadline, re-armed after a reboot" % left]
    assert w.timer() == 23 + mono_min * 60 and not (w.tmp / "poweroff-now").exists()
    assert w.sched()["USEC"] == str((w.deadline() - ahead_s + left * 60) * 1_000_000)


@needs_bash
@pytest.mark.parametrize("ahead_s", [59, 0, -5, -4000])
def test_after_a_reboot_past_the_deadline_the_per_boot_script_powers_off_at_once(tmp_path, ahead_s):
    w = _rebooted(tmp_path, ahead_s)
    r = w.perboot()
    assert r.returncode == 0, r.stdout + r.stderr
    assert w.calls("shutdown") == ["shutdown -h now auto-terminate: session deadline passed"]
    assert (w.tmp / "poweroff-now").exists() and w.calls("systemd-run") == [] and w.sched() is None


_NO_NUMBER = ["", "soon", "17x", "-5", "09", "00", "01790005340", "9" * 26, "9223372036854775808", " 1790005340",
              "1790005340\n1790005341", "1790005340 1790005341"]


@needs_bash
@pytest.mark.parametrize("deadline", [None, *_NO_NUMBER], ids=["missing"] + [repr(d)[:16] for d in _NO_NUMBER])
def test_a_deadline_that_cannot_be_read_after_a_reboot_powers_off_at_once(tmp_path, deadline):
    """User-data writes the deadline before this script exists, so a deadline that is missing,
    empty or not a plain number of seconds was lost: the session's end is not known, and the
    instance powers off. A form the shell cannot count with (a leading zero is an octal number to
    it, and it stops at "09"; a number too long for it) never reaches its arithmetic, where it
    would stop the script with nothing armed. Another session's worth of minutes on every boot,
    which is what this script did for such a file at first, would not be a bound."""
    w = _rebooted(tmp_path, 40 * 60)
    p = w.root / "var" / "lib" / "qnx-metal-deadline"
    if deadline is None:
        p.unlink()
    else:
        aws._write(p, deadline)
    for boot in (1, 2):                              # and the same on any later boot
        r = w.perboot()
        assert (r.returncode, r.stderr) == (0, ""), r.stdout + r.stderr
        assert w.calls("shutdown") == ["shutdown -h now auto-terminate: no readable session deadline or clock"] * boot
    assert (w.tmp / "poweroff-now").exists() and w.calls("systemd-run") == [] and w.timer() is None and w.sched() is None


@needs_bash
@pytest.mark.parametrize("clock", ["", "soon", "09", "9" * 26])
def test_a_clock_that_cannot_be_read_after_a_reboot_powers_off_at_once(tmp_path, clock):
    """The remainder is the deadline less the clock. A clock that gives no plain number of
    seconds leaves it as unknown as a lost deadline does, and stops the shell's arithmetic the
    same way."""
    w = _rebooted(tmp_path, 40 * 60)
    aws._write(w.tmp / "wall", clock)
    r = w.perboot()
    assert (r.returncode, r.stderr) == (0, ""), r.stdout + r.stderr
    assert w.calls("shutdown") == ["shutdown -h now auto-terminate: no readable session deadline or clock"]
    assert w.calls("systemd-run") == [] and w.timer() is None and w.sched() is None


@needs_bash
@pytest.mark.parametrize("deadline", ["0", "9999999999"])
def test_the_per_boot_script_reads_any_plain_number_of_up_to_ten_digits_as_a_deadline(tmp_path, deadline):
    """The two ends of what counts as readable: "0" is a number (long past), and ten digits are
    epoch seconds for some centuries yet. The timer is still held to the session's minutes."""
    w = _rebooted(tmp_path, 40 * 60)
    now = int((w.tmp / "wall").read_text(encoding="utf-8"))
    aws._write(w.root / "var" / "lib" / "qnx-metal-deadline", deadline)
    r = w.perboot()
    assert (r.returncode, r.stderr) == (0, ""), r.stdout + r.stderr
    left = (int(deadline) - now) // 60
    if left <= 0:
        assert w.calls("shutdown") == ["shutdown -h now auto-terminate: session deadline passed"] and w.timer() is None
    else:
        assert left > 100 * NETS_MIN
        assert w.calls("shutdown") == ["shutdown -h +%d auto-terminate: session deadline, re-armed after a reboot" % left]
        assert w.timer() == 23 + NETS_MIN * 60


@needs_bash
def test_the_per_boot_script_still_schedules_the_poweroff_when_systemd_run_refuses(tmp_path):
    w = _rebooted(tmp_path, 40 * 60)
    r = w.perboot(STUB_SDRUN="refuses")
    assert len(w.calls("systemd-run")) == 1 and w.timer() is None
    assert w.calls("shutdown") == ["shutdown -h +40 auto-terminate: session deadline, re-armed after a reboot"], r.stderr


@needs_bash
def test_the_per_boot_script_is_a_plain_sh_script_that_carries_the_sessions_minutes(tmp_path):
    """cloud-init runs it by its first line, and /bin/sh on Ubuntu is dash. It cannot read
    user-data's variables after a reboot, so the session's minutes are written into it."""
    w = _rebooted(tmp_path, 40 * 60)
    lines = w.perboot_path.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["#!/bin/sh", "MAX=%d" % NETS_MIN], lines[:3]
    code = _code("\n".join(lines[1:]))
    for bashism in ("[[", "$(<", "local ", "function ", "=~", "${!"):
        assert bashism not in code, bashism


# -- the read `wait` makes, and what it does with it


@needs_bash
def test_what_wait_reads_on_an_instance_user_data_has_armed_proves_both_nets(tmp_path, rig):
    """user-data on the made-up instance, then the driver's own read on it, then `wait` on what
    the read gave: the three agree on names, paths and formats without an instance."""
    _wait_s, poll_s = _wait_consts()
    w = World(tmp_path / "instance", sync_after="3")
    r = w.userdata()
    assert r.returncode == 0, r.stdout + r.stderr
    w.advance(100)                                   # the install, and the operator's `wait`
    slept = 3 * poll_s
    out = w.read()
    lines = out.splitlines()
    for want in ("ARMED_FILE=yes", "PERBOOT=yes", "MODE=poweroff", "NOW=%d" % (ARM_WALL + slept + 100), "ActiveState=active",
                 "NextElapseUSecMonotonic=1h 30min 41s", "UPTIME=%d" % (ARM_UP + slept + 100), "NTPSynchronized=yes"):
        assert want in lines, (want, out)
    assert lines[lines.index("== arming facts") + 1:] == w.facts_lines()
    left = aws._sourced('shutdown_left_min "$PROOF"', env={"PROOF": out})
    assert left.stdout.split() == [str((_left(slept) * 60 - 100) // 60)], left.stdout + left.stderr
    mono = aws._sourced('mono_left_s "$PROOF"', env={"PROOF": out})
    assert mono.stdout.split() == [str(NETS_MIN * 60 - slept - 100)], mono.stdout + mono.stderr
    run, state, _ = rig
    aws._launched(state)
    aws._write(tmp_path / "answer.txt", out, newline=False)
    r, log = run("wait", STUB_IP="203.0.113.9", STUB_PROV="OK", STUB_SCHED_FILE=tmp_path / "answer.txt")
    assert r.returncode == 0 and "terminate-instances" not in log, r.stdout + r.stderr
    assert (state / "armed").exists() and "self-termination armed" in r.stdout


@needs_bash
def test_wait_refuses_an_instance_whose_systemd_run_refused_and_says_which_net_it_has(tmp_path, rig):
    w = World(tmp_path / "instance", sdrun="refuses")
    r = w.userdata()
    assert r.returncode == 0, r.stdout + r.stderr
    w.advance(100)
    out = w.read()
    assert "ActiveState=inactive" in out.splitlines()
    run, state, _ = rig
    aws._launched(state)
    aws._write(tmp_path / "answer.txt", out, newline=False)
    r, log = run("wait", STUB_IP="203.0.113.9", STUB_PROV="OK", STUB_SCHED_FILE=tmp_path / "answer.txt")
    lines, abort = _refused(r, log, state, "the monotonic timer is NOT armed")
    assert "  arm_net=wall-clock" in lines[:abort]


_ARM_FACTS = ["minutes=%d" % NETS_MIN, "arm_wall=%d" % ARM_WALL, "arm_uptime=%d" % ARM_UP, "arm_synced=no", "arm_net=monotonic",
              "sched_wall=%d" % (ARM_WALL + 9), "sched_uptime=%d" % (ARM_UP + 9), "sched_synced=yes", "sync_wait=synchronised",
              "sync_wait_s=9", "sched_left_min=%d" % (NETS_MIN - 1), "deadline=%d" % (ARM_WALL + 9 + (NETS_MIN - 1) * 60),
              "sched_net=wall-clock"]
_NOW_AFTER = 139        # made up: seconds from the arming to the operator's `wait`


def _span(seconds):
    """Whole seconds as systemd prints a time span: "1h 30min 41s"."""
    parts = [("%dh" % (seconds // 3600), seconds // 3600), ("%dmin" % (seconds % 3600 // 60), seconds % 3600 // 60),
             ("%ds" % (seconds % 60), seconds % 60)]
    return " ".join(text for text, n in parts if n) or "0"


def _proof(wall_min=NETS_MIN - 3, mode="poweroff", state="active", mono_at=ARM_UP + NETS_MIN * 60, mono=None,
           up=ARM_UP + _NOW_AFTER, armed=True, perboot=True, sched=True, synced="yes", facts=None, crlf=False, wall_shift=0,
           now_says=None):
    """What the instance answers to `wait`'s one read. By default both nets are right.
    wall_shift: how far the wall clock stands from where the uptime would put it.
    now_says: the text of the NOW line, where it is not the number the schedule is counted from."""
    now = ARM_WALL + _NOW_AFTER + wall_shift
    lines = (["ARMED_FILE=yes"] if armed else []) + (["PERBOOT=yes"] if perboot else [])
    if sched:
        lines += ["USEC=%d" % ((now + wall_min * 60) * 1_000_000), "WARN_WALL=1", "MODE=" + mode, "UID=0"]
    lines.append("NOW=%s" % (now if now_says is None else now_says))
    if state is not None:
        lines += ["NextElapseUSecMonotonic=" + (_span(mono_at) if mono is None else mono), "ActiveState=" + state]
    lines += ["UPTIME=" + ("" if up is None else str(up)), "NTPSynchronized=" + synced, "== arming facts"]
    lines += _ARM_FACTS if facts is None else facts
    return ("\r\n" if crlf else "\n").join(lines) + "\n"


def _wait(rig, tmp_path, text, **env):
    run, state, _ = rig
    aws._launched(state)
    e = dict(STUB_IP="203.0.113.9", STUB_PROV="OK")
    if text is not None:
        with open(str(tmp_path / "answer.txt"), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        e["STUB_SCHED_FILE"] = tmp_path / "answer.txt"
    e.update(env)
    r, log = run("wait", **e)
    return r, log, state


_SAID = "the arming, as the instance recorded it and as it reads now"


def _reads(rig):
    """How many times `wait` ran its one read on the instance (the stub ssh's log)."""
    log = rig[2] / "ssh.log"
    return len([ln for ln in log.read_text(encoding="utf-8").splitlines() if "shutdown/scheduled" in ln]) if log.exists() else 0


def _refused(r, log, state, why):
    """`wait` refused: the abort, the termination and its record are as they always were."""
    assert r.returncode == 1, r.stdout + r.stderr
    assert "terminate-instances" in log, log
    assert (state / "terminated").exists() and not (state / "armed").exists() and not (state / "ip").exists()
    lines = r.stdout.splitlines()
    abort = [i for i, ln in enumerate(lines) if "ABORT: " in ln]
    assert len(abort) == 1 and why in lines[abort[0]] and lines[abort[0]].endswith(" -- terminating"), r.stdout
    assert "FATAL: " in r.stderr and "(instance shutting-down)" in r.stderr, r.stderr
    return lines, abort[0]


@needs_bash
@pytest.mark.parametrize("over", [
    {},
    {"crlf": True},
    {"wall_min": NETS_MIN - 29}, {"wall_min": NETS_MIN + 1},                       # the wall-clock window's two ends
    {"mono_at": ARM_UP + _NOW_AFTER + NETS_MIN * 60},                              # the whole session left, to the second
    {"mono_at": ARM_UP + _NOW_AFTER + (NETS_MIN - 29) * 60},
    {"mono": "1h 30min 41.279004s"},                                               # as systemd prints a fraction
    {"synced": "no"},                                                              # said, not required
])
def test_wait_goes_on_when_both_nets_are_right_and_says_what_the_instance_recorded(rig, tmp_path, over):
    r, log, state = _wait(rig, tmp_path, _proof(**over))
    assert r.returncode == 0 and "terminate-instances" not in log, r.stdout + r.stderr
    assert (state / "armed").exists() and (state / "ip").read_text().strip() == "203.0.113.9"
    lines = r.stdout.splitlines()
    done = [i for i, ln in enumerate(lines) if "self-termination armed: " in ln]
    assert len(done) == 1 and "monotonic timer" in lines[done[0]] and "re-armed on any reboot" in lines[done[0]]
    for fact in _ARM_FACTS:
        assert "  " + fact in lines[:done[0]], (fact, r.stdout)
    elapse = over.get("mono") or _span(over.get("mono_at", ARM_UP + NETS_MIN * 60))
    assert "  now_monotonic_elapse=" + elapse.replace(" ", "_") in lines[:done[0]], "the timer's time, as systemd printed it"
    assert len([ln for ln in lines if _SAID in ln]) == 1 and _reads(rig) == 1, "one read, said once"
    # A clock the instance does not call synchronised is no refusal, but the operator is told
    # what it can still do to the session: said once, after the verdict.
    note = [i for i, ln in enumerate(lines) if "NOTE: " in ln and "does not call its clock synchronised" in ln]
    assert len(note) == (1 if over.get("synced") == "no" else 0) and all(i > done[0] for i in note), r.stdout


# What the record of the arming could say if it were another file, or a damaged one: lines that
# would prove both nets if `wait` took them for the instance's own answers. It reads the proof
# from what stands BEFORE the record, and from nothing else.
_VOUCHING = ["ARMED_FILE=yes", "PERBOOT=yes", "USEC=%d" % ((ARM_WALL + _NOW_AFTER + (NETS_MIN - 3) * 60) * 1_000_000),
             "MODE=poweroff", "ActiveState=active", "NextElapseUSecMonotonic=" + _span(ARM_UP + NETS_MIN * 60)]

# The lines of a passing answer that prove the nets, as it has them (the clock's NTPSynchronized
# line is a reading, not a proof, and is left out), and the timer unit's two among them. For an
# answer whose record holds a marker of its own: `wait` cuts at the FIRST "== arming facts" line
# and judges what stands before it, so a record that carries these lines and then a second marker
# is still only a record. Cut at the last marker instead, the same answer would pass.
_PROOF_LINES = [ln for ln in _proof().split("\n== arming facts\n")[0].splitlines() if not ln.startswith("NTPSynchronized=")]
_TIMER_LINES = [ln for ln in _PROOF_LINES if ln.startswith(("NextElapseUSecMonotonic=", "ActiveState="))]

_WAIT_REFUSALS = [
    # the monotonic net
    ("timer-missing", {"state": None}, "the monotonic timer is NOT armed"),
    ("timer-inactive", {"state": "inactive", "mono": "0"}, "the monotonic timer is NOT armed"),
    ("timer-failed", {"state": "failed"}, "the monotonic timer is NOT armed"),
    ("timer-no-time", {"mono": "infinity"}, "the monotonic timer is NOT armed"),
    ("timer-no-uptime", {"up": None}, "the monotonic timer is NOT armed"),
    ("timer-long", {"mono_at": ARM_UP + _NOW_AFTER + (NETS_MIN + 1) * 60}, "monotonic timer armed for %d min ahead" % (NETS_MIN + 1)),
    # One second more than the session: the same whole minutes as a timer that is right.
    ("timer-a-second-long", {"mono_at": ARM_UP + _NOW_AFTER + NETS_MIN * 60 + 1},
     "monotonic timer armed for %d min ahead, expected %d..%d and not a second more" % (NETS_MIN, NETS_MIN - 29, NETS_MIN)),
    ("timer-far", {"mono": "1d 1h 30min 41s"}, "monotonic timer armed for "),
    ("timer-short", {"mono_at": ARM_UP + _NOW_AFTER + (NETS_MIN - 30) * 60}, "monotonic timer armed for %d min ahead" % (NETS_MIN - 30)),
    ("timer-elapsed", {"mono_at": ARM_UP + 60}, "monotonic timer armed for "),
    # the wall-clock net, as before
    ("wall-short", {"wall_min": NETS_MIN - 30}, "shutdown armed for %d min ahead" % (NETS_MIN - 30)),
    ("wall-very-short", {"wall_min": 12}, "shutdown armed for 12 min ahead"),
    ("wall-long", {"wall_min": NETS_MIN + 2}, "shutdown armed for %d min ahead" % (NETS_MIN + 2)),
    ("wall-very-long", {"wall_min": 4 * NETS_MIN}, "shutdown armed for %d min ahead" % (4 * NETS_MIN)),
    ("wall-reboot", {"mode": "reboot"}, "the self-termination shutdown is NOT armed"),
    ("wall-none", {"sched": False}, "the self-termination shutdown is NOT armed"),
    ("no-armed-file", {"armed": False}, "the self-termination shutdown is NOT armed"),
    ("no-per-boot", {"perboot": False}, "the self-termination shutdown is NOT armed"),
    # the record cannot vouch for a net the instance's own answers do not show
    ("record-vouches-for-the-timer", {"state": None, "facts": _ARM_FACTS + _VOUCHING}, "the monotonic timer is NOT armed"),
    ("record-vouches-for-the-marks", {"armed": False, "perboot": False, "sched": False, "facts": _ARM_FACTS + _VOUCHING},
     "the self-termination shutdown is NOT armed"),
    ("record-vouches-for-the-schedule", {"sched": False, "facts": _ARM_FACTS + _VOUCHING}, "the self-termination shutdown is NOT armed"),
    # ... and not by holding a marker of its own: the first marker ends what `wait` judges. Before it
    # nothing proves (the NOW and UPTIME lines have no number), after it the record carries every
    # proving line of a passing answer and then a second marker.
    ("record-holds-a-marker-and-vouches", {"armed": False, "perboot": False, "sched": False, "state": None, "up": None, "now_says": "",
                                          "facts": _ARM_FACTS + _PROOF_LINES + ["== arming facts"]},
     "the self-termination shutdown is NOT armed"),
    # Only the timer unit's two lines stand after the first marker; the rest of the answer is right.
    ("record-holds-a-marker-and-vouches-for-the-timer", {"state": None, "facts": _ARM_FACTS + _TIMER_LINES + ["== arming facts"]},
     "the monotonic timer is NOT armed"),
]


@needs_bash
@pytest.mark.parametrize("case,over,why", _WAIT_REFUSALS, ids=[c[0] for c in _WAIT_REFUSALS])
def test_wait_refuses_unless_both_nets_are_right_and_prints_the_facts_before_it_aborts(rig, tmp_path, case, over, why):
    r, log, state = _wait(rig, tmp_path, _proof(**over))
    lines, abort = _refused(r, log, state, why)
    before = lines[:abort]
    for fact in _ARM_FACTS:
        assert "  " + fact in before, (fact, r.stdout)
    assert len([ln for ln in lines if _SAID in ln]) == 1 and _reads(rig) == 1, "one read of the instance, said once"
    now = dict(ln.strip().split("=", 1) for ln in before if ln.startswith("  now_"))
    assert now["now_wall"] == ("unread" if over.get("now_says") == "" else str(ARM_WALL + _NOW_AFTER)) and now["now_synced"] == "yes", now
    assert now["now_uptime"] == ("unread" if over.get("up", 0) is None else str(ARM_UP + _NOW_AFTER)), now
    # What the timer unit said, whether or not `wait` could use it: a refusal on a form this
    # script does not read shows the form.
    if over.get("state", "active") is None:
        assert (now["now_monotonic_state"], now["now_monotonic_elapse"]) == ("absent", "absent"), now
    else:
        elapse = over.get("mono") or _span(over.get("mono_at", ARM_UP + NETS_MIN * 60))
        assert (now["now_monotonic_state"], now["now_monotonic_elapse"]) == (over.get("state", "active"), elapse.replace(" ", "_")), now
    assert "203.0.113.9" not in r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("when,step", [("before", 2000), ("before", -1500), ("after", 2000), ("after", -1500)])
def test_the_facts_wait_prints_say_what_the_clock_did(rig, tmp_path, when, step):
    """The record is there so that a refusal explains itself: how much further the wall clock
    moved than the uptime between the arming and the schedule, and from the schedule to now. A
    step before the schedule leaves the window right, which is what the wait in user-data is
    for; a step after it moves the minutes left by its size, and `wait` refuses."""
    facts = list(_ARM_FACTS)
    wall_min = NETS_MIN - 3
    if when == "before":
        facts[facts.index("sched_wall=%d" % (ARM_WALL + 9))] = "sched_wall=%d" % (ARM_WALL + 9 + step)
    else:
        wall_min -= step // 60
    r, log, state = _wait(rig, tmp_path, _proof(wall_min=wall_min, facts=facts, wall_shift=step))
    if when == "before":
        assert r.returncode == 0 and "terminate-instances" not in log, r.stdout + r.stderr
        lines = r.stdout.splitlines()
    else:
        lines, abort = _refused(r, log, state, "shutdown armed for %d min ahead" % wall_min)
        lines = lines[:abort]
    said = dict(ln.strip().split("=", 1) for ln in lines if ln.startswith("  "))
    assert (said["step_arm_to_sched_s"], said["step_sched_to_now_s"]) == (
        (str(step), "0") if when == "before" else ("0", str(step))), said
    assert (said["now_wallclock_left_min"], said["now_monotonic_state"], said["now_monotonic_left_min"]) == (
        str(wall_min), "active", str((NETS_MIN * 60 - _NOW_AFTER) // 60)), said


@needs_bash
@pytest.mark.parametrize("prov,why", [("FAILED", "user-data failed (PROVISION_FAILED)"), ("PENDING", "not provisioned after 1s")])
def test_a_wait_that_stops_before_the_proof_still_reads_and_prints_the_facts(rig, tmp_path, prov, why):
    """A clock that is far off can fail the install itself. So the two refusals that come before
    the proof read the record too, with one more ssh call, before the same abort."""
    r, log, state = _wait(rig, tmp_path, _proof(), STUB_PROV=prov)
    lines, abort = _refused(r, log, state, why)
    for fact in _ARM_FACTS:
        assert "  " + fact in lines[:abort], (fact, r.stdout)
    assert len([ln for ln in lines if _SAID in ln]) == 1 and _reads(rig) == 1


def _facts_with(**over):
    """The record of a right arming, with some of its values replaced."""
    return ["%s=%s" % (k, over.get(k, v)) for k, v in (ln.split("=", 1) for ln in _ARM_FACTS)]


_NOTHING_ARMED = {"armed": False, "perboot": False, "sched": False, "state": None}
_LEADING_ZEROS = [
    # (case, the instance's answer, provisioning, why `wait` refuses)
    ("timer-gone-arm_uptime-08", {"state": None, "facts": _facts_with(arm_uptime="08")}, "OK", "the monotonic timer is NOT armed"),
    ("nothing-armed-sched_wall-019", dict(_NOTHING_ARMED, facts=_facts_with(sched_wall="019")), "OK",
     "the self-termination shutdown is NOT armed"),
    ("install-failed-arm_wall-08", {"facts": _facts_with(arm_wall="08")}, "FAILED", "user-data failed (PROVISION_FAILED)"),
    ("never-provisioned-arm_wall-08", {"facts": _facts_with(arm_wall="08")}, "PENDING", "not provisioned after 1s"),
    ("now-08", {"now_says": "08"}, "OK", "shutdown armed for "),
    ("uptime-08", {"up": "08"}, "OK", "monotonic timer armed for %d min ahead" % NETS_MIN),
]


@needs_bash
@pytest.mark.parametrize("case,over,prov,why", _LEADING_ZEROS, ids=[c[0] for c in _LEADING_ZEROS])
def test_a_number_the_shell_cannot_count_with_stops_neither_the_printing_nor_the_abort(rig, tmp_path, case, over, prov, why):
    """A number with a leading zero is an octal number to bash, and "08" is none: its arithmetic
    stops there, and what it stops is the whole command it is in, not a line of it. In `wait`
    that command was the driver itself, on its way to the abort: the instance was left running,
    unproven, with nothing said. user-data writes no such number, so it took a damaged record or
    a strange answer; `wait` reads every number of the instance in base ten, prints the record as
    it stands, and refuses as it does for any other."""
    r, log, state = _wait(rig, tmp_path, _proof(**over), STUB_PROV=prov)
    lines, abort = _refused(r, log, state, why)
    before = lines[:abort]
    for fact in over.get("facts", _ARM_FACTS):
        assert "  " + fact in before, (fact, r.stdout)
    said = dict(ln.strip().split("=", 1) for ln in before if ln.startswith("  "))
    assert re.match(r"^-?\d+$", said["step_arm_to_sched_s"]) and re.match(r"^-?\d+$", said["step_sched_to_now_s"]), said
    assert said["now_wall"] == ("8" if "now_says" in over else str(ARM_WALL + _NOW_AFTER)), said
    assert said["now_uptime"] == ("8" if over.get("up") == "08" else str(ARM_UP + _NOW_AFTER)), said
    assert "value too great" not in r.stdout + r.stderr


def _rig_env(rig, **over):
    """The environment the rig gives the driver, for a run that sources it first."""
    _run, state, stub = rig
    e = dict(AWS=str(stub / "aws"), STUB_DIR=str(stub), METAL_STATE=str(state), METAL_KEY_NAME="lab-key", METAL_SG_NAME="lab-sg",
             METAL_POLL_S="0", METAL_IP_WAIT_S="1", METAL_PROV_WAIT_S="1", METAL_CONFIRM_TRIES="2", METAL_READBACK_TRIES="5",
             PATH=aws._path_with(stub))
    e.update({k: str(v) for k, v in over.items()})
    return e


@needs_bash
@pytest.mark.parametrize("breaks", ["arming_num() { printf 08; }", "arming_say() { exit 7; }"])
def test_a_printing_of_the_facts_that_breaks_cannot_skip_the_abort(rig, tmp_path, breaks):
    """The printing stands between a refusal and its abort, so nothing that goes wrong in it may
    reach the abort: it runs in a subshell. Shown here with the driver sourced and one function of
    the printing replaced by one that breaks: a number bash's arithmetic stops on (which discards
    the command it is in, and without the subshell that is the driver), and an exit."""
    _run, state, stub = rig
    aws._launched(state)
    aws._write(tmp_path / "answer.txt", _proof(state=None), newline=False)
    r = aws._sourced(breaks + '; main wait', env=_rig_env(rig, STUB_IP="203.0.113.9", STUB_PROV="OK",
                                                         STUB_SCHED_FILE=tmp_path / "answer.txt"))
    log = (stub / "aws.log").read_text(encoding="utf-8")
    _refused(r, log, state, "the monotonic timer is NOT armed")


@needs_bash
@needs_mode_bits
def test_a_per_boot_script_that_is_not_executable_is_not_a_re_arm_and_wait_refuses(tmp_path, rig):
    """cloud-init runs the scripts of its per-boot directory that are executable and skips the
    others, so a script that is there and cannot be run re-arms nothing after a reboot. The
    driver's read asks for an executable one, and `wait` refuses an instance without it."""
    w = World(tmp_path / "instance")
    r = w.userdata()
    assert r.returncode == 0, r.stdout + r.stderr
    w.advance(100)
    assert "PERBOOT=yes" in w.read().splitlines()
    os.chmod(str(w.perboot_path), 0o644)
    out = w.read()
    assert "PERBOOT=yes" not in out.splitlines() and "ARMED_FILE=yes" in out.splitlines(), out
    aws._write(tmp_path / "answer.txt", out, newline=False)
    run, state, _ = rig
    aws._launched(state)
    r, log = run("wait", STUB_IP="203.0.113.9", STUB_PROV="OK", STUB_SCHED_FILE=tmp_path / "answer.txt")
    _refused(r, log, state, "the self-termination shutdown is NOT armed (or its per-boot re-arm is missing)")


@needs_bash
def test_a_wait_that_can_read_nothing_says_so_and_aborts_as_before(rig, tmp_path):
    r, log, state = _wait(rig, tmp_path, None)
    lines, abort = _refused(r, log, state, "the self-termination shutdown is NOT armed")
    assert any("nothing could be read from the instance" in ln for ln in lines[:abort]), r.stdout


@needs_bash
def test_a_refusal_whose_termination_cannot_be_confirmed_is_still_reported_not_recorded(rig, tmp_path):
    r, log, state = _wait(rig, tmp_path, _proof(state=None), STUB_TERM_FAIL=1)
    out = r.stdout + r.stderr
    assert r.returncode == 3 and "TERMINATE FAILED" in out and "was NOT proven" in out, out
    assert "terminate-instances" in log and not (state / "terminated").exists() and not (state / "armed").exists()
    assert r.stdout.index("  arm_wall=") < r.stdout.index("ABORT: ")


# The thirteen lines user-data writes into its record, in the order it writes them, each with the
# only forms its value can have. A number is of at most eleven digits: red() masks a run of
# exactly twelve as an account id, and epoch seconds have ten.
_FACT_FORMS = {
    "minutes": r"\d{1,11}", "arm_wall": r"\d{1,11}|unread", "arm_uptime": r"\d{1,11}|unread", "arm_synced": "yes|no|unknown",
    "arm_net": "monotonic|wall-clock|none", "sched_wall": r"\d{1,11}|unread", "sched_uptime": r"\d{1,11}|unread",
    "sched_synced": "yes|no|unknown", "sync_wait": "synchronised|bound", "sync_wait_s": r"\d{1,11}",
    "sched_left_min": r"\d{1,11}", "deadline": r"\d{1,11}", "sched_net": "wall-clock|failed",
}


@needs_bash
def test_only_the_records_own_lines_are_printed_and_they_pass_red_whole(tmp_path):
    """The record is thirteen lines, numbers and a few words, and that is all `wait` prints of it:
    a line with another key, or with a value its key cannot have, is counted, not shown. The
    shape of a line is not enough: a key name, a host name with hyphens for its dots, or a MAC
    written with hyphens has the shape of a fact. What is shown passes red() unchanged, so nothing
    of it is masked and nothing in it is an identifier."""
    shown = []
    for i, world in enumerate(({"sync_after": "never", "jump_at": 2, "jump_s": 2000}, {"sdrun": "refuses", "up": None},
                               {"shutdown": "refuse", "sync_after": "broken"}, {"sdrun": "refuses", "shutdown": "refuse"},
                               {"wall": ""})):                    # the last: a wall clock that gives nothing
        w = World(tmp_path / str(i), **world)
        assert w.userdata().returncode == 0
        assert [ln.split("=", 1)[0] for ln in w.facts_lines()] == list(_FACT_FORMS), "user-data writes these keys and no other"
        shown += w.facts_lines()
    assert all(re.fullmatch(_FACT_FORMS[k], v) for k, v in (ln.split("=", 1) for ln in shown)), shown
    for key, forms in _FACT_FORMS.items():          # every word a value can be was written by one of the four
        for word in [f for f in forms.split("|") if f.isalpha() or "-" in f]:
            assert "%s=%s" % (key, word) in shown, (key, word)
    junk = ["host=ip-10-0-0-5.eu-central-1.compute.internal", "seen at 203.0.113.7", "id i-0123456789abcdef0", "x=1 y=2", "A=1",
            # the shape of a fact, and not one of the record's keys
            "key=my-ssh-key-name", "note=build-box-of-the-owner", "mac=aa-bb-cc-dd-ee-ff", "where=203-0-113-7", "arm_host=build-box",
            # a key of the record, with a value it cannot have
            "arm_net=my-ssh-key-name", "sched_net=build-box-of-the-owner", "arm_synced=maybe", "sync_wait=wall-clock",
            "minutes=ninety", "minutes=unread", "arm_wall=123456789012", "deadline=-5", "arm_uptime=", "sched_uptime=soon",
            "sched_wall=my-ssh-key-name", "sync_wait_s=maybe", "sched_left_min=-1", "sched_synced=maybe",
            # a line of the record with something before it or after it
            "arm_net=monotonic-my-ssh-key-name", "xarm_net=monotonic", "minutes=90 build-box", " minutes=90"]
    env = {"USER": "tester", "USERNAME": "tester", "PROOF": _proof(facts=shown + junk)}
    r = aws._sourced('arming_say "$PROOF"', env=env)
    printed = [ln[2:] for ln in r.stdout.splitlines() if ln.startswith("  ")]
    assert r.returncode == 0 and printed[:len(shown)] == shown, (r.stdout, r.stderr)
    assert "now_monotonic_elapse=1h_30min_41s" in printed, "the one value with another shape: a time span, its spaces as _"
    rest = [ln for ln in printed if not ln.startswith("now_monotonic_elapse=")]
    assert not [ln for ln in rest if not re.match(r"^[a-z][a-z_]*=-?[a-z0-9-]+$", ln)], printed
    assert "%d line(s) of the record not shown" % len(junk) in r.stdout
    for leak in ("ip-10-0-0-5", "203.0.113.7", "i-0123456789abcdef0", "y=2", "my-ssh-key-name", "build-box", "aa-bb-cc", "203-0-113-7",
                 "maybe", "ninety", "123456789012"):
        assert leak not in r.stdout, leak
    through = aws._sourced("red", env=env, stdin=r.stdout)
    assert through.stdout == r.stdout, "red() changed a line of the facts"
    for ln in printed:
        assert not re.search(r"\d{12}|\d+\.\d+|:|/|[A-Z]", ln), ln
    # A timer time that is not a time span is not shown either, and a fraction passes red() too.
    for mono, want in (("1h 30min; id i-0123456789abcdef0", "unshown"), ("x" * 41, "unshown"), ("1h 30min 41.279004s", "1h_30min_41.279004s")):
        r = aws._sourced('arming_say "$PROOF"', env=dict(env, PROOF=_proof(mono=mono)))
        assert "  now_monotonic_elapse=" + want in r.stdout.splitlines(), (mono, r.stdout)
        assert aws._sourced("red", env=env, stdin=r.stdout).stdout == r.stdout
    # Nor is a word of the instance's other answers shown unless it is one the answer can be: the
    # unit's state is a state systemd gives a unit, the clock's a yes or a no said once.
    for over, want in (({"state": "my-ssh-key-name"}, "  now_monotonic_state=other"), ({"state": "activating"}, "  now_monotonic_state=activating"),
                       ({"synced": "yes\nNTPSynchronized=no"}, "  now_synced=unknown"), ({"synced": "maybe"}, "  now_synced=unknown")):
        r = aws._sourced('arming_say "$PROOF"', env=dict(env, PROOF=_proof(**over)))
        lines = r.stdout.splitlines()
        assert r.returncode == 0 and want in lines and "my-ssh-key-name" not in r.stdout, (over, r.stdout)
        assert all(ln.startswith(("  ", "[")) for ln in lines), lines


@needs_bash
@pytest.mark.parametrize("text,want", [
    ("arm_wall=1790000000", "1790000000"), ("x=1\narm_wall=5\ny=2", "5"),
    ("arm_wall=08", "8"), ("arm_wall=000", "0"), ("arm_wall=0000001790000000", ""),      # base ten; sixteen digits are no number of a record
    ("arm_wall=123456789012345", "123456789012345"), ("arm_wall=1234567890123456", ""),
    ("arm_wall=5\narm_wall=6", ""), ("arm_wall=-5", ""), ("arm_wall=5x", ""), ("arm_wall=", ""), ("arm_wallx=5", ""), ("", ""),
])
def test_arming_num_gives_a_number_bash_can_count_with_or_nothing(text, want):
    """Every number the printing counts with comes through arming_num: the key once, digits
    alone, fifteen at most, and printed in base ten, so that bash's arithmetic takes it as it is
    meant ("08" stops it, "010" would be eight)."""
    r = aws._sourced('v="$(arming_num "$TEXT" arm_wall)"; echo "[$v] $(( ${v:-0} + 1 ))"', env={"TEXT": text})
    assert (r.returncode, r.stderr) == (0, ""), r.stderr
    assert r.stdout.split() == ["[%s]" % want, str(int(want or 0) + 1)], r.stdout


@needs_bash
@pytest.mark.parametrize("text,want", [
    ("USEC={usec}\nMODE=poweroff\nNOW={now}", "90"),
    ("USEC=0{usec}\nMODE=poweroff\nNOW=00{now}", "90"),                          # base ten, whatever stands in front
    ("USEC={usec}\nMODE=poweroff\nNOW=08", str((1_790_000_000 + 90 * 60 - 8) // 60)),
    ("USEC={usec}\nUSEC={usec}\nMODE=poweroff\nNOW={now}", None),                # said twice: no schedule
    ("USEC={usec}\nMODE=poweroff\nNOW={now}\nNOW={now}", None),
])
def test_shutdown_left_min_counts_in_base_ten_and_takes_a_number_said_once(text, want):
    """The older test of this function (tests/test_aws_tooling.py) holds what it accepts. Here:
    its two numbers are read in base ten, so a leading zero neither stops bash's arithmetic nor
    makes an octal number of them, and a line that stands twice is no schedule to count with."""
    now = 1_790_000_000
    r = aws._sourced('if shutdown_left_min "$SCHED"; then echo rc=0; else echo rc=1; fi',
                     env={"SCHED": text.format(usec=(now + 90 * 60) * 1_000_000, now=now)})
    assert r.stderr == "", r.stderr
    assert r.stdout.split() == ([want, "rc=0"] if want is not None else ["rc=1"]), r.stdout


@needs_bash
def test_wait_reads_no_more_of_the_record_than_a_record_can_be(tmp_path):
    """Only user-data writes the record, and it is a few hundred bytes. The driver's read takes
    its first few kilobytes and no more, so whatever the file has become, the transcript and the
    time `wait` spends on it stay small."""
    m = re.search(r"; head -c (\d+) /var/lib/qnx-metal-arming'", _text(DRIVER))
    assert m, "the driver's read no longer bounds the record"
    limit = int(m.group(1))
    w = World(tmp_path)
    assert w.userdata().returncode == 0
    record = (w.root / "var" / "lib" / "qnx-metal-arming").read_bytes()
    assert 8 * len(record) <= limit <= 8192, (len(record), limit)
    assert w.read().split("== arming facts\n", 1)[1].splitlines() == w.facts_lines(), "a record as user-data writes it is read whole"
    aws._write(w.root / "var" / "lib" / "qnx-metal-arming", "minutes=1\n" * 60000, newline=False)
    out = w.read().split("== arming facts\n", 1)[1]
    assert len(out) == limit, len(out)
    r = aws._sourced('arming_say "$PROOF"', env={"PROOF": w.read()})
    assert r.returncode == 0 and len(r.stdout.splitlines()) < limit // len("minutes=1\n") + 20, len(r.stdout.splitlines())


@needs_bash
@pytest.mark.parametrize("span,want", [
    ("1h 30min 41.279004s", "5441"), ("1h 30min 41s", "5441"), ("1h 30min", "5400"), ("90min", "5400"), ("59.999999s", "59"),
    ("2min 500.123ms", "120"), ("250us", "0"), ("1d 2h", "93600"), ("1w", "604800"), ("1month 1s", "2629801"), ("1y", "31557600"),
    ("0", None), ("infinity", None), ("", None), ("1h foo", None), ("90", None), ("-5s", None), ("1h30min", None), ("1.5h", None),
    ("1h\n30min", None),                                        # one line: a time said twice is no time
])
def test_timespan_s_reads_a_time_span_as_systemctl_show_prints_one(span, want):
    """`systemctl show` prints a timer's next elapse as a time span (format_timespan in systemd's
    time-util.c): parts from years down to microseconds, a space between them, a fraction only
    on the last. Whole seconds are enough here; anything that is not such a span is no time."""
    r = aws._sourced('if timespan_s "${SPAN:-}"; then echo rc=0; else echo rc=1; fi', env={"SPAN": span})
    assert r.stderr == "", r.stderr
    assert r.stdout.split() == ([want, "rc=0"] if want is not None else ["rc=1"]), r.stdout


@needs_bash
def test_timespan_s_does_not_take_a_file_name_for_a_time(tmp_path):
    """The words of the span are split, never matched against the files of the directory the
    operator stands in: there a file called 89min would have turned "??min" into a time."""
    aws._write(tmp_path / "89min", "", newline=False)
    aws._write(tmp_path / "1h", "", newline=False)
    for span in ("??min", "*", "?h 89mi[n]"):
        r = aws._sourced('cd "$DIR" && if timespan_s "$SPAN"; then echo rc=0; else echo rc=1; fi',
                         env={"DIR": _msys(tmp_path), "SPAN": span})
        assert (r.stdout.split(), r.stderr) == (["rc=1"], ""), (span, r.stdout, r.stderr)


@needs_bash
@pytest.mark.parametrize("text,want", [
    ("ActiveState=active\nNextElapseUSecMonotonic=1h 30min 41s\nUPTIME=180", "5261"),
    ("NextElapseUSecMonotonic=1h 30min 41s\r\nActiveState=active\r\nUPTIME=180\r\n", "5261"),     # CRLF, another order
    ("ActiveState=active\nNextElapseUSecMonotonic=2min\nUPTIME=180", "-60"),                   # elapsed: said, then refused
    ("ActiveState=inactive\nNextElapseUSecMonotonic=1h 30min 41s\nUPTIME=180", None),
    ("ActiveState=active\nNextElapseUSecMonotonic=0\nUPTIME=180", None),
    ("ActiveState=active\nNextElapseUSecMonotonic=1h 30min 41s\nUPTIME=", None),
    ("ActiveState=active\nUPTIME=180", None),
    ("NextElapseUSecMonotonic=1h 30min 41s\nUPTIME=180", None),
    ("ActiveState=active\nNextElapseUSecMonotonic=30min\nNextElapseUSecMonotonic=45min\nUPTIME=180", None),   # said twice: no time
    ("ActiveState=active\nNextElapseUSecMonotonic=1h 30min 41s\nUPTIME=0180", "5261"),                         # base ten
    ("", None),
])
def test_mono_left_s_accepts_only_an_active_timer_with_a_time(text, want):
    r = aws._sourced('if mono_left_s "${PROOF:-}"; then echo rc=0; else echo rc=1; fi', env={"PROOF": text})
    assert r.stderr == "", r.stderr
    assert r.stdout.split() == ([want, "rc=0"] if want is not None else ["rc=1"]), r.stdout


def test_the_readme_says_the_two_nets_and_what_each_cannot_bound():
    import results_guard

    cost = _between(_text(README), "## What bounds the cost", "## What `run setup` says about the host")
    said = re.sub(r"\s+", " ", cost)
    for phrase in ("monotonic timer", "armed first", "no step of the wall clock", "`daemon-reload`", "does not survive a reboot",
                   "wall-clock poweroff", "is an absolute wall-clock time", "stepped after", "`systemd-run` is missing or refuses",
                   "scheduled at once", "re-arms both", "never for more than the session", "hangs without rebooting",
                   "runs no timer of either kind", "Nothing here watches the instance from outside the instance",
                   # what the two nets cannot bound across a reboot, and what a lost deadline does
                   "until a reboot the monotonic timer is the bound", "or cannot be read", "is itself a wall-clock time",
                   "at most the session's minutes again for each boot", "is not bounded in sum",
                   # and that none of it has run where it is meant to
                   "have not run on an instance"):
        assert phrase in said, phrase
    assert "61\u201391 minutes" in said, "the wall-clock window is still said, and still the driver's"
    table = [ln for ln in _text(README).splitlines() if ln.startswith("| `userdata.sh`")]
    assert len(table) == 1 and "both" in table[0], table
    # A sub-README is guarded text: the section gains no number with a unit.
    assert not [m.group(0) for ln in cost.splitlines() for m in results_guard.FIGURE.finditer(ln)]
