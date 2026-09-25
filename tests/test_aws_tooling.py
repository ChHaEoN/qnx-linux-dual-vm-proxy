"""scripts/aws/ -- the bare-metal AWS session tooling, and the shift-isolation driver.

Nothing here contacts AWS. The driver's real code paths run against stub `aws`,
`ssh` and `scp` programs that log their arguments and answer from environment
variables, so what is tested is what keeps a session cheap and its record clean:
every failure between launch and the proven safety net must TERMINATE (and
confirm it), teardown checks must refuse a live instance or an orphaned volume,
the capture must publish run data byte-for-byte and redact only strings, and a
fetched capture carrying an identifier must be refused.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import hashlib

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
        -- 49 of them, which reads like a pass.
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
case "$*" in
  *terminate-instances*)
    if [ "${STUB_TERM_FAIL:-0}" = 1 ]; then
      echo "An error occurred (ExpiredToken): User: arn:aws:iam::123456789012:user/bob" >&2; exit 254
    fi
    echo shutting-down > "$STUB_DIR/state"; echo shutting-down ;;
  *State.Name*) cat "$STUB_DIR/state" 2>/dev/null || echo "${STUB_STATE:-running}" ;;
  *run-instances*)
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

    def run(*args, **env):
        e = dict(os.environ, METAL_NO_ENV_LOCAL="1", AWS=str(stub / "aws"), STUB_DIR=str(stub),
                 METAL_STATE=str(state), METAL_KEY_NAME="lab-key", METAL_SG_NAME="lab-sg",
                 METAL_POLL_S="0", METAL_IP_WAIT_S="1", METAL_PROV_WAIT_S="1",
                 METAL_CONFIRM_TRIES="2", METAL_READBACK_TRIES="5",
                 PATH=_path_with(stub))
        e.update({k: str(v) for k, v in env.items()})
        r = subprocess.run([BASH, DRIVER] + list(args), capture_output=True, text=True, env=e, timeout=120)
        log = (stub / "aws.log").read_text(encoding="utf-8") if (stub / "aws.log").exists() else ""
        return r, log

    return run, state, stub


def _sched(tmp_path, minutes, mode="poweroff"):
    now = 1_790_000_000
    f = tmp_path / "sched.txt"
    _write(f, "USEC=%d\nWARN_WALL=1\nMODE=%s\nNOW=%d" % ((now + minutes * 60) * 1_000_000, mode, now))
    return f


# --------------------------------------------------------------------------
# launch: every failure after the id exists terminates, and says so


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
    session nobody comes back to, and a stopped instance keeps its 16 GB root
    volume attached and billing."""
    run, state, _ = rig
    r, log = run("launch")
    assert r.returncode == 0, r.stdout + r.stderr
    sent = [ln for ln in log.splitlines() if "run-instances" in ln]
    assert len(sent) == 1, log
    assert "--instance-initiated-shutdown-behavior terminate" in sent[0], sent[0]
    assert '"DeleteOnTermination":true' in sent[0], sent[0]
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
    r, log = run("launch", STUB_RUNNING=1)
    assert r.returncode != 0 and "run-instances" not in log


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


# --------------------------------------------------------------------------
# fetch: integrity, then cleanliness


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
    ({"ladder/run.log": "guest 192.168.100.10 answered", "ladder/raw/kvm-D-db_r1.json": '{"halt_wait_ns": 113645786915}'}, True),
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
        "booted ami-02153ae97d7504246",
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
    assert "ami-02153ae97d7504246" in out, "the AMI is provenance and must survive"


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
    m = re.match(r'^shutdown -h \+\$MIN .*&& touch "\$M/SHUTDOWN_ARMED"$', commands[0])
    assert m, "the first command must arm the shutdown and record that it did: %r" % commands[0]
    mins = re.search(r"^MIN=(\d+)$", body, re.M)
    driver = open(DRIVER, encoding="utf-8").read()
    d = re.search(r'SHUTDOWN_MIN_EXPECTED="\$\{SHUTDOWN_MIN_EXPECTED:-(\d+)\}"', driver)
    assert mins and d and d.group(1) == mins.group(1), "userdata's minutes and the driver's expectation differ"
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
    for phase in ("launch-live", "liveness", "launch-stamp", "stamp", "metal"):
        run("run", phase, K="4")
    log = (stub / "ssh.log").read_text()
    for phase in ("launch-live", "liveness", "launch-stamp", "stamp", "metal"):
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
])
def test_remote_session_phases_refuse_without_a_guest_or_with_a_bad_k(tmp_path, phase, env, msg):
    r = _remote_env(tmp_path, phase, **env)
    assert r.returncode != 0 and msg in r.stdout + r.stderr, r.stdout + r.stderr


@needs_bash
@pytest.mark.parametrize("session", ["liveness", "stamp", "metal"])
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
           json.dumps({"summary": {"tag": "D-db_r1", "p50_ms": 0.178123456789, "n": 1000},
                       "samples_ms": [0.1, 0.178123456789]}), newline=False)
    # 12-digit counters: exactly the shape of an account id.
    _write(raw / "kvm-D-db_r1.json",
           json.dumps({"before": {"t_ns": 912345678901, "qemu_pid": 4022,
                                  "counters": {"halt_wait_ns": 113645786915},
                                  "threads": {"4022": {"comm": "qemu-system-aar", "wait_ns": 5}}}}), newline=False)
    _write(raw / "stamp.json",
           json.dumps({"guest_ifs": "/home/ubuntu/a1/img/ifs-kick.bin", "qemu_started_ns": 123456789012,
                       "qemu_version": "QEMU emulator version 6.2.0 (Debian 1:6.2+dfsg-2ubuntu6.31)",
                       "kernel": "6.8.0-1063-aws", "ami": "ami-02153ae97d7504246"}, indent=2))
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
    assert stamp["ami"] == "ami-02153ae97d7504246", "the AMI is provenance and is kept"
    assert stamp["qemu_version"].endswith("2ubuntu6.31)"), "the package version must not be over-masked"
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
    ("vol-0abcdef1234567890 attached", False),
    ("arn:aws:iam::111122223333:user/x", False),
    ("id 11112222-3333-4444-5555-666677778888", False),
    ("account 111122223333 here", False),
    ("ami-02153ae97d7504246 is fine", True),
])
def test_leakscan_text(tmp_path, text, ok):
    _write(tmp_path / "d" / "x.log", text)
    r = subprocess.run([PY, LEAKSCAN, str(tmp_path / "d")], capture_output=True, text=True)
    assert (r.returncode == 0) is ok, r.stdout
    assert text.split()[-1] not in r.stdout or ok, "the leaked value itself must not be printed"


def test_leakscan_json_scans_strings_not_numbers_and_takes_literals(tmp_path):
    _write(tmp_path / "d" / "kvm.json", json.dumps({"halt_wait_ns": 113645786915, "comm": "qemu-system-aar"}))
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
