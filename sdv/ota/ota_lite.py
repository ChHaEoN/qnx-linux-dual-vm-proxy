#!/usr/bin/env python3
"""ota_lite.py -- the updater ota-lite: switches the app container on a spool record and reports the outcome (sdv/ota;
SDV Phase 6 WP1).

Standard library only, but for the health check's source (ota_kuksa.py, kuksa-client
0.6.0 from the app's locks), which only `run` loads. It runs as a transient systemd unit (owner decision D3), the only
holder of Docker control on the host; it acts on app-class entries of the host's manifest only, and never on a
platform image, its own unit, the guest's image or the manifest itself.

    ota_lite.py check --manifest M --host-role R --arch A
    ota_lite.py run --manifest M --host-role R --arch A --state DIR [--once] [--cpuset LIST] [--after-start CMD]
                    [--registry-file F] [--spool-dir D] [--status-dir D] [--runtime-dir D] [--docker-config D]
                    [--marker P] [--lock P] [--home D] [--docker PREFIX] [--kuksa HOST:PORT]
    ota_lite.py teardown [--docker PREFIX]
    ota_lite.py reprocess --state DIR
    ota_lite.py unit start (run's arguments) [--cpus LIST] [--python P] | unit stop | unit status

THE INTERFACES (spec section 2, word for word)
  spool    SPOOL_DIR/desired.json, the connector's two-field record (sdv/connector/spool.py is its writer and its
           definition); read here, never written.
  status   STATUS_DIR/status.json, written here only, by write_status(): exactly {"image_id", "scenario", "result"} in
           that order, compact, ASCII, at most 256 bytes, through .status.json.tmp and a rename, mode 0644. image_id is
           the config digest of the app container running when it was written, read from that container's own
           sdv.ota.image label (Docker's truth, never the state; null when none runs); scenario the one last accepted;
           result the outcome of the latest record processed: applied, rolled-back or refused. It never carries a
           cause. No status file exists before the first record is processed.
  start    app_run_argv(): spec 2.6's argv from `run` on (the Docker prefix goes in front), COMMON equal to
           sdv/stack/stack.py's (a test holds them equal), the image run by the reference whose config digest was
           proved, APP_IMAGE_ID the config digest.
  paths    SPOOL_DIR, STATUS_DIR, RUNTIME_DIR, DOCKER_CONFIG_DIR, TWIN_CONTROL_MARKER (spec 2.2); each is an argument.

ONE RECORD (manifest-classes.md section 5's decision order; first refusal wins; section 3 items 3 to 9)
  1  at most 256 bytes (257 are read; the 257th refuses); a symbolic link or anything but a regular file is refused;
  2  UTF-8 JSON, one object, no duplicate key;            3  spool.py's rules: exactly two fields, their forms, not
  both null;  4  a non-null image_id is a container entry;  5  of class app;  6  a non-null scenario is defined;
  7  the pair (the new image or the one Docker runs, the new or current scenario) is in that image's
     allowed_scenarios;
  8  a scenario request needs the twin-control marker (D11: without it every scenario request is refused) and then a
     free scenario lock (a non-blocking flock on --lock, held through the act; the file is never created here);
  bounds  the hour's starts leave room for every start the record may need (its own and, when there is a rollback
     target, a rollback's);
  act  for an image: get it (ecr: `docker pull` of the reference with <registry> replaced from --registry-file, with
     DOCKER_CONFIG the credentials directory, never a login and never an AWS call; tar: its sha256 checked, then
     `docker load`; local-build: the store ID), prove its config digest from a save stream (ota_docker.py), and only
     then stop (docker stop -t 10) and remove the old sdv-ota-app (one still there after both is refused at `stop`
     and nothing is started; a stop that worked before its rm failed leaves it stopped, which the status says), start
     the new one, run --after-start (shlex-split, never a shell, the container's name appended; non-zero is a failed
     start), and check its health (ota_health.py). A failed start or check stops and removes it and starts the
     rollback target (the state's `previous`) with the same flags, and checks that again: rolled-back. No rollback is
     started when the failed container could not be removed, or when the target's image has left the store (read by
     `docker image inspect`, so no `docker run` pulls it implicitly). A record for the current image that Docker runs
     as recorded is applied with no restart; a container Docker runs that the state does not record as current (a
     crash between a start and the state's write) is stopped and the requested image started and checked.
     For a scenario: its recording's sha256 checked, then the hand-off RUNTIME_DIR/scenario.json (the name, the
     recording's path and sha256; nothing in Phase 6 reads it), staged as .scenario.json.tmp before anything is
     touched (a stage that cannot be written refuses the record at `handoff`) and renamed into place only once the
     rest of the record is applied; a rollback or a refusal removes the stage. Should that rename fail after an image
     passed, the record is still applied, with the scenario unchanged and the cause in the log.
  A record equal in bytes to the last processed one is not processed again (the mark is kept in the state directory,
  so it holds across restarts; `reprocess` clears it). The mark is written before the act: no record is retried, and
  one pull at most is made per record.

THE STATE DIRECTORY (--state; never /var/lib, never inside the repo; it must exist)
  state.json      {"version": 1, "current", "previous", "scenario", "starts"}, an image as {"image_id", "name",
                  "app_version", "ref"} (an ecr reference kept as the manifest writes it, <registry> and all).
                  current: the image the updater last started that passed its check (null after a failed one), taken
                  as running only while Docker's own label on sdv-ota-app names it. previous: the rollback target, set
                  once a switch has removed the old container: the current image when Docker ran it as recorded at
                  the switch's start, else the previous one kept (a crashed or unknown image is never a rollback
                  target). scenario: the one last accepted. starts: the wall-clock times of the last hour's starts.
  processed       the mark of the last record processed.
  ota-lite.jsonl  the log: every record processed, each refusal by step and reason, each pull, load, proof, stop,
                  start, after-start, check, rollback, hand-off and status. It never holds a registry host, a
                  credential, a docker error text from a command that names the registry, or a value of the names file.
                  It is appended to without following a symbolic link (a link, or anything but a regular file, stops
                  the updater).

BOUNDS  at most STARTS_PER_HOUR container starts in any hour, rollbacks included; one pull per record; no retry.

Does not demonstrate: secure OTA (no signing, no secure boot, no root of trust; registry access control is not
signing), a platform or host rollback (only the app container moves), any timing, or that a heartbeat is a correct
app (it is the app's own report).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import ota_docker
import ota_health
import ota_manifest

SPOOL_DIR = "/run/sdv-local/spool/v1"
STATUS_DIR = "/run/sdv-local/status/v1"
RUNTIME_DIR = "/run/sdv-local/ota"
DOCKER_CONFIG_DIR = "/run/sdv-local/ota/docker"
TWIN_CONTROL_MARKER = "/run/sdv-local/twin-control"
SCENARIO_LOCK = "/run/lock/sdv-scenario.lock"        # the bridge's designated lock path (sdv/bridge/vss_claim_bridge.py)
APP_CONTAINER = "sdv-ota-app"
APP_LABEL = "sdv.ota.app"
IMAGE_LABEL = "sdv.ota.image"
UNIT = "ota-lite"
HOST_ROLES = ("pc", "a1-metal", "c7g-metal", "orin")   # sdv/stack/stack.py's HOST_ROLES and the schema's enum (a test)
KUKSA_ADDRESS = "127.0.0.1:55555"
HBH_LOG = "/out/hard-brake-hazard.jsonl"
OUT_TMPFS = "/out:rw,nosuid,nodev,noexec,size=16m"   # the one departure from manifest-classes:134-138 (spec 2.6)
COMMON = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-opt", "max-size=10m",
          "--memory", "512m", "--memory-swap", "512m"]  # sdv/stack/stack.py's COMMON, held equal by a test

SPOOL_FILE = "desired.json"
STATUS_FILE = "status.json"
STATUS_TMP = ".status.json.tmp"
SCENARIO_FILE = "scenario.json"
SCENARIO_TMP = ".scenario.json.tmp"
STATE_FILE = "state.json"
MARK_FILE = "processed"
LOG_FILE = "ota-lite.jsonl"
SPOOL_MAX_BYTES = 256
STATUS_MAX_BYTES = 256
REGISTRY_FILE_MAX_BYTES = 4096
RESULTS = ("applied", "rolled-back", "refused")
POLL_S = 1.0                    # the spool is read every second (spec section 3 item 3)
STARTS_PER_HOUR = 12            # a design value: the drill's few switches and their rollbacks, with room to spare
HOUR_S = 3600.0
AFTER_START_TIMEOUT_S = 30.0    # --after-start's bound per start, as the stack's SDV_AFTER_START
CPUSET_FORBIDDEN = (0, 1, 2, 4)  # the stack's rule: on the Orin QEMU's cores (0-2) and the probe's (4)
ACTIVE_STATES = ("active", "activating", "deactivating", "reloading", "refreshing")
REGISTRY_PLACEHOLDER = "<registry>"

_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_SCENARIO = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_NAME = re.compile(r"[a-z][a-z0-9]*(-[a-z][a-z0-9]*)*")
_REF = re.compile(r"sha256:[0-9a-f]{64}|[a-z0-9.-]+(:[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}")
_REGISTRY = re.compile(r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com")
_CPU = re.compile(r"0|[1-9][0-9]*")


class Refused(Exception):
    """A record refused at a step: the status says refused, the log says the step and the reason."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__("%s: %s" % (step, reason))
        self.step = step
        self.reason = reason


