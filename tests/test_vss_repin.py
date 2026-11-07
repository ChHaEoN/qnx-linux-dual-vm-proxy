"""vss-repin.sh (plan Phase 5 WP2): the one re-pin of QEMU's threads to QEMU's
cores, used by both vss harnesses in Orin mode (VSS_REPIN, `vss-repin.sh boot` after each boot) and by the stack after
every container it starts (SDV_AFTER_START, the container's name as the tag). No git
runs here.

THE RIG. A copy of the script whose /proc is a fake tree of the test (its PROC= line changed in the copy): one directory
per QEMU process and one task directory per thread, each with a status file whose Cpus_allowed_list a test sets. Stubs
first on PATH, each logging its call (its name, whether it ran under the stub sudo, its arguments): pgrep (`-x
qemu-system-aar` answers the QEMU pids a test gives; anything else exits 2), sudo (only `sudo -n`) and taskset (`-pc
LIST TID` rewrites that thread's Cpus_allowed_list in the fake tree; for the threads a test names it refuses, does
nothing and says it did, ends the thread, or starts another thread on 0-5 first). No real QEMU, sudo or taskset is
touched.

Does not demonstrate: the kernel's affinity calls, a real QEMU's threads, that a pin holds after the script returns.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, "orin-native", "gpu-concurrency", "vss-repin.sh")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or sys.platform == "win32", reason="the script runs on Linux under bash")

LINE = re.compile(r"^repin tag=(\S+) cores=0-2 qemu=(\d+) threads=(\d+) off_before=(\d+) pin_failed=(\d+) gone=(\d+) "
                  r"threads_after=(\d+) off_after=(\d+) on_cores=(yes|no)$")

_LOG = 'printf \'%s\\t%s\\t%s\\n\' "$(basename "$0")" "${STUB_VIA_SUDO:-0}" "$*" >> "$STUB_DIR/calls.log"\n'
_STUBS = {
    "pgrep": _LOG + r'''[ "$*" = "-x qemu-system-aar" ] || exit 2
[ -n "${STUB_QEMU_PIDS:-}" ] || exit 1
printf '%s\n' $STUB_QEMU_PIDS
''',
    "sudo": _LOG + r'''[ "${1:-}" = -n ] || { echo "sudo: a terminal is required to read the password" >&2; exit 1; }
shift
[ -z "${STUB_SUDO_REFUSE:-}" ] || { echo "sudo: a password is required" >&2; exit 1; }
export STUB_VIA_SUDO=1
exec "$@"
''',
    "taskset": _LOG + r'''[ "${STUB_VIA_SUDO:-0}" = 1 ] \
	|| { echo "taskset: failed to set pid ${3:-}'s affinity: Operation not permitted" >&2; exit 1; }
[ "${1:-}" = -pc ] && [ "$#" = 3 ] || { echo "taskset stub: $*" >&2; exit 2; }
list="$2"; tid="$3"
named() { case " $2 " in *" $1 "*) return 0 ;; esac; return 1; }
d=""
for x in "$STUB_PROC"/*/task/"$tid"; do [ -d "$x" ] && d="$x"; done
[ -n "$d" ] || { echo "taskset: failed to get pid $tid's affinity: No such process" >&2; exit 1; }
if named "$tid" "${STUB_GONE:-}"; then rm -rf "$d"; echo "taskset: failed to set pid $tid's affinity: No such process" >&2; exit 1; fi
if named "$tid" "${STUB_REFUSE:-}"; then echo "taskset: failed to set pid $tid's affinity: Invalid argument" >&2; exit 1; fi
for sp in ${STUB_SPAWN:-}; do
	[ "${sp%%:*}" = "$tid" ] || continue
	mkdir -p "$(dirname "$d")/${sp#*:}"
	printf 'Name:\tqemu-system-aar\nCpus_allowed_list:\t0-5\n' > "$(dirname "$d")/${sp#*:}/status"
done
echo "pid $tid's current affinity list: $(sed -n 's/^Cpus_allowed_list:\t//p' "$d/status")"
named "$tid" "${STUB_NOOP:-}" || sed -i "s/^Cpus_allowed_list:.*/Cpus_allowed_list:\t$list/" "$d/status"
echo "pid $tid's new affinity list: $list"
''',
}


class Repin:
    """The script's copy, its fake /proc, the stubs, and the run (THE RIG above)."""

    def __init__(self, base):
        self.base = base
        self.proc = base / "proc"
        self.stub = base / "stub"
        self.cwd = base / "cwd"
        self.home = base / "home"
        for d in (self.proc, self.stub, self.cwd, self.home):
            os.makedirs(str(d))
        with open(SCRIPT, encoding="utf-8") as f:
            text = f.read()
        assert text.count("\nPROC=/proc\n") == 1, "vss-repin.sh holds PROC=/proc once"
        self.script = base / "vss-repin.sh"
        self.script.write_text(text.replace("\nPROC=/proc\n", "\nPROC=%s\n" % self.proc), encoding="utf-8")
        for name, body in _STUBS.items():
            p = self.stub / name
            p.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
            os.chmod(str(p), 0o755)

    def qemu(self, pid, threads):
        """One QEMU process: THREADS maps each thread id to its Cpus_allowed_list."""
        for tid, aff in threads.items():
            d = self.proc / str(pid) / "task" / str(tid)
            os.makedirs(str(d))
            (d / "status").write_text("Name:\tqemu-system-aar\nState:\tS (sleeping)\nCpus_allowed:\t3f\nCpus_allowed_list:\t%s\n"
                                      "voluntary_ctxt_switches:\t12\n" % aff, encoding="utf-8")

    def affinity(self, pid, tid):
        text = (self.proc / str(pid) / "task" / str(tid) / "status").read_text(encoding="utf-8")
        return re.search(r"^Cpus_allowed_list:\t(.*)$", text, re.M).group(1)

    def run(self, *args, pids="", **cfg):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("STUB_", "VSS_", "SDV_"))}
        env.update(PATH=str(self.stub) + os.pathsep + os.environ["PATH"], STUB_DIR=str(self.stub), STUB_PROC=str(self.proc),
                   STUB_QEMU_PIDS=pids, HOME=str(self.home), TMPDIR=str(self.home))
        env.update({k: str(v) for k, v in cfg.items()})
        p = subprocess.run([BASH, str(self.script)] + list(args), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           cwd=str(self.cwd), env=env, timeout=60)
        cl = self.stub / "calls.log"
        calls = [tuple(ln.split("\t", 2)) for ln in cl.read_text(encoding="utf-8").splitlines()] if cl.exists() else []
        return p, calls


