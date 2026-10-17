"""lib-measure.sh's setup-layout functions and read-backs (Phase 3b / A6, 2026-10-17), the pieces
run-randomise.sh and launch-qnx-kvm-bridged.sh build a launch from and read it back with:

  m_layout_cmd       the prefix of a fixed (env -i, setarch -R) or random (env -i, A6PAD) launch,
                     and the size of the environment it gives the program
  m_await_exec       a launch's exec chain has reached its program
  m_launch_readback  personality, environment size, startstack and first mappings, read as root
  m_qemu_threads     every QEMU thread's last CPU, allowed CPUs and name
  m_pin_by_name      QEMU's thread groups one per core, by thread name, read back
  m_qemu_identify    the running QEMU and its guest image, with nothing pinned

Every /proc file is faked under PROC_ROOT and every privileged tool is a stub first on PATH, except
where a test says it runs the real setarch (Linux only). Also the owner's D5 for the two files ported
from the local branch they were written on: no reference to that branch's plan in their headers.
"""
import os
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
LIB = os.path.join(GC, "lib-measure.sh")
BASH = shutil.which("bash")
sys.path.insert(0, GC)
import randomise_schedule as rs  # noqa: E402

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")
LINUX = sys.platform.startswith("linux")


def _posix(p):
    return os.path.abspath(str(p)).replace("\\", "/")


def _stub(path, body):
    with open(str(path), "w", newline="\n") as f:
        f.write("#!/usr/bin/env bash\n" + body + "\n")
    os.chmod(str(path), 0o755)


def _run(tmp_path, snippet, stubs=None, strict=False):
    """Source the library under nounset (or set -euo pipefail with strict) and run snippet, with
    a logging `sudo -n` stub, a python3 that is this interpreter and the given stubs first on PATH."""
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    _stub(b / "sudo", 'echo "sudo $*" >> "%s"\n[ "$1" = -n ] || exit 97\nshift\nexec "$@"' % _posix(log))
    _stub(b / "python3", 'exec "%s" "$@"' % _posix(sys.executable))
    for name, body in (stubs or {}).items():
        _stub(b / name, body)
    env = dict(os.environ)
    env["PATH"] = _posix(b) + os.pathsep + env.get("PATH", "")
    env["PROC_ROOT"] = _posix(tmp_path / "proc")
    script = textwrap.dedent("""
        set %s
        . "%s"
        %s
    """) % ("-euo pipefail" if strict else "-u", _posix(LIB), snippet)
    r = subprocess.run([BASH, "-c", script], env=env, capture_output=True, text=True, timeout=120)
    r.calls = log.read_text().splitlines() if log.exists() else []
    return r


def _lib_text():
    with open(LIB, encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ m_layout_cmd

def _layout(tmp_path, *args):
    return _run(tmp_path, 'm_layout_cmd %s; printf "%%s\\n" "${LAYOUT_CMD[@]}"; echo "BYTES=$LAYOUT_ENV_BYTES"'
                % " ".join(args))


def _arch():
    return subprocess.run([BASH, "-c", "uname -m"], capture_output=True, text=True).stdout.strip()


def test_the_fixed_list_is_the_schedules():
    m = re.search(r"^M_FIXED_ENV=\(([^)]*)\)$", _lib_text(), re.M)
    assert m, "lib-measure.sh sets M_FIXED_ENV on one line"
    assert tuple(m.group(1).split()) == rs.FIXED_ENV


def test_a_fixed_launch_is_env_i_with_the_fixed_list_then_setarch_r(tmp_path):
    r = _layout(tmp_path, "1", "-")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.split("\n")
    assert lines[:6] == ["env", "-i", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C", "setarch", _arch()]
    assert lines[6] == "-R" and lines[7] == "BYTES=%d" % rs.env_bytes(rs.launch_env(None))


def test_a_fixed_probe_launch_carries_hash_seed_zero_before_setarch(tmp_path):
    r = _layout(tmp_path, "1", "-", "0")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split("\n")[:8] == ["env", "-i", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C",
                                        "PYTHONHASHSEED=0", "setarch", _arch(), "-R"]
    assert "BYTES=%d" % rs.env_bytes(rs.launch_env(None, hashseed=0)) in r.stdout


def test_a_random_launch_has_the_pad_and_no_setarch(tmp_path):
    r = _layout(tmp_path, "0", "48", "123")
    assert r.returncode == 0, r.stderr
    lines = [x for x in r.stdout.split("\n") if x]
    assert lines == ["env", "-i", "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C", "PYTHONHASHSEED=123",
                     "A6PAD=" + "x" * 48, "BYTES=%d" % rs.env_bytes(rs.launch_env(48, hashseed=123))]


@pytest.mark.parametrize("args", [("1", "-"), ("1", "-", "0"), ("0", "0"), ("0", "16", "4294967295"),
                                  ("0", "4080"), ("0", "2048", "7")])
def test_the_environment_size_is_the_one_the_schedule_states(tmp_path, args):
    r = _layout(tmp_path, *args)
    assert r.returncode == 0, r.stderr
    pad = None if args[1] == "-" else int(args[1])
    hs = int(args[2]) if len(args) > 2 else None
    assert ("BYTES=%d" % rs.env_bytes(rs.launch_env(pad, hashseed=hs))) in r.stdout


@pytest.mark.parametrize("args,why", [
    (("1", "16"), "a fixed launch has no pad"),
    (("0", "-"), "a random launch has a pad"),
    (("0", "17"), "not on the pad grid"),
    (("0", "4096"), "not on the pad grid"),
    (("0", "-16"), "not on the pad grid"),
    (("2", "-"), "norand"),
    (("1", "-", "4294967296"), "hash seed"),
    (("1", "-", "x1"), "hash seed"),
    (("1",), "usage"),
    (("0", "00016"), "not on the pad grid"),
    (("1", "-", "-1"), "hash seed"),
    (("0", "x"), "not on the pad grid"),
    (("1", "-", "0", "9"), "usage"),
])
def test_a_launch_the_design_has_no_level_for_is_refused(tmp_path, args, why):
    r = _layout(tmp_path, *args)
    assert r.returncode != 0 and why in r.stderr, r.stdout + r.stderr


@pytest.mark.skipif(not LINUX or shutil.which("setarch") is None, reason="the real setarch, on Linux")
def test_the_real_prefix_gives_the_program_its_personality_and_exactly_that_environment(tmp_path):
    """No stub: env -i and setarch as the board runs them. cat is exec'd by the prefix, so its
    /proc/self is the launched program's."""
    for args, norand in ((("1", "-", "0"), True), (("0", "64", "99"), False)):
        snippet = ('m_layout_cmd %s; "${LAYOUT_CMD[@]}" cat /proc/self/personality; '
                   '"${LAYOUT_CMD[@]}" wc -c /proc/self/environ; echo "BYTES=$LAYOUT_ENV_BYTES"' % " ".join(args))
        r = _run(tmp_path, snippet)
        assert r.returncode == 0, r.stderr
        lines = r.stdout.split("\n")
        assert (int(lines[0], 16) & 0x0040000 != 0) is norand, lines[0]
        assert lines[1].split()[0] == lines[2].split("=")[1], r.stdout


# ------------------------------------------------------------------ m_await_exec

def _proc(tmp_path, pid, cmdline=None, personality=None, environ=None, stat=None, maps=None):
    d = tmp_path / "proc" / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    for name, val in (("cmdline", cmdline), ("personality", personality), ("environ", environ), ("stat", stat),
                      ("maps", maps)):
        if val is not None:
            (d / name).write_bytes(val if isinstance(val, bytes) else val.encode())
    return d


def test_await_exec_sees_the_program_once_the_chain_has_reached_it(tmp_path):
    _proc(tmp_path, 321, cmdline=b"python3\0/x/latency_probe.py\0--tag\0A\0")
    r = _run(tmp_path, "m_await_exec 321 python3 && echo YES")
    assert r.returncode == 0 and "YES" in r.stdout, r.stderr


def test_await_exec_gives_up_on_a_chain_that_never_reaches_it(tmp_path):
    _proc(tmp_path, 322, cmdline=b"setarch\0x86_64\0-R\0python3\0")
    r = _run(tmp_path, "m_await_exec 322 python3 5 && echo YES || echo NO")
    assert "NO" in r.stdout and "YES" not in r.stdout, r.stdout + r.stderr


def test_await_exec_gives_up_at_once_on_a_process_that_is_gone(tmp_path):
    r = _run(tmp_path, "m_await_exec 323 python3 && echo YES || echo NO")
    assert "NO" in r.stdout, r.stdout + r.stderr


def test_await_exec_matches_the_basename_of_argv0_only(tmp_path):
    _proc(tmp_path, 324, cmdline=b"/home/u/gate2/bin/monitor-native\x007100\0")
    _proc(tmp_path, 325, cmdline=b"bash\0-c\0monitor-native 7100\0")
    r = _run(tmp_path, "m_await_exec 324 monitor-native 3 && echo A; m_await_exec 325 monitor-native 3 || echo B")
    assert "A" in r.stdout.split() and "B" in r.stdout.split(), r.stdout + r.stderr


# ------------------------------------------------------------------ m_launch_readback

STAT_FIELDS = ["S", "1", "100", "100", "0", "-1", "4194304", "10", "0", "0", "0", "1", "0", "0", "0", "20", "0",
               "1", "0", "1000", "1000000", "100", "18446744073709551615", "4194304", "4200000",
               "281474976710000", "0", "0"]


def _stat(pid, comm, startstack):
    f = list(STAT_FIELDS)
    f[25] = str(startstack)            # field 28 is the 26th after "pid (comm)"
    return "%d (%s) %s\n" % (pid, comm, " ".join(f))


MAPS = ("aaaa0000-aaab0000 r-xp 00000000 00:00 1 /usr/bin/python3.12\n"
        "aaac0000-aaad0000 r--p 00010000 00:00 1 /usr/bin/python3.12\n"
        "aaad0000-aaae0000 rw-p 00020000 00:00 1 /usr/bin/python3.12\n"
        "ffff0000-ffff1000 rw-p 00000000 00:00 0 [heap]\n"
        "fffff7a0000-fffff7c1000 rw-p 00000000 00:00 0 [stack]\n")


def test_readback_reads_personality_environment_startstack_and_mappings_as_root(tmp_path):
    _proc(tmp_path, 4100, personality="00040000\n", environ=b"PATH=/x\0LC_ALL=C\0", maps=MAPS,
          stat=_stat(4100, "pyth) on", 281474976711234))
    r = _run(tmp_path, 'CORE_AUX=5; m_launch_readback 4100 && echo "RB=$RB"',
             stubs={"taskset": 'echo "taskset $*" >> "%s"\nshift 2\nexec "$@"' % _posix(tmp_path / "calls.log")})
    assert r.returncode == 0, r.stderr
    assert ("RB=personality=00040000 environ=17 startstack=281474976711234 maps=aaaa0000,aaac0000,aaad0000 "
            "stack=fffff7a0000-fffff7c1000") in r.stdout
    assert any(c.startswith("taskset -c 5 sudo -n ") for c in r.calls), r.calls
    assert all(c.split()[1] == "-n" for c in r.calls if c.startswith("sudo ")), r.calls


def test_readback_says_unread_and_fails_for_a_field_it_cannot_read(tmp_path):
    _proc(tmp_path, 4101, environ=b"A=1\0", maps=MAPS, stat=_stat(4101, "x", 5))
    r = _run(tmp_path, 'CORE_AUX=5; m_launch_readback 4101 && echo OK || echo "FAILED RB=$RB"',
             stubs={"taskset": 'shift 2\nexec "$@"'})
    assert "FAILED RB=personality=unread environ=4 startstack=5" in r.stdout, r.stdout + r.stderr


def test_readback_of_a_process_that_is_gone_fails_and_never_dies(tmp_path):
    r = _run(tmp_path, 'CORE_AUX=5; m_launch_readback 4102 || echo "FAILED RB=$RB"; echo AFTER',
             stubs={"taskset": 'shift 2\nexec "$@"'}, strict=True)
    assert "FAILED RB=personality=unread environ=unread startstack=unread maps=unread stack=unread" in r.stdout
    assert "AFTER" in r.stdout, r.stdout + r.stderr


# ------------------------------------------------------------------ m_qemu_threads and m_pin_by_name

def _qemu(tmp_path, qpid, threads):
    """threads: [(tid, comm, allowed, last_cpu)]"""
    for tid, comm, allowed, last in threads:
        d = tmp_path / "proc" / str(qpid) / "task" / str(tid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "comm").write_text(comm + "\n")
        (d / "status").write_text("Name:\t%s\nCpus_allowed_list:\t%s\n" % (comm, allowed))
        f = ["S"] + ["0"] * 37
        f[36] = str(last)              # field 39 is the 37th after "tid (comm)"
        (d / "stat").write_text("%d (%s) %s\n" % (tid, comm, " ".join(f)))


THREADS = [(900, "qemu-system-aar", "0-5", 4), (901, "qemu-system-aar", "0-5", 5), (902, "CPU 0/KVM", "0-5", 3),
           (903, "CPU 1/KVM", "0-5", 2), (904, "worker", "0-5", 1)]


def test_qemu_threads_lists_every_thread_with_its_last_cpu_allowed_cpus_and_name(tmp_path):
    _qemu(tmp_path, 900, THREADS)
    r = _run(tmp_path, "m_qemu_threads 900")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "tid=900 last=4 allowed=0-5 comm=qemu-system-aar", "tid=901 last=5 allowed=0-5 comm=qemu-system-aar",
        "tid=902 last=3 allowed=0-5 comm=CPU 0/KVM", "tid=903 last=2 allowed=0-5 comm=CPU 1/KVM",
        "tid=904 last=1 allowed=0-5 comm=worker"]


TASKSET_INTO_FAKE = ('[ "$1" = -pc ] || exit 9\necho "taskset $*" >> "%(log)s"\n'
                     'f="%(proc)s/900/task/$3/status"\n[ -e "$f" ] || exit 1\n'
                     'printf "Name:\\tx\\nCpus_allowed_list:\\t%%s\\n" "$2" > "$f"')


def test_pin_by_name_puts_each_vcpu_on_its_core_and_every_other_thread_on_the_rest_core(tmp_path):
    _qemu(tmp_path, 900, THREADS)
    stub = TASKSET_INTO_FAKE % {"log": _posix(tmp_path / "calls.log"), "proc": _posix(tmp_path / "proc")}
    r = _run(tmp_path, "m_pin_by_name 900 2,0,1 && echo PINNED; m_qemu_threads 900", stubs={"taskset": stub})
    assert r.returncode == 0 and "PINNED" in r.stdout, r.stdout + r.stderr
    got = {ln.split()[0]: ln.split()[2] for ln in r.stdout.splitlines() if ln.startswith("tid=")}
    assert got == {"tid=900": "allowed=1", "tid=901": "allowed=1", "tid=902": "allowed=2", "tid=903": "allowed=0",
                   "tid=904": "allowed=1"}
    assert not any(c.startswith("sudo") for c in r.calls), "the owner pins its own threads"


def test_pin_by_name_fails_when_a_thread_does_not_read_back_its_core(tmp_path):
    _qemu(tmp_path, 900, THREADS)
    stub = '[ "$1" = -pc ] || exit 9\n[ "$3" = 903 ] && exit 0\n' + TASKSET_INTO_FAKE.split("\n", 1)[1] % {
        "log": _posix(tmp_path / "calls.log"), "proc": _posix(tmp_path / "proc")}
    r = _run(tmp_path, "m_pin_by_name 900 1,2,0 && echo PINNED || echo NOTPINNED", stubs={"taskset": stub})
    assert "NOTPINNED" in r.stdout, r.stdout + r.stderr


def test_pin_by_name_fails_on_a_vcpu_the_pin_has_no_core_for(tmp_path):
    _qemu(tmp_path, 900, THREADS + [(905, "CPU 2/KVM", "0-5", 0)])
    stub = TASKSET_INTO_FAKE % {"log": _posix(tmp_path / "calls.log"), "proc": _posix(tmp_path / "proc")}
    r = _run(tmp_path, "m_pin_by_name 900 1,2,0 && echo PINNED || echo NOTPINNED", stubs={"taskset": stub})
    assert "NOTPINNED" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("taskset_rc", [0, 1])
def test_pin_by_name_skips_a_thread_that_vanished_while_it_was_being_pinned(tmp_path, taskset_rc):
    """A thread that exits between the listing and the read-back is not a failed pin: its directory is gone
    (taskset succeeded just before it went, or failed because it was gone)."""
    _qemu(tmp_path, 900, THREADS)
    stub = ('[ "$1" = -pc ] || exit 9\nd="%s/900/task/$3"\n'
            'if [ "$3" = 904 ]; then rm -rf "$d"; exit %d; fi\n'
            'printf "Name:\\tx\\nCpus_allowed_list:\\t%%s\\n" "$2" > "$d/status"') % (_posix(tmp_path / "proc"), taskset_rc)
    r = _run(tmp_path, "m_pin_by_name 900 1,2,0 && echo PINNED || echo NOTPINNED", stubs={"taskset": stub})
    assert "PINNED" in r.stdout.split() and "NOTPINNED" not in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("spec", ["1,1,0", "1,2", "1,2,0,3", "a,2,0", "", "1, 2,0"])
def test_pin_by_name_refuses_a_spec_that_is_not_three_distinct_cores(tmp_path, spec):
    _qemu(tmp_path, 900, THREADS)
    r = _run(tmp_path, 'm_pin_by_name 900 "%s"; echo REACHED' % spec, stubs={"taskset": "exit 0"})
    assert r.returncode != 0 and "REACHED" not in r.stdout and "three distinct cores" in r.stderr, r.stdout + r.stderr


# ------------------------------------------------------------------ m_qemu_identify

@pytest.mark.skipif(not LINUX, reason="a real process under /proc")
def test_qemu_identify_names_the_guest_and_pins_nothing(tmp_path):
    ifs, disk = tmp_path / "ifs-stamp.bin", tmp_path / "disk-qemu"
    ifs.write_bytes(b"image")
    disk.write_bytes(b"disk")
    for f in (ifs, disk):           # older than the process by more than the start time's one-second grain
        os.utime(str(f), (os.path.getmtime(str(f)) - 30, os.path.getmtime(str(f)) - 30))
    snippet = ('exec -a qemu-system-aarch64 "%s" -c "import time; time.sleep(30)" -kernel "%s" '
               '-drive "file=%s,if=none,id=drv0,format=raw" &\nQP=$!\nsleep 0.5\n'
               'PROC_ROOT=/proc\nm_qemu_identify "$QP"\necho "QPID=$QPID OK=$([ "$QPID" = "$QP" ] && echo 1)"\n'
               'echo "IFS=$GUEST_IFS SHA=$GUEST_IFS_SHA DISK=$GUEST_DISK THREADS=$QTHREADS"\n'
               'echo "AFF=$QAFF"\nkill "$QP"') % (_posix(sys.executable), _posix(ifs), _posix(disk))
    r = _run(tmp_path, snippet, stubs={"taskset": 'echo "taskset $*" >> "%s"\nexit 1' % _posix(tmp_path / "calls.log")})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK=1" in r.stdout and "IFS=%s" % _posix(ifs) in r.stdout and "DISK=%s" % _posix(disk) in r.stdout
    import hashlib
    assert "SHA=%s" % hashlib.sha256(b"image").hexdigest() in r.stdout
    assert re.search(r"THREADS=[1-9]", r.stdout) and "AFF=" in r.stdout
    assert not any(c.startswith("taskset") for c in r.calls), "identify pins nothing"


@pytest.mark.skipif(not LINUX, reason="a real process under /proc")
def test_qemu_identify_refuses_a_pid_that_is_not_a_qemu(tmp_path):
    """By the pid the launcher printed, never by a scan: another run on the same machine may have a
    process of that name (a shared test host does)."""
    r = _run(tmp_path, 'PROC_ROOT=/proc; m_qemu_identify "$$"; echo REACHED')
    assert r.returncode != 0 and "REACHED" not in r.stdout and "is not a qemu-system-aarch64" in r.stderr


def test_qemu_identify_refuses_a_qemu_none_of_whose_threads_can_be_read(tmp_path):
    """The placement is what the report judges: a QEMU whose threads cannot be read back is not one whose
    placement was verified, and the run does not go on."""
    d = tmp_path / "proc" / "900"
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"/usr/bin/qemu-system-aarch64\0-machine\0virt\0")
    r = _run(tmp_path, "m_qemu_identify 900; echo REACHED")
    assert r.returncode != 0 and "REACHED" not in r.stdout and "could not read QEMU's threads back" in r.stderr, r.stdout + r.stderr


def test_qemu_identify_without_a_pid_wants_exactly_one_qemu(tmp_path):
    r = _run(tmp_path, 'm_pids_of() { printf "11\n12\n"; }; m_qemu_identify; echo REACHED')
    assert r.returncode != 0 and "REACHED" not in r.stdout and "expected exactly 1 qemu-system-aarch64, found 2" in r.stderr


# ------------------------------------------------------------------ the owner's D5 for the ported files

def test_the_ported_files_carry_no_sdv_plan_reference_in_their_headers():
    q = open(os.path.join(GC, "platform-quiesce.sh"), encoding="utf-8").read().split("\nset -u\n")[0]
    lib = _lib_text()
    plat = lib[lib.index("# ------------------------------------------------------------- the platform"):]
    plat = plat[:plat.index("\nPLATFORM_POLICY=")]
    for text in (q, plat):
        assert "SDV" not in text and "sdv" not in text and "Phase 0" not in text, text[:300]
    assert "owner's S6" in q and "owner's S6" in plat
