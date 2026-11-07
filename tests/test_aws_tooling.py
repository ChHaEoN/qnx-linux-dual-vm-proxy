"""scripts/aws/ -- the bare-metal AWS session tooling, and the shift-isolation driver.

Nothing here contacts AWS. The driver's real code paths run against stub `aws`,
`ssh` and `scp` programs that log their arguments and answer from environment
variables, so what is tested is what keeps a session cheap and its record clean:
every failure between launch and the proven safety net must TERMINATE (and
confirm it), teardown checks must refuse a live instance or an orphaned volume,
the capture must publish run data byte-for-byte and redact only strings, and a
fetched capture carrying an identifier must be refused.

plan Phase 3 WP3 (the last section): the root volume's size and its
read-back, the uploaded files and setup's check of them, the two vss harnesses'
words, their detached run and `wait-run`, the session marker, the deadline
contract of lib-vss-deadline.sh, and quiesce's platform record. Stub harnesses
stand in for run-vss-setup.sh and run-vss-suite.sh. Every address, id and name
is a documentation value. WP3i: capture.py and leakscan.py on a fake vss
record (the whitelist, JSONL and the bridge log by the JSON rule, IPv6, the
evidence of a vss stem), and the capture phase's gate for a vss stem. WP3fix,
after them: the session-safety review's findings, each a test that failed on
the tree the review read. WP6 item 2: the capture rehearsal's findings (the
redactor's boundary after a kept match, the substitutions made in JSON strings,
IPv6 in a vss record's text files), each a test that failed on the tree the
rehearsal ran. Last, WP6 item 4 and item 1's NIT 2: the signals the detached
runner's descendants ignore, the did-not-start path's kill of the runner's
process group, and red() on a sha256 that holds 12 digits in a row. SDV Phase 6
WP6, at the end: run-ota-drill.sh in the harness phase (its words, its setup,
its host mode, its detached run, the marker, wait-run), the two vss harnesses'
calls held whole, and an ota-drill stem in capture.py's whitelist and evidence
and in the capture phase's gate. SDV Phase 7 WP3d, in section c-h: the suite's
PLAN=carla in the harness phase. Any other case or spelling is refused, and so
is the word on any other harness. The word is passed through to the suite as
given. The phase's plan list is held equal to run-vss-suite.sh's preflight list
and vss_suite.py's plan table, and the header's and the README's sentences on
the word are held as written. A carla suite meets every refusal a v2 suite meets
before anything is made, a bad word is refused after a setup that ended DONE as
before one, the suite's whole environment under carla is a v2 suite's less the
word, and the word is passed through on whatever image the session booted. SDV
Phase 7 WP6-T, at the end: a session's minutes chosen at launch
(METAL_SESSION_MIN): its refusals before any aws call, the user-data rendered
from userdata.sh's one MIN=90 line and removed once run-instances returns,
session_min in the state, and wait's two windows from the state's minutes.

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import hashlib
import io

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
AWSDIR = os.path.join(REPO, "scripts", "aws")
CAPTURE = os.path.join(AWSDIR, "capture.py")
LEAKSCAN = os.path.join(AWSDIR, "leakscan.py")
DRIVER = os.path.join(AWSDIR, "drive-metal.sh")
REMOTE = os.path.join(AWSDIR, "remote-ladder.sh")
USERDATA = os.path.join(AWSDIR, "userdata.sh")
REDACT = os.path.join(REPO, "orin-native", "gpu-concurrency", "redact-aws.sh")
SHIFT = os.path.join(REPO, "orin-native", "gpu-concurrency", "run-shift-isolation.sh")
# sys.executable, not which("python3"): on Windows that finds the Microsoft Store
# placeholder, which exits 9009.
PY = sys.executable


def _find_bash():
    """A bash that can read this checkout AND leaves PATH alone.

    Two Windows candidates have to be screened out, and both fail silently:

      * the WindowsApps WSL alias, which which("bash") finds whenever Git is not
        on PATH. It cannot open a drive-letter path, so every driver test skipped
        -- which reads like a pass.
      * Git's bin\\bash.exe, the wrapper. It rewrites PATH at startup so
        /mingw64/bin and /usr/bin come first, which puts the REAL ssh and scp
        ahead of the stub directory: the fetch tests then dialled a host and
        timed out instead of exercising the driver.

    Git's usr\\bin\\bash.exe does neither, so it is preferred.
    """
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates = [os.path.join(pf, "Git", "usr", "bin", "bash.exe"),
                  shutil.which("bash"),
                  os.path.join(pf, "Git", "bin", "bash.exe")]
    marker = os.path.dirname(DRIVER)                      # any real directory will do
    for c in candidates:
        if not c or not os.path.exists(c):
            continue
        r = subprocess.run([c, "-c", 'test -r "$1" && echo ok', "_", DRIVER], capture_output=True, text=True)
        if r.returncode != 0 or r.stdout.strip() != "ok":
            continue
        e = dict(os.environ, PATH=marker + os.pathsep + os.environ.get("PATH", ""))
        r = subprocess.run([c, "-c", 'printf %s "${PATH%%:*}"'], capture_output=True, text=True, env=e)
        if r.stdout.strip().rstrip("/").replace("\\", "/").lower().endswith("/" + os.path.basename(marker).lower()):
            return c
    return None


BASH = _find_bash()


def _tools_dirs():
    """Where that bash keeps tar, sha256sum and awk.

    The scripts call them; Git for Windows ships them beside bash rather than on
    the caller's PATH, so a run started from PowerShell has bash and none of its
    tools. They go AFTER the stub directory, which must keep winning: Git's bin
    also holds a real ssh.exe and scp.exe.
    """
    if BASH is None or os.name != "nt":
        return []
    here = os.path.dirname(BASH)
    root = os.path.dirname(here)
    cand = [here, os.path.join(root, "usr", "bin"), os.path.join(os.path.dirname(root), "usr", "bin")]
    return [d for d in dict.fromkeys(cand) if os.path.isdir(d)]


TOOLS = _tools_dirs()


def _path_with(*first):
    return os.pathsep.join([str(p) for p in first] + TOOLS + [os.environ.get("PATH", "")])


needs_bash = pytest.mark.skipif(
    BASH is None, reason="no bash on this machine can read this checkout (Git for Windows not installed?)")


# --------------------------------------------------------------------------
# helpers


def _write(path, text, newline=True):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + ("\n" if newline else ""))


def _sourced(expr, env=None, stdin=None):
    """Run `expr` in a bash that has sourced drive-metal.sh (main does not run)."""
    e = dict(os.environ, METAL_NO_ENV_LOCAL="1", PATH=_path_with())
    e.update(env or {})
    return subprocess.run([BASH, "-c", '. "$1"; ' + expr, "_", DRIVER], input=stdin,
                          capture_output=True, text=True, env=e, timeout=120)


STUB_AWS = r'''#!/usr/bin/env bash
echo "$*" >> "$STUB_DIR/aws.log"
if [ -n "${STUB_WATCH:-}" ]; then   # WP6-T: how many rendered user-data files the session state holds at this call
  w="$METAL_STATE"; command -v cygpath >/dev/null 2>&1 && w="$(cygpath -u "$w")"
  n=0; for f in "$w"/userdata.sh.*; do [ -e "$f" ] && n=$((n + 1)); done
  echo "$n ${2:-}" >> "$STUB_DIR/watch.log"
fi
case "$*" in
  *terminate-instances*)
    if [ "${STUB_TERM_FAIL:-0}" = 1 ]; then
      echo "An error occurred (ExpiredToken): User: arn:aws:iam::123456789012:user/bob" >&2; exit 254
    fi
    echo shutting-down > "$STUB_DIR/state"; echo shutting-down ;;
  *State.Name*) cat "$STUB_DIR/state" 2>/dev/null || echo "${STUB_STATE:-running}" ;;
  *run-instances*)
    for a; do case "$a" in file://*) cp "${a#file://}" "$STUB_DIR/userdata.sent" ;; esac; done   # the user-data as sent
    s="$METAL_STATE"; command -v cygpath >/dev/null 2>&1 && s="$(cygpath -u "$s")"
    cp "$s/session_min" "$STUB_DIR/session_min.at_run" 2>/dev/null || true   # the minutes as run-instances found them
    [ "${STUB_RUN_FAIL:-0}" = 1 ] && { echo "An error occurred (RequestLimitExceeded)" >&2; exit 254; }
    echo i-0123456789abcdef0 ;;
  *client-token*) echo "${STUB_TOKEN_ID:-None}" ;;
  *BlockDeviceMappings*)
    n=$(cat "$STUB_DIR/nf" 2>/dev/null || echo 0)
    if [ "$n" -lt "${STUB_NOTFOUND:-0}" ]; then
      echo $((n + 1)) > "$STUB_DIR/nf"; echo "An error occurred (InvalidInstanceID.NotFound)" >&2; exit 254
    fi
    printf '%s\n' "${STUB_MAPPINGS:-/dev/sda1 1 /dev/sda1 True vol-0abcdef1234567890}" ;;
  *PublicIpAddress*) echo "${STUB_IP:-None}" ;;
  *'Volumes[0].Size'*)
    # launch's size read-back: what run-instances asked for, unless the test says otherwise
    if [ -n "${STUB_VOL_SIZE+x}" ]; then echo "$STUB_VOL_SIZE"
    else sed -n 's/.*"VolumeSize":\([0-9]*\).*/\1/p' "$STUB_DIR/aws.log" | tail -1; fi ;;
  *describe-volumes*--volume-ids*)
    [ "${STUB_VOL_GONE:-0}" = 1 ] && { echo "An error occurred (InvalidVolume.NotFound)" >&2; exit 254; }
    echo in-use ;;
  *describe-volumes*) echo "${STUB_AVAIL:-0}" ;;
  *instance-state-name*) echo "${STUB_RUNNING:-0}" ;;
  *) echo "stub aws: unhandled: $*" >&2; exit 99 ;;
esac
'''
STUB_SSH = r'''#!/usr/bin/env bash
echo "$*" >> "$STUB_DIR/ssh.log"
case "$*" in
  *PROVISION_FAILED*) printf '%s\n' "${STUB_PROV:-OK}" ;;
  *shutdown/scheduled*) [ -n "${STUB_SCHED_FILE:-}" ] && cat "$STUB_SCHED_FILE" ;;
  *) exit 0 ;;
esac
'''
STUB_SCP = r'''#!/usr/bin/env bash
echo "$*" >> "$STUB_DIR/scp.log"
case "$*" in
  *a1/pub.tgz*) for last; do :; done; cp "$STUB_DIR/pub.tgz" "$STUB_DIR/pub.sha256" "$last" ;;
  *) exit 0 ;;
esac
'''


@pytest.fixture
def rig(tmp_path):
    stub = tmp_path / "stub"
    stub.mkdir()
    for name, body in (("aws", STUB_AWS), ("ssh", STUB_SSH), ("scp", STUB_SCP)):
        _write(stub / name, body, newline=False)
        os.chmod(str(stub / name), 0o755)
    state = tmp_path / "state"

    def run(*args, driver=DRIVER, **env):
        e = dict(os.environ, METAL_NO_ENV_LOCAL="1", AWS=str(stub / "aws"), STUB_DIR=str(stub),
                 METAL_STATE=str(state), METAL_KEY_NAME="lab-key", METAL_SG_NAME="lab-sg",
                 METAL_POLL_S="0", METAL_IP_WAIT_S="1", METAL_PROV_WAIT_S="1",
                 METAL_CONFIRM_TRIES="2", METAL_READBACK_TRIES="5",
                 PATH=_path_with(stub))
        e.update({k: str(v) for k, v in env.items()})
        r = subprocess.run([BASH, driver] + list(args), capture_output=True, text=True, env=e, timeout=120)
        log = (stub / "aws.log").read_text(encoding="utf-8") if (stub / "aws.log").exists() else ""
        return r, log

    return run, state, stub


def _sched(tmp_path, minutes, mode="poweroff"):
    now = 1_790_000_000
    f = tmp_path / "sched.txt"
    # 2026-10-10: `wait` proves two nets with one read of the instance, so the answer also carries
    # the two marks user-data leaves and the monotonic timer, armed and in time. What a case here
    # varies is still the wall-clock schedule alone.
    _write(f, "ARMED_FILE=yes\nPERBOOT=yes\nUSEC=%d\nWARN_WALL=1\nMODE=%s\nNOW=%d\n"
              "ActiveState=active\nNextElapseUSecMonotonic=1h 30min 41s\nUPTIME=180" % ((now + minutes * 60) * 1_000_000, mode, now))
    return f


# --------------------------------------------------------------------------
# launch: every failure after the id exists terminates, and says so


@needs_bash
def test_the_environment_wins_over_env_local(tmp_path):
    # 2026-09-25: .env.local's METAL_REPO_TAR replaced the one given on the command line,
    # and an older session's repository was uploaded. A value in the environment now wins;
    # a value only the file sets still comes from the file.
    d = tmp_path / "aws"
    d.mkdir()
    shutil.copy(DRIVER, str(d / "drive-metal.sh"))
    _write(d / ".env.local", "METAL_REPO_TAR=/from/file/repo.tar\nMETAL_IFS=/from/file/ifs-stamp.bin")
    e = {k: v for k, v in os.environ.items() if k not in ("METAL_NO_ENV_LOCAL", "METAL_IFS", "METAL_REPO_TAR")}
    e.update(PATH=_path_with(), METAL_REPO_TAR="/given/repo.tar")
    r = subprocess.run([BASH, "-c", '. "$1"; echo "tar=$METAL_REPO_TAR ifs=$METAL_IFS"', "_", str(d / "drive-metal.sh")],
                       capture_output=True, text=True, env=e, timeout=60)
    assert "tar=/given/repo.tar ifs=/from/file/ifs-stamp.bin" in r.stdout, r.stdout + r.stderr


@needs_bash
def test_launch_from_copy_outside_repository_creates_state(rig, tmp_path, monkeypatch):
    # Only the existing stand-in can be called; the script has no Git root here.
    copied = tmp_path / "copied-scripts" / "drive-metal.sh"
    copied.parent.mkdir()
    shutil.copyfile(DRIVER, copied)
    monkeypatch.setitem(globals(), "DRIVER", str(copied))
    run, state, _ = rig
    r, log = run("launch")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "run-instances" in log
    assert (state / "vol").read_text().strip() == "vol-0abcdef1234567890"
    assert not (state / "lock").exists()


@needs_bash
def test_launch_terminates_when_the_block_devices_are_wrong(rig):
    run, state, _ = rig
    r, log = run("launch", STUB_MAPPINGS="/dev/sda1 2 /dev/sda1 True vol-0abcdef1234567890")
    assert r.returncode != 0 and "terminate-instances" in log, r.stdout + r.stderr
    assert (state / "terminated").exists() and not (state / "vol").exists()


@needs_bash
def test_launch_retries_an_id_ec2_does_not_know_yet(rig):
    run, state, _ = rig
    r, log = run("launch", STUB_NOTFOUND=2)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "terminate-instances" not in log
    assert (state / "vol").read_text().strip() == "vol-0abcdef1234567890"
    assert not (state / "lock").exists(), "the launch lock must be released"


@needs_bash
def test_launch_asks_for_an_instance_that_terminates_itself(rig):
    """The flags the 90-minute deadline rests on, read off the argv rather than
    assumed. Nothing else pins the shutdown behaviour: `wait` proves a poweroff is
    SCHEDULED, not that a poweroff terminates, and unlike DeleteOnTermination it is
    never read back from EC2. Drop it and userdata's `shutdown -h +90` only STOPS
    the instance -- `verify` would catch that, but the deadline exists for the
    session nobody comes back to, and a stopped instance keeps its root volume
    (16 GB unless METAL_VOLUME_SIZE says otherwise) attached and billing."""
    run, state, _ = rig
    r, log = run("launch")
    assert r.returncode == 0, r.stdout + r.stderr
    sent = [ln for ln in log.splitlines() if "run-instances" in ln]
    assert len(sent) == 1, log
    assert "--instance-initiated-shutdown-behavior terminate" in sent[0], sent[0]
    assert '"DeleteOnTermination":true' in sent[0], sent[0]
    assert '"VolumeSize":16,' in sent[0], sent[0]
    assert "--client-token qnx-a6-" in sent[0], sent[0]
    assert "--user-data file://" in sent[0] and "userdata.sh" in sent[0], sent[0]


@needs_bash
def test_a_termination_that_cannot_be_confirmed_is_reported_not_recorded(rig):
    run, state, _ = rig
    r, log = run("launch", STUB_MAPPINGS="x 2 y True vol-0abcdef1234567890", STUB_TERM_FAIL=1)
    out = r.stdout + r.stderr
    assert r.returncode == 3 and "TERMINATE FAILED" in out, out
    assert not (state / "terminated").exists()
    assert "123456789012" not in out and "arn:aws" not in out, "aws errors must be redacted"


@needs_bash
def test_a_failed_run_instances_still_terminates_what_it_started(rig):
    run, state, _ = rig
    r, log = run("launch", STUB_RUN_FAIL=1, STUB_TOKEN_ID="i-0123456789abcdef0")
    assert r.returncode != 0 and "client-token" in log and "terminate-instances" in log, r.stdout + r.stderr


@needs_bash
def test_launch_refuses_an_unclean_session_and_a_live_region(rig):
    run, state, _ = rig
    state.mkdir(parents=True)
    (state / "id").write_text("i-0aaaaaaaaaaaaaaaa")
    r, log = run("launch")
    assert r.returncode != 0 and "not clean" in (r.stdout + r.stderr) and "run-instances" not in log
    (state / "id").unlink()
    (state / "type").write_text("a1.metal\n")      # 2026-10-17: the launched type is session state too
    r, log = run("launch")
    assert r.returncode != 0 and "not clean (type exists)" in (r.stdout + r.stderr) and "run-instances" not in log
    (state / "type").unlink()
    r, log = run("launch", STUB_RUNNING=1)
    assert r.returncode != 0 and "run-instances" not in log


@needs_bash
@pytest.mark.parametrize("given,want", [(None, "c7g.metal"), ("a1.metal", "a1.metal")])
def test_launch_asks_for_c7g_metal_unless_metal_type_names_another_and_records_the_type(rig, monkeypatch, given, want):
    """2026-10-17: c7g.metal is the default bare-metal type; a1.metal, the earlier
    default, stays one METAL_TYPE away. The type is read off run-instances' argv and the launch line, and recorded in the
    session state, where `run harness` reads it for a vss harness's host mode."""
    monkeypatch.delenv("METAL_TYPE", raising=False)
    run, state, _ = rig
    r, log = run("launch", **({} if given is None else {"METAL_TYPE": given}))
    assert r.returncode == 0, r.stdout + r.stderr
    sent = [ln for ln in log.splitlines() if "run-instances" in ln]
    assert len(sent) == 1 and re.search(r"--instance-type %s( |$)" % re.escape(want), sent[0]), sent
    assert "(%s, eu-central-1)" % want in r.stdout + r.stderr, r.stdout + r.stderr
    assert (state / "type").read_text() == want + "\n"


@needs_bash
def test_the_state_directory_may_not_be_inside_the_repo(rig):
    run, _, _ = rig
    r, log = run("verify", METAL_STATE=os.path.join(REPO, ".metal-test-state"))
    try:
        assert r.returncode != 0 and "inside the repository" in (r.stdout + r.stderr) and log == ""
    finally:
        shutil.rmtree(os.path.join(REPO, ".metal-test-state"), ignore_errors=True)


# --------------------------------------------------------------------------
# wait: the safety net is proven, or the instance goes


def _launched(state):
    state.mkdir(parents=True, exist_ok=True)
    (state / "id").write_text("i-0123456789abcdef0\n")


@needs_bash
@pytest.mark.parametrize("env", [
    {"STUB_IP": "None"},                                  # no address
    {"STUB_IP": "203.0.113.9", "STUB_PROV": "FAILED"},    # user-data failed
    {"STUB_IP": "203.0.113.9", "STUB_PROV": "OK", "SCHED": ("reboot", 88)},
    {"STUB_IP": "203.0.113.9", "STUB_PROV": "OK", "SCHED": ("poweroff", 59)},
    {"STUB_IP": "203.0.113.9", "STUB_PROV": "OK", "SCHED": ("poweroff", 95)},
    {"STUB_IP": "203.0.113.9", "STUB_PROV": "OK"},        # nothing scheduled at all
])
def test_wait_terminates_unless_the_safety_net_is_proven(rig, tmp_path, env):
    run, state, _ = rig
    _launched(state)
    env = dict(env)
    if "SCHED" in env:
        mode, minutes = env.pop("SCHED")
        env["STUB_SCHED_FILE"] = _sched(tmp_path, minutes, mode)
    r, log = run("wait", **env)
    assert r.returncode != 0 and "terminate-instances" in log, r.stdout + r.stderr
    assert not (state / "armed").exists() and not (state / "ip").exists()


@needs_bash
def test_wait_promotes_the_address_only_once_armed(rig, tmp_path):
    run, state, _ = rig
    _launched(state)
    r, log = run("wait", STUB_IP="203.0.113.9", STUB_PROV="OK", STUB_SCHED_FILE=_sched(tmp_path, 88))
    assert r.returncode == 0 and "terminate-instances" not in log, r.stdout + r.stderr
    assert (state / "armed").exists() and (state / "ip").read_text().strip() == "203.0.113.9"
    assert "203.0.113.9" not in r.stdout + r.stderr, "the address is redacted in the transcript"


@needs_bash
@pytest.mark.parametrize("step", ["upload", "fetch", "run setup"])
def test_nothing_is_spent_before_the_safety_net_is_proven(rig, step):
    run, state, _ = rig
    _launched(state)
    r, _ = run(*step.split())
    assert r.returncode != 0 and "not proven armed" in (r.stdout + r.stderr)


@needs_bash
@pytest.mark.parametrize("args,env,msg", [
    (["run", "rm -rf /"], {}, "unknown phase"),
    (["run", "ladder"], {"LADDER_ENV": "KICK=1 -i"}, "not NAME=value"),
    (["run", "ladder"], {"K": "12;reboot"}, "not a round count"),
    (["run", "harness"], {"K": "0"}, "no leading zero"),
    (["run", "ladder"], {"K": "012"}, "no leading zero"),
    (["run", "liveness"], {"K": "08"}, "no leading zero"),
])
def test_run_passes_only_known_phases_and_validated_words(rig, args, env, msg):
    run, state, stub = rig
    _launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")
    r, _ = run(*args, **env)
    assert r.returncode != 0 and msg in (r.stdout + r.stderr)
    assert not (stub / "ssh.log").exists(), "nothing may reach the instance"


# --------------------------------------------------------------------------
# terminate / verify / verify-vol


@needs_bash
def test_terminate_confirms_the_state_before_recording_it(rig):
    run, state, _ = rig
    _launched(state)
    r, _ = run("terminate", STUB_TERM_FAIL=1)
    assert r.returncode != 0 and not (state / "terminated").exists()
    r, _ = run("terminate")
    assert r.returncode == 0 and (state / "terminated").exists()


@needs_bash
def test_an_aws_error_reaches_the_transcript_redacted(rig):
    """The one path where aws_()'s `2> >(red >&2)` is load-bearing: `terminate`
    redirects stdout alone, so the stub's ExpiredToken error -- an ARN carrying an
    account id -- is what the operator sees. abort() sends the same call's stderr
    to /dev/null, so the launch test above proves nothing about red()."""
    run, state, _ = rig
    _launched(state)
    r, _ = run("terminate", STUB_TERM_FAIL=1)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "ExpiredToken" in out, out
    assert "<arn>" in out, "aws's stderr must pass through red()"
    assert "arn:aws" not in out and "123456789012" not in out and "user/bob" not in out, out


@needs_bash
@pytest.mark.parametrize("env,ok", [
    ({"STUB_STATE": "shutting-down"}, True),
    ({"STUB_STATE": "terminated"}, True),
    ({"STUB_STATE": "running"}, False),
    ({"STUB_STATE": "terminated", "STUB_RUNNING": 1}, False),
    ({"STUB_STATE": "terminated", "STUB_AVAIL": 1}, False),
])
def test_verify_refuses_a_live_instance_or_an_orphaned_volume(rig, env, ok):
    run, state, _ = rig
    _launched(state)
    r, _ = run("verify", **env)
    assert (r.returncode == 0) is ok, r.stdout + r.stderr


@needs_bash
def test_verify_vol_and_clear(rig):
    run, state, _ = rig
    _launched(state)
    (state / "vol").write_text("vol-0abcdef1234567890\n")
    r, _ = run("clear")
    assert r.returncode != 0 and (state / "id").exists(), "clear before verify-vol must refuse"
    r, _ = run("verify-vol")
    assert r.returncode != 0
    r, _ = run("verify-vol", STUB_VOL_GONE=1)
    assert r.returncode == 0 and (state / "closed").exists()
    r, _ = run("clear")
    assert r.returncode == 0 and not os.listdir(str(state))


@needs_bash
@pytest.mark.parametrize("typ", ["c7g.metal", "a1.metal", None])
def test_clear_names_the_type_the_session_launched_beside_the_capture_it_keeps(rig, typ):
    """2026-10-17: a capture goes into a record named for the type it ran on (`-c7gmetal-`, `-a1metal-`); clear, which
    removes the recorded type with the rest of the state, says which it was. A state from before the type was recorded
    clears as before."""
    run, state, _ = rig
    _launched(state)
    (state / "closed").touch()
    if typ:
        (state / "type").write_text(typ + "\n")
    _write(state / "fetched" / "pub.sha256", "")
    r, _ = run("clear")
    out = r.stdout + r.stderr
    assert r.returncode == 0 and sorted(os.listdir(str(state))) == ["fetched"], out
    assert "the capture stays in" in out and (("this session launched %s" % typ) in out if typ else "launched" not in out), out


def _pub(stub, files):
    pub = stub / "pubsrc"
    for rel, text in files.items():
        _write(pub / rel, text, newline=False)
    lines = []
    for rel in sorted(files):
        lines.append("%s  %s" % (hashlib.sha256((pub / rel).read_bytes()).hexdigest(), rel))
    _write(stub / "pub.sha256", "\n".join(lines))
    with tarfile.open(str(stub / "pub.tgz"), "w:gz") as t:
        for rel in files:
            t.add(str(pub / rel), arcname=rel)


@needs_bash
@pytest.mark.parametrize("files,ok", [
    ({"ladder/run.log": "guest 192.168.100.10 answered", "ladder/raw/kvm-D-db_r1.json": '{"halt_wait_ns": 123456789012}'}, True),
    ({"ladder/run.log": "on i-0123456789abcdef0 today"}, False),
    ({"ladder/run.log": "reached 203.0.113.7"}, False),
    ({"ladder/run.log": "account 111122223333 used"}, False),
    ({"host-facts.txt": "root=PARTUUID=00000000-0000-4000-8000-000000000000"}, False),
    ({"ladder/raw/kvm-D-db_r1.json": '{"halt_wait_ns": <account>}'}, False),   # a corrupted number
    ({"ladder/run.log": "the ladder ran with lab-key"}, False),                # the key pair, via red_literals
])
def test_fetch_refuses_a_capture_that_still_identifies_anything(rig, tmp_path, files, ok):
    run, state, stub = rig
    _launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")
    _pub(stub, files)
    r, _ = run("fetch", METAL_FETCH_DIR=tmp_path / "fetched", PYTHON=PY)
    assert (r.returncode == 0) is ok, r.stdout + r.stderr
    if not ok:
        assert "NOT publishable" in r.stdout + r.stderr


# --------------------------------------------------------------------------
# red() and shutdown_left_min(), sourced


@needs_bash
def test_red_masks_every_aws_shape_and_the_local_literals():
    text = "\n".join([
        "Warning: Identity file /c/keys/lab-eu.pem not accessible",
        "i-0123456789abcdef0 vol-0abcdef1234567890 sg-0123abcd4567ef890 subnet-0aaaaaaaaaaaaaaa1",
        "User: arn:aws:iam::123456789012:user/bob is not authorized",
        "ec2-203-0-113-7.eu-central-1.compute.amazonaws.com ip-10-0-0-5",
        "ssh 203.0.113.7 mac 0a:1b:2c:3d:4e:5f accounts 111122223333 444455556666 done",
        "InvalidKeyPair.NotFound: lab-key; group lab-sg; addr 2001:db8::1 and fe80::1",
        "booted ami-0d9429f78b33241cd",
    ])
    # stdin, not argv: on Windows an argv string is cut at its first newline.
    r = _sourced("red", env={"METAL_PEM": "/c/keys/lab-eu.pem", "METAL_KEY_NAME": "lab-key",
                             "METAL_SG_NAME": "lab-sg"}, stdin=text + "\n")
    out = r.stdout
    assert r.returncode == 0 and len(out.splitlines()) == 7, (r.stderr, out)
    for leaked in ("lab-eu.pem", "i-0123456789abcdef0", "vol-0abcdef1234567890", "sg-0123abcd",
                   "subnet-0aaa", "arn:aws", "123456789012", "203-0-113-7", "ip-10-0-0-5",
                   "203.0.113.7", "0a:1b:2c:3d:4e:5f", "111122223333", "444455556666",
                   "lab-key", "lab-sg", "2001:db8::1", "fe80::1"):
        assert leaked not in out, (leaked, out)
    assert "ami-0d9429f78b33241cd" in out, "the AMI is provenance and must survive"


@needs_bash
@pytest.mark.parametrize("text,want", [
    ("USEC={usec}\nWARN_WALL=1\nMODE=poweroff\nNOW={now}", "90"),
    ("USEC={usec}\r\nMODE=poweroff\r\nNOW={now}\r\n", "90"),     # CRLF must not hide it
    ("USEC={usec}\nMODE=reboot\nNOW={now}", None),
    ("MODE=poweroff\nNOW={now}", None),
    ("", None),
])
def test_shutdown_left_min_accepts_only_an_armed_poweroff(text, want):
    now = 1_790_000_000
    sched = text.format(usec=(now + 90 * 60) * 1_000_000, now=now)
    # The driver runs under set -e, so a failing call is caught by `if`, not by $?.
    r = _sourced('if shutdown_left_min "$SCHED"; then echo rc=0; else echo rc=1; fi', env={"SCHED": sched})
    assert r.stderr == "", r.stderr
    if want is None:
        assert r.stdout.strip() == "rc=1", r.stdout
    else:
        assert r.stdout.split() == [want, "rc=0"], r.stdout


# --------------------------------------------------------------------------
# userdata.sh


def test_userdata_arms_the_shutdown_first_survives_a_reboot_and_agrees_with_the_driver():
    body = open(USERDATA, encoding="utf-8").read()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    commands = [ln for ln in lines if not re.match(r"^[A-Z_]+=\S+$", ln)]
    # 2026-10-10: the first command arms the monotonic net and records that it did; what was the
    # first command until then is what runs at once when it cannot, and records which net there is.
    assert re.match(r'^if systemd-run .* --on-boot=\$\(\( \$\{UP:-0\} \+ MIN \* 60 \)\) .*systemctl poweroff; then$', commands[0]), \
        "the first command must arm the monotonic net: %r" % commands[0]
    assert commands[1] == 'echo monotonic > "$M/SHUTDOWN_ARMED"' and commands[2] == "else" and commands[4] == "fi", commands[:5]
    m = re.match(r'^shutdown -h \+\$MIN .*&& echo wall-clock > "\$M/SHUTDOWN_ARMED"$', commands[3])
    assert m, "without it the first command must arm the shutdown and record that it did: %r" % commands[3]
    # SDV Phase 7 WP6-T: the minutes are chosen at launch (METAL_SESSION_MIN). userdata.sh keeps ONE line MIN=90, the
    # minutes of a session that does not choose, the driver's default is that 90, and the driver's rendering rule makes
    # that line, and no other, MIN=N: it counts the lines that are exactly MIN=<default> and substitutes only such a line.
    mins = re.findall(r"^MIN=(\d+)$", body, re.M)
    driver = open(DRIVER, encoding="utf-8").read()
    d = re.findall(r"^SESSION_MIN_DEFAULT=(\d+)$", driver, re.M)
    assert mins == ["90"] and d == mins, "userdata's minutes and the driver's default differ"
    assert driver.count('n="$(grep -U -c "^MIN=$SESSION_MIN_DEFAULT\\$" "$1" || true)"') == 1, "the count of MIN= lines"
    assert driver.count('sed -b "s/^MIN=$SESSION_MIN_DEFAULT\\$/MIN=$2/" "$1" > "$3"') == 1, "the rendering rule"
    assert "SHUTDOWN_MIN_EXPECTED:-" not in driver, "wait's minutes are the state's, never the environment's"
    assert "/var/lib/cloud/scripts/per-boot/qnx-metal-deadline.sh" in body and "qnx-metal-deadline.sh" in driver, \
        "a reboot must re-arm the deadline, and wait must check that it can"
    assert body.index("set -e") > body.index("shutdown -h"), "set -e must not stop the safety net"
    assert re.search(r"trap .*PROVISION_FAILED.* ERR", body)
    assert commands[-1] == 'touch "$M/PROVISIONED"', "readiness is written last, only on success"


# --------------------------------------------------------------------------
# remote-ladder.sh: input parsing, both directions


def _inputs_env(tmp_path, **over):
    v = {"IFS_NAME": "ifs-kick.bin", "IFS_SHA256": "a" * 64, "DISK_SHA256": "b" * 64,
         "REMOTE_LADDER_SHA256": "c" * 64, "CAPTURE_SHA256": "d" * 64, "REPO_COMMIT": "e" * 40}
    v.update(over)
    # The same format drive-metal.sh `upload` writes.
    fmt = "IFS_NAME=%s\nIFS_SHA256=%s\nDISK_SHA256=%s\nREMOTE_LADDER_SHA256=%s\nCAPTURE_SHA256=%s\nREPO_COMMIT=%s\n"
    (tmp_path / "inputs.env").write_text(fmt % (v["IFS_NAME"], v["IFS_SHA256"], v["DISK_SHA256"],
                                               v["REMOTE_LADDER_SHA256"], v["CAPTURE_SHA256"], v["REPO_COMMIT"]),
                                         encoding="utf-8", newline="\n")


def _remote(tmp_path, phase="launch"):
    return subprocess.run([BASH, REMOTE, phase], capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, W=str(tmp_path), PATH=_path_with()))


@needs_bash
def test_remote_ladder_refuses_a_missing_inputs_file(tmp_path):
    r = _remote(tmp_path)
    out = r.stdout + r.stderr
    # Two asserts, not one: `and ... or ...` binds so that the message alone would
    # satisfy it and the exit status would never be checked.
    assert r.returncode != 0, out
    assert "inputs.env (drive-metal.sh upload writes it)" in out, out


@needs_bash
@pytest.mark.parametrize("over", [{"IFS_SHA256": "zz"}, {"IFS_NAME": "ifs kick.bin"}, {"CAPTURE_SHA256": "d" * 63}])
def test_remote_ladder_refuses_malformed_inputs(tmp_path, over):
    _inputs_env(tmp_path, **over)
    r = _remote(tmp_path)
    assert r.returncode != 0 and "inputs.env is malformed" in r.stdout + r.stderr


@needs_bash
def test_remote_ladder_accepts_what_the_driver_writes(tmp_path):
    """The positive half: a well-formed file gets PAST the parser (the launch then
    fails for want of a repo, which is not a parsing message)."""
    _inputs_env(tmp_path)
    r = _remote(tmp_path)
    assert r.returncode != 0 and "malformed" not in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
def test_run_accepts_the_liveness_phases(rig):
    # OD14's session (2026-09-23): launch-live and liveness reach the instance,
    # with K passed through like the ladder's.
    run, state, stub = rig
    _launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")
    for phase in ("launch-live", "liveness", "launch-stamp", "stamp", "metal", "someip", "harness"):
        run("run", phase, K="4")
    log = (stub / "ssh.log").read_text()
    for phase in ("launch-live", "liveness", "launch-stamp", "stamp", "metal", "someip", "harness"):
        assert "remote-ladder.sh %s" % phase in log, (phase, log)
    assert "K=4" in log, log


def _remote_env(tmp_path, phase, **env):
    return subprocess.run([BASH, REMOTE, phase], capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, W=str(tmp_path), PATH=_path_with(), **env))


@needs_bash
@pytest.mark.parametrize("phase,env,msg", [
    ("liveness", {}, "run launch-live first"), ("liveness", {"K": "4;reboot"}, "not a round count"),
    ("stamp", {}, "run launch-stamp first"), ("stamp", {"K": "4;reboot"}, "not a round count"),
    ("metal", {}, "no "), ("metal", {"K": "4;reboot"}, "not a round count"),
    ("someip", {}, "no "), ("someip", {"K": "4;reboot"}, "not a round count"),
    ("harness", {}, "no "), ("harness", {"K": "4;reboot"}, "not a round count"),
])
def test_remote_session_phases_refuse_without_a_guest_or_with_a_bad_k(tmp_path, phase, env, msg):
    r = _remote_env(tmp_path, phase, **env)
    assert r.returncode != 0 and msg in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("session", ["liveness", "stamp", "metal", "someip", "trace2"])
def test_remote_capture_takes_a_finished_session_and_refuses_an_unfinished_one(tmp_path, session):
    (tmp_path / "rec" / session).mkdir(parents=True)
    r = _remote_env(tmp_path, "capture")
    assert r.returncode != 0 and "the session did not finish" in r.stdout + r.stderr, r.stdout + r.stderr
    (tmp_path / "rec" / session / "host-after.txt").write_text("done\n")
    r = _remote_env(tmp_path, "capture")
    # Past the gate: it then fails for want of the redactor, which is not the gate's message.
    assert r.returncode != 0 and "did not finish" not in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
def test_remote_ladder_refuses_an_unsafe_ladder_env(tmp_path):
    (tmp_path / "repo" / "orin-native" / "gpu-concurrency").mkdir(parents=True)
    (tmp_path / "rec" / "ladder").mkdir(parents=True)
    r = subprocess.run([BASH, REMOTE, "ladder"], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, W=str(tmp_path), LADDER_ENV="KICK=1 -i", PATH=_path_with()))
    assert r.returncode != 0 and "not NAME=value" in r.stdout + r.stderr


# --------------------------------------------------------------------------
# capture.py and leakscan.py


