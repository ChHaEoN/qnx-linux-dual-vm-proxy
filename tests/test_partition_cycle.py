"""partition_cycle.sh (Phase 3b / A6, reviewed 2026-10-17): the PC-side orchestrator that reboots the
board and runs one board boot's harness after each reboot (run-randomise.sh by default; run-boots.sh
names this script as its reboot machinery).

Everything runs against stubs: `ssh` is a script that plays the board (its boot id, whether it is up,
what each call exits with), and PORT_CHECK plays port 22. Nothing here can reach a host. What is held:
  - the refusals before any call: no host, no key, no owner at the plug, a bad tag, a bad word;
  - one reboot, a bounded wait for port 22 to close and to open again with no login meanwhile, then
    ONE session per board boot; a stop, and no further reboot, on any failure;
  - a reboot that did not happen (the same boot id) is a stop;
  - the code never touches a boot entry, the bootloader, the kernel command line or nvpmodel, and
    carries no address or user of its own.
In the sandbox tests the stub `ssh` runs what it receives, locally, with the board's paths pointed into
tmp_path, `sudo` a stub and the bridge and the harness logging stubs: what the session does on the board,
and in which order -- the boot id, reset_reason and pstore first, before the settle wait, the bridge and
the harness -- is run, not read. Nothing reboots: the reboot is replaced by a log line.
"""
import os
import re
import shutil
import subprocess
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
CYCLE = os.path.join(GC, "partition_cycle.sh")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def _posix(p):
    return os.path.abspath(str(p)).replace("\\", "/")


def _stub(path, body):
    with open(str(path), "w", newline="\n") as f:
        f.write("#!/usr/bin/env bash\n" + body + "\n")
    os.chmod(str(path), 0o755)


# The board, in files under W: boot_id (the current boot), up (0/1), down_left / up_left (port checks
# the board stays up / down after a reboot is asked), rc.<tag> (what the session of that tag exits
# with), reboot_rc (what the reboot call exits with), same_id (a reboot that keeps the boot id).
SSH = r'''W="%(w)s"
cmd="${!#}"
echo "ssh $(echo "$*" | tr '\n' ' ')" >> "$W/calls.log"
case "$cmd" in
  *"systemctl reboot"*)
    echo "boot_id=$(cat "$W/boot_id")"
    rc=$(cat "$W/reboot_rc" 2>/dev/null || echo 0)
    [ "$rc" = 0 ] || exit "$rc"
    echo reboot-asked
    echo rebooting > "$W/phase"
    exit 0 ;;
  *"BOOT_TAG="*)
    tag=$(printf '%%s' "$cmd" | sed -n 's/.*BOOT_TAG=\(b[0-9]\).*/\1/p')
    echo "boot_id=$(cat "$W/boot_id")"
    echo "reset_reason=$(cat "$W/reset_reason")"
    echo "session $tag"
    exit "$(cat "$W/rc.$tag" 2>/dev/null || echo 0)" ;;
esac
echo "unexpected call" >&2
exit 99
'''

# The port check; on the way back up it gives the board a new boot id (unless same_id) and the next
# reset_reason of reset_next, when there is one.
PORT = r'''W="%(w)s"
echo "port $*" >> "$W/calls.log"
phase=$(cat "$W/phase" 2>/dev/null || echo up)
if [ "$phase" = rebooting ]; then
  n=$(cat "$W/down_left"); if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$W/down_left"; exit 0; fi
  echo down > "$W/phase"; exit 1
fi
if [ "$phase" = down ]; then
  n=$(cat "$W/up_left"); if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$W/up_left"; exit 1; fi
  echo up > "$W/phase"
  if [ ! -e "$W/same_id" ]; then printf '%%08x-0000-4000-8000-%%012x\n' "$RANDOM" "$RANDOM$RANDOM" > "$W/boot_id"; fi
  if [ -s "$W/reset_next" ]; then head -1 "$W/reset_next" > "$W/reset_reason"; sed -i 1d "$W/reset_next"; fi
  exit 0
fi
exit 0
'''