def _one_line(p):
    lines = p.stdout.splitlines()
    assert len(lines) == 1 and p.stdout.endswith("\n"), "one line on stdout: %r (stderr %r)" % (p.stdout, p.stderr)
    return lines[0]


def _fields(p):
    m = LINE.match(_one_line(p))
    assert m is not None, p.stdout
    return {k: m.group(i + 1) for i, k in enumerate(("tag", "qemu", "threads", "off_before", "pin_failed", "gone",
                                                      "threads_after", "off_after", "on_cores"))}


THREADS = {4242: "0-5", 4243: "0-5", 4250: "0-5", 4251: "0-5"}


def test_every_thread_off_qemus_cores_is_pinned_and_read_back(tmp_path):
    r = Repin(tmp_path)
    r.qemu(4242, THREADS)
    p, calls = r.run("boot", pids="4242")
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert _one_line(p) == ("repin tag=boot cores=0-2 qemu=4242 threads=4 off_before=4 pin_failed=0 gone=0 threads_after=4 "
                            "off_after=0 on_cores=yes")
    assert all(r.affinity(4242, t) == "0-2" for t in THREADS)
    assert [c for c in calls if c[0] == "pgrep"] == [("pgrep", "0", "-x qemu-system-aar")]
    assert sorted(c[2] for c in calls if c[0] == "sudo") == ["-n taskset -pc 0-2 %d" % t for t in sorted(THREADS)]
    assert sorted(c for c in calls if c[0] == "taskset") == [("taskset", "1", "-pc 0-2 %d" % t) for t in sorted(THREADS)]


def test_the_line_counts_the_threads_that_were_not_on_qemus_cores_before(tmp_path):
    """The count a record reads to say whether a container's start moved the pin: a thread
    on 0-2 however its list is written (0,1,2; 2,0-1) is on them; one on 0-5, 3,5 or 0-1 is not."""
    r = Repin(tmp_path)
    r.qemu(4242, {4242: "0-2", 4243: "0,1,2", 4244: "2,0-1", 4245: "0-5", 4246: "3,5", 4247: "0-1"})
    p, _calls = r.run("sdv-stack-databroker", pids="4242")
    assert p.returncode == 0, (p.stdout, p.stderr)
    f = _fields(p)
    assert (f["tag"], f["threads"], f["off_before"], f["off_after"], f["on_cores"]) == ("sdv-stack-databroker", "6", "3", "0", "yes")


def test_a_qemu_already_pinned_reads_nothing_off_before(tmp_path):
    r = Repin(tmp_path)
    r.qemu(4242, dict.fromkeys(THREADS, "0-2"))
    p, _calls = r.run("boot", pids="4242")
    assert p.returncode == 0 and _fields(p)["off_before"] == "0" and _fields(p)["on_cores"] == "yes", p.stdout


@pytest.mark.parametrize("how", ["refuse", "noop"])
def test_a_thread_left_off_qemus_cores_fails(tmp_path, how):
    """refuse: taskset fails for one thread; noop: taskset says it moved the thread and did not -- the read-back, not
    taskset's word, decides. Either way the exit is 1 and the line says no."""
    r = Repin(tmp_path)
    r.qemu(4242, THREADS)
    p, _calls = r.run("boot", pids="4242", **{"STUB_REFUSE" if how == "refuse" else "STUB_NOOP": "4250"})
    assert p.returncode == 1, (p.stdout, p.stderr)
    f = _fields(p)
    assert f["off_after"] == "1" and f["on_cores"] == "no" and f["pin_failed"] == ("1" if how == "refuse" else "0"), f
    assert r.affinity(4242, 4250) == "0-5" and r.affinity(4242, 4251) == "0-2"


@pytest.mark.parametrize("aff", ["0-5", "0-2"], ids=["off", "already-on"])
def test_sudo_that_refuses_pins_nothing_and_fails(tmp_path, aff):
    """A pin that fails while its thread is still there fails the run, even when every thread already read on QEMU's
    cores: a re-pin that cannot pin is not one (after a container's start the next read could differ)."""
    r = Repin(tmp_path)
    r.qemu(4242, dict.fromkeys(THREADS, aff))
    p, _calls = r.run("boot", pids="4242", STUB_SUDO_REFUSE=1)
    f = _fields(p)
    assert p.returncode == 1 and f["pin_failed"] == "4" and f["on_cores"] == "no", p.stdout
    assert f["off_after"] == ("4" if aff == "0-5" else "0"), f


def test_a_thread_that_ends_during_the_pins_is_gone_and_not_read_back(tmp_path):
    r = Repin(tmp_path)
    r.qemu(4242, THREADS)
    p, _calls = r.run("boot", pids="4242", STUB_GONE="4250")
    assert p.returncode == 0, (p.stdout, p.stderr)
    f = _fields(p)
    assert (f["threads"], f["gone"], f["pin_failed"], f["threads_after"], f["off_after"]) == ("4", "1", "0", "3", "0"), f