def _rec(tmp_path):
    rec = tmp_path / "rec"
    raw = rec / "ladder" / "raw"
    # json.dump style: no trailing newline, which a line-oriented redactor adds.
    _write(raw / "lat-D-db_r1.json",
           json.dumps({"summary": {"tag": "D-db_r1", "p50_ms": 0.123456789012, "n": 1000},
                       "samples_ms": [0.1, 0.123456789012]}), newline=False)
    # 12-digit counters: exactly the shape of an account id.
    _write(raw / "kvm-D-db_r1.json",
           json.dumps({"before": {"t_ns": 912345678901, "qemu_pid": 4022,
                                  "counters": {"halt_wait_ns": 123456789012},
                                  "threads": {"4022": {"comm": "qemu-system-aar", "wait_ns": 5}}}}), newline=False)
    _write(raw / "stamp.json",
           json.dumps({"guest_ifs": "/home/ubuntu/a1/img/ifs-kick.bin", "qemu_started_ns": 123456789012,
                       # Ubuntu 24.04's shape, with a made-up build: the login's name stands inside it
                       "qemu_version": "QEMU emulator version 8.2.2 (Debian 1:8.2.2+ds-0ubuntu1.99)",
                       "kernel": "6.8.0-1063-aws", "ami": "ami-0d9429f78b33241cd"}, indent=2))
    _write(rec / "ladder" / "run.log",
           "ubuntu@ip-10-0-0-5 ran it\naccount 111122223333.\nguest 192.168.100.10:7100 on br0")
    (raw / "libshmchan.so").write_bytes(b"\x7fELF")
    (raw / ".run-start").write_bytes(b"")
    return rec


def _capture(rec, pub, user=""):
    # capture.py shells out to the redactor as plain `bash`; without this the run
    # picks up whatever bash the caller's PATH has, which on Windows is the WSL
    # alias that cannot open a drive-letter path.
    env = dict(os.environ, USER=user, PATH=_path_with())
    return subprocess.run([PY, CAPTURE, str(rec), str(pub), REDACT], capture_output=True, text=True,
                          env=env, timeout=120)


@needs_bash
def test_capture_publishes_arm_files_byte_for_byte_and_redacts_the_rest(tmp_path):
    rec, pub = _rec(tmp_path), tmp_path / "pub"
    r = _capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    raw, praw = rec / "ladder" / "raw", pub / "ladder" / "raw"
    for name in ("lat-D-db_r1.json", "kvm-D-db_r1.json"):
        assert (praw / name).read_bytes() == (raw / name).read_bytes(), name
    stamp = json.loads((praw / "stamp.json").read_text(encoding="utf-8"))
    assert stamp["qemu_started_ns"] == 123456789012, "a 12-digit NUMBER must survive"
    assert stamp["ami"] == "ami-0d9429f78b33241cd", "the AMI is provenance and is kept"
    assert stamp["qemu_version"].endswith("+ds-0ubuntu1.99)"), "the package version must not be over-masked"
    log = (pub / "ladder" / "run.log").read_text(encoding="utf-8")
    assert "ip-10-0-0-5" not in log and "111122223333" not in log and "192.168.100.10" in log
    assert not (praw / "libshmchan.so").exists() and not (praw / ".run-start").exists()
    manifest = (tmp_path / "pub.sha256").read_text(encoding="utf-8").splitlines()
    listed = sorted(line.split("  ", 1)[1] for line in manifest)
    on_disk = sorted(os.path.relpath(os.path.join(d, f), str(pub)).replace(os.sep, "/")
                     for d, _s, fs in os.walk(str(pub)) for f in fs)
    assert listed == on_disk
    lk = subprocess.run([PY, LEAKSCAN, str(pub)], capture_output=True, text=True)
    assert lk.returncode == 0, lk.stdout


@needs_bash
def test_capture_takes_a_stamp_with_the_system_object_through_unchanged(tmp_path):
    """The stamp's "system" object (2026-10-04) names the L4T and OS releases, the kernel's HZ
    and where it was read, the Python versions, nvpmodel, the Wi-Fi and the bridge's netfilter
    state. None of it is a host identity, so the redactor must leave every string of it alone:
    a version string it over-masked would come back changed in the published copy. Every value
    is made up, in the shape a noble a1.metal and an L4T R39 host give (a three-part release,
    a kernel release in a config path, a Debian package build): none is one a host reported."""
    systems = {
        "metal": {"l4t_release": "absent", "os_release": "Example OS 98.04.7 LTS", "config_hz": 250,
                  "config_hz_source": "/boot/config-9.8.0-1234-example", "python3_version": "9.8.7",
                  "python3_version_under_sudo": "9.8.7", "nvpmodel": "unavailable",
                  "wifi": {"interface": "none", "state": "none", "driver": "none", "module": "none"},
                  "br_netfilter": "absent", "bridge_nf_call_iptables": "absent",
                  "sys_root": "/sys", "etc_root": "/etc", "proc_root": "/proc"},
        "l4t": {"l4t_release": "# R39 (release), REVISION: 0.0, GCID: 12345678, BOARD: generic, EABI: aarch64, "
                               "DATE: Thu Jan  1 00:00:00 UTC 2026",
                "os_release": "Example OS 98.04.7 LTS", "config_hz": 250, "config_hz_source": "/proc/config.gz",
                "python3_version": "9.8.7", "python3_version_under_sudo": "unavailable",
                "nvpmodel": "NV Power Mode: EXAMPLE 1",
                "wifi": {"interface": "wlan0", "state": "up", "driver": "examplewifi", "module": "examplemod"},
                "br_netfilter": "loaded", "bridge_nf_call_iptables": "1",
                "sys_root": "/sys", "etc_root": "/etc", "proc_root": "/proc"},
    }
    for name, system in systems.items():
        rec, pub = _rec(tmp_path / name), tmp_path / name / "pub"
        src = rec / "ladder" / "raw" / "stamp.json"
        stamp = json.loads(src.read_text(encoding="utf-8"))
        stamp["qemu_version"] = "QEMU emulator version 9.8.7 (Debian 1:9.8.7+ds-0example1.23)"
        stamp["system"] = system
        _write(src, json.dumps(stamp, indent=2))
        r = _capture(rec, pub)
        assert r.returncode == 0, r.stdout + r.stderr
        out = pub / "ladder" / "raw" / "stamp.json"
        assert out.read_bytes() == src.read_bytes(), "%s: the redactor changed a stamp that holds no identity" % name
        assert json.loads(out.read_text(encoding="utf-8"))["system"] == system
        lk = subprocess.run([PY, LEAKSCAN, str(pub)], capture_output=True, text=True)
        assert lk.returncode == 0, lk.stdout


@needs_bash
def test_capture_refuses_an_arm_file_carrying_an_identity(tmp_path):
    rec, pub = _rec(tmp_path), tmp_path / "pub"
    _write(rec / "ladder" / "raw" / "lat-D-kick_r1.json",
           json.dumps({"summary": {"tag": "on i-0123456789abcdef0", "p50_ms": 0.2}}), newline=False)
    r = _capture(rec, pub)
    assert r.returncode != 0 and "lat-D-kick_r1.json" in (r.stdout + r.stderr)


def test_capture_refuses_nothing_and_a_used_output(tmp_path):
    (tmp_path / "empty").mkdir()
    r = _capture(tmp_path / "empty", tmp_path / "pub")
    assert r.returncode != 0 and "nothing ran" in r.stdout + r.stderr
    r = _capture(tmp_path / "missing", tmp_path / "pub")
    assert r.returncode != 0 and "no run directory" in r.stdout + r.stderr
    rec = _rec(tmp_path)
    _write(tmp_path / "used" / "x.txt", "old")
    r = _capture(rec, tmp_path / "used")
    assert r.returncode != 0 and "not empty" in r.stdout + r.stderr


@pytest.mark.parametrize("text,ok", [
    ("br0 192.168.100.1 guest 192.168.100.10 loop 127.0.0.1", True),
    ("time 13:20:34 and version 6.2.0", True),
    ("guest mac 52:54:00:11:11:11, link fe80::5054:ff:fe11:1111", True),
    ("public 203.0.113.7", False),
    ("mac 0a:1b:2c:3d:4e:5f", False),
    ("addr 2001:db8::1", False),
    ("route fe80::1 via br0", False),
    ("  TRACE_DATE:: Thu Jan  1 00:00:00 2026 TRACE_CYCLES_PER_SEC:: 12345678", True),     # a traceprinter header's shape, made up
    ("in client_endpoint_impl::send, a lone request waits", True),
    ("vol-0abcdef1234567890 attached", False),
    ("arn:aws:iam::111122223333:user/x", False),
    ("id 11112222-3333-4444-5555-666677778888", False),
    ("account 111122223333 here", False),
    ("ami-0d9429f78b33241cd is fine", True),
    ("ami-02153ae97d7504246 is fine", True),     # a held record names the image launched until 2026-10-08
])
def test_leakscan_text(tmp_path, text, ok):
    _write(tmp_path / "d" / "x.log", text)
    r = subprocess.run([PY, LEAKSCAN, str(tmp_path / "d")], capture_output=True, text=True)
    assert (r.returncode == 0) is ok, r.stdout
    assert text.split()[-1] not in r.stdout or ok, "the leaked value itself must not be printed"


def test_leakscan_json_scans_strings_not_numbers_and_takes_literals(tmp_path):
    _write(tmp_path / "d" / "kvm.json", json.dumps({"halt_wait_ns": 123456789012, "comm": "qemu-system-aar"}))
    r = subprocess.run([PY, LEAKSCAN, str(tmp_path / "d")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    _write(tmp_path / "d" / "run.log", "ran by someuser with lab-key")
    r = subprocess.run([PY, LEAKSCAN, str(tmp_path / "d"), "lab-key"], capture_output=True, text=True)
    assert r.returncode == 1 and "local literal" in r.stdout and "lab-key" not in r.stdout


# --------------------------------------------------------------------------
# run-shift-isolation.sh: the plan, and the real loop against stubs


@needs_bash
def test_shift_isolation_plan_is_abccba_with_alternating_snapshot_order(tmp_path):
    r = subprocess.run([BASH, SHIFT], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, DRY="1", OUTBASE=str(tmp_path / "x"), PATH=_path_with()))
    assert r.returncode == 0, r.stderr
    rows = [ln.split() for ln in r.stdout.splitlines()]
    assert [row[3] for row in rows] == list("ABCCBA")
    assert [" ".join(row[-2:]) for row in rows] == ["0 1", "1 0"] * 3
    assert {row[3]: row[5] for row in rows} == {"A": "ifs-udp.bin", "B": "ifs-udp.bin", "C": "ifs-kick.bin"}
    for seq in ("A D", "A B C"):
        bad = subprocess.run([BASH, SHIFT], capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, DRY="1", OUTBASE=str(tmp_path / "y"), SEQ=seq, PATH=_path_with()))
        assert bad.returncode != 0, seq


STUB_LAUNCH = r'''#!/usr/bin/env bash
# stub launch: log which devices it was given, and write the console an image of
# this kind would print
echo "IFS=$(basename "$IFS_BIN") IVSHMEM=${IVSHMEM:-} SERVER=${IVSHMEM_SERVER:-} KICK=${KICK_SOCK:-}" >> "$STUB_DIR/launch.log"
case "$(basename "$IFS_BIN")" in
  ifs-udp.bin) : > "$LOG" ;;
  ifs-shm.bin) echo "monitor: safety monitor serving shm on ivshmem 00:01.0" > "$LOG" ;;
  ifs-kick-nomon.bin) printf 'monitor: shm configured: x\nmonitor: safety monitor serving shm on ivshmem\n' > "$LOG" ;;
  ifs-kick.bin) printf '%s\n' 'monitor: shm configured: x' 'monitor: safety monitor serving shm on ivshmem' \
    'monitor: safety monitor serving shm-kick on' > "$LOG" ;;
esac
[ "${STUB_BROKEN:-}" = "$(basename "$IFS_BIN")" ] && : > "$LOG"
exit 0
'''
STUB_LADDER = r'''#!/usr/bin/env bash
echo "KVM_STATS=$KVM_STATS OUT=$(basename "$(dirname "$OUT")")/$(basename "$OUT")" >> "$STUB_DIR/ladder.log"
mkdir -p "$OUT"; exit 0
'''


def _shift_rig(tmp_path):
    d = tmp_path / "gc"
    d.mkdir()
    shutil.copy(SHIFT, str(d / "run-shift-isolation.sh"))
    for name, body in (("launch-qnx-kvm-bridged.sh", STUB_LAUNCH), ("run-ladder.sh", STUB_LADDER)):
        _write(d / name, body, newline=False)
    stub = tmp_path / "bin"
    stub.mkdir()
    for name in ("pgrep", "pkill"):
        _write(stub / name, "#!/usr/bin/env bash\nexit 1" if name == "pgrep" else "#!/usr/bin/env bash\nexit 0",
               newline=False)
        os.chmod(str(stub / name), 0o755)
    img = tmp_path / "img"
    img.mkdir()
    for f in ("ifs-udp.bin", "ifs-shm.bin", "ifs-kick-nomon.bin", "ifs-kick.bin", "disk-qemu"):
        (img / f).write_bytes(f.encode())
    return d, stub, img