# The board, run: the received command is executed here with the board's paths pointed into W, HOME in
# W/home, `sudo` and `sync` stubs first on PATH, and the reboot replaced by a log line in W/board.log.
SANDBOX = r'''W="%(w)s"
cmd="${!#}"
echo "ssh $(echo "$*" | tr '\n' ' ')" >> "$W/calls.log"
orig="$cmd"
cmd="${cmd//\/proc\/sys\/kernel\/random\/boot_id/$W/boot_id}"
cmd="${cmd//\/proc\/uptime/$W/uptime}"
cmd="${cmd//\/sys\/fs\/pstore/$W/pstore}"
cmd="${cmd//\/sys\/devices\/platform\/bus@0\/c360000.pmc\/reset_reason/$W/reset_reason}"
cmd="${cmd//\/tmp\/partition-cycle-bridge-/$W/bridge-}"
cmd="${cmd//sleep 2; sudo -n systemctl reboot/echo REBOOT >> $W/board.log}"
env -u XDG_STATE_HOME HOME="$W/home" PATH="$W/boardbin:$PATH" bash -c "$cmd"
rc=$?
case "$orig" in *"systemctl reboot"*) [ "$rc" != 0 ] || echo rebooting > "$W/phase" ;; esac
exit "$rc"
'''


def _world(tmp_path, down_left=1, up_left=2, rcs=None, reboot_rc=0, same_id=False, never_down=False, never_up=False):
    w = tmp_path / "world"
    w.mkdir()
    (w / "boot_id").write_text("b0071d00-0000-4000-8000-000000000001\n")
    (w / "reset_reason").write_text("TEST_RESET\n")
    (w / "down_left").write_text("%d\n" % (10 ** 6 if never_down else down_left))
    (w / "up_left").write_text("%d\n" % (10 ** 6 if never_up else up_left))
    (w / "reboot_rc").write_text("%d\n" % reboot_rc)
    for tag, rc in (rcs or {}).items():
        (w / ("rc." + tag)).write_text("%d\n" % rc)
    if same_id:
        (w / "same_id").write_text("1")
    b = tmp_path / "bin"
    b.mkdir()
    _stub(b / "ssh", SSH % {"w": _posix(w)})
    _stub(b / "portcheck", PORT % {"w": _posix(w)})
    return w, b


def _run(tmp_path, tags, w, b, _cwd=None, _script=CYCLE, **env):
    e = dict(os.environ, HOST="tester@203.0.113.7", KEY=_posix(tmp_path / "key"), OWNER_AT_PLUG="1", REMOTE="~/qlv",
             PORT_CHECK=_posix(b / "portcheck"), POLL_S="0.01", DOWN_TRIES="6", UP_TRIES="6", EXPECT_RESET="TEST_RESET",
             LOGDIR=_posix(tmp_path / "logs"), PATH=_posix(b) + os.pathsep + os.environ.get("PATH", ""))
    (tmp_path / "key").write_text("not a key\n")
    for k, v in env.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    r = subprocess.run([BASH, str(_script)] + list(tags), capture_output=True, text=True, env=e, timeout=120,
                       cwd=None if _cwd is None else str(_cwd))
    r.calls = (w / "calls.log").read_text().splitlines() if (w / "calls.log").exists() else []
    return r


def _sandbox(tmp_path, reset="TEST_RESET", reset_next=(), pstore=(), same_id=False, uptime="900.00 1.00"):
    """A world whose ssh runs the received command on a stand-in board (SANDBOX); the board's checkout
    is tmp_path/remote, its bridge script and harness logging stubs. Returns (w, b, env words)."""
    w, b = _world(tmp_path, same_id=same_id)
    _stub(b / "ssh", SANDBOX % {"w": _posix(w)})
    (w / "uptime").write_text(uptime + "\n")
    if reset is None:
        (w / "reset_reason").unlink()
    else:
        (w / "reset_reason").write_text(reset + "\n")
    (w / "reset_next").write_text("".join(x + "\n" for x in reset_next))
    (w / "pstore").mkdir()
    for n in pstore:
        (w / "pstore" / n).write_text("record\n")
    (w / "home").mkdir()
    bb = w / "boardbin"
    bb.mkdir()
    _stub(bb / "sudo", '[ "$1" = -n ] || exit 97\nshift\nexec "$@"')
    _stub(bb / "sync", "exit 0")
    remote = tmp_path / "remote"
    (remote / "scripts" / "orin").mkdir(parents=True)
    (remote / "orin-native" / "gpu-concurrency").mkdir(parents=True)
    log = _posix(w / "board.log")
    _stub(remote / "scripts" / "orin" / "setup-bridge-orin.sh", 'echo BRIDGE >> "%s"' % log)
    _stub(remote / "orin-native" / "gpu-concurrency" / "run-randomise.sh", 'echo "HARNESS $BOOT_TAG" >> "%s"' % log)
    return w, b, {"REMOTE": _posix(remote), "LOCK": _posix(tmp_path / "lock")}


