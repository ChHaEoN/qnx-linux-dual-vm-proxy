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
    a 12-digit run inside a longer token.

Nothing here contacts AWS or a board. `setup` runs for real, against stub id, ip, sudo, uname,
nproc, lsmod, dpkg-query, lscpu and qemu-system-aarch64 and a made-up /proc and /sys. Every
value is made up, in the shape a host gives it (a kernel release, a Debian package version, a
kallsyms line, a kernel command line); every identifier is a documentation value. The bash, the
path helper and the driver's rig are tests/test_aws_tooling.py's.

What these tests do NOT show: that the image launches, what its kernel calls the tick handler,
that its KVM counters read, that vsomeip builds there, or anything about a guest. Those are the
rehearsal session's to show.
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