def test_a_thread_born_during_the_pins_is_read_back_too(tmp_path):
    """The read-back lists the task directory again: a thread started (on 0-5) while the others were pinned is read,
    and fails the run."""
    r = Repin(tmp_path)
    r.qemu(4242, THREADS)
    p, _calls = r.run("boot", pids="4242", STUB_SPAWN="4243:4299")
    assert p.returncode == 1, (p.stdout, p.stderr)
    f = _fields(p)
    assert (f["threads"], f["threads_after"], f["off_after"], f["on_cores"]) == ("4", "5", "1", "no"), f


def test_a_qemu_that_is_gone_before_its_threads_are_read_fails(tmp_path):
    r = Repin(tmp_path)
    p, calls = r.run("boot", pids="4242")
    assert p.returncode == 1, (p.stdout, p.stderr)
    f = _fields(p)
    assert (f["threads"], f["threads_after"], f["on_cores"]) == ("0", "0", "no") and not [c for c in calls if c[0] == "sudo"]


@pytest.mark.parametrize("pids,line", [
    ("", "repin tag=boot cores=0-2 qemu=none error=no-qemu"),
    ("4242 4300", "repin tag=boot cores=0-2 qemu=4242,4300 error=not-one-qemu"),
], ids=["none", "two"])
def test_no_qemu_or_two_exit_non_zero_saying_which(tmp_path, pids, line):
    r = Repin(tmp_path)
    r.qemu(4242, THREADS)
    r.qemu(4300, {4300: "0-5"})
    p, calls = r.run("boot", pids=pids)
    assert p.returncode == 3 and _one_line(p) == line, (p.returncode, p.stdout)
    assert [c[0] for c in calls] == ["pgrep"], "nothing pinned"
    assert r.affinity(4242, 4243) == "0-5"


@pytest.mark.parametrize("args", [(), ("boot", "two"), ("a b",), ("",), ("x;y",), ("--help",)],
                         ids=["none", "two", "space", "empty", "semicolon", "option"])
def test_a_call_that_is_not_one_tag_word_is_refused_before_anything(tmp_path, args):
    r = Repin(tmp_path)
    r.qemu(4242, THREADS)
    p, calls = r.run(*args, pids="4242")
    assert p.returncode == 2 and _one_line(p).startswith("repin error=usage"), (p.returncode, p.stdout)
    assert calls == []


def test_it_finds_qemu_by_its_process_name_never_its_command_line(tmp_path):
    """`pgrep -f` matches its caller's own command line (and this script's, whose tag can be anything); `pgrep -x` on the
    15 characters the kernel keeps of qemu-system-aarch64's name cannot."""
    with open(SCRIPT, encoding="utf-8") as f:
        code = "\n".join(ln for ln in f.read().splitlines() if not ln.lstrip().startswith("#"))
    assert re.findall(r"\bpgrep\b[^\n]*", code) == ['pgrep -x "$QEMU_COMM" || true)"'], re.findall(r"\bpgrep\b[^\n]*", code)
    assert 'QEMU_COMM=qemu-system-aar ' in code and "pgrep -f" not in code


def test_qemus_cores_are_one_design_value_and_nothing_is_written(tmp_path):
    with open(SCRIPT, encoding="utf-8") as f:
        text = f.read()
    code = [re.sub(r"\s+#\s.*$", "", ln) for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert [ln for ln in code if "0-2" in ln] == ["QEMU_CORES=0-2"], [ln for ln in code if "0-2" in ln]
    r = Repin(tmp_path)
    r.qemu(4242, THREADS)
    p, _calls = r.run("boot", pids="4242")
    assert p.returncode == 0 and os.listdir(str(r.cwd)) == [] and os.listdir(str(r.home)) == []
    assert ">" not in "".join(ln.replace(">/dev/null", "").replace("2>&1", "") for ln in code), "no redirect into a file"