def _board(w):
    """What ran on the stand-in board, the reboots' log lines left out (they come from a background job)."""
    p = w / "board.log"
    return [x for x in p.read_text().splitlines() if x != "REBOOT"] if p.exists() else []


def _session_log(tmp_path, tag):
    return (tmp_path / "logs" / ("%s-session.log" % tag)).read_text()


def _kinds(calls):
    out = []
    for c in calls:
        if c.startswith("port"):
            out.append("port")
        elif "systemctl reboot" in c:
            out.append("reboot")
        elif "BOOT_TAG=" in c:
            out.append("session " + re.search(r"BOOT_TAG=(b\d)", c).group(1))
        else:
            out.append("other")
    return out


def _squash(kinds):
    out = []
    for k in kinds:
        if not out or out[-1] != k or k != "port":
            out.append(k)
    return out


# ------------------------------------------------------------------ refusals before any call

@pytest.mark.parametrize("env,why", [
    ({"HOST": None}, "HOST"),
    ({"HOST": "203.0.113.7"}, "HOST"),
    ({"KEY": None}, "KEY"),
    ({"OWNER_AT_PLUG": None}, "OWNER_AT_PLUG=1"),
    ({"OWNER_AT_PLUG": "yes"}, "OWNER_AT_PLUG=1"),
    ({"REMOTE": None}, "REMOTE"),
    ({"REMOTE": "~/q lv"}, "REMOTE"),
    ({"BOARD_ENV": "SCHEDULE=~/a6/s.txt IMG=$(reboot)"}, "BOARD_ENV"),
    ({"BOARD_ENV": "schedule=x"}, "BOARD_ENV"),
    ({"DOWN_TRIES": "0"}, "DOWN_TRIES"),
    ({"POLL_S": "abc"}, "POLL_S"),
    ({"UP_TRIES": "0"}, "UP_TRIES"),
    ({"WAIT_UPTIME_S": "x"}, "WAIT_UPTIME_S"),
    ({"SETTLE_TRIES": "-1"}, "SETTLE_TRIES"),
    ({"RUN_MAX_S": "0"}, "RUN_MAX_S"),
    ({"SESSION_MAX_S": "abc"}, "SESSION_MAX_S"),
    ({"FIRST_IS_CURRENT": "2"}, "FIRST_IS_CURRENT"),
    ({"HARNESS": "a b"}, "HARNESS"),
    ({"BOARD_ENV": "BOOT_TAG=b1"}, "BOOT_TAG"),
    ({"KEY": "/nonexistent/key"}, "KEY"),
    ({"EXPECT_RESET": "it's"}, "EXPECT_RESET"),
    ({"EXPECT_RESET": "a$(reboot)"}, "EXPECT_RESET"),
    ({"LOGDIR": "logs/../.."}, "LOGDIR"),
])
def test_a_cycle_that_is_not_fully_specified_is_refused_before_any_call(tmp_path, env, why):
    w, b = _world(tmp_path)
    r = _run(tmp_path, ["b1"], w, b, **env)
    assert r.returncode != 0 and why in r.stderr, r.stdout + r.stderr
    assert r.calls == [], "refused before any call"


@pytest.mark.parametrize("tags", [[], ["b7"], ["b1", "x"], ["b1", "b1"]])
def test_tags_are_board_boots_given_once(tmp_path, tags):
    w, b = _world(tmp_path)
    r = _run(tmp_path, tags, w, b)
    assert r.returncode != 0 and r.calls == [], r.stdout + r.stderr


# ------------------------------------------------------------------ the cycle

def test_each_board_boot_is_one_reboot_a_wait_on_the_port_then_one_session(tmp_path):
    w, b = _world(tmp_path)
    r = _run(tmp_path, ["b1", "b2"], w, b)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _squash(_kinds(r.calls)) == ["reboot", "port", "session b1", "reboot", "port", "session b2"], r.calls
    assert "cycle done: b1 b2" in r.stdout