class SpoolRefused(Refused):
    """A spool record refused at step 1, 2 or 3 (its bytes, its JSON, its form)."""


class StatusRefused(ValueError):
    """A status record outside spec 2.4's rules: nothing is written."""


class _Duplicate(Exception):
    pass


def _no_duplicates(pairs: List[Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise _Duplicate()
        out[k] = v
    return out


def _no_constant(_name: str) -> Any:
    raise ValueError("NaN and Infinity are not JSON")


def image_id_ok(value: Any) -> bool:
    return isinstance(value, str) and _IMAGE_ID.fullmatch(value) is not None


def scenario_ok(value: Any) -> bool:
    return isinstance(value, str) and _SCENARIO.fullmatch(value) is not None


# --- placement and the start (spec 2.6, section 3 item 8) ----------------------------------------------------------

def cpu_list(value: Optional[str], role: str, what: str) -> Optional[str]:
    """A CPU list as given, or None when none is given off the Orin: the stack's rule (sdv/stack/stack.py,
    container_cpuset). Required on orin; refused when empty, when it is not N[,N...] of distinct decimal integers, or
    when it holds a core of CPUSET_FORBIDDEN, on every role. ValueError names the argument, never a host value."""
    if value is None:
        if role == "orin":
            raise ValueError("%s is required on the orin: the CPU list the app runs on (cores 0-2 are QEMU's and core 4 the "
                             "probe's, plan 3.7)" % what)
        return None
    if not value:
        raise ValueError("%s is empty: give a CPU list N[,N...]" % what)
    items = value.split(",")
    if not all(_CPU.fullmatch(i) for i in items):
        raise ValueError("%s is not a CPU list N[,N...] of decimal integers (no space, range or leading zero)" % what)
    cpus = [int(i) for i in items]
    if len(set(cpus)) != len(cpus):
        raise ValueError("%s names a CPU twice" % what)
    bad = sorted(set(cpus) & set(CPUSET_FORBIDDEN))
    if bad:
        raise ValueError("%s holds CPU %s: on the Orin cores 0-2 are QEMU's and core 4 the probe's (plan 3.7)"
                         % (what, ", ".join(str(c) for c in bad)))
    return value


def app_run_argv(name: str, image_id: str, reference: str, cpuset: Optional[str] = None) -> List[str]:
    """Spec 2.6's start of the app container, from `run` on: the Docker prefix goes in front. `reference` is the store
    ID or the reference by digest whose config digest was proved to be `image_id`; `cpuset` is given exactly when the
    updater has one. ValueError for a value that is not of its form (none can become a flag)."""
    if not (isinstance(name, str) and len(name) <= 32 and _NAME.fullmatch(name)):
        raise ValueError("the app's name is not a manifest name")
    if not image_id_ok(image_id):
        raise ValueError("the image_id is not a config digest")
    if not (isinstance(reference, str) and _REF.fullmatch(reference)):
        raise ValueError("the reference is neither a store ID nor a reference by digest")
    if cpuset is not None:
        cpu_list(cpuset, "", "the cpuset")
    return (["run", "-d", "--name", APP_CONTAINER, "--label", "%s=%s" % (APP_LABEL, name), "--label", "%s=%s" % (IMAGE_LABEL, image_id)]
            + list(COMMON) + (["--cpuset-cpus", cpuset] if cpuset is not None else [])
            + ["--network", "host", "--read-only", "--tmpfs", OUT_TMPFS,
               "-e", "APP_IMAGE_ID=" + image_id, "-e", "KUKSA_ADDRESS=" + KUKSA_ADDRESS, "-e", "HBH_LOG=" + HBH_LOG,
               "--restart", "no", reference])


# --- the status record (spec 2.4) ----------------------------------------------------------------------------------

def status_bytes(image_id: Optional[str], scenario: Optional[str], result: str) -> bytes:
    """The status file's bytes, or StatusRefused for a value outside the rules (the record never carries a cause)."""
    if image_id is not None and not image_id_ok(image_id):
        raise StatusRefused("image_id is not null or a config digest")
    if scenario is not None and not scenario_ok(scenario):
        raise StatusRefused("scenario is not null or a scenario name")
    if not (isinstance(result, str) and result in RESULTS):
        raise StatusRefused("result is not one of %s" % ", ".join(RESULTS))
    data = json.dumps({"image_id": image_id, "scenario": scenario, "result": result}, separators=(",", ":")).encode("ascii")
    if len(data) > STATUS_MAX_BYTES:
        raise StatusRefused("a status record of %d bytes" % len(data))
    return data


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def _write_tmp(directory: Path, tmp_name: str, data: bytes, mode: int) -> Path:
    tmp = directory / tmp_name
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        os.fchmod(fd, mode)
        _write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return tmp


def _atomic_write(directory: Path, name: str, tmp_name: str, data: bytes, mode: int) -> Path:
    tmp = _write_tmp(directory, tmp_name, data, mode)
    target = directory / name
    os.replace(str(tmp), str(target))
    return target


def write_status(directory: Any, image_id: Optional[str], scenario: Optional[str], result: str) -> Path:
    """Write DIRECTORY/status.json (spec 2.4) by write-then-rename through .status.json.tmp, mode 0644. Refuses a value
    outside the rules (StatusRefused, a ValueError) before any file is touched."""
    data = status_bytes(image_id, scenario, result)
    return _atomic_write(Path(directory), STATUS_FILE, STATUS_TMP, data, 0o644)


# --- the spool record (section 3 item 3) ---------------------------------------------------------------------------

def read_spool(directory: Any) -> Optional[bytes]:
    """At most SPOOL_MAX_BYTES + 1 bytes of DIRECTORY/desired.json, or None when there is none. A symbolic link, a
    directory, a FIFO or anything else that is not a regular file is SpoolRefused at step 1 (opened without following a
    link and without blocking)."""
    path = Path(directory) / SPOOL_FILE
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SpoolRefused("1", "the spool file cannot be opened as a regular file (%s)" % (exc.strerror or type(exc).__name__)) from None
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode):
            raise SpoolRefused("1", "the spool file is not a regular file")
        chunks: List[bytes] = []
        n = 0
        while n < SPOOL_MAX_BYTES + 1:
            b = os.read(fd, SPOOL_MAX_BYTES + 1 - n)
            if not b:
                break
            chunks.append(b)
            n += len(b)
        return b"".join(chunks)
    finally:
        os.close(fd)


def spool_problems(record: Any) -> List[str]:
    """spool.py's rules for the record's form (sdv/connector/spool.py, problems()): [] when it is one."""
    if not isinstance(record, dict) or len(record) != 2 or set(record) != {"image_id", "scenario"}:
        return ["the record's fields are not exactly the two of the spool"]
    out: List[str] = []
    if record["image_id"] is not None and not image_id_ok(record["image_id"]):
        out.append("image_id is not null or an image ID (sha256: and 64 lower-case hex digits)")
    if record["scenario"] is not None and not scenario_ok(record["scenario"]):
        out.append("scenario is not null or a scenario name (1 to 48 of a-z, 0-9 and '-', never a path)")
    if not out and record["image_id"] is None and record["scenario"] is None:
        out.append("both are null: the record asks for nothing")
    return out


def parse_spool(data: bytes) -> Dict[str, Optional[str]]:
    """The record in these bytes, or SpoolRefused at the first step it fails (1: size, 2: UTF-8 JSON, one object, no
    duplicate key, 3: the spool's form). No reason repeats a value."""
    if len(data) > SPOOL_MAX_BYTES:
        raise SpoolRefused("1", "the record is over %d bytes" % SPOOL_MAX_BYTES)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SpoolRefused("2", "the record is not UTF-8") from None
    try:
        obj = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except _Duplicate:
        raise SpoolRefused("2", "the record holds a duplicate key") from None
    except ValueError:
        raise SpoolRefused("2", "the record is not JSON") from None
    if not isinstance(obj, dict):
        raise SpoolRefused("2", "the record is not one JSON object")
    found = spool_problems(obj)
    if found:
        raise SpoolRefused("3", "; ".join(found))
    return {"image_id": obj["image_id"], "scenario": obj["scenario"]}


# --- files the updater reads -----------------------------------------------------------------------------------------

def registry_host(path: Optional[Any]) -> str:
    """The registry host from the pulling host's root-only file (spec 2.5; the `registry` key of the file `twinctl
    ecr-config` writes). ValueError, naming no value, when there is no file, it lies inside the repo, is not a regular
    file of its owner's only (no group or other bit), is over REGISTRY_FILE_MAX_BYTES, is not one JSON object, or its
    registry is not an ECR registry host."""
    if path is None:
        raise ValueError("no --registry-file: an ecr entry's registry host stands in that file only (D7)")
    p = Path(path)
    if ota_manifest.inside(p):
        raise ValueError("the registry file is inside the repo: it never enters the repo")
    try:
        fd = os.open(str(p), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        raise ValueError("the registry file cannot be opened (%s)" % (exc.strerror or type(exc).__name__)) from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("the registry file is not a regular file")
        if st.st_mode & 0o077:
            raise ValueError("the registry file's mode is %04o: it must be its owner's only (0600)" % stat.S_IMODE(st.st_mode))
        data = os.read(fd, REGISTRY_FILE_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > REGISTRY_FILE_MAX_BYTES:
        raise ValueError("the registry file is over %d bytes" % REGISTRY_FILE_MAX_BYTES)
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (_Duplicate, UnicodeDecodeError, ValueError):
        raise ValueError("the registry file is not one JSON object") from None
    host = obj.get("registry") if isinstance(obj, dict) else None
    if not isinstance(host, str) or not _REGISTRY.fullmatch(host):
        raise ValueError("the registry file's registry is not an ECR registry host")
    return host


def registry_file_problems(path: Optional[Any]) -> List[str]:
    """What `unit start` can say about the registry file without opening it: [] or why it refuses. The launcher runs as
    the login and the file is root-only on a pulling host (D7), so it never reads the content: no file named, a path
    inside the repo, a missing file, a symbolic link, anything but a regular file, or a group or other bit refuse; a
    file the login cannot even look up (a parent it may not search) passes. `run`, as root in the unit, reads the file
    (registry_host) before anything starts and refuses there."""
    if path is None:
        return ["no --registry-file: an ecr entry's registry host stands in that file only (D7)"]
    where = Path(path)
    if ota_manifest.inside(where):
        return ["the registry file is inside the repo: it never enters the repo"]
    try:
        st = os.lstat(str(where))
    except PermissionError:
        return []
    except OSError as exc:
        return ["the registry file cannot be looked up (%s)" % (exc.strerror or type(exc).__name__)]
    if stat.S_ISLNK(st.st_mode):
        return ["the registry file is a symbolic link"]
    if not stat.S_ISREG(st.st_mode):
        return ["the registry file is not a regular file"]
    if stat.S_IMODE(st.st_mode) & 0o077:
        return ["the registry file's mode is %04o: it must be its owner's only (0600)" % stat.S_IMODE(st.st_mode)]
    return []


def expand(path: str, home: str) -> str:
    """A manifest path with a leading '~/' put under `home` (the loader refuses '~user')."""
    if path == "~":
        return home
    if path.startswith("~/"):
        return os.path.join(home, path[2:])
    return path


def state_dir_problems(path: Any) -> List[str]:
    """Why `path` cannot be the updater's state directory: [] when it can (it exists; neither in the repo nor /var/lib)."""
    d = Path(path).expanduser()
    if ota_manifest.inside(d):
        return ["the state directory is inside the repo"]
    r = d.resolve()
    if r == Path("/var/lib") or Path("/var/lib") in r.parents:
        return ["the state directory is under /var/lib: Phase 6 leaves nothing there"]
    if not d.is_dir():
        return ["the state directory does not exist or is not a directory"]
    return []


def take_lock(path: Any) -> int:
    """A non-blocking exclusive flock on the scenario lock, returned as the open descriptor that holds it. The file is
    opened read-only and never created (the bridge's host file; one made here would be root's and refuse the bridge).
    Refused at step 8 when it cannot be opened, is not a regular file, or someone holds it."""
    import fcntl
    lock_path = str(path)
    try:
        fd = os.open(lock_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        raise Refused("8", "the scenario lock cannot be opened (%s), so it cannot be tested" % (exc.strerror or type(exc).__name__)) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refused("8", "the scenario lock is not a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused("8", "the scenario lock is held") from None
    except BaseException:
        os.close(fd)
        raise
    return fd


def run_hook(argv: Sequence[str]) -> int:
    """--after-start: argv (the container's name already appended), no shell, under AFTER_START_TIMEOUT_S. Its exit
    status; -1 when it timed out, -2 when it could not be started."""
    try:
        p = subprocess.run(list(argv), capture_output=True, text=True, timeout=AFTER_START_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return -1
    except OSError:
        return -2
    return p.returncode


def kuksa_source(address: str) -> Any:
    """The health check's source through kuksa-client: the one place ota_kuksa is imported."""
    import ota_kuksa
    return ota_kuksa.KuksaSource(address)


def _new_state() -> Dict[str, Any]:
    return {"version": 1, "current": None, "previous": None, "scenario": None, "starts": []}


def _image_rec_ok(v: Any) -> bool:
    return v is None or (isinstance(v, dict) and set(v) == {"image_id", "name", "app_version", "ref"}
                         and all(isinstance(v[k], str) for k in v) and image_id_ok(v["image_id"]))


# --- the updater -----------------------------------------------------------------------------------------------------

class Updater:
    """One host's updater over a loaded manifest. poll_once() reads the spool once and processes a new record."""

    def __init__(self, manifest: Dict[str, Any], state_dir: Any, *, spool_dir: Any = SPOOL_DIR, status_dir: Any = STATUS_DIR,
                 runtime_dir: Any = RUNTIME_DIR, docker_config: Any = DOCKER_CONFIG_DIR, marker: Any = TWIN_CONTROL_MARKER,
                 lock: Any = SCENARIO_LOCK, registry_file: Any = None, cpuset: Optional[str] = None,
                 after_start: Optional[Sequence[str]] = None, home: Optional[str] = None, kuksa: str = KUKSA_ADDRESS,
                 docker: Any = None, source_factory: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, hook: Callable[[Sequence[str]], int] = run_hook) -> None:
        self.manifest = manifest
        self.state_dir = Path(state_dir)
        self.spool_dir, self.status_dir, self.runtime_dir = Path(spool_dir), Path(status_dir), Path(runtime_dir)
        self.docker_config, self.marker, self.lock = Path(docker_config), Path(marker), Path(lock)
        self.registry_file = registry_file
        if cpuset is not None:
            cpu_list(cpuset, "", "the cpuset")
        self.cpuset = cpuset
        self.after_start = list(after_start) if after_start else None
        self.home = home if home is not None else os.path.expanduser("~")
        self.docker = docker if docker is not None else ota_docker.Docker()
        self.source_factory = source_factory if source_factory is not None else (lambda: kuksa_source(kuksa))
        self.clock, self.wall, self.sleep, self.hook = clock, wall, sleep, hook
        self._source: Any = None
        self.state = self._load_state()

    # -- the state, the mark, the log --

    def _load_state(self) -> Dict[str, Any]:
        p = self.state_dir / STATE_FILE
        if not p.exists():
            return _new_state()
        st = json.loads(p.read_text(encoding="utf-8"))
        ok = (isinstance(st, dict) and set(st) == set(_new_state()) and st["version"] == 1 and _image_rec_ok(st["current"])
              and _image_rec_ok(st["previous"]) and (st["scenario"] is None or scenario_ok(st["scenario"]))
              and isinstance(st["starts"], list) and all(isinstance(t, (int, float)) and not isinstance(t, bool) for t in st["starts"]))
        if not ok:
            raise ValueError("the state file %s is not the updater's" % p)
        return st

    def _save_state(self) -> None:
        data = json.dumps(self.state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        _atomic_write(self.state_dir, STATE_FILE, "." + STATE_FILE + ".tmp", data, 0o600)

    def _read_mark(self) -> Optional[str]:
        try:
            return (self.state_dir / MARK_FILE).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def _write_mark(self, mark: str) -> None:
        _atomic_write(self.state_dir, MARK_FILE, "." + MARK_FILE + ".tmp", mark.encode("utf-8"), 0o600)

    def log(self, event: str, **fields: Any) -> None:
        """One line appended to the log, opened without following a link and without blocking (OSError when the path
        is a link or anything but a regular file: the caller owns the state directory, root writes into it)."""
        rec: Dict[str, Any] = {"t_wall": round(self.wall(), 3), "event": event}
        rec.update(fields)
        data = (json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(str(self.state_dir / LOG_FILE), flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("the log %s is not a regular file" % LOG_FILE)
            _write_all(fd, data)
        finally:
            os.close(fd)

    # -- one record --

    def poll_once(self) -> Optional[str]:
        """Read the spool once; process the record when it is not the last one processed. The result written to the
        status, or None when nothing was processed."""
        data: Optional[bytes] = None
        unreadable: Optional[SpoolRefused] = None
        try:
            data = read_spool(self.spool_dir)
        except SpoolRefused as exc:
            unreadable = exc
        if data is not None:
            mark = "sha256:" + hashlib.sha256(data).hexdigest()
        elif unreadable is not None:
            mark = "unreadable: " + unreadable.reason
        else:
            return None
        if mark == self._read_mark():
            return None
        self._write_mark(mark)
        self.log("record", mark=mark)
        try:
            if unreadable is not None:
                raise unreadable
            assert data is not None
            rec = parse_spool(data)
            self.log("request", image_id=rec["image_id"], scenario=rec["scenario"])
            result = self._decide_and_act(rec)
        except Refused as exc:
            self.log("refused", step=exc.step, reason=exc.reason)
            result = "refused"
        self._write_status(result)
        return result

    def _write_status(self, result: str) -> None:
        image = self._running_image()
        try:
            write_status(self.status_dir, image, self.state["scenario"], result)
        except OSError as exc:
            self.log("status-error", error=exc.strerror or type(exc).__name__)
            return
        self.log("status", image_id=image, scenario=self.state["scenario"], result=result)

    def _decide_and_act(self, rec: Dict[str, Optional[str]]) -> str:
        img, scn = rec["image_id"], rec["scenario"]
        entry: Optional[Dict[str, Any]] = None
        if img is not None:
            entry = ota_manifest.container_entry(self.manifest, img)
            if entry is None:
                raise Refused("4", "the image ID is no container entry of the manifest")
            if entry["class"] != "app":
                raise Refused("5", "the image ID's entry is of class %s, not app: the updater never starts it" % entry["class"])
        scenario: Optional[Dict[str, Any]] = None
        if scn is not None:
            scenario = ota_manifest.scenario_entry(self.manifest, scn)
            if scenario is None:
                raise Refused("6", "the scenario is not defined in the manifest")
        pair_img = img if img is not None else self._running_image()
        pair_scn = scn if scn is not None else self.state["scenario"]
        if pair_img is not None and pair_scn is not None:
            pe = entry if img is not None else ota_manifest.app_entry(self.manifest, pair_img)
            if pe is None:
                raise Refused("7", "the running image is no app-class entry of the manifest, so no pair can be checked")
            if pair_scn not in pe["allowed_scenarios"]:
                raise Refused("7", "the pair of image and scenario is not in the image's allowed_scenarios")
        lock_fd: Optional[int] = None
        staged = False
        try:
            recording: Optional[Tuple[str, str]] = None
            if scenario is not None:
                if not os.path.exists(str(self.marker)):
                    raise Refused("8", "a scenario request with no twin-control marker: every one is refused (D11)")
                lock_fd = take_lock(self.lock)
                recording = self._verify_recording(scenario)
            switch = entry is not None and not self._runs(entry["image_id"])
            target = self._rollback_target() if switch else None
            if switch:
                self._admit(target)
            if scenario is not None and recording is not None:
                staged = True
                self._handoff_stage(scenario, *recording)
            result = "applied"
            if switch:
                assert entry is not None
                result = self._switch(entry, target)
            elif entry is not None:
                self.log("running", image_id=entry["image_id"], note="the requested image runs: no restart")
            if scenario is not None and staged and result == "applied":
                staged = False
                if not self._handoff_commit(scenario) and not switch:
                    raise Refused("handoff", "the scenario hand-off could not be renamed into place")
            return result
        finally:
            if staged:
                self._handoff_discard()
            if lock_fd is not None:
                os.close(lock_fd)

    def _running_image(self) -> Optional[str]:
        """Docker's truth: the config digest the running sdv-ota-app was started as, read from its own sdv.ota.image
        label; None when none runs or its label is not a config digest. The state is never asked."""
        if self.docker.status(APP_CONTAINER) != "running":
            return None
        label = self.docker.image_label(APP_CONTAINER)
        return label if image_id_ok(label) else None

    def _current_runs(self) -> bool:
        """Whether Docker runs the image the state records as current."""
        cur = self.state["current"]
        return cur is not None and self._running_image() == cur["image_id"]

    def _runs(self, image_id: str) -> bool:
        """Whether a record for `image_id` needs no restart: it is the current image, and Docker runs it as recorded."""
        cur = self.state["current"]
        return cur is not None and cur["image_id"] == image_id and self._current_runs()

    def _rollback_target(self) -> Optional[Dict[str, Any]]:
        """The image a failed switch goes back to: the current one when Docker runs it as recorded, else the previous
        one kept from an earlier switch (a crashed or unknown image is never a rollback target)."""
        return self.state["current"] if self._current_runs() else self.state["previous"]

    def _rollback_entry(self, prev: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """The previous image's entry when it is recorded and still an app-class entry of the manifest."""
        if prev is None:
            return None
        return ota_manifest.app_entry(self.manifest, prev["image_id"])

    def _recent_starts(self) -> List[float]:
        now = self.wall()
        return [t for t in self.state["starts"] if t > now - HOUR_S]

    def _admit(self, target: Optional[Dict[str, Any]]) -> None:
        needed = 1 + (1 if self._rollback_entry(target) is not None else 0)
        recent = len(self._recent_starts())
        if recent + needed > STARTS_PER_HOUR:
            raise Refused("bounds", "%d container starts in the last hour, and this record may need %d more: the bound is %d"
                          % (recent, needed, STARTS_PER_HOUR))

    def _verify_recording(self, scenario: Dict[str, Any]) -> Tuple[str, str]:
        path = expand(scenario["recording"]["path"], self.home)
        try:
            got = ota_docker.sha256_file(path)
        except OSError as exc:
            raise Refused("recording", "the recording cannot be read (%s)" % (exc.strerror or type(exc).__name__)) from None
        if got != scenario["recording"]["sha256"]:
            raise Refused("recording", "the recording's sha256 is not the manifest's")
        return path, got

    def _handoff_stage(self, scenario: Dict[str, Any], path: str, sha: str) -> None:
        """The hand-off written to its temporary file before anything is touched, or Refused at `handoff`."""
        data = json.dumps({"scenario": scenario["name"], "recording": {"path": path, "sha256": sha}}, separators=(",", ":")).encode("utf-8")
        try:
            _write_tmp(self.runtime_dir, SCENARIO_TMP, data, 0o644)
        except OSError as exc:
            why = exc.strerror or type(exc).__name__
            self.log("handoff-failed", stage="write", error=why)
            raise Refused("handoff", "the scenario hand-off cannot be written (%s): nothing is touched" % why) from None

    def _handoff_commit(self, scenario: Dict[str, Any]) -> bool:
        """The staged hand-off renamed into place and the scenario accepted; False (the stage removed, the cause logged)
        when the rename fails."""
        try:
            os.replace(str(self.runtime_dir / SCENARIO_TMP), str(self.runtime_dir / SCENARIO_FILE))
        except OSError as exc:
            self.log("handoff-failed", stage="rename", error=exc.strerror or type(exc).__name__)
            self._handoff_discard()
            return False
        self.state["scenario"] = scenario["name"]
        self._save_state()
        self.log("handoff", scenario=scenario["name"])
        return True

    def _handoff_discard(self) -> None:
        try:
            os.unlink(str(self.runtime_dir / SCENARIO_TMP))
        except OSError:
            pass

    # -- an image: get, prove, stop, start, check, roll back --

    def _runnable(self, ref: str) -> str:
        """A kept reference made runnable: <registry> replaced from the registry file (ValueError when it cannot be)."""
        if ref.startswith(REGISTRY_PLACEHOLDER + "/"):
            return registry_host(self.registry_file) + ref[len(REGISTRY_PLACEHOLDER):]
        return ref

    def _obtain(self, entry: Dict[str, Any]) -> Tuple[str, str, str]:
        """(the reference to run, the digest it names, the reference as the state keeps it), or Refused at pull or load
        before anything runs."""
        pull, img = entry["pull"], entry["image_id"]
        via = pull["via"]
        if via == "local-build":
            return pull["store_id"], pull["store_id"], pull["store_id"]
        if via == "tar":
            path = expand(pull["tar_path"], self.home)
            try:
                got = ota_docker.sha256_file(path)
            except OSError as exc:
                raise Refused("load", "the tar cannot be read (%s)" % (exc.strerror or type(exc).__name__)) from None
            if got != pull["tar_sha256"]:
                self.log("load", via="tar", image_id=img, exit=None, note="the tar's sha256 is not the manifest's: not loaded")
                raise Refused("load", "the tar's sha256 is not the manifest's")
            try:
                digest = ota_docker.tar_manifest_digest(path)
            except (ota_docker.ProofError, OSError) as exc:
                raise Refused("load", "the tar's index: %s" % ((exc.strerror or type(exc).__name__) if isinstance(exc, OSError) else exc)) from None
            r = self.docker.load(path)
            self.log("load", via="tar", image_id=img, exit=r.rc, err=r.err.replace(path, "<tar>").strip()[-300:] if r.rc else "")
            if r.rc != 0:
                raise Refused("load", "docker load: exit %d" % r.rc)
            return digest, digest, digest
        if via == "ecr":
            try:
                ref = self._runnable(pull["ref"])
            except ValueError as exc:
                raise Refused("pull", str(exc)) from None
            r = self.docker.pull(ref, self.docker_config)
            self.log("pull", via="ecr", image_id=img, exit=r.rc)
            if r.rc != 0:
                raise Refused("pull", "docker pull: exit %d" % r.rc)
            return ref, ota_docker.digest_of(ref), pull["ref"]
        raise Refused("pull", "an app's image comes by ecr, tar or local-build; %s is not the updater's" % via)

    def _switch(self, entry: Dict[str, Any], target: Optional[Dict[str, Any]]) -> str:
        """The act for an image; `target` is the rollback target read when the record's act began."""
        ref, digest, kept = self._obtain(entry)
        try:
            self.docker.prove(ref, digest, entry["image_id"])
        except (ota_docker.ProofError, ota_docker.DockerError) as exc:
            self.log("proof", image_id=entry["image_id"], ok=False, reason=str(exc))
            raise Refused("proof", str(exc)) from None
        self.log("proof", image_id=entry["image_id"], ok=True)
        if not self._stop_old():
            raise Refused("stop", "the old container is still there after docker stop and docker rm: nothing is started")
        self.state["previous"] = target
        self._save_state()
        if self._start_and_check(entry, ref):
            self.state["current"] = {"image_id": entry["image_id"], "name": entry["name"], "app_version": entry["app_version"],
                                     "ref": kept}
            self._save_state()
            return "applied"
        removed = self._stop_old()
        self.state["current"] = None
        target_entry = self._rollback_entry(target)
        runnable: Optional[str] = None
        why = ""
        if target is None:
            why = "no previous image recorded"
        elif target_entry is None:
            why = "the previous image is no longer an app-class entry of the manifest"
        elif not removed:
            why = "the started container could not be removed, so no other can take its name"
        else:
            try:
                runnable = self._runnable(target["ref"])
            except ValueError as exc:
                why = str(exc)
            else:
                if not self.docker.has_image(runnable):
                    why, runnable = "the previous image is no longer in the store: a docker run would pull it", None
        if runnable is None or target is None or target_entry is None:
            self.log("rollback", to=None, reason=why)
        else:
            self.log("rollback", to=target["image_id"])
            if self._start_and_check(target_entry, runnable):
                self.state["current"] = target
            else:
                self._stop_old()
        self._save_state()
        return "rolled-back"

    def _stop_old(self) -> bool:
        """Stop and remove sdv-ota-app when there is one; True when none is left, as Docker reads it back."""
        if self.docker.status(APP_CONTAINER) is None:
            return True
        s = self.docker.stop(APP_CONTAINER)
        r = self.docker.remove(APP_CONTAINER)
        gone = self.docker.status(APP_CONTAINER) is None
        self.log("stop", container=APP_CONTAINER, stop_exit=s.rc, rm_exit=r.rc, gone=gone)
        return gone

    def _source_now(self) -> Any:
        if self._source is None:
            try:
                self._source = self.source_factory()
            except Exception as exc:  # noqa: BLE001 -- no source is a failed check, logged by its kind only
                self.log("source-error", error=type(exc).__name__)
                return None
        return self._source

    def _start_and_check(self, entry: Dict[str, Any], ref: str) -> bool:
        now = self.wall()
        self.state["starts"] = self._recent_starts() + [now]
        self._save_state()
        argv = app_run_argv(entry["name"], entry["image_id"], ref, self.cpuset)
        r = self.docker.run(argv)
        fields: Dict[str, Any] = {"image_id": entry["image_id"], "name": entry["name"], "app_version": entry["app_version"], "exit": r.rc}
        if r.rc != 0 and "/" not in ref:
            fields["err"] = r.err.strip()[-300:]
        self.log("start", **fields)
        if r.rc != 0:
            return False
        if self.after_start:
            rc = self.hook(list(self.after_start) + [APP_CONTAINER])
            self.log("after-start", exit=rc)
            if rc != 0:
                return False
        source = self._source_now()
        if source is None:
            self.log("check", image_id=entry["image_id"], ok=False, reason="no AppState source", beats=0)
            return False
        ok, reason, beats = ota_health.check(source, entry["name"], entry["app_version"], entry["image_id"],
                                             lambda: self.docker.status(APP_CONTAINER), self.clock, self.sleep)
        self.log("check", image_id=entry["image_id"], ok=ok, reason=reason, beats=beats)
        return ok


# --- the commands ----------------------------------------------------------------------------------------------------

def _run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--manifest", required=True, help="the host's manifest, outside the repo")
    p.add_argument("--host-role", required=True, choices=HOST_ROLES)
    p.add_argument("--arch", required=True, choices=("amd64", "arm64"))
    p.add_argument("--state", required=True, help="the updater's state directory: it exists, never /var/lib, never in the repo")
    p.add_argument("--spool-dir", default=SPOOL_DIR)
    p.add_argument("--status-dir", default=STATUS_DIR)
    p.add_argument("--runtime-dir", default=RUNTIME_DIR)
    p.add_argument("--docker-config", default=DOCKER_CONFIG_DIR, help="DOCKER_CONFIG of every pull")
    p.add_argument("--marker", default=TWIN_CONTROL_MARKER, help="the twin-control marker (D11)")
    p.add_argument("--lock", default=SCENARIO_LOCK, help="the scenario lock (an flock; never created here)")
    p.add_argument("--registry-file", default=None, help="the pulling host's root-only file with the registry host")
    p.add_argument("--cpuset", default=None, help="the app container's CPU list; required on the orin")
    p.add_argument("--after-start", default=None, help="a command run after each start, the container's name appended")
    p.add_argument("--home", default=os.path.expanduser("~"), help="where a manifest path's '~/' points")
    p.add_argument("--docker", default="docker", help="the Docker command, shlex-split")
    p.add_argument("--kuksa", default=KUKSA_ADDRESS, help="the databroker the health check reads")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ota_lite.py", description="ota-lite: the app container's updater (SDV Phase 6)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="load the manifest and say whether it passes")
    c.add_argument("--manifest", required=True)
    c.add_argument("--host-role", required=True, choices=HOST_ROLES)
    c.add_argument("--arch", required=True, choices=("amd64", "arm64"))
    r = sub.add_parser("run", help="poll the spool every second and act on each new record")
    _run_args(r)
    r.add_argument("--once", action="store_true", help="read the spool once, act on a new record, and exit")
    t = sub.add_parser("teardown", help="stop and remove every container labelled sdv.ota.app")
    t.add_argument("--docker", default="docker")
    rp = sub.add_parser("reprocess", help="forget the last processed record, so the spool's record is processed again")
    rp.add_argument("--state", required=True)
    u = sub.add_parser("unit", help="the transient systemd unit ota-lite")
    us = u.add_subparsers(dest="unit_cmd", required=True)
    s = us.add_parser("start")
    _run_args(s)
    s.add_argument("--cpus", default=None, help="the unit's AllowedCPUs; required on the orin")
    s.add_argument("--python", default=sys.executable, help="the Python the unit runs (the venv with kuksa-client)")
    us.add_parser("stop")
    us.add_parser("status")
    return p


class Usage(Exception):
    pass


def _prepare(a: argparse.Namespace, launcher: bool = False) -> Tuple[Dict[str, Any], Optional[str], Optional[List[str]]]:
    """run's and unit start's checks, before anything starts: (the manifest, the cpuset, the after-start argv). With an
    ecr entry, `run` reads the registry file (registry_host); the launcher, which runs as the login, never opens that
    root-only file and checks only what its path shows (registry_file_problems)."""
    problems = state_dir_problems(a.state)
    if problems:
        raise Usage("; ".join(problems))
    try:
        m = ota_manifest.load(a.manifest, a.host_role, a.arch)
    except ota_manifest.ManifestRefused as exc:
        raise Usage("the manifest is refused: %s" % exc) from None
    try:
        cpuset = cpu_list(a.cpuset, a.host_role, "--cpuset")
    except ValueError as exc:
        raise Usage(str(exc)) from None
    after: Optional[List[str]] = None
    if a.after_start is not None:
        try:
            after = shlex.split(a.after_start)
        except ValueError as exc:
            raise Usage("--after-start cannot be split by shlex (%s)" % exc) from None
        if not after:
            raise Usage("--after-start is empty")
    if any(c.get("pull", {}).get("via") == "ecr" for c in m["components"] if c["class"] == "app"):
        if launcher:
            found = registry_file_problems(a.registry_file)
            if found:
                raise Usage("; ".join(found))
        else:
            try:
                registry_host(a.registry_file)
            except ValueError as exc:
                raise Usage(str(exc)) from None
    return m, cpuset, after


def _default_runner(cmd: Sequence[str]) -> Any:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)


def _unit_state(runner: Callable[[Sequence[str]], Any]) -> str:
    r = runner(["systemctl", "is-active", UNIT])
    return (r.stdout or "").strip() or "unknown"


def _unit_start(a: argparse.Namespace, runner: Callable[[Sequence[str]], Any]) -> int:
    _m, cpuset, _after = _prepare(a, launcher=True)
    try:
        cpus = cpu_list(a.cpus, a.host_role, "--cpus")
    except ValueError as exc:
        raise Usage(str(exc)) from None
    state = _unit_state(runner)
    if state in ACTIVE_STATES:
        raise Usage("a unit %s is %s: stop it first (unit stop)" % (UNIT, state))
    ab = os.path.abspath
    owner = (str(os.getuid()), str(os.getgid()))
    for path, mode, (uid, gid) in ((a.spool_dir, "0755", owner), (a.status_dir, "0755", ("root", "root")),
                                   (a.runtime_dir, "0700", ("root", "root")), (a.docker_config, "0700", ("root", "root"))):
        r = runner(["sudo", "-n", "install", "-d", "-m", mode, "-o", uid, "-g", gid, ab(path)])
        if r.returncode != 0:
            print("ota-lite: unit start: making %s failed (exit %d)" % (ab(path), r.returncode), file=sys.stderr)
            return 1
    run = ["run", "--manifest", ab(a.manifest), "--host-role", a.host_role, "--arch", a.arch, "--state", ab(a.state),
           "--spool-dir", ab(a.spool_dir), "--status-dir", ab(a.status_dir), "--runtime-dir", ab(a.runtime_dir),
           "--docker-config", ab(a.docker_config), "--marker", ab(a.marker), "--lock", ab(a.lock), "--home", ab(a.home),
           "--docker", a.docker, "--kuksa", a.kuksa]
    if a.registry_file is not None:
        run += ["--registry-file", ab(a.registry_file)]
    if cpuset is not None:
        run += ["--cpuset", cpuset]
    if a.after_start is not None:
        run += ["--after-start", a.after_start]
    cmd = (["sudo", "-n", "systemd-run", "--unit=" + UNIT, "--property=Type=exec", "--property=NoNewPrivileges=yes"]
           + (["--property=AllowedCPUs=" + cpus] if cpus is not None else [])
           + ["--collect", a.python, "-B", str(Path(__file__).resolve())] + run)
    r = runner(cmd)
    if r.returncode != 0:
        print("ota-lite: unit start: systemd-run failed (exit %d)" % r.returncode, file=sys.stderr)
        return 1
    state = _unit_state(runner)
    print("ota-lite: unit %s is %s" % (UNIT, state))
    return 0 if state == "active" else 1


def main(argv: Optional[Sequence[str]] = None, runner: Optional[Callable[[Sequence[str]], Any]] = None, docker: Any = None,
         source_factory: Optional[Callable[[], Any]] = None, clock: Optional[Callable[[], float]] = None,
         wall: Optional[Callable[[], float]] = None, sleep: Optional[Callable[[float], None]] = None,
         hook: Optional[Callable[[Sequence[str]], int]] = None) -> int:
    a = build_parser().parse_args(argv)
    run_cmd = runner if runner is not None else _default_runner
    try:
        if a.cmd == "check":
            try:
                m = ota_manifest.load(a.manifest, a.host_role, a.arch)
            except ota_manifest.ManifestRefused as exc:
                raise Usage("the manifest is refused: %s" % exc) from None
            apps = sum(1 for c in m["components"] if c["class"] == "app")
            print("ota-lite check: the manifest is ok: %d components (%d app-class), %d scenarios"
                  % (len(m["components"]), apps, len(m["scenarios"])))
            return 0
        if a.cmd == "reprocess":
            problems = state_dir_problems(a.state)
            if problems:
                raise Usage("; ".join(problems))
            mark = Path(a.state).expanduser() / MARK_FILE
            existed = mark.exists()
            if existed:
                mark.unlink()
            print("ota-lite reprocess: %s" % ("the mark is cleared: the spool's record is processed again" if existed
                                              else "no record was marked processed"))
            return 0
        if a.cmd == "teardown":
            d = docker if docker is not None else ota_docker.Docker(shlex.split(a.docker))
            names = d.labelled(APP_LABEL)
            for n in names:
                d.stop(n)
                d.remove(n)
            left = d.labelled(APP_LABEL)
            print("ota-lite teardown: %d container(s) labelled %s removed, %d left" % (len(set(names) - set(left)), APP_LABEL, len(left)))
            return 0 if not left else 1
        if a.cmd == "unit":
            if a.unit_cmd == "start":
                return _unit_start(a, run_cmd)
            if a.unit_cmd == "stop":
                r = run_cmd(["sudo", "-n", "systemctl", "stop", UNIT])
                state = _unit_state(run_cmd)
                print("ota-lite: unit %s is %s" % (UNIT, state))
                if r.returncode != 0 or state != "inactive":
                    return 1
                return 0
            state = _unit_state(run_cmd)
            print("ota-lite: unit %s is %s" % (UNIT, state))
            return 0 if state == "active" else 1
        # run
        m, cpuset, after = _prepare(a)
        u = Updater(m, a.state, spool_dir=a.spool_dir, status_dir=a.status_dir, runtime_dir=a.runtime_dir,
                    docker_config=a.docker_config, marker=a.marker, lock=a.lock, registry_file=a.registry_file, cpuset=cpuset,
                    after_start=after, home=a.home, kuksa=a.kuksa,
                    docker=docker if docker is not None else ota_docker.Docker(shlex.split(a.docker)),
                    source_factory=source_factory, clock=clock or time.monotonic, wall=wall or time.time,
                    sleep=sleep or time.sleep, hook=hook or run_hook)
        u.log("updater-start", host_role=a.host_role, arch=a.arch, components=len(m["components"]), cpuset=cpuset,
              after_start=after is not None, manifest_sha256=ota_docker.sha256_file(Path(a.manifest).expanduser()))
        if a.once:
            u.poll_once()
            return 0
        stopping: List[bool] = []

        def _stop(_signum: int, _frame: Any) -> None:
            stopping.append(True)
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        while not stopping:
            u.poll_once()
            u.sleep(POLL_S)
        u.log("updater-stop")
        return 0
    except Usage as exc:
        print("ota-lite: refused: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