@needs_bash
def test_shift_isolation_loop_gives_devices_and_checks_services(tmp_path):
    d, stub, img = _shift_rig(tmp_path)
    env = dict(os.environ, OUTBASE=str(tmp_path / "out"), IMG=str(img), SNAP="1", SEQ="B S N C C N S B",
               STUB_DIR=str(tmp_path), PATH=_path_with(stub))
    r = subprocess.run([BASH, str(d / "run-shift-isolation.sh")], capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    launches = (tmp_path / "launch.log").read_text().splitlines()
    assert [ln.split()[0] for ln in launches] == ["IFS=" + x for x in (
        "ifs-udp.bin", "ifs-shm.bin", "ifs-kick-nomon.bin", "ifs-kick.bin",
        "ifs-kick.bin", "ifs-kick-nomon.bin", "ifs-shm.bin", "ifs-udp.bin")]
    assert all("IVSHMEM=/dev/shm/a6-ivshmem" in ln and "KICK=/tmp/a6-kick.sock" in ln for ln in launches)
    ladders = (tmp_path / "ladder.log").read_text().splitlines()
    assert len(ladders) == 8 and all(ln.startswith("KVM_STATS=1 ") for ln in ladders)
    # Condition A gets no devices.
    env.update(SEQ="A B B A", OUTBASE=str(tmp_path / "out2"))
    (tmp_path / "launch.log").unlink()
    r = subprocess.run([BASH, str(d / "run-shift-isolation.sh")], capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    rows = (tmp_path / "launch.log").read_text().splitlines()
    assert "IVSHMEM= " in rows[0] and "IVSHMEM=/dev/shm" in rows[1]


@needs_bash
def test_shift_isolation_stops_when_a_service_did_not_start(tmp_path):
    d, stub, img = _shift_rig(tmp_path)
    env = dict(os.environ, OUTBASE=str(tmp_path / "out"), IMG=str(img), SNAP="1", SEQ="S S",
               STUB_DIR=str(tmp_path), STUB_BROKEN="ifs-shm.bin",
               PATH=_path_with(stub))
    r = subprocess.run([BASH, str(d / "run-shift-isolation.sh")], capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode != 0 and "needs 'shm'" in r.stdout + r.stderr
    assert not (tmp_path / "ladder.log").exists(), "no ladder may run on a guest that is not the condition"


# --------------------------------------------------------------------------
# 2026-09-27: more images per session, and the harness phase


def _harness_env(tmp_path, extra="ifs-trace.bin:" + "f" * 64, harness="run-trace2.sh", **env):
    _inputs_env(tmp_path)
    if extra is not None:
        with open(tmp_path / "inputs.env", "a", encoding="utf-8", newline="\n") as f:
            f.write("IFS_EXTRA=%s\n" % extra)
    g = tmp_path / "repo" / "orin-native" / "gpu-concurrency"
    g.mkdir(parents=True, exist_ok=True)
    if harness:
        (g / harness).write_text("exit 0\n")
    base = {k: v for k, v in os.environ.items() if k not in ("K", "LADDER_ENV")}
    return subprocess.run([BASH, REMOTE, "harness"], capture_output=True, text=True, timeout=60,
                          env=dict(base, W=str(tmp_path), PATH=_path_with(), **env))


@needs_bash
@pytest.mark.parametrize("words,msg", [
    ("HARNESS=run-ladder.sh", "is not one the harness phase runs"),
    ("HARNESS=run-trace.sh IMAGE=ifs-trace.bin", "the repo tarball lacks run-trace.sh"),
    ("HARNESS=run-trace2.sh IMAGE=ifs-nope.bin", "image 'ifs-nope.bin' was not uploaded in this session"),
])
def test_the_harness_phase_runs_only_listed_harnesses_on_uploaded_images(tmp_path, words, msg):
    r = _harness_env(tmp_path, LADDER_ENV=words)
    assert r.returncode != 0 and msg in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("extra", ["ifs-trace.bin:" + "f" * 63, "ifs trace.bin:" + "f" * 64, ""])
def test_a_malformed_extra_image_list_is_refused(tmp_path, extra):
    r = _harness_env(tmp_path, extra=extra, LADDER_ENV="HARNESS=run-trace2.sh IMAGE=ifs-trace.bin")
    assert r.returncode != 0 and "inputs.env is malformed" in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
def test_the_harness_phase_gets_past_its_checks_with_an_uploaded_image(tmp_path):
    # Past every check: it then fails running the stub harness's missing pieces, not a refusal.
    r = _harness_env(tmp_path, LADDER_ENV="HARNESS=run-trace2.sh IMAGE=ifs-trace.bin")
    out = r.stdout + r.stderr
    for refusal in ("is not one", "lacks", "was not uploaded", "malformed"):
        assert refusal not in out, out
    assert (tmp_path / "rec" / "trace2" / "host-before.txt").exists(), out


# 2026-09-29 (later): harnesses that boot more than one image name the others with IMG_ words

_EXTRA3 = " ".join("%s:%s" % (n, "f" * 64) for n in ("ifs-bell.bin", "ifs-robust.bin", "ifs-unmask-a.bin",
                                                     "ifs-unmask-b.bin"))
_SHOW_IMGS = ('printf "%s\\n" "IMG_S=${IMG_S:-}" "IFS_BIN=${IFS_BIN:-}" "IMG_B=${IMG_B:-}" "IMG_R=${IMG_R:-}" '
              '"IMG_UA=${IMG_UA:-}" "IMG_UB=${IMG_UB:-}" > "$W/imgs.txt"\n')
_UNMASK = "HARNESS=run-unmask.sh IMG_UA=ifs-unmask-a.bin IMG_UB=ifs-unmask-b.bin"
_ROBUST = "HARNESS=run-bellrobust.sh IMAGE=ifs-bell.bin IMG_R=ifs-robust.bin IMG_UA=ifs-unmask-a.bin"
# The phase writes host-before.txt from /proc/interrupts, under set -e, before it runs the harness:
# Git Bash has no such file, so a test that needs the harness itself to run is Linux-only.
needs_proc_interrupts = pytest.mark.skipif(
    BASH is None or subprocess.run([BASH, "-c", "test -r /proc/interrupts"]).returncode != 0,
    reason="the harness phase reads /proc/interrupts before it runs the harness; this bash has none")


@needs_bash
@pytest.mark.parametrize("words,k,msg", [
    ("HARNESS=run-bellrobust.sh IMAGE=ifs-bell.bin IMG_R=ifs-nope.bin IMG_UA=ifs-unmask-a.bin", None,
     "image 'ifs-nope.bin' (IMG_R) was not uploaded in this session"),
    (_UNMASK + " IMG_U=ifs-unmask-b.bin", None, "the harness phase passes only IMG_B, IMG_R, IMG_UA and IMG_UB"),
    (_ROBUST + " IMG_S=ifs-bell.bin", None, "the harness phase passes only IMG_B, IMG_R, IMG_UA and IMG_UB"),
    (_ROBUST + " IMG_RX=ifs-robust.bin", None, "the harness phase passes only IMG_B, IMG_R, IMG_UA and IMG_UB"),
    ("HARNESS=run-unmask.sh IMG_UA=ifs-unmask-a.bin IMGUB=ifs-unmask-b.bin", None,
     "LADDER_ENV word 'IMGUB=ifs-unmask-b.bin' is not one the harness phase reads"),
    ("HARNESS=run-unmask.sh IMG_UA=ifs-unmask-a.bin IMG_UB=", None,
     "image '' (IMG_UB) was not uploaded in this session"),
    ("HARNESS=run-unmask.sh IMG_UA=ifs-unmask-a.bin", None,
     "run-unmask.sh boots more than one image: LADDER_ENV needs IMG_UB="),
    ("HARNESS=run-bellrobust.sh IMAGE=ifs-bell.bin IMG_R=ifs-robust.bin", None,
     "run-bellrobust.sh boots more than one image: LADDER_ENV needs IMG_UA="),
    ("HARNESS=run-bellrobust.sh IMG_R=ifs-robust.bin IMG_UA=ifs-unmask-a.bin", None,
     "run-bellrobust.sh boots more than one image: LADDER_ENV needs IMAGE= or IMG_B="),
    (_UNMASK + " IMG_UA=ifs-unmask-b.bin", None, "LADDER_ENV names IMG_UA twice"),
    (_ROBUST + " HARNESS=run-unmask.sh", None, "LADDER_ENV names HARNESS twice"),
    (_ROBUST + " IMAGE=ifs-unmask-b.bin", None, "LADDER_ENV names IMAGE twice"),
    ("HARNESS= HARNESS=run-bell.sh IMAGE=ifs-bell.bin", None, "LADDER_ENV word 'HARNESS=' has no value"),
    ("HARNESS=run-bell.sh IMAGE= IMAGE=ifs-bell.bin", None, "LADDER_ENV word 'IMAGE=' has no value"),
    ("HARNESS=run-bell.sh IMAGE=ifs-bell.bin IMG_B=ifs-bell.bin", None,
     "run-bell.sh takes no IMG_B word (its image is IMAGE=)\n"),
    (_UNMASK + " IMG_R=ifs-robust.bin", None, "run-unmask.sh takes no IMG_R word (it takes IMG_UA IMG_UB)\n"),
    (_ROBUST + " IMG_UB=ifs-unmask-b.bin", None,
     "run-bellrobust.sh takes no IMG_UB word (it takes IMG_B IMG_R IMG_UA)\n"),
    ("HARNESS=run-unmask.sh IMG_UA=ifs-unmask-b.bin IMG_UB=ifs-unmask-b.bin", None,
     "IMG_UA and IMG_UB are the same image"),
    (_UNMASK, "6", "run-unmask.sh needs K a multiple of 4"),
    (_UNMASK, "016", "K='016' is not a round count (digits, no leading zero)"),
    (_UNMASK, "08", "K='08' is not a round count (digits, no leading zero)"),
    (_UNMASK, "0", "K='0' is not a round count (digits, no leading zero)"),
    ("HARNESS=run-bell.sh IMAGE=ifs-bell.bin", "012", "K='012' is not a round count"),
    (_ROBUST, "12", "run-bellrobust.sh takes no K"),
    (None, None, "the harness phase needs LADDER_ENV="),
])
def test_the_harness_phase_refuses_what_it_cannot_resolve_before_making_anything(tmp_path, words, k, msg):
    env = {} if words is None else {"LADDER_ENV": words}
    if k is not None:
        env["K"] = k
    harness = "run-bell.sh" if words is None else (words.split()[0][len("HARNESS="):] or "run-bell.sh")
    r = _harness_env(tmp_path, extra=_EXTRA3, harness=harness, **env)
    assert r.returncode != 0 and msg in r.stdout + r.stderr, r.stdout + r.stderr
    assert not (tmp_path / "rec").exists(), "refused before anything was made"


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("words,k,want", [
    (_ROBUST, None, {"IMG_S": "ifs-bell.bin", "IFS_BIN": "ifs-bell.bin", "IMG_B": "ifs-bell.bin",
                     "IMG_R": "ifs-robust.bin", "IMG_UA": "ifs-unmask-a.bin", "IMG_UB": None}),
    # run-unmask.sh reads no IMAGE=: its IMG_S/IFS_BIN/IMG_B are the session's first image, unused
    (_UNMASK, "8", {"IMG_S": "ifs-kick.bin", "IFS_BIN": "ifs-kick.bin", "IMG_B": "ifs-kick.bin",
                    "IMG_R": None, "IMG_UA": "ifs-unmask-a.bin", "IMG_UB": "ifs-unmask-b.bin"}),
    # an IMG_ word wins over IMAGE's default; IMAGE still sets IMG_S and IFS_BIN
    ("HARNESS=run-bellrobust.sh IMAGE=ifs-unmask-b.bin IMG_B=ifs-bell.bin IMG_R=ifs-robust.bin "
     "IMG_UA=ifs-unmask-a.bin", None,
     {"IMG_S": "ifs-unmask-b.bin", "IFS_BIN": "ifs-unmask-b.bin", "IMG_B": "ifs-bell.bin",
      "IMG_R": "ifs-robust.bin", "IMG_UA": "ifs-unmask-a.bin", "IMG_UB": None}),
])
def test_the_harness_phase_passes_each_named_image_as_this_sessions_upload(tmp_path, words, k, want):
    harness = words.split()[0][len("HARNESS="):]
    g = tmp_path / "repo" / "orin-native" / "gpu-concurrency"
    g.mkdir(parents=True)
    (g / harness).write_text(_SHOW_IMGS + "exit 0\n", encoding="utf-8", newline="\n")
    env = {"LADDER_ENV": words}
    if k is not None:
        env["K"] = k
    r = _harness_env(tmp_path, extra=_EXTRA3, harness=None, **env)
    out = r.stdout + r.stderr
    assert (tmp_path / "imgs.txt").exists(), out
    got = dict(ln.split("=", 1) for ln in (tmp_path / "imgs.txt").read_text().splitlines())
    img = str(tmp_path / "img")
    for key, v in want.items():
        assert got[key] == ("" if v is None else img + "/" + v), (key, got, out)


def _bellrobust_rec(tmp_path, files):
    raw = tmp_path / "rec" / "bellrobust" / "raw"
    for name, text in files.items():
        _write(raw / name, text, newline=False)
    _write(tmp_path / "rec" / "bellrobust" / "run.log", "done")
    return tmp_path / "rec"


_EX = json.dumps({"summary": {"tag": "S1_r1-pre", "n": 2, "bad": 0}, "samples_ms": [1.0, 2.0]})   # synthetic
_STAMP = json.dumps({"experiment": "bellrobust", "repeats": 3})


@pytest.mark.parametrize("files", [
    {"stamp.json": _STAMP},
    {"stamp.json": _STAMP, "kvm-D-db_r1.json": json.dumps({"before": {"t_ns": 1}})},
    {"ex-S1_r1-pre.json": _EX},
    {"stamp.json": _STAMP, "extra.json": _EX},
    {"stamp.json": _STAMP, "scenarios.log": "S4_r1 msixcfg_seen=never msix_monitor_seen=never\nring-S4_r1 rc=0\n"},
])
def test_capture_refuses_a_stamp_without_evidence_or_evidence_without_a_stamp(tmp_path, files):
    r = _capture(_bellrobust_rec(tmp_path, files), tmp_path / "pub")
    assert r.returncode != 0 and "nothing ran" in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("files", [
    {"stamp.json": _STAMP, "ex-S1_r1-pre.json": _EX, "scenarios.log": "S1_r1-pre rc=0 t0=1000 t1=2000\n"},
    # every set failed: the probe wrote no file, but the run is a result and is captured
    {"stamp.json": _STAMP, "scenarios.log": "S1_r1-pre rc=3 t0=1000 t1=2000\n", "probe.log": "no reply"},
])
def test_capture_takes_run_bellrobust_by_its_exchange_sets(tmp_path, files):
    rec = _bellrobust_rec(tmp_path, files)
    r = _capture(rec, tmp_path / "pub")
    assert r.returncode == 0, r.stdout + r.stderr
    for name in files:
        assert (tmp_path / "pub" / "bellrobust" / "raw" / name).exists(), name
    if "ex-S1_r1-pre.json" in files:
        assert (tmp_path / "pub" / "bellrobust" / "raw" / "ex-S1_r1-pre.json").read_bytes() == \
            (rec / "bellrobust" / "raw" / "ex-S1_r1-pre.json").read_bytes()


@needs_bash
def test_capture_holds_an_exchange_set_to_the_arm_files_rule(tmp_path):
    ex = json.dumps({"summary": {"tag": "on i-0123456789abcdef0", "n": 100}})   # documentation instance id
    r = _capture(_bellrobust_rec(tmp_path, {"stamp.json": _STAMP, "ex-S1_r1-pre.json": ex}), tmp_path / "pub")
    assert r.returncode != 0 and "ex-S1_r1-pre.json" in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("bad", ["ifs;x.bin", "ifs-kick.bin"])
def test_upload_refuses_a_bad_or_repeated_extra_image(rig, tmp_path, bad):
    run, state, stub = rig
    _launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")
    d = tmp_path / "in"
    d.mkdir()
    for name in ("repo.tar", "ifs-kick.bin", bad):
        (d / name).write_bytes(b"x")
    with gzip.open(d / "disk-qemu.gz", "wb") as f:
        f.write(b"disk")
    r, _ = run("upload", METAL_REPO_TAR=d / "repo.tar", METAL_IFS=d / "ifs-kick.bin",
               METAL_DISK_GZ=d / "disk-qemu.gz", METAL_IFS_EXTRA=d / bad)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and ("will not pass on" in out or "repeats" in out), out
    assert not (stub / "scp.log").exists(), (stub / "scp.log").read_text()


@needs_bash
def test_upload_sends_and_records_the_extra_images(rig, tmp_path):
    run, state, stub = rig
    _launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")
    d = tmp_path / "in"
    d.mkdir()
    for name in ("repo.tar", "ifs-someip.bin", "ifs-trace.bin", "ifs-stamp.bin"):
        (d / name).write_bytes(name.encode())
    with gzip.open(d / "disk-qemu.gz", "wb") as f:
        f.write(b"disk")
    r, _ = run("upload", METAL_REPO_TAR=d / "repo.tar", METAL_IFS=d / "ifs-someip.bin",
               METAL_DISK_GZ=d / "disk-qemu.gz", METAL_IFS_EXTRA="%s %s" % (d / "ifs-trace.bin", d / "ifs-stamp.bin"))
    assert r.returncode == 0, r.stdout + r.stderr
    scp = (stub / "scp.log").read_text()
    assert "ifs-trace.bin" in scp and "ifs-stamp.bin" in scp, scp
    sha = hashlib.sha256(b"ifs-trace.bin").hexdigest()
    ssh = (stub / "ssh.log").read_text()
    assert "IFS_EXTRA=%s" in ssh and "ifs-trace.bin:" + sha in ssh, ssh


# --------------------------------------------------------------------------
# 2026-09-27: a terminate after a failed fetch lost a billed session's data


@needs_bash
@pytest.mark.parametrize("markers,env,ok", [
    (("uploaded",), {}, False),                           # uploaded, nothing fetched: refused
    (("uploaded",), {"METAL_DISCARD": "1"}, True),        # the operator says to lose it
    (("uploaded", "fetched-ok"), {}, True),               # fetched and scanned: fine
    ((), {}, True),                                       # nothing uploaded yet: nothing to lose
])
def test_terminate_wants_a_fetch_once_something_was_uploaded(rig, markers, env, ok):
    run, state, _ = rig
    _launched(state)
    for m in markers:
        (state / m).touch()
    r, log = run("terminate", **env)
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0 and (state / "terminated").exists(), out
    else:
        assert r.returncode != 0 and "nothing was fetched from this session" in out, out
        assert "terminate-instances" not in log and not (state / "terminated").exists(), log


def test_capture_redacts_many_text_files_side_by_side(tmp_path):
    """capture.py now runs one redactor per text file in parallel: every file must still come
    through redacted, whole and in its own place."""
    rec = _rec(tmp_path)
    for i in range(40):
        _write(rec / "many" / ("t%02d.txt" % i), "line %d from 203.0.113.%d\nplain %d" % (i, i % 250, i))
    r = _capture(rec, tmp_path / "pub")
    assert r.returncode == 0, r.stdout + r.stderr
    for i in range(40):
        got = (tmp_path / "pub" / "many" / ("t%02d.txt" % i)).read_text()
        assert "203.0.113." not in got and ("plain %d" % i) in got, got


# --------------------------------------------------------------------------
# plan Phase 3 WP3: a vss session. Documentation values only (a test fixture is capture data).


# a. METAL_VOLUME_SIZE, and the size read back

@needs_bash
@pytest.mark.parametrize("size,want", [(None, "16"), ("16", "16"), ("32", "32"), ("64", "64")])
def test_launch_sizes_the_root_volume_from_metal_volume_size_and_reads_it_back(rig, size, want):
    run, state, _ = rig
    r, log = run("launch", **({} if size is None else {"METAL_VOLUME_SIZE": size}))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    sent = [ln for ln in log.splitlines() if "run-instances" in ln]
    assert len(sent) == 1 and '"VolumeSize":%s,' % want in sent[0], log
    asked = [ln for ln in log.splitlines() if "describe-volumes" in ln]
    assert asked, log
    assert all("--volume-ids vol-0abcdef1234567890" in ln and "Volumes[0].Size" in ln for ln in asked), log
    assert "terminate-instances" not in log, log
    assert "%s GiB" % want in out, out
    assert (state / "vol").read_text().strip() == "vol-0abcdef1234567890"


@needs_bash
@pytest.mark.parametrize("size", ["15", "65", "0", "8", "128", "032", "32GB", "3 2", "-32", "x"])
def test_launch_refuses_a_volume_size_outside_16_to_64_before_any_aws_call(rig, size):
    run, state, _ = rig
    r, log = run("launch", METAL_VOLUME_SIZE=size)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "METAL_VOLUME_SIZE" in out and "16 to 64" in out, out
    assert log == "", "refused before any aws call: " + log
    assert not (state / "lock").exists() and not (state / "token").exists()


@needs_bash
@pytest.mark.parametrize("got", ["16", "33", "None", ""])
def test_launch_terminates_when_the_root_volume_reads_back_another_size(rig, got):
    run, state, _ = rig
    r, log = run("launch", METAL_VOLUME_SIZE="32", STUB_VOL_SIZE=got)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "reads back as" in out, out
    assert "terminate-instances" in log and (state / "terminated").exists(), log
    # recorded before the read-back, so verify-vol can see it go
    assert (state / "vol").read_text().strip() == "vol-0abcdef1234567890"


# b. METAL_FILES: the driver's side

def _armed(state):
    _launched(state)
    (state / "armed").touch()
    (state / "ip").write_text("203.0.113.9\n")


def _upload_dir(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    for name in ("repo.tar", "ifs-vss.bin", "ifs-trace.bin"):
        (d / name).write_bytes(name.encode())
    with gzip.open(d / "disk-qemu.gz", "wb") as f:
        f.write(b"disk")
    return d


def _upload(run, d, files):
    return run("upload", METAL_REPO_TAR=d / "repo.tar", METAL_IFS=d / "ifs-vss.bin", METAL_DISK_GZ=d / "disk-qemu.gz",
               METAL_IFS_EXTRA=d / "ifs-trace.bin", METAL_FILES=" ".join(str(p) for p in files))


@needs_bash
@pytest.mark.parametrize("names,msg", [
    (["a;b.json"], "has characters this script will not pass on"),
    (["ifs-vss.bin"], "is an image or the disk"),          # the session's image
    (["ifs-trace.bin"], "is an image or the disk"),        # an extra image
    (["disk-qemu.gz"], "is an image or the disk"),
    (["bundle.json", "again/bundle.json"], "METAL_FILES names bundle.json twice"),
    (["missing.tar"], "no readable file"),
    (["adir"], "no readable file"),
])
def test_upload_refuses_a_bad_repeated_or_clashing_file(rig, tmp_path, names, msg):
    run, state, stub = rig
    _armed(state)
    d = _upload_dir(tmp_path)
    paths = []
    for name in names:
        p = tmp_path / "files" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if name == "adir":
            p.mkdir()
        elif name != "missing.tar":
            p.write_bytes(b"x")
        paths.append(p)
    r, _ = _upload(run, d, paths)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and msg in out, out
    assert not (stub / "scp.log").exists() and not (stub / "ssh.log").exists(), "refused before anything was sent"


@needs_bash
@pytest.mark.parametrize("names", [[], ["bundle.json", "sdv-arm64-images.tar", "cpython-3.12-aarch64-install_only.tar.gz"]])
def test_upload_sends_the_files_to_a1_in_and_records_each_hash(rig, tmp_path, names):
    run, state, stub = rig
    _armed(state)
    d = _upload_dir(tmp_path)
    _tar_with_commit(d / "repo.tar", "e" * 40)     # WP3fix, NIT 9: bundle.json names the tarball's commit
    (tmp_path / "files").mkdir()
    content = {n: ("content of " + n).encode() for n in names}
    if "bundle.json" in content:
        content["bundle.json"] = json.dumps({"format": 1, "commit": "e" * 40}).encode()
    paths = []
    for name in names:
        (tmp_path / "files" / name).write_bytes(content[name])
        paths.append(tmp_path / "files" / name)
    r, _ = _upload(run, d, paths)
    assert r.returncode == 0, r.stdout + r.stderr
    sha = {n: hashlib.sha256(content[n]).hexdigest() for n in names}
    scp = [ln for ln in (stub / "scp.log").read_text().splitlines() if "a1/in/" in ln]
    ssh = (stub / "ssh.log").read_text()
    inputs = (state / "inputs.txt").read_text().splitlines()
    assert "mkdir -p ~/a1/img ~/a1/in" in ssh, ssh
    if not names:
        assert scp == [] and "FILES=" not in ssh and not [ln for ln in inputs if ln.startswith("file ")]
        return
    assert len(scp) == 1 and all(n in scp[0] for n in names), scp
    assert "printf 'FILES=%s\\n' '" + " ".join("%s:%s" % (n, sha[n]) for n in names) + "' >> ~/a1/inputs.env" in ssh, ssh
    assert [ln for ln in inputs if ln.startswith("file ")] == ["file %s %s" % (n, sha[n]) for n in names], inputs


@needs_bash
def test_run_reaches_wait_run_and_the_vss_words_but_never_the_internal_detached_runner(rig):
    run, state, stub = rig
    _armed(state)
    r, _ = run("run", "wait-run", LADDER_ENV="HARNESS=run-vss-setup.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    r, _ = run("run", "harness", LADDER_ENV="HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1 VSS_HOST=c7g-metal")
    assert r.returncode == 0, r.stdout + r.stderr
    log = (stub / "ssh.log").read_text()
    assert "remote-ladder.sh wait-run" in log and "HARNESS=run-vss-setup.sh" in log, log
    assert "remote-ladder.sh harness" in log and "PLAN=v1" in log and "VSS_HOST=c7g-metal" in log, log
    (stub / "ssh.log").unlink()
    r, _ = run("run", "_detached")
    assert r.returncode != 0 and "unknown phase" in r.stdout + r.stderr, r.stdout + r.stderr
    assert not (stub / "ssh.log").exists(), "nothing may reach the instance"


_VSS_SETUP_W = "HARNESS=run-vss-setup.sh IMAGE=ifs-vss.bin"
_VSS_SUITE_W = "HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v2"


@needs_bash
@pytest.mark.parametrize("typ,phase,words,sent,refused", [
    ("c7g.metal", "harness", _VSS_SETUP_W, "VSS_HOST=c7g-metal", None),
    ("a1.metal", "harness", _VSS_SETUP_W, "VSS_HOST=a1-metal", None),
    ("c7g.metal", "harness", _VSS_SUITE_W, "VSS_HOST=c7g-metal", None),
    ("c7g.metal", "harness", _VSS_SUITE_W + " VSS_HOST=c7g-metal", "VSS_HOST=c7g-metal", None),
    ("a1.metal", "harness", _VSS_SETUP_W + " VSS_HOST=a1-metal", "VSS_HOST=a1-metal", None),
    ("c7g.metal", "harness", _VSS_SETUP_W + " VSS_HOST=a1-metal", None,
     "VSS_HOST=a1-metal, but this session launched c7g.metal (VSS_HOST=c7g-metal)"),
    ("a1.metal", "harness", _VSS_SUITE_W + " VSS_HOST=c7g-metal", None,
     "VSS_HOST=c7g-metal, but this session launched a1.metal (VSS_HOST=a1-metal)"),
    ("c6g.metal", "harness", _VSS_SETUP_W, None, "this session launched c6g.metal, which has no vss host role"),
    (None, "harness", _VSS_SETUP_W, "", None),                                   # no type recorded: the words as given
    ("c7g.metal", "harness", "HARNESS=run-bell.sh IMAGE=ifs-bell.bin", "", None),  # an A6 harness: no word
    ("c7g.metal", "wait-run", "HARNESS=run-vss-setup.sh", "", None),             # wait-run reads HARNESS= alone
], ids=["c7g-setup", "a1-setup", "c7g-suite", "c7g-given", "a1-given", "a1-word-on-c7g", "c7g-word-on-a1", "c6g",
        "no-type", "a6-harness", "wait-run"])
def test_run_gives_a_vss_harness_the_host_mode_of_the_type_this_session_launched(rig, typ, phase, words, sent, refused):
    """2026-10-17, with c7g.metal the default type: a vss harness's VSS_HOST follows the type `launch` recorded, so that
    a session's records name the host it ran on whatever the operator remembers. Without the word, `run harness` adds
    the type's (a1.metal: a1-metal, c7g.metal: c7g-metal); a word that is not the type's is refused before anything
    reaches the instance, and so is a vss harness on a type with no host role. An A6 harness and wait-run get no word; a
    session state from before the type was recorded passes the words as given."""
    run, state, stub = rig
    _armed(state)
    if typ:
        (state / "type").write_text(typ + "\n")
    r, _ = run("run", phase, LADDER_ENV=words)
    out = r.stdout + r.stderr
    log = (stub / "ssh.log").read_text() if (stub / "ssh.log").exists() else ""
    if refused:
        assert r.returncode != 0 and refused in out and log == "", out + log
        return
    assert r.returncode == 0, out
    line = [ln for ln in log.splitlines() if "remote-ladder.sh %s" % phase in ln]
    assert len(line) == 1, log
    assert line[0].count("VSS_HOST=") == (1 if sent else 0) and (not sent or sent in line[0]), line[0]


def test_the_readme_says_whether_run_harness_adds_the_drills_vss_host_word_as_drive_metal_does():
    """SDV Phase 6 WP6: drive-metal.sh is not the drill's package's file. Its vss_host_words adds the launched type's
    VSS_HOST word to the calls of the vss harnesses its first case names; the README's drill section says what it does
    for run-ota-drill.sh's call: added by itself when that case names the drill, given by hand when it does not."""
    with open(DRIVER, encoding="utf-8") as f:
        m = re.search(r"^\s*vss_host_words\(\) \{\n[^\n]*\n\s*(case \" \$words \" in [^\n]*)$", f.read(), re.M)
    assert m is not None, "vss_host_words's first case line"
    adds = "HARNESS=run-ota-drill.sh" in m.group(1)
    with open(os.path.join(AWSDIR, "README.md"), encoding="utf-8") as f:
        text = f.read()
    readme = re.sub(r"\s+", " ", text[text.index("### An OTA drill session"):text.index("## What bounds the cost")])
    by_itself = "and to the drill's call too" in readme
    by_hand = "but not to the drill's, so give it there by hand" in readme
    assert (by_itself, by_hand) == (adds, not adds), (adds, by_itself, by_hand)


# b. METAL_FILES: the instance's side

@needs_bash
@pytest.mark.parametrize("files", ["bundle.json:" + "f" * 63, "bundle json:" + "f" * 64, "", "..:" + "f" * 64,
                                   "bundle.json", "bundle.json:" + "F" * 64])
def test_a_malformed_file_list_is_refused(tmp_path, files):
    _inputs_env(tmp_path)
    with open(tmp_path / "inputs.env", "a", encoding="utf-8", newline="\n") as f:
        f.write("FILES=%s\n" % files)
    r = _remote(tmp_path)
    assert r.returncode != 0 and "inputs.env is malformed (FILES" in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
def test_a_well_formed_file_list_gets_past_the_parser(tmp_path):
    _inputs_env(tmp_path)
    with open(tmp_path / "inputs.env", "a", encoding="utf-8", newline="\n") as f:
        f.write("FILES=bundle.json:%s sdv-gen.tar:%s\n" % ("a" * 64, "b" * 64))
    r = _remote(tmp_path)
    assert r.returncode != 0 and "malformed" not in r.stdout + r.stderr, r.stdout + r.stderr


def _posix(p):
    """p as this bash names it: GNU tar reads the "C:" of a Windows path given to -f as a remote host."""
    if os.name != "nt":
        return str(p)
    r = subprocess.run([BASH, "-c", 'cygpath -u "$1"', "_", str(p)], capture_output=True, text=True,
                       env=dict(os.environ, PATH=_path_with()))
    return r.stdout.strip()


def _stubs(d, bodies):
    d.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        _write(d / name, "#!/usr/bin/env bash\n" + body, newline=True)
        os.chmod(str(d / name), 0o755)
    return d


def _setup_run(tmp_path, files, wrong=(), missing=()):
    """remote-ladder.sh setup on a W laid out as upload leaves it: every hash right but the named ones. It then
    stops at the bridge, past every hash check: this rig has no `ip` and no `sudo` (stubs that fail)."""
    def sha(b):
        return hashlib.sha256(b).hexdigest()
    w = tmp_path / "w"
    (w / "img").mkdir(parents=True)
    with tarfile.open(str(w / "repo.tar"), "w") as t:
        _write(tmp_path / "x" / "README.md", "stand-in")
        t.add(str(tmp_path / "x" / "README.md"), arcname="orin-native/gpu-concurrency/README.md")
    (w / "img" / "ifs-vss.bin").write_bytes(b"ifs-vss")
    (w / "img" / "disk-qemu").write_bytes(b"disk")
    shutil.copy(REMOTE, str(w / "remote-ladder.sh"))
    shutil.copy(CAPTURE, str(w / "capture.py"))
    _inputs_env(w, IFS_NAME="ifs-vss.bin", IFS_SHA256=sha(b"ifs-vss"), DISK_SHA256=sha(b"disk"),
                REMOTE_LADDER_SHA256=sha((w / "remote-ladder.sh").read_bytes()),
                CAPTURE_SHA256=sha((w / "capture.py").read_bytes()))
    words = []
    for name, data in files.items():
        if name not in missing:
            (w / "in").mkdir(exist_ok=True)
            (w / "in" / name).write_bytes(data)
        words.append("%s:%s" % (name, "0" * 64 if name in wrong else sha(data)))
    with open(w / "inputs.env", "a", encoding="utf-8", newline="\n") as f:
        f.write("FILES=%s\n" % " ".join(words))
    stub = _stubs(tmp_path / "bin", {"id": 'echo "ubuntu adm kvm"', "ip": "exit 1", "sudo": "exit 1"})
    r = subprocess.run([BASH, REMOTE, "setup"], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, W=_posix(w), REHEARSAL="1", PATH=_path_with(stub)))
    return w, r


_FILES = {"bundle.json": b'{"format": 1}\n', "sdv-gen.tar": b"gen", "rec-20260930-sigsim-1b.tar": b"rec"}


@needs_bash
def test_setup_verifies_every_uploaded_file_names_them_and_keeps_bundle_json_in_the_record(tmp_path):
    w, r = _setup_run(tmp_path, _FILES)
    out = r.stdout + r.stderr
    line = [ln for ln in out.splitlines() if "artefacts verified" in ln]
    assert len(line) == 1 and all(n in line[0] for n in _FILES), out
    assert "hash mismatch" not in out, out
    assert (w / "rec" / "tooling" / "bundle.json").read_bytes() == _FILES["bundle.json"]
    assert "FILES=" in (w / "rec" / "tooling" / "inputs.env").read_text()


@needs_bash
@pytest.mark.parametrize("how", ["wrong", "missing"])
def test_setup_refuses_a_file_that_is_not_what_was_uploaded(tmp_path, how):
    w, r = _setup_run(tmp_path, _FILES, **{how: ("sdv-gen.tar",)})
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "sdv-gen.tar hash mismatch" in out, out
    assert "artefacts verified" not in out, out


# SDV Phase 6 WP6: the OTA drill's three files, which a drill session's METAL_FILES carries beside the upload bundle
_DRILL_FILES = {"drill-images.json": b'{"format": 1}\n', "sdv-drill.tar": b"a docker save of the three pinned images (a stand-in)",
                "sdv-drill.tar.sha256": b"0" * 64 + b"  sdv-drill.tar\ncommit " + b"0" * 40 + b"\n"}


@needs_bash
@pytest.mark.parametrize("drill", [True, False], ids=["with-the-drills-files", "a-vss-session"])
def test_setup_moves_the_drills_files_out_of_the_bundle_directory_once_checked(tmp_path, drill):
    """in/ is the upload bundle's directory, and run-vss-setup.sh's preflight runs `bundle.py verify --in` on it, which
    refuses a file bundle.json does not list. So setup, once every file's hash is checked, moves the drill's three files
    to drill-in/ (run-ota-drill.sh's DRILL_IN): in/ holds the bundle's files and nothing else. A session without them has
    no drill-in/."""
    files = dict(_FILES, **_DRILL_FILES) if drill else dict(_FILES)
    w, r = _setup_run(tmp_path, files)
    out = r.stdout + r.stderr
    line = [ln for ln in out.splitlines() if "artefacts verified" in ln]
    assert len(line) == 1 and all(n in line[0] for n in files) and "hash mismatch" not in out, out
    assert sorted(os.listdir(str(w / "in"))) == sorted(_FILES), out
    if drill:
        assert sorted(os.listdir(str(w / "drill-in"))) == sorted(_DRILL_FILES), out
        assert all((w / "drill-in" / n).read_bytes() == b for n, b in _DRILL_FILES.items())
    else:
        assert not (w / "drill-in").exists()


@needs_bash
def test_setup_checks_a_drill_files_hash_before_it_moves_anything(tmp_path):
    w, r = _setup_run(tmp_path, dict(_FILES, **_DRILL_FILES), wrong=("sdv-drill.tar",))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "in/sdv-drill.tar hash mismatch" in out, out
    assert not (w / "drill-in").exists() and sorted(os.listdir(str(w / "in"))) == sorted(dict(_FILES, **_DRILL_FILES))


# c-h. The harness phase for a vss harness, wait-run, the marker, the deadline, quiesce

LIB = os.path.join(REPO, "orin-native", "gpu-concurrency", "lib-vss-deadline.sh")
_VSS_BOTH = ("run-vss-setup.sh", "run-vss-suite.sh")
_A6_HARNESSES = ("run-someip.sh", "run-someip0.sh", "run-someip1.sh", "run-trace.sh", "run-trace2.sh",
                 "run-haltpoll.sh", "run-bell.sh", "run-paths.sh", "run-mmio.sh", "run-bellrate.sh",
                 "run-unmask.sh", "run-bellrobust.sh")
_A6_PHASES = ("launch", "ladder", "launch-live", "liveness", "launch-stamp", "stamp", "metal", "someip")
_SETUP = "HARNESS=run-vss-setup.sh IMAGE=ifs-vss.bin"
_SUITE = "HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1"
_QUIESCE_REC = "== quiesce (a stand-in record)\ndocker.socket absent absent\n== platform-quiesce.sh exit 0\n"

# A stub vss harness: what it was given, then the scenario its environment names. STUB_RELEASE holds it
# (bounded) until the test lets it end.
_STUB_VSS = r'''#!/usr/bin/env bash
mkdir -p "$OUT"
printf '%s\n' "PLAN=${PLAN:-}" "VSS_IN=${VSS_IN:-}" "VSS_HOME=${VSS_HOME:-}" "STATUS=${STATUS:-}" \
  "IFS_BIN=${IFS_BIN:-}" "DISK=${DISK:-}" "OUT=$OUT" "K=${K:-}" "PWD=$PWD" "VSS_HOST=${VSS_HOST-<unset>}" \
  "DRILL_IN=${DRILL_IN-<unset>}" > "$OUT/env.txt"
echo "stub $(basename "$0") running"
if [ -n "${STUB_RELEASE:-}" ]; then
  for _ in $(seq 1 200); do [ -e "$STUB_RELEASE" ] && break; sleep 0.05; done
fi
[ -z "${STUB_STATUS_LINE:-}" ] || echo "$STUB_STATUS_LINE" >> "$STATUS"
echo "stub $(basename "$0") ends"
exit "${STUB_RC:-0}"
'''
# A stub vss harness holding the deadline contract: one check point, then one unit under its cap, called in the form
# lib-vss-deadline.sh's header gives (WP3fix, NIT 11: bare, a fired cap would end it under set -e).
_STUB_DEADLINE = r'''#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/lib-vss-deadline.sh"
mkdir -p "$OUT"
vss_deadline_load
if vss_past_stop; then
  vss_status TIMEOUT at=step-1 reason=deadline
  printf '{"status": "TIMEOUT", "at": "step-1", "not_run": ["step-1"]}\n' > "$OUT/setup.json"
  exit 0
fi
rc=0; vss_capped true || rc=$?
if vss_cap_fired "$rc"; then
  vss_status TIMEOUT at=step-1 reason=step-timeout
  printf '{"status": "TIMEOUT", "at": "step-1", "not_run": []}\n' > "$OUT/setup.json"
  exit 0
fi
[ "$rc" = 0 ] || exit "$rc"
vss_status DONE
printf '{"status": "DONE"}\n' > "$OUT/setup.json"
'''
# platform-quiesce.sh as a1.metal before Docker would answer it, with a chosen exit status
_STUB_PQ = r'''#!/usr/bin/env bash
echo "pq $*" >> "$STUB_DIR/pq.log"
printf '%s\n' "docker.socket absent absent" "docker absent absent" "containerd absent absent"
[ -z "${STUB_PQ_ERR:-}" ] || echo "$STUB_PQ_ERR" >&2
exit "${STUB_PQ_RC:-0}"
'''
_STUB_BIN = {
    # no real setsid in Git Bash; on Linux the stub keeps a log of what it was given
    "setsid": 'echo "setsid $*" >> "$STUB_DIR/setsid.log"; exec "$@"',
    # quiesce's helpers: nothing on this machine may be stopped, waited for or run as root
    "sudo": 'echo "sudo $*" >> "$STUB_DIR/sudo.log"; [ "$1" = -n ] && shift; '
            'case "$1" in *k3s-killall.sh) exec "$@" ;; esac; exit 0',
    "cloud-init": "exit 0", "snap": "exit 0", "pgrep": "exit 1",
    # the deadline contract's cap: logged, the command run without one
    "timeout": 'echo "timeout $*" >> "$STUB_DIR/timeout.log"; while [ "${1#--}" != "$1" ]; do shift; done; '
               'shift; exec "$@"',
}


def _vss_w(tmp_path, harness_body=_STUB_VSS, step3=True, quiesce=True, lib=True, ahead_min=80):
    """W as setup and quiesce leave it for a vss session: the vss image and one more uploaded, the tarball's
    vss form (sdv/stack/step3.py, the deadline library), the stub harnesses, quiesce's record."""
    w = tmp_path / "w"
    w.mkdir()
    _inputs_env(w, IFS_NAME="ifs-vss.bin")
    with open(w / "inputs.env", "a", encoding="utf-8", newline="\n") as f:
        f.write("IFS_EXTRA=ifs-bell.bin:%s\n" % ("f" * 64))
    g = w / "repo" / "orin-native" / "gpu-concurrency"
    g.mkdir(parents=True)
    for h in _VSS_BOTH:
        _write(g / h, harness_body, newline=False)
    _write(g / "platform-quiesce.sh", _STUB_PQ, newline=False)
    if lib:
        shutil.copy(LIB, str(g / "lib-vss-deadline.sh"))
    if step3:
        _write(w / "repo" / "sdv" / "stack" / "step3.py", "# stand-in")
    if quiesce:
        _write(w / "rec" / "quiesce.txt", _QUIESCE_REC, newline=False)
    shutil.copy(REMOTE, str(w / "remote-ladder.sh"))
    _write(w / "deadline", str(int(time.time()) + ahead_min * 60))
    return w, _stubs(tmp_path / "bin", _STUB_BIN)


def _vss_phase(w, stub, phase, words=None, timeout=60, popen=False, **env):
    drop = ("K", "LADDER_ENV", "PLAN", "STATUS", "VSS_IN", "VSS_HOME", "OUT", "IFS_BIN", "STUB_RELEASE",
            "STUB_STATUS_LINE", "STUB_RC", "QNX_METAL_DEADLINE_FILE", "K3S_KILLALL", "WAIT_POLL_S", "VSS_HOST")
    e = {k: v for k, v in os.environ.items() if k not in drop}
    e.update(W=str(w), PATH=_path_with(stub), STUB_DIR=str(stub), QNX_METAL_DEADLINE_FILE=str(w / "deadline"),
             WAIT_POLL_S="0.1", K3S_KILLALL=str(w / "no-k3s" / "k3s-killall.sh"))
    if words is not None:
        e["LADDER_ENV"] = words
    e.update({k: str(v) for k, v in env.items()})
    if popen:
        return subprocess.Popen([BASH, REMOTE, phase], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=e)
    return subprocess.run([BASH, REMOTE, phase], capture_output=True, text=True, timeout=timeout, env=e)


def _wait_for(path, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        if os.path.exists(str(path)):
            return True
        time.sleep(0.05)
    return False


def _env_of(d):
    return dict(ln.split("=", 1) for ln in (d / "raw" / "env.txt").read_text().splitlines())


@needs_bash
@pytest.mark.parametrize("words,k,msg", [
    ("HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin", None, "run-vss-suite.sh needs PLAN=v1, PLAN=v2 or PLAN=carla"),
    ("HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v3", None, "run-vss-suite.sh needs PLAN=v1, PLAN=v2 or PLAN=carla"),
    ("HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=V1", None, "run-vss-suite.sh needs PLAN=v1, PLAN=v2 or PLAN=carla"),
    # SDV Phase 7 WP3d: carla is the suite's third plan, the word whole and in lower case
    ("HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=CARLA", None, "run-vss-suite.sh needs PLAN=v1, PLAN=v2 or PLAN=carla"),
    ("HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=carla2", None, "run-vss-suite.sh needs PLAN=v1, PLAN=v2 or PLAN=carla"),
    ("HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v2carla", None, "run-vss-suite.sh needs PLAN=v1, PLAN=v2 or PLAN=carla"),
    (_SETUP + " PLAN=v1", None, "run-vss-setup.sh takes no PLAN word"),
    (_SETUP + " PLAN=carla", None, "run-vss-setup.sh takes no PLAN word"),
    ("HARNESS=run-bell.sh IMAGE=ifs-bell.bin PLAN=v1", None, "run-bell.sh takes no PLAN word"),
    ("HARNESS=run-bell.sh IMAGE=ifs-bell.bin PLAN=carla", None, "run-bell.sh takes no PLAN word"),
    ("HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=", None, "LADDER_ENV word 'PLAN=' has no value"),
    (_SUITE + " PLAN=v2", None, "LADDER_ENV names PLAN twice"),
    (_SUITE + " PLAN=carla", None, "LADDER_ENV names PLAN twice"),
    ("HARNESS=run-vss-setup.sh", None, "run-vss-setup.sh needs IMAGE="),
    ("HARNESS=run-vss-suite.sh PLAN=v1", None, "run-vss-suite.sh needs IMAGE="),
    (_SETUP, "4", "run-vss-setup.sh takes no K"),
    (_SUITE, "12", "run-vss-suite.sh takes no K"),
    (_SETUP + " IMG_B=ifs-vss.bin", None, "run-vss-setup.sh takes no IMG_B word (its image is IMAGE=)"),
    (_SUITE + " IMG_R=ifs-bell.bin", None, "run-vss-suite.sh takes no IMG_R word (its image is IMAGE=)"),
    ("HARNESS=run-vss-setup.sh IMAGE=ifs-nope.bin", None, "image 'ifs-nope.bin' was not uploaded in this session"),
    ("HARNESS=run-vss-other.sh IMAGE=ifs-vss.bin", None, "is not one the harness phase runs"),
    # 2026-10-17: VSS_HOST=, a vss harness's bare-metal AWS host mode (a1-metal or c7g-metal)
    (_SETUP + " VSS_HOST=orin", None, "VSS_HOST=orin is not a bare-metal AWS host: a1-metal or c7g-metal"),
    (_SETUP + " VSS_HOST=c7g.metal", None, "VSS_HOST=c7g.metal is not a bare-metal AWS host: a1-metal or c7g-metal"),
    (_SUITE + " VSS_HOST=C7G-METAL", None, "VSS_HOST=C7G-METAL is not a bare-metal AWS host: a1-metal or c7g-metal"),
    (_SETUP + " VSS_HOST=", None, "LADDER_ENV word 'VSS_HOST=' has no value"),
    (_SETUP + " VSS_HOST=c7g-metal VSS_HOST=c7g-metal", None, "LADDER_ENV names VSS_HOST twice"),
    ("HARNESS=run-bell.sh IMAGE=ifs-bell.bin VSS_HOST=c7g-metal", None, "run-bell.sh takes no VSS_HOST word (only the vss harnesses do)"),
])
def test_the_harness_phase_holds_a_vss_harness_to_its_words_before_making_anything(tmp_path, words, k, msg):
    w, stub = _vss_w(tmp_path)
    r = _vss_phase(w, stub, "harness", words, **({} if k is None else {"K": k}))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and msg in out, out
    assert sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt"], "refused before anything was made"
    assert not (w / "vss-session").exists() and not (stub / "setsid.log").exists() and not (w / "vss-host").exists()


# SDV Phase 7 WP3d: PLAN=carla, the suite's third plan. run-vss-suite.sh
# takes it (Phase 7 WP3b), and its own preflight refuses it when the profiles setup's guest listed in its `vss rules:`
# lines do not include 3. The harness phase passes the word through as it passes v1 and v2, and judges no image by it: a
# carla session's METAL_IFS is ifs-vss-carla.bin.

def test_the_harness_phase_passes_exactly_the_plans_run_vss_suite_sh_takes():
    """The phase's plan list is the suite's preflight list and vss_suite.py's plan table, in that order; its refusal,
    its header and the README's two harness bullets name each plan. The header and the README say what PLAN=carla is as
    written: the word passed through, profile 3 in setup's `vss rules:` lines, each plan's image, and v2's units."""
    import ast
    with open(REMOTE, encoding="utf-8") as f:
        ladder = f.read()
    m = re.search(r'^\s*if \[ "\$H" = run-vss-suite\.sh \]; then[^\n]*\n\s*case "\$P" in ([^)\s]*)\) ;; \*\) die "([^"]*)" ;; esac$',
                  ladder, re.M)
    assert m is not None, "the harness phase's PLAN case for run-vss-suite.sh"
    gc = os.path.join(REPO, "orin-native", "gpu-concurrency")
    with open(os.path.join(gc, "run-vss-suite.sh"), encoding="utf-8") as f:
        s = re.search(r'^\s*case "\$\{PLAN:-\}" in\n\s*([^)\s]*)\) ;;$', f.read(), re.M)
    assert s is not None, "run-vss-suite.sh's preflight PLAN case"
    with open(os.path.join(gc, "vss_suite.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    table = [n.value for n in tree.body
             if isinstance(n, ast.Assign) and [getattr(t, "id", None) for t in n.targets] == ["PLAN_RECORDINGS"]]
    assert len(table) == 1, "vss_suite.py's PLAN_RECORDINGS"
    plans = list(ast.literal_eval(table[0]))
    assert m.group(1).split("|") == s.group(1).split("|") == plans == ["v1", "v2", "carla"], (m.group(1), s.group(1), plans)

    def listed(form):   # "A, B or C"
        names = [form % p for p in plans]
        return ", ".join(names[:-1]) + " or " + names[-1]
    assert m.group(2) == "run-vss-suite.sh needs " + listed("PLAN=%s"), m.group(2)
    header = _one_paragraph(ladder[ladder.index("# A VSS SESSION"):ladder.index("#   THE OTA DRILL")])
    assert 'LADDER_ENV="HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1|v2"' in header, header
    assert "IMAGE=ifs-vss-carla.bin PLAN=carla" in header, header
    # the sentences that say what the word is: a digit or a phrase changed in one of them would
    # tell the operator another profile, image or plan, and no other test reads them
    assert "this phase passes the word through" in header, header
    assert ("the suite's own preflight refuses it, spending its one run, when the profiles setup's guest listed in its "
            "`vss rules:` lines do not include 3") in header, header
    with open(os.path.join(AWSDIR, "README.md"), encoding="utf-8") as f:
        text = f.read()
    image = re.sub(r"\s+", " ", text[text.index("- **`METAL_IFS`** is"):text.index("- **`METAL_VOLUME_SIZE=32`.**")])
    assert ("- **`METAL_IFS`** is `ifs-vss.bin` for `PLAN=v1` or `PLAN=v2`, and `ifs-vss-carla.bin` for `PLAN=carla`"
            in image), image
    assert ("Its guest's `vss rules:` lines must list profile 3, or the suite's preflight refuses `PLAN=carla`"
            in image), image
    words = re.sub(r"\s+", " ", text[text.index("- **Two harnesses, run detached.**"):text.index("- **`VSS_HOST=`**")])
    assert "`run-vss-suite.sh` takes `IMAGE=` and %s," % listed("`PLAN=%s`") in words, words
    assert "`METAL_IFS` is `ifs-vss-carla.bin`. The phase passes the word through." in words, words
    assert ("The suite's own preflight refuses it when the profiles setup's guest listed in its `vss rules:` lines "
            "do not include 3, and that refusal spends the suite's one run.") in words, words
    suite = re.sub(r"\s+", " ", text[text.index("- **`run-vss-suite.sh`**"):])
    assert "Its preflight refuses: a `PLAN` other than %s," % listed("`%s`") in suite, suite[:600]
    assert "`PLAN=carla` is `v2`'s units and compares over the CARLA pair" in suite, suite[:600]
    assert "profiles do not include the recordings' profile, 3 (or that recorded none)" in suite, suite[:1200]


# A stub vss harness that dumps its WHOLE environment (NUL-separated), not the eighteen variables _STUB_ENV names below: a
# variable the phase adds for one plan alone shows in it.
_STUB_ENV_WHOLE = r'''#!/usr/bin/env bash
mkdir -p "$OUT"
env -0 | sort -z > "$OUT/env-whole.bin"
echo "status=DONE" >> "$STATUS"
'''
# the variables the phase gives a vss harness (the ones _STUB_ENV prints)
_ENV_NAMES = ("W IMG_S IMG_B IFS_BIN DISK VPROBE OUT CSTATE PLAN VSS_HOST VSS_IN DRILL_IN VSS_HOME STATUS K LADDER_ENV IMAGE "
              "HARNESS").split()


def _whole_env(path):
    """What _STUB_ENV_WHOLE dumped, as {name: value}."""
    with open(str(path), "rb") as f:
        return dict(e.decode("utf-8", "replace").split("=", 1) for e in f.read().split(b"\0") if e)


def _plan_session(root, image, plan, word):
    """A vss session on ROOT (a new directory) whose METAL_IFS is IMAGE, its harnesses dumping the whole environment they
    are given: a stub setup that ended DONE, then the suite with PLAN=<plan> and the host word, if any. The harness phase
    must start both. Returns W, the stub directory and, per stem, (the words, the stem's directory, the harness's
    environment, the phase's result)."""
    root.mkdir()
    w, stub = _vss_w(root, harness_body=_STUB_ENV_WHOLE)
    _inputs_env(w, IFS_NAME=image)   # the session's METAL_IFS
    tail = "" if word is None else " VSS_HOST=" + word
    got = {}
    for words, stem in (("HARNESS=run-vss-setup.sh IMAGE=" + image, "vss-setup"),
                        ("HARNESS=run-vss-suite.sh IMAGE=%s PLAN=%s" % (image, plan), "vss-suite")):
        r = _vss_phase(w, stub, "harness", words + tail)
        d = w / "rec" / stem
        assert r.returncode == 0 and "started" in r.stdout + r.stderr and _wait_for(d / "done"), r.stdout + r.stderr
        got[stem] = (words + tail, d, _whole_env(d / "raw" / "env-whole.bin"), r)
    return w, stub, got


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("word", [None, "a1-metal", "c7g-metal"], ids=["no-word", "a1-metal", "c7g-metal"])
@pytest.mark.parametrize("plan,image", [("v1", "ifs-vss.bin"), ("v2", "ifs-vss.bin"), ("carla", "ifs-vss-carla.bin")],
                         ids=["v1", "v2", "carla"])
def test_the_suite_gets_its_plan_word_as_given_v1_and_v2_as_before_and_carla_on_the_carla_image(tmp_path, plan, image, word):
    """After a stub setup that ended DONE on the session's METAL_IFS, the phase starts the suite detached, and the suite
    gets PLAN=<the word> and every other variable exactly as the two vss harnesses' calls are held whole below (no word,
    VSS_HOST=a1-metal, or VSS_HOST=c7g-metal, the default bare-metal host's). Under PLAN=carla the suite's whole
    environment, every variable its stub is given, is also a v2 suite's in the same session form, less PLAN and LADDER_ENV
    (the two sessions' own directories apart)."""
    w, stub, got = _plan_session(tmp_path / "s", image, plan, word)
    img = str(w / "img" / image)
    for stem, (words, d, env, _r) in got.items():
        seen = {k: v for k, v in env.items() if k in _ENV_NAMES}
        want = {"W": str(w), "IMG_S": img, "IMG_B": img, "IFS_BIN": img, "DISK": str(w / "img" / "disk-qemu"),
                "VPROBE": str(w / "vsomeip" / "3.4.10" / "bin" / "someip_vprobe"), "OUT": str(d / "raw"), "CSTATE": "shallow",
                "VSS_IN": str(w / "in"), "VSS_HOME": str(w / "sdv"), "STATUS": str(d / "status"),
                "LADDER_ENV": words}
        if stem == "vss-suite":
            want["PLAN"] = plan
        if word:
            want["VSS_HOST"] = word
        assert seen == want, (stem, seen)
        assert (d / "host-after.txt").exists() and (d / "status").read_text().splitlines() == ["status=DONE"], stem
    log = (stub / "setsid.log").read_text()
    assert re.search(r"^setsid nohup bash \S*remote-ladder\.sh _detached vss-suite run-vss-suite\.sh$", log, re.M), log
    if plan == "carla":
        _w2, _stub2, v2 = _plan_session(tmp_path / "v2", image, "v2", word)

        def rest(root, session):   # the suite's variables but PLAN and LADDER_ENV, the session's own directory made nameless
            return {k: v.replace(str(root), "<ROOT>") for k, v in session["vss-suite"][2].items()
                    if k not in ("PLAN", "LADDER_ENV")}
        a, b = rest(tmp_path / "s", got), rest(tmp_path / "v2", v2)
        differ = {k: (a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}
        assert not differ, "the carla suite's environment differs from a v2 suite's in (carla, v2): %r" % (differ,)


@needs_bash
@needs_proc_interrupts
def test_plan_carla_is_passed_through_on_the_vss_image_as_the_phase_names_no_image_for_a_plan(tmp_path):
    """The documented pass-through (README.md: the phase passes the word through): METAL_IFS=ifs-vss.bin, a stub setup that
    ended DONE, then IMAGE=ifs-vss.bin PLAN=carla. The phase starts the suite and gives it PLAN=carla. It reads no profile
    list and names no image for a plan: whether the image's guest lists profile 3 is the suite's own preflight's to judge."""
    w, _stub, got = _plan_session(tmp_path / "s", "ifs-vss.bin", "carla", None)
    words, _d, env, r = got["vss-suite"]
    assert words == "HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=carla", words
    assert r.returncode == 0 and "started" in r.stdout + r.stderr, r.stdout + r.stderr
    assert env["PLAN"] == "carla" and env["IFS_BIN"] == str(w / "img" / "ifs-vss.bin"), (env["PLAN"], env["IFS_BIN"])
    assert [ln.split()[0] for ln in (w / "vss-session").read_text().splitlines()] == ["run-vss-setup.sh", "run-vss-suite.sh"]


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("plan", [None, "v3", "V1", "CARLA", "carla2", "v2carla"],
                         ids=["no-word", "v3", "V1", "CARLA", "carla2", "v2carla"])
def test_a_bad_plan_word_is_refused_after_a_setup_that_ended_done_as_it_is_before_one(tmp_path, plan):
    """The six bad words of the refusal test above, once more in a session whose setup ended DONE: the setup-DONE refusal
    is then out of the way, so a PLAN refusal that only warned would start the suite (and spend its one run on a preflight
    that cannot judge the word). The last FATAL line is the PLAN refusal's, and no suite stem or marker line is made."""
    w, stub = _vss_w(tmp_path)
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    marker = (w / "vss-session").read_text()
    r = _vss_phase(w, stub, "harness", "HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin" + ("" if plan is None else " PLAN=" + plan))
    out = r.stdout + r.stderr
    fatal = [ln for ln in out.splitlines() if "FATAL:" in ln]
    assert r.returncode != 0 and fatal, out
    assert re.fullmatch(r"\[[0-9:]{8}\] FATAL: run-vss-suite\.sh needs PLAN=v1, PLAN=v2 or PLAN=carla", fatal[-1]), out
    assert not (w / "rec" / "vss-suite").exists() and sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt", "vss-setup"], out
    assert (w / "vss-session").read_text() == marker, "a new marker line: " + out


def _tree_state(root):
    """Every directory and file under ROOT by its path from ROOT, a file's bytes with it: what a refusal leaves as found."""
    seen = {}
    for d, subs, files in os.walk(str(root)):
        for n in subs:
            seen[os.path.relpath(os.path.join(d, n), str(root))] = None
        for n in files:
            with open(os.path.join(d, n), "rb") as f:
                seen[os.path.relpath(os.path.join(d, n), str(root))] = f.read()
    return seen


def _put_in_a_refusal_state(w, state):
    """W, after a stub setup that ended DONE, made into the state the suite's refusal named STATE reads. The states that are a
    word or a K, or a setup that ended FAILED, are the test's own and need nothing here."""
    rec = w / "rec"
    if state == "setup-not-done":
        os.remove(str(rec / "vss-setup" / "done"))
    elif state == "suite-already-run":
        (rec / "vss-suite").mkdir()
    elif state == "drill-still-running":
        (rec / "ota-drill").mkdir()
    elif state == "an-a6-record":
        _write(rec / "bell" / "x.txt", "an A6 record (a stand-in)")
    elif state == "no-quiesce-record":
        os.remove(str(rec / "quiesce.txt"))
    elif state == "inputs-changed-after-setup":
        (rec / "tooling").mkdir()
        shutil.copy(str(w / "inputs.env"), str(rec / "tooling" / "inputs.env"))   # the copy setup verified
        with open(str(w / "inputs.env"), "a", encoding="utf-8", newline="\n") as f:
            f.write("METAL_EXTRA=1\n")                                            # an upload after setup
    elif state == "no-step3-in-the-tarball":
        os.remove(str(w / "repo" / "sdv" / "stack" / "step3.py"))


_SUITE_PLAN = "HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=%s"


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("state,words,k,msg", [
    ("setup-not-done", _SUITE_PLAN, None, "run-vss-suite.sh needs a finished run-vss-setup.sh"),
    ("setup-failed", _SUITE_PLAN, None, "run-vss-suite.sh needs a finished run-vss-setup.sh"),
    ("another-vss-host", _SUITE_PLAN + " VSS_HOST=c7g-metal", None,
     "run-vss-suite.sh needs the VSS_HOST run-vss-setup.sh ran with (a1-metal), not VSS_HOST=c7g-metal"),
    ("a-host-that-is-not-bare-metal", _SUITE_PLAN + " VSS_HOST=orin", None, "VSS_HOST=orin is not a bare-metal AWS host"),
    ("another-uploaded-image", _SUITE_PLAN.replace("IMAGE=ifs-vss.bin", "IMAGE=ifs-bell.bin"), None,
     "run-vss-suite.sh boots the session's METAL_IFS, ifs-vss.bin, not ifs-bell.bin"),
    ("suite-already-run", _SUITE_PLAN, None, "exists: one vss-suite run per session"),
    ("drill-still-running", _SUITE_PLAN, None, "run-vss-suite.sh is refused while ota-drill still runs"),
    ("an-a6-record", _SUITE_PLAN, None, "holds an A6 record (bell)"),
    ("no-quiesce-record", _SUITE_PLAN, None, "run quiesce first"),
    ("inputs-changed-after-setup", _SUITE_PLAN, None, "inputs.env differs from"),
    ("no-step3-in-the-tarball", _SUITE_PLAN, None, "the repo tarball lacks sdv/stack/step3.py"),
    ("k-given", _SUITE_PLAN, "4", "run-vss-suite.sh takes no K"),
    ("img-b-given", _SUITE_PLAN + " IMG_B=ifs-bell.bin", None, "run-vss-suite.sh takes no IMG_B word (its image is IMAGE=)"),
    ("nothing-to-refuse", _SUITE_PLAN, None, None),
], ids=["setup-not-done", "setup-failed", "another-vss-host", "a-host-that-is-not-bare-metal", "another-uploaded-image",
        "suite-already-run", "drill-still-running", "an-a6-record", "no-quiesce-record", "inputs-changed-after-setup",
        "no-step3-in-the-tarball", "k-given", "img-b-given", "nothing-to-refuse"])
def test_a_carla_suite_meets_every_refusal_a_v2_suite_meets_before_anything_is_made(tmp_path, state, words, k, msg):
    """The phase passes PLAN=carla through and judges nothing by it, so each refusal that keeps a suite from spending the
    session's one run is the same for carla as for v2: after a stub setup that ended DONE (FAILED, in the one state that
    says so), the suite word with PLAN=v2 and with PLAN=carla gives the same status and the same FATAL line and leaves W
    as it found it. With nothing to refuse both start, and the suite's line joins the session marker as setup's did. A
    refusal that carla skipped would start a suite the session cannot run."""
    ends = ({"STUB_STATUS_LINE": "status=FAILED at=preflight", "STUB_RC": 1} if state == "setup-failed"
            else {"STUB_STATUS_LINE": "status=DONE"})

    def session(name):
        root = tmp_path / name
        root.mkdir()
        w, stub = _vss_w(root)
        r = _vss_phase(w, stub, "harness", _SETUP, **ends)
        assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
        _put_in_a_refusal_state(w, state)
        return w, stub

    shared = session("s") if msg is not None else None   # a refusal changes nothing: both plans can meet it in one session
    got = {}
    for plan in ("v2", "carla"):
        w, stub = shared if shared is not None else session(plan)
        before = _tree_state(w)
        r = _vss_phase(w, stub, "harness", words % plan, STUB_STATUS_LINE="status=DONE", **({} if k is None else {"K": k}))
        out = (r.stdout + r.stderr).replace(str(w), "<W>")
        if msg is None:
            assert r.returncode == 0 and "started" in out and _wait_for(w / "rec" / "vss-suite" / "done"), (plan, out)
            marks = [ln.split()[0] for ln in (w / "vss-session").read_text().splitlines()]
            assert marks == ["run-vss-setup.sh", "run-vss-suite.sh"], (plan, marks)
            got[plan] = (r.returncode, sorted(os.listdir(str(w / "rec"))), marks)
        else:
            fatal = [re.sub(r"^\[[0-9:]{8}\] ", "", ln) for ln in out.splitlines() if "FATAL:" in ln]
            assert r.returncode != 0 and len(fatal) == 1 and msg in fatal[0], (plan, out)
            assert _tree_state(w) == before, (plan, "the refusal changed W")
            got[plan] = (r.returncode, fatal)
    assert got["carla"] == got["v2"], got


@needs_bash
@pytest.mark.parametrize("words", [_SETUP, _SUITE])
@pytest.mark.parametrize("missing,msg", [
    ("step3", "the repo tarball lacks sdv/stack/step3.py"),
    ("lib", "the repo tarball lacks lib-vss-deadline.sh"),
    ("quiesce", "run quiesce first"),
])
def test_a_vss_harness_needs_the_vss_tarball_and_the_quiesce_record(tmp_path, words, missing, msg):
    w, stub = _vss_w(tmp_path, **{missing: False})
    r = _vss_phase(w, stub, "harness", words)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and msg in out, out
    assert not (w / "vss-session").exists() and not (stub / "setsid.log").exists()
    assert not (w / "rec" / "vss-setup").exists() and not (w / "rec" / "vss-suite").exists()


@needs_bash
@pytest.mark.parametrize("words,stem", [(_SETUP, "vss-setup"), (_SUITE, "vss-suite")])
def test_a_vss_harness_still_runs_once_per_session(tmp_path, words, stem):
    w, stub = _vss_w(tmp_path)
    (w / "rec" / stem).mkdir()
    r = _vss_phase(w, stub, "harness", words)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "exists: one %s run per session" % stem in out, out
    assert not (w / "vss-session").exists() and not (stub / "setsid.log").exists()


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("rc", [0, 3])
def test_an_a6_harness_still_runs_in_the_foreground_and_gets_host_after_only_on_exit_0(tmp_path, rc):
    """The A6 path is unchanged by the vss one: the phase returns only once the harness has ended, host-after.txt
    follows exit 0 alone, and nothing of the detached path (marker, detach.log, status, done) is made."""
    w, stub = _vss_w(tmp_path)
    _write(w / "repo" / "orin-native" / "gpu-concurrency" / "run-bell.sh",
           'sleep 1\necho "bell ran" > "$(dirname "$OUT")/ran.txt"\nexit %d' % rc)
    r = _vss_phase(w, stub, "harness", "HARNESS=run-bell.sh IMAGE=ifs-bell.bin")
    d = w / "rec" / "bell"
    out = r.stdout + r.stderr
    assert (d / "ran.txt").exists(), "the phase returned before the harness ended: " + out
    assert (r.returncode == 0) is (rc == 0) and (d / "host-after.txt").exists() is (rc == 0), out
    if rc:
        assert "run-bell.sh failed" in out, out
    assert not (w / "vss-session").exists() and not (stub / "setsid.log").exists()
    assert sorted(os.listdir(str(d))) == sorted(["host-before.txt", "run.log", "ran.txt"]
                                                + (["host-after.txt"] if rc == 0 else []))


@needs_bash
@needs_proc_interrupts
def test_a_vss_harness_runs_detached_and_the_phase_reaches_eof_before_the_harness_ends(tmp_path):
    """WP3e: the phase's stdout, read through a pipe as ssh's is, reaches EOF while the harness still runs. Without
    the redirection to detach.log the detached runner would hold that pipe, and the phase would end only when the
    harness did (here: when the stub's bound runs out, long after it should have returned)."""
    w, stub = _vss_w(tmp_path)
    release = tmp_path / "release"
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_RELEASE=release, STUB_STATUS_LINE="status=DONE")
    d = w / "rec" / "vss-setup"
    done_at_return = (d / "done").exists()
    release.touch()
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "started" in out, out
    assert not done_at_return, "the phase ended only with the harness: it was not detached"
    assert _wait_for(d / "done"), out
    assert "run-vss-setup.sh" in (w / "vss-session").read_text()
    log = (stub / "setsid.log").read_text()
    assert re.search(r"^setsid nohup bash \S*remote-ladder\.sh _detached vss-setup run-vss-setup\.sh$", log, re.M), log
    env = _env_of(d)
    assert env["PLAN"] == "" and env["K"] == "", env
    assert (env["VSS_IN"], env["VSS_HOME"], env["STATUS"]) == (str(w / "in"), str(w / "sdv"), str(d / "status")), env
    assert env["IFS_BIN"] == str(w / "img" / "ifs-vss.bin") and env["OUT"] == str(d / "raw"), env
    assert os.path.realpath(env["PWD"]) == os.path.realpath(str(w / "repo" / "orin-native" / "gpu-concurrency"))
    run_log = (d / "run.log").read_text()
    assert "stub run-vss-setup.sh running" in run_log and "stub run-vss-setup.sh ends" in run_log, run_log
    assert (d / "host-before.txt").exists() and (d / "host-after.txt").exists() and (d / "detach.log").exists()
    assert (d / "status").read_text().splitlines() == ["status=DONE"]


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("line,rc,after,last", [
    ("status=DONE", 0, True, "status=DONE"),
    ("status=TIMEOUT at=step-3 reason=deadline", 0, True, "status=TIMEOUT at=step-3 reason=deadline"),
    ("status=TIMEOUT", 0, True, "status=TIMEOUT"),
    ("", 0, False, "status=FAILED rc=0"),                       # exit 0 with no status line
    ("status=TIMEOUTISH", 0, False, "status=FAILED rc=0"),
    ("status=DONE", 3, False, "status=FAILED rc=3"),
    ("", 1, False, "status=FAILED rc=1"),
    ("status=FAILED at=preflight", 1, False, "status=FAILED rc=1"),
])
def test_the_detached_runner_writes_host_after_only_for_done_and_timeout_and_always_touches_done(
        tmp_path, line, rc, after, last):
    w, stub = _vss_w(tmp_path)
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_STATUS_LINE=line, STUB_RC=rc)
    d = w / "rec" / "vss-setup"
    assert r.returncode == 0, r.stdout + r.stderr
    assert _wait_for(d / "done"), "done is touched whatever the harness did"
    assert (d / "host-after.txt").exists() is after
    assert (d / "status").read_text().splitlines()[-1] == last


@needs_bash
@needs_proc_interrupts
def test_wait_run_blocks_until_the_detached_harness_is_done_then_prints_its_status(tmp_path):
    w, stub = _vss_w(tmp_path)
    release = tmp_path / "release"
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_RELEASE=release, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0, r.stdout + r.stderr
    p = _vss_phase(w, stub, "wait-run", "HARNESS=run-vss-setup.sh", popen=True)
    try:
        time.sleep(1.0)
        assert p.poll() is None, "wait-run returned while the harness still ran"
        release.touch()
        out, _ = p.communicate(timeout=30)
    finally:
        p.kill()
    assert p.returncode == 0, out
    assert "status=DONE" in out and "done: yes" in out and "stub run-vss-setup.sh ends" in out, out


def _laid(w, stem="vss-setup", lines=None, done=False, log="step 3 of 13: the guest boots"):
    d = w / "rec" / stem
    d.mkdir(parents=True)
    _write(d / "run.log", log)
    if lines is not None:
        _write(d / "status", "\n".join(lines), newline=bool(lines))
    if done:
        (d / "done").touch()
    return d


@needs_bash
@pytest.mark.parametrize("ahead_min", [12, 5, -1])
def test_wait_run_gives_up_at_stop_at_plus_12_min_with_exit_2(tmp_path, ahead_min):
    """A deadline 12 min ahead puts the give-up point (stop_at + 12 min, the deadline - 13 min) a minute in the
    past: wait-run returns at once. Giving up only 2 min before the deadline would leave it waiting here."""
    w, stub = _vss_w(tmp_path, ahead_min=ahead_min)
    _laid(w)
    r = _vss_phase(w, stub, "wait-run", "HARNESS=run-vss-setup.sh", timeout=20)
    out = r.stdout + r.stderr
    assert r.returncode == 2 and "gave up" in out, out
    assert "done: no" in out and "step 3 of 13" in out, out


@needs_bash
def test_wait_run_before_its_give_up_point_waits_for_done(tmp_path):
    w, stub = _vss_w(tmp_path, ahead_min=14)       # the give-up point is a minute ahead
    d = _laid(w)
    p = _vss_phase(w, stub, "wait-run", "HARNESS=run-vss-setup.sh", popen=True)
    try:
        time.sleep(1.5)
        assert p.poll() is None, "wait-run gave up before its give-up point"
        _write(d / "status", "status=DONE")
        (d / "done").touch()
        out, _ = p.communicate(timeout=30)
    finally:
        p.kill()
    assert p.returncode == 0 and "status=DONE" in out and "done: yes" in out, out


@needs_bash
@pytest.mark.parametrize("lines,rc", [
    (["status=DONE"], 0),
    (["status=TIMEOUT at=step-12 reason=30min-rule"], 0),
    (["status=TIMEOUT"], 0),
    (["status=FAILED rc=1"], 1),
    (["status=TIMEOUT at=step-4 reason=step-timeout", "status=FAILED rc=3"], 1),
    ([], 1),
    (None, 1),
])
def test_wait_run_exits_0_for_done_and_timeout_and_1_otherwise(tmp_path, lines, rc):
    w, stub = _vss_w(tmp_path)
    _laid(w, lines=lines, done=True)
    r = _vss_phase(w, stub, "wait-run", "HARNESS=run-vss-setup.sh", timeout=20)
    out = r.stdout + r.stderr
    assert r.returncode == rc and "done: yes" in out, out
    assert (lines or ["no status line"])[-1] in out, out


@needs_bash
@pytest.mark.parametrize("words,env,msg", [
    (None, {}, "wait-run needs LADDER_ENV=\"HARNESS="),
    ("HARNESS=run-bell.sh", {}, "is not a detached (vss) harness"),
    ("HARNESS=run-vss-setup.sh IMAGE=ifs-vss.bin", {}, "wait-run reads only HARNESS="),
    ("HARNESS=run-vss-setup.sh HARNESS=run-vss-suite.sh", {}, "LADDER_ENV names HARNESS twice"),
    ("HARNESS=run-vss-suite.sh", {}, "run-vss-suite.sh was not started in this session"),
    ("HARNESS=run-vss-setup.sh", {"K": "4"}, "wait-run takes no K"),
    ("HARNESS=run-vss-setup.sh", {"QNX_METAL_DEADLINE_FILE": "/nonexistent/qnx-metal-deadline"}, "deadline"),
])
def test_wait_run_refuses_what_it_cannot_wait_for(tmp_path, words, env, msg):
    w, stub = _vss_w(tmp_path)
    _laid(w)
    r = _vss_phase(w, stub, "wait-run", words, timeout=20, **env)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and msg in out, out
    assert "gave up" not in out


# f. The session marker

@needs_bash
@pytest.mark.parametrize("harness", _A6_HARNESSES)
def test_the_session_marker_refuses_every_a6_harness_by_name(tmp_path, harness):
    w, stub = _vss_w(tmp_path)
    _write(w / "vss-session", "run-vss-setup.sh 2026-10-03T00:00:00Z")
    _write(w / "repo" / "orin-native" / "gpu-concurrency" / harness, "exit 0")
    r = _vss_phase(w, stub, "harness", "HARNESS=%s IMAGE=ifs-bell.bin" % harness)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "vss-session exists" in out and harness in out, out
    assert sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt"]


@needs_bash
@pytest.mark.parametrize("phase", _A6_PHASES)
def test_the_session_marker_refuses_every_a6_phase_at_its_first_line(tmp_path, phase):
    # No inputs.env and no repo: any line of the phase but its first would fail on something else.
    _write(tmp_path / "vss-session", "run-vss-setup.sh 2026-10-03T00:00:00Z")
    r = _remote_env(tmp_path, phase)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "vss-session exists" in out and phase in out, out


@needs_bash
@needs_proc_interrupts
def test_after_a_stub_vss_setup_run_a6_refuses_and_the_suite_still_runs(tmp_path):
    """After a stub run-vss-setup.sh run through the harness phase, every A6 harness of the
    list and every A6 phase refuses, and run-vss-suite.sh still runs."""
    w, stub = _vss_w(tmp_path)
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    for h in _A6_HARNESSES:
        _write(w / "repo" / "orin-native" / "gpu-concurrency" / h, "exit 0")
        r = _vss_phase(w, stub, "harness", "HARNESS=%s IMAGE=ifs-bell.bin" % h)
        assert r.returncode != 0 and "vss-session exists" in r.stdout + r.stderr, (h, r.stdout + r.stderr)
    for phase in _A6_PHASES:
        r = _vss_phase(w, stub, phase)
        assert r.returncode != 0 and "vss-session exists" in r.stdout + r.stderr, (phase, r.stdout + r.stderr)
    assert sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt", "vss-setup"], "nothing A6 was made"
    r = _vss_phase(w, stub, "harness", _SUITE, STUB_STATUS_LINE="status=DONE")
    d = w / "rec" / "vss-suite"
    assert r.returncode == 0 and _wait_for(d / "done"), r.stdout + r.stderr
    assert _env_of(d)["PLAN"] == "v1" and (d / "host-after.txt").exists()
    assert _env_of(d)["VSS_HOST"] == "<unset>" and not (w / "vss-host").exists(), "no VSS_HOST word: the a1.metal path"


# 2026-10-17: VSS_HOST=c7g-metal, the vss harnesses' a1.metal path on c7g.metal. The word reaches the harness's
# environment; setup's word is kept in W/vss-host (outside rec: never captured), and the suite's must be the same.

@needs_bash
@needs_proc_interrupts
def test_a_vss_host_word_reaches_both_harnesses_and_is_kept_for_the_suite_outside_rec(tmp_path):
    w, stub = _vss_w(tmp_path)
    r = _vss_phase(w, stub, "harness", _SETUP + " VSS_HOST=c7g-metal", STUB_STATUS_LINE="status=DONE")
    d = w / "rec" / "vss-setup"
    assert r.returncode == 0 and _wait_for(d / "done"), r.stdout + r.stderr
    assert _env_of(d)["VSS_HOST"] == "c7g-metal" and (w / "vss-host").read_text() == "c7g-metal\n"
    r = _vss_phase(w, stub, "harness", _SUITE + " VSS_HOST=c7g-metal", STUB_STATUS_LINE="status=DONE")
    d = w / "rec" / "vss-suite"
    assert r.returncode == 0 and _wait_for(d / "done"), r.stdout + r.stderr
    assert _env_of(d)["VSS_HOST"] == "c7g-metal" and sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt", "vss-setup", "vss-suite"]


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("setup_word,suite_word", [("c7g-metal", None), ("c7g-metal", "a1-metal"), (None, "c7g-metal"),
                                                   ("a1-metal", "c7g-metal")])
def test_the_suite_is_refused_unless_its_vss_host_is_the_setups_before_anything_is_made(tmp_path, setup_word, suite_word):
    """A suite of another host mode than its setup would spend the session's one suite run on its preflight's refusal
    (vss_suite.py setup): the phase refuses it first. No word is a1-metal, either side."""
    w, stub = _vss_w(tmp_path)
    r = _vss_phase(w, stub, "harness", _SETUP + ("" if setup_word is None else " VSS_HOST=" + setup_word),
                   STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    r = _vss_phase(w, stub, "harness", _SUITE + ("" if suite_word is None else " VSS_HOST=" + suite_word))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "run-vss-suite.sh needs the VSS_HOST run-vss-setup.sh ran with" in out, out
    assert "(%s)" % (setup_word or "a1-metal") in out and "VSS_HOST=%s" % (suite_word or "a1-metal") in out, out
    assert sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt", "vss-setup"], "refused before the suite's stem was made"
    assert "run-vss-suite.sh" not in (w / "vss-session").read_text()


@needs_bash
@needs_proc_interrupts
def test_a_setup_started_again_after_a_runner_that_did_not_start_keeps_only_its_own_word(tmp_path):
    """The stem goes when the detached runner did not start, so setup may run again, perhaps with another word: W/vss-host
    then holds that run's word, or nothing when it has none."""
    w, stub = _vss_w(tmp_path)
    _write(w / "vss-host", "c7g-metal\n")          # a first start's word, its stem since removed
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    assert not (w / "vss-host").exists() and _env_of(w / "rec" / "vss-setup")["VSS_HOST"] == "<unset>"


# g. The deadline contract (lib-vss-deadline.sh)

def _lib(tmp_path, body, deadline="2500", now=None, **env):
    f = tmp_path / "deadline"
    if deadline is not None:
        _write(f, deadline)
    clock = "" if now is None else "vss_now() { echo %d; }; " % now
    stub = _stubs(tmp_path / "bin", {"timeout": _STUB_BIN["timeout"]})
    e = dict(os.environ, QNX_METAL_DEADLINE_FILE=str(f), PATH=_path_with(stub), STUB_DIR=str(stub))
    e.update({k: str(v) for k, v in env.items()})
    return subprocess.run([BASH, "-c", 'set -euo pipefail; . "$1"; ' + clock + body, "_", LIB],
                          capture_output=True, text=True, timeout=60, env=e)


@needs_bash
@pytest.mark.parametrize("now,past", [(999, False), (1000, True), (1001, True), (0, False), (2600, True)])
def test_a_check_point_stops_when_now_reaches_stop_at(tmp_path, now, past):
    # deadline 2500: stop_at 1000 (deadline - 25 min)
    r = _lib(tmp_path, 'vss_deadline_load; echo "$VSS_DEADLINE $VSS_STOP_AT"; '
                       'if vss_past_stop; then echo past; else echo before; fi', now=now)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["2500", "1000", "past" if past else "before"], r.stdout


@needs_bash
@pytest.mark.parametrize("now,cap", [(999, 601), (400, 1200), (0, 1600)])
def test_a_units_cap_is_stop_at_plus_10_min_minus_now_with_a_30_s_kill_after(tmp_path, now, cap):
    r = _lib(tmp_path, 'vss_deadline_load; vss_cap_s; vss_capped echo ran; vss_giveup_at', now=now)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == [str(cap), "ran", "1720"], r.stdout     # give-up: stop_at + 12 min
    assert (tmp_path / "bin" / "timeout.log").read_text().splitlines() == ["timeout --kill-after=30s %d echo ran" % cap]


@needs_bash
@pytest.mark.parametrize("rc,then,fired", [(124, 1600, True), (137, 1600, True), (124, 5000, True), (124, 1599, False),
                                           (137, 10, False), (0, 1600, False), (1, 1600, False), (125, 1600, False)])
def test_a_cap_that_fired_is_told_apart_by_timeouts_status_and_the_caps_end(tmp_path, rc, then, fired):
    # deadline 2500: stop_at 1000, so every cap ends at 1600. The unit starts at 10 and returns at THEN: a 124 or 137
    # before 1600 is the command's own (an OOM kill's 137), never a cap
    r = _lib(tmp_path, 'vss_deadline_load; rc=0; vss_capped bash -c "exit %d" || rc=$?; echo "rc=$rc"; '
                       'vss_now() { echo %d; }; if vss_cap_fired "$rc"; then echo fired; else echo ran; fi' % (rc, then),
             now=10)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["rc=%d" % rc, "fired" if fired else "ran"], r.stdout


@needs_bash
@pytest.mark.parametrize("now", [1600, 1601, 5000])
def test_a_unit_past_the_latest_end_of_a_cap_is_not_run_and_reads_as_a_cap_that_fired(tmp_path, now):
    r = _lib(tmp_path, 'vss_deadline_load; rc=0; vss_capped echo ran || rc=$?; echo "rc=$rc"', now=now)
    assert r.returncode == 0 and r.stdout.split() == ["rc=124"], (r.stdout, r.stderr)
    assert not (tmp_path / "bin" / "timeout.log").exists()


# Where a cap's KILL goes. coreutils timeout, not --foreground as
# vss_capped calls it, sends its TERM to the unit's process group. Its KILL, after the kill-after, goes out only while
# the direct child still lives, and then to the child and to the whole group, timeout itself included (hence 137). Once
# the child has died of the TERM, timeout returns 124 at once and no KILL goes out.
# The grandchild holds no pipe of the test's: subprocess.run would wait for it to close.
_UNIT_DEAF = 'trap "" TERM; sleep 30 >/dev/null 2>&1 & echo $! > "$GC"; wait'           # the direct child ignores TERM
_UNIT_DIES = '(trap "" TERM; exec sleep 30 >/dev/null 2>&1) & echo $! > "$GC"; wait'   # it dies of the TERM


def _gone_or_zombie(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] == "Z"
    except OSError:
        return True


@needs_bash
@pytest.mark.skipif(sys.platform == "win32", reason="Linux's process groups and coreutils timeout, as on the instance")
@pytest.mark.parametrize("unit,rc,left", [(_UNIT_DEAF, 137, False), (_UNIT_DIES, 124, True)],
                         ids=["child-ignores-term", "child-dies-of-term"])
def test_a_caps_kill_goes_out_only_while_the_direct_child_lives_and_then_to_the_whole_group(tmp_path, unit, rc, left):
    """The real coreutils timeout under vss_capped, the cap 1 s (deadline 2500, now 1599) and the kill-after 1 s: a
    grandchild that ignores TERM is gone after the KILL when the direct child ignored the TERM too (137), and outlives
    the cap when the direct child died of the TERM (124)."""
    _write(tmp_path / "deadline", "2500")
    gc = tmp_path / "gc"
    e = dict(os.environ, QNX_METAL_DEADLINE_FILE=str(tmp_path / "deadline"), GC=str(gc), UNIT=unit)
    r = subprocess.run([BASH, "-c", 'set -euo pipefail; . "$1"; vss_now() { echo 1599; }; vss_deadline_load; '
                        'VSS_KILL_AFTER_S=1; vss_cap_s; rc=0; vss_capped bash -c "$UNIT" || rc=$?; echo "rc=$rc"',
                        "_", LIB], capture_output=True, text=True, timeout=60, env=e)
    pid = int(gc.read_text().strip())
    try:
        assert r.returncode == 0 and r.stdout.split() == ["1", "rc=%d" % rc], (r.stdout, r.stderr)
        time.sleep(2)                     # a KILL has landed by now; a grandchild no KILL reached still runs
        gone = _gone_or_zombie(pid)
        assert gone is not left, "grandchild %d %s" % (pid, "gone" if gone else "still running")
    finally:
        if not _gone_or_zombie(pid):
            os.kill(pid, 9)               # SIGKILL: the grandchild the case leaves alive


def _one_paragraph(text):
    return re.sub(r"\s+", " ", re.sub(r"(?m)^\s*#", " ", text))


def test_the_readme_and_the_library_say_where_a_caps_kill_goes_and_name_no_qemu_as_ignoring_term():
    """The README's deadline contract states the cap's KILL as the library's header does (the test above shows it), and
    neither names a QEMU as a group member that ignored the TERM: QEMU shuts down on a TERM."""
    with open(os.path.join(AWSDIR, "README.md"), encoding="utf-8") as f:
        readme = _one_paragraph(f.read())
    with open(LIB, encoding="utf-8") as f:
        lib = _one_paragraph(f.read())
    for name, text in (("README.md", readme), ("lib-vss-deadline.sh", lib)):
        assert "goes out only while the unit's direct child still lives, and then to the whole group" in text, name
        assert "timeout returns 124 at once" in text, name
        ignored = [s for s in re.split(r"(?<=[.:]) ", text) if "ignored the TERM" in s]
        assert ignored and not [s for s in ignored if "QEMU" in s.split("outlives")[0]], (name, ignored)
    assert "goes only to the unit's direct child" not in readme


@needs_bash
@pytest.mark.parametrize("deadline", [None, "", "soon", "0123", "12 34", "-5"])
def test_the_deadline_library_refuses_a_deadline_file_it_cannot_read(tmp_path, deadline):
    r = _lib(tmp_path, 'if vss_deadline_load; then echo loaded; else echo refused; fi', deadline=deadline)
    assert r.returncode == 0 and r.stdout.split() == ["refused"], (r.stdout, r.stderr)
    assert "qnx-metal-deadline" in r.stderr or "deadline" in r.stderr, r.stderr


@needs_bash
def test_the_deadline_library_reads_the_instances_file_unless_told_otherwise(tmp_path):
    r = _lib(tmp_path, 'unset QNX_METAL_DEADLINE_FILE; vss_deadline_file')
    assert r.returncode == 0 and r.stdout.strip() == "/var/lib/qnx-metal-deadline", (r.stdout, r.stderr)
    r = _lib(tmp_path, 'vss_deadline_file')
    assert r.stdout.strip() == str(tmp_path / "deadline"), r.stdout


@needs_bash
def test_a_status_line_goes_to_the_status_file_and_to_run_log_one_line_each(tmp_path):
    st = tmp_path / "status"
    r = _lib(tmp_path, 'vss_status TIMEOUT at=step-4 reason=step-timeout; vss_status "$(printf "DONE\\nx")"',
             STATUS=st)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["status=TIMEOUT at=step-4 reason=step-timeout", "status=DONE x"], r.stdout
    assert st.read_text().splitlines() == r.stdout.splitlines()
    r = _lib(tmp_path, 'unset STATUS; vss_status DONE')
    assert r.returncode != 0 and "STATUS" in r.stderr, r.stderr


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("ahead_min", [24, 26])
def test_a_vss_harness_past_stop_at_stops_at_its_first_check_point_and_else_caps_its_unit(tmp_path, ahead_min):
    """24 min before the deadline is past stop_at (deadline - 25 min): the stub harness
    stops at its first check point, exits 0, and writes status=TIMEOUT to status, run.log and its result file;
    host-after is written, and capture's gate takes the record. 26 min before, it passes the check point and
    its unit runs under a cap of stop_at + 10 min - now, about 11 min."""
    w, stub = _vss_w(tmp_path, harness_body=_STUB_DEADLINE, ahead_min=ahead_min)
    r = _vss_phase(w, stub, "harness", _SETUP)
    d = w / "rec" / "vss-setup"
    assert r.returncode == 0 and _wait_for(d / "done"), r.stdout + r.stderr
    status = (d / "status").read_text().splitlines()
    result = json.loads((d / "raw" / "setup.json").read_text())
    assert (d / "host-after.txt").exists(), status
    if ahead_min == 24:
        assert status == ["status=TIMEOUT at=step-1 reason=deadline"], status
        assert "status=TIMEOUT at=step-1 reason=deadline" in (d / "run.log").read_text()
        assert result["status"] == "TIMEOUT" and not (stub / "timeout.log").exists()
        r = _vss_phase(w, stub, "capture")
        assert "did not finish" not in r.stdout + r.stderr, r.stdout + r.stderr
    else:
        assert status == ["status=DONE"] and result["status"] == "DONE", status
        cap = (stub / "timeout.log").read_text().split()
        assert cap[:2] == ["timeout", "--kill-after=30s"] and cap[3:] == ["true"], cap
        assert 600 < int(cap[2]) <= 660, cap


# h. Quiesce

@needs_bash
@pytest.mark.parametrize("pq_rc,ok", [(0, True), (3, True), (1, False), (2, False)])
def test_quiesce_records_platform_quiesce_and_fails_where_the_host_may_have_changed(tmp_path, pq_rc, ok):
    w, stub = _vss_w(tmp_path, quiesce=False)
    (w / "rec").mkdir()
    reason = "platform-quiesce.sh: refusing: the marker names another record" if pq_rc == 3 else ""
    r = _vss_phase(w, stub, "quiesce", STUB_PQ_RC=pq_rc, STUB_PQ_ERR=reason)
    out = r.stdout + r.stderr
    assert (r.returncode == 0) is ok, out
    q = (w / "rec" / "quiesce.txt").read_text()
    assert "docker absent absent" in q and "platform-quiesce.sh stop exit %d" % pq_rc in q, q
    assert reason in q, q
    assert (stub / "pq.log").read_text().splitlines() == ["pq stop %s/platform-quiesce.state" % w], "a fixed state path"
    if ok:
        assert "k3s-killall.sh: not executable here" in q, q


@needs_bash
@pytest.mark.parametrize("k3s_rc,ok", [(0, True), (1, False)])
def test_quiesce_runs_k3s_killall_as_root_when_it_is_executable_and_records_it(tmp_path, k3s_rc, ok):
    w, stub = _vss_w(tmp_path, quiesce=False)
    (w / "rec").mkdir()
    k3s = _stubs(tmp_path / "k3s", {"k3s-killall.sh": 'echo "k3s stopped"; exit %d' % k3s_rc}) / "k3s-killall.sh"
    r = _vss_phase(w, stub, "quiesce", K3S_KILLALL=k3s)
    out = r.stdout + r.stderr
    assert (r.returncode == 0) is ok, out
    q = (w / "rec" / "quiesce.txt").read_text()
    assert "k3s stopped" in q and "k3s-killall.sh exit %d" % k3s_rc in q, q
    assert "sudo -n %s" % k3s in (stub / "sudo.log").read_text()


@needs_bash
@pytest.mark.parametrize("missing,msg", [("rec", "run setup first"), ("pq", "the repo tarball lacks platform-quiesce.sh")])
def test_quiesce_needs_setup_first(tmp_path, missing, msg):
    w, stub = _vss_w(tmp_path, quiesce=False)
    if missing == "pq":
        (w / "rec").mkdir()
        (w / "repo" / "orin-native" / "gpu-concurrency" / "platform-quiesce.sh").unlink()
    r = _vss_phase(w, stub, "quiesce")
    out = r.stdout + r.stderr
    assert r.returncode != 0 and msg in out, out
    assert not (stub / "pq.log").exists() and not (stub / "sudo.log").exists(), "refused before it did anything"


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("words", [_SETUP, "HARNESS=run-bell.sh IMAGE=ifs-bell.bin"])
def test_the_quiesce_record_heads_every_later_host_before(tmp_path, words):
    w, stub = _vss_w(tmp_path, quiesce=False)
    (w / "rec").mkdir()
    _write(w / "repo" / "orin-native" / "gpu-concurrency" / "run-bell.sh", "exit 0")
    r = _vss_phase(w, stub, "quiesce")
    assert r.returncode == 0, r.stdout + r.stderr
    q = (w / "rec" / "quiesce.txt").read_text()
    r = _vss_phase(w, stub, "harness", words, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0, r.stdout + r.stderr
    stem = "vss-setup" if "vss" in words else "bell"
    hb = (w / "rec" / stem / "host-before.txt").read_text()
    assert hb.startswith(q) and len(hb) > len(q), hb
    if stem == "vss-setup":
        assert _wait_for(w / "rec" / stem / "done")


# i. Capture and leakscan for a vss record. The fake record below is capture data
# too: documentation values only (RFC 5737 and RFC 3849 addresses, fe80::/10, the example instance id), and a
# 12-digit monotonic count that is synthetic.

_T12 = 912345678901        # a 12-digit CLOCK_MONOTONIC count in ns, as replay mode writes during uptime 100-999 s
_RUNDIR = "vss-suite/raw/runs/20261003-01-honest-replay"
_REPLAY = _RUNDIR + "/honest-replay-1"
_CMPDIR = "vss-suite/raw/runs/20261003-20-compare-broker-replay"
_CONSOLE = "/home/ubuntu/a1/rec/vss-suite/raw/guest/01-honest-replay-console.log"
# vss-claim-bridge.log as `docker logs -t` leaves it: dockerd's stamp, then the bridge's summary (stdout), then
# a stderr line
_BRIDGE_JSON = json.dumps({"anchor_ns": _T12, "by_reason": {"0": 453, "22": 7}, "fatal": None, "run_dir": "/out",
                           "source": {"host": "203.0.113.7", "mode": "replay"}}, sort_keys=True)
_BRIDGE_LOG = ("2026-10-03T05:31:30.821425168Z " + _BRIDGE_JSON + "\n"
               "2026-10-03T05:31:30.900000001Z vss_claim_bridge: a note from i-0123456789abcdef0\n")
_REPLIES = "".join('{"age_ms":27,"event":"reply","frame":"0100000000000000ce74ef96","reason":0,"seq":%d,"t_mono":%d}\n'
                   % (i, _T12 + i) for i in range(1, 4))
_BRIDGE_JSONL = ('{"event":"source","host":"203.0.113.7","peer":"[2001:db8::7]:7160","t_mono":%d}\n'
                 '{"event":"start","t_mono":%d,"wall_s":1790919035.9288163}\n' % (_T12, _T12 + 5))
_WITNESS = "".join('{"event":"update","path":"Vehicle.Speed","t_ns":%d,"target":"127.0.0.1:55555","value":%d.5}\n'
                   % (_T12 + i, i) for i in range(3))
_LISTENERS = {
    "monitor": {"form": "guest", "host": "192.168.100.10", "port": 7160},
    "listeners_before": {"with_owners": True, "sockets": [
        {"proto": "tcp", "local": "0.0.0.0:22", "process": 'users:(("sshd",pid=812,fd=3))'},
        {"proto": "tcp", "local": "[::]:22", "process": 'users:(("sshd",pid=812,fd=4))'},
        {"proto": "udp", "local": "127.0.0.1:323", "process": 'users:(("chronyd",pid=640,fd=5))'},
        {"proto": "udp", "local": "[::1]:323", "process": 'users:(("chronyd",pid=640,fd=6))'},
        {"proto": "udp", "local": "203.0.113.7%ens5:68", "process": 'users:(("systemd-network",pid=520,fd=15))'},
        {"proto": "udp", "local": "[fe80::1%ens5]:546", "process": 'users:(("systemd-network",pid=520,fd=16))'},
        {"proto": "tcp", "local": "192.168.100.1:7100", "process": ""}]},
    "added_not_loopback": []}
_LISTENED = ["0.0.0.0:22", "[::]:22", "127.0.0.1:323", "[::1]:323", "<ip>%ens5:68", "[<ipv6>%ens5]:546",
             "192.168.100.1:7100"]
_RESULT = {"ok": True, "c12b_lines": 5, "c12b_expected": 5, "t_mono_first": _T12,
           "console_file": {"raw": {"path": _CONSOLE, "bytes": 4096, "sha256": "ab" * 32}},
           "guest_link_local": "fe80::5054:ff:fe11:1111",
           "console": {"problems": ["line one from 203.0.113.7\nline two on i-0123456789abcdef0\nline three"]}}
_SETUP_JSON = {"status": "DONE", "skip": [], "steps": [{"n": 1, "name": "preflight", "utc_start": "2026-10-03T05:00:01Z"}],
               "apt_tail": "Get:1 http://203.0.113.7/ubuntu jammy-updates InRelease\nReading package lists"}


def _vss_stem(rec, stem, status=("status=DONE",), done=True, result=True, after=True):
    """One vss harness's record as the harness phase and the detached runner leave it."""
    d = rec / stem
    _write(d / "host-before.txt", _QUIESCE_REC + "2026-10-03T05:00:00Z\n0.10 0.20 0.30 1/200 4022", newline=False)
    _write(d / "run.log", "step 1 of 13: preflight\nfetched from 203.0.113.7")
    _write(d / "detach.log", "[05:00:00] _detached: the harness starts")
    if status is not None:
        _write(d / "status", "\n".join(status), newline=bool(status))
    if after:
        _write(d / "host-after.txt", "2026-10-03T05:30:00Z")
    if result:
        _write(d / "raw" / (stem[len("vss-"):] + ".json"),
               json.dumps({"status": status[-1][len("status="):] if status else ""}), newline=False)
    if done:
        (d / "done").touch()
    return d


def _vss_record(tmp_path):
    """A vss record with every kind of file both harnesses and step3 leave, and the ones capture must never take."""
    rec = tmp_path / "rec"
    _write(rec / "host-facts.txt", "== uname -r\n6.8.0-1063-aws\n== nproc\n16")
    _write(rec / "quiesce.txt", _QUIESCE_REC, newline=False)
    _write(rec / "tooling" / "inputs.env", "IFS_NAME=ifs-vss.bin\nREPO_COMMIT=" + "e" * 40)
    _write(rec / "tooling" / "bundle.json", json.dumps({"format": 1, "commit": "e" * 40}), newline=False)
    (rec / "ladder").mkdir()                                                    # setup makes it; empty
    _write(rec / "notes.txt", "a stray file at the top")                        # unlisted
    raw = _vss_stem(rec, "vss-setup") / "raw"
    _write(raw / "setup.json", json.dumps(_SETUP_JSON), newline=False)
    for name, text in (("net-before.txt", "net.ipv4.ip_forward = 0\n-P FORWARD ACCEPT"),
                       ("net-after.txt", "net.ipv4.ip_forward = 1\n-P FORWARD DROP"),
                       ("docker-facts.txt", "docker.io 29.1.3-0ubuntu3~22.04.2\ndriver-type io.containerd.snapshotter.v1"),
                       ("venv.txt", "Python 3.12.14\ncantools==40.7.1"), ("smoke-1.txt", "rc=0 bad=0 rej=0"),
                       ("df.txt", "/dev/root on /"), ("apt.log", "Get:1 http://203.0.113.7/ubuntu jammy-updates InRelease"),
                       ("guest/00-setup-console.log", "monitor: vss rules: profile=1")):
        _write(raw / name, text)
    _write(raw / "probes.json", json.dumps({"databroker": {"rc": 0, "listening": True}}), newline=False)
    _write(raw / "docker-info.txt", "ID: 11112222-3333-4444-5555-666677778888")             # a raw docker info
    _write(raw / "inspect-bridge.json", json.dumps([{"Id": "sha256:" + "c" * 64}]), newline=False)   # a raw inspect
    raw = _vss_stem(rec, "vss-suite") / "raw"
    _write(raw / "suite.json", json.dumps({"plan": "v1", "status": "DONE", "runs": [
        {"nn": 1, "spec": "honest", "mode": "replay", "ok": True, "operational_s": {"boot": 1, "step3": 2}}]}), newline=False)
    _write(raw / "guest" / "01-honest-replay-console.log", "monitor: vss rules: profile=1\nclient done: seen=0")
    rd = rec / _RUNDIR
    _write(rd / "manifest.json", json.dumps({"host_role": "a1-metal", "components": {
        "vss-monitor-guest": {"host": "192.168.100.10", "image": "ifs-vss.bin"}}}, indent=1, sort_keys=True))
    _write(rd / "ownership.json", json.dumps({"rows": []}), newline=False)
    _write(rd / "step3.json", json.dumps({"mode": "replay", "runs": [{"run": "honest-replay-1", "ok": True}]}), newline=False)
    _write(rd / "in" / "sigsim.log", "(1790000000.000000) vcan0 123#0011223344556677")      # the staged inputs
    _write(rd / "in" / "vss-databroker.json", json.dumps({"Vehicle": {}}), newline=False)
    _write(rd / "in" / "slice.dbc", 'VERSION ""')
    (rd / "bin").mkdir()
    (rd / "bin" / "monitor-vss").write_bytes(b"\x7fELF")
    rp = rec / _REPLAY
    for name, doc in (("plan.json", {"spec": "honest", "windows": []}), ("bridge-script.json", {"calls": []}),
                      ("bridge-header.json", {"mode": "replay", "host": "192.168.100.10"}),
                      ("attribution.json", {"rows": [], "c12b": {"lines": 5}}),
                      ("bridge/summary.json", {"identity": {"holds": True, "packed": 3, "replied": 3}}),
                      ("bridge/source.json", {"mode": "replay", "clock": "CLOCK_MONOTONIC"})):
        _write(rp / name, json.dumps(doc, indent=1, sort_keys=True))
    _write(rp / "listeners.json", json.dumps(_LISTENERS, indent=1, sort_keys=True))
    _write(rp / "result.json", json.dumps(_RESULT, indent=1, sort_keys=True))
    _write(rp / "bridge" / "replies.jsonl", _REPLIES, newline=False)
    _write(rp / "bridge" / "bridge.jsonl", _BRIDGE_JSONL, newline=False)
    _write(rp / "vss-witness.jsonl", _WITNESS, newline=False)
    _write(rp / "hard-brake-hazard.jsonl", '{"event":"start","t":1192.86102914}\n', newline=False)
    _write(rp / "vss-claim-bridge.log", _BRIDGE_LOG, newline=False)
    _write(rp / "kuksa-databroker.log", "2026-10-03T05:31:00.000000000Z Listening on 127.0.0.1:55555")
    _write(rp / "guest-console.log", "monitor: vss rules: profile=1\nclient done: seen=12")
    _write(rp / "player.log", "")
    _write(rp / "vss-recorder.csv", "field,signal,value,delay\ncurrent,Vehicle.Speed,%d,0.0\n"
                                    "current,Vehicle.Chassis.Wheelbase,2700,0.0" % _T12)
    (rp / "scenario.lock").write_bytes(b"")
    _write(rp / "attribution.md", "| writer | path |")                                       # unlisted
    (rp / "libshim.so").write_bytes(b"\x7fELF")
    (rp / ".run-start").write_bytes(b"")
    _write(rec / _CMPDIR / "compare.json", json.dumps({"ok": True, "modes": ["broker", "replay"],
                                                       "inputs": ["/home/ubuntu/a1/rec/" + _RUNDIR]}), newline=False)
    return rec


_VSS_PUBLISHED = sorted(
    ["host-facts.txt", "quiesce.txt", "tooling/inputs.env", "tooling/bundle.json", "capture.log"]
    + ["%s/%s" % (s, n) for s in ("vss-setup", "vss-suite")
       for n in ("host-before.txt", "host-after.txt", "run.log", "status", "detach.log")]
    + ["vss-setup/raw/" + n for n in ("setup.json", "net-before.txt", "net-after.txt", "docker-facts.txt", "probes.json",
                                      "venv.txt", "smoke-1.txt", "df.txt", "apt.log", "guest/00-setup-console.log")]
    + ["vss-suite/raw/suite.json", "vss-suite/raw/guest/01-honest-replay-console.log", _CMPDIR + "/compare.json"]
    + [_RUNDIR + "/" + n for n in ("manifest.json", "ownership.json", "step3.json")]
    + [_REPLAY + "/" + n for n in ("plan.json", "bridge-script.json", "bridge-header.json", "attribution.json",
                                   "bridge/summary.json", "bridge/source.json", "bridge/replies.jsonl", "bridge/bridge.jsonl",
                                   "listeners.json", "result.json", "vss-witness.jsonl", "hard-brake-hazard.jsonl",
                                   "vss-claim-bridge.log", "kuksa-databroker.log", "guest-console.log", "player.log",
                                   "vss-recorder.csv")])
_VSS_NEVER = (["notes.txt", "vss-setup/done", "vss-suite/done", "vss-setup/raw/docker-info.txt",
               "vss-setup/raw/inspect-bridge.json", _RUNDIR + "/bin/monitor-vss"]
              + [_RUNDIR + "/in/" + n for n in ("sigsim.log", "vss-databroker.json", "slice.dbc")]
              + [_REPLAY + "/" + n for n in ("scenario.lock", "attribution.md", "libshim.so", ".run-start")])
_AWKS = ["awk"] + (["mawk"] if shutil.which("mawk") else [])   # Ubuntu's awk on the instance is mawk


def _vss_capture(rec, pub, **env):
    e = dict(os.environ, USER="", PATH=_path_with())
    e.pop("CAPTURE_INCOMPLETE", None)
    e.update({k: str(v) for k, v in env.items()})
    return subprocess.run([PY, CAPTURE, str(rec), str(pub), REDACT], capture_output=True, text=True, env=e, timeout=300)


def _published(pub):
    return sorted(os.path.relpath(os.path.join(d, f), str(pub)).replace(os.sep, "/")
                  for d, _s, fs in os.walk(str(pub)) for f in fs)


def _leakscan(d, *literals):
    return subprocess.run([PY, LEAKSCAN, str(d)] + list(literals), capture_output=True, text=True, timeout=120)


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
def test_capture_takes_a_vss_record_by_its_whitelist_and_names_what_it_leaves_out(tmp_path, awk):
    """The whitelist: in/, bin/, scenario.lock, a raw docker info or inspect and anything unlisted
    stay on the instance, each named in capture.log; the record's own report goes into the publication."""
    rec, pub = _vss_record(tmp_path), tmp_path / "pub"
    r = _vss_capture(rec, pub, AWK=awk)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert _published(pub) == _VSS_PUBLISHED, out
    report = (pub / "capture.log").read_text(encoding="utf-8")
    for rel in _VSS_NEVER:
        assert "excluded: %s " % rel in r.stdout and "excluded: %s " % rel in report, (rel, r.stdout)
    assert "vss-setup: DONE" in report and "vss-suite: DONE" in report, report
    manifest = (tmp_path / "pub.sha256").read_text(encoding="utf-8").splitlines()
    assert sorted(line.split("  ", 1)[1] for line in manifest) == _VSS_PUBLISHED


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
def test_capture_keeps_every_number_of_a_vss_record_and_redacts_its_strings(tmp_path, awk):
    """.jsonl by the JSON rule line by line, vss-claim-bridge.log's JSON too, so a 12-digit monotonic count
    survives byte for byte; IPv6 masked in JSON strings except ::, ::1 and the guest's; a string holding a newline
    redacted line by line; the 12-digit substitutions in other text files counted per file."""
    rec, pub = _vss_record(tmp_path), tmp_path / "pub"
    r = _vss_capture(rec, pub, AWK=awk)
    assert r.returncode == 0, r.stdout + r.stderr

    def got(rel):
        return (pub / rel).read_bytes()

    # no string changed: byte for byte, 12-digit numbers and all
    for rel in (_REPLAY + "/bridge/replies.jsonl", _REPLAY + "/vss-witness.jsonl", _RUNDIR + "/manifest.json",
                _REPLAY + "/plan.json", _CMPDIR + "/compare.json", "vss-setup/raw/probes.json"):
        assert got(rel) == (rec / rel).read_bytes(), rel
    # a JSONL line whose strings change keeps every other byte, its 12-digit number included
    assert got(_REPLAY + "/bridge/bridge.jsonl").decode() == \
        _BRIDGE_JSONL.replace('"203.0.113.7"', '"<ip>"').replace('"[2001:db8::7]:7160"', '"[<ipv6>]:7160"')
    # vss-claim-bridge.log: the JSON after dockerd's stamp by the JSON rule, a line that is not JSON as text
    assert got(_REPLAY + "/vss-claim-bridge.log").decode().splitlines() == [
        "2026-10-03T05:31:30.821425168Z " + _BRIDGE_JSON.replace('"203.0.113.7"', '"<ip>"'),
        "2026-10-03T05:31:30.900000001Z vss_claim_bridge: a note from <instance-id>"]
    assert ('"anchor_ns": %d' % _T12).encode() in got(_REPLAY + "/vss-claim-bridge.log")
    # listeners.json: sshd's [::]:22 and chrony's [::1]:323 kept, the link-local and the instance's address masked,
    # the bridge subnet kept
    ls = json.loads(got(_REPLAY + "/listeners.json"))
    assert [s["local"] for s in ls["listeners_before"]["sockets"]] == _LISTENED
    assert ls["monitor"]["host"] == "192.168.100.10"
    # result.json: the console's absolute path holds no identity and is kept; a multi-line string line by line
    res = json.loads(got(_REPLAY + "/result.json"))
    assert res["console_file"]["raw"]["path"] == _CONSOLE and res["guest_link_local"] == "fe80::5054:ff:fe11:1111"
    assert res["console"]["problems"] == ["line one from <ip>\nline two on <instance-id>\nline three"]
    assert ('"t_mono_first": %d' % _T12).encode() in got(_REPLAY + "/result.json")
    assert json.loads(got("vss-setup/raw/setup.json"))["apt_tail"] == \
        "Get:1 http://<ip>/ubuntu jammy-updates InRelease\nReading package lists"
    # text files through the redactor; the CSV's 12-digit field is rewritten, and counted per file
    assert b"current,Vehicle.Speed,<account>,0.0" in got(_REPLAY + "/vss-recorder.csv")
    assert "12-digit substitutions in %s/vss-recorder.csv: 1" % _REPLAY in r.stdout, r.stdout
    assert "12-digit substitutions in vss-setup/run.log" not in r.stdout, r.stdout
    assert "12-digit substitutions in text files: 1, in 1 file(s)" in r.stdout, r.stdout
    assert b"203.0.113.7" not in got("vss-setup/run.log") and b"<ip>" in got("vss-setup/run.log")
    assert "%s/result.json: 1 string(s) holding a newline" % _REPLAY in r.stdout, r.stdout
    lk = _leakscan(pub)
    assert lk.returncode == 0, lk.stdout


def _small_vss(tmp_path, stems):
    rec = tmp_path / "rec"
    _write(rec / "quiesce.txt", _QUIESCE_REC, newline=False)
    for stem, kw in stems.items():
        _vss_stem(rec, stem, **kw)
    return rec


_RUNNING = dict(status=None, done=False, result=False, after=False)


@needs_bash
@pytest.mark.parametrize("stems,incomplete,ok,marks", [
    ({"vss-setup": {}}, "", True, ["vss-setup: DONE"]),
    ({"vss-setup": dict(status=["status=TIMEOUT at=step-12 reason=30min-rule"])}, "", True, ["vss-setup: TIMEOUT"]),
    ({"vss-setup": dict(result=False)}, "", False, ["nothing ran"]),           # DONE, but no setup.json
    ({"vss-setup": dict(status=["status=FAILED at=preflight", "status=FAILED rc=1"], result=False, after=False)},
     "", True, ["vss-setup: FAILED"]),                                         # packed for its diagnostics
    ({"vss-setup": dict(status=["status=FAILED rc=127"], result=True, after=False)}, "", True, ["vss-setup: FAILED"]),
    ({"vss-setup": dict(status=[], after=False)}, "", False, ["nothing ran", "vss-setup: NO STATUS"]),
    ({"vss-setup": dict(status=["status=TIMEOUTISH"], after=False)}, "", False, ["nothing ran"]),
    ({"vss-setup": _RUNNING}, "", False, ["vss-setup has no done"]),
    ({"vss-setup": _RUNNING}, "vss-setup", True, ["vss-setup: INCOMPLETE"]),
    ({"vss-setup": {}, "vss-suite": _RUNNING}, "", False, ["vss-suite has no done"]),
    ({"vss-setup": {}, "vss-suite": _RUNNING}, "vss-suite", True, ["vss-setup: DONE", "vss-suite: INCOMPLETE"]),
    ({"vss-setup": {}}, "vss-other", False, ["CAPTURE_INCOMPLETE"]),
])
def test_capture_holds_a_vss_record_to_its_evidence_and_marks_failed_and_incomplete_stems(
        tmp_path, stems, incomplete, ok, marks):
    rec, pub = _small_vss(tmp_path, stems), tmp_path / "pub"
    r = _vss_capture(rec, pub, CAPTURE_INCOMPLETE=incomplete)
    out = r.stdout + r.stderr
    assert (r.returncode == 0) is ok, out
    for m in marks:
        assert m in out, (m, out)
    if ok:
        report = (pub / "capture.log").read_text(encoding="utf-8")
        assert all(m in report for m in marks), report
        for stem in stems:
            assert (pub / stem / "run.log").exists() and (pub / stem / "detach.log").exists(), stem
    else:
        assert not os.path.exists(str(tmp_path / "pub.sha256")), out


@needs_bash
def test_capture_publishes_its_report_through_the_redactor(tmp_path):
    """capture.log on the instance holds a stem's last status line as it was written; the copy in the publication
    went through the redactor like every other file there."""
    last = "status=FAILED at=apt from 203.0.113.7 on i-0123456789abcdef0"
    rec = _small_vss(tmp_path, {"vss-setup": dict(status=[last], result=False, after=False)})
    r = _vss_capture(rec, tmp_path / "pub")
    assert r.returncode == 0 and "vss-setup: FAILED (%s" % last in r.stdout, r.stdout + r.stderr
    report = (tmp_path / "pub" / "capture.log").read_text(encoding="utf-8")
    assert "vss-setup: FAILED (status=FAILED at=apt from <ip> on <instance-id>" in report, report
    assert "203.0.113.7" not in report and "i-0123456789abcdef0" not in report, report
    lk = _leakscan(tmp_path / "pub")
    assert lk.returncode == 0, lk.stdout


@needs_bash
def test_capture_drops_a_torn_last_jsonl_line_and_refuses_any_other_that_does_not_parse(tmp_path):
    rel = _REPLAY + "/vss-witness.jsonl"
    rec = _small_vss(tmp_path, {"vss-setup": {}, "vss-suite": {}})
    _write(rec / rel, _WITNESS + '{"event":"update","t_ns":9123', newline=False)     # the writer was cut off
    r = _vss_capture(rec, tmp_path / "pub")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "pub" / rel).read_bytes() == _WITNESS.encode()
    assert "torn last line dropped: %s" % rel in r.stdout, r.stdout
    # a last line with no newline that parses is kept as it is
    last = '{"event":"end","t_ns":%d}' % (_T12 + 9)
    _write(rec / rel, _WITNESS + last, newline=False)
    r = _vss_capture(rec, tmp_path / "pub2")
    assert r.returncode == 0 and (tmp_path / "pub2" / rel).read_bytes() == (_WITNESS + last).encode(), r.stdout + r.stderr
    # any other line that does not parse refuses the capture
    _write(rec / rel, '{"a":1}\n{"a":\n{"b":2}\n', newline=False)
    r = _vss_capture(rec, tmp_path / "pub3")
    assert r.returncode != 0 and "%s:2" % rel in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("suite,incomplete,state", [
    (dict(status=["status=FAILED rc=137"], after=False), "", "FAILED"),
    (_RUNNING, "vss-suite", "INCOMPLETE"),
    (dict(status=[], after=False), "", "NO STATUS"),          # done, but no terminal status line
    ({}, "", None),
])
def test_capture_leaves_out_a_json_file_a_partial_stem_cut_short_and_refuses_one_elsewhere(
        tmp_path, suite, incomplete, state):
    """A FAILED, INCOMPLETE or NO STATUS stem's JSON may have been cut short (a kill, or a harness still writing): it
    is left out and named, not a refusal that would lose the whole session. In a DONE stem it is a fault, refused as
    before."""
    rel = _REPLAY + "/result.json"
    rec = _small_vss(tmp_path, {"vss-setup": {}, "vss-suite": suite})
    _write(rec / rel, '{"ok": true, "gates": {', newline=False)
    r = _vss_capture(rec, tmp_path / "pub", CAPTURE_INCOMPLETE=incomplete)
    out = r.stdout + r.stderr
    assert (r.returncode == 0) is (state is not None), out
    if state:
        assert "excluded: %s (does not parse, in a %s stem: " % (rel, state) in out, out
        assert not (tmp_path / "pub" / rel).exists(), out
    else:
        assert "%s: does not parse" % rel in out, out


@needs_bash
def test_capture_takes_a_20k_line_jsonl_file_with_one_redactor_call_within_a_bound(tmp_path):
    """A large synthetic JSONL input must use a shared redactor call;
    the bound here (a design value) is far above one call per file."""
    rel = _REPLAY + "/vss-witness.jsonl"
    rec = _small_vss(tmp_path, {"vss-setup": {}, "vss-suite": {}})
    lines = ['{"event":"update","path":"Vehicle.Speed","seq":%d,"t_ns":%d,"tag":"u%d"}' % (i, _T12 + i, i)
             for i in range(20000)]
    lines[0] = lines[0].replace('"tag":"u0"', '"tag":"from 203.0.113.7"')
    text = "\n".join(lines) + "\n"
    _write(rec / rel, text, newline=False)
    t0 = time.monotonic()
    r = _vss_capture(rec, tmp_path / "pub")
    took = time.monotonic() - t0
    assert r.returncode == 0, r.stdout + r.stderr
    assert took < 30, "a 20k-line JSONL file took %.0f s to capture" % took
    assert (tmp_path / "pub" / rel).read_bytes() == text.replace("203.0.113.7", "<ip>").encode()


@needs_bash
def test_an_a6_record_keeps_its_rules_and_its_jsonl_now_gets_the_json_rule(tmp_path):
    """The A6 path is unchanged where the vss capture does not change it: no whitelist, no capture.log in the
    publication, a newline in a JSON string still refused. Its .jsonl files get the JSON rule, as leakscan reads them,
    and its JSON strings lose an IPv6 address as a vss record's do, :: and ::1 kept."""
    rec = _rec(tmp_path)
    stamp = rec / "ladder" / "raw" / "stamp.json"
    doc = json.loads(stamp.read_text(encoding="utf-8"))
    doc.update({"host_ipv6": "2001:db8::5", "sshd": "[::]:22", "chronyd": "[::1]:323"})
    _write(stamp, json.dumps(doc, indent=2))
    _write(rec / "ladder" / "raw" / "inj-t2ms_r1.jsonl", '{"kind":"U","t_ns":%d}\n' % _T12, newline=False)
    _write(rec / "ladder" / "extra.txt", "kept: the A6 walk takes everything but *.so and .run-start")
    r = _capture(rec, tmp_path / "pub")
    assert r.returncode == 0, r.stdout + r.stderr
    pub = tmp_path / "pub"
    assert (pub / "ladder" / "raw" / "inj-t2ms_r1.jsonl").read_bytes() == \
        (rec / "ladder" / "raw" / "inj-t2ms_r1.jsonl").read_bytes()
    assert (pub / "ladder" / "extra.txt").exists() and not (pub / "capture.log").exists()
    assert "excluded:" not in r.stdout, r.stdout
    got = json.loads((pub / "ladder" / "raw" / "stamp.json").read_text(encoding="utf-8"))
    assert (got["host_ipv6"], got["sshd"], got["chronyd"]) == ("<ipv6>", "[::]:22", "[::1]:323"), got
    assert got["qemu_started_ns"] == 123456789012, got
    _write(rec / "ladder" / "raw" / "stamp.json", json.dumps({"note": "a\nb"}), newline=False)
    r = _capture(rec, tmp_path / "pub2")
    assert r.returncode != 0 and "a string holds a newline" in r.stdout + r.stderr, r.stdout + r.stderr


# leakscan: .jsonl per line as JSON, vss-claim-bridge.log's JSON as JSON, :: and ::1 kept

@pytest.mark.parametrize("name,text,ok", [
    ("replies.jsonl", '{"t_mono":%d,"local":"[::]:22"}\n{"t_mono":%d,"local":"[::1]:323"}\n' % (_T12, _T12 + 1), True),
    ("replies.jsonl", '{"local":"[fe80::1%ens5]:546"}\n', False),
    ("replies.jsonl", '{"peer":"203.0.113.7"}\n', False),
    ("replies.jsonl", '{"a":1}\n{"a":<account>}\n', False),                 # a number the text redactor rewrote
    ("replies.jsonl", '{"a":1}\n\n{"b":2}', True),                         # a blank line holds nothing
    ("vss-claim-bridge.log", "2026-10-03T05:31:30.821425168Z " + _BRIDGE_JSON.replace("203.0.113.7", "<ip>") + "\n", True),
    ("vss-claim-bridge.log", "2026-10-03T05:31:30.821425168Z " + _BRIDGE_JSON + "\n", False),
    ("vss-claim-bridge.log", "2026-10-03T05:31:30.900000001Z account %d noted\n" % _T12, False),
    ("listen.log", "sshd on [::]:22 and chronyd on [::1]:323", True),
    ("listen.log", "dhcp6 on [fe80::1%ens5]:546", False),
])
def test_leakscan_reads_jsonl_and_the_bridge_logs_json_as_json_and_keeps_unspecified_and_loopback_ipv6(
        tmp_path, name, text, ok):
    _write(tmp_path / "d" / name, text, newline=False)
    r = _leakscan(tmp_path / "d")
    assert (r.returncode == 0) is ok, r.stdout


def test_capture_masks_ipv6_by_leakscans_own_pattern_and_keep_set():
    """capture.py runs alone on the instance, so it cannot import leakscan.py: the two copies are held equal here.
    What capture keeps, leakscan keeps; what leakscan would flag, capture masked."""
    import ast

    def parts(path):
        src = open(path, encoding="utf-8").read()
        pat = re.search(r'^IPV6 = re\.compile\((r".*")\)$', src, re.M)
        keep = re.search(r"^KEEP_IPV6 = (\{.*?\})", src, re.M)
        assert pat and keep, path
        return ast.literal_eval(pat.group(1)), ast.literal_eval(keep.group(1)), src
    cp, ck, csrc = parts(CAPTURE)
    lp, lk, lsrc = parts(LEAKSCAN)
    assert cp == lp and ck == lk == {"::", "::1", "fe80::5054:ff:fe11:1111"}
    rule = 'if ("::" in tok or tok.count(":") >= 5) and tok.lower() not in KEEP_IPV6 and not MAC.fullmatch(tok):'
    assert rule in csrc and rule in lsrc


@needs_bash
def test_the_published_tooling_is_a_fixed_point_of_the_redactor_and_clean(tmp_path):
    """capture.py and remote-ladder.sh are copied into every record's tooling/ and published through the redactor:
    an edit that left a shape the redactor rewrites would break the CAPTURE_SHA256 the record carries."""
    d = tmp_path / "tooling"
    d.mkdir()
    for src in (CAPTURE, REMOTE):
        with open(src, "rb") as f:
            r = subprocess.run([BASH, REDACT], stdin=f, capture_output=True, timeout=120,
                               env=dict(os.environ, USER="", PATH=_path_with()))
        assert r.returncode == 0 and r.stdout == open(src, "rb").read(), src
        shutil.copy(src, str(d))
    lk = _leakscan(d)
    assert lk.returncode == 0, lk.stdout


# the capture phase's gate for a vss stem (remote-ladder.sh capture)

def _capture_w(tmp_path, ahead_min=80):
    """W for the capture phase: the real redactor and capture.py, python3 as this test's interpreter."""
    w, stub = _vss_w(tmp_path, ahead_min=ahead_min)
    shutil.copy(REDACT, str(w / "repo" / "orin-native" / "gpu-concurrency" / "redact-aws.sh"))
    shutil.copy(CAPTURE, str(w / "capture.py"))
    _stubs(stub, {"python3": 'exec "%s" "$@"' % _posix(PY)})
    return w, stub


def _gate(w, stub):
    # W in this bash's own form: GNU tar reads a Windows path's "C:" as a remote host
    return _vss_phase(w, stub, "capture", timeout=300, W=_posix(w), USER="")


@needs_bash
def test_the_capture_phase_packs_a_failed_only_vss_record_and_marks_it_failed(tmp_path):
    """A FAILED setup writes no host-after.txt; its record is still captured, marked FAILED."""
    w, stub = _capture_w(tmp_path)
    _vss_stem(w / "rec", "vss-setup", status=("status=FAILED at=preflight", "status=FAILED rc=1"), result=False,
              after=False)
    r = _gate(w, stub)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "captured" in out, out
    assert (w / "pub.tgz").exists()
    log = (w / "capture.log").read_text(encoding="utf-8")
    assert "vss-setup: FAILED" in log, log
    assert (w / "pub" / "vss-setup" / "status").read_text().splitlines()[-1] == "status=FAILED rc=1"
    assert "FAILED" in (w / "pub" / "capture.log").read_text(encoding="utf-8")


@needs_bash
@pytest.mark.parametrize("ahead_min,packed", [(80, False), (14, False), (12, True)])
def test_the_capture_phase_refuses_a_stem_without_done_until_the_give_up_point_then_packs_it_incomplete(
        tmp_path, ahead_min, packed):
    """The give-up point is stop_at + 12 min, the deadline - 13 min: 14 min ahead it is a minute away, 12 min
    ahead a minute past."""
    w, stub = _capture_w(tmp_path, ahead_min=ahead_min)
    _vss_stem(w / "rec", "vss-setup")
    _vss_stem(w / "rec", "vss-suite", **_RUNNING)
    r = _gate(w, stub)
    out = r.stdout + r.stderr
    if not packed:
        assert r.returncode != 0 and "vss-suite has no done" in out, out
        assert not (w / "pub.tgz").exists() and not (w / "capture.log").exists(), "refused before capture.py ran"
    else:
        assert r.returncode == 0 and "INCOMPLETE" in out, out
        assert "vss-suite: INCOMPLETE" in (w / "capture.log").read_text(encoding="utf-8")
        assert (w / "pub" / "vss-suite" / "run.log").exists() and (w / "pub.tgz").exists()


@needs_bash
@pytest.mark.parametrize("ahead_min,packed", [(14, False), (12, True)])
def test_the_capture_phase_packs_a_record_whose_only_stem_has_no_done_once_past_the_give_up_point(
        tmp_path, ahead_min, packed):
    """V1's likeliest INCOMPLETE record: setup hangs, wait-run gives up, and the runbook goes on to the capture. No
    stem has finished and no host-after.txt exists, so the gate's own pass past the give-up point is all that lets
    the capture through, and the session's diagnostics out before the instance goes."""
    w, stub = _capture_w(tmp_path, ahead_min=ahead_min)
    _vss_stem(w / "rec", "vss-setup", **_RUNNING)
    r = _gate(w, stub)
    out = r.stdout + r.stderr
    if not packed:
        assert r.returncode != 0 and "vss-setup has no done" in out, out
        assert not (w / "pub.tgz").exists() and not (w / "capture.log").exists(), "refused before capture.py ran"
    else:
        assert r.returncode == 0 and "captured" in out, out
        assert "vss-setup: INCOMPLETE" in (w / "capture.log").read_text(encoding="utf-8")
        assert (w / "pub" / "vss-setup" / "run.log").exists() and (w / "pub.tgz").exists()
        assert "vss-setup: INCOMPLETE" in (w / "pub" / "capture.log").read_text(encoding="utf-8")


@needs_bash
def test_the_capture_phase_refuses_a_stem_without_done_when_it_cannot_read_the_give_up_point(tmp_path):
    w, stub = _capture_w(tmp_path, ahead_min=-60)
    (w / "deadline").unlink()
    _vss_stem(w / "rec", "vss-setup", **_RUNNING)
    r = _gate(w, stub)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "give-up point" in out and not (w / "pub.tgz").exists(), out


@needs_bash
@pytest.mark.parametrize("status,ok", [
    (("status=DONE",), True), (("status=TIMEOUT at=step-12 reason=30min-rule",), True),
    ((), False), (("status=RUNNING step=3",), False)])
def test_the_capture_phase_takes_a_done_vss_stem_only_with_a_terminal_status_line(tmp_path, status, ok):
    w, stub = _capture_w(tmp_path)
    _vss_stem(w / "rec", "vss-setup", status=status, after=ok)
    r = _gate(w, stub)
    out = r.stdout + r.stderr
    assert (r.returncode == 0) is ok, out
    if not ok:
        assert "the session did not finish" in out and not (w / "capture.log").exists(), out


# --------------------------------------------------------------------------
# Plan Phase 3 WP3fix: session-safety regression cases. Documentation values only.

# Findings 1-4: capture.py on a vss stem that did not end whole, and on a file it cannot read

@needs_bash
@pytest.mark.parametrize("stem,rel", [
    ("vss-suite", _REPLAY + "/attribution.json"),       # E1: a cap's TERM inside step3's write
    ("vss-setup", "vss-setup/raw/setup.json"),          # E1b: the TIMEOUT stem's own result file
], ids=["E1-attribution", "E1b-setup-json"])
def test_capture_leaves_out_a_json_file_a_timeout_stem_cut_short(tmp_path, stem, rel):
    """Finding 1. A TIMEOUT by step-timeout is a cap's TERM landing anywhere, inside a JSON write too: such a file is
    left out and named, as a FAILED stem's is, not a refusal that loses the session's record."""
    rec = _small_vss(tmp_path, {"vss-setup": {}, "vss-suite": {}})
    _write(rec / stem / "status", "status=TIMEOUT at=run-07 reason=step-timeout")
    whole = json.dumps({"rows": [{"writer": "w%d" % i, "path": "Vehicle.Speed"} for i in range(400)]})
    _write(rec / rel, whole[:len(whole) // 2], newline=False)
    r = _vss_capture(rec, tmp_path / "pub")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "excluded: %s (does not parse, in a TIMEOUT stem: " % rel in out, out
    assert not (tmp_path / "pub" / rel).exists() and (tmp_path / "pub.sha256").exists(), out
    assert "%s: TIMEOUT" % stem in (tmp_path / "pub" / "capture.log").read_text(encoding="utf-8")


@needs_bash
def test_capture_takes_a_timeout_stem_without_its_result_file_and_notes_it(tmp_path):
    """Finding 2 (E2). A TIMEOUT stem stopped before its end, as a FAILED one did: without its result file it is still
    evidence, packed with the missing file noted. A DONE stem still needs its result file (an earlier test)."""
    rec = _small_vss(tmp_path, {"vss-setup": dict(status=["status=TIMEOUT at=step-1 reason=deadline"], result=False)})
    r = _vss_capture(rec, tmp_path / "pub")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    report = (tmp_path / "pub" / "capture.log").read_text(encoding="utf-8")
    assert "vss-setup: TIMEOUT (status=TIMEOUT at=step-1 reason=deadline" in report, report
    assert "no raw/setup.json" in report, report
    assert (tmp_path / "pub" / "vss-setup" / "status").exists() and (tmp_path / "pub" / "vss-setup" / "run.log").exists()


_JL = '{"event":"update","path":"Vehicle.Speed","t_ns":%d,"value":1.5}\n' % _T12
_ZEROED = (_JL + "\0" * 64 + "\n" + _JL).encode()                       # a zero-filled run inside the file
_LATIN = _JL.encode() + b'{"name":"Stra\xdfe"}\n' + _JL.encode()         # a line that is not UTF-8
_TORN = _JL.encode() + '{"event":"start","name":"Stra\u00dfe'.encode()[:-2]   # the last line cut inside the sharp s


@needs_bash
@pytest.mark.parametrize("suite,incomplete,body,outcome", [
    (dict(status=["status=FAILED rc=137"], after=False), "", _ZEROED, "excluded"),          # E3a
    (dict(status=["status=TIMEOUT at=run-07 reason=step-timeout"]), "", _LATIN, "excluded"),
    (dict(status=[], after=False), "", _ZEROED, "excluded"),                               # NO STATUS
    (_RUNNING, "vss-suite", _TORN, "torn"),                                                 # E3b
    ({}, "", _TORN, "torn"),                       # a torn last line is judged first, in any stem
    ({}, "", _ZEROED, "refused"),                  # a whole (DONE) stem: refused, as before
    ({}, "", _LATIN, "refused"),
], ids=["E3a-failed-zeroed", "timeout-not-utf8", "nostatus-zeroed", "E3b-incomplete-torn", "done-torn", "done-zeroed",
        "done-not-utf8"])
def test_capture_leaves_out_a_jsonl_file_of_a_partial_stem_that_does_not_parse_and_drops_a_torn_last_line(
        tmp_path, suite, incomplete, body, outcome):
    """Finding 3 (E3a, E3b). In a stem that did not end whole (FAILED, TIMEOUT, INCOMPLETE, NO STATUS) a JSONL file
    with a line that does not parse or decode is left out and named, as such a stem's JSON file is; and a last line
    cut inside a multi-byte character is a torn last line, dropped, whatever the stem. A DONE stem's bad line still
    refuses the capture."""
    rel = _REPLAY + "/vss-witness.jsonl"
    rec = _small_vss(tmp_path, {"vss-setup": {}, "vss-suite": suite})
    (rec / rel).parent.mkdir(parents=True, exist_ok=True)
    (rec / rel).write_bytes(body)
    r = _vss_capture(rec, tmp_path / "pub", CAPTURE_INCOMPLETE=incomplete)
    out = r.stdout + r.stderr
    if outcome == "refused":
        assert r.returncode != 0 and "%s:2" % rel in out, out
        return
    assert r.returncode == 0, out
    if outcome == "excluded":
        assert "excluded: %s (a line that does not parse, in a " % rel in out, out
        assert not (tmp_path / "pub" / rel).exists(), out
    else:
        assert "torn last line dropped: %s" % rel in out, out
        assert (tmp_path / "pub" / rel).read_bytes() == _JL.encode()
    assert (tmp_path / "pub.sha256").exists()


@needs_bash
@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="a dangling link and a mode-000 file need a POSIX file system and a user who is not root")
@pytest.mark.parametrize("how,rel,incomplete", [
    ("dangling", "vss-setup/raw/df.txt", "vss-setup"),                # E7: an INCOMPLETE stem's file gone
    ("mode000", "vss-setup/raw/df.txt", ""),                          # E7b: a DONE stem's file unreadable
    ("dangling", _REPLAY + "/attribution.json", ""),
    ("dangling", _REPLAY + "/vss-witness.jsonl", ""),
    ("dangling", _REPLAY + "/vss-claim-bridge.log", ""),
], ids=["E7-dangling-text", "E7b-mode000-text", "dangling-json", "dangling-jsonl", "dangling-bridge-log"])
def test_capture_names_a_file_it_cannot_read_and_goes_on(tmp_path, how, rel, incomplete):
    """Finding 4 (E7, E7b). A file the walk listed and the read cannot open (removed meanwhile by a harness still
    running, or unreadable) is left out and named in capture.log; the capture goes on, where it ended in a traceback."""
    stems = {"vss-setup": _RUNNING if incomplete else {}, "vss-suite": {}}
    rec = _small_vss(tmp_path, stems)
    p = rec / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if how == "dangling":
        os.symlink(str(tmp_path / "gone" / os.path.basename(rel)), str(p))
    else:
        _write(p, "/dev/root on /")
        os.chmod(str(p), 0)
    try:
        r = _vss_capture(rec, tmp_path / "pub", CAPTURE_INCOMPLETE=incomplete)
    finally:
        if how == "mode000":
            os.chmod(str(p), 0o644)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "Traceback" not in out, out
    assert "excluded: %s (cannot be read: " % rel in out, out
    assert "excluded: %s (cannot be read: " % rel in (tmp_path / "pub" / "capture.log").read_text(encoding="utf-8")
    assert not (tmp_path / "pub" / rel).exists() and (tmp_path / "pub.sha256").exists()


# Findings 5-8 and NIT 10: the harness phase's checks before it starts a vss harness

def _setup_done(w):
    """vss-setup as the detached runner leaves a run that ended DONE."""
    return _laid(w, lines=["status=DONE"], done=True)


@needs_bash
@pytest.mark.parametrize("words", [_SETUP, _SUITE])
@pytest.mark.parametrize("a6", ["bell", "ladder"])
def test_a_vss_harness_is_refused_while_rec_holds_an_a6_record(tmp_path, words, a6):
    """Finding 5 (E4). capture.py publishes a vss record by its whitelist, so an A6 harness's record beside a vss stem
    would be left out and lost with the instance: the phase refuses a vss harness while rec holds one."""
    w, stub = _vss_w(tmp_path)
    if words == _SUITE:
        _setup_done(w)
    _write(w / "rec" / a6 / "run.log", "an A6 harness ran here")
    r = _vss_phase(w, stub, "harness", words)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "holds an A6 record (%s)" % a6 in out, out
    assert not (w / "vss-session").exists() and not (stub / "setsid.log").exists()
    assert not (w / "rec" / ("vss-suite" if words == _SUITE else "vss-setup") / "host-before.txt").exists()


@needs_bash
@needs_proc_interrupts
def test_setups_own_empty_ladder_directory_is_not_an_a6_record(tmp_path):
    w, stub = _vss_w(tmp_path)
    (w / "rec" / "ladder").mkdir()
    (w / "rec" / "tooling").mkdir()
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("setup", [
    None,                                                           # E5b: no vss-setup at all
    dict(lines=None, done=False),                                   # E5: setup still running
    dict(lines=["status=DONE"], done=False),                        # its runner not yet done
    dict(lines=["status=TIMEOUT at=step-12 reason=30min-rule"], done=True),
    dict(lines=["status=FAILED rc=1"], done=True),
    dict(lines=["status=DONE", "status=FAILED rc=0"], done=True),   # the runner's FAILED line comes last
], ids=["E5b-no-setup", "E5-running", "done-line-no-done", "timeout-30min-rule", "failed", "done-then-failed"])
def test_the_suite_needs_a_finished_setup_whose_last_status_line_is_done(tmp_path, setup):
    """Finding 6 (E5, E5b). A suite started before setup finished (a premature step 8) spent the session's one suite
    run on a preflight failure: the phase now refuses it before the marker and the stem directory."""
    w, stub = _vss_w(tmp_path)
    if setup is not None:
        _laid(w, **setup)
    r = _vss_phase(w, stub, "harness", _SUITE)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "run-vss-suite.sh needs a finished run-vss-setup.sh" in out, out
    assert not (w / "vss-session").exists() and not (w / "rec" / "vss-suite").exists()
    assert not (stub / "setsid.log").exists()


@needs_bash
@needs_proc_interrupts
def test_the_phase_fails_and_frees_its_stem_when_the_detached_runner_does_not_start(tmp_path):
    """Finding 7 (E8). `started` was printed with no proof that the runner ran: wait-run then waited to its give-up
    point, and the phase could not run again. The runner's run.log is now the proof; without it the phase shows
    detach.log, removes the stem directory it made and fails, and a second attempt can start."""
    w, stub = _vss_w(tmp_path)
    _stubs(stub, {"setsid": 'echo "setsid: failed to execute nohup: No such file or directory" >&2; exit 1'})
    r = _vss_phase(w, stub, "harness", _SETUP, VSS_START_WAIT_S="1")
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "did not start" in out, out
    assert "failed to execute nohup" in out and "started run-vss-setup.sh, detached" not in out, out
    assert not (w / "rec" / "vss-setup").exists(), out
    _stubs(stub, {"setsid": _STUB_BIN["setsid"]})
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_STATUS_LINE="status=DONE")
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "started run-vss-setup.sh, detached" in out, out
    assert _wait_for(w / "rec" / "vss-setup" / "done"), out


@needs_bash
def test_upload_refuses_a_second_upload_in_one_session(rig, tmp_path):
    """Finding 8 (E6), the driver's half. setup verifies one upload and refuses to run again, so a second upload
    would leave the first tarball's repo beside the second's inputs: upload refuses once this session uploaded."""
    run, state, stub = rig
    _armed(state)
    (state / "uploaded").touch()
    r, _ = _upload(run, _upload_dir(tmp_path), [])
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "already uploaded" in out, out
    assert not (stub / "scp.log").exists() and not (stub / "ssh.log").exists(), "refused before anything was sent"


@needs_bash
@pytest.mark.parametrize("words", [_SETUP, _SUITE])
def test_a_vss_harness_refuses_inputs_that_are_not_what_setup_verified(tmp_path, words):
    """Finding 8 (E6), the instance's half: W/inputs.env must still be the copy setup verified and kept in
    rec/tooling/inputs.env."""
    w, stub = _vss_w(tmp_path)
    if words == _SUITE:
        _setup_done(w)
    verified = (w / "inputs.env").read_text(encoding="utf-8")
    _write(w / "rec" / "tooling" / "inputs.env", verified.replace("REPO_COMMIT=" + "e" * 40, "REPO_COMMIT=" + "a" * 40),
           newline=False)
    r = _vss_phase(w, stub, "harness", words)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "differs from" in out and "rec/tooling/inputs.env" in out, out
    assert not (w / "vss-session").exists() and not (stub / "setsid.log").exists()


@needs_bash
@needs_proc_interrupts
def test_a_vss_harness_starts_when_inputs_env_is_what_setup_verified(tmp_path):
    w, stub = _vss_w(tmp_path)
    _write(w / "rec" / "tooling" / "inputs.env", (w / "inputs.env").read_text(encoding="utf-8"), newline=False)
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("words", [_SETUP, _SUITE])
def test_a_vss_harness_boots_only_the_sessions_metal_ifs(tmp_path, words):
    """NIT 10 (E13). IMAGE= of a vss harness is the session's METAL_IFS: another uploaded image would pass the phase
    and fail the harness's own check later, spending its one run."""
    w, stub = _vss_w(tmp_path)
    r = _vss_phase(w, stub, "harness", words.replace("IMAGE=ifs-vss.bin", "IMAGE=ifs-bell.bin"))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "boots the session's METAL_IFS, ifs-vss.bin, not ifs-bell.bin" in out, out
    assert not (w / "vss-session").exists() and not (stub / "setsid.log").exists()


# NIT 9: the bundle's commit is the tarball's

def _tar_with_commit(path, commit):
    """A tarball as `git archive <commit>` writes one: the commit in a pax global header (git get-tar-commit-id)."""
    data = b"stand-in"
    with tarfile.open(str(path), "w", format=tarfile.PAX_FORMAT,
                      pax_headers={} if commit is None else {"comment": commit}) as t:
        info = tarfile.TarInfo("orin-native/gpu-concurrency/README.md")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))


@needs_bash
@pytest.mark.parametrize("tar_commit,bundle,ok", [
    ("e" * 40, {"format": 1, "commit": "e" * 40}, True),
    ("e" * 40, {"format": 1, "commit": "d" * 40}, False),         # E10
    (None, {"format": 1, "commit": "e" * 40}, False),            # a tarball with no commit to compare
    ("e" * 40, {"format": 1}, False),                            # a bundle.json with no commit
    ("e" * 40, "not JSON", False),
])
def test_upload_refuses_a_bundle_built_from_another_commit_than_the_tarball(rig, tmp_path, tar_commit, bundle, ok):
    """NIT 9 (E10). WP4's preflight would catch the mismatch only on the instance, after a launch."""
    run, state, stub = rig
    _armed(state)
    d = _upload_dir(tmp_path)
    _tar_with_commit(d / "repo.tar", tar_commit)
    b = tmp_path / "files" / "bundle.json"
    _write(b, bundle if isinstance(bundle, str) else json.dumps(bundle), newline=False)
    r, _ = _upload(run, d, [b])
    out = r.stdout + r.stderr
    assert (r.returncode == 0) is ok, out
    if not ok:
        assert "bundle.json" in out and "commit" in out, out
        assert not (stub / "scp.log").exists() and not (stub / "ssh.log").exists(), "refused before anything was sent"


# NIT 11: the call form of vss_capped under set -e

@needs_bash
@needs_proc_interrupts
def test_a_cap_that_fires_in_the_documented_call_form_ends_in_a_timeout_line_not_a_failed_run(tmp_path):
    """NIT 11. vss_capped returns the cap's 124 or 137: called bare under set -e it ends the harness before any status
    line, and the runner writes FAILED with no clean stop. In the call form the library's header gives, the stub
    harness writes status=TIMEOUT ... reason=step-timeout and exits 0. A real cap fires at its end, stop_at + 10 minutes,
    and vss_cap_fired reads 124 as the cap's only from then on: the stub cap moves the clock (`date +%s`) there."""
    w, stub = _vss_w(tmp_path, harness_body=_STUB_DEADLINE, ahead_min=26)
    _stubs(stub, {"timeout": 'echo "timeout $*" >> "$STUB_DIR/timeout.log"; : > "$STUB_DIR/cap-fired"; exit 124',
                  "date": 'if [ "$*" = +%s ] && [ -e "$STUB_DIR/cap-fired" ]; then '
                          'echo $(( $(cat "$QNX_METAL_DEADLINE_FILE") - 900 )); exit 0; fi; command -p date "$@"'})
    r = _vss_phase(w, stub, "harness", _SETUP)
    d = w / "rec" / "vss-setup"
    assert r.returncode == 0 and _wait_for(d / "done"), r.stdout + r.stderr
    assert (d / "status").read_text().splitlines() == ["status=TIMEOUT at=step-1 reason=step-timeout"]
    assert (d / "host-after.txt").exists()
    with open(LIB, encoding="utf-8") as f:
        assert "rc=0; vss_capped CMD... || rc=$?" in f.read()


# --------------------------------------------------------------------------
# plan Phase 3 WP6 item 2: the capture rehearsal's findings,
# each a test that failed on the tree the rehearsal ran. Documentation values only.

# Finding 1 (BLOCKER): the redactor's boundary after a kept match. A reply frame as the bridge writes it
# (replies.jsonl's "frame": 64 bytes as 128 hex characters, zero-padded), with synthetic values in its layout. Its
# trailing digit run is 84 characters long, seven times twelve, as in most of the PC's replay frames.
_FRAME = "0700000000000000" "4a1b2c3d" "af000000" "1f0168ea684d" + "0" * 36 + "04" + "0" * 46
_REPLY = ('{"age_ms":0,"demo":false,"event":"reply","frame":"%s","inject":null,"profile":1,"reason":0,"seq":%d,'
          '"src_now_ns":%d,"t_mono":%d,"tstamp_ns":%d,"verdict":0}\n')


def _frame(run):
    """A 128-hex frame whose trailing digit run is `run` characters long, with a letter before it."""
    return (_FRAME[:44] + "c" * 84)[:128 - run] + "0" * run


def _redacted(text, awk):
    r = subprocess.run([BASH, REDACT], input=text.encode(), capture_output=True, timeout=60,
                       env=dict(os.environ, USER="", AWK=awk, PATH=_path_with()))
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
    """Finding 1. mask() read the character before a match as "" whenever the match began at the head of what was
    left, so after a kept 12-digit match the next 12 digits of the same run were masked when the run then ended:
    x and 24 zeros came back as x, 12 zeros and <account>. Both directions, under every awk here."""
    assert _redacted(line + "\n", awk) == (line if want is None else want) + "\n"


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
def test_capture_publishes_the_guests_reply_frames_as_the_guest_sent_them(tmp_path, awk):
    """Finding 1. In the rehearsal frames in every replies.jsonl lost their last 12 zeros to <account>, and nothing
    said so. Lines in the bridge's own format, with frames whose trailing digit runs are 12, 24, 36 and 84 long, come
    through byte for byte, and no substitution is named for the file."""
    rel = _REPLAY + "/bridge/replies.jsonl"
    rec = _small_vss(tmp_path, {"vss-setup": {}, "vss-suite": {}})
    body = "".join(_REPLY % (f, i, _T12 + i, _T12 + 50 + i, _T12 + 40 + i)
                   for i, f in enumerate([_frame(12), _frame(24), _frame(36), _FRAME], 1))
    _write(rec / rel, body, newline=False)
    r = _vss_capture(rec, tmp_path / "pub", AWK=awk)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "pub" / rel).read_bytes() == body.encode()
    assert "string substitutions in %s" % rel not in r.stdout, r.stdout


# Finding 2 (SHOULD): the substitutions made in JSON strings, named per file in capture.log

@needs_bash
def test_capture_names_every_substitution_it_makes_in_json_strings_per_file(tmp_path):
    """Finding 2. The per-file count covered text files only, so the frames' <account> went unreported. Every
    substitution the redactor or the IPv6 mask makes in a string of a JSON or JSONL file, or of the bridge log's JSON,
    is named per file and by kind, and totalled, in the printed report and in the published capture.log."""
    rec, pub = _vss_record(tmp_path), tmp_path / "pub"
    _write(rec / _REPLAY / "bridge" / "replies.jsonl",
           _REPLIES + '{"event":"note","text":"account 111122223333 and 444455556666"}\n', newline=False)
    r = _vss_capture(rec, pub)
    assert r.returncode == 0, r.stdout + r.stderr
    want = sorted(["string substitutions in %s/bridge/bridge.jsonl: <ip> 1, <ipv6> 1" % _REPLAY,
                   "string substitutions in %s/bridge/replies.jsonl: <account> 2" % _REPLAY,
                   "string substitutions in %s/listeners.json: <ip> 1, <ipv6> 1" % _REPLAY,
                   "string substitutions in %s/result.json: <instance-id> 1, <ip> 1" % _REPLAY,
                   "string substitutions in %s/vss-claim-bridge.log: <ip> 1" % _REPLAY,
                   "string substitutions in vss-setup/raw/setup.json: <ip> 1",
                   "string substitutions in JSON strings: 10, in 6 file(s) (<account> 2, <instance-id> 1, <ip> 5, "
                   "<ipv6> 2)"])
    for text in (r.stdout, (pub / "capture.log").read_text(encoding="utf-8")):
        assert sorted(ln for ln in text.splitlines() if ln.startswith("string substitutions in ")) == want, text
    assert '"text":"account <account> and <account>"' in (pub / _REPLAY / "bridge" / "replies.jsonl").read_text()


@needs_bash
def test_capture_says_when_it_made_no_substitution_in_json_strings(tmp_path):
    rec = _small_vss(tmp_path, {"vss-setup": {}})
    r = _vss_capture(rec, tmp_path / "pub")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "string substitutions in JSON strings: 0, in 0 file(s)" in \
        (tmp_path / "pub" / "capture.log").read_text(encoding="utf-8").splitlines()


# Finding 3 (SHOULD): IPv6 in a vss record's text files

@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
def test_capture_masks_ipv6_in_a_vss_records_text_files_and_keeps_unspecified_loopback_and_the_guests(tmp_path, awk):
    """Finding 3. The redactor masks IPv4 only and capture masked IPv6 only in JSON strings, so an instance address in
    run.log could reach the output and be refused by the fetch's leakscan.
    Text files, the bridge log's text lines included, now lose an IPv6 address by leakscan's own pattern and keep
    set, and each file's count is named."""
    rec = _small_vss(tmp_path, {"vss-setup": {}, "vss-suite": {}})
    _write(rec / "vss-setup" / "run.log",
           "instance inet6 fe80::1%ens5 scope link\n"
           "sshd on [::]:22, chronyd on [::1]:323, guest fe80::5054:ff:fe11:1111\n"
           "public 2001:db8::7 on the same line as fe80::1%ens5\n", newline=False)
    _write(rec / "vss-setup" / "raw" / "apt.log", "Err:1 http://[2001:db8::7]/ubuntu jammy InRelease\n", newline=False)
    _write(rec / _REPLAY / "vss-claim-bridge.log",
           "2026-10-03T05:31:30.821425168Z " + _BRIDGE_JSON + "\n"
           "2026-10-03T05:31:30.900000001Z vss_claim_bridge: peer [2001:db8::7]:7160 gone\n", newline=False)
    r = _vss_capture(rec, tmp_path / "pub", AWK=awk)
    assert r.returncode == 0, r.stdout + r.stderr
    pub = tmp_path / "pub"
    assert (pub / "vss-setup" / "run.log").read_text(encoding="utf-8") == (
        "instance inet6 <ipv6>%ens5 scope link\n"
        "sshd on [::]:22, chronyd on [::1]:323, guest fe80::5054:ff:fe11:1111\n"
        "public <ipv6> on the same line as <ipv6>%ens5\n")
    assert (pub / "vss-setup" / "raw" / "apt.log").read_text(encoding="utf-8") == \
        "Err:1 http://[<ipv6>]/ubuntu jammy InRelease\n"
    assert (pub / _REPLAY / "vss-claim-bridge.log").read_text(encoding="utf-8").splitlines() == [
        "2026-10-03T05:31:30.821425168Z " + _BRIDGE_JSON.replace('"203.0.113.7"', '"<ip>"'),
        "2026-10-03T05:31:30.900000001Z vss_claim_bridge: peer [<ipv6>]:7160 gone"]
    for line in ("IPv6 substitutions in vss-setup/run.log: 3", "IPv6 substitutions in vss-setup/raw/apt.log: 1",
                 "IPv6 substitutions in %s/vss-claim-bridge.log: 1" % _REPLAY,
                 "IPv6 substitutions in text files: 5, in 3 file(s)"):
        assert line in r.stdout.splitlines(), (line, r.stdout)
    lk = _leakscan(pub)
    assert lk.returncode == 0, lk.stdout


@needs_bash
def test_a_vss_capture_publishes_its_tooling_byte_for_byte(tmp_path):
    """capture.py and remote-ladder.sh go into every record's tooling/, and a vss record's text files now pass the
    IPv6 mask and the final-newline rule besides the redactor: the published copies must still be the uploaded bytes,
    or the record's tooling would not match its own CAPTURE_SHA256."""
    rec = _small_vss(tmp_path, {"vss-setup": {}})
    (rec / "tooling").mkdir()
    for src in (CAPTURE, REMOTE):
        shutil.copy(src, str(rec / "tooling"))
    r = _vss_capture(rec, tmp_path / "pub")
    assert r.returncode == 0, r.stdout + r.stderr
    for src in (CAPTURE, REMOTE):
        with open(src, "rb") as f:
            assert (tmp_path / "pub" / "tooling" / os.path.basename(src)).read_bytes() == f.read(), src


# NIT 4: a text file's missing final newline

@needs_bash
def test_capture_keeps_a_text_files_missing_final_newline(tmp_path):
    """NIT 4. awk's print ended every text file in a newline, so an INCOMPLETE stem's run.log, cut inside a line, read
    as whole in the publication. A missing final newline stays missing, and a present one stays."""
    rec = _small_vss(tmp_path, {"vss-setup": {}, "vss-suite": _RUNNING})
    _write(rec / "vss-suite" / "run.log", "step 3 of 9: run 12\nprepared /home/ubuntu/a1/rec/vss-suite/raw/runs/inj",
           newline=False)
    _write(rec / "vss-setup" / "run.log", "step 13 of 13: close\nfrom 203.0.113.7\n", newline=False)
    r = _vss_capture(rec, tmp_path / "pub", CAPTURE_INCOMPLETE="vss-suite")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "pub" / "vss-suite" / "run.log").read_bytes() == \
        b"step 3 of 9: run 12\nprepared /home/ubuntu/a1/rec/vss-suite/raw/runs/inj"
    assert (tmp_path / "pub" / "vss-setup" / "run.log").read_bytes() == b"step 13 of 13: close\nfrom <ip>\n"


# NIT 5: a FAILED stem's own last status line

@needs_bash
def test_capture_quotes_a_failed_stems_own_last_status_line_beside_the_runners(tmp_path):
    """NIT 5. The detached runner appends status=FAILED rc=N after the harness's own line, and capture.log quoted only
    the runner's: where the run failed was only in the published status file. A stem whose only line is the runner's
    reads as before."""
    rec = _small_vss(tmp_path, {"vss-setup": dict(status=["status=FAILED at=pulls", "status=FAILED rc=1"], after=False),
                                "vss-suite": dict(status=["status=FAILED rc=127"], result=False, after=False)})
    r = _vss_capture(rec, tmp_path / "pub")
    assert r.returncode == 0, r.stdout + r.stderr
    report = (tmp_path / "pub" / "capture.log").read_text(encoding="utf-8")
    assert "vss-setup: FAILED (status=FAILED rc=1, after the harness's own status=FAILED at=pulls: a partial record" \
        in report, report
    assert "vss-suite: FAILED (status=FAILED rc=127: a partial record" in report, report


# --------------------------------------------------------------------------
# wp6-close: WP6 item 4 (the detach rehearsal in WSL, with a real setsid) and item 1's NIT 2. The doc test,
# the group kill and the two red() tests each failed on the tree the rehearsal ran; the two SigIgn tests pin what the
# rehearsal found and what the headers now say about a unit under its cap.

_HUP, _INT, _QUIT, _PIPE, _TERM = 1, 2, 3, 13, 15


def _ignored(mask_hex):
    """The signal numbers a /proc/<pid>/status SigIgn mask ignores (bit n-1 for signal n)."""
    m = int(mask_hex, 16)
    return {n for n in range(1, 65) if m >> (n - 1) & 1}


def test_the_headers_say_which_signals_the_runner_and_its_harness_ignore_and_what_a_cap_sends():
    """The runner and harness inherit SIGHUP, SIGINT, SIGQUIT and SIGPIPE ignored.
    bash ignores INT and QUIT for a command it starts in the background with no job
    control, and the headers named only PIPE and HUP. remote-ladder.sh's and the library's headers now name all four,
    what that means for a Python child and for a unit under its cap, and that the caps signal with TERM and KILL; the
    README and the two harness headers no longer name two."""
    for p in (REMOTE, LIB):
        with open(p, encoding="utf-8") as f:
            text = _one_paragraph(f.read())
        name = os.path.basename(p)
        assert "SIGPIPE, SIGHUP, SIGINT and SIGQUIT ignored" in text, name
        assert "with no job control" in text, name
        assert "installs no KeyboardInterrupt" in text, name
        assert "only SIGPIPE ignored" in text, name
        assert "TERM and KILL, which are not ignored" in text, name
    gc = os.path.join(REPO, "orin-native", "gpu-concurrency")
    for p in (REMOTE, os.path.join(AWSDIR, "README.md"), os.path.join(gc, "run-vss-setup.sh"),
              os.path.join(gc, "run-vss-suite.sh")):
        with open(p, encoding="utf-8") as f:
            text = _one_paragraph(f.read())
        for stale in ("SIGPIPE and SIGHUP ignored", "ignores SIGPIPE and SIGHUP,", "SIGPIPE and SIGHUP are ignored"):
            assert stale not in text, (p, stale)


# A stub vss harness that records what it, a child of it, and its runner (its parent) ignore, then ends DONE.
_STUB_SIGIGN = r'''#!/usr/bin/env bash
mkdir -p "$OUT"
{ echo "harness $(awk '/^SigIgn/ { print $2 }' /proc/$$/status)"
  grep '^SigIgn' /proc/self/status | awk '{ print "child " $2 }'
  echo "runner $(awk '/^SigIgn/ { print $2 }' /proc/$PPID/status)"
} > "$OUT/sigign.txt"
echo "status=DONE" >> "$STATUS"
'''


@needs_bash
@needs_proc_interrupts
@pytest.mark.skipif(sys.platform == "win32", reason="/proc/<pid>/status SigIgn, as Linux has it")
def test_the_runner_its_harness_and_their_children_ignore_hup_int_quit_and_pipe_and_not_term(tmp_path):
    """The detach rehearsal's finding, in the test rig: the runner the phase starts (the stub setsid execs, so the background start
    and nohup are the phase's own), the harness and a child of the harness each ignore SIGHUP, SIGINT, SIGQUIT and
    SIGPIPE, and none ignores SIGTERM, which a cap sends."""
    w, stub = _vss_w(tmp_path, harness_body=_STUB_SIGIGN)
    r = _vss_phase(w, stub, "harness", _SETUP)
    d = w / "rec" / "vss-setup"
    assert r.returncode == 0 and _wait_for(d / "done"), r.stdout + r.stderr
    got = dict(ln.split() for ln in (d / "raw" / "sigign.txt").read_text().splitlines())
    assert sorted(got) == ["child", "harness", "runner"], got
    for who, mask in got.items():
        ign = _ignored(mask)
        assert {_HUP, _INT, _QUIT, _PIPE} <= ign and _TERM not in ign, (who, mask)


@needs_bash
@pytest.mark.skipif(sys.platform == "win32", reason="Linux's /proc and coreutils timeout, as on the instance")
def test_a_unit_under_its_cap_starts_with_only_sigpipe_of_the_four_ignored(tmp_path):
    """What the headers say of a unit under its cap: GNU timeout catches HUP, INT, QUIT and TERM before it forks, and an
    exec resets a caught signal to its default. From a shell that ignores all four, as the detached runner leaves the
    harness, a command under vss_capped starts with only SIGPIPE of them ignored, and a Python there has its
    KeyboardInterrupt; outside a cap a command keeps all four ignored, and a Python installs none."""
    _write(tmp_path / "deadline", "2500")
    e = dict(os.environ, QNX_METAL_DEADLINE_FILE=str(tmp_path / "deadline"), PY=PY)
    py = "import signal; h = signal.getsignal(signal.SIGINT); print(h is signal.default_int_handler, h == signal.SIG_IGN)"
    body = ('trap "" PIPE HUP INT QUIT; . "$1"; vss_now() { echo 1000; }; vss_deadline_load; '
            'grep "^SigIgn" /proc/self/status | awk "{ print \\"outside\\", \\$2 }"; '
            'vss_capped grep "^SigIgn" /proc/self/status | awk "{ print \\"capped\\", \\$2 }"; '
            'echo "outside-py $("$PY" -c "$2")"; echo "capped-py $(vss_capped "$PY" -c "$2")"')
    r = subprocess.run([BASH, "-c", body, "_", LIB, py], capture_output=True, text=True, timeout=60, env=e)
    assert r.returncode == 0, (r.stdout, r.stderr)
    got = {ln.split(None, 1)[0]: ln.split(None, 1)[1] for ln in r.stdout.splitlines()}
    four = {_HUP, _INT, _QUIT, _PIPE}
    assert four <= _ignored(got["outside"]), got
    assert _ignored(got["capped"]) & (four | {_TERM}) == {_PIPE}, got
    assert got["outside-py"] == "False True" and got["capped-py"] == "True False", got


@needs_bash
@needs_proc_interrupts
@pytest.mark.skipif(sys.platform == "win32", reason="Linux's sessions and process groups, as on the instance")
def test_a_runner_that_did_not_start_is_ended_with_its_whole_process_group(tmp_path):
    """WP6 item 4 (nostart, doublefault): a runner held before its exec, with a child already started, leads its own
    process group under setsid. The phase sent TERM to its pid alone, and the child outlived the phase's failure; the
    phase now sends TERM to the runner's group, then to its pid. The stub setsid makes a session and group as
    util-linux's does from a shell with no job control (no fork, so $! is the leader), then holds the runner."""
    w, stub = _vss_w(tmp_path)
    _stubs(stub, {
        "setsid": 'echo "setsid $*" >> "$STUB_DIR/setsid.log"\n'
                  'exec "%s" -c "import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])" "$STUB_DIR/held" "$@"'
                  % PY,
        "held": 'echo $$ > "$STUB_DIR/group"; sleep 300 & echo $! > "$STUB_DIR/child"; sleep 300; exec "$@"'})
    group = None
    try:
        r = _vss_phase(w, stub, "harness", _SETUP, VSS_START_WAIT_S="1")
        out = r.stdout + r.stderr
        assert r.returncode != 0 and "did not start" in out, out
        assert not (w / "rec" / "vss-setup").exists(), out
        group = int((stub / "group").read_text())
        child = int((stub / "child").read_text())
        end = time.time() + 10
        while time.time() < end and not _gone_or_zombie(child):
            time.sleep(0.1)
        assert _gone_or_zombie(child), "the held runner's child %d outlived the phase's failure" % child
        assert _gone_or_zombie(group), "the held runner %d outlived the phase's failure" % group
    finally:
        if group is not None:
            try:
                os.killpg(group, 9)       # SIGKILL: what the unfixed phase left running
            except ProcessLookupError:
                pass


# Item 1's NIT 2: red() and a sha256 that holds 12 digits in a row. upload prints inputs.txt through red(), and its
# 12-digit rule took any such run between a letter and a letter: the hash printed with a masked digit run.
_SHA12_MID = "ab123456789012cd" + "ef" * 24      # 64 hex characters, exactly 12 digits in a row, inside
_SHA12_HEAD = "123456789012" + "ab" * 26         # at the token's head
_SHA12_TAIL = "ab" * 26 + "123456789012"         # at its tail
_RED_KEPT = ["file bundle.json " + _SHA12_MID, "repo.tar " + _SHA12_HEAD, "disk " + _SHA12_TAIL,
             "ifs ifs-vss.bin %s here" % _SHA12_TAIL, "build123456789012x"]
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
    """NIT 2. A sha256 holding 12 digits in a row printed as ab<account>cd...; a run beside a letter or digit is part
    of a token and stays (want is the line itself), and a standalone run, one beside punctuation, - or _, is still
    masked."""
    r = _sourced("red", stdin=line + "\n")
    assert r.returncode == 0 and r.stdout == want + "\n", (r.stdout, r.stderr)


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
@pytest.mark.parametrize("line", _RED_KEPT + [m for m, _ in _RED_MASKED])
def test_red_and_the_redactor_agree_on_a_12_digit_run_inside_a_token_and_on_a_standalone_one(awk, line):
    """red() and redact-aws.sh keep the same 12-digit runs inside a token and mask the same standalone ones."""
    r = _sourced("red", stdin=line + "\n")
    assert r.returncode == 0 and r.stdout == _redacted(line + "\n", awk), (r.stdout, line)


# --------------------------------------------------------------------------
# SDV Phase 6 WP6: run-ota-drill.sh, the OTA drill's harness, in the harness phase, wait-run,
# the session marker, the capture's whitelist and the capture phase's gate. A stub stands in for the harness, as for the
# two vss harnesses above; tests/test_ota_drill_harness.py runs the real one. Documentation values only.

_DRILL = "HARNESS=run-ota-drill.sh"


def _drill_w(tmp_path, harness_body=_STUB_VSS, drill=True, **kw):
    """W as _vss_w lays it, with the drill's stub harness beside the two and the tarball's sdv/drill/drill.py."""
    w, stub = _vss_w(tmp_path, harness_body=harness_body, **kw)
    _write(w / "repo" / "orin-native" / "gpu-concurrency" / "run-ota-drill.sh", harness_body, newline=False)
    if drill:
        _write(w / "repo" / "sdv" / "drill" / "drill.py", "# stand-in")
    return w, stub


@needs_bash
@pytest.mark.parametrize("words,k,msg", [
    (_DRILL + " IMAGE=ifs-vss.bin", None, "run-ota-drill.sh takes no IMAGE word: it boots no image"),
    (_DRILL + " PLAN=v1", None, "run-ota-drill.sh takes no PLAN word (only run-vss-suite.sh does)"),
    (_DRILL + " PLAN=carla", None, "run-ota-drill.sh takes no PLAN word (only run-vss-suite.sh does)"),
    (_DRILL, "4", "run-ota-drill.sh takes no K"),
    (_DRILL + " IMG_B=ifs-vss.bin", None, "run-ota-drill.sh takes no IMG_B word (it boots no image)"),
    (_DRILL + " IMG_UA=ifs-bell.bin", None, "run-ota-drill.sh takes no IMG_UA word (it boots no image)"),
    (_DRILL + " IMG_S=ifs-vss.bin", None, "the harness phase passes only IMG_B, IMG_R, IMG_UA and IMG_UB"),
    (_DRILL + " VSS_HOST=orin", None, "VSS_HOST=orin is not a bare-metal AWS host: a1-metal or c7g-metal"),
    (_DRILL + " VSS_HOST=c7g.metal", None, "VSS_HOST=c7g.metal is not a bare-metal AWS host: a1-metal or c7g-metal"),
    (_DRILL + " VSS_HOST=c7g-metal VSS_HOST=c7g-metal", None, "LADDER_ENV names VSS_HOST twice"),
    (_DRILL + " SHM=1", None, "is not one the harness phase reads"),
    (_DRILL + " " + _DRILL, None, "LADDER_ENV names HARNESS twice"),
])
def test_the_harness_phase_holds_the_drill_to_its_words_before_making_anything(tmp_path, words, k, msg):
    """The drill takes VSS_HOST= (a1-metal or c7g-metal) and nothing else; no IMAGE=, PLAN=, K
    or IMG_ word. Each refusal comes before the session marker and the stem directory."""
    w, stub = _drill_w(tmp_path)
    _setup_done(w)
    r = _vss_phase(w, stub, "harness", words, **({} if k is None else {"K": k}))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and msg in out, out
    assert sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt", "vss-setup"], "refused before anything was made"
    assert not (w / "vss-session").exists() and not (stub / "setsid.log").exists()


@needs_bash
@pytest.mark.parametrize("setup", [
    None,
    dict(lines=None, done=False),
    dict(lines=["status=DONE"], done=False),
    dict(lines=["status=TIMEOUT at=30min-rule reason=30min-rule"], done=True),
    dict(lines=["status=FAILED rc=1"], done=True),
    dict(lines=["status=DONE", "status=FAILED rc=0"], done=True),
], ids=["no-setup", "running", "done-line-no-done", "timeout-30min-rule", "failed", "done-then-failed"])
def test_the_drill_needs_a_finished_setup_whose_last_status_line_is_done(tmp_path, setup):
    """Refused unless setup is DONE, as the suite is, before the marker and the stem."""
    w, stub = _drill_w(tmp_path)
    if setup is not None:
        _laid(w, **setup)
    r = _vss_phase(w, stub, "harness", _DRILL)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "run-ota-drill.sh needs a finished run-vss-setup.sh" in out, out
    assert not (w / "vss-session").exists() and not (w / "rec" / "ota-drill").exists()
    assert not (stub / "setsid.log").exists()


@needs_bash
def test_the_drill_needs_the_drill_in_the_tarball(tmp_path):
    w, stub = _drill_w(tmp_path, drill=False)
    _setup_done(w)
    r = _vss_phase(w, stub, "harness", _DRILL)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "the repo tarball lacks sdv/drill/drill.py" in out, out
    assert not (w / "vss-session").exists() and not (w / "rec" / "ota-drill").exists()


@needs_bash
@pytest.mark.parametrize("words,missing,msg", [
    (_DRILL, "step3", "the repo tarball lacks sdv/stack/step3.py"),
    (_DRILL, "lib", "the repo tarball lacks lib-vss-deadline.sh"),
    (_DRILL, "quiesce", "run quiesce first"),
])
def test_the_drill_needs_the_vss_tarball_and_the_quiesce_record(tmp_path, words, missing, msg):
    w, stub = _drill_w(tmp_path, **{missing: False})
    r = _vss_phase(w, stub, "harness", words)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and msg in out, out
    assert not (w / "vss-session").exists() and not (w / "rec" / "ota-drill").exists()


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("setup_word,drill_word", [("c7g-metal", None), ("c7g-metal", "a1-metal"), (None, "c7g-metal"),
                                                   ("a1-metal", "c7g-metal")])
def test_the_drill_is_refused_unless_its_vss_host_is_the_setups_before_anything_is_made(tmp_path, setup_word, drill_word):
    """A drill of another host mode than its setup would spend its one run on its preflight's refusal: the phase refuses
    it first. No word is a1-metal, either side."""
    w, stub = _drill_w(tmp_path)
    r = _vss_phase(w, stub, "harness", _SETUP + ("" if setup_word is None else " VSS_HOST=" + setup_word),
                   STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    r = _vss_phase(w, stub, "harness", _DRILL + ("" if drill_word is None else " VSS_HOST=" + drill_word))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "run-ota-drill.sh needs the VSS_HOST run-vss-setup.sh ran with" in out, out
    assert "(%s)" % (setup_word or "a1-metal") in out and "VSS_HOST=%s" % (drill_word or "a1-metal") in out, out
    assert sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt", "vss-setup"], "refused before the drill's stem was made"
    assert "run-ota-drill.sh" not in (w / "vss-session").read_text()


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("word", [None, "a1-metal", "c7g-metal"], ids=["no-word", "a1-metal", "c7g-metal"])
def test_the_drill_runs_detached_into_its_stem_once_per_session_with_its_host_mode(tmp_path, word):
    """run-ota-drill.sh joins the vss harnesses: the marker, the stem rec/ota-drill and its
    host-before.txt, the detached runner, host-after.txt for DONE, done; its VSS_HOST as setup's; no PLAN and no K. A
    second run is refused."""
    w, stub = _drill_w(tmp_path)
    tail = "" if word is None else " VSS_HOST=" + word
    r = _vss_phase(w, stub, "harness", _SETUP + tail, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    r = _vss_phase(w, stub, "harness", _DRILL + tail, STUB_STATUS_LINE="status=DONE")
    d = w / "rec" / "ota-drill"
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "started run-ota-drill.sh, detached, into" in out, out
    assert _wait_for(d / "done"), out
    assert "run-ota-drill.sh" in (w / "vss-session").read_text()
    log = (stub / "setsid.log").read_text()
    assert re.search(r"^setsid nohup bash \S*remote-ladder\.sh _detached ota-drill run-ota-drill\.sh$", log, re.M), log
    env = _env_of(d)
    assert env["PLAN"] == "" and env["K"] == "" and env["VSS_HOST"] == (word or "<unset>"), env
    assert (env["VSS_IN"], env["VSS_HOME"], env["STATUS"], env["OUT"]) == (
        str(w / "in"), str(w / "sdv"), str(d / "status"), str(d / "raw")), env
    assert env["DRILL_IN"] == str(w / "drill-in"), "the drill's files, which setup moved out of in/"
    assert (d / "host-before.txt").exists() and (d / "host-after.txt").exists() and (d / "run.log").exists()
    assert (d / "status").read_text().splitlines() == ["status=DONE"]
    r = _vss_phase(w, stub, "harness", _DRILL + tail)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "exists: one ota-drill run per session" in out, out


@needs_bash
@needs_proc_interrupts
def test_after_the_drill_every_a6_harness_refuses_and_the_suite_still_runs(tmp_path):
    """The session marker applies to the drill as to the others, and its stem is no A6 record: the suite after it is not
    refused for one."""
    w, stub = _drill_w(tmp_path)
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    (w / "vss-session").unlink()                                     # only the drill's start may write it now
    r = _vss_phase(w, stub, "harness", _DRILL, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "ota-drill" / "done"), r.stdout + r.stderr
    assert (w / "vss-session").read_text().startswith("run-ota-drill.sh ")
    for h in _A6_HARNESSES[:3]:
        _write(w / "repo" / "orin-native" / "gpu-concurrency" / h, "exit 0")
        r = _vss_phase(w, stub, "harness", "HARNESS=%s IMAGE=ifs-bell.bin" % h)
        assert r.returncode != 0 and "vss-session exists" in r.stdout + r.stderr, (h, r.stdout + r.stderr)
    r = _vss_phase(w, stub, "harness", _SUITE, STUB_STATUS_LINE="status=DONE")
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "holds an A6 record" not in out and _wait_for(w / "rec" / "vss-suite" / "done"), out


@needs_bash
@pytest.mark.parametrize("a6", ["bell", "ladder"])
def test_the_drill_is_refused_while_rec_holds_an_a6_record(tmp_path, a6):
    w, stub = _drill_w(tmp_path)
    _setup_done(w)
    _write(w / "rec" / a6 / "run.log", "an A6 harness ran here")
    r = _vss_phase(w, stub, "harness", _DRILL)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "holds an A6 record (%s)" % a6 in out, out
    assert not (w / "vss-session").exists() and not (w / "rec" / "ota-drill").exists()


@needs_bash
@needs_proc_interrupts
def test_wait_run_waits_for_the_drill_and_prints_its_status(tmp_path):
    w, stub = _drill_w(tmp_path)
    _setup_done(w)
    release = tmp_path / "release"
    r = _vss_phase(w, stub, "harness", _DRILL, STUB_RELEASE=release, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0, r.stdout + r.stderr
    p = _vss_phase(w, stub, "wait-run", _DRILL, popen=True)
    try:
        time.sleep(1.0)
        assert p.poll() is None, "wait-run returned while the drill still ran"
        release.touch()
        out, _ = p.communicate(timeout=30)
    finally:
        p.kill()
    assert p.returncode == 0 and "status=DONE" in out and "done: yes" in out, out


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("first,then,running", [(_SUITE, _DRILL, "vss-suite"), (_DRILL, _SUITE, "ota-drill")],
                         ids=["suite-running-then-drill", "drill-running-then-suite"])
def test_the_suite_and_the_drill_each_refuse_to_start_while_the_other_still_runs(tmp_path, first, then, running):
    """Both need only a setup that ended DONE, so either could start while the other still runs detached: they would share
    this host's Docker and the stack, and each would likely spend its one run. The phase refuses the second, naming the
    stem that has no done yet, before it makes anything; once that one is done, the second starts."""
    w, stub = _drill_w(tmp_path)
    r = _vss_phase(w, stub, "harness", _SETUP, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    release = tmp_path / "release"
    r = _vss_phase(w, stub, "harness", first, STUB_RELEASE=release, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0, r.stdout + r.stderr
    h = then.split()[0][len("HARNESS="):]
    stem = "ota-drill" if running == "vss-suite" else "vss-suite"
    try:
        r = _vss_phase(w, stub, "harness", then)
        out = r.stdout + r.stderr
        refused_while_running = not (w / "rec" / running / "done").exists()
    finally:
        release.touch()
    assert refused_while_running, "the first harness ended before the second was asked: " + out
    assert r.returncode != 0 and "%s is refused while %s still runs (%s has no done)" % (h, running, w / "rec" / running) in out, out
    assert not (w / "rec" / stem).exists() and h not in (w / "vss-session").read_text(), "refused before anything was made"
    assert _wait_for(w / "rec" / running / "done")
    r = _vss_phase(w, stub, "harness", then, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / stem / "done"), r.stdout + r.stderr


# The calls of the two existing vss harnesses, as the harness phase makes them, held whole: every variable it gives
# either one, for no word, a1-metal and c7g-metal (none of them changed by the drill).
_STUB_ENV = r'''#!/usr/bin/env bash
mkdir -p "$OUT"
for v in W IMG_S IMG_B IFS_BIN DISK VPROBE OUT CSTATE PLAN VSS_HOST VSS_IN DRILL_IN VSS_HOME STATUS K LADDER_ENV IMAGE HARNESS; do
  if [ -n "${!v+x}" ]; then printf '%s=%s\n' "$v" "${!v}"; fi
done > "$OUT/env-all.txt"
echo "status=DONE" >> "$STATUS"
'''


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("word", [None, "a1-metal", "c7g-metal"], ids=["no-word", "a1-metal", "c7g-metal"])
def test_the_two_vss_harnesses_get_exactly_the_environment_they_got_before_the_drill(tmp_path, word):
    w, stub = _drill_w(tmp_path, harness_body=_STUB_ENV)
    tail = "" if word is None else " VSS_HOST=" + word
    img = str(w / "img" / "ifs-vss.bin")
    for words, stem, plan in ((_SETUP, "vss-setup", None), ("HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v2", "vss-suite", "v2")):
        r = _vss_phase(w, stub, "harness", words + tail)
        d = w / "rec" / stem
        assert r.returncode == 0 and _wait_for(d / "done"), r.stdout + r.stderr
        got = dict(ln.split("=", 1) for ln in (d / "raw" / "env-all.txt").read_text().splitlines())
        want = {"W": str(w), "IMG_S": img, "IMG_B": img, "IFS_BIN": img, "DISK": str(w / "img" / "disk-qemu"),
                "VPROBE": str(w / "vsomeip" / "3.4.10" / "bin" / "someip_vprobe"), "OUT": str(d / "raw"), "CSTATE": "shallow",
                "VSS_IN": str(w / "in"), "VSS_HOME": str(w / "sdv"), "STATUS": str(d / "status"),
                "LADDER_ENV": words + tail}
        if plan:
            want["PLAN"] = plan
        if word:
            want["VSS_HOST"] = word
        assert got == want, (stem, got)
        log = (stub / "setsid.log").read_text()
        assert re.search(r"^setsid nohup bash \S*remote-ladder\.sh _detached %s run-%s\.sh$" % (stem, stem), log, re.M), log


# capture.py and an ota-drill stem: the whitelist gains exactly the drill's record under
# ota-drill/raw/ and the stem's run.log, status, host-before.txt and host-after.txt; the stem is evidence by the vss rules.

_DRILL_RESULT = {"format": 1, "host_role": "c7g-metal", "arch": "arm64", "transport": "tar", "via": "spool", "repo_commit": None,
                 "manifest_sha256": "sha256:" + "ab" * 32,
                 "steps": [{"n": 1, "asks": "image v1", "app_version": "1.0.0", "scenario": None, "result": "applied",
                            "refused_step": None, "rollback": False, "waited_s": 4}], "verdict": "ok", "problems": []}
_DRILL_RAW = ["drill-result.json", "ota-lite.jsonl", "state.json", "status-1.json", "status-6.json", "manifest.json",
              "venv.txt"]


def _drill_stem(rec, status=("status=DONE",), done=True, result=True, after=True):
    """rec/ota-drill as the harness phase, the detached runner and run-ota-drill.sh leave it, with one file of the stem
    and one of raw/ that are on no whitelist."""
    d = rec / "ota-drill"
    _write(d / "host-before.txt", _QUIESCE_REC + "2026-10-20T05:00:00Z\n0.10 0.20 0.30 1/200 4022", newline=False)
    _write(d / "run.log", "[05:00:01] unit load: start\nfetched from 203.0.113.7")
    _write(d / "detach.log", "[05:00:00] _detached: run-ota-drill.sh starts")
    if status is not None:
        _write(d / "status", "\n".join(status), newline=bool(status))
    if after:
        _write(d / "host-after.txt", "2026-10-20T05:40:00Z")
    raw = d / "raw"
    if result:
        _write(raw / "drill.json", json.dumps({"harness": "run-ota-drill.sh", "status": status[-1][len("status="):]
                                               if status else ""}), newline=False)
    _write(raw / "drill-result.json", json.dumps(_DRILL_RESULT), newline=False)
    _write(raw / "ota-lite.jsonl", '{"event":"updater-start","host_role":"c7g-metal","t":%d}\n{"event":"updater-stop"}\n'
           % _T12, newline=False)
    for n in ("state.json", "status-1.json", "status-6.json"):
        _write(raw / n, json.dumps({"image_id": "sha256:" + "cd" * 32, "scenario": None, "result": "applied"}), newline=False)
    _write(raw / "manifest.json", json.dumps({"host_role": "c7g-metal", "app": "external"}), newline=False)
    _write(raw / "venv.txt", "== ota-venv/bin/python --version\nPython 3.12.14\nkuksa-client==0.6.0")
    _write(raw / "manifest-ota.json", json.dumps({"tar_path": "/home/ubuntu/a1/in/sdv-drill.tar"}), newline=False)
    (raw / "pip-cache").mkdir()
    _write(raw / "pip-cache" / "x.whl.txt", "a cache entry")
    if done:
        (d / "done").touch()
    return d


_DRILL_PUBLISHED = sorted(["ota-drill/" + n for n in ("host-before.txt", "host-after.txt", "run.log", "status")]
                          + ["ota-drill/raw/" + n for n in _DRILL_RAW + ["drill.json"]])
_DRILL_NEVER = ["ota-drill/detach.log", "ota-drill/done", "ota-drill/raw/manifest-ota.json", "ota-drill/raw/pip-cache/x.whl.txt"]


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
def test_capture_takes_an_ota_drill_stem_by_exactly_its_whitelist(tmp_path, awk):
    rec = _small_vss(tmp_path, {"vss-setup": {}})
    _drill_stem(rec)
    pub = tmp_path / "pub"
    r = _vss_capture(rec, pub, AWK=awk)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    got = [p for p in _published(pub) if p.startswith("ota-drill/")]
    assert got == _DRILL_PUBLISHED, got
    report = (pub / "capture.log").read_text(encoding="utf-8")
    for rel in _DRILL_NEVER:
        assert "excluded: %s " % rel in r.stdout and "excluded: %s " % rel in report, (rel, r.stdout)
    assert "capture: a vss record (ota-drill vss-setup)" in report, report
    assert "ota-drill: DONE (status=DONE, with raw/drill.json)" in report, report
    # the JSON rule: no string changed, so byte for byte, the 12-digit count included; the text rule on run.log
    for rel in ("raw/drill-result.json", "raw/ota-lite.jsonl", "raw/state.json"):
        assert (pub / "ota-drill" / rel).read_bytes() == (rec / "ota-drill" / rel).read_bytes(), rel
    assert b"203.0.113.7" not in (pub / "ota-drill" / "run.log").read_bytes()
    assert _leakscan(pub).returncode == 0


@needs_bash
def test_capture_does_not_take_a_stem_named_like_the_drill_for_the_drill(tmp_path):
    """The drill's stem is exactly `ota-drill`: an `ota-drill2` beside it (a leftover copy, a second run's directory) is no
    vss stem. Its files are on no whitelist, so each is named as excluded, nothing of it is published, and no evidence line
    is written for it."""
    rec = _small_vss(tmp_path, {"vss-setup": {}})
    _drill_stem(rec)
    shutil.copytree(str(rec / "ota-drill"), str(rec / "ota-drill2"))
    pub = tmp_path / "pub"
    r = _vss_capture(rec, pub)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    published = _published(pub)
    assert [p for p in published if p.startswith("ota-drill/")] == _DRILL_PUBLISHED, published
    assert not [p for p in published if p.startswith("ota-drill2")], published
    for rel in ("run.log", "status", "host-before.txt", "raw/drill-result.json", "raw/drill.json"):
        assert "excluded: ota-drill2/%s " % rel in out, (rel, out)
    assert "ota-drill2:" not in out and "ota-drill: DONE (status=DONE, with raw/drill.json)" in out, out


@needs_bash
@pytest.mark.parametrize("stems,drill,incomplete,ok,marks", [
    ({"vss-setup": {}}, {}, "", True, ["ota-drill: DONE"]),
    ({"vss-setup": {}}, dict(status=["status=TIMEOUT at=drill reason=step-timeout"], result=False), "", True,
     ["ota-drill: TIMEOUT (status=TIMEOUT at=drill reason=step-timeout, but no raw/drill.json"]),
    ({"vss-setup": {}}, dict(status=["status=FAILED at=preflight", "status=FAILED rc=1"], after=False), "", True,
     ["ota-drill: FAILED (status=FAILED rc=1, after the harness's own status=FAILED at=preflight"]),
    ({"vss-setup": {}}, dict(status=None, done=False, result=False, after=False), "", False, ["ota-drill has no done"]),
    ({"vss-setup": {}}, dict(status=None, done=False, result=False, after=False), "ota-drill", True,
     ["ota-drill: INCOMPLETE"]),
    ({}, dict(result=False), "", False, ["ota-drill: DONE (status=DONE, but no raw/drill.json: not evidence)", "nothing ran"]),
    ({}, {}, "", True, ["capture: a vss record (ota-drill)", "ota-drill: DONE"]),
    ({}, dict(status=[], after=False), "", False, ["ota-drill: NO STATUS"]),
], ids=["done", "timeout-no-result", "failed", "running", "incomplete", "done-no-result", "alone", "no-status"])
def test_capture_holds_an_ota_drill_stem_to_the_vss_evidence_rules(tmp_path, stems, drill, incomplete, ok, marks):
    rec = _small_vss(tmp_path, stems)
    _drill_stem(rec, **drill)
    r = _vss_capture(rec, tmp_path / "pub", CAPTURE_INCOMPLETE=incomplete)
    out = r.stdout + r.stderr
    assert (r.returncode == 0) is ok, out
    for m in marks:
        assert m in out, (m, out)
    if ok:
        assert (tmp_path / "pub" / "ota-drill" / "run.log").exists()
        assert not (tmp_path / "pub" / "ota-drill" / "detach.log").exists()


@needs_bash
@pytest.mark.parametrize("ahead_min,packed", [(80, False), (12, True)])
def test_the_capture_phase_refuses_a_drill_without_done_until_the_give_up_point(tmp_path, ahead_min, packed):
    w, stub = _capture_w(tmp_path, ahead_min=ahead_min)
    _vss_stem(w / "rec", "vss-setup")
    _drill_stem(w / "rec", status=None, done=False, result=False, after=False)
    r = _gate(w, stub)
    out = r.stdout + r.stderr
    if not packed:
        assert r.returncode != 0 and "ota-drill has no done" in out, out
        assert not (w / "pub.tgz").exists() and not (w / "capture.log").exists(), "refused before capture.py ran"
    else:
        assert r.returncode == 0 and "ota-drill: INCOMPLETE" in out, out
        assert (w / "pub" / "ota-drill" / "run.log").exists() and (w / "pub.tgz").exists()


@needs_bash
def test_the_capture_phase_takes_a_finished_drill_and_prints_its_line(tmp_path):
    w, stub = _capture_w(tmp_path)
    _vss_stem(w / "rec", "vss-setup")
    _drill_stem(w / "rec")
    r = _gate(w, stub)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "captured" in out, out
    assert re.search(r"^ota-drill: DONE ", out, re.M) and re.search(r"^vss-setup: DONE ", out, re.M), out
    assert (w / "pub" / "ota-drill" / "raw" / "drill-result.json").exists()


# --------------------------------------------------------------------------
# SDV Phase 7 WP6-T: a bare-metal session's minutes as a launch option. `launch` alone
# reads METAL_SESSION_MIN (unset or empty: 90; else a whole number from 60 to 180 in plain digits), sends userdata.sh
# with its one line MIN=90 made MIN=N and records N in the state as session_min; `wait` judges both nets by the state's
# minutes, never the environment's, and a state without them by 90. The rig's stub aws keeps the user-data as sent
# (userdata.sent) and, with STUB_WATCH, how many rendered copies the state held at each call (watch.log).


USERDATA_BYTES = open(USERDATA, "rb").read()
_SESSION_REFUSED = ["59", "181", "090", "+90", "9 0", "abc", "1e2", "0", "-90", " 90", "90 ", "60.0", "1800", "6O"]


def _rendered_as(minutes):
    """userdata.sh as a session of so many minutes sends it: its one line MIN=90 made MIN=<minutes>."""
    assert USERDATA_BYTES.count(b"\nMIN=90\n") == 1
    return USERDATA_BYTES.replace(b"\nMIN=90\n", b"\nMIN=%s\n" % str(minutes).encode())


def _left_in_state(state):
    """What a launch left in the session state: nothing at all, for a refusal."""
    return sorted(os.listdir(str(state))) if state.exists() else []


def _watched(stub):
    """(rendered copies in the state, ec2 call) at each aws call, in order (the stub's STUB_WATCH log)."""
    return [tuple(ln.split(" ", 1)) for ln in (stub / "watch.log").read_text(encoding="utf-8").splitlines()]


def _gone_once_sent(stub):
    """The rendered user-data was in the state when run-instances read it, and at no aws call after it returned."""
    calls = _watched(stub)
    at = [i for i, (_, call) in enumerate(calls) if call == "run-instances"]
    assert len(at) == 1 and calls[at[0]][0] == "1", calls
    assert all(n == "0" for n, _ in calls[at[0] + 1:]), calls


def _nets(tmp_path, wall_min, mono_s, name="nets.txt", up=180):
    """`wait`'s one read of an instance whose wall-clock poweroff is wall_min minutes ahead and whose monotonic timer has
    mono_s seconds left, the two marks and the per-boot script there."""
    now = 1_790_000_000
    at = up + mono_s
    span = " ".join(t for t, n in (("%dh" % (at // 3600), at // 3600), ("%dmin" % (at % 3600 // 60), at % 3600 // 60),
                                   ("%ds" % (at % 60), at % 60)) if n)
    f = tmp_path / name
    _write(f, "ARMED_FILE=yes\nPERBOOT=yes\nUSEC=%d\nWARN_WALL=1\nMODE=poweroff\nNOW=%d\nActiveState=active\n"
              "NextElapseUSecMonotonic=%s\nUPTIME=%d" % ((now + wall_min * 60) * 1_000_000, now, span, up))
    return f


def _abort_line(r):
    lines = [ln for ln in r.stdout.splitlines() if "ABORT: " in ln]
    assert len(lines) == 1, r.stdout + r.stderr
    return lines[0]


@needs_bash
@pytest.mark.parametrize("given,ok", [(v, True) for v in ("60", "61", "89", "90", "99", "100", "119", "150", "179", "180")]
                         + [(v, False) for v in _SESSION_REFUSED + [""]])
def test_session_min_ok_takes_a_whole_number_from_60_to_180_in_plain_digits_and_nothing_else(given, ok):
    r = _sourced('if session_min_ok "$GIVEN"; then echo ok; else echo refused; fi', env={"GIVEN": given})
    assert r.stderr == "" and r.stdout.split() == ["ok" if ok else "refused"], r.stdout + r.stderr


# A userdata.sh with every near miss of the one line: a comment, an indented line, lines that start with MIN, a CRLF line,
# and no newline at the end. The rule changes the exact line MIN=90 and leaves every other byte.
_UD_NEAR = (b"#!/bin/bash\n# MIN=90 in a comment\nMIN_X=1\nMIN=900\nMINUTES=90\n  MIN=90\nMIN=90\nMAX=$MIN\n"
            b"a crlf line\r\nMIN=90x\nno newline at the end")


def _render(tmp_path, src, minutes):
    f = tmp_path / "userdata.src"
    f.write_bytes(src)
    out = tmp_path / "userdata.out"
    r = _sourced('if render_userdata "$SRC" "$N" "$OUT"; then echo rendered; else echo refused; fi',
                 env={"SRC": _posix(f), "N": minutes, "OUT": _posix(out)})
    return r, out


@needs_bash
@pytest.mark.parametrize("which,minutes", [("userdata.sh", "90"), ("userdata.sh", "150"), ("userdata.sh", "60"),
                                           ("userdata.sh", "180"), ("near", "90"), ("near", "150")])
def test_the_user_data_is_userdata_sh_with_its_one_min_90_line_made_min_n_and_every_other_byte_as_it_is(tmp_path, which, minutes):
    src = USERDATA_BYTES if which == "userdata.sh" else _UD_NEAR
    r, out = _render(tmp_path, src, minutes)
    assert r.stderr == "" and r.stdout.split() == ["rendered"], r.stdout + r.stderr
    got = out.read_bytes()
    assert got == src.replace(b"\nMIN=90\n", b"\nMIN=%s\n" % minutes.encode()), got[-200:]
    changed = [(a, b) for a, b in zip(src.split(b"\n"), got.split(b"\n")) if a != b]
    assert changed == ([] if minutes == "90" else [(b"MIN=90", b"MIN=" + minutes.encode())]), changed
    assert len(got.split(b"\n")) == len(src.split(b"\n"))
    if minutes == "90":
        assert got == src, "the default renders the source's own bytes"


@needs_bash
@pytest.mark.parametrize("src", [b"#!/bin/bash\nMIN=91\n", b"MIN=90 \n", b"  MIN=90\n", b"# MIN=90\n", b"MIN=090\n", b"",
                                 b"MIN=90\r\n", b"MIN=90\nMIN=90\n", b"MIN=90\nx\nMIN=90", USERDATA_BYTES + b"MIN=90\n"],
                         ids=["other", "spaced", "indented", "comment", "zero", "empty", "crlf", "two", "two-last-unended",
                              "userdata-two"])
def test_a_userdata_without_exactly_one_min_90_line_is_not_rendered_and_nothing_is_written(tmp_path, src):
    r, out = _render(tmp_path, src, "150")
    assert r.stderr == "" and r.stdout.split() == ["refused"], r.stdout + r.stderr
    assert not out.exists()


@needs_bash
@pytest.mark.parametrize("held,want", [(None, "90"), ("150\n", "150"), ("90\n", "90"), ("60\n", "60"), ("180", "180"),
                                       ("", None), ("\n", None), ("abc\n", None), ("090\n", None), ("150\r\n", None),
                                       ("59\n", None), ("181\n", None), ("1 50\n", None), ("150\n150\n", None),
                                       ("150\n\n", None)])
def test_a_later_step_reads_the_minutes_from_the_state_and_90_from_a_state_without_them(tmp_path, held, want):
    state = tmp_path / "state"
    state.mkdir()
    if held is not None:
        (state / "session_min").write_bytes(held.encode())
    r = _sourced('if session_min_of; then echo " rc=0"; else echo "rc=1"; fi',
                 env={"METAL_STATE": str(state), "METAL_SESSION_MIN": "120", "SHUTDOWN_MIN_EXPECTED": "120"})
    assert r.stderr == "", r.stderr
    assert r.stdout.split() == ([want, "rc=0"] if want is not None else ["rc=1"]), r.stdout


@needs_bash
def test_a_session_min_that_cannot_be_read_as_a_file_fails_without_cats_complaint_naming_the_state_path(tmp_path):
    """A session_min that is a directory: cat's own error would name the state's path, which red() holds back from the
    transcript. The function says nothing; the abort line of the step that called it says what was wrong."""
    state = tmp_path / "state"
    (state / "session_min").mkdir(parents=True)
    r = _sourced('if session_min_of; then echo " rc=0"; else echo "rc=1"; fi', env={"METAL_STATE": str(state)})
    assert r.stderr == "" and r.stdout.split() == ["rc=1"], r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("given", _SESSION_REFUSED)
def test_launch_refuses_a_metal_session_min_outside_60_to_180_before_any_aws_call_and_writes_nothing(rig, tmp_path, given):
    run, state, stub = rig
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    r, log = run("launch", METAL_SESSION_MIN=given, TMPDIR=_posix(tmp))
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "METAL_SESSION_MIN" in out and "from 60 to 180" in out, out
    assert log == "" and not [p for p in ("aws.log", "ssh.log", "scp.log") if (stub / p).exists()], "no aws call: " + log
    assert _left_in_state(state) == [] and os.listdir(str(tmp)) == [], (_left_in_state(state), os.listdir(str(tmp)))


@needs_bash
@pytest.mark.parametrize("how,ok", [("as-is", True), ("none", False), ("other", False), ("two", False), ("spaced", False)])
def test_launch_refuses_a_userdata_sh_without_exactly_one_min_90_line_before_any_aws_call(rig, tmp_path, how, ok):
    """A copy of the driver beside a copy of userdata.sh: as it is, the launch goes on; without the one line the minutes
    go into, it is refused before any aws call, with nothing left in the state."""
    run, state, stub = rig
    d = tmp_path / "aws"
    d.mkdir()
    shutil.copy(DRIVER, str(d / "drive-metal.sh"))
    body = {"as-is": USERDATA_BYTES, "none": USERDATA_BYTES.replace(b"\nMIN=90\n", b"\n"),
            "other": _rendered_as(120), "two": USERDATA_BYTES + b"MIN=90\n",
            "spaced": USERDATA_BYTES.replace(b"\nMIN=90\n", b"\nMIN=90 \n")}[how]
    (d / "userdata.sh").write_bytes(body)
    state.mkdir(parents=True)          # outside any repository, outside_repo returns before it makes the directory
    r, log = run("launch", driver=str(d / "drive-metal.sh"), METAL_SESSION_MIN="150")
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0 and (stub / "userdata.sent").read_bytes() == _rendered_as(150), out
        return
    assert r.returncode != 0 and "userdata.sh" in out and "MIN=90" in out, out
    assert log == "" and not (stub / "aws.log").exists(), "no aws call: " + log
    assert _left_in_state(state) == [], _left_in_state(state)


@needs_bash
@pytest.mark.parametrize("given,minutes", [(None, 90), ("", 90), ("90", 90), ("150", 150), ("60", 60), ("180", 180)])
def test_launch_sends_userdata_sh_with_the_sessions_minutes_records_them_and_says_them(rig, monkeypatch, given, minutes):
    """The default (unset, empty or 90) sends userdata.sh's own bytes; another number differs from it in the MIN= line
    alone. The minutes are one line of the state, the launch says them once, and the rendered copy, outside the
    repository, was there when run-instances read it and gone at every aws call after it."""
    monkeypatch.delenv("METAL_SESSION_MIN", raising=False)
    run, state, stub = rig
    r, log = run("launch", STUB_WATCH="1", **({} if given is None else {"METAL_SESSION_MIN": given}))
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "terminate-instances" not in log, out
    sent = (stub / "userdata.sent").read_bytes()
    assert sent == _rendered_as(minutes), sent[-200:]
    assert (sent == USERDATA_BYTES) is (minutes == 90), "only the default sends userdata.sh's own bytes"
    assert (state / "session_min").read_bytes() == b"%d\n" % minutes
    assert (stub / "session_min.at_run").read_bytes() == b"%d\n" % minutes, "recorded before run-instances"
    said = [ln for ln in r.stdout.splitlines() if "session minutes:" in ln]
    want = "session minutes: %d" % minutes + ("" if minutes == 90 else " (not the default 90)")
    assert len(said) == 1 and said[0].split("] ", 1)[1] == want and "session minutes:" not in r.stderr, out
    asked = [ln for ln in log.splitlines() if "run-instances" in ln]
    url = re.search(r"--user-data file://(\S+) ", asked[0]).group(1)
    assert not os.path.normcase(os.path.abspath(url)).startswith(os.path.normcase(REPO) + os.sep), url
    assert not [f for f in os.listdir(str(state)) if f.startswith("userdata")], os.listdir(str(state))
    _gone_once_sent(stub)


@needs_bash
@pytest.mark.parametrize("started", [False, True], ids=["nothing-started", "an-instance-started"])
def test_a_failed_run_instances_removes_the_rendered_user_data_at_once_and_leaves_no_minutes_for_nothing(rig, monkeypatch,
                                                                                                         started):
    """Whatever run-instances did, the rendered copy goes as soon as it returns. With no instance the state is left clean,
    the minutes gone with the token, so the next launch goes on; with one, its minutes stay with it. The second launch
    gives no minutes, so it is the default's whatever the shell that runs the tests exports."""
    monkeypatch.delenv("METAL_SESSION_MIN", raising=False)
    run, state, stub = rig
    r, log = run("launch", STUB_RUN_FAIL=1, STUB_WATCH="1", METAL_SESSION_MIN="150",
                 **({"STUB_TOKEN_ID": "i-0123456789abcdef0"} if started else {}))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "client-token" in log, out
    assert (stub / "userdata.sent").read_bytes() == _rendered_as(150)
    _gone_once_sent(stub)
    assert not [f for f in os.listdir(str(state)) if f.startswith("userdata")], os.listdir(str(state))
    if started:
        assert "terminate-instances" in log and (state / "terminated").exists(), out
        assert (state / "session_min").read_bytes() == b"150\n"
        return
    assert "no instance carries this launch's token" in out, out
    assert not (state / "session_min").exists() and not (state / "token").exists(), _left_in_state(state)
    r, log = run("launch")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (state / "session_min").read_bytes() == b"90\n"


@needs_bash
@pytest.mark.parametrize("case", ["held", "running"])
def test_launch_refuses_a_state_holding_session_min_and_a_live_region_leaving_no_minutes_or_user_data(rig, tmp_path, case):
    """session_min is session state, as type is: a state that holds one is not clean. The region's check, the one
    refusal made after an aws call, leaves neither the minutes nor a rendered copy."""
    run, state, stub = rig
    if case == "held":
        state.mkdir(parents=True)
        (state / "session_min").write_bytes(b"150\n")
        r, log = run("launch", METAL_SESSION_MIN="150")
        assert r.returncode != 0 and "not clean (session_min exists)" in r.stdout + r.stderr, r.stdout + r.stderr
        assert log == "", log
        assert _left_in_state(state) == ["session_min"]
        return
    r, log = run("launch", STUB_RUNNING=1, METAL_SESSION_MIN="150")
    assert r.returncode != 0 and "already running or pending" in r.stdout + r.stderr, r.stdout + r.stderr
    assert "run-instances" not in log
    assert _left_in_state(state) == [], _left_in_state(state)


# (the minutes in the state, the environment's, the wall-clock poweroff's minutes ahead, the timer's seconds, the refusal)
_BY_STATE = [
    # the state's 150, with 60 in the environment both ways it could be read
    ("150\n", "60", 140, 140 * 60, None),
    ("150\n", "60", 151, 150 * 60, None),                                    # both upper ends, the timer to the second
    ("150\n", "60", 121, 121 * 60, None),                                    # both lower ends
    ("150\n", "60", 152, 140 * 60, "shutdown armed for 152 min ahead, expected 121..151"),
    ("150\n", "60", 140, 152 * 60, "monotonic timer armed for 152 min ahead, expected 121..150"),
    ("150\n", "60", 140, 150 * 60 + 1, "monotonic timer armed for 150 min ahead, expected 121..150 and not a second more"),
    ("150\n", "60", 120, 140 * 60, "shutdown armed for 120 min ahead, expected 121..151"),
    ("150\n", "60", 140, 121 * 60 - 1, "monotonic timer armed for 120 min ahead, expected 121..150"),
    # a state without the minutes (a session launched before there were any) is a 90-minute one, whatever the environment
    (None, "150", 88, 87 * 60, None),
    (None, "150", 91, 90 * 60, None),
    (None, "150", 140, 140 * 60, "monotonic timer armed for 140 min ahead, expected 61..90"),
    (None, "150", 92, 90 * 60, "shutdown armed for 92 min ahead, expected 61..91"),
    # the range's two ends
    ("60\n", "150", 61, 60 * 60, None),
    ("60\n", "150", 62, 60 * 60, "shutdown armed for 62 min ahead, expected 31..61"),
    ("180\n", "60", 181, 180 * 60, None),
    ("180\n", "60", 181, 180 * 60 + 1, "monotonic timer armed for 180 min ahead, expected 151..180 and not a second more"),
]


@needs_bash
@pytest.mark.parametrize("held,env_min,wall,mono_s,why", _BY_STATE,
                         ids=["%s-%s-%d-%d" % ((c[0] or "none").strip(), c[1], c[2], c[3]) for c in _BY_STATE])
def test_wait_judges_both_nets_by_the_states_session_min_and_never_the_environments(rig, tmp_path, held, env_min, wall,
                                                                                   mono_s, why):
    run, state, _ = rig
    _launched(state)
    if held is not None:
        (state / "session_min").write_bytes(held.encode())     # as launch writes it: LF, on Windows too
    r, log = run("wait", STUB_IP="203.0.113.9", STUB_PROV="OK", STUB_SCHED_FILE=_nets(tmp_path, wall, mono_s),
                 METAL_SESSION_MIN=env_min, SHUTDOWN_MIN_EXPECTED=env_min)
    out = r.stdout + r.stderr
    if why is None:
        assert r.returncode == 0 and "terminate-instances" not in log and (state / "armed").exists(), out
        assert "poweroff in %d min by the wall clock and in %d min by the monotonic timer" % (wall, mono_s // 60) in out, out
        return
    assert r.returncode == 1 and "terminate-instances" in log and (state / "terminated").exists(), out
    assert not (state / "armed").exists() and why in _abort_line(r), out


@needs_bash
@pytest.mark.parametrize("given,minutes", [(None, 90), ("", 90), ("90", 90), ("150", 150)])
def test_a_session_is_waited_for_by_the_minutes_it_was_launched_with(rig, monkeypatch, tmp_path, given, minutes):
    """launch, then wait on two copies of its state: the wall-clock window's upper end passes, a minute past it is refused.
    The default's windows are today's, 61..91 and 90 minutes to the second."""
    monkeypatch.delenv("METAL_SESSION_MIN", raising=False)
    run, state, _ = rig
    r, _ = run("launch", **({} if given is None else {"METAL_SESSION_MIN": given}))
    assert r.returncode == 0, r.stdout + r.stderr
    twin = tmp_path / "state-twin"
    shutil.copytree(str(state), str(twin))
    r, log = run("wait", STUB_IP="203.0.113.9", STUB_PROV="OK",
                 STUB_SCHED_FILE=_nets(tmp_path, minutes + 1, minutes * 60, name="right.txt"))
    assert r.returncode == 0 and (state / "armed").exists() and "terminate-instances" not in log, r.stdout + r.stderr
    r, log = run("wait", METAL_STATE=str(twin), STUB_IP="203.0.113.9", STUB_PROV="OK",
                 STUB_SCHED_FILE=_nets(tmp_path, minutes + 2, minutes * 60, name="late.txt"))
    assert r.returncode == 1 and "terminate-instances" in log, r.stdout + r.stderr
    assert "shutdown armed for %d min ahead, expected %d..%d" % (minutes + 2, minutes - 29, minutes + 1) in _abort_line(r)


@needs_bash
@pytest.mark.parametrize("held", ["", "\n", "abc\n", "090\n", "150\r\n", "59\n", "181\n", "150\n150\n"])
def test_wait_terminates_when_the_states_session_min_is_not_minutes_it_can_judge_by(rig, tmp_path, held):
    """The instance was armed with the minutes launch sent; a state whose session_min is not such a number does not say
    which, so wait terminates, before it asks the instance anything. The read the instance gives would pass for 90."""
    run, state, stub = rig
    _launched(state)
    (state / "session_min").write_bytes(held.encode())
    r, log = run("wait", STUB_IP="203.0.113.9", STUB_PROV="OK", STUB_SCHED_FILE=_nets(tmp_path, 88, 87 * 60),
                 METAL_SESSION_MIN="90")
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "terminate-instances" in log and (state / "terminated").exists(), out
    assert not (state / "armed").exists() and "session_min" in _abort_line(r), out
    assert not (stub / "ssh.log").exists(), "judged before anything is asked of the instance"


@needs_bash
def test_wait_on_a_session_already_proven_armed_says_so_and_terminates_nothing_whatever_its_session_min(rig):
    """Past the proof a failure must not terminate (the driver's FAILURE POLICY): a re-run of wait on a state that holds
    armed and an address exits before it reads session_min or asks anything of aws or the instance, even when session_min
    is not minutes it could judge by."""
    run, state, stub = rig
    _launched(state)
    (state / "armed").write_bytes(b"")
    (state / "ip").write_bytes(b"203.0.113.9\n")
    (state / "session_min").write_bytes(b"abc\n")
    r, log = run("wait")
    assert r.returncode == 0 and "already proven armed" in r.stdout and log == "", r.stdout + r.stderr
    assert not (state / "terminated").exists() and not (stub / "ssh.log").exists()


def test_the_readme_says_the_sessions_minutes_their_range_default_stop_point_and_cost_rule():
    with open(os.path.join(AWSDIR, "README.md"), encoding="utf-8") as f:
        text = " ".join(f.read().split())
    head = "### The session's minutes (SDV Phase 7 WP6-T)"
    section = text[text.index(head):text.index("### A liveness session instead")]
    for words in ("**`METAL_SESSION_MIN`** is the session's minutes: 90 when unset or empty, otherwise a whole number from "
                  "60 to 180 in plain decimal digits (no sign, no leading zero, no space)",
                  "`launch` alone reads it", "before its first `aws` call", "exactly one line `MIN=90`",
                  "records the minutes in the session state as `session_min`", "`session minutes: N`",
                  "`(not the default 90)`", "never the environment", "A state without `session_min`",
                  "is a 90-minute session", "do not keep it in `.env.local`",
                  "The harnesses' stop point follows the deadline", "with no change to any harness or to the deadline library",
                  "applies to the session's worst case: its minutes at the instance's rate",
                  "Check that budget before launch",
                  "a longer session needs its own budget review"):
        assert words in section, words
    cost = text[text.index("## What bounds the cost"):text.index("## What `run setup` says about the host")]
    assert "the session's 90 minutes" not in cost and "what is left of the 90 minutes" not in cost, "a fixed 90 is said"
    assert "the session's minutes (90 unless `launch` was given others" in cost
    assert "a poweroff 61–91 minutes ahead by the wall clock for a 90-minute session (N-29 to N+1 for N minutes)" in cost


def test_the_readme_says_a_rejected_run_instances_leaves_nothing_that_refuses_the_next_launch():
    """The step-by-step paragraph on a run-instances that EC2 rejects says what launch does about it, as the
    [nothing-started] case of the failed run-instances test above shows: it asks by its client token whether anything
    started anyway, and when nothing did removes the token and the minutes, so the next launch goes on. Nothing is left
    to remove by hand."""
    with open(os.path.join(AWSDIR, "README.md"), encoding="utf-8") as f:
        text = " ".join(f.read().split())
    head = "### The session's minutes (SDV Phase 7 WP6-T)"
    steps = text[text.index("## The session, step by step"):text.index(head)]
    para = steps[steps.index("`run-instances` itself rejects"):steps.index("The image and the disk are QNX-derived")]
    assert ("Those cost nothing: `launch` asks EC2 by its client token whether anything started anyway, and when nothing "
            "did it removes the token and the minutes it had recorded, so the next `launch` is not refused.") in para, para
    for stale in ("leave `$METAL_STATE/token` behind", "removed by hand", "`clear` will not remove it"):
        assert stale not in para, stale


# --------------------------------------------------------------------------
# SDV Phase 8 WP6 9.2: run-aw-setup.sh and run-aw-suite.sh, the Autoware
# session's harnesses, in setup's move of the aw inputs, the harness phase (their words, refusals and environment),
# wait-run, the detached runner, the session marker, the capture's whitelist and the capture phase's gate. Stubs stand
# in for the two harnesses, as for the vss ones above; tests/test_aw_harness.py runs the real ones. Documentation values
# only.

_AW_FILES = {"aw-inputs.json": b'{"format": 1, "files": {}}\n', "aw-scan.json": b'{"format": 1, "verdict": "fail"}\n',
             "aw-map.tar": b"a map tar stand-in"}
_AW_SETUP = "HARNESS=run-aw-setup.sh IMAGE=ifs-vss.bin VSS_HOST=c7g-metal"
_AW_SUITE = "HARNESS=run-aw-suite.sh IMAGE=ifs-vss.bin PLAN=a1 VSS_HOST=c7g-metal"


@needs_bash
@pytest.mark.parametrize("aw", [True, False], ids=["with-the-aw-inputs", "a-vss-session"])
def test_setup_moves_the_aw_inputs_out_of_the_bundle_directory_once_checked(tmp_path, aw):
    """in/ is the upload bundle's directory, which run-vss-setup.sh's `bundle.py verify --in` takes whole: setup, once every
    file's hash is checked, moves each aw-* file to aw-in/ (the aw harnesses' AW_IN). A session without them has none."""
    files = dict(_FILES, **_AW_FILES) if aw else dict(_FILES)
    w, r = _setup_run(tmp_path, files)
    out = r.stdout + r.stderr
    line = [ln for ln in out.splitlines() if "artefacts verified" in ln]
    assert len(line) == 1 and all(n in line[0] for n in files) and "hash mismatch" not in out, out
    assert sorted(os.listdir(str(w / "in"))) == sorted(_FILES), out
    if aw:
        assert sorted(os.listdir(str(w / "aw-in"))) == sorted(_AW_FILES), out
        assert all((w / "aw-in" / n).read_bytes() == b for n, b in _AW_FILES.items())
        assert "the aw session's files moved to aw-in/" in out
    else:
        assert not (w / "aw-in").exists()


@needs_bash
def test_setup_checks_an_aw_inputs_hash_before_it_moves_anything(tmp_path):
    w, r = _setup_run(tmp_path, dict(_FILES, **_AW_FILES), wrong=("aw-map.tar",))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "in/aw-map.tar hash mismatch" in out, out
    assert not (w / "aw-in").exists() and sorted(os.listdir(str(w / "in"))) == sorted(dict(_FILES, **_AW_FILES))


def _aw_w(tmp_path, harness_body=_STUB_VSS, aw=True, ifs=None, **kw):
    """W as _vss_w lays it, with the two aw stub harnesses beside the vss ones and the tarball's sdv/aw (stand-ins). IFS: the session's
    image when it is not _vss_w's ifs-vss.bin (gate G1's rehearsal boots ifs-ctl.bin)."""
    w, stub = _vss_w(tmp_path, harness_body=harness_body, **kw)
    if ifs is not None:
        inputs = w / "inputs.env"
        inputs.write_text(inputs.read_text(encoding="utf-8").replace("IFS_NAME=ifs-vss.bin", "IFS_NAME=" + ifs), encoding="utf-8", newline="\n")
    for h in ("run-aw-setup.sh", "run-aw-suite.sh", "run-aw-g1.sh"):
        _write(w / "repo" / "orin-native" / "gpu-concurrency" / h, harness_body, newline=False)
    if aw:
        for n in ("aw-entrypoint.sh", "hostcheck.sh"):
            _write(w / "repo" / "sdv" / "aw" / n, "# stand-in")
    return w, stub


def _c7g_setup_done(w):
    """run-vss-setup.sh as the harness phase and the detached runner leave a c7g-metal run that ended DONE."""
    _setup_done(w)
    _write(w / "vss-host", "c7g-metal\n")


@needs_bash
@pytest.mark.parametrize("words,k,msg", [
    ("HARNESS=run-aw-suite.sh IMAGE=ifs-vss.bin VSS_HOST=c7g-metal", None,
     "run-aw-suite.sh needs PLAN=a1, PLAN=a2, PLAN=b1, PLAN=b2 or PLAN=s"),
    (_AW_SUITE.replace("PLAN=a1", "PLAN=v1"), None, "run-aw-suite.sh needs PLAN=a1, PLAN=a2, PLAN=b1, PLAN=b2 or PLAN=s"),
    (_AW_SUITE.replace("PLAN=a1", "PLAN=A1"), None, "run-aw-suite.sh needs PLAN=a1, PLAN=a2, PLAN=b1, PLAN=b2 or PLAN=s"),
    (_AW_SUITE.replace("PLAN=a1", "PLAN=a3"), None, "run-aw-suite.sh needs PLAN=a1, PLAN=a2, PLAN=b1, PLAN=b2 or PLAN=s"),
    (_AW_SUITE.replace("PLAN=a1", "PLAN=carla"), None, "run-aw-suite.sh needs PLAN=a1, PLAN=a2, PLAN=b1, PLAN=b2 or PLAN=s"),
    (_AW_SETUP + " PLAN=a1", None, "run-aw-setup.sh takes no PLAN word (only run-aw-suite.sh does)"),
    ("HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=a1", None, "run-vss-suite.sh needs PLAN=v1, PLAN=v2 or PLAN=carla"),
    ("HARNESS=run-ota-drill.sh PLAN=a2", None, "run-ota-drill.sh takes no PLAN word (only run-vss-suite.sh does)"),
    ("HARNESS=run-aw-setup.sh IMAGE=ifs-vss.bin", None, "run-aw-setup.sh takes VSS_HOST=c7g-metal only (given: none)"),
    (_AW_SETUP.replace("c7g-metal", "a1-metal"), None, "run-aw-setup.sh takes VSS_HOST=c7g-metal only (given: a1-metal)"),
    (_AW_SUITE.replace("c7g-metal", "a1-metal"), None, "run-aw-suite.sh takes VSS_HOST=c7g-metal only (given: a1-metal)"),
    ("HARNESS=run-aw-suite.sh IMAGE=ifs-vss.bin PLAN=b2", None, "run-aw-suite.sh takes VSS_HOST=c7g-metal only (given: none)"),
    (_AW_SETUP.replace("c7g-metal", "orin"), None, "VSS_HOST=orin is not a bare-metal AWS host: a1-metal or c7g-metal"),
    (_AW_SETUP, "4", "run-aw-setup.sh takes no K"),
    (_AW_SUITE, "12", "run-aw-suite.sh takes no K"),
    (_AW_SETUP + " IMG_B=ifs-vss.bin", None, "run-aw-setup.sh takes no IMG_B word (its image is IMAGE=)"),
    (_AW_SUITE + " IMG_R=ifs-bell.bin", None, "run-aw-suite.sh takes no IMG_R word (its image is IMAGE=)"),
    ("HARNESS=run-aw-setup.sh VSS_HOST=c7g-metal", None, "run-aw-setup.sh needs IMAGE="),
    (_AW_SETUP.replace("ifs-vss.bin", "ifs-bell.bin"), None,
     "run-aw-setup.sh boots the session's METAL_IFS, ifs-vss.bin, not ifs-bell.bin"),
    (_AW_SUITE.replace("ifs-vss.bin", "ifs-nope.bin"), None, "image 'ifs-nope.bin' was not uploaded in this session"),
    (_AW_SETUP + " " + _AW_SETUP, None, "LADDER_ENV names HARNESS twice"),
    (_AW_SUITE.replace("PLAN=a1", "PLAN="), None, "LADDER_ENV word 'PLAN=' has no value"),
    (_AW_SETUP.replace("c7g-metal", "c7g.metal"), None,
     "VSS_HOST=c7g.metal is not a bare-metal AWS host: a1-metal or c7g-metal"),
    (_AW_SUITE + " IMG_UA=ifs-bell.bin", None, "run-aw-suite.sh takes no IMG_UA word (its image is IMAGE=)"),
    (_AW_SETUP + " SHM=1", None, "is not one the harness phase reads"),
])
def test_the_harness_phase_holds_the_aw_harnesses_to_their_words_before_making_anything(tmp_path, words, k, msg):
    """The two need IMAGE=, the session's METAL_IFS; VSS_HOST=c7g-metal and no other (the owner,
    2026-10-24); PLAN= the aw words for the suite alone; no K and no IMG_ word. Each refusal comes before the session
    marker and the stem directory."""
    w, stub = _aw_w(tmp_path)
    _write(w / "repo" / "orin-native" / "gpu-concurrency" / "run-ota-drill.sh", _STUB_VSS, newline=False)
    _write(w / "repo" / "sdv" / "drill" / "drill.py", "# stand-in")
    _c7g_setup_done(w)
    r = _vss_phase(w, stub, "harness", words, **({} if k is None else {"K": k}))
    out = r.stdout + r.stderr
    assert r.returncode != 0 and msg in out, out
    assert sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt", "vss-setup"], "refused before anything was made"
    assert not (w / "vss-session").exists() and not (stub / "setsid.log").exists()


@needs_bash
@pytest.mark.parametrize("words", [_AW_SETUP, _AW_SUITE])
@pytest.mark.parametrize("have", [(), ("aw-entrypoint.sh",), ("hostcheck.sh",)],
                         ids=["neither", "the-entrypoint-alone", "the-host-check-alone"])
def test_an_aw_harness_needs_sdv_aw_in_the_tarball(tmp_path, words, have):
    """The entrypoint and the host check both: a tarball with only one of the two is a tarball without sdv/aw's pair."""
    w, stub = _aw_w(tmp_path, aw=False)
    for n in have:
        _write(w / "repo" / "sdv" / "aw" / n, "# stand-in")
    _c7g_setup_done(w)
    r = _vss_phase(w, stub, "harness", words)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "the repo tarball lacks sdv/aw" in out, out
    assert not (w / "vss-session").exists() and sorted(os.listdir(str(w / "rec"))) == ["quiesce.txt", "vss-setup"]


@needs_bash
@pytest.mark.parametrize("setup", [
    None,
    dict(lines=None, done=False),
    dict(lines=["status=DONE"], done=False),
    dict(lines=["status=TIMEOUT at=30min-rule reason=30min-rule"], done=True),
    dict(lines=["status=FAILED rc=1"], done=True),
], ids=["no-setup", "running", "done-line-no-done", "timeout-30min-rule", "failed"])
def test_run_aw_setup_needs_a_finished_vss_setup_whose_last_status_line_is_done(tmp_path, setup):
    """Setup refused unless vss-setup is DONE, before the marker and the stem."""
    w, stub = _aw_w(tmp_path)
    if setup is not None:
        _laid(w, **setup)
        _write(w / "vss-host", "c7g-metal\n")
    r = _vss_phase(w, stub, "harness", _AW_SETUP)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "run-aw-setup.sh needs a finished run-vss-setup.sh" in out, out
    assert not (w / "vss-session").exists() and not (w / "rec" / "aw-setup").exists()


@needs_bash
@pytest.mark.parametrize("setup_word", [None, "a1-metal"])
def test_run_aw_setup_is_refused_after_a_vss_setup_of_another_host_mode(tmp_path, setup_word):
    w, stub = _aw_w(tmp_path)
    _setup_done(w)
    if setup_word:
        _write(w / "vss-host", setup_word + "\n")
    r = _vss_phase(w, stub, "harness", _AW_SETUP)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and ("run-aw-setup.sh needs the VSS_HOST run-vss-setup.sh ran with (%s), not VSS_HOST=c7g-metal"
                                  % (setup_word or "a1-metal")) in out, out
    assert not (w / "rec" / "aw-setup").exists()


@needs_bash
@pytest.mark.parametrize("aw_setup", [
    None,
    dict(lines=["status=DONE"], done=False),
    dict(lines=["status=FAILED at=smoke", "status=FAILED rc=1"], done=True),
    dict(lines=["status=TIMEOUT at=pull reason=deadline"], done=True),
    dict(lines=["status=FAILED at=host-check", "status=FAILED rc=1"], done=True),
], ids=["no-aw-setup", "done-line-no-done", "failed-smoke", "timeout", "failed-host-check"])
def test_run_aw_suite_needs_a_finished_aw_setup_whose_last_status_line_is_done(tmp_path, aw_setup):
    w, stub = _aw_w(tmp_path)
    _c7g_setup_done(w)
    if aw_setup is not None:
        _laid(w, stem="aw-setup", **aw_setup)
    r = _vss_phase(w, stub, "harness", _AW_SUITE)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    if aw_setup is not None and not aw_setup["done"]:
        assert "run-aw-suite.sh is refused while aw-setup still runs" in out, out
    else:
        assert "run-aw-suite.sh needs a finished run-aw-setup.sh" in out, out
    assert not (w / "rec" / "aw-suite").exists() and not (w / "vss-session").exists()


# SDV Phase 8 WP8: run-aw-g1.sh, gate G1's rehearsal on c7g.metal, is one more aw harness, under the suite's rule.
# Its image is ifs-ctl.bin, as the header says, so a session that runs it is laid with that image: _aw_w(..., ifs=_G1_IFS).
_G1_IFS = "ifs-ctl.bin"
_AW_G1 = "HARNESS=run-aw-g1.sh IMAGE=%s PLAN=rehearsal VSS_HOST=c7g-metal" % _G1_IFS


@needs_bash
@pytest.mark.parametrize("words, msg", [
    (_AW_G1.replace(" PLAN=rehearsal", ""), "run-aw-g1.sh needs PLAN=rehearsal here"),
    (_AW_G1.replace("PLAN=rehearsal", "PLAN=main"), "run-aw-g1.sh needs PLAN=rehearsal here"),
    (_AW_G1.replace("c7g-metal", "a1-metal"), "run-aw-g1.sh takes VSS_HOST=c7g-metal only (given: a1-metal)"),
    (_AW_G1.replace("VSS_HOST=c7g-metal", "VSS_HOST=orin"), "VSS_HOST=orin is not a bare-metal AWS host"),
], ids=["no-plan", "plan-main", "a1-metal", "orin"])
def test_run_aw_g1_takes_the_rehearsal_on_c7g_metal_only(tmp_path, words, msg):
    w, stub = _aw_w(tmp_path, ifs=_G1_IFS)
    _c7g_setup_done(w)
    _laid(w, stem="aw-setup", lines=["status=DONE"], done=True)
    r = _vss_phase(w, stub, "harness", words)
    assert r.returncode != 0 and msg in r.stdout + r.stderr, r.stdout + r.stderr
    assert not (w / "rec" / "aw-g1").exists()


@needs_bash
@pytest.mark.parametrize("aw_setup", [None, dict(lines=["status=DONE"], done=False), dict(lines=["status=FAILED at=smoke"], done=True)],
                         ids=["no-aw-setup", "no-done", "failed"])
def test_run_aw_g1_needs_a_finished_aw_setup(tmp_path, aw_setup):
    w, stub = _aw_w(tmp_path, ifs=_G1_IFS)
    _c7g_setup_done(w)
    if aw_setup is not None:
        _laid(w, stem="aw-setup", **aw_setup)
    r = _vss_phase(w, stub, "harness", _AW_G1)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "run-aw-g1.sh is refused while aw-setup still runs" in out or "run-aw-g1.sh needs a finished run-aw-setup.sh" in out, out
    assert not (w / "rec" / "aw-g1").exists()


def _aw_g1_record(tmp_path):
    rec = tmp_path / "rec"
    d = rec / "aw-g1"
    _write(d / "status", "status=DONE")
    (d / "done").touch()
    for rel in ("host-before.txt", "host-after.txt", "run.log", "detach.log"):
        _write(d / rel, "a line")
    _write(d / "raw" / "g1.json", json.dumps({"harness": "run-aw-g1.sh", "status": "DONE"}), newline=False)
    for rel, doc in (("claim/run/replies.jsonl", {"seq": 1}), ("drives/d001/scenario.jsonl", {"step": "map"}), ("diag/diag.jsonl", {"mono_ns": 1}),
                     ("kill/claim/run/replies.jsonl", {"seq": 1})):
        _write(d / "raw" / rel, json.dumps(doc))
    for rel in ("watchdog.log", "arm.tsv", "verdict.txt", "kill/verdict.txt", "drives/driver-d001.log"):
        _write(d / "raw" / rel, "a line")
    return rec


def test_capture_takes_an_aw_g1_stem_by_the_whitelist_with_g1_json_as_its_evidence(tmp_path):
    pub = tmp_path / "pub"
    r = _vss_capture(_aw_g1_record(tmp_path), pub)
    assert r.returncode == 0, r.stdout + r.stderr
    got = _published(pub)
    for rel in ("aw-g1/status", "aw-g1/run.log", "aw-g1/raw/g1.json", "aw-g1/raw/watchdog.log", "aw-g1/raw/claim/run/replies.jsonl",
                "aw-g1/raw/drives/d001/scenario.jsonl", "aw-g1/raw/drives/driver-d001.log", "aw-g1/raw/kill/verdict.txt",
                "aw-g1/raw/kill/claim/run/replies.jsonl"):
        assert rel in got, (rel, got)
    assert "aw-g1/detach.log" not in got
    assert "aw-g1: DONE" in (pub / "capture.log").read_text(encoding="utf-8")


_STUB_AW_RUN = r'''#!/usr/bin/env bash
mkdir -p "$OUT"
env -0 | sort -z > "$OUT/env-whole.bin"
if [ -n "${STUB_RELEASE:-}" ]; then
  for _ in $(seq 1 200); do [ -e "$STUB_RELEASE" ] && break; sleep 0.05; done
fi
printf '%s\n' "== the harness's own host check, after its sweep" >> "$(dirname "$OUT")/host-after.txt"
echo "status=DONE" >> "$STATUS"
'''


@needs_bash
@needs_proc_interrupts
def test_the_aw_harnesses_run_detached_once_per_session_with_aw_in_and_their_host_mode(tmp_path):
    """vss-setup first; aw-setup and then aw-suite each detached, under the session marker, into
    its stem with host-before.txt, once per session; AW_IN the moved inputs, VSS_HOST c7g-metal, PLAN the suite's alone.
    The detached runner appends its host snapshot after the harness's own host check in host-after.txt. One session, one image: G1's
    rehearsal runs after setup and the suite in a session whose METAL_IFS is ifs-ctl.bin, as their words say here."""
    w, stub = _aw_w(tmp_path, harness_body=_STUB_AW_RUN, ifs=_G1_IFS)
    r = _vss_phase(w, stub, "harness", (_SETUP + " VSS_HOST=c7g-metal").replace("ifs-vss.bin", _G1_IFS))
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    img = str(w / "img" / _G1_IFS)
    for words, stem, plan in ((_AW_SETUP.replace("ifs-vss.bin", _G1_IFS), "aw-setup", None),
                              (_AW_SUITE.replace("ifs-vss.bin", _G1_IFS).replace("PLAN=a1", "PLAN=b2"), "aw-suite", "b2"),
                              (_AW_G1, "aw-g1", "rehearsal")):
        r = _vss_phase(w, stub, "harness", words)
        d = w / "rec" / stem
        out = r.stdout + r.stderr
        assert r.returncode == 0 and "started run-%s.sh, detached, into" % stem in out and _wait_for(d / "done"), out
        assert "run-%s.sh " % stem in (w / "vss-session").read_text()
        log = (stub / "setsid.log").read_text()
        assert re.search(r"^setsid nohup bash \S*remote-ladder\.sh _detached %s run-%s\.sh$" % (stem, stem), log, re.M), log
        env = _whole_env(d / "raw" / "env-whole.bin")
        want = {"W": str(w), "IMG_S": img, "IMG_B": img, "IFS_BIN": img, "DISK": str(w / "img" / "disk-qemu"),
                "OUT": str(d / "raw"), "VSS_IN": str(w / "in"), "AW_IN": str(w / "aw-in"), "VSS_HOME": str(w / "sdv"),
                "STATUS": str(d / "status"), "VSS_HOST": "c7g-metal"}
        assert {k: env.get(k) for k in want} == want, env
        assert env.get("PLAN") == plan and "DRILL_IN" not in env and "K" not in env, env
        assert (d / "host-before.txt").read_text().startswith(_QUIESCE_REC)
        after = (d / "host-after.txt").read_text()
        assert after.startswith("== the harness's own host check, after its sweep\n") and re.search(
            r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", after, re.M), after
        assert (d / "status").read_text().splitlines() == ["status=DONE"]
        r = _vss_phase(w, stub, "harness", words)
        assert r.returncode != 0 and "exists: one %s run per session" % stem in r.stdout + r.stderr
    for h in _A6_HARNESSES[:3]:
        _write(w / "repo" / "orin-native" / "gpu-concurrency" / h, "exit 0")
        r = _vss_phase(w, stub, "harness", "HARNESS=%s IMAGE=ifs-bell.bin" % h)
        assert r.returncode != 0 and "vss-session exists" in r.stdout + r.stderr, (h, r.stdout + r.stderr)


@needs_bash
@needs_proc_interrupts
def test_a_vss_harness_still_writes_its_host_after_anew(tmp_path):
    """The detached runner appends host-after.txt for an aw harness alone: a vss harness's is written as before."""
    w, stub = _aw_w(tmp_path, harness_body=_STUB_AW_RUN)
    r = _vss_phase(w, stub, "harness", _SETUP + " VSS_HOST=c7g-metal")
    d = w / "rec" / "vss-setup"
    assert r.returncode == 0 and _wait_for(d / "done"), r.stdout + r.stderr
    after = (d / "host-after.txt").read_text()
    assert "the harness's own host check" not in after and re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n", after), after
    env = _whole_env(d / "raw" / "env-whole.bin")
    assert "AW_IN" not in env and "DRILL_IN" not in env, "the aw harnesses' word goes to them alone"


@needs_bash
@pytest.mark.parametrize("words", [_AW_SETUP, _AW_SUITE])
@pytest.mark.parametrize("a6", ["bell", "ladder"])
def test_an_aw_harness_is_refused_while_rec_holds_an_a6_record(tmp_path, words, a6):
    w, stub = _aw_w(tmp_path)
    _c7g_setup_done(w)
    if words == _AW_SUITE:
        _laid(w, stem="aw-setup", lines=["status=DONE"], done=True)
    _write(w / "rec" / a6 / "run.log", "an A6 harness ran here")
    r = _vss_phase(w, stub, "harness", words)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "holds an A6 record (%s)" % a6 in out, out
    assert not (w / "vss-session").exists()


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("then", ["HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1 VSS_HOST=c7g-metal",
                                  "HARNESS=run-ota-drill.sh VSS_HOST=c7g-metal", _AW_SUITE],
                         ids=["vss-suite", "drill", "aw-suite"])
def test_no_vss_harness_starts_while_aw_setup_still_runs(tmp_path, then):
    """The aw harnesses share this host's Docker with the others: none starts while aw-setup still runs (no done)."""
    w, stub = _aw_w(tmp_path)
    _write(w / "repo" / "orin-native" / "gpu-concurrency" / "run-ota-drill.sh", _STUB_VSS, newline=False)
    _write(w / "repo" / "sdv" / "drill" / "drill.py", "# stand-in")
    r = _vss_phase(w, stub, "harness", _SETUP + " VSS_HOST=c7g-metal", STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-setup" / "done"), r.stdout + r.stderr
    release = w.parent / "release"
    r = _vss_phase(w, stub, "harness", _AW_SETUP, STUB_RELEASE=release, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0, r.stdout + r.stderr
    h = then.split()[0][len("HARNESS="):]
    try:
        r = _vss_phase(w, stub, "harness", then)
        out = r.stdout + r.stderr
        still = not (w / "rec" / "aw-setup" / "done").exists()
    finally:
        release.touch()
    assert still, "aw-setup ended before the second was asked: " + out
    assert r.returncode != 0 and "%s is refused while aw-setup still runs" % h in out, out
    assert _wait_for(w / "rec" / "aw-setup" / "done")


@needs_bash
@needs_proc_interrupts
def test_wait_run_waits_for_an_aw_harness_and_prints_its_status(tmp_path):
    w, stub = _aw_w(tmp_path)
    _c7g_setup_done(w)
    release = w.parent / "release"
    r = _vss_phase(w, stub, "harness", _AW_SETUP, STUB_RELEASE=release, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0, r.stdout + r.stderr
    p = _vss_phase(w, stub, "wait-run", "HARNESS=run-aw-setup.sh", popen=True)
    try:
        time.sleep(1.0)
        assert p.poll() is None, "wait-run returned while aw-setup still ran"
        release.touch()
        out, _ = p.communicate(timeout=30)
    finally:
        p.kill()
    assert p.returncode == 0 and "status=DONE" in out and "done: yes" in out, out


# capture.py and the aw stems: the whitelist gains exactly the aw records' files under aw-setup and aw-suite; each
# stem is evidence by the vss rules.

def _aw_stem(rec, stem, status=("status=DONE",), done=True, result=True, after=True):
    """rec/<stem> as the harness phase, the detached runner and an aw harness leave it, with files of the stem that are on
    no whitelist."""
    d = rec / stem
    _write(d / "host-before.txt", _QUIESCE_REC + "2026-10-26T05:00:00Z\n0.10 0.20 0.30 1/200 4022\n== 2.12's host check\n"
           "format=1\nlo.flags=LOOPBACK,UP,LOWER_UP\nnet.core.rmem_max=212992", newline=False)
    _write(d / "run.log", "[05:00:01] step 1/6 preflight: start\nfetched from 203.0.113.7")
    _write(d / "detach.log", "[05:00:00] _detached: the harness starts")
    if status is not None:
        _write(d / "status", "\n".join(status), newline=bool(status))
    if after:
        _write(d / "host-after.txt", "== 2.12's host check\nformat=1\nlo.flags=LOOPBACK,UP,LOWER_UP\n2026-10-26T05:40:00Z")
    raw = d / "raw"
    name = "setup.json" if stem == "aw-setup" else "suite.json"
    if result:
        _write(raw / name, json.dumps({"harness": "run-%s.sh" % stem, "status": status[-1][len("status="):] if status else "",
                                       "image": {"ref": "ghcr.io/autowarefoundation/autoware@sha256:" + "ab" * 32}}),
               newline=False)
    if stem == "aw-setup":
        _write(raw / "inputs.txt", "aw-inputs.json %s ok\naw-map.tar %s ok\ncommit %s (aw-inputs.json)" % (
            "cd" * 32, "ef" * 32, "0123456789abcdef" * 2 + "01234567"))
        _write(raw / "smoke.err", "a smoke's raw stderr, on no whitelist")
    else:
        for unit in ("00-guest", "01-honest"):
            u = raw / unit
            _write(u / "guest-console.log", "monitor: ctl rules: kind 2, catalog 0x12345678 (vss 6.0)\r\n")
            _write(u / "unit.json", json.dumps({"unit": unit, "state": "ran", "console_from": _T12}), newline=False)
        u = raw / "01-honest"
        _write(u / "replies.jsonl", '{"seq":1,"frame":"07%s","outcome":"replied","verdict":0,"reason":0,"mono_ns":%d}\n'
               % ("00" * 63, _T12), newline=False)
        _write(u / "claim-node.log", "ctl_claim_node: controls=1 replied=1 (accepted=1 rejected=0) identity=holds")
        _write(u / "scenario.jsonl", '{"step":"map","outcome":"done","mono_ns":null}\n{"step":"arrive","outcome":"done",'
               '"mono_ns":%d}\n' % _T12, newline=False)
        _write(u / "export.jsonl", '{"topic":"/control/command/control_cmd","recv_ns":%d,"stamp_ns":%d,"fields":{}}\n'
               % (_T12, _T12), newline=False)
        _write(u / "ros-log" / "aw_scenario_1.log", "a ROS log line")
        _write(u / "bag" / "metadata.yaml", "rosbag2_bagfile_information:")
        _write(u / ".ros" / "log" / "latest", "a ROS log line")
        _write(u / "samples.txt", "== t 0 mem 29000000")
        _write(u / "scenario.log", "aw_scenario: arrived")
    if done:
        (d / "done").touch()
    return d


_AW_PUBLISHED = sorted(["%s/%s" % (s, n) for s in ("aw-setup", "aw-suite")
                        for n in ("host-before.txt", "host-after.txt", "run.log", "status")]
                       + ["aw-setup/raw/setup.json", "aw-setup/raw/inputs.txt", "aw-suite/raw/suite.json"]
                       + ["aw-suite/raw/00-guest/" + n for n in ("guest-console.log", "unit.json")]
                       + ["aw-suite/raw/01-honest/" + n for n in ("claim-node.log", "export.jsonl", "guest-console.log",
                                                                  "replies.jsonl", "scenario.jsonl", "unit.json")])
_AW_NEVER = ["aw-setup/detach.log", "aw-setup/raw/smoke.err", "aw-suite/detach.log",
             "aw-suite/raw/01-honest/ros-log/aw_scenario_1.log", "aw-suite/raw/01-honest/bag/metadata.yaml",
             "aw-suite/raw/01-honest/.ros/log/latest", "aw-suite/raw/01-honest/samples.txt",
             "aw-suite/raw/01-honest/scenario.log"]


@needs_bash
@pytest.mark.parametrize("awk", _AWKS)
def test_capture_takes_the_aw_stems_by_exactly_their_whitelist(tmp_path, awk):
    rec = _small_vss(tmp_path, {"vss-setup": {}})
    for stem in ("aw-setup", "aw-suite"):
        _aw_stem(rec, stem)
    pub = tmp_path / "pub"
    r = _vss_capture(rec, pub, AWK=awk)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    got = [p for p in _published(pub) if p.startswith("aw-")]
    assert got == _AW_PUBLISHED, got
    report = (pub / "capture.log").read_text(encoding="utf-8")
    for rel in _AW_NEVER + ["aw-setup/done", "aw-suite/done"]:
        assert "excluded: %s " % rel in r.stdout and "excluded: %s " % rel in report, (rel, r.stdout)
    assert "capture: a vss record (aw-setup aw-suite vss-setup)" in report, report
    assert "aw-setup: DONE (status=DONE, with raw/setup.json)" in report, report
    assert "aw-suite: DONE (status=DONE, with raw/suite.json)" in report, report
    for rel in ("raw/01-honest/replies.jsonl", "raw/01-honest/export.jsonl", "raw/01-honest/unit.json"):
        assert (pub / "aw-suite" / rel).read_bytes() == (rec / "aw-suite" / rel).read_bytes(), rel
    assert b"203.0.113.7" not in (pub / "aw-setup" / "run.log").read_bytes()
    assert _leakscan(pub).returncode == 0


@needs_bash
def test_capture_does_not_take_a_stem_named_like_an_aw_one_for_it(tmp_path):
    rec = _small_vss(tmp_path, {"vss-setup": {}})
    _aw_stem(rec, "aw-setup")
    shutil.copytree(str(rec / "aw-setup"), str(rec / "aw-setup2"))
    shutil.copytree(str(rec / "aw-setup"), str(rec / "aw-suites"))
    r = _vss_capture(rec, tmp_path / "pub")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    published = _published(tmp_path / "pub")
    assert not [p for p in published if p.startswith(("aw-setup2", "aw-suites"))], published
    assert "aw-setup2:" not in out and "aw-suites:" not in out and "excluded: aw-setup2/run.log " in out, out


@needs_bash
@pytest.mark.parametrize("stem", ["aw-setup", "aw-suite"])
@pytest.mark.parametrize("kw,incomplete,ok,marks", [
    ({}, "", True, ["%s: DONE"]),
    (dict(status=["status=TIMEOUT at=02-inject reason=step-timeout"], result=False), "", True,
     ["%s: TIMEOUT (status=TIMEOUT at=02-inject reason=step-timeout, but no raw/"]),
    (dict(status=["status=FAILED at=host-check", "status=FAILED rc=1"], after=False), "", True,
     ["%s: FAILED (status=FAILED rc=1, after the harness's own status=FAILED at=host-check"]),
    (dict(status=None, done=False, result=False, after=False), "", False, ["%s has no done"]),
    (dict(status=None, done=False, result=False, after=False), "STEM", True, ["%s: INCOMPLETE"]),
    (dict(result=False), "", False, ["%s: DONE (status=DONE, but no raw/", "nothing ran"]),
    (dict(status=[], after=False), "", False, ["%s: NO STATUS"]),
], ids=["done", "timeout-no-result", "failed-host-check", "running", "incomplete", "done-no-result", "no-status"])
def test_capture_holds_an_aw_stem_to_the_vss_evidence_rules(tmp_path, stem, kw, incomplete, ok, marks):
    rec = _small_vss(tmp_path, {})
    _aw_stem(rec, stem, **kw)
    r = _vss_capture(rec, tmp_path / "pub", CAPTURE_INCOMPLETE=incomplete.replace("STEM", stem))
    out = r.stdout + r.stderr
    assert (r.returncode == 0) is ok, out
    for m in marks:
        assert (m % stem if "%s" in m else m) in out, (m, out)
    if ok:
        assert (tmp_path / "pub" / stem / "run.log").exists() and not (tmp_path / "pub" / stem / "detach.log").exists()


@needs_bash
@pytest.mark.parametrize("ahead_min,packed", [(80, False), (12, True)])
def test_the_capture_phase_refuses_an_aw_stem_without_done_until_the_give_up_point(tmp_path, ahead_min, packed):
    w, stub = _capture_w(tmp_path, ahead_min=ahead_min)
    _vss_stem(w / "rec", "vss-setup")
    _aw_stem(w / "rec", "aw-setup")
    _aw_stem(w / "rec", "aw-suite", status=None, done=False, result=False, after=False)
    r = _gate(w, stub)
    out = r.stdout + r.stderr
    if not packed:
        assert r.returncode != 0 and "aw-suite has no done" in out, out
        assert not (w / "pub.tgz").exists() and not (w / "capture.log").exists(), "refused before capture.py ran"
    else:
        assert r.returncode == 0 and "aw-suite: INCOMPLETE" in out, out
        assert (w / "pub" / "aw-suite" / "run.log").exists() and (w / "pub.tgz").exists()


@needs_bash
def test_the_capture_phase_takes_finished_aw_stems_and_prints_their_lines(tmp_path):
    w, stub = _capture_w(tmp_path)
    _vss_stem(w / "rec", "vss-setup")
    for stem in ("aw-setup", "aw-suite"):
        _aw_stem(w / "rec", stem)
    r = _gate(w, stub)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "captured" in out, out
    for stem in ("aw-setup", "aw-suite", "vss-setup"):
        assert re.search(r"^%s: DONE " % stem, out, re.M), (stem, out)
    assert (w / "pub" / "aw-suite" / "raw" / "01-honest" / "replies.jsonl").exists()


def test_the_readme_and_the_header_say_what_an_aw_session_is():
    """The aw session's own section (METAL_TYPE and VSS_HOST together, METAL_IFS=ifs-ctl.bin,
    METAL_FILES the aw inputs, the harness order, capture, fetch, terminate and verify-vol, the cost by the c7g notes)
    after the vss sections, and remote-ladder.sh's header names the two."""
    with open(os.path.join(AWSDIR, "README.md"), encoding="utf-8") as f:
        text = f.read()
    start = text.index("### An aw session (SDV plan Phase 8)")
    assert text.index("### An OTA drill session") < start < text.index("## What bounds the cost")
    sec = re.sub(r"\s+", " ", text[start:text.index("## What bounds the cost")])
    for want in ("`METAL_TYPE` and `VSS_HOST` go together", "`VSS_HOST=c7g-metal`", "`METAL_IFS=ifs-ctl.bin`",
                 "`aw-inputs.json`", "`aw-scan.json`", "`aw-map.tar`", "`~/a1/aw-in`",
                 '`LADDER_ENV="HARNESS=run-vss-setup.sh IMAGE=ifs-ctl.bin VSS_HOST=c7g-metal"',
                 '`LADDER_ENV="HARNESS=run-aw-setup.sh IMAGE=ifs-ctl.bin VSS_HOST=c7g-metal"',
                 '`LADDER_ENV="HARNESS=run-aw-suite.sh IMAGE=ifs-ctl.bin PLAN=a2 VSS_HOST=c7g-metal"',
                 "`run capture`, `fetch`, `terminate`, `verify`, later `verify-vol`",
                 "The budget",
                 "review it before launch", "`status=FAILED at=host-check`",
                 "`PLAN=a1`, `PLAN=a2`, `PLAN=b1`, `PLAN=b2` or `PLAN=s`"):
        assert want in sec, want
    with open(REMOTE, encoding="utf-8") as f:
        ladder = f.read()
    header = _one_paragraph(ladder[ladder.index("#   THE AW SESSION"):ladder.index("#   THE SESSION MARKER")])
    for want in ("run-aw-setup.sh and run-aw-suite.sh", "VSS_HOST=c7g-metal", "PLAN=a1|a2|b1|b2|s", "AW_IN=$W/aw-in",
                 "appends its host-after.txt"):
        assert want in header, want


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("stem", ["aw-setup", "aw-suite"])
def test_a_finished_aw_stem_is_no_a6_record_for_a_vss_harness_asked_for_after_it(tmp_path, stem):
    """capture.py takes the aw stems by the vss rules, so the harness phase's list of stems that are no A6 record holds both:
    a vss harness asked for after a finished aw one is not refused for it."""
    w, stub = _aw_w(tmp_path)
    _c7g_setup_done(w)
    _laid(w, stem=stem, lines=["status=DONE"], done=True)
    r = _vss_phase(w, stub, "harness", "HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1 VSS_HOST=c7g-metal",
                   STUB_STATUS_LINE="status=DONE")
    out = r.stdout + r.stderr
    assert "A6 record (%s)" % stem not in out and "holds an A6 record" not in out, out
    assert r.returncode == 0 and _wait_for(w / "rec" / "vss-suite" / "done"), out


# --------------------------------------------------------------------------
# Four checks added after WP6 9.2 (SDV Phase 8, 2026-10-27): the harness phase's running check
# names rec/aw-suite as it names rec/aw-setup, so no vss harness starts while run-aw-suite.sh still runs.


@needs_bash
@needs_proc_interrupts
@pytest.mark.parametrize("then", ["HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1 VSS_HOST=c7g-metal",
                                  "HARNESS=run-ota-drill.sh VSS_HOST=c7g-metal"], ids=["vss-suite", "drill"])
def test_no_vss_harness_starts_while_aw_suite_still_runs(tmp_path, then):
    """As for aw-setup above: run-aw-suite.sh shares this host's Docker with the others, so none starts while rec/aw-suite
    has no done, and the refusal comes before the session marker and the stem. (A second aw harness is refused earlier,
    as one run per session: both aw stems exist by then.)"""
    w, stub = _aw_w(tmp_path)
    # this test's aw-suite stand-in waits for the release up to 2400 x 0.05 s, past the 60 s _vss_phase gives each call, so
    # a slow second call fails as its own timeout, never as aw-suite ending first (the shared _STUB_VSS keeps its 200)
    held = _STUB_VSS.replace("$(seq 1 200)", "$(seq 1 2400)")
    assert held.count("$(seq 1 2400)") == 1, "the stand-in's hold is not where this test lengthens it"
    _write(w / "repo" / "orin-native" / "gpu-concurrency" / "run-aw-suite.sh", held, newline=False)
    _write(w / "repo" / "orin-native" / "gpu-concurrency" / "run-ota-drill.sh", _STUB_VSS, newline=False)
    _write(w / "repo" / "sdv" / "drill" / "drill.py", "# stand-in")
    for words, stem in ((_SETUP + " VSS_HOST=c7g-metal", "vss-setup"), (_AW_SETUP, "aw-setup")):
        r = _vss_phase(w, stub, "harness", words, STUB_STATUS_LINE="status=DONE")
        assert r.returncode == 0 and _wait_for(w / "rec" / stem / "done"), r.stdout + r.stderr
    release = w.parent / "release"
    r = _vss_phase(w, stub, "harness", _AW_SUITE, STUB_RELEASE=release, STUB_STATUS_LINE="status=DONE")
    assert r.returncode == 0, r.stdout + r.stderr
    h = then.split()[0][len("HARNESS="):]
    try:
        r = _vss_phase(w, stub, "harness", then)
        out = r.stdout + r.stderr
        still = not (w / "rec" / "aw-suite" / "done").exists()
        marker = (w / "vss-session").read_text()
    finally:
        release.touch()
    assert still, "aw-suite ended before the second was asked: " + out
    assert r.returncode != 0 and "%s is refused while aw-suite still runs" % h in out, out
    assert not (w / "rec" / h[len("run-"):-len(".sh")]).exists() and h not in marker, marker
    assert _wait_for(w / "rec" / "aw-suite" / "done")