def test_no_login_between_the_reboot_and_the_session(tmp_path):
    """Only TCP connects to port 22 while the board reboots: no polling logins (section 10)."""
    w, b = _world(tmp_path, down_left=2, up_left=3)
    r = _run(tmp_path, ["b3"], w, b)
    kinds = _kinds(r.calls)
    first, last = kinds.index("reboot"), kinds.index("session b3")
    assert set(kinds[first + 1:last]) == {"port"} and len(kinds[first + 1:last]) >= 6


def test_the_current_boot_can_be_the_first_board_boot(tmp_path):
    w, b = _world(tmp_path)
    r = _run(tmp_path, ["b0", "b1"], w, b, FIRST_IS_CURRENT="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _squash(_kinds(r.calls)) == ["session b0", "reboot", "port", "session b1"], r.calls


def test_a_failed_board_boot_stops_the_cycle_and_no_reboot_follows(tmp_path):
    w, b = _world(tmp_path, rcs={"b2": 1})
    r = _run(tmp_path, ["b1", "b2", "b3"], w, b)
    assert r.returncode != 0
    assert _squash(_kinds(r.calls)) == ["reboot", "port", "session b1", "reboot", "port", "session b2"], r.calls
    assert "b2" in r.stderr and "stop" in r.stderr and "reset_reason" in r.stderr


def test_a_refused_reboot_stops_the_cycle(tmp_path):
    w, b = _world(tmp_path, reboot_rc=3)
    r = _run(tmp_path, ["b1"], w, b)
    assert r.returncode != 0 and _kinds(r.calls) == ["reboot"], r.calls
    assert "reboot" in r.stderr


def test_a_board_that_does_not_go_down_stops_the_cycle(tmp_path):
    w, b = _world(tmp_path, never_down=True)
    r = _run(tmp_path, ["b1"], w, b)
    assert r.returncode != 0 and "did not go down" in r.stderr
    assert _kinds(r.calls).count("port") == 6 and "session b1" not in _kinds(r.calls)


def test_a_board_that_does_not_come_back_stops_the_cycle(tmp_path):
    w, b = _world(tmp_path, never_up=True)
    r = _run(tmp_path, ["b1"], w, b)
    assert r.returncode != 0 and "did not come back" in r.stderr and "plug" in r.stderr
    assert "session b1" not in _kinds(r.calls)


def test_a_reboot_that_kept_the_boot_id_stops_the_cycle(tmp_path):
    w, b = _world(tmp_path, same_id=True)
    r = _run(tmp_path, ["b1"], w, b)
    assert r.returncode != 0 and "no reboot happened" in r.stderr, r.stdout + r.stderr


def test_the_calls_carry_the_host_and_key_and_the_session_its_board_boots_words(tmp_path):
    w, b = _world(tmp_path)
    r = _run(tmp_path, ["b4"], w, b, BOARD_ENV="SCHEDULE=~/a6-randomise/schedule.txt IMG=~/output")
    assert r.returncode == 0, r.stdout + r.stderr
    ssh = [c for c in r.calls if c.startswith("ssh ")]
    assert all(" -i %s " % _posix(tmp_path / "key") in c and " tester@203.0.113.7 " in c for c in ssh), ssh
    assert all("BatchMode=yes" in c and "ConnectTimeout=" in c for c in ssh)
    session = [c for c in ssh if "BOOT_TAG=" in c][0]
    assert "BOOT_TAG=b4 SCHEDULE=~/a6-randomise/schedule.txt IMG=~/output timeout " in session
    assert "bash orin-native/gpu-concurrency/run-randomise.sh" in session
    assert "cd ~/qlv" in session and "sudo -n bash scripts/orin/setup-bridge-orin.sh" in session
    assert (tmp_path / "logs").is_dir() and any((tmp_path / "logs").iterdir())


# ------------------------------------------------------------------ the session's first reads, run on a stand-in board

def test_the_session_refuses_on_the_board_before_anything_when_no_reboot_happened(tmp_path):
    """Section 4.1: each board boot a fresh boot. The session compares the boot id with the one the reboot
    was asked on before the settle wait, the bridge and the harness -- never after the harness ran."""
    w, b, env = _sandbox(tmp_path, same_id=True)
    r = _run(tmp_path, ["b1"], w, b, **env)
    assert r.returncode != 0 and "no reboot happened" in r.stderr, r.stdout + r.stderr
    assert _board(w) == [], _board(w)
    assert "the boot the reboot was asked on" in _session_log(tmp_path, "b1")


def test_reset_reason_and_pstore_are_read_first_in_the_session(tmp_path):
    """Section 10: reset_reason first, then pstore, before anything else runs. An unreadable reset_reason
    stops the session at once: no settle wait (the uptime is under it here), no bridge, no harness."""
    w, b, env = _sandbox(tmp_path, reset=None, uptime="100.00 1.00")
    t0 = time.time()
    r = _run(tmp_path, ["b1"], w, b, SETTLE_TRIES="1", **env)
    assert r.returncode != 0 and time.time() - t0 < 8, "no settle wait ran first"
    log = _session_log(tmp_path, "b1")
    assert "cannot read reset_reason" in log and "uptime did not reach" not in log, log
    assert _board(w) == [] and "reset_reason or pstore" in r.stderr, r.stderr


def test_the_settle_wait_in_the_session_is_bounded_by_its_tries(tmp_path):
    """The uptime stays under WAIT_UPTIME_S: the loop sleeps SETTLE_TRIES times, then the session stops with exit 4,
    before the bridge and the harness. The board's sleep is a stub that counts its calls and, at the 40th, lets the
    uptime reach the wait: a loop with no bound of its own would then go on to the bridge and the harness."""
    w, b, env = _sandbox(tmp_path, uptime="100.00 1.00")
    sleeps = _posix(w / "sleeps.log")
    _stub(w / "boardbin" / "sleep", 'echo "$*" >> "%s"\n[ "$(wc -l < "%s")" -lt 40 ] || echo "900.00 1.00" > "%s"'
          % (sleeps, sleeps, _posix(w / "uptime")))
    r = _run(tmp_path, ["b1"], w, b, SETTLE_TRIES="3", **env)
    assert r.returncode != 0 and "board boot b1 failed (exit 4;" in r.stderr, r.stdout + r.stderr
    assert "the uptime did not reach 660 s" in _session_log(tmp_path, "b1")
    assert (w / "sleeps.log").read_text().splitlines() == ["10", "10", "10"] and _board(w) == []


def test_a_crash_record_in_pstore_is_archived_and_stops_the_session_before_the_bridge(tmp_path):
    w, b, env = _sandbox(tmp_path, pstore=("dmesg-ramoops-0", "console-ramoops-0"))
    r = _run(tmp_path, ["b1"], w, b, **env)
    assert r.returncode != 0
    assert len(list((w / "home" / "partition-cycle-pstore").glob("b1-*/dmesg-ramoops-0"))) == 1, "archived first"
    assert _board(w) == [] and "pstore holds a crash record" in _session_log(tmp_path, "b1")


def test_a_console_record_alone_is_archived_and_the_session_goes_on(tmp_path):
    w, b, env = _sandbox(tmp_path, pstore=("console-ramoops-0",))
    r = _run(tmp_path, ["b1"], w, b, **env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert list((w / "home" / "partition-cycle-pstore").glob("b1-*/console-ramoops-0"))
    assert _board(w) == ["BRIDGE", "HARNESS b1"], _board(w)


def test_a_reset_reason_other_than_the_planned_reboots_stops_the_session(tmp_path):
    """Section 10's stop rule: any reset. A watchdog reset in place of the planned reboot stops it."""
    w, b, env = _sandbox(tmp_path, reset="BCCPLEXWDT")
    r = _run(tmp_path, ["b1"], w, b, **env)
    log = _session_log(tmp_path, "b1")
    assert r.returncode != 0 and "reset_reason 'BCCPLEXWDT' is not the planned reboot's 'TEST_RESET'" in log, log
    assert _board(w) == []


def test_the_smoke_boot_settles_the_planned_reboots_reset_reason_for_the_board_boots_after_it(tmp_path):
    w, b, env = _sandbox(tmp_path, reset_next=("SW_REBOOT", "SW_REBOOT", "BCCPLEXWDT"))
    r = _run(tmp_path, ["b0", "b1", "b2"], w, b, EXPECT_RESET=None, **env)
    assert r.returncode != 0
    assert "settled on the smoke boot: 'SW_REBOOT'" in r.stdout, r.stdout
    assert _board(w) == ["BRIDGE", "HARNESS b0", "BRIDGE", "HARNESS b1"], _board(w)
    assert "reset_reason 'BCCPLEXWDT' is not the planned reboot's 'SW_REBOOT'" in _session_log(tmp_path, "b2")


def test_a_clean_session_runs_the_bridge_then_the_harness(tmp_path):
    w, b, env = _sandbox(tmp_path)
    r = _run(tmp_path, ["b1", "b2"], w, b, **env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _board(w) == ["BRIDGE", "HARNESS b1", "BRIDGE", "HARNESS b2"], _board(w)
    log = _session_log(tmp_path, "b2")
    assert log.index("boot_id=") < log.index("reset_reason=TEST_RESET") < log.index("pstore=empty"), log


# ------------------------------------------------------------------ the reboot call's refusals, run on the stand-in board

def _reboots_asked(w):
    """The reboots the stand-in board was asked for (the reboot is a background job, so wait for it)."""
    time.sleep(0.5)
    p = w / "board.log"
    return p.read_text().splitlines().count("REBOOT") if p.exists() else 0


def test_a_platform_quiesce_stop_that_is_outstanding_refuses_the_reboot_on_the_board(tmp_path):
    """The restore must come before every reboot: the marker the stop leaves is checked on the board, in
    the call that would reboot it."""
    w, b, env = _sandbox(tmp_path)
    marker = w / "home" / ".local" / "state" / "platform-quiesce.active"
    marker.parent.mkdir(parents=True)
    marker.write_text("outstanding\n")
    r = _run(tmp_path, ["b1"], w, b, **env)
    assert r.returncode != 0 and "the reboot before b1 was refused or failed" in r.stderr, r.stdout + r.stderr
    assert "a platform-quiesce stop is outstanding" in (tmp_path / "logs" / "b1-reboot.log").read_text()
    assert _reboots_asked(w) == 0 and _board(w) == [] and _kinds(r.calls) == ["reboot"], r.calls


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
def test_a_harness_holding_the_run_lock_refuses_the_reboot_on_the_board(tmp_path):
    w, b, env = _sandbox(tmp_path)
    lock = tmp_path / "lock"
    holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
    try:
        end = time.time() + 10
        while subprocess.run(["flock", "-n", str(lock), "true"]).returncode == 0 and time.time() < end:
            time.sleep(0.05)
        r = _run(tmp_path, ["b1"], w, b, **env)
    finally:
        holder.kill()
        holder.wait()
    assert r.returncode != 0 and "the reboot before b1 was refused or failed" in r.stderr, r.stdout + r.stderr
    assert "a harness holds" in (tmp_path / "logs" / "b1-reboot.log").read_text()
    assert _reboots_asked(w) == 0 and _board(w) == [] and _kinds(r.calls) == ["reboot"], r.calls


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
def test_a_board_with_no_marker_and_a_lock_nobody_holds_is_asked_one_reboot(tmp_path):
    w, b, env = _sandbox(tmp_path)
    (tmp_path / "lock").write_text("")
    r = _run(tmp_path, ["b1"], w, b, **env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _reboots_asked(w) == 1 and _board(w) == ["BRIDGE", "HARNESS b1"], _board(w)


def test_the_session_stops_on_the_board_when_its_checkout_is_not_there(tmp_path):
    """The directory change is checked: without it the bridge script would be looked for under the login's
    home, and the session would stop as a failed bridge (exit 5), not as a missing checkout (exit 1)."""
    w, b, env = _sandbox(tmp_path)
    env["REMOTE"] = _posix(tmp_path / "no-such-checkout")
    r = _run(tmp_path, ["b1"], w, b, **env)
    assert r.returncode != 0 and "board boot b1 failed (exit 1;" in r.stderr, r.stdout + r.stderr
    assert _board(w) == []
    assert '"cd $REMOTE || exit 1"' in open(CYCLE, encoding="utf-8").read()


@pytest.mark.parametrize("tags,first", [(["b1"], "0"), (["b1", "b0"], "0"), (["b0", "b1"], "1")])
def test_a_scored_board_boot_needs_the_planned_reboots_reset_reason(tmp_path, tags, first):
    """No reset_reason is settled until the smoke boot b0 has run after a reboot of the cycle (or the
    owner gives what it read): a scored board boot before that is refused before any call."""
    w, b = _world(tmp_path)
    r = _run(tmp_path, tags, w, b, EXPECT_RESET=None, FIRST_IS_CURRENT=first)
    assert r.returncode != 0 and r.calls == [] and "EXPECT_RESET" in r.stderr and "smoke" in r.stderr, r.stderr


def test_the_smoke_boot_alone_needs_no_expected_reset_reason(tmp_path):
    w, b = _world(tmp_path)
    r = _run(tmp_path, ["b0"], w, b, EXPECT_RESET=None)
    assert r.returncode == 0 and "settled on the smoke boot: 'TEST_RESET'" in r.stdout, r.stdout + r.stderr


# ------------------------------------------------------------------ where the logs go

def test_the_logs_go_under_home_by_default_and_never_into_the_callers_directory(tmp_path):
    w, b = _world(tmp_path)
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    r = _run(tmp_path, ["b1"], w, b, _cwd=cwd, LOGDIR=None, HOME=_posix(home))
    assert r.returncode == 0, r.stdout + r.stderr
    assert list(cwd.iterdir()) == [], "nothing in the caller's directory"
    assert len(list((home / "partition-cycle").glob("*/b1-session.log"))) == 1


def test_a_logdir_inside_the_scripts_repository_is_refused_before_any_call(tmp_path):
    """The session logs carry the harness's --one summary, figures included: results stay out of the
    repository. A copy of the script in a checkout's layout, so nothing is made in the real one."""
    repo = tmp_path / "repo"
    gc = repo / "orin-native" / "gpu-concurrency"
    gc.mkdir(parents=True)
    shutil.copy(CYCLE, str(gc / "partition_cycle.sh"))
    w, b = _world(tmp_path)
    for logdir, cwd in ((_posix(repo / "logs"), None), (_posix(gc / "x" / "y"), None), (_posix(repo), None), ("logs", repo)):
        r = _run(tmp_path, ["b1"], w, b, _cwd=cwd, _script=gc / "partition_cycle.sh", LOGDIR=logdir)
        assert r.returncode != 0 and r.calls == [] and "inside this script's repository" in r.stderr, (logdir, r.stderr)
    assert sorted(p.name for p in repo.iterdir()) == ["orin-native"] and not (gc / "x").exists()


def test_a_logdir_inside_any_work_tree_is_refused_before_any_call(tmp_path):
    other = tmp_path / "other"
    (other / "sub").mkdir(parents=True)
    (other / ".git").write_text("gitdir: elsewhere\n")
    w, b = _world(tmp_path)
    r = _run(tmp_path, ["b1"], w, b, LOGDIR=_posix(other / "sub" / "logs"))
    assert r.returncode != 0 and r.calls == [] and "inside a work tree" in r.stderr, r.stderr
    assert not (other / "sub" / "logs").exists()


# ------------------------------------------------------------------ what the script never does

def _code(path):
    lines = []
    for line in open(path, encoding="utf-8").read().split("\n"):
        if line.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"\s#\s.*$", "", line))
    return "\n".join(lines)


def test_the_code_never_touches_a_boot_entry_the_bootloader_the_command_line_or_nvpmodel():
    code = _code(CYCLE)
    for word in ("partition-boot", "extlinux", "efibootmgr", "nvbootctrl", "grub", "nvpmodel", "isolcpus", "irqaffinity",
                 "/boot/", "cmdline", "kexec", "flash"):
        assert word not in code, word
    assert code.count("systemctl reboot") == 1


def test_the_script_names_no_address_and_no_user():
    text = open(CYCLE, encoding="utf-8").read()
    assert not re.search(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", text), "no address of its own"
    assert "/home/" not in text and not re.search(r"\.ssh/[A-Za-z0-9_]", text), "no login's home and no key path of its own"
    assert 'HOST="${HOST:-}"' in text and 'KEY="${KEY:-}"' in text


def test_every_wait_is_bounded():
    code = _code(CYCLE)
    assert "while true" not in code and "while :" not in code and "until " not in code
    assert re.search(r'DOWN_TRIES="\$\{DOWN_TRIES:-\d+\}"', code) and re.search(r'UP_TRIES="\$\{UP_TRIES:-\d+\}"', code)
    assert re.search(r'RUN_MAX_S="\$\{RUN_MAX_S:-\d+\}"', code) and re.search(r'SETTLE_TRIES="\$\{SETTLE_TRIES:-\d+\}"', code)
    assert "timeout \"$SESSION_MAX_S\" ssh" in code or 'timeout "$SESSION_MAX_S" ssh' in code


def test_the_script_parses():
    r = subprocess.run([BASH, "-n", CYCLE], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr

