"""platform-quiesce.sh (Phase 3b / A6, 2026-09-30; the owner's S6(a)): stop docker.socket, docker and
containerd for a measurement, record what each was, and start back exactly what was active.

Every test runs against a `systemctl` that keeps the units' state in a temp directory, a `sudo` that
accepts only `-n`, a `docker` that lists containers from a file and a `timeout` that logs its arguments,
all first on PATH, so no test touches a real service and none depends on what the machine running it has
installed. The stub systemctl knows only `show -p LoadState --value`, the five-property dependents
`show` (no --value: Key=Value lines), is-enabled, is-active, stop and start: any other verb (enable,
disable, mask...) or any other `show` is logged to bad.log and fails, and every test that calls
check_no_persistent_change looks there -- the script promises no persistent change. XDG_STATE_HOME and
HOME point into the test's own directory, so the marker (the one well-known file `stop` writes) is never
the real one. DOCKER_HOST, DOCKER_CONTEXT and DOCKER_CONFIG are set to other places in every test's
environment (documentation values): the docker stub logs what it sees of them, and the script must have
removed all three from every call.

Exit statuses: stop exits 3 when it refused before it wrote or stopped anything (every refusal path), 1
when it may have changed the host, 0 on success; restore exits 0 or 1; 2 is wrong usage.
"""
import os
import re
import shutil
import subprocess
import time

import pytest

HERE = os.path.dirname(__file__)
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "platform-quiesce.sh")).replace("\\", "/")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="no bash")

ALL_ACTIVE = {"docker.socket": ("enabled", "active"), "docker": ("enabled", "active"),
              "containerd": ("enabled", "active")}
ALL_INACTIVE = {"docker.socket": ("enabled", "inactive"), "docker": ("enabled", "inactive"),
                "containerd": ("enabled", "inactive")}

# A systemctl over a directory D: <unit>.enabled and <unit>.active hold the words it prints; a unit with
# no .enabled file is not installed (`show -p LoadState --value` says not-found, is-enabled prints nothing
# and fails, is-active says inactive, stop and start fail: as on a host without Docker).
#   <unit>.loadstate  what `show -p LoadState --value` prints instead (empty file: nothing at all)
#   <unit>.loadfail   `show` fails with no output
#   <unit>.stuck      start fails (nonzero) and changes nothing
#   <unit>.forever    start succeeds and leaves the unit `activating` for good (docker.service has
#                     TimeoutStartSec=0 upstream: a start that never ends)
#   <unit>.slow       start succeeds; the unit reads `activating` for its next two is-active calls
#   <unit>.unstoppable  stop changes nothing (a failed unit stays failed, as in systemd)
#   <unit>.slowstop   stop succeeds; the unit reads `deactivating` for its next two is-active calls
#   <unit>.deps       what the five-property dependents `show` prints for the unit: Key=Value lines, one
#                     per property, in the order the file has them (_deps writes systemd's own order).
#                     Without the file it prints all five Key= lines, each empty, in systemd's order
#                     (RequiredBy, RequisiteOf, WantedBy, BoundBy, ConsistsOf): a property that was
#                     asked for is printed even when it has no names
#   <unit>.depfail    the dependents `show` fails with no output
#   docker.pulls-socket  starting docker starts docker.socket too, as docker.service's Requires= does
#   containers.on-start  starting docker copies this file over D/containers: the containers a restart
#                     policy (restart=always) brings back with the daemon, none of them running at stop
# `start` and `stop` skip the flag --no-block; a call without it is still logged in systemctl.log (and in
# sudo.log).
# The `docker` stub knows only `-H unix:///run/docker.sock ps -q --no-trunc`: it prints D/containers, and
# fails while docker is not active, with D/ps.fail, or, with D/ps.needs-sudo, unless it was run by the stub
# sudo (which sets STUB_SUDO). It logs the arguments to docker.log and, for every call, what it sees of
# DOCKER_HOST, DOCKER_CONTEXT and DOCKER_CONFIG to docker.env.log. The `timeout` stub logs its arguments
# to timeout.log and runs the rest, or, with D/timeout.expire, exits 124 (a docker that never answers)
# without running it.
SYSTEMCTL = r'''D="%(d)s"
verb="$1"; shift
echo "$verb $*" >> "$D/systemctl.log"
case "$verb" in
  show)  u="${!#}"
         if [ "$*" = "-p RequiredBy -p BoundBy -p ConsistsOf -p RequisiteOf -p WantedBy $u" ]; then
           [ ! -e "$D/$u.depfail" ] || exit 1
           if [ -e "$D/$u.deps" ]; then cat "$D/$u.deps"
           else printf 'RequiredBy=\nRequisiteOf=\nWantedBy=\nBoundBy=\nConsistsOf=\n'; fi
           exit 0
         fi
         [ "$1 $2 $3" = "-p LoadState --value" ] || { echo "show $*" >> "$D/bad.log"; exit 99; }
         [ ! -e "$D/$u.loadfail" ] || exit 1
         if [ -e "$D/$u.loadstate" ]; then cat "$D/$u.loadstate"
         elif [ -e "$D/$u.enabled" ]; then echo loaded
         else echo not-found; fi ;;
  is-enabled) [ -e "$D/$1.enabled" ] || exit 1; cat "$D/$1.enabled" ;;
  is-active)  f="$D/$1.slowleft"; g="$D/$1.stopleft"
              if [ -e "$f" ]; then
                n="$(cat "$f")"
                if [ "$n" -le 0 ]; then echo active > "$D/$1.active"; rm -f "$f"; else echo $((n-1)) > "$f"; fi
              fi
              if [ -e "$g" ]; then
                n="$(cat "$g")"
                if [ "$n" -le 0 ]; then echo inactive > "$D/$1.active"; rm -f "$g"; else echo $((n-1)) > "$g"; fi
              fi
              if [ -e "$D/$1.active" ]; then a="$(cat "$D/$1.active")"; else a=inactive; fi
              echo "$a"; [ "$a" = active ] ;;
  stop)  rc=0
         for u in "$@"; do
           case "$u" in --no-block) continue ;; esac
           if [ ! -e "$D/$u.enabled" ]; then rc=5
           elif [ -e "$D/$u.slowstop" ]; then echo deactivating > "$D/$u.active"; echo 2 > "$D/$u.stopleft"
           elif [ ! -e "$D/$u.unstoppable" ] && [ "$(cat "$D/$u.active" 2>/dev/null)" != failed ]; then echo inactive > "$D/$u.active"; fi
         done
         exit $rc ;;
  start) rc=0
         for u in "$@"; do
           case "$u" in --no-block) continue ;; esac
           if [ ! -e "$D/$u.enabled" ]; then rc=5
           elif [ -e "$D/$u.stuck" ]; then rc=1
           elif [ -e "$D/$u.forever" ]; then echo activating > "$D/$u.active"
           elif [ -e "$D/$u.slow" ]; then echo activating > "$D/$u.active"; echo 2 > "$D/$u.slowleft"
           else
             echo active > "$D/$u.active"
             if [ "$u" = docker ] && [ -e "$D/docker.pulls-socket" ]; then echo active > "$D/docker.socket.active"; fi
             if [ "$u" = docker ] && [ -e "$D/containers.on-start" ]; then cp "$D/containers.on-start" "$D/containers"; fi
           fi
         done
         exit $rc ;;
  *) echo "$verb $*" >> "$D/bad.log"; exit 99 ;;
esac'''
SUDO = 'echo "$*" >> "%(d)s/sudo.log"\n[ "$1" = -n ] || exit 97\nshift\nexec env STUB_SUDO=1 "$@"'
DOCKER = r'''D="%(d)s"
echo "$* via=${STUB_SUDO:-direct} docker=$(cat "$D/docker.active" 2>/dev/null)" >> "$D/docker.log"
echo "host=${DOCKER_HOST-unset} context=${DOCKER_CONTEXT-unset} config=${DOCKER_CONFIG-unset}" >> "$D/docker.env.log"
[ "$*" = "-H unix:///run/docker.sock ps -q --no-trunc" ] || { echo "docker $*" >> "$D/bad.log"; exit 99; }
[ "$(cat "$D/docker.active" 2>/dev/null)" = active ] || exit 1
[ ! -e "$D/ps.fail" ] || exit 1
[ ! -e "$D/ps.needs-sudo" ] || [ -n "${STUB_SUDO:-}" ] || exit 1
[ ! -e "$D/containers" ] || cat "$D/containers"
exit 0'''
TIMEOUT = r'''D="%(d)s"
echo "$*" >> "$D/timeout.log"
[ ! -e "$D/timeout.expire" ] || exit 124
shift
exec "$@"'''

# 64-hex container ids, as `docker ps -q --no-trunc` prints them
CID1 = "a" * 63 + "1"
CID2 = "b" * 63 + "2"
CID3 = "c" * 63 + "3"
CID4 = "d" * 63 + "4"

# The one docker call the script makes, as the docker stub sees its arguments, and as the timeout and sudo
# stubs see the command that runs it: the SYSTEM daemon only, whatever the caller's environment says.
DOCKER_ARGS = "-H unix:///run/docker.sock ps -q --no-trunc"
DOCKER_CMD = "env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_CONFIG docker " + DOCKER_ARGS
ENV_UNSET = "host=unset context=unset config=unset"


def _stub(path, body):
    with open(path, "w", newline="\n") as f:
        f.write("#!/usr/bin/env bash\n" + body + "\n")
    os.chmod(path, 0o755)


def _write(path, text):
    """LF endings whatever the host: a CR left in a state word would be part of the word."""
    with open(path, "w", newline="\n") as f:
        f.write(text)


def _posix(p):
    return str(p).replace("\\", "/")


def _abs(path):
    """The path as the script's abspath() spells it: the physical directory (in bash's own spelling, which
    is not Python's on Windows) plus the file name."""
    parent, name = os.path.split(_posix(path))
    r = subprocess.run([BASH, "-c", 'cd -- "$1" && pwd -P', "x", parent], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().rstrip("/") + "/" + name


class Host:
    def __init__(self, tmp_path, units, marks=()):
        """units: {unit: (is-enabled, is-active)}; a unit left out is not installed.
        marks: (unit, marker) files such as ("docker", "stuck")."""
        self.tmp = tmp_path
        self.d = tmp_path / "units"
        self.d.mkdir()
        for unit, (enabled, active) in units.items():
            _write(self.d / (unit + ".enabled"), enabled + "\n")
            _write(self.d / (unit + ".active"), active + "\n")
        for unit, mark in marks:
            _write(self.d / (unit + "." + mark), "")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        d = _posix(self.d)
        _stub(self.bin / "systemctl", SYSTEMCTL % {"d": d})
        _stub(self.bin / "sudo", SUDO % {"d": d})
        _stub(self.bin / "docker", DOCKER % {"d": d})
        _stub(self.bin / "timeout", TIMEOUT % {"d": d})
        # the marker's directory is not created here: stop makes it
        self.xdg = tmp_path / "xdg"
        self.marker = self.xdg / "platform-quiesce.active"
        # Deadlines of 2 s, so that no test can ever wait the design values (60 s and 120 s); the
        # environment of the machine running the tests must not decide anything either
        # The caller's docker client configuration points elsewhere in every test (documentation values,
        # RFC 5737): the script must remove it from every docker call, and the stub logs what it sees.
        env = {k: v for k, v in os.environ.items() if k not in ("ALLOW_CONTAINERS", "STOP_DEADLINE_S", "START_DEADLINE_S")}
        self.env = dict(env, PATH=_posix(self.bin) + os.pathsep + os.environ["PATH"],
                        XDG_STATE_HOME=_posix(self.xdg), HOME=_posix(tmp_path / "home"),
                        START_DEADLINE_S="2", STOP_DEADLINE_S="2",
                        DOCKER_HOST="tcp://203.0.113.9:2375", DOCKER_CONTEXT="remote-elsewhere",
                        DOCKER_CONFIG=_posix(tmp_path / "docker-config-elsewhere"))
        self.state = tmp_path / "state" / "quiesce.state"
        self.state.parent.mkdir()
        self.abs_state = _abs(self.state)
        # what a harness-shaped script leaves (_run_sketch): the order its cleanup() did things in, and the
        # marker file its stand-in for m_governor_restore writes
        self.order_log = tmp_path / "harness-order.log"
        self.governor_mark = tmp_path / "governor.restored"

    def cleanup_order(self):
        """What the sketch's cleanup() did, in order: qemu, quiesce-restore (only when restore was called), governor."""
        return self.order_log.read_text().split() if self.order_log.exists() else []

    def run(self, *args, env=None, cwd=None):
        return subprocess.run([BASH, SCRIPT] + list(args), capture_output=True, text=True,
                              env=self.env if env is None else env, cwd=cwd, timeout=120)

    def stop(self, path=None):
        return self.run("stop", _posix(self.state if path is None else path))

    def restore(self, path=None):
        return self.run("restore", _posix(self.state if path is None else path))

    def record(self, text, path=None):
        """A record written by hand, and the marker that a stop would have written beside it."""
        path = self.state if path is None else path
        _write(path, text)
        self.xdg.mkdir(exist_ok=True)
        _write(self.marker, _abs(path) + "\n")

    def active(self, unit):
        f = self.d / (unit + ".active")
        return f.read_text().strip() if f.exists() else "inactive"

    def actives(self):
        return [self.active(u) for u in ("docker.socket", "docker", "containerd")]

    def set_active(self, unit, word):
        _write(self.d / (unit + ".active"), word + "\n")

    def sudo_calls(self):
        f = self.d / "sudo.log"
        return f.read_text().splitlines() if f.exists() else []

    def systemctl_calls(self):
        f = self.d / "systemctl.log"
        return f.read_text().splitlines() if f.exists() else []

    def docker_calls(self):
        f = self.d / "docker.log"
        return f.read_text().splitlines() if f.exists() else []

    def docker_env_calls(self):
        """What the docker stub saw of DOCKER_HOST, DOCKER_CONTEXT and DOCKER_CONFIG, one line per call."""
        f = self.d / "docker.env.log"
        return f.read_text().splitlines() if f.exists() else []

    def timeout_calls(self):
        f = self.d / "timeout.log"
        return f.read_text().splitlines() if f.exists() else []

    def units_changed(self):
        """The sudo calls that could change a unit: a docker ps under sudo -n changes nothing."""
        return [c for c in self.sudo_calls() if c.startswith("-n systemctl")]

    def containers(self, *ids):
        """The containers the stub docker lists."""
        _write(self.d / "containers", "".join(i + "\n" for i in ids))

    def recorded(self):
        return [l for l in self.state.read_text().splitlines() if l and not l.startswith("#")]

    def containers_line(self):
        """The record's `# containers:` comment line (exactly one)."""
        lines = [l for l in self.state.read_text().splitlines() if l.startswith("# containers:")]
        assert len(lines) == 1, self.state.read_text()
        return lines[0]

    def nothing_written_or_stopped(self, r, *, still=None, rc=3):
        """A refused stop: it said so, stopped nothing, and left no record and no marker. It exits 3 when
        it refused before it wrote anything, and 1 when the record was written first and taken back."""
        assert r.returncode == rc, r.stdout + r.stderr
        assert self.units_changed() == [], "nothing may be stopped"
        assert not self.state.exists() and not self.marker.exists()
        assert r.stdout == ""
        if still is not None:
            assert self.actives() == still

    def check_no_persistent_change(self):
        """Nothing but show -p LoadState, the dependents show, is-enabled, is-active, stop and start reached
        systemctl, and every sudo was -n systemctl stop --no-block, -n systemctl start --no-block, or the
        container list -n timeout 10 <the system-daemon docker call>: no stop or start that could block ever
        runs, and no docker call ever saw the caller's DOCKER_HOST, DOCKER_CONTEXT or DOCKER_CONFIG."""
        assert not (self.d / "bad.log").exists(), (self.d / "bad.log").read_text()
        for c in self.sudo_calls():
            assert re.match(r"^-n (systemctl (stop|start) --no-block \S|timeout 10 " + re.escape(DOCKER_CMD) + "$)", c), c
        assert all(c.startswith(DOCKER_ARGS + " via=") for c in self.docker_calls()), self.docker_calls()
        assert all(e == ENV_UNSET for e in self.docker_env_calls()), self.docker_env_calls()
        for unit in ("docker.socket", "docker", "containerd"):
            f = self.d / (unit + ".enabled")
            assert not f.exists() or f.read_text().strip() in ("enabled", "disabled", "static", "masked"), unit


def _lines(r):
    return [l for l in r.stdout.splitlines() if l.strip()]


# ------------------------------------------------------------ stop

def test_stop_records_every_unit_then_stops_them(tmp_path):
    h = Host(tmp_path, {"docker.socket": ("enabled", "active"), "docker": ("enabled", "active"),
                        "containerd": ("disabled", "active")})
    r = h.stop()
    assert r.returncode == 0, r.stderr
    assert h.recorded() == ["docker.socket enabled active", "docker enabled active", "containerd disabled active"]
    assert h.state.read_text().startswith("# platform-quiesce state, recorded ")
    assert h.containers_line() == "# containers: none", "a comment line, never a unit line"
    assert h.actives() == ["inactive"] * 3
    # exactly the command the owner named, once, and not a blocking one
    assert h.sudo_calls() ==["-n systemctl stop --no-block docker.socket docker containerd"]
    lines = _lines(r)
    assert len(lines) == 3 and all(l.endswith(" ok") for l in lines), r.stdout
    assert lines[0].startswith("docker.socket: was enabled/active, now inactive")
    assert "restore" in r.stderr
    h.check_no_persistent_change()


def test_stop_refuses_to_overwrite_an_earlier_record(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.state, "keep me\n")
    r = h.stop()
    assert r.returncode == 3 and "already exists" in r.stderr
    assert h.state.read_text() == "keep me\n"
    assert h.sudo_calls() == [] and h.active("docker") == "active", "nothing may be stopped when the record is refused"
    assert not h.marker.exists(), "a record that stop did not write gets no marker from it"


def test_stop_twice_is_refused_the_second_time_and_the_first_record_survives(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    assert h.stop().returncode == 0
    first, marker = h.state.read_text(), h.marker.read_text()
    r = h.stop()
    assert r.returncode == 3 and "earlier stop is outstanding" in r.stderr and h.abs_state in r.stderr
    assert h.state.read_text() == first and h.recorded()[0] == "docker.socket enabled active"
    assert h.marker.read_text() == marker


def test_stop_refuses_a_dangling_symlink_as_a_state_file(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    try:
        os.symlink(str(tmp_path / "nowhere"), str(h.state))
    except (OSError, NotImplementedError):
        pytest.skip("cannot make symlinks here")
    r = h.stop()
    assert r.returncode == 3 and h.sudo_calls() == [] and not (tmp_path / "nowhere").exists()
    assert not h.marker.exists()


def test_stop_creates_nothing_and_stops_nothing_when_the_state_file_cannot_be_written(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    r = h.run("stop", _posix(tmp_path / "no-such-dir" / "state"))
    assert r.returncode == 3 and h.sudo_calls() == [] and h.active("docker") == "active"
    assert not h.marker.exists()


def test_stop_reports_a_unit_that_will_not_stop_and_keeps_the_record_and_the_marker(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE, marks=[("docker", "unstoppable")])
    r = h.stop()
    assert r.returncode == 1
    lines = _lines(r)
    assert lines[1] == "docker: was enabled/active, now active NOT STOPPED"
    assert lines[0].endswith(" ok") and lines[2].endswith(" ok")
    assert h.state.exists() and h.recorded()[1] == "docker enabled active"
    assert h.marker.read_text() == h.abs_state + "\n"
    assert "restore" in r.stderr and "docker is not down 2 s after its stop was queued" in r.stderr


def test_a_failed_or_already_inactive_unit_counts_as_down(tmp_path):
    h = Host(tmp_path, {"docker.socket": ("enabled", "active"), "docker": ("enabled", "failed"),
                        "containerd": ("enabled", "inactive")})
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.recorded() == ["docker.socket enabled active", "docker enabled failed", "containerd enabled inactive"]
    assert _lines(r)[1] == "docker: was enabled/failed, now failed ok"
    assert _lines(r)[2] == "containerd: was enabled/inactive, now inactive ok"


def test_stop_without_sudo_rights_fails_and_says_which_units_are_still_up(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _stub(h.bin / "sudo", "exit 1")           # sudo -n: a password is required
    r = h.stop()
    assert r.returncode == 1 and r.stdout.count("NOT STOPPED") == 3
    assert h.state.exists() and h.marker.exists() and h.active("docker") == "active"


# ------------------------------------------------------------ the marker

def test_stop_writes_the_marker_naming_the_absolute_path_of_the_record(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    assert not h.marker.exists()
    r = h.stop()
    assert r.returncode == 0, r.stderr
    assert h.marker.read_text() == h.abs_state + "\n"
    assert h.abs_state.startswith("/") and "marker" in r.stderr


def test_the_marker_holds_the_absolute_path_whatever_way_the_state_file_was_named(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    r = h.run("stop", "quiesce.state", cwd=str(h.state.parent))
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.marker.read_text() == h.abs_state + "\n"
    # a different spelling of the same file restores it
    r = h.run("restore", "../state/./quiesce.state", cwd=str(h.state.parent))
    assert r.returncode == 0, r.stdout + r.stderr
    assert not h.state.exists() and not h.marker.exists()


def test_the_marker_defaults_to_home_local_state_when_xdg_state_home_is_unset(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    env = {k: v for k, v in h.env.items() if k != "XDG_STATE_HOME"}
    r = h.run("stop", _posix(h.state), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    marker = tmp_path / "home" / ".local" / "state" / "platform-quiesce.active"
    assert marker.read_text() == h.abs_state + "\n" and not h.marker.exists()
    r = h.run("restore", _posix(h.state), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not marker.exists() and not h.state.exists()


def test_a_relative_marker_directory_is_refused_and_nothing_is_stopped(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    r = h.run("stop", _posix(h.state), env=dict(h.env, XDG_STATE_HOME="relative/dir"))
    assert r.returncode == 3 and "not an absolute path" in r.stderr
    assert h.sudo_calls() == [] and not h.state.exists() and h.actives() == ["active"] * 3


def test_stop_a_then_stop_b_is_refused_naming_a_and_b_is_not_written(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    b = tmp_path / "state" / "other.state"
    assert h.stop().returncode == 0
    first_record, first_marker = h.state.read_text(), h.marker.read_text()
    for unit in ("docker.socket", "docker", "containerd"):       # the board is up again: a second stop would stop it
        h.set_active(unit, "active")
    r = h.stop(b)
    assert r.returncode == 3 and h.abs_state in r.stderr, r.stderr
    assert "earlier stop is outstanding" in r.stderr and "Nothing was stopped and nothing was written" in r.stderr
    assert not b.exists(), "B must not be written"
    assert h.actives() == ["active"] * 3, "nothing may be stopped"
    assert len(h.sudo_calls()) == 1, "only A's stop ever reached sudo"
    assert h.state.read_text() == first_record and h.marker.read_text() == first_marker
    assert r.stdout == ""


def test_a_marker_whose_record_is_gone_still_refuses_a_stop_and_names_it(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    h.xdg.mkdir()
    _write(h.marker, "/somewhere/else/quiesce.state\n")
    r = h.stop()
    assert r.returncode == 3 and "/somewhere/else/quiesce.state" in r.stderr
    assert h.sudo_calls() == [] and not h.state.exists() and h.actives() == ["active"] * 3


@pytest.mark.parametrize("what", ["empty", "directory"])
def test_a_marker_that_names_nothing_readable_refuses_a_stop(tmp_path, what):
    h = Host(tmp_path, ALL_ACTIVE)
    h.xdg.mkdir()
    if what == "empty":
        _write(h.marker, "")
    else:
        h.marker.mkdir()
    r = h.stop()
    assert r.returncode == 3 and "names no readable path" in r.stderr
    assert h.sudo_calls() == [] and not h.state.exists() and h.actives() == ["active"] * 3


def test_stop_stops_nothing_and_leaves_no_record_when_the_marker_cannot_be_written(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.xdg, "a file where the marker's directory should be\n")
    r = h.stop()
    assert r.returncode == 3 and "cannot write the marker" in r.stderr and "nothing was stopped" in r.stderr
    assert h.sudo_calls() == [] and h.actives() == ["active"] * 3
    assert not h.state.exists(), "the record stop made is taken back, or the next stop is blocked by it"
    assert r.stdout == ""


def test_the_marker_is_written_after_the_record_and_before_anything_is_stopped(tmp_path):
    """A sudo that looks for both files when the stop arrives."""
    h = Host(tmp_path, ALL_ACTIVE)
    _stub(h.bin / "sudo", 'echo "record=$([ -e "%s" ] && echo yes || echo no) marker=$([ -e "%s" ] && echo yes || echo no)" >> "%s/order.log"\n'
                          '[ "$1" = -n ] || exit 97\nshift\nexec "$@"' % (_posix(h.state), _posix(h.marker), _posix(h.d)))
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (h.d / "order.log").read_text().split() == ["record=yes", "marker=yes"]


def test_stop_stop_restore_restore_round_trips_twice(tmp_path):
    """After a restore the marker is gone, so the next stop is not refused."""
    h = Host(tmp_path, ALL_ACTIVE)
    for _ in range(2):
        assert h.stop().returncode == 0
        assert h.actives() == ["inactive"] * 3
        assert h.restore().returncode == 0
        assert h.actives() == ["active"] * 3
        assert not h.state.exists() and not h.marker.exists()


# ------------------------------------------------------------ before it writes anything

@pytest.mark.parametrize("unit", ["docker.socket", "docker", "containerd"])
@pytest.mark.parametrize("text,word", [("activating", "activating"), ("deactivating", "deactivating"),
                                       ("reloading", "reloading"), ("maintenance", "maintenance"),
                                       ("", "unknown"), ('activ"e', "unknown"), ("active;rm", "unknown")])
def test_stop_refuses_while_a_unit_is_in_any_state_but_active_inactive_or_failed(tmp_path, unit, text, word):
    units = dict(ALL_ACTIVE)
    units[unit] = ("enabled", text)
    h = Host(tmp_path, units)
    r = h.stop()
    assert "unit %s is %s; wait until it settles and rerun" % (unit, word) in r.stderr, r.stderr
    h.nothing_written_or_stopped(r)
    assert h.active(unit) == text


def test_stop_names_every_unit_that_has_not_settled(tmp_path):
    h = Host(tmp_path, {"docker.socket": ("enabled", "activating"), "docker": ("enabled", "active"),
                        "containerd": ("enabled", "deactivating")})
    r = h.stop()
    assert "unit docker.socket is activating; wait until it settles and rerun" in r.stderr
    assert "unit containerd is deactivating; wait until it settles and rerun" in r.stderr
    assert "unit docker is" not in r.stderr
    h.nothing_written_or_stopped(r)


def test_a_unit_the_host_does_not_have_is_not_asked_whether_it_settled(tmp_path):
    h = Host(tmp_path, {"containerd": ("enabled", "active")})
    _write(h.d / "docker.active", "activating\n")        # a leftover word, but LoadState says not-found
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.recorded()[:2] == ["docker.socket absent absent", "docker absent absent"]


# ------------------------------------------------------------ absent is decided by LoadState

@pytest.mark.parametrize("mark", ["loadfail", "loadstate"])
def test_stop_refuses_when_the_loadstate_of_a_unit_cannot_be_read(tmp_path, mark):
    """`show` fails, or answers nothing: not recorded as absent, and nothing is stopped or written."""
    h = Host(tmp_path, ALL_ACTIVE, marks=[("docker", mark)])
    r = h.stop()
    assert "cannot read the LoadState of docker" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


def test_stop_refuses_a_loadstate_word_outside_the_safe_alphabet(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.d / "docker.loadstate", 'not"found\n')
    r = h.stop()
    assert "cannot read the LoadState of docker" in r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


def test_stop_refuses_on_a_host_with_no_systemctl_at_all(tmp_path):
    """No systemctl means no LoadState, and a unit that cannot be read is not recorded as absent. PATH holds
    only the tools the script could reach before it refuses, and the stub sudo."""
    h = Host(tmp_path, ALL_ACTIVE)
    os.remove(h.bin / "systemctl")
    tools = tmp_path / "tools"
    tools.mkdir()
    for n in ("bash", "tr", "date", "rm", "sync", "mkdir"):
        src = shutil.which(n)
        if src is None:
            pytest.skip("no %s on this machine" % n)
        try:
            os.symlink(src, str(tools / n))
        except (OSError, NotImplementedError):
            pytest.skip("cannot make symlinks here")
    path = os.pathsep.join([_posix(h.bin), _posix(tools)])
    assert shutil.which("systemctl", path=path) is None
    r = h.run("stop", _posix(h.state), env=dict(h.env, PATH=path))
    assert r.returncode == 3 and "cannot read the LoadState of docker.socket" in r.stderr, r.stdout + r.stderr
    assert "not found" not in r.stderr, "a tool the refusal needed is missing from this test's PATH: " + r.stderr
    h.nothing_written_or_stopped(r)


def test_a_unit_is_absent_when_loadstate_says_not_found_whatever_else_systemctl_says(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.d / "docker.loadstate", "not-found\n")      # is-enabled and is-active still answer for it
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.recorded() == ["docker.socket enabled active", "docker absent absent", "containerd enabled active"]
    assert h.sudo_calls() == ["-n systemctl stop --no-block docker.socket containerd"]
    assert h.actives() == ["inactive", "active", "inactive"], "an absent unit is not touched"


def test_a_unit_that_is_there_is_not_absent_though_is_enabled_prints_nothing(tmp_path):
    """The old rule read an empty is-enabled as absence, and skipped a running unit's stop."""
    h = Host(tmp_path, {"docker.socket": ("enabled", "active"), "docker": ("", "active"),
                        "containerd": ("enabled", "active")})
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.recorded()[1] == "docker unknown active"
    assert h.sudo_calls() == ["-n systemctl stop --no-block docker.socket docker containerd"] and h.actives() == ["inactive"] * 3
    assert h.restore().returncode == 0 and h.actives() == ["active"] * 3


def test_a_masked_unit_is_a_unit_that_is_there(tmp_path):
    h = Host(tmp_path, {"docker.socket": ("masked", "inactive"), "docker": ("enabled", "active"),
                        "containerd": ("enabled", "active")})
    _write(h.d / "docker.socket.loadstate", "masked\n")
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.recorded()[0] == "docker.socket masked inactive"
    assert h.sudo_calls() == ["-n systemctl stop --no-block docker.socket docker containerd"]


# ------------------------------------------------------------ a record that does not read back

def test_stop_stops_nothing_when_the_record_does_not_read_back_as_written(tmp_path):
    """A `date` that prints a second line makes the record's header carry a line that is no record's:
    the read-back refuses it, before anything is stopped or the marker is written."""
    h = Host(tmp_path, ALL_ACTIVE)
    _stub(h.bin / "date", 'printf "2026-09-30\\nrogue line"')
    r = h.stop()
    assert r.returncode == 1 and "does not read back as written" in r.stderr and "malformed" in r.stderr
    assert "nothing was stopped" in r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3, rc=1)


def test_stop_stops_nothing_when_the_record_reads_back_valid_but_not_what_was_written(tmp_path):
    """A record that parses is not yet the record that was decided on: a `sync` that changes a line of it
    between the write and the read-back is caught by the comparison, not by the parser."""
    h = Host(tmp_path, ALL_ACTIVE)
    _stub(h.bin / "sync", 'sed -i "s/^docker enabled active$/docker enabled inactive/" "%s"' % _posix(h.state))
    r = h.stop()
    assert r.returncode == 1 and "does not read back as written (docker differs)" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3, rc=1)


# ------------------------------------------------------------ a word with a quote in it

@pytest.mark.parametrize("word", ['ena"bled', "ena\\bled"])
def test_a_quote_or_a_backslash_in_is_enabled_never_reaches_the_record(tmp_path, word):
    """The word is not a word of the safe alphabet: it is recorded as `unknown`, not with characters
    dropped, and the record stays one restore can read (restore compares `unknown` with `unknown`)."""
    h = Host(tmp_path, {"docker.socket": ("enabled", "active"), "docker": (word, "active"),
                        "containerd": ("enabled", "active")})
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.recorded() == ["docker.socket enabled active", "docker unknown active", "containerd enabled active"]
    assert "unknown" in _lines(r)[1] and '"' not in h.state.read_text() and "\\" not in h.state.read_text()
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert not h.state.exists() and not h.marker.exists()


def test_a_record_with_a_quote_in_it_is_refused_and_starts_nothing(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE)
    content = 'docker.socket enabled active\ndocker ena"bled active\ncontainerd enabled active\n'
    h.record(content)
    r = h.restore()
    assert r.returncode == 1 and "malformed" in r.stderr, r.stderr
    assert h.sudo_calls() == [] and h.state.read_text() == content and h.marker.exists()


# ------------------------------------------------------------ restore

def test_restore_starts_exactly_the_units_the_record_says_were_active_in_order(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE)
    h.record("# x\ndocker.socket enabled inactive\ndocker enabled active\ncontainerd enabled active\n")
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.sudo_calls() == ["-n systemctl start --no-block containerd", "-n systemctl start --no-block docker"]
    assert h.actives() == ["inactive", "active", "active"]
    assert [l.split(":")[0] for l in _lines(r)] == ["containerd", "docker", "docker.socket"]
    assert all(l.endswith(" ok") for l in _lines(r)), r.stdout
    assert not h.state.exists() and not h.marker.exists()
    h.check_no_persistent_change()


def test_stop_then_restore_puts_every_unit_back_and_removes_the_record_and_the_marker(tmp_path):
    h = Host(tmp_path, {"docker.socket": ("enabled", "active"), "docker": ("enabled", "active"),
                        "containerd": ("disabled", "active")})
    assert h.stop().returncode == 0
    assert h.marker.exists()
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.actives() == ["active"] * 3
    assert h.sudo_calls() == ["-n systemctl stop --no-block docker.socket docker containerd",
                              "-n systemctl start --no-block containerd", "-n systemctl start --no-block docker",
                              "-n systemctl start --no-block docker.socket"]
    assert len(_lines(r)) == 3 and not h.state.exists() and not h.marker.exists()
    assert (h.d / "containerd.enabled").read_text().strip() == "disabled"     # never enabled or disabled
    h.check_no_persistent_change()


def test_restore_starts_only_the_socket_when_only_the_socket_was_active(tmp_path):
    """The socket-activated shape: dockerd runs only once something connects."""
    h = Host(tmp_path, {"docker.socket": ("enabled", "active"), "docker": ("enabled", "inactive"),
                        "containerd": ("enabled", "inactive")})
    assert h.stop().returncode == 0
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.sudo_calls()[-1:] == ["-n systemctl start --no-block docker.socket"] and len(h.sudo_calls()) == 2
    assert h.actives() == ["active", "inactive", "inactive"]


def test_restore_removes_the_record_first_and_the_marker_after_it(tmp_path):
    """An rm that logs its arguments, and whether the record and the marker were still there when it was called
    (the real rm then runs): the record goes first, while the marker still names it, and the marker last."""
    h = Host(tmp_path, ALL_ACTIVE)
    assert h.stop().returncode == 0
    log = h.d / "rm.log"
    exists = '$([ -e "%s" ] && echo yes || echo no)'
    _stub(h.bin / "rm", 'echo "$* record=%s marker=%s" >> "%s"\nexec "%s" "$@"'
          % (exists % _posix(h.state), exists % _posix(h.marker), _posix(log), _posix(shutil.which("rm"))))
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.read_text().splitlines() == ["-f -- %s record=yes marker=yes" % _posix(h.state),
                                            "-f -- %s record=no marker=yes" % _posix(h.marker)]
    assert not h.state.exists() and not h.marker.exists()


def test_restore_fails_and_keeps_the_record_and_the_marker_when_a_unit_does_not_come_back(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE, marks=[("docker", "stuck")])
    recorded = "docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\n"
    h.record(recorded)
    marker = h.marker.read_text()
    r = h.restore()
    assert r.returncode == 1
    lines = _lines(r)
    assert lines[1] == "docker: recorded enabled/active, now enabled/inactive MISMATCH"
    assert lines[0].endswith(" ok") and lines[2].endswith(" ok"), "the others are still brought back"
    assert h.state.read_text() == recorded and h.marker.read_text() == marker, "the record and the marker stay"
    assert "are kept" in r.stderr


def test_a_start_that_itself_fails_is_not_polled_for_the_deadline(tmp_path):
    """The deadline is for a start that was accepted: a call that fails is reported at once."""
    h = Host(tmp_path, ALL_INACTIVE, marks=[("docker", "stuck")])
    h.record("docker.socket enabled inactive\ndocker enabled active\ncontainerd enabled inactive\n")
    t0 = time.monotonic()
    r = h.run("restore", _posix(h.state), env=dict(h.env, START_DEADLINE_S="30"))
    assert r.returncode == 1 and "'sudo -n systemctl start --no-block docker' failed" in r.stderr
    assert time.monotonic() - t0 < 20


def test_restore_reports_a_unit_that_is_active_though_it_was_recorded_inactive(tmp_path):
    """restore never stops anything: starting docker pulls its socket in, and that is a mismatch."""
    h = Host(tmp_path, ALL_INACTIVE, marks=[("docker", "pulls-socket")])
    h.record("docker.socket enabled inactive\ndocker enabled active\ncontainerd enabled active\n")
    r = h.restore()
    assert r.returncode == 1 and _lines(r)[2] == "docker.socket: recorded enabled/inactive, now enabled/active MISMATCH"
    assert h.state.exists() and h.marker.exists()
    assert not any("stop" in c for c in h.sudo_calls())


def test_restore_notices_a_changed_enabled_state(tmp_path):
    h = Host(tmp_path, {"docker.socket": ("enabled", "active"), "docker": ("enabled", "active"),
                        "containerd": ("masked", "inactive")})
    h.record("docker.socket enabled active\ndocker enabled active\ncontainerd enabled inactive\n")
    r = h.restore()
    assert r.returncode == 1 and "containerd: recorded enabled/inactive, now masked/inactive MISMATCH" in r.stdout
    assert h.state.exists() and h.marker.exists()


@pytest.mark.parametrize("recorded,now", [("failed", "inactive"), ("inactive", "failed")])
def test_a_unit_recorded_down_is_as_recorded_while_it_is_inactive_or_failed(tmp_path, recorded, now):
    """stop accepts inactive and failed as down, and a failed unit stays failed: at restore they are one state."""
    h = Host(tmp_path, {"docker.socket": ("enabled", "inactive"), "docker": ("enabled", now),
                        "containerd": ("enabled", now)})
    h.record("docker.socket enabled inactive\ndocker enabled %s\ncontainerd enabled %s\n" % (recorded, recorded))
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert _lines(r)[1] == "docker: recorded enabled/%s, now enabled/%s ok" % (recorded, now)
    assert h.sudo_calls() == [], "nothing recorded down is started"
    assert not h.state.exists() and not h.marker.exists()


def test_a_unit_recorded_active_that_is_failed_is_still_a_mismatch(tmp_path):
    h = Host(tmp_path, {"docker.socket": ("enabled", "inactive"), "docker": ("enabled", "failed"),
                        "containerd": ("enabled", "inactive")}, marks=[("docker", "stuck")])
    h.record("docker.socket enabled inactive\ndocker enabled active\ncontainerd enabled inactive\n")
    r = h.restore()
    assert r.returncode == 1 and _lines(r)[1] == "docker: recorded enabled/active, now enabled/failed MISMATCH"


@pytest.mark.parametrize("content,what", [
    ("", "no line for"),
    ("docker enabled active\ncontainerd enabled active\n", "no line for docker.socket"),
    ("docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\nsshd enabled active\n", "unknown unit"),
    ("docker.socket enabled active\ndocker enabled active\ndocker enabled active\ncontainerd enabled active\n", "twice"),
    ("docker.socket enabled\ndocker enabled active\ncontainerd enabled active\n", "malformed"),
    ("docker.socket enabled active extra\ndocker enabled active\ncontainerd enabled active\n", "malformed"),
    ("docker.socket enabled active;rm\ndocker enabled active\ncontainerd enabled active\n", "malformed"),
    ("docker.socket enabled activating\ndocker enabled active\ncontainerd enabled active\n", "malformed"),
    ("docker.socket absent active\ndocker enabled active\ncontainerd enabled active\n", "malformed"),
    ("docker.socket enabled absent\ndocker enabled active\ncontainerd enabled active\n", "malformed"),
])
def test_restore_starts_nothing_from_a_file_that_is_not_its_own_record(tmp_path, content, what):
    h = Host(tmp_path, ALL_INACTIVE)
    h.record(content)
    r = h.restore()
    assert r.returncode == 1 and what in r.stderr, r.stderr
    assert h.sudo_calls() == [] and h.state.read_text() == content and h.marker.exists()


def test_restore_without_a_record_starts_nothing(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    r = h.restore()
    assert r.returncode == 1 and "nothing to restore" in r.stderr and h.sudo_calls() == []


def test_restore_of_a_record_that_is_gone_says_which_marker_still_names_it(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE)
    h.record("docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\n")
    os.remove(h.state)
    r = h.restore()
    assert r.returncode == 1 and "nothing to restore" in r.stderr and h.abs_state in r.stderr
    assert h.sudo_calls() == [] and h.marker.exists()


def test_restore_of_a_directory_is_refused_cleanly(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE)
    h.state.mkdir()
    r = h.restore()
    assert r.returncode == 1 and "not a regular file" in r.stderr, r.stderr
    assert "unbound" not in r.stderr and h.sudo_calls() == []


def test_read_state_on_a_path_it_cannot_read_a_line_from_fails_cleanly_under_set_u(tmp_path):
    """`local line=""`: a read that fails before it assigns (a directory) would otherwise leave `line`
    unset for the `|| [ -n "$line" ]` of the loop, and `set -u` would kill the script there. The function
    is cut out of the script and run on a directory, because restore's regular-file check keeps that
    path from ever reaching it."""
    d = tmp_path / "adir"
    d.mkdir()
    prog = ('set -u\nUNITS="docker.socket docker containerd"\ndeclare -A S_EN S_ACT\nERR=""\n'
            'eval "$(awk \'/^read_state\\(\\) \\{/,/^\\}/\' "$1")"\n'
            'read_state "$2"; echo "rc=$? err=$ERR"')
    r = subprocess.run([BASH, "-c", prog, "x", SCRIPT, _posix(d)], capture_output=True, text=True, timeout=60)
    assert "unbound" not in r.stderr, r.stderr
    assert "rc=1 err=no line for docker.socket" in r.stdout, r.stdout + r.stderr


def test_restore_of_a_symlink_to_a_record_is_refused(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE)
    real = tmp_path / "state" / "real.state"
    h.record("docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\n", path=real)
    try:
        os.symlink(str(real), str(h.state))
    except (OSError, NotImplementedError):
        pytest.skip("cannot make symlinks here")
    r = h.restore()
    assert r.returncode == 1 and "not a regular file" in r.stderr, r.stderr
    assert h.sudo_calls() == [] and real.exists()


def test_restore_of_the_wrong_file_is_refused_and_starts_nothing(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    assert h.stop().returncode == 0
    b = tmp_path / "state" / "other.state"
    text = "docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\n"
    _write(b, text)
    calls = len(h.sudo_calls())
    r = h.restore(b)
    assert r.returncode == 1 and h.abs_state in r.stderr and "nothing was started" in r.stderr, r.stderr
    assert len(h.sudo_calls()) == calls and h.actives() == ["inactive"] * 3
    assert b.read_text() == text and h.state.exists() and h.marker.read_text() == h.abs_state + "\n"
    assert r.stdout == ""
    # the right one still restores, and removes both
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.actives() == ["active"] * 3 and not h.state.exists() and not h.marker.exists() and b.exists()


def test_restore_with_no_marker_is_refused_and_says_how_to_write_it_back(tmp_path):
    """No marker: no stop is outstanding, so the record is not one restore acts on (a record left by
    something else could start what the owner has stopped since)."""
    h = Host(tmp_path, ALL_INACTIVE)
    text = "docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\n"
    _write(h.state, text)
    r = h.restore()
    assert r.returncode == 1 and "no marker" in r.stderr and "printf" in r.stderr and h.abs_state in r.stderr
    assert h.sudo_calls() == [] and h.state.read_text() == text and not h.marker.exists()
    assert h.actives() == ["inactive"] * 3


@pytest.mark.parametrize("what", ["empty", "directory"])
def test_restore_with_a_marker_that_names_nothing_readable_is_refused(tmp_path, what):
    h = Host(tmp_path, ALL_INACTIVE)
    _write(h.state, "docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\n")
    h.xdg.mkdir()
    if what == "empty":
        _write(h.marker, "")
    else:
        h.marker.mkdir()
    r = h.restore()
    assert r.returncode == 1 and "names no readable path" in r.stderr and h.sudo_calls() == []
    assert h.state.exists()


# ------------------------------------------------------------ start never blocks

def test_restore_waits_for_a_unit_that_is_a_moment_activating(tmp_path):
    """--no-block returns before the unit is up: restore polls is-active, and only the unit that
    reads active in time is reported ok."""
    h = Host(tmp_path, ALL_INACTIVE, marks=[("docker", "slow")])
    h.record("docker.socket enabled inactive\ndocker enabled active\ncontainerd enabled active\n")
    t0 = time.monotonic()
    r = h.run("restore", _posix(h.state), env=dict(h.env, START_DEADLINE_S="20"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert time.monotonic() - t0 < 15, "a unit that is up ends the wait, not the deadline"
    assert "after its start was queued" not in r.stderr
    assert _lines(r)[1] == "docker: recorded enabled/active, now enabled/active ok"
    calls = h.systemctl_calls()
    after = calls[calls.index("start --no-block docker"):]
    assert after.count("is-active docker") >= 3, "it polled, not once"
    assert not h.state.exists() and not h.marker.exists()
    h.check_no_persistent_change()


def test_a_unit_that_never_finishes_starting_is_a_mismatch_after_the_deadline_not_a_hang(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE, marks=[("docker", "forever")])
    recorded = "docker.socket enabled inactive\ndocker enabled active\ncontainerd enabled active\n"
    h.record(recorded)
    t0 = time.monotonic()
    r = h.run("restore", _posix(h.state), env=dict(h.env, START_DEADLINE_S="1"))
    elapsed = time.monotonic() - t0
    assert r.returncode == 1, r.stdout + r.stderr
    assert _lines(r)[1] == "docker: recorded enabled/active, now enabled/activating MISMATCH"
    assert _lines(r)[0].endswith(" ok") and _lines(r)[2].endswith(" ok")
    assert "docker is not active 1 s after its start was queued" in r.stderr
    assert h.state.read_text() == recorded and h.marker.exists()
    assert elapsed < 20, "the deadline, not the unit, ends the wait"
    h.check_no_persistent_change()


def test_a_deadline_of_zero_asks_once(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE, marks=[("docker", "forever")])
    h.record("docker.socket enabled inactive\ndocker enabled active\ncontainerd enabled inactive\n")
    r = h.run("restore", _posix(h.state), env=dict(h.env, START_DEADLINE_S="0"))
    assert r.returncode == 1 and "MISMATCH" in r.stdout


def test_a_deadline_with_a_leading_zero_is_a_decimal_number(tmp_path):
    """08 is no octal number: bash arithmetic would refuse it without 10#."""
    h = Host(tmp_path, ALL_INACTIVE)
    h.record("docker.socket enabled inactive\ndocker enabled active\ncontainerd enabled active\n")
    r = h.run("restore", _posix(h.state), env=dict(h.env, START_DEADLINE_S="08"))
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "", "1234567"])
def test_a_deadline_that_is_not_a_whole_number_of_seconds_refuses_the_restore(tmp_path, value):
    h = Host(tmp_path, ALL_INACTIVE)
    h.record("docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\n")
    r = h.run("restore", _posix(h.state), env=dict(h.env, START_DEADLINE_S=value))
    if value == "":
        # empty means unset: the design value applies, and the restore goes ahead
        assert r.returncode == 0, r.stdout + r.stderr
    else:
        assert r.returncode == 1 and "START_DEADLINE_S" in r.stderr and h.sudo_calls() == [], r.stderr
        assert h.state.exists()


def test_the_design_value_of_the_deadline_is_sixty_seconds_and_its_reason_is_in_the_header(tmp_path):
    with open(SCRIPT, encoding="utf-8") as f:
        text = f.read()
    assert 'START_DEADLINE_S="${START_DEADLINE_S:-60}"' in text
    header = re.sub(r"\s*\n#\s*", " ", text.split("set -u")[0])       # the comment lines joined into prose
    assert "TimeoutStartSec=0" in header and "design value, 60" in header and "--no-block" in header
    assert "FIXED STATE PATH, NEVER ONE UNDER A PER-RUN $OUT" in header
    assert "only if the record matches what the host boots with; otherwise it reports the mismatch" in header


def test_the_design_value_of_the_stop_deadline_is_120_seconds_and_its_reason_is_in_the_header(tmp_path):
    with open(SCRIPT, encoding="utf-8") as f:
        text = f.read()
    assert 'STOP_DEADLINE_S="${STOP_DEADLINE_S:-120}"' in text
    header = re.sub(r"\s*\n#\s*", " ", text.split("set -u")[0])
    assert "STOP_DEADLINE_S is a design value, 120" in header
    assert "systemd's default TimeoutStopSec is 90 s" in header and "SIGKILL" in header and "a drop-in" in header
    assert "sudo -n systemctl stop --no-block UNITS" in header and "`NOT STOPPED`" in header


# ------------------------------------------------------------ a host without the units

def test_units_the_host_does_not_have_are_recorded_and_skipped_both_ways(tmp_path):
    """The a1.metal shape: systemd, but no Docker at all."""
    h = Host(tmp_path, {})
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.recorded() == ["docker.socket absent absent", "docker absent absent", "containerd absent absent"]
    assert _lines(r) == ["docker.socket: absent on this host, skipped", "docker: absent on this host, skipped",
                         "containerd: absent on this host, skipped"]
    assert h.sudo_calls() == [], "nothing to stop, so no privilege is used"
    assert h.marker.exists(), "the marker is written all the same: the harness restores all the same"
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert [l.split(":")[0] for l in _lines(r)] == ["containerd", "docker", "docker.socket"]
    assert all("absent when recorded, skipped" in l for l in _lines(r))
    assert h.sudo_calls() == [] and not h.state.exists() and not h.marker.exists()
    h.check_no_persistent_change()


def test_only_the_units_the_host_has_are_stopped_and_started(tmp_path):
    h = Host(tmp_path, {"containerd": ("enabled", "active")})       # containerd alone, no Docker
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.recorded() == ["docker.socket absent absent", "docker absent absent", "containerd enabled active"]
    assert h.sudo_calls() == ["-n systemctl stop --no-block containerd"] and h.active("containerd") == "inactive"
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.sudo_calls()[1:] == ["-n systemctl start --no-block containerd"] and h.active("containerd") == "active"
    assert not h.state.exists()


# ------------------------------------------------------------ usage

@pytest.mark.parametrize("args", [(), ("stop",), ("restore",), ("stop", "a", "b"), ("start", "x"), ("enable", "x")])
def test_wrong_usage_exits_2_and_touches_nothing(tmp_path, args):
    h = Host(tmp_path, ALL_ACTIVE)
    r = h.run(*args)
    assert r.returncode == 2 and "usage" in r.stderr
    assert h.sudo_calls() == [] and not h.state.exists() and not h.marker.exists() and h.active("docker") == "active"


# ------------------------------------------------------------ the containers

def _allow(h):
    return dict(h.env, ALLOW_CONTAINERS="1")


def test_stop_refuses_while_a_container_runs_and_names_how_many(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    h.containers(CID1, CID2)
    r = h.stop()
    assert "refused: 2 running container(s)" in r.stderr and "ALLOW_CONTAINERS=1" in r.stderr, r.stderr
    assert "nothing was stopped, no record and no marker was written" in r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)
    # asked while docker was active, before anything was stopped, in the form the owner named
    assert h.docker_calls() == [DOCKER_ARGS + " via=direct docker=active"]
    assert h.timeout_calls() == ["10 " + DOCKER_CMD]
    assert h.sudo_calls() == [], "the direct call answered: no privilege was used"


@pytest.mark.parametrize("value", ["", "0", "yes", "true", "11"])
def test_only_allow_containers_equal_to_1_lets_a_stop_go_on_over_a_container(tmp_path, value):
    h = Host(tmp_path, ALL_ACTIVE)
    h.containers(CID1)
    r = h.run("stop", _posix(h.state), env=dict(h.env, ALLOW_CONTAINERS=value))
    assert "refused: 1 running container(s)" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


def test_allow_containers_records_the_containers_and_restore_reports_which_run_again(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    h.containers(CID1, CID2, CID3)
    r = h.run("stop", _posix(h.state), env=_allow(h))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALLOW_CONTAINERS=1: 3 running container(s) are recorded" in r.stderr
    assert h.containers_line() == "# containers: %s %s %s" % (CID1, CID2, CID3)
    assert [l.split()[0] for l in h.recorded()] == ["docker.socket", "docker", "containerd"], "no container is a unit line"
    assert h.actives() == ["inactive"] * 3 and len(_lines(r)) == 3
    # the first and the third come back on their own (their restart policy), the second does not, and a
    # fourth that was not there at stop runs now
    h.containers(CID1, CID3, CID4)
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(_lines(r)) == 3, "stdout stays one line per unit"
    report = [l for l in r.stderr.splitlines() if "containers at stop" in l]
    assert report == ["platform-quiesce: containers at stop: 3; running again: %s %s; not running: %s; "
                      "running now, not at stop: %s; restore starts none"
                      % (CID1[:12], CID3[:12], CID2[:12], CID4[:12])], r.stderr
    assert all(c.startswith(DOCKER_ARGS) for c in h.docker_calls()), "restore asks, and starts nothing"
    assert not h.state.exists() and not h.marker.exists()
    h.check_no_persistent_change()


def test_restore_reports_none_not_running_when_every_recorded_container_is_back(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    h.containers(CID2)
    assert h.run("stop", _posix(h.state), env=_allow(h)).returncode == 0
    r = h.restore()
    assert r.returncode == 0
    assert ("containers at stop: 1; running again: %s; not running: none; running now, not at stop: none; restore starts none"
            % CID2[:12]) in r.stderr


def test_restore_lists_every_container_that_runs_now_and_did_not_at_stop_and_starts_nothing(tmp_path):
    """None of the recorded containers is back; two others are running. A report: no container is started,
    no unit but the recorded ones, and the record and the marker go as they do for any restore."""
    h = Host(tmp_path, ALL_ACTIVE)
    h.containers(CID1)
    assert h.run("stop", _posix(h.state), env=_allow(h)).returncode == 0
    h.containers(CID3, CID4)
    calls_before = len(h.docker_calls())
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    report = [l for l in r.stderr.splitlines() if "containers at stop" in l]
    assert report == ["platform-quiesce: containers at stop: 1; running again: none; not running: %s; "
                      "running now, not at stop: %s %s; restore starts none" % (CID1[:12], CID3[:12], CID4[:12])], r.stderr
    assert len(_lines(r)) == 3 and h.actives() == ["active"] * 3 and not h.state.exists() and not h.marker.exists()
    assert len(h.docker_calls()) == calls_before + 1, "restore asked once"
    assert all(c.startswith(DOCKER_ARGS) for c in h.docker_calls()), "ps and nothing else: no container is started"
    assert all(c.startswith("-n systemctl ") or c.startswith("-n timeout 10 ") for c in h.sudo_calls())
    h.check_no_persistent_change()


def test_a_recorded_container_that_runs_again_is_not_listed_as_new(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    h.containers(CID1, CID2)
    assert h.run("stop", _posix(h.state), env=_allow(h)).returncode == 0
    h.containers(CID2, CID1)                # the same two, in another order
    r = h.restore()
    assert r.returncode == 0
    assert "running again: %s %s; not running: none; running now, not at stop: none;" % (CID1[:12], CID2[:12]) in r.stderr


def test_docker_that_cannot_be_asked_at_restore_is_reported_as_unknown_and_never_started_through_the_socket(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE, marks=[("docker", "stuck")])
    h.record("# containers: %s\ndocker.socket enabled inactive\ndocker enabled active\ncontainerd enabled inactive\n" % CID1)
    r = h.restore()
    assert r.returncode == 1 and "docker: recorded enabled/active, now enabled/inactive MISMATCH" in r.stdout
    assert "containers at stop: 1; which of them run again is not known" in r.stderr and "restore starts none" in r.stderr
    assert "running now, not at stop: not known" in r.stderr
    assert h.docker_calls() == [], "docker is not active: asking would start it through docker.socket"
    assert h.state.exists() and h.marker.exists()


def test_a_record_without_a_containers_line_says_nothing_about_containers_at_restore(tmp_path):
    """A record with no `# containers:` line at all (a file from before the line existed): no report, and
    no question, though docker is active at restore time."""
    h = Host(tmp_path, ALL_INACTIVE)
    h.containers(CID4)
    h.record("docker.socket enabled inactive\ndocker enabled active\ncontainerd enabled active\n")
    r = h.restore()
    assert r.returncode == 0 and "containers at stop" not in r.stderr and "running now" not in r.stderr
    assert h.docker_calls() == [] and h.active("docker") == "active"


NONE_LINE = "platform-quiesce: containers at stop: 0; running now, not at stop: %s; restore starts none"


def test_a_record_of_none_reports_none_running_now_when_docker_is_active_and_nothing_runs(tmp_path):
    """The report of a record of none: nothing recorded to run again, so only what runs now is said. The
    system daemon is asked once, at restore, on top of the one stop made."""
    h = Host(tmp_path, ALL_ACTIVE)
    assert h.stop().returncode == 0
    assert h.containers_line() == "# containers: none" and len(h.docker_calls()) == 1, "stop asked once"
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert [l for l in r.stderr.splitlines() if "containers at stop" in l] == [NONE_LINE % "none"], r.stderr
    assert len(h.docker_calls()) == 2, "restore asked once"
    assert h.docker_calls()[1] == DOCKER_ARGS + " via=direct docker=active"
    assert h.timeout_calls() == ["10 " + DOCKER_CMD] * 2
    assert len(_lines(r)) == 3, "stdout stays one line per unit"
    assert not h.state.exists() and not h.marker.exists()
    h.check_no_persistent_change()


def test_a_restart_always_container_that_comes_back_with_docker_is_listed_as_running_now_not_at_stop(tmp_path):
    """Nothing runs at stop, so the record says none. A container with restart=always is not among the
    running containers at stop and comes back with the daemon that restore starts: the report names it, and
    restore starts nothing but the units."""
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.d / "containers.on-start", CID4 + "\n" + CID3 + "\n")
    assert h.stop().returncode == 0
    assert h.containers_line() == "# containers: none" and not (h.d / "containers").exists()
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert [l for l in r.stderr.splitlines() if "containers at stop" in l] == [NONE_LINE % (CID4[:12] + " " + CID3[:12])], r.stderr
    assert len(h.docker_calls()) == 2 and all(c.startswith(DOCKER_ARGS) for c in h.docker_calls())
    assert [c for c in h.sudo_calls() if c.startswith("-n systemctl")] == [
        "-n systemctl stop --no-block docker.socket docker containerd", "-n systemctl start --no-block containerd",
        "-n systemctl start --no-block docker", "-n systemctl start --no-block docker.socket"], "no container is started"
    assert not h.state.exists() and not h.marker.exists()
    h.check_no_persistent_change()


def test_a_record_of_none_says_not_known_when_docker_is_not_active_at_restore_and_asks_nothing(tmp_path):
    """dockerd is not running, so asking would start it through docker.socket: not asked."""
    h = Host(tmp_path, ALL_INACTIVE, marks=[("docker", "stuck")])
    h.record("# containers: none\ndocker.socket enabled inactive\ndocker enabled active\ncontainerd enabled inactive\n")
    r = h.restore()
    assert r.returncode == 1 and "docker: recorded enabled/active, now enabled/inactive MISMATCH" in r.stdout
    assert [l for l in r.stderr.splitlines() if "containers at stop" in l] == [NONE_LINE % "not known"], r.stderr
    assert h.docker_calls() == [] and h.timeout_calls() == [], "docker is not active: asking would start it through docker.socket"
    assert h.state.exists() and h.marker.exists()


def test_a_record_of_none_says_not_known_when_the_list_cannot_be_read_at_restore(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    assert h.stop().returncode == 0
    _write(h.d / "ps.fail", "")
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert [l for l in r.stderr.splitlines() if "containers at stop" in l] == [NONE_LINE % "not known"], r.stderr
    assert h.docker_calls()[1:] == [DOCKER_ARGS + " via=direct docker=active", DOCKER_ARGS + " via=1 docker=active"]
    assert not h.state.exists() and not h.marker.exists()


def test_a_containers_line_that_is_not_ours_is_reported_and_does_not_stop_the_restore(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE)
    h.record("# containers: not ids at all\ndocker.socket enabled inactive\ndocker enabled active\ncontainerd enabled inactive\n")
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "'# containers:' line is not one of ours" in r.stderr and "starts none" in r.stderr
    assert not h.state.exists() and not h.marker.exists()


def test_unknown_when_docker_ps_fails_both_ways_refuses_unless_allow_containers_is_1(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.d / "ps.fail", "")
    r = h.stop()
    assert "the running containers cannot be listed" in r.stderr and "ALLOW_CONTAINERS=1" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)
    # tried directly, then under sudo -n, both through timeout 10 -- and fail closed
    assert h.sudo_calls() == ["-n timeout 10 " + DOCKER_CMD]
    assert h.docker_calls() == [DOCKER_ARGS + " via=direct docker=active", DOCKER_ARGS + " via=1 docker=active"]
    assert h.timeout_calls() == ["10 " + DOCKER_CMD] * 2
    # allowed: goes on, and the record says it did not know
    r = h.run("stop", _posix(h.state), env=_allow(h))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "recorded as unknown" in r.stderr and h.containers_line() == "# containers: unknown"
    assert h.actives() == ["inactive"] * 3
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "containers at stop: unknown (they could not be listed); restore starts none" in r.stderr
    h.check_no_persistent_change()


def test_the_container_list_falls_back_to_sudo_when_the_direct_call_is_refused(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.d / "ps.needs-sudo", "")
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.containers_line() == "# containers: none"
    assert h.sudo_calls()[0] == "-n timeout 10 " + DOCKER_CMD
    assert h.docker_calls() == [DOCKER_ARGS + " via=direct docker=active", DOCKER_ARGS + " via=1 docker=active"]
    h.check_no_persistent_change()


def test_a_container_seen_only_through_sudo_refuses_a_stop_too(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.d / "ps.needs-sudo", "")
    h.containers(CID3)
    r = h.stop()
    assert "refused: 1 running container(s)" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)
    assert h.units_changed() == [] and h.sudo_calls() == ["-n timeout 10 " + DOCKER_CMD]


def test_every_docker_call_goes_to_the_system_daemon_whatever_the_callers_client_configuration_says(tmp_path):
    """DOCKER_HOST, DOCKER_CONTEXT and DOCKER_CONFIG point elsewhere (Host sets them in every test): the
    docker stub sees all three unset, and -H unix:///run/docker.sock, on every call -- stop's direct call,
    its sudo -n fallback (the stub sudo passes the environment on, so only the `env -u` removes them there)
    and restore's report."""
    h = Host(tmp_path, ALL_ACTIVE)
    for k in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG"):
        assert h.env[k], "the test's own environment must set %s, or nothing is being proved" % k
    _write(h.d / "ps.needs-sudo", "")           # the direct call fails, so the sudo one is made as well
    h.containers(CID1)
    r = h.run("stop", _posix(h.state), env=_allow(h))
    assert r.returncode == 0, r.stdout + r.stderr
    r = h.restore()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "containers at stop: 1" in r.stderr
    assert h.docker_calls() == [DOCKER_ARGS + " via=direct docker=active", DOCKER_ARGS + " via=1 docker=active"] * 2
    assert h.docker_env_calls() == [ENV_UNSET] * 4
    assert h.timeout_calls() == ["10 " + DOCKER_CMD] * 4
    assert [c for c in h.sudo_calls() if c.startswith("-n timeout")] == ["-n timeout 10 " + DOCKER_CMD] * 2
    h.check_no_persistent_change()
    # the control: the stub does see the environment when nothing removes it
    subprocess.run([BASH, _posix(h.bin / "docker")] + DOCKER_ARGS.split(), capture_output=True, env=h.env, timeout=60)
    assert h.docker_env_calls()[-1] == "host=tcp://203.0.113.9:2375 context=remote-elsewhere config=%s" % _posix(tmp_path / "docker-config-elsewhere")


def test_a_docker_that_never_answers_is_unknown_not_none(tmp_path):
    """timeout expires (exit 124) on both calls: a wedged dockerd must not read as an empty list."""
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.d / "timeout.expire", "")
    r = h.stop()
    assert "the running containers cannot be listed" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)
    assert h.timeout_calls() == ["10 " + DOCKER_CMD] * 2 and h.docker_calls() == []


@pytest.mark.parametrize("junk", ["Cannot connect to the Docker daemon", "abc123", "A" * 64, "sha256:" + "a" * 64,
                                  CID1 + " " + CID2, CID1 + "x"])
def test_output_that_is_no_container_id_is_unknown_not_none_and_not_dropped(tmp_path, junk):
    h = Host(tmp_path, ALL_ACTIVE)
    h.containers(CID1, junk)
    r = h.stop()
    assert "the running containers cannot be listed" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


@pytest.mark.parametrize("docker", [("enabled", "inactive"), ("enabled", "failed"), None])
def test_docker_that_is_not_active_is_not_asked_and_is_recorded_as_none(tmp_path, docker):
    """`docker ps` against a stopped docker with its socket up would start dockerd: never asked."""
    units = {"docker.socket": ("enabled", "active"), "containerd": ("enabled", "active")}
    if docker is not None:
        units["docker"] = docker
    h = Host(tmp_path, units)
    h.containers(CID1)            # would refuse, if it were asked
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.docker_calls() == [] and h.timeout_calls() == [] and h.containers_line() == "# containers: none"


def test_stop_stops_nothing_when_the_containers_line_does_not_read_back_as_written(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _stub(h.bin / "sync", 'sed -i "s/^# containers: none$/# containers: unknown/" "%s"' % _posix(h.state))
    r = h.stop()
    assert r.returncode == 1 and "its containers line differs" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3, rc=1)


# ------------------------------------------------------------ the dependents

DEPS_SHOW = "show -p RequiredBy -p BoundBy -p ConsistsOf -p RequisiteOf -p WantedBy %s"
# The order systemd prints the five in, whatever order they were asked for in.
SYSTEMD_ORDER = ("RequiredBy", "RequisiteOf", "WantedBy", "BoundBy", "ConsistsOf")


def _deps(h, unit, **props):
    """What the five-property `show` prints for the unit, as systemd prints it: a Key=Value line for each of
    the five, in systemd's own order (RequiredBy, RequisiteOf, WantedBy, BoundBy, ConsistsOf), with an empty
    value for a property that has no names (a property that was asked for is printed even when empty)."""
    assert set(props) <= set(SYSTEMD_ORDER), props
    _write(h.d / (unit + ".deps"), "".join("%s=%s\n" % (k, props.get(k, "")) for k in SYSTEMD_ORDER))


def _deps_raw(h, unit, *lines):
    """Exactly these lines, in this order: for what the script must not depend on."""
    _write(h.d / (unit + ".deps"), "".join(l + "\n" for l in lines))


def _app_host(tmp_path, state="active", extra=None):
    units = dict(ALL_ACTIVE)
    units["app.service"] = ("enabled", state)
    units.update(extra or {})
    return Host(tmp_path, units)


def test_stop_refuses_while_an_active_unit_requires_docker_and_names_it(tmp_path):
    h = _app_host(tmp_path)
    _deps(h, "docker", RequiredBy="app.service", WantedBy="multi-user.target")
    r = h.stop()
    assert "docker has dependents that are not inactive: app.service (active)" in r.stderr, r.stderr
    assert "nothing was stopped, no record and no marker was written" in r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)
    assert h.active("app.service") == "active"


def test_an_inactive_dependent_does_not_refuse_and_the_dependents_are_read_without_sudo(tmp_path):
    h = _app_host(tmp_path, "inactive")
    _deps(h, "docker", RequiredBy="app.service", WantedBy="multi-user.target")
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    calls = h.systemctl_calls()
    for u in ("docker.socket", "docker", "containerd"):
        assert DEPS_SHOW % u in calls
    assert h.sudo_calls() == ["-n systemctl stop --no-block docker.socket docker containerd"], "no sudo for a read"
    h.check_no_persistent_change()


def test_a_failed_dependent_does_not_refuse(tmp_path):
    h = _app_host(tmp_path, "failed")
    _deps(h, "containerd", BoundBy="app.service")
    assert h.stop().returncode == 0


@pytest.mark.parametrize("state,word", [("activating", "activating"), ("deactivating", "deactivating"),
                                        ("reloading", "reloading"), ("", "unknown")])
def test_a_dependent_that_is_neither_inactive_nor_failed_refuses_too(tmp_path, state, word):
    h = _app_host(tmp_path, state)
    _deps(h, "docker.socket", WantedBy="app.service")
    r = h.stop()
    assert "app.service (%s)" % word in r.stderr and "docker.socket has dependents" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


def test_targets_and_the_three_units_themselves_are_not_dependents(tmp_path):
    """Stopping does not affect multi-user.target or sockets.target, and docker.service requires
    docker.socket and containerd.service: neither is a reason to refuse."""
    h = _app_host(tmp_path, "inactive", extra={"multi-user.target": ("static", "active"),
                                                 "sockets.target": ("static", "active"),
                                                 "shutdown.target": ("static", "active")})
    _deps(h, "docker.socket", RequiredBy="docker.service", WantedBy="sockets.target")
    _deps(h, "docker", WantedBy="multi-user.target shutdown.target")
    _deps(h, "containerd", RequiredBy="docker.service docker", WantedBy="multi-user.target containerd docker.socket")
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.sudo_calls() == ["-n systemctl stop --no-block docker.socket docker containerd"]


TARGETS = {"multi-user.target": ("static", "active"), "sockets.target": ("static", "active")}


def test_an_active_target_under_wantedby_is_ignored_and_never_asked_about(tmp_path):
    h = _app_host(tmp_path, "inactive", extra=TARGETS)
    _deps(h, "docker", WantedBy="multi-user.target")
    _deps(h, "containerd", WantedBy="multi-user.target")
    _deps(h, "docker.socket", WantedBy="sockets.target")
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert not any(c.startswith("is-active") and c.endswith(".target") for c in h.systemctl_calls())
    h.check_no_persistent_change()


@pytest.mark.parametrize("prop", ["RequiredBy", "BoundBy", "ConsistsOf", "RequisiteOf"])
def test_an_active_target_under_any_property_but_wantedby_refuses_like_any_other_dependent(tmp_path, prop):
    """A target that requires, is bound to, consists of or requisites the unit depends on it for real."""
    h = _app_host(tmp_path, "inactive", extra={"app.target": ("static", "active")})
    _deps(h, "docker", **{prop: "app.target"})
    r = h.stop()
    assert "docker has dependents that are not inactive: app.target (active)" in r.stderr, r.stderr
    assert "nothing was stopped, no record and no marker was written" in r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


@pytest.mark.parametrize("prop", ["RequiredBy", "BoundBy"])
@pytest.mark.parametrize("state", ["inactive", "failed"])
def test_a_target_under_requiredby_or_boundby_that_is_inactive_or_failed_does_not_refuse(tmp_path, prop, state):
    """It counts like any other dependent, so it is judged by its state, not by its name."""
    h = _app_host(tmp_path, "inactive", extra={"app.target": ("static", state)})
    _deps(h, "docker", **{prop: "app.target"})
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "is-active app.target" in h.systemctl_calls()


ORDERS = [SYSTEMD_ORDER, tuple(reversed(SYSTEMD_ORDER)), ("BoundBy", "WantedBy", "ConsistsOf", "RequiredBy", "RequisiteOf")]


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("props,refused", [
    ({"WantedBy": "multi-user.target"}, False),                                        # a want: ignored
    ({"RequiredBy": "multi-user.target"}, True),                                       # a requirement: judged
    ({"WantedBy": "multi-user.target", "RequiredBy": "multi-user.target"}, True),      # judged by the second
    ({"ConsistsOf": "multi-user.target", "WantedBy": "multi-user.target"}, True),
])
def test_the_order_of_the_property_lines_does_not_matter_to_the_verdict(tmp_path, order, props, refused):
    """systemd prints the five in its own order, not the one they were asked for in: a name is judged by the
    property it is under, whichever line comes first, and a target skipped under WantedBy is not thereby
    skipped under another."""
    h = _app_host(tmp_path, "inactive", extra=TARGETS)
    _deps_raw(h, "docker", *["%s=%s" % (k, props.get(k, "")) for k in order])
    r = h.stop()
    if refused:
        assert "docker has dependents that are not inactive: multi-user.target (active)" in r.stderr, r.stderr
        h.nothing_written_or_stopped(r, still=["active"] * 3)
    else:
        assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("text", ["Id=docker.service", "no equals sign here", "requiredby=app.service", "app.service"])
def test_a_line_that_is_not_one_of_the_five_properties_is_a_refusal_not_a_pass(tmp_path, text):
    """`--value` output (bare names), another property or a garbled line is not a list that was read."""
    h = _app_host(tmp_path, "inactive")
    _deps_raw(h, "docker", "RequiredBy=", text)
    r = h.stop()
    assert "cannot read what depends on docker" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


def test_stop_names_every_active_dependent_across_the_five_properties_once(tmp_path):
    h = _app_host(tmp_path, extra={"b.service": ("enabled", "active"), "c.service": ("enabled", "active"),
                                    "idle.service": ("enabled", "inactive")})
    _deps(h, "docker", RequiredBy="app.service b.service", BoundBy="idle.service", ConsistsOf="c.service",
          RequisiteOf="app.service", WantedBy="b.service")
    r = h.stop()
    assert "app.service (active) b.service (active) c.service (active) --" in r.stderr, r.stderr
    # app.service and b.service are each listed under two properties: named once, not once per property
    for name in ("app.service", "b.service", "c.service"):
        assert r.stderr.count(name) == 1, (name, r.stderr)
    assert r.stderr.count("(active)") == 3 and r.stderr.count("dependents that are not inactive") == 1, r.stderr
    assert "idle.service" not in r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


def test_a_dependent_of_containerd_alone_refuses_too(tmp_path):
    h = _app_host(tmp_path)
    _deps(h, "containerd", BoundBy="app.service")
    r = h.stop()
    assert "containerd has dependents that are not inactive: app.service (active)" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


@pytest.mark.parametrize("name", ["bad;name.service", "-x.service", 'q"uote.service', "a$(x).service"])
def test_a_dependent_name_outside_the_safe_alphabet_refuses_and_is_never_run(tmp_path, name):
    h = Host(tmp_path, ALL_ACTIVE)
    _deps(h, "docker", RequiredBy=name)
    r = h.stop()
    assert "(name not readable)" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)
    assert not any(name in c for c in h.systemctl_calls() if c.startswith("is-active")), "the name was never asked about"


def test_a_dependent_with_an_escaped_or_templated_name_is_asked_about(tmp_path):
    """systemd escapes with a backslash and templates with @: both are ordinary unit names."""
    h = Host(tmp_path, ALL_ACTIVE)
    _deps(h, "docker", RequiredBy="app@1.service", BoundBy="dev-sda1.mount", ConsistsOf="var-lib-foo" + chr(92) + "x2dbar.mount")
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr          # all three read inactive
    calls = h.systemctl_calls()
    assert "is-active app@1.service" in calls and "is-active var-lib-foo" + chr(92) + "x2dbar.mount" in calls


def test_stop_refuses_when_the_dependents_of_a_unit_cannot_be_read(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE, marks=[("docker", "depfail")])
    r = h.stop()
    assert "cannot read what depends on docker" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)


def test_the_dependents_of_a_unit_the_host_does_not_have_are_not_read(tmp_path):
    h = Host(tmp_path, {"containerd": ("enabled", "active")})
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c for c in h.systemctl_calls() if "RequiredBy" in c] == [DEPS_SHOW % "containerd"]


def test_every_reason_of_one_pass_is_printed_before_the_one_refusal(tmp_path):
    h = _app_host(tmp_path)
    _deps(h, "docker", RequiredBy="app.service")
    h.containers(CID1)
    r = h.stop()
    assert "app.service (active)" in r.stderr and "refused: 1 running container(s)" in r.stderr, r.stderr
    assert r.stderr.count("nothing was stopped, no record and no marker was written") == 1
    h.nothing_written_or_stopped(r, still=["active"] * 3)


def test_a_unit_that_has_not_settled_is_refused_before_anything_is_asked_about_its_dependents(tmp_path):
    h = Host(tmp_path, {"docker.socket": ("enabled", "activating"), "docker": ("enabled", "active"),
                        "containerd": ("enabled", "active")})
    r = h.stop()
    assert "unit docker.socket is activating; wait until it settles and rerun" in r.stderr
    h.nothing_written_or_stopped(r)
    assert not any("RequiredBy" in c for c in h.systemctl_calls()) and h.docker_calls() == []


# ------------------------------------------------------------ the bounded stop

def test_stop_is_queued_without_blocking_and_polled_until_the_unit_is_down(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE, marks=[("docker", "slowstop")])
    r = h.stop()
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.sudo_calls() == ["-n systemctl stop --no-block docker.socket docker containerd"]
    assert _lines(r)[1] == "docker: was enabled/active, now inactive ok"
    assert "not down" not in r.stderr
    calls = h.systemctl_calls()
    after = calls[calls.index("stop --no-block docker.socket docker containerd"):]
    assert after.count("is-active docker") >= 3, "it polled, not once"
    assert h.state.exists() and h.marker.exists()
    h.check_no_persistent_change()


def test_a_unit_that_never_stops_is_not_stopped_after_the_deadline_not_a_hang(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE, marks=[("docker", "unstoppable")])
    t0 = time.monotonic()
    r = h.run("stop", _posix(h.state), env=dict(h.env, STOP_DEADLINE_S="1"))
    elapsed = time.monotonic() - t0
    assert r.returncode == 1, r.stdout + r.stderr
    assert _lines(r)[1] == "docker: was enabled/active, now active NOT STOPPED"
    assert _lines(r)[0].endswith(" ok") and _lines(r)[2].endswith(" ok")
    assert "docker is not down 1 s after its stop was queued" in r.stderr
    assert h.state.exists() and h.marker.read_text() == h.abs_state + "\n", "the record and the marker stay"
    assert elapsed < 20, "the deadline, not the unit, ends the wait"
    h.check_no_persistent_change()


def test_a_stop_call_that_itself_fails_is_not_polled_for_the_deadline(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _stub(h.bin / "sudo", "exit 1")
    t0 = time.monotonic()
    r = h.run("stop", _posix(h.state), env=dict(h.env, STOP_DEADLINE_S="30"))
    assert r.returncode == 1 and r.stdout.count("NOT STOPPED") == 3
    assert "'sudo -n systemctl stop --no-block docker.socket docker containerd' failed" in r.stderr
    assert time.monotonic() - t0 < 20
    assert h.state.exists() and h.marker.exists()


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "1234567", " 5"])
def test_a_stop_deadline_that_is_not_a_whole_number_refuses_before_anything_is_written(tmp_path, value):
    h = Host(tmp_path, ALL_ACTIVE)
    r = h.run("stop", _posix(h.state), env=dict(h.env, STOP_DEADLINE_S=value))
    assert "STOP_DEADLINE_S" in r.stderr and "nothing was stopped" in r.stderr, r.stderr
    h.nothing_written_or_stopped(r, still=["active"] * 3)
    assert not h.xdg.exists(), "not even the marker's directory"


def test_an_empty_or_zero_padded_stop_deadline_is_the_design_value_or_a_decimal(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    r = h.run("stop", _posix(h.state), env=dict(h.env, STOP_DEADLINE_S=""))       # empty means unset
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.restore().returncode == 0
    r = h.run("stop", _posix(h.state), env=dict(h.env, STOP_DEADLINE_S="08"))     # 08 is no octal number
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_stop_deadline_of_zero_asks_once(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE, marks=[("docker", "slowstop")])
    r = h.run("stop", _posix(h.state), env=dict(h.env, STOP_DEADLINE_S="0"))
    assert r.returncode == 1 and "docker: was enabled/active, now deactivating NOT STOPPED" in r.stdout


# ------------------------------------------------------------ the marker race

@pytest.mark.parametrize("when", ["after-the-record", "at-the-first-mkdir"])
def test_a_marker_planted_after_the_check_is_left_alone_and_nothing_is_stopped(tmp_path, when):
    """A `mkdir` that runs the real one and then plants another stop's marker: once the record is written
    (the last moment before the write), or at the first call (before anything is read)."""
    h = Host(tmp_path, ALL_ACTIVE)
    planted = "/planted/by/another/stop.state"
    cond = '[ -e "%s" ] && ' % _posix(h.state) if when == "after-the-record" else ""
    _stub(h.bin / "mkdir", '"%s" "$@" || exit $?\n%s[ ! -e "%s" ] && printf "%%s\\n" "%s" > "%s"\nexit 0'
          % (_posix(shutil.which("mkdir")), cond, _posix(h.marker), planted, _posix(h.marker)))
    r = h.stop()
    assert r.returncode == 1, r.stdout + r.stderr
    assert "cannot write the marker" in r.stderr and "it holds '%s'" % planted in r.stderr, r.stderr
    assert "the record was removed" in r.stderr
    assert h.marker.read_text() == planted + "\n", "the planted marker is not ours to change or remove"
    assert not h.state.exists(), "stop's own record is removed"
    assert h.sudo_calls() == [] and r.stdout == "" and h.actives() == ["active"] * 3


# ------------------------------------------------------------ the marker's directory

def test_the_recommended_fixed_path_works_on_a_home_without_local_state(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in h.env.items() if k != "XDG_STATE_HOME"}
    state = home / ".local" / "state" / "platform-quiesce.state"
    assert not state.parent.exists()
    prog = 'S="${XDG_STATE_HOME:-$HOME/.local/state}/platform-quiesce.state"; bash "$1" "$2" "$S"'
    r = subprocess.run([BASH, "-c", prog, "x", SCRIPT, "stop"], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert state.is_file() and (state.parent / "platform-quiesce.active").read_text() == _abs(state) + "\n"
    r = subprocess.run([BASH, "-c", prog, "x", SCRIPT, "restore"], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not state.exists() and not (state.parent / "platform-quiesce.active").exists()


def test_a_state_file_in_a_marker_directory_that_does_not_exist_yet_works(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    assert not h.xdg.exists()
    state = h.xdg / "quiesce.state"
    r = h.stop(state)
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.marker.read_text() == _abs(state) + "\n"
    assert h.restore(state).returncode == 0


def test_the_state_files_directory_is_created_only_when_it_is_the_marker_directory(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    r = h.stop(tmp_path / "other" / "deep" / "quiesce.state")
    assert "its directory must exist" in r.stderr, r.stderr
    assert not (tmp_path / "other").exists(), "any other directory must exist already"
    h.nothing_written_or_stopped(r, still=["active"] * 3)
    assert h.xdg.is_dir() and not any(h.xdg.iterdir()), "the marker's directory is all a refusal leaves, empty"


def test_a_marker_directory_that_cannot_be_created_refuses_before_anything_is_written(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    _write(h.xdg, "a file where the marker's directory should be\n")
    r = h.stop()
    assert "cannot write the marker" in r.stderr and "nothing was stopped, and nothing was written" in r.stderr, r.stderr
    assert h.sudo_calls() == [] and h.actives() == ["active"] * 3 and not h.state.exists() and r.stdout == ""


# ------------------------------------------------------------ how a harness uses it

def _header_prose():
    with open(SCRIPT, encoding="utf-8") as f:
        text = f.read()
    return re.sub(r"\s*\n#\s*", " ", text.split("set -u")[0])


def test_the_header_tells_harnesses_to_put_the_restore_in_their_one_cleanup_and_what_each_exit_status_means(tmp_path):
    header = _header_prose()
    # bash keeps one EXIT trap: the restore goes into the harness's cleanup(), behind a flag set BEFORE stop
    assert "bash keeps ONE EXIT trap, and every measuring run-*.sh already has `trap cleanup EXIT`" in header
    assert "an orchestrator such as run-shift-isolation.sh" in header and "leaves the quiesce to the harness it runs" in header
    assert "What keeps two runs from overlapping on S in the first place is the harness's own run lock" in header
    assert "So the restore goes INTO that cleanup(); it does not get a trap of its own" in header
    assert "Never `trap - EXIT`: it drops the harness's own cleanup with it. Never a second EXIT trap: it replaces the first" in header
    assert "A flag is set BEFORE stop is called, cleanup() restores when the flag is set" in header
    assert "QUIESCE_STATE is set before the trap is armed, because the harnesses run with nounset" in header
    assert "Arm `trap" not in header and "disarm" not in header, "the trap-based advice is gone"
    # the four statuses
    assert "EXIT STATUS. 0: all as intended. 3 (stop only): stop REFUSED before it wrote or stopped anything" in header
    assert "every refusal path" in header and "restore exits 0 or 1, never 3" in header and "2: wrong usage" in header
    assert "1: not as intended, and for stop it MAY HAVE CHANGED THE HOST: a unit NOT STOPPED, or a failure after the record was written" in header
    # what a harness does with 3, with 1 and with 0
    assert 'rc=0; platform-quiesce.sh stop "$S" || rc=$? [ "$rc" != 3 ] || QUIESCE_STATE="" [ "$rc" = 0 ] || exit "$rc"' in header
    assert "On 3, clear the flag" in header and "may belong to ANOTHER run that is still measuring" in header
    assert "a restore run by this harness's cleanup() would find the marker naming S" in header
    assert "On 1, keep the flag" in header and 'Never read a stop that exits 1 as "nothing happened"' in header
    assert "On 0, keep the flag" in header
    assert "Any status but 0 ends the run" in header
    # where in cleanup(), and the process group
    assert "The restore goes after QEMU is stopped and before the governor is restored" in header
    assert "Signal a harness's process group, never its PID alone" in header
    assert "a stop it is running is its child" in header and "the stop can then outlive the cleanup" in header
    assert "Keeping the flag on a 1 costs nothing when stop did not get as far as writing the marker" in header
    assert "restore then refuses harmlessly (starts nothing, removes nothing) when there is no marker" in header
    assert "when the marker names another record" in header
    assert ("STATEFILE's own directory is created only when it is the marker's directory; otherwise it must exist"
            in header)
    assert "before the state file's path is made absolute" in header and "(mkdir -p)" in header
    assert "ALLOW_CONTAINERS=1 (exactly 1)" in header
    # the docker call: the system daemon only
    assert ("`timeout 10 env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_CONFIG docker -H unix:///run/docker.sock ps -q --no-trunc`"
            in header)
    assert "SYSTEM daemon" in header and "It never talks to a docker daemon but the system one" in header
    # the report at restore: for a record of none too, and never for a file with no containers line
    assert "`running now, not at stop: <ids|none>`" in header
    assert "A record of `none` gets the same report, as `containers at stop: 0; running now, not at stop: <ids|none>; restore starts none`" in header
    assert "a restart=always container was not running at stop" in header
    assert "says `running now, not at stop: not known`" in header
    assert "A record with no containers line at all gets no report and no question" in header
    # the dependents: Key=Value, no --value, targets exempt only under WantedBy
    assert "-p RequiredBy -p BoundBy -p ConsistsOf -p RequisiteOf -p WantedBy UNIT` -- Key=Value lines" in header
    assert "never `--value`" in header and "A *.target is exempt ONLY under WantedBy" in header
    assert "--value UNIT" not in header.split("THE DEPENDENTS. For each")[1]


CLEAR_ON_3 = '[ "$rc" != 3 ] || QUIESCE_STATE=""'


def _sketch():
    """The harness the header sketches: the indented lines under HARNESS USE, verbatim."""
    with open(SCRIPT, encoding="utf-8") as f:
        lines = f.read().split("set -u")[0].splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith("# HARNESS USE."))
    code = []
    for l in lines[i:]:
        if l == "#":
            break
        if l.startswith("#     "):
            code.append(l[len("#     "):])
    assert code and code[-2:] == [CLEAR_ON_3, '[ "$rc" = 0 ] || exit "$rc"'], code
    return code


def test_the_sketch_has_one_exit_trap_and_its_restore_is_in_the_cleanup_behind_a_flag_set_before_stop(tmp_path):
    code = _sketch()
    assert [l for l in code if "trap" in l] == ["trap cleanup EXIT"], "one EXIT trap: the harness's own, never `trap - EXIT`"
    at = {}
    for n, l in enumerate(code):
        for key, needle in (("init", 'QUIESCE_STATE=""'), ("def", "cleanup() {"), ("qemu", "stop_vm"),
                            ("restore", 'platform-quiesce.sh restore "$QUIESCE_STATE"'), ("governor", "m_governor_restore"),
                            ("trap", "trap cleanup EXIT"), ("flag", 'QUIESCE_STATE="$S"'),
                            ("stop", 'platform-quiesce.sh stop "$S"'), ("clear", CLEAR_ON_3)):
            if l.strip() == needle or (key in ("restore", "stop") and needle in l):
                assert key not in at, "%s twice: %r" % (key, code)
                at[key] = n
    assert set(at) == {"init", "def", "qemu", "restore", "governor", "trap", "flag", "stop", "clear"}, (at, code)
    # the flag exists before the trap is armed (nounset), and is set before stop is called; cleanup() is
    # defined before the trap names it; and in cleanup() QEMU comes first, then the platform, then the governor
    assert at["init"] < at["def"] < at["qemu"] < at["restore"] < at["governor"] < at["trap"] < at["flag"] < at["stop"] < at["clear"], at
    assert code[at["governor"] + 1] == "}"


def _run_sketch(h, *, clear_on_3=True, after="", shell_opts="-u", env=None):
    """The header's sketch, verbatim, inside a harness-shaped script: the harness's own stop_vm and
    m_governor_restore (stand-ins: each logs its name to h.order_log, and the governor one leaves
    h.governor_mark), then the sketch with `platform-quiesce.sh` on PATH (a wrapper that logs a restore call),
    then `after`, the rest of the harness. clear_on_3=False drops the line that clears the flag on a 3."""
    _stub(h.bin / "platform-quiesce.sh", '[ "$1" != restore ] || echo quiesce-restore >> "$ORDER_LOG"\nexec bash "%s" "$@"' % SCRIPT)
    code = [l for l in _sketch() if clear_on_3 or l != CLEAR_ON_3]
    prelude = ('set %s\nstop_vm() { echo qemu >> "$ORDER_LOG"; }\n'
               'm_governor_restore() { echo governor >> "$ORDER_LOG"; : > "$GOVERNOR_MARK"; }\n' % shell_opts)
    e = dict(h.env if env is None else env, ORDER_LOG=_posix(h.order_log), GOVERNOR_MARK=_posix(h.governor_mark))
    return subprocess.run([BASH, "-c", prelude + "\n".join(code) + "\n" + after], capture_output=True, text=True,
                          env=e, timeout=120)


def _harness(h, state):
    """A harness with the flag set BEFORE stop and never cleared, whatever stop says, on a state path of its own
    choosing (the header's sketch always uses the fixed one): its cleanup() restores at exit."""
    prog = ('S="$1"; Q="$2"; QUIESCE_STATE="$S"\n'
            'cleanup() { [ -z "$QUIESCE_STATE" ] || bash "$Q" restore "$QUIESCE_STATE"; }\n'
            'trap cleanup EXIT\nbash "$Q" stop "$S"')
    return subprocess.run([BASH, "-c", prog, "x", _posix(state), SCRIPT], capture_output=True, text=True,
                          env=h.env, timeout=120)


def test_the_sketch_in_the_header_runs_a_clean_run_start_to_finish(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    r = _run_sketch(h)
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.sudo_calls()[0] == "-n systemctl stop --no-block docker.socket docker containerd"
    assert h.actives() == ["active"] * 3, "the restore in cleanup() put them back at exit"
    assert not (h.xdg / "platform-quiesce.state").exists() and not h.marker.exists()
    assert "restored; " in r.stderr
    h.check_no_persistent_change()


DIE = 'die() { echo "harness: died after stop" >&2; exit 7; }\ndie\n'


@pytest.mark.parametrize("how,rc", [("clean run", 0), ("stop exits 1", 1), ("stop exits 3", 3), ("die after stop", 7)])
def test_the_harnesss_cleanup_does_both_of_its_restores_on_every_exit_path(tmp_path, how, rc):
    """One EXIT trap, the harness's own, and a flag: whatever way the harness leaves, its cleanup() runs and does
    its own restore (the governor marker) -- and the platform's, unless stop was refused (3: nothing to undo)."""
    h = Host(tmp_path, ALL_ACTIVE, marks=[("docker", "unstoppable")] if how == "stop exits 1" else [])
    if how == "stop exits 3":
        h.containers(CID1)
    r = _run_sketch(h, after=DIE if how == "die after stop" else "")
    assert r.returncode == rc, r.stdout + r.stderr
    assert h.governor_mark.exists(), "the harness's own restore ran on this exit path"
    assert not (h.xdg / "platform-quiesce.state").exists() and not h.marker.exists()
    if how == "stop exits 3":
        assert "refused: 1 running container(s)" in r.stderr
        assert h.cleanup_order() == ["qemu", "governor"], "no platform restore: stop refused, nothing was changed"
        assert "restored;" not in r.stderr and "nothing to restore" not in r.stderr, "the platform restore never ran"
        assert not any(c.startswith(("start", "stop")) for c in h.systemctl_calls())
        assert h.units_changed() == [] and h.actives() == ["active"] * 3
    else:
        assert h.cleanup_order() == ["qemu", "quiesce-restore", "governor"], "QEMU, then the units, then the governor"
        assert "restored; " in r.stderr and h.actives() == ["active"] * 3
        if how == "stop exits 1":
            assert "docker: was enabled/active, now active NOT STOPPED" in r.stdout, "some units were stopped, some not"
        if how == "die after stop":
            assert "harness: died after stop" in r.stderr
    h.check_no_persistent_change()


def test_a_restore_that_fails_in_the_cleanup_does_not_skip_the_rest_of_it_even_under_set_e(tmp_path):
    """docker will not start: restore exits 1 and keeps the record and the marker, cleanup() says so and still
    does the governor's restore, and the harness leaves with the status it had."""
    h = Host(tmp_path, ALL_ACTIVE, marks=[("docker", "stuck")])
    r = _run_sketch(h, shell_opts="-eu")
    assert r.returncode == 0, r.stdout + r.stderr
    assert h.cleanup_order() == ["qemu", "quiesce-restore", "governor"] and h.governor_mark.exists()
    assert "WARNING: platform-quiesce restore failed" in r.stderr and "MISMATCH" in r.stdout + r.stderr
    assert (h.xdg / "platform-quiesce.state").exists() and h.marker.exists(), "both stay for another restore"


def test_a_second_harness_refused_on_the_fixed_state_path_leaves_the_first_ones_record_and_marker_alone(tmp_path):
    """The reason for the 3: a harness uses one fixed S, so while a first run is stopped and measuring, the
    marker names that same S. The second run's stop is refused (3); its sketch clears the flag; nothing is
    started or stopped, its cleanup() does only its own restores, and the first run's record and marker are
    byte for byte what they were."""
    h = Host(tmp_path, ALL_ACTIVE)
    fixed = h.xdg / "platform-quiesce.state"
    assert h.stop(fixed).returncode == 0                        # the first run: units down, record and marker held
    record, marker = fixed.read_bytes(), h.marker.read_bytes()
    assert marker == (_abs(fixed) + "\n").encode() and h.actives() == ["inactive"] * 3
    sudo_calls, systemctl_calls = h.sudo_calls(), h.systemctl_calls()
    r = _run_sketch(h)
    assert r.returncode == 3 and "earlier stop is outstanding" in r.stderr, r.stdout + r.stderr
    assert "restored;" not in r.stderr and "nothing to restore" not in r.stderr, "no restore ran"
    assert h.cleanup_order() == ["qemu", "governor"] and h.governor_mark.exists(), "cleanup() ran, and did its own restores only"
    assert fixed.read_bytes() == record and h.marker.read_bytes() == marker
    assert h.sudo_calls() == sudo_calls, "nothing started, nothing stopped"
    assert not any(c.startswith(("start", "stop")) for c in h.systemctl_calls()[len(systemctl_calls):])
    assert h.actives() == ["inactive"] * 3 and r.stdout == ""
    # the first run then ends as it should
    assert h.restore(fixed).returncode == 0 and h.actives() == ["active"] * 3


def test_a_flag_left_set_on_a_3_would_start_the_first_runs_units_under_it(tmp_path):
    """What clearing the flag is for. The same two runs, but the second does not clear it: its cleanup()
    restore finds the marker naming the fixed S and puts the first run's units back while that run is still
    measuring."""
    h = Host(tmp_path, ALL_ACTIVE)
    fixed = h.xdg / "platform-quiesce.state"
    assert h.stop(fixed).returncode == 0
    r = _run_sketch(h, clear_on_3=False)
    assert r.returncode == 3 and "earlier stop is outstanding" in r.stderr, r.stdout + r.stderr
    assert h.cleanup_order() == ["qemu", "quiesce-restore", "governor"]
    assert h.actives() == ["active"] * 3, "the refused run's cleanup() restored the first run's record"
    assert not fixed.exists() and not h.marker.exists()


def test_a_restore_after_a_stop_refused_for_another_outstanding_record_touches_neither(tmp_path):
    """A flag that IS left set (a harness that does not read the status) finds the marker naming another record."""
    h = Host(tmp_path, ALL_ACTIVE)
    assert h.stop().returncode == 0                   # record A, the marker names it, the units are down
    b = tmp_path / "state" / "b.state"
    calls = len(h.sudo_calls())
    r = _harness(h, b)
    assert "earlier stop is outstanding" in r.stderr and "nothing to restore from" in r.stderr, r.stderr
    assert len(h.sudo_calls()) == calls and h.actives() == ["inactive"] * 3, "nothing stopped, nothing started"
    assert h.state.exists() and h.marker.read_text() == h.abs_state + "\n" and not b.exists()
    # and a record of B's own that the marker does not name is refused by the marker, and left alone
    text = "docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\n"
    _write(b, text)
    r = _harness(h, b)
    assert "names %s, not %s: nothing was started" % (h.abs_state, _abs(b)) in r.stderr, r.stderr
    assert len(h.sudo_calls()) == calls and h.actives() == ["inactive"] * 3 and b.read_text() == text
    assert h.state.exists() and h.marker.read_text() == h.abs_state + "\n"


# ------------------------------------------------------------ exit statuses

def _noop(h):
    pass


def _read_only_state_dir(h):
    """chmod 555 on the directory the record would go in. Root, and a filesystem that does not keep directory
    modes (Windows), can write there all the same and cannot show this refusal: the test skips."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores directory modes")
    os.chmod(h.state.parent, 0o555)
    probe = h.state.parent / ".probe"
    try:
        probe.write_text("x")
    except OSError:
        return
    probe.unlink()
    pytest.skip("this filesystem lets a 555 directory be written to")


# (id, what is arranged, environment changes, the state file's path relative to the test's directory or None)
REFUSALS = [
    ("container running", lambda h: h.containers(CID1), {}, None),
    ("containers cannot be listed", lambda h: _write(h.d / "ps.fail", ""), {}, None),
    ("active dependent", lambda h: _deps(h, "docker", RequiredBy="app.service"), {}, None),
    ("dependents cannot be read", lambda h: _write(h.d / "docker.depfail", ""), {}, None),
    ("unit in a transitional state", lambda h: h.set_active("docker", "activating"), {}, None),
    ("LoadState cannot be read", lambda h: _write(h.d / "docker.loadfail", ""), {}, None),
    ("marker held by another stop", lambda h: (h.xdg.mkdir(), _write(h.marker, "/elsewhere/quiesce.state\n")), {}, None),
    ("marker names nothing readable", lambda h: (h.xdg.mkdir(), _write(h.marker, "")), {}, None),
    ("state file exists", lambda h: _write(h.state, "keep me\n"), {}, None),
    ("bad deadline", _noop, {"STOP_DEADLINE_S": "abc"}, None),
    ("nowhere to put the marker", _noop, {"XDG_STATE_HOME": "relative/dir"}, None),
    ("marker directory cannot be created", lambda h: _write(h.xdg, "a file, not a directory\n"), {}, None),
    ("state directory missing", _noop, {}, "no-such-dir/state"),
    ("state directory read-only", _read_only_state_dir, {}, None),
]


@pytest.mark.parametrize("what,setup,env,state", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_every_refusal_path_of_stop_exits_3_and_leaves_the_host_as_found(tmp_path, what, setup, env, state):
    h = _app_host(tmp_path)               # app.service is active, and is nobody's dependent unless a test says so
    try:
        setup(h)
        path = h.state if state is None else tmp_path / state
        marker_before = h.marker.read_bytes() if h.marker.is_file() else None
        actives_before = h.actives()
        r = h.run("stop", _posix(path), env=dict(h.env, **env))
        assert r.returncode == 3, r.stdout + r.stderr
        assert h.units_changed() == [] and h.actives() == actives_before and r.stdout == ""
        assert (h.marker.read_bytes() if h.marker.is_file() else None) == marker_before, "a marker that was not ours is left as it was"
        if what == "state file exists":
            assert h.state.read_text() == "keep me\n"
        else:
            assert not path.exists()
    finally:
        os.chmod(h.state.parent, 0o755)   # the read-only row leaves a directory pytest could not clean up


def test_a_unit_that_will_not_stop_exits_1_though_others_were_stopped(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE, marks=[("docker", "unstoppable")])
    r = h.stop()
    assert r.returncode == 1 and r.stdout.count("NOT STOPPED") == 1
    assert h.actives() == ["inactive", "active", "inactive"], "a partial stop: the host has changed"
    assert h.state.exists() and h.marker.exists()


@pytest.mark.parametrize("failure", ["readback", "marker"])
def test_a_failure_after_the_record_was_written_exits_1_though_nothing_was_stopped(tmp_path, failure):
    """The record was written (and taken back again): stop can no longer say it wrote nothing."""
    h = Host(tmp_path, ALL_ACTIVE)
    if failure == "readback":
        _stub(h.bin / "sync", 'sed -i "s/^docker enabled active$/docker enabled inactive/" "%s"' % _posix(h.state))
    else:
        planted = "/planted/by/another/stop.state"
        _stub(h.bin / "mkdir", '"%s" "$@" || exit $?\n[ -e "%s" ] && [ ! -e "%s" ] && printf "%%s\\n" "%s" > "%s"\nexit 0'
              % (_posix(shutil.which("mkdir")), _posix(h.state), _posix(h.marker), planted, _posix(h.marker)))
    r = h.stop()
    assert r.returncode == 1, r.stdout + r.stderr
    assert h.units_changed() == [] and h.actives() == ["active"] * 3 and not h.state.exists()


def test_stop_and_restore_exit_0_when_all_is_as_intended(tmp_path):
    h = Host(tmp_path, ALL_ACTIVE)
    assert h.stop().returncode == 0 and h.restore().returncode == 0


def test_restore_exits_0_or_1_and_never_3(tmp_path):
    h = Host(tmp_path, ALL_INACTIVE)
    r = h.restore()                                                           # no record
    assert r.returncode == 1, r.stdout + r.stderr
    h.record("docker.socket enabled active\ndocker enabled active\ncontainerd enabled active\n")
    r = h.run("restore", _posix(h.state), env=dict(h.env, XDG_STATE_HOME="relative/dir"))   # nowhere to put the marker
    assert r.returncode == 1 and "not an absolute path" in r.stderr, r.stderr
    r = h.run("restore", _posix(h.state), env=dict(h.env, START_DEADLINE_S="abc"))          # a bad deadline
    assert r.returncode == 1 and "START_DEADLINE_S" in r.stderr, r.stderr
    assert h.sudo_calls() == []
