#!/usr/bin/env python3
"""drill.py -- the OTA drill: one host's manifest, the six steps against a running stack and updater, and the
cross-host compare (sdv/drill; SDV Phase 6 WP3).

Standard library only (it runs on the hosts' Python 3.12), and the connector's spool
writer (sdv/connector/spool.py, standard library itself), whose bytes the drill's records are.

    drill.py manifest --host-role R --arch amd64|arm64 --transport local-build|tar|ecr --stack-run DIR --out FILE
                      [--pins FILE] [--store-ids FILE] [--tar FILE] [--recording DIR]
    drill.py run      --manifest FILE --state DIR --record DIR --stack-run DIR --sim-python PY --ota-python PY
                      [--via spool|twin] [--cpuset LIST] [--registry-file F] [--docker-config D] [--home D]
                      [--spool-dir D] [--status-dir D] [--sudo PREFIX] [--docker PREFIX] [--step-timeout-s N]
    drill.py compare  --host ROLE=DIR [--host ROLE=DIR ...] --out DIR

EXIT STATUS  0: the run's own verdict is ok (compare: the sequences are equal). 1: it ran and the verdict is not ok
  (compare: they differ). 2: a refusal: nothing started, or what started was undone. `manifest` ends with the status
  of `ota_lite.py check` on what it wrote (2 when the drill refused before writing).

MANIFEST  One host's manifest (Phase 6 spec 2.5: manifest-classes section 9 with its changes) for the drill: the three
  versions of hard-brake-hazard (class app: v1 1.0.0, v2 1.1.0, v3 1.2.0, each allowed the drill's one scenario only),
  the claim bridge (class platform, the bridge's image of that architecture by its config digest, a local-build pull of
  its store ID: the updater never starts it), and the scenario of the stack run, naming its staged recording
  (in/sigsim.log) and its scenario table (ownership.json) by path and sha256. arm64's images come from --pins (default
  sdv/drill/drill-images.json) and the bridge's from sdv/stack/images.json's bridge.arm64 pin; amd64's, the bridge's
  included, from --store-ids (the file `build_drill.py build --arch amd64` writes outside the repo), on local-build only.
  --transport gives each app entry its pull: local-build its store ID; tar its own tar; ecr
  `<registry>/sdv-twin/hard-brake-hazard@<manifest digest>`, the placeholder and never a registry host (D7), the digest
  being the pin's ecr_manifest_digest where the pins file holds one (the registry's own, read back after `twinctl
  push` and added by the orchestrator) and its store ID otherwise. --tar is the save of the three arm64 IDs
  `build_drill.py save` writes (sdv-drill.tar): its index.json must list exactly the pins, each image proved there (a
  manifest, never an index; its config digest the pin's; every layer of its digest), and since the updater's tar
  transport takes a tar of one image (sdv/ota/ota_docker.py, tar_manifest_digest), it is split into one tar per version
  beside --out, in drill-tars/, each holding what a save of that one ID holds. A session's manifest and tars are never
  overwritten: an existing --out, and with tar transport an existing tar of drill-tars/, are refused, and so is an --out
  directory whose path holds a character outside the manifest's path form (the tars are named in it), before any tar is
  written. The host roles taken are sdv/stack/stack.py's HOST_ROLES, read from its source at run time; the updater's
  own check is the judge of the manifest. --recording, the sigsim recording directory the stack staged from, is a
  cross-check: its sigsim.log must hash to the staged copy's sha256, and its manifest line must name the scenario and
  that sha256.

RUN  The six steps against a stack already up (`stack.py up --feed vcan --app external`, the caller's: never started or
  stopped here) and a manifest already checked. Refused before anything starts: a stack run that is not up by stack.py's
  own record of it (its run manifest saying app external and this host's role, its up/ directory, its staged
  recording, and its databroker container running under its sdv.stack.run label), or whose CAN provider is not running
  (the recording on vcan0 reaches the databroker only through it: without it the app's inputs are never fresh, the app
  is degraded and no health check can pass); no vcan0; a QEMU that runs (D6: the drill runs without the guest); an
  sdv-ota-app container; an active unit ota-lite; the twin-control marker (SDV_TWIN_CONTROL_MARKER, by default
  /run/sdv-local/twin-control) existing; a record directory that exists; a state directory that holds anything (an
  earlier run's mark would change step 1); a record already in the spool; a manifest that is not a drill's; a
  --sim-python or --ota-python that is not an executable file; REPO_COMMIT set to anything but 40 hex digits; what
  `ota_lite.py unit start` would refuse only once the record directory is made (an ecr manifest without
  --registry-file, the orin without --cpuset); a --sudo prefix that cannot run `cat -- /dev/null` (the log and state are
  read through it). Then: the record and state directories made; the updater started with `ota_lite.py unit start`
  (its launcher calls sudo itself and is run as the login, so the spool directory it makes is the login's; --cpus is
  --cpuset when given; the marker's path passed; what the launcher says, stdout and stderr, is printed line by line to
  this output and never enters the record); the stack's staged recording played on vcan0 with `<sim python> -m
  can.player -i socketcan -c vcan0 <stack run>/in/sigsim.log`, again each time it ends. Per step: with
  --via spool the spool record written by spool.py; with --via twin `<record>/next-step.json` (the step's number and
  the record it expects) written and the record waited for in the spool (the connector writes it, from `config` desired
  that WP5's driver sets); then at most --step-timeout-s (300 by default, a design value) for the updater's answer: the
  first `status` event in its log after the `record` event of this record's mark (two refusals in a row write the same
  status bytes; their events tell them apart), and only then the status file read. A step with no answer is a problem
  and the next step runs. At the end, whatever happened, a stop signal included: the player stopped (one each of whose
  starts exited non-zero never played the recording: a problem), `ota_lite.py unit stop`, `ota_lite.py teardown`, and
  the updater's log and state (root's, mode 0600) copied into the record through --sudo. It never logs in to a
  registry and never reads a names file or the registry file (whose path it passes to the unit).

THE STEPS (spec-2 section 2.2)                                   expected status after it         refusal step (log)
  1  image v1                                                    1.0.0, null, applied             none
  2  image v2                                                    1.1.0, null, applied             none
  3  image v3                                                    1.1.0, null, rolled-back         none (a rollback event)
  4  the bridge's image (class platform)                         1.1.0, null, refused             5
  5  an image ID in no entry (UNKNOWN_IMAGE_ID, a documentation value)  1.1.0, null, refused      4
  6  the drill's scenario, no image, no marker                   1.1.0, null, refused             8

THE RECORD (--record)  drill-result.json (format 1): host_role, arch, transport, via, repo_commit (REPO_COMMIT, or
  null), manifest_sha256; per step n, asks, image_id (the status's, information: it differs by architecture), the
  status as app_version (the manifest's for that image_id; null when null), scenario and result, the log's refusal step
  (refused_step, or null), rollback (whether a rollback event came), waited_s (information, never judged) and timed_out;
  then the player's starts, the end's exits, the verdict (ok when every step equals the table and nothing else went
  wrong) and the problems. Beside it status-<n>.json (the status file's bytes after step n), the updater's
  ota-lite.jsonl and state.json, and with --via twin next-step.json. It holds no registry host, no credential and no
  host path; the updater's log is the updater's own.

COMPARE  Each --host directory's drill-result.json (its host_role ROLE's, its steps drill.py run's: steps 1 to k in
  order, k at most six, or it is refused) into DIR/compare.json: the sequence of (asks, app_version, scenario, result,
  refused_step) per step on every host, equal or the first difference with why (the hosts differ, a step missing on a
  host, or a step with no answer: result null). Equal means 2.2's six steps, each answered, the same on every host:
  records that lack the same step (runs refused or cut short alike), or whose same step got no answer, differ there.
  Image IDs differ by architecture and never enter the key. Exit 0 only when equal. An existing compare.json in --out,
  or an --out that exists and is not a directory, is refused (2).

Does not demonstrate: secure OTA; anything about the app beyond its own heartbeat (the updater's health check); that
v2's change shows on the bus or in the twin; with --via twin, anything about the twin but that the connector wrote
the record; any timing (waited_s is information only).
"""
from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import io
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STACK_FILE = REPO / "sdv" / "stack" / "stack.py"
IMAGES_FILE = REPO / "sdv" / "stack" / "images.json"
OTA_LITE = REPO / "sdv" / "ota" / "ota_lite.py"
CONNECTOR_DIR = REPO / "sdv" / "connector"
PINS_FILE = HERE / "drill-images.json"

sys.dont_write_bytecode = True
if str(CONNECTOR_DIR) not in sys.path:
    sys.path.insert(1, str(CONNECTOR_DIR))        # right after the script's own directory: no site-packages `spool` or `limits`
import spool  # noqa: E402  -- the connector's spool writer: the drill's records are its bytes

APP = "hard-brake-hazard"
BRIDGE = "vss-claim-bridge"
VERSIONS = ("1.0.0", "1.1.0", "1.2.0")          # v1, v2 and v3 (v3 never publishes one: its entry says 1.2.0)
ARCHES = ("amd64", "arm64")
TRANSPORTS = ("local-build", "tar", "ecr")
VIAS = ("spool", "twin")
ECR_REPOSITORY = "sdv-twin/" + APP               # spec 2.2: a constant namespace with no names-file value in it
REGISTRY_PLACEHOLDER = "<registry>"
UNKNOWN_IMAGE_ID = "sha256:" + "0123456789abcdef" * 4     # a documentation value: in no entry of any drill manifest
STEP_TIMEOUT_S = 300            # a design value: a pull, a start, a health check of 30 s and a rollback fit with room
POLL_S = 1.0                    # the updater reads the spool every second; the drill reads its log as often
PLAYER_RESTART_S = 1.0          # the least time between two starts of the player (one that fails at once does not spin)
PLAYER_STOP_S = 10.0
CALL_TIMEOUT_S = 120.0
VCAN = "vcan0"
SPOOL_DIR = "/run/sdv-local/spool/v1"
STATUS_DIR = "/run/sdv-local/status/v1"
TWIN_CONTROL_ENV = "SDV_TWIN_CONTROL_MARKER"
TWIN_CONTROL_MARKER = "/run/sdv-local/twin-control"
UNIT = "ota-lite"
ACTIVE_STATES = ("active", "activating", "deactivating", "reloading", "refreshing")
CPUSET_ROLE = "orin"            # ota_lite.py's cpu_list: the one role on which a CPU list is required
SUDO_PROBE = "/dev/null"        # read through --sudo before anything starts: the log and state are read the same way
APP_CONTAINER = "sdv-ota-app"
STACK_LABEL = "sdv.stack.run"
DATABROKER_CONTAINER = "sdv-stack-databroker"
CAN_PROVIDER_CONTAINER = "sdv-stack-can-provider"   # the app's two inputs reach the databroker from vcan0 only through it
PROC = "/proc"
NET_SYSFS = "/sys/class/net"
QEMU_COMMS = ("qemu-system", "qemu-kvm")         # a comm is cut at 15 characters: qemu-system-aar
RESULT_FILE = "drill-result.json"
NEXT_STEP_FILE = "next-step.json"
COMPARE_FILE = "compare.json"
LOG_FILE = "ota-lite.jsonl"
STATE_FILE = "state.json"
STATUS_FILE = "status.json"
STATUS_MAX_BYTES = 256
TAR_DIR = "drill-tars"
SMALL = 4 << 20                 # manifests, configs and index files are small; layers are streamed
MANIFEST_TYPES = ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json")
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
KEY = ("asks", "app_version", "scenario", "result", "refused_step")     # the cross-host key: never an image ID
# (n, asks, what the record asks for); the expected status after each: (app_version, scenario, result, refused_step,
# rollback), spec-2 section 2.2's table
STEPS: Tuple[Tuple[int, str, str], ...] = (
    (1, "image v1", "1.0.0"), (2, "image v2", "1.1.0"), (3, "image v3", "1.2.0"), (4, "the bridge's image", "bridge"),
    (5, "an image ID in no entry", "unknown"), (6, "the drill's scenario", "scenario"))
EXPECTED: Dict[int, Tuple[Optional[str], Optional[str], str, Optional[str], bool]] = {
    1: ("1.0.0", None, "applied", None, False), 2: ("1.1.0", None, "applied", None, False),
    3: ("1.1.0", None, "rolled-back", None, True), 4: ("1.1.0", None, "refused", "5", False),
    5: ("1.1.0", None, "refused", "4", False), 6: ("1.1.0", None, "refused", "8", False)}
JUDGED = ("app_version", "scenario", "result", "refused_step", "rollback")

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_PATH = re.compile(r"(~|/)[A-Za-z0-9._/-]{1,255}")      # the manifest schema's path form


class DrillError(RuntimeError):
    """A refusal, or a proof that failed. The message names no secret."""


class StartFailed(RuntimeError):
    """The updater or the player could not be started: what started is undone, and the run is a refusal."""


class Stopped(BaseException):
    """A stop signal: it passes every step's own handler, so the end still runs."""

    def __init__(self, signum: int) -> None:
        super().__init__("stopped by signal %d" % signum)
        self.signum = signum


class Done(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str]], Any]


def _raise_stopped(signum: int, _frame: Any) -> None:
    raise Stopped(signum)


def install_signals() -> None:
    """SIGTERM and SIGINT raise Stopped, so a run cut by its caller's cap still stops what it started."""
    signal.signal(signal.SIGTERM, _raise_stopped)
    signal.signal(signal.SIGINT, _raise_stopped)


def default_runner(cmd: Sequence[str]) -> Done:
    try:
        p = subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=CALL_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return Done(-1, "", "did not end within %g s" % CALL_TIMEOUT_S)
    except OSError as exc:
        return Done(-2, "", "could not be started: %s" % (exc.strerror or type(exc).__name__))
    return Done(p.returncode, p.stdout, p.stderr)


def default_popen(cmd: Sequence[str]) -> Any:
    return subprocess.Popen(list(cmd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- small helpers ---------------------------------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Any) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def digest_ok(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def inside_repo(path: Any) -> bool:
    r, top = Path(path).expanduser().resolve(), REPO.resolve()
    return r == top or top in r.parents


def read_json(path: Any, what: str) -> Any:
    try:
        with open(str(path), "rb") as f:
            data = f.read(SMALL + 1)
    except OSError as exc:
        raise DrillError("%s cannot be read (%s)" % (what, exc.strerror or type(exc).__name__)) from None
    if len(data) > SMALL:
        raise DrillError("%s is over %d bytes" % (what, SMALL))
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise DrillError("%s is not UTF-8 JSON" % what) from None


def write_json(path: Path, obj: Any) -> None:
    """The file written whole through a temporary name in its directory, LF line ends."""
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def host_roles() -> Tuple[str, ...]:
    """sdv/stack/stack.py's HOST_ROLES, read from its source (never imported: it loads the stack's modules)."""
    try:
        tree = ast.parse(Path(STACK_FILE).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        raise DrillError("stack.py's HOST_ROLES cannot be read (%s)" % type(exc).__name__) from None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HOST_ROLES" for t in node.targets):
            try:
                roles = ast.literal_eval(node.value)
            except ValueError:
                break
            if isinstance(roles, tuple) and roles and all(isinstance(r, str) for r in roles):
                return roles
            break
    raise DrillError("stack.py holds no HOST_ROLES tuple of names")


def abspath(path: Any) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def schema_path(path: Path, what: str) -> str:
    """An absolute path the manifest schema can name ([A-Za-z0-9._/-], no '..'), or DrillError."""
    p = str(path)
    if not _PATH.fullmatch(p) or "/../" in p + "/":
        raise DrillError("%s's path holds a character the manifest's path form does not take ([A-Za-z0-9._/-])" % what)
    return p


# --- images in a docker save ------------------------------------------------------------------------------------------

def image_of(get: Callable[[str], Optional[bytes]], digest: str) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """(the manifest, its config, the config digest) of the image whose manifest blob is `digest`, among blobs read
    by get(digest) (None when absent): the manifest hash-checked and one platform's image manifest (an index is
    refused), the config hash-checked. DrillError otherwise."""
    raw = get(digest)
    if raw is None:
        raise DrillError("the save holds no blob %s" % digest)
    if sha256_bytes(raw) != digest:
        raise DrillError("the blob %s does not hash to its digest" % digest)
    try:
        man = json.loads(raw)
    except ValueError:
        raise DrillError("the blob %s is not JSON" % digest) from None
    if not isinstance(man, dict):
        raise DrillError("the blob %s is not a manifest" % digest)
    if man.get("mediaType") in INDEX_TYPES or "manifests" in man:
        raise DrillError("%s names an index, not one platform's image manifest: an index is refused" % digest)
    if man.get("mediaType") not in MANIFEST_TYPES or not isinstance(man.get("config"), dict) or not isinstance(man.get("layers"), list):
        raise DrillError("%s is not one platform's image manifest" % digest)
    cd = man["config"].get("digest")
    if not digest_ok(cd):
        raise DrillError("the manifest %s names no config digest" % digest)
    craw = get(cd)
    if craw is None or sha256_bytes(craw) != cd:
        raise DrillError("the config %s is missing or does not hash to its digest" % cd)
    try:
        cfg = json.loads(craw)
    except ValueError:
        raise DrillError("the config %s is not JSON" % cd) from None
    if not isinstance(cfg, dict):
        raise DrillError("the config %s is not an object" % cd)
    return man, cfg, cd


class OciTar:
    """A `docker save` tar (an OCI layout) opened for reading: its regular files by name; a link refuses it."""

    def __init__(self, path: Any) -> None:
        self.path = Path(path)
        try:
            self.tf = tarfile.open(str(path), "r:")
        except (OSError, tarfile.TarError):
            raise DrillError("%s is not a tar that can be read" % self.path.name) from None
        self.members: Dict[str, tarfile.TarInfo] = {}
        try:
            for m in self.tf.getmembers():
                name = m.name[2:] if m.name.startswith("./") else m.name
                if m.issym() or m.islnk():
                    raise DrillError("%s holds a link (%s)" % (self.path.name, name))
                if m.isreg():
                    if name in self.members:
                        raise DrillError("%s holds %s twice" % (self.path.name, name))
                    self.members[name] = m
        except (tarfile.TarError, EOFError):
            self.tf.close()
            raise DrillError("%s is not a tar that can be read to its end" % self.path.name) from None
        except BaseException:
            self.tf.close()
            raise

    def __enter__(self) -> "OciTar":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.tf.close()

    def read(self, name: str, limit: int = SMALL) -> Optional[bytes]:
        m = self.members.get(name)
        if m is None or m.size > limit:
            return None
        f = self.tf.extractfile(m)
        return f.read() if f is not None else None

    def blob(self, digest: str) -> Optional[bytes]:
        return self.read("blobs/sha256/" + digest[7:]) if digest_ok(digest) else None

    def blob_hash(self, digest: str) -> Optional[str]:
        m = self.members.get("blobs/sha256/" + digest[7:]) if digest_ok(digest) else None
        f = self.tf.extractfile(m) if m is not None else None
        if f is None:
            return None
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
        return "sha256:" + h.hexdigest()

    def index(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        raw = self.read("index.json")
        try:
            idx = json.loads(raw) if raw is not None else None
        except ValueError:
            idx = None
        listed = idx.get("manifests") if isinstance(idx, dict) else None
        if not isinstance(idx, dict) or not isinstance(listed, list) or not all(isinstance(d, dict) for d in listed):
            raise DrillError("%s has no index.json listing its images (not an OCI layout)" % self.path.name)
        return idx, listed


def check_save(tar: OciTar, pins: Dict[str, Dict[str, str]], arch: str) -> Dict[str, Tuple[Dict[str, Any], Dict[str, Any], str]]:
    """The save against the pins: index.json lists exactly the pins' IDs, each once and as an image manifest (never an
    index); each image proved (image_of), its config digest the pin's, of `arch`, every layer present and of its digest.
    Per version: (its index descriptor, its manifest, its config digest)."""
    _idx, listed = tar.index()
    if sorted(str(d.get("digest")) for d in listed) != sorted(p["id"] for p in pins.values()):
        raise DrillError("%s's index.json lists other images than the pins' three" % tar.path.name)
    out: Dict[str, Tuple[Dict[str, Any], Dict[str, Any], str]] = {}
    for version, pin in pins.items():
        desc = next(d for d in listed if d.get("digest") == pin["id"])
        if desc.get("mediaType") not in MANIFEST_TYPES:
            raise DrillError("%s lists %s as %s, not one platform's image manifest: an index is refused"
                             % (tar.path.name, version, desc.get("mediaType")))
        man, cfg, cd = image_of(tar.blob, pin["id"])
        if cd != pin["config_digest"]:
            raise DrillError("%s's image %s has the config digest %s, its pin %s" % (tar.path.name, version, cd, pin["config_digest"]))
        if (cfg.get("os"), cfg.get("architecture")) != ("linux", arch):
            raise DrillError("%s's image %s is %s/%s, not linux/%s" % (tar.path.name, version, cfg.get("os"), cfg.get("architecture"), arch))
        for lay in man["layers"]:
            d = lay.get("digest") if isinstance(lay, dict) else None
            if not digest_ok(d) or tar.blob_hash(str(d)) != d:
                raise DrillError("%s's image %s: the layer %s is missing or not of its digest" % (tar.path.name, version, d))
        out[version] = (desc, man, cd)
    return out


def _add(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    ti = tarfile.TarInfo(name)
    ti.size, ti.mode, ti.mtime = len(data), 0o644, 0
    tf.addfile(ti, io.BytesIO(data))


def split_tar(out_dir: Path, version: str, arch: str) -> Path:
    """The path of one version's tar in out_dir (split_save's name for it)."""
    return out_dir / ("%s-%s-%s.tar" % (APP, version, arch))


def split_save(src: Path, pins: Dict[str, Dict[str, str]], arch: str, out_dir: Path) -> Dict[str, Tuple[Path, str]]:
    """The three-image save as one tar per version in out_dir, each holding what `docker save <that ID>` holds: its
    blobs, oci-layout, an index.json listing its one manifest (the save's own descriptor) and the legacy manifest.json's
    entry for it. Per version: (the tar, its sha256). Nothing is written before the save is checked (check_save)."""
    made: Dict[str, Tuple[Path, str]] = {}
    with OciTar(src) as tar:
        images = check_save(tar, pins, arch)
        idx, _listed = tar.index()
        layout = tar.read("oci-layout")
        legacy_raw = tar.read("manifest.json")
        try:
            legacy = json.loads(legacy_raw) if legacy_raw is not None else None
        except ValueError:
            legacy = None
        out_dir.mkdir(parents=True, exist_ok=True)
        for version, (desc, man, cd) in images.items():
            path = split_tar(out_dir, version, arch)
            tmp = path.with_name("." + path.name + ".tmp")
            wanted: List[str] = []
            for d in [pins[version]["id"], cd] + [str(lay["digest"]) for lay in man["layers"]]:
                if d not in wanted:
                    wanted.append(d)
            try:
                with tarfile.open(str(tmp), "w") as out:
                    for dname in ("blobs", "blobs/sha256"):
                        ti = tarfile.TarInfo(dname)
                        ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, 0o755, 0
                        out.addfile(ti)
                    for d in wanted:
                        m = tar.members["blobs/sha256/" + d[7:]]
                        ti = tarfile.TarInfo("blobs/sha256/" + d[7:])
                        ti.size, ti.mode, ti.mtime = m.size, 0o644, 0
                        out.addfile(ti, tar.tf.extractfile(m))
                    one = {k: v for k, v in idx.items() if k != "manifests"}
                    one["manifests"] = [desc]
                    _add(out, "index.json", json.dumps(one, separators=(",", ":")).encode("utf-8"))
                    if isinstance(legacy, list):
                        mine = [e for e in legacy if isinstance(e, dict) and e.get("Config") == "blobs/sha256/" + cd[7:]]
                        _add(out, "manifest.json", json.dumps(mine, separators=(",", ":")).encode("utf-8"))
                    if layout is not None:
                        _add(out, "oci-layout", layout)
                os.replace(str(tmp), str(path))
            finally:
                if tmp.exists():
                    tmp.unlink()
            made[version] = (path, sha256_file(path))
    return made


# --- the pins, the store IDs, the scenario ---------------------------------------------------------------------------

def _pair(obj: Any, id_key: str, what: str) -> Dict[str, str]:
    if not isinstance(obj, dict) or not digest_ok(obj.get(id_key)) or not digest_ok(obj.get("config_digest")):
        raise DrillError("%s is not {%s, config_digest} as sha256:<64 hex>" % (what, id_key))
    return {"id": obj[id_key], "config_digest": obj["config_digest"]}


def _distinct(pairs: Dict[str, Dict[str, str]], what: str) -> None:
    ids = [p[k] for p in pairs.values() for k in ("id", "config_digest")]
    if len(set(ids)) != len(ids):
        raise DrillError("%s names one digest twice" % what)


def read_pins(path: Any) -> Dict[str, Dict[str, str]]:
    """The arm64 pins of the three versions: drill-images.json's arm64.<version> {id, config_digest}, and its optional
    ecr_manifest_digest (the digest the registry reports after `twinctl push`, which the orchestrator adds when it is
    not the store's ID): the ecr pull's digest when it stands, the store ID otherwise. Every digest distinct, but a
    version's ecr_manifest_digest may be its own ID."""
    doc = read_json(path, "the pins file")
    arm = doc.get("arm64") if isinstance(doc, dict) else None
    if not isinstance(arm, dict):
        raise DrillError("the pins file has no arm64 pins")
    out = {v: _pair(arm.get(v), "id", "the pins file's arm64 %s" % v) for v in VERSIONS}
    _distinct(out, "the pins file")
    extra = []
    for v in VERSIONS:
        ecr = arm[v].get("ecr_manifest_digest")
        if ecr is None:
            continue
        if not digest_ok(ecr):
            raise DrillError("the pins file's arm64 %s ecr_manifest_digest is not sha256:<64 hex>" % v)
        out[v]["ecr_manifest_digest"] = ecr
        if ecr != out[v]["id"]:
            extra.append(ecr)
    known = [p[k] for p in out.values() for k in ("id", "config_digest")]
    if len(set(known + extra)) != len(known) + len(extra):
        raise DrillError("the pins file's ecr_manifest_digest names a digest another pin or version holds")
    return out


def read_store_ids(path: Any) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    """The PC's amd64 store IDs and config digests (build_drill.py build --arch amd64): the three versions and the
    bridge."""
    doc = read_json(path, "the store IDs file")
    if not isinstance(doc, dict) or doc.get("format") != 1 or doc.get("arch") != "amd64" or not isinstance(doc.get("images"), dict):
        raise DrillError("the store IDs file is not build_drill.py's amd64 file (format 1)")
    apps = {v: _pair(doc["images"].get(v), "store_id", "the store IDs file's %s" % v) for v in VERSIONS}
    bridge = _pair(doc.get("bridge"), "store_id", "the store IDs file's bridge")
    _distinct(dict(apps, bridge=bridge), "the store IDs file")
    return apps, bridge


def bridge_arm64() -> Dict[str, str]:
    """images.json's bridge.arm64 pin: the claim bridge's arm64 image, its config digest proved when it was pinned."""
    doc = read_json(IMAGES_FILE, "images.json")
    try:
        return _pair(doc["bridge"]["arm64"], "id", "images.json's bridge.arm64")
    except (KeyError, TypeError):
        raise DrillError("images.json has no bridge.arm64 pin") from None


def stack_manifest(stack_run: Path) -> Dict[str, Any]:
    doc = read_json(stack_run / "manifest.json", "the stack run's manifest.json (stack.py's run manifest)")
    if not isinstance(doc, dict) or doc.get("format") != 1:
        raise DrillError("the stack run's manifest.json is not stack.py's run manifest (format 1)")
    return doc


def scenario_entry(stack_run: Path, recording: Optional[Path]) -> Dict[str, Any]:
    """The stack run's scenario as a manifest scenario entry: its staged recording and its scenario table by path and
    sha256, its name, source and profile from ownership.json. With `recording` (the sigsim recording directory), that
    directory's sigsim.log must be the staged copy and its manifest line must name both."""
    own_path, log = stack_run / "ownership.json", stack_run / "in" / "sigsim.log"
    for p, what in ((own_path, "ownership.json"), (log, "in/sigsim.log")):
        if not p.is_file():
            raise DrillError("the stack run has no %s" % what)
    own = read_json(own_path, "the stack run's ownership.json")
    if not isinstance(own, dict) or not isinstance(own.get("recording"), dict):
        raise DrillError("the stack run's ownership.json is not stack.py's scenario table")
    staged = sha256_file(log)
    if recording is not None:
        line = read_json(recording / "manifest-line.json", "the recording's manifest-line.json")
        try:
            got = sha256_file(recording / "sigsim.log")
        except OSError:
            raise DrillError("the recording directory has no sigsim.log") from None
        listed = str((line.get("recording") or {}).get("sha256", "")) if isinstance(line, dict) else ""
        if got != staged or ("sha256:" + listed if not listed.startswith("sha256:") else listed) != staged:
            raise DrillError("the recording directory's sigsim.log is not the stack run's staged copy")
        if not isinstance(line, dict) or line.get("name") != own.get("scenario"):
            raise DrillError("the recording's manifest line names another scenario than the stack run's")
    return {"name": own.get("scenario"),
            "recording": {"path": schema_path(log, "the staged recording"), "sha256": staged, "format": own["recording"].get("format")},
            "source": own.get("source"), "profile_id": own.get("profile_id"),
            "ownership": {"file": schema_path(own_path, "the scenario table"), "sha256": sha256_file(own_path)}}


def build_manifest(host_role: str, arch: str, transport: str, apps: Dict[str, Dict[str, str]], bridge: Dict[str, str],
                   scenario: Dict[str, Any], tars: Optional[Dict[str, Tuple[Path, str]]]) -> Dict[str, Any]:
    written = today()
    comps: List[Dict[str, Any]] = []
    for v in VERSIONS:
        pin = apps[v]
        if transport == "local-build":
            pull: Dict[str, Any] = {"via": "local-build", "store_id": pin["id"]}
        elif transport == "tar":
            assert tars is not None
            pull = {"via": "tar", "tar_path": schema_path(tars[v][0], "a drill tar"), "tar_sha256": tars[v][1]}
        else:
            md = pin.get("ecr_manifest_digest", pin["id"])     # the registry's digest when the pins hold it
            pull = {"via": "ecr", "ref": "%s/%s@%s" % (REGISTRY_PLACEHOLDER, ECR_REPOSITORY, md), "manifest_digest": md}
        comps.append({"name": APP, "class": "app", "form": "container", "image_id": pin["config_digest"], "pull": pull,
                      "app_version": v, "allowed_scenarios": [scenario["name"]], "added": written})
    comps.append({"name": BRIDGE, "class": "platform", "form": "container", "image_id": bridge["config_digest"],
                  "pull": {"via": "local-build", "store_id": bridge["id"]}, "added": written})
    return {"manifest_version": 1, "host_role": host_role, "arch": arch, "written": written, "components": comps,
            "scenarios": [scenario]}


def cmd_manifest(a: argparse.Namespace, runner: Runner) -> int:
    try:
        roles = host_roles()
        if a.host_role not in roles:
            raise DrillError("--host-role %s: one of stack.py's HOST_ROLES (%s)" % (a.host_role, ", ".join(roles)))
        out = abspath(a.out)
        if inside_repo(out):
            raise DrillError("--out is inside the repo: a host's manifest never enters it (the updater refuses one there)")
        if not out.parent.is_dir():
            raise DrillError("--out's directory does not exist")
        if os.path.lexists(str(out)):
            raise DrillError("--out exists: a session's manifest is never overwritten")
        if a.transport == "tar" and any(os.path.lexists(str(split_tar(out.parent / TAR_DIR, v, a.arch))) for v in VERSIONS):
            raise DrillError("a drill tar exists in --out's %s/: a session's tars are never overwritten" % TAR_DIR)
        stack_run = abspath(a.stack_run)
        if not stack_run.is_dir():
            raise DrillError("--stack-run is not a directory")
        run_doc = stack_manifest(stack_run)
        if run_doc.get("host_role") != a.host_role:
            raise DrillError("the stack run is %s's, not %s's" % (run_doc.get("host_role"), a.host_role))
        if a.arch == "arm64":
            if a.store_ids is not None:
                raise DrillError("--store-ids is the amd64 images': arm64's come from --pins")
            apps = read_pins(a.pins if a.pins is not None else PINS_FILE)
            bridge = bridge_arm64()
        else:
            if a.pins is not None:
                raise DrillError("--pins is the arm64 images': amd64's come from --store-ids")
            if a.store_ids is None:
                raise DrillError("amd64 needs --store-ids (the file build_drill.py build --arch amd64 writes)")
            if a.transport != "local-build":
                raise DrillError("the amd64 images are the PC's local builds: tar and ecr carry the arm64 images only")
            apps, bridge = read_store_ids(a.store_ids)
        if (a.transport == "tar") != (a.tar is not None):
            raise DrillError("--tar goes with --transport tar, and only with it")
        if a.transport == "tar":
            for v in VERSIONS:             # the manifest names the split tars by path: refused here, before any is written
                schema_path(split_tar(out.parent / TAR_DIR, v, a.arch), "a drill tar")
        recording = abspath(a.recording) if a.recording is not None else None
        scenario = scenario_entry(stack_run, recording)
        tars = split_save(abspath(a.tar), apps, a.arch, out.parent / TAR_DIR) if a.transport == "tar" else None
        m = build_manifest(a.host_role, a.arch, a.transport, apps, bridge, scenario, tars)
        write_json(out, m)
    except DrillError as exc:
        print("drill.py manifest: refused: %s" % exc, file=sys.stderr)
        return 2
    r = runner([sys.executable, "-B", str(OTA_LITE), "check", "--manifest", str(out), "--host-role", a.host_role, "--arch", a.arch])
    for line in ((r.stdout or "") + (r.stderr or "")).splitlines():
        print("drill.py manifest: %s" % line)
    return int(r.returncode)


# --- run -------------------------------------------------------------------------------------------------------------

def outcome(events: Sequence[Dict[str, Any]], mark: str, start: int = 0) -> Optional[Dict[str, Any]]:
    """The updater's answer to the record whose mark (the sha256 of its bytes) is `mark`, from its log: the first
    `status` event after that record's `record` event, with the refusal step and whether a `rollback` event came
    between them; None while that status event has not come. Events before `start` are an earlier step's. Two records
    refused in a row write the same status bytes: their events tell them apart."""
    for i in range(start, len(events)):
        e = events[i]
        if e.get("event") == "record" and e.get("mark") == mark:
            for j in range(i + 1, len(events)):
                if events[j].get("event") == "status":
                    between = events[i + 1:j]
                    refused = [x.get("step") for x in between if x.get("event") == "refused"]
                    return {"status": events[j], "refused_step": refused[-1] if refused else None,
                            "rollback": any(x.get("event") == "rollback" for x in between)}
            return None
    return None


def app_versions(m: Dict[str, Any]) -> Dict[str, str]:
    """image_id -> app_version, from the manifest's app-class entries: a status's app_version is the manifest's for the
    image it names (image IDs differ by architecture; versions do not)."""
    return {c["image_id"]: c["app_version"] for c in m["components"] if c.get("class") == "app"}


def drill_ids(m: Any) -> Dict[str, Any]:
    """What the six steps ask for, from a drill manifest: the three versions' and the bridge's image IDs, the scenario,
    the transport. DrillError for a manifest that is not a drill's."""
    if not isinstance(m, dict) or not isinstance(m.get("components"), list) or not isinstance(m.get("scenarios"), list):
        raise DrillError("the manifest is not a host manifest")
    comps = [c for c in m["components"] if isinstance(c, dict)]
    apps = [c for c in comps if c.get("class") == "app"]
    platform = [c for c in comps if c.get("class") == "platform" and c.get("form") == "container"]
    if sorted(str(c.get("app_version")) for c in apps) != list(VERSIONS) or any(c.get("name") != APP for c in apps):
        raise DrillError("the manifest's app entries are not the drill's three versions of %s" % APP)
    if len(platform) != 1 or platform[0].get("name") != BRIDGE:
        raise DrillError("the manifest has not the one platform entry, the bridge")
    if len(m["scenarios"]) != 1 or not isinstance(m["scenarios"][0], dict):
        raise DrillError("the manifest has not the drill's one scenario")
    vias = {str((c.get("pull") or {}).get("via")) for c in apps}
    if len(vias) != 1 or not vias <= set(TRANSPORTS):
        raise DrillError("the manifest's app entries do not share one transport")
    out: Dict[str, Any] = {c["app_version"]: c.get("image_id") for c in apps}
    out.update(bridge=platform[0].get("image_id"), scenario=m["scenarios"][0].get("name"), transport=vias.pop())
    if not all(digest_ok(out[k]) for k in VERSIONS + ("bridge",)) or UNKNOWN_IMAGE_ID in [out[k] for k in VERSIONS + ("bridge",)]:
        raise DrillError("the manifest's image IDs are not config digests, or one is the drill's unknown one")
    if m.get("host_role") is None or m.get("arch") not in ARCHES:
        raise DrillError("the manifest names no host role or architecture")
    return out


def qemu_pids() -> List[int]:
    """The PIDs whose comm is a QEMU's, read from PROC; DrillError when PROC cannot be listed."""
    try:
        names = os.listdir(PROC)
    except OSError:
        raise DrillError("the process list cannot be read, so a QEMU cannot be ruled out") from None
    out = []
    for n in names:
        if not n.isdigit():
            continue
        try:
            with open(os.path.join(PROC, n, "comm"), encoding="utf-8", errors="replace") as f:
                comm = f.read().strip()
        except OSError:
            continue                                   # a process that ended while it was listed
        if comm.startswith(QEMU_COMMS):
            out.append(int(n))
    return sorted(out)


def marker_path() -> Path:
    raw = os.environ.get(TWIN_CONTROL_ENV)
    if raw is None:
        return Path(TWIN_CONTROL_MARKER)
    if not raw or not os.path.isabs(raw):
        raise DrillError("%s must be an absolute path (the twin-control marker; unset, %s)" % (TWIN_CONTROL_ENV, TWIN_CONTROL_MARKER))
    return Path(raw)


def marker_exists(path: Path) -> bool:
    """The stack's rule: any entry at the path is the marker, and one that cannot be looked for counts as one."""
    try:
        os.lstat(str(path))
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True
    return True


class Player:
    """The stack's staged recording on vcan0, started again each time it ends (a feed that ended inside a health window
    would make a good version look degraded)."""

    def __init__(self, cmd: Sequence[str], popen: Callable[[Sequence[str]], Any], clock: Callable[[], float]) -> None:
        self.cmd, self.popen, self.clock = list(cmd), popen, clock
        self.proc: Any = None
        self.starts = 0
        self.nonzero = 0
        self.last = 0.0
        self.stopped = False

    def start(self) -> None:
        self.proc = self.popen(self.cmd)
        self.starts += 1
        self.last = self.clock()

    def tick(self) -> None:
        if self.stopped:
            return
        if self.proc is not None:
            rc = self.proc.poll()
            if rc is None:
                return
            if rc != 0:
                self.nonzero += 1
            self.proc = None
        if self.clock() - self.last >= PLAYER_RESTART_S:
            self.start()

    def stop(self) -> bool:
        """Stop it; True when no player is left running."""
        self.stopped = True
        p, self.proc = self.proc, None
        if p is None:
            return True
        rc = p.poll()
        if rc is not None:
            if rc != 0:
                self.nonzero += 1             # it ended by itself before the stop: counted as tick() counts one
            return True
        p.terminate()
        try:
            p.wait(timeout=PLAYER_STOP_S)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=PLAYER_STOP_S)
        return p.poll() is not None

    def never_played(self) -> bool:
        """Every start exited non-zero (no python-can in the sim venv, no access to vcan0): the recording never played."""
        return self.starts > 0 and self.nonzero == self.starts

    def record(self) -> Dict[str, int]:
        return {"starts": self.starts, "nonzero_exits": self.nonzero}


class Run:
    """One drill run on this host."""

    def __init__(self, a: argparse.Namespace, runner: Runner, popen: Callable[[Sequence[str]], Any],
                 clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
        self.a, self.runner, self.popen, self.clock, self.sleep = a, runner, popen, clock, sleep
        self.sudo = shlex.split(a.sudo)
        self.docker = shlex.split(a.docker)
        self.via = a.via
        self.timeout = int(a.step_timeout_s)
        self.manifest_path = abspath(a.manifest)
        self.state, self.record = abspath(a.state), abspath(a.record)
        self.stack_run = abspath(a.stack_run)
        self.spool_dir, self.status_dir = abspath(a.spool_dir), abspath(a.status_dir)
        self.m: Dict[str, Any] = {}
        self.ids: Dict[str, Any] = {}
        self.versions: Dict[str, str] = {}
        self.marker = Path(TWIN_CONTROL_MARKER)
        self.commit: Optional[str] = None
        self.manifest_sha: Optional[str] = None
        self.problems: List[str] = []
        self.steps: List[Dict[str, Any]] = []
        self.player: Optional[Player] = None
        self.unit_started = False
        self.end_record: Dict[str, Any] = {}

    def ota(self, args: Sequence[str]) -> Any:
        return self.runner([self.a.ota_python, "-B", str(OTA_LITE)] + list(args))

    # -- before anything starts --

    def refusals(self) -> List[str]:
        out: List[str] = []
        raw = os.environ.get("REPO_COMMIT")
        if raw is not None and not _COMMIT.fullmatch(raw):
            out.append("REPO_COMMIT is set and is not a commit (40 lower-case hex digits)")
        self.commit = raw if raw is not None and _COMMIT.fullmatch(raw) else None
        if self.timeout <= 0:
            out.append("--step-timeout-s must be a positive number of seconds")
        try:
            self.marker = marker_path()
        except DrillError as exc:
            out.append(str(exc))
        try:
            self.m = read_json(self.manifest_path, "the manifest")
            self.ids = drill_ids(self.m)
            self.versions = app_versions(self.m)
            self.manifest_sha = sha256_file(self.manifest_path)
        except DrillError as exc:
            out.append(str(exc))
        try:
            doc = stack_manifest(self.stack_run)
            if doc.get("app") != "external":
                out.append("the stack run is not `up --app external`: its app is the stack's own")
            if self.m and doc.get("host_role") != self.m.get("host_role"):
                out.append("the stack run is %s's, the manifest %s's" % (doc.get("host_role"), self.m.get("host_role")))
        except DrillError as exc:
            out.append("the stack run is not up: %s" % exc)
        if not (self.stack_run / "up").is_dir():
            out.append("the stack run has no up/ directory: stack.py up has not run in it")
        if not (self.stack_run / "in" / "sigsim.log").is_file():
            out.append("the stack run has no staged recording in/sigsim.log")
        for opt, prog in (("--sim-python", self.a.sim_python), ("--ota-python", self.a.ota_python)):
            if not (os.path.isfile(prog) and os.access(prog, os.X_OK)):
                out.append("%s is not an executable file" % opt)
        # what ota_lite.py unit start would refuse only after the record directory is made
        if self.ids.get("transport") == "ecr" and self.a.registry_file is None:
            out.append("an ecr manifest needs --registry-file (the unit reads the registry host from it; it is never read here)")
        if self.m.get("host_role") == CPUSET_ROLE and self.a.cpuset is None:
            out.append("--cpuset is required on the %s (ota_lite.py's rule: the CPU list the app and the unit run on)" % CPUSET_ROLE)
        if not os.path.exists(os.path.join(NET_SYSFS, VCAN)):
            out.append("there is no %s: the drill plays the recording on it (--app external needs the vcan feed)" % VCAN)
        try:
            pids = qemu_pids()
            if pids:
                out.append("a QEMU runs (PID %s): the drill runs without the guest (owner decision D6)" % ", ".join(str(p) for p in pids))
        except DrillError as exc:
            out.append(str(exc))
        if marker_exists(self.marker):
            out.append("the twin-control marker exists: the drill's step 6 needs it absent (D11)")
        if os.path.lexists(str(self.record)):
            out.append("the record directory exists: a run's record is never reused")
        for path, what in ((self.record, "the record directory"), (self.state, "the state directory"), (self.manifest_path, "the manifest")):
            if inside_repo(path):
                out.append("%s is inside the repo" % what)
        if os.path.lexists(str(self.state)):
            if not self.state.is_dir():
                out.append("the state directory is not a directory")
            elif os.listdir(str(self.state)):
                out.append("the state directory holds files: an earlier run's mark or state would change what step 1 does")
        if os.path.lexists(str(self.spool_dir / spool.FILE)):
            out.append("a record is in the spool already: the updater would process it before step 1")
        r = self.runner(self.docker + ["ps", "--filter", "label=%s=%s/up" % (STACK_LABEL, self.stack_run.name), "--format", "{{.Names}}"])
        if r.returncode != 0:
            out.append("docker ps (the stack's containers) exited %d" % r.returncode)
        elif DATABROKER_CONTAINER not in (r.stdout or "").split():
            out.append("the stack run's databroker container is not running: the stack is not up")
        elif CAN_PROVIDER_CONTAINER not in (r.stdout or "").split():
            out.append("the stack run's CAN provider is not running: the recording played on vcan0 reaches the databroker only "
                       "through it, and without fresh inputs the app is degraded and no health check can pass")
        r = self.runner(self.docker + ["ps", "-a", "--filter", "name=^%s$" % APP_CONTAINER, "--format", "{{.Names}}"])
        if r.returncode != 0:
            out.append("docker ps (an %s container) exited %d" % (APP_CONTAINER, r.returncode))
        elif APP_CONTAINER in (r.stdout or "").split():
            out.append("an %s container exists: the updater's app is started by the drill's step 1 only" % APP_CONTAINER)
        r = self.runner(["systemctl", "is-active", UNIT])
        if (r.stdout or "").strip() in ACTIVE_STATES:
            out.append("a unit %s is %s: stop it first" % (UNIT, (r.stdout or "").strip()))
        r = self.runner(self.sudo + ["cat", "--", SUDO_PROBE])
        if r.returncode != 0:
            out.append("--sudo cannot run cat (exit %d): the updater's log and state are read through it, so every step "
                       "would wait its whole timeout" % r.returncode)
        return out

    # -- start --

    def unit_start_args(self) -> List[str]:
        args = ["unit", "start", "--manifest", str(self.manifest_path), "--host-role", str(self.m["host_role"]),
                "--arch", str(self.m["arch"]), "--state", str(self.state), "--spool-dir", str(self.spool_dir),
                "--status-dir", str(self.status_dir), "--marker", str(self.marker), "--docker", self.a.docker,
                "--python", self.a.ota_python]
        if self.a.cpuset is not None:
            args += ["--cpuset", self.a.cpuset, "--cpus", self.a.cpuset]
        for opt, value in (("--registry-file", self.a.registry_file), ("--docker-config", self.a.docker_config), ("--home", self.a.home)):
            if value is not None:
                args += [opt, str(abspath(value))]
        return args

    def start(self) -> None:
        try:
            self.record.mkdir(parents=True)
            self.state.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StartFailed("the record or state directory cannot be made (%s)" % (exc.strerror or type(exc).__name__)) from None
        self.unit_started = True                 # whatever unit start says, the end stops the unit
        r = self.ota(self.unit_start_args())
        print("drill.py run: ota_lite.py unit start exited %d" % r.returncode, flush=True)
        for line in ((r.stdout or "") + (r.stderr or "")).splitlines():      # the launcher's own words: this output only
            print("drill.py run: %s" % line, flush=True)
        if r.returncode != 0:
            raise StartFailed("ota_lite.py unit start exited %d" % r.returncode)
        cmd = [self.a.sim_python, "-m", "can.player", "-i", "socketcan", "-c", VCAN, str(self.stack_run / "in" / "sigsim.log")]
        self.player = Player(cmd, self.popen, self.clock)
        try:
            self.player.start()
        except OSError as exc:
            raise StartFailed("the player could not be started (%s)" % (exc.strerror or type(exc).__name__)) from None

    # -- the steps --

    def records(self) -> List[Tuple[int, str, Dict[str, Optional[str]]]]:
        out = []
        for n, asks, what in STEPS:
            if what in VERSIONS:
                rec = {"image_id": self.ids[what], "scenario": None}
            elif what == "bridge":
                rec = {"image_id": self.ids["bridge"], "scenario": None}
            elif what == "unknown":
                rec = {"image_id": UNKNOWN_IMAGE_ID, "scenario": None}
            else:
                rec = {"image_id": None, "scenario": self.ids["scenario"]}
            out.append((n, asks, rec))
        return out

    def tick(self) -> None:
        if self.player is not None:
            self.player.tick()

    def read_log(self) -> List[Dict[str, Any]]:
        """The updater's log (root's, 0600), read through --sudo."""
        r = self.runner(self.sudo + ["cat", "--", str(self.state / LOG_FILE)])
        if r.returncode != 0:
            return []
        events = []
        for line in (r.stdout or "").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict):
                events.append(e)
        return events

    def wait_spool(self, data: bytes) -> bool:
        deadline = self.clock() + self.timeout
        while True:
            self.tick()
            try:
                if (self.spool_dir / spool.FILE).read_bytes() == data:
                    return True
            except OSError:
                pass
            if self.clock() >= deadline:
                return False
            self.sleep(POLL_S)

    def wait_outcome(self, mark: str, start: int) -> Optional[Dict[str, Any]]:
        deadline = self.clock() + self.timeout
        while True:
            self.tick()
            found = outcome(self.read_log(), mark, start)
            if found is not None:
                return found
            if self.clock() >= deadline:
                return None
            self.sleep(POLL_S)

    def step(self, n: int, asks: str, rec: Dict[str, Optional[str]]) -> None:
        data = spool.encode(rec)
        mark = sha256_bytes(data)
        start = len(self.read_log())
        out: Dict[str, Any] = {"n": n, "asks": asks, "image_id": None, "app_version": None, "scenario": None, "result": None,
                               "refused_step": None, "rollback": False, "waited_s": None, "timed_out": False}
        self.steps.append(out)
        if self.via == "twin":
            write_json(self.record / NEXT_STEP_FILE, {"format": 1, "n": n, "asks": asks, "record": rec})
            if not self.wait_spool(data):
                out["timed_out"] = True
                self.problems.append("step %d (%s): its record did not reach the spool within %d s (the connector writes it "
                                     "from config desired)" % (n, asks, self.timeout))
                return
        else:
            spool.write(self.spool_dir, rec)
        t0 = self.clock()
        found = self.wait_outcome(mark, start)
        out["waited_s"] = round(self.clock() - t0, 1)
        if found is None:
            out["timed_out"] = True
            self.problems.append("step %d (%s): no status event in the updater's log within %d s" % (n, asks, self.timeout))
            return
        with open(str(self.status_dir / STATUS_FILE), "rb") as f:
            raw = f.read(STATUS_MAX_BYTES + 1)
        (self.record / ("status-%d.json" % n)).write_bytes(raw)
        try:
            st = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            st = None
        if not isinstance(st, dict) or list(st) != ["image_id", "scenario", "result"]:
            self.problems.append("step %d (%s): the status file is not the status record" % (n, asks))
            return
        img = st["image_id"]
        out.update(image_id=img, scenario=st["scenario"], result=st["result"], refused_step=found.get("refused_step"),
                   rollback=bool(found.get("rollback")), app_version=self.versions.get(img) if img is not None else None)
        if img is not None and img not in self.versions:
            self.problems.append("step %d (%s): the status names an image that is no app entry of the manifest" % (n, asks))
        for field, want in zip(JUDGED, EXPECTED[n]):
            if out[field] != want:
                self.problems.append("step %d (%s): %s is %r, the table's is %r" % (n, asks, field, out[field], want))
        print("drill.py run: step %d (%s): %s %s %s%s" % (n, asks, out["app_version"], out["scenario"], out["result"],
                                                         "" if out["refused_step"] is None else ", refused at %s" % out["refused_step"]),
              flush=True)

    # -- the end --

    def copy_out(self, name: str) -> bool:
        r = self.runner(self.sudo + ["cat", "--", str(self.state / name)])
        if r.returncode != 0:
            return False
        (self.record / name).write_text(r.stdout or "", encoding="utf-8")
        return True

    def end(self) -> None:
        """Whatever happened: the player stopped, the unit stopped, the updater's teardown, its log and state copied."""
        if signal.getsignal(signal.SIGTERM) is _raise_stopped:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        e = self.end_record
        try:
            stopped = self.player.stop() if self.player is not None else True
            e["player_stopped"] = stopped
            if not stopped:
                self.problems.append("the end: the player is still running")
        except Exception as exc:  # noqa: BLE001 -- the end goes on
            self.problems.append("the end: stopping the player: %s" % type(exc).__name__)
        if self.player is not None and self.player.never_played():
            self.problems.append("the player never played: each of its %d start(s) exited non-zero" % self.player.starts)
        try:
            if self.unit_started:
                u = self.ota(["unit", "stop"])
                e["unit_stop_exit"] = u.returncode
                if u.returncode != 0:
                    self.problems.append("the end: ota_lite.py unit stop exited %d" % u.returncode)
        except Exception as exc:  # noqa: BLE001
            self.problems.append("the end: ota_lite.py unit stop: %s" % type(exc).__name__)
        try:
            t = self.ota(["teardown", "--docker", self.a.docker])
            e["teardown_exit"] = t.returncode
            if t.returncode != 0:
                self.problems.append("the end: ota_lite.py teardown exited %d" % t.returncode)
        except Exception as exc:  # noqa: BLE001
            self.problems.append("the end: ota_lite.py teardown: %s" % type(exc).__name__)
        for name in (LOG_FILE, STATE_FILE):
            try:
                ok = self.copy_out(name)
            except Exception:  # noqa: BLE001
                ok = False
            e["copied_" + name.split(".")[0].replace("-", "_")] = ok
            if not ok:
                self.problems.append("the end: the updater's %s could not be copied into the record" % name)

    def result(self) -> Dict[str, Any]:
        ok = not self.problems and len(self.steps) == len(STEPS)
        return {"format": 1, "host_role": self.m.get("host_role"), "arch": self.m.get("arch"), "transport": self.ids.get("transport"),
                "via": self.via, "repo_commit": self.commit, "manifest_sha256": self.manifest_sha, "steps": self.steps,
                "player": self.player.record() if self.player is not None else {"starts": 0, "nonzero_exits": 0},
                "end": self.end_record, "verdict": "ok" if ok else "not ok", "problems": self.problems}


def exc_text(exc: BaseException) -> str:
    """An exception for the record: an OSError by its kind and strerror only (its text names the path), a DrillError
    by its own words (they name no path), anything else by its kind alone."""
    if isinstance(exc, OSError):
        return "%s (%s)" % (type(exc).__name__, exc.strerror or "no reason given")
    if isinstance(exc, DrillError):
        return str(exc)
    return type(exc).__name__


def cmd_run(a: argparse.Namespace, runner: Runner, popen: Callable[[Sequence[str]], Any], clock: Callable[[], float],
            sleep: Callable[[float], None]) -> int:
    r = Run(a, runner, popen, clock, sleep)
    refused = r.refusals()
    if refused:
        for why in refused:
            print("drill.py run: refused: %s" % why, file=sys.stderr)
        return 2
    undone = False
    res: Dict[str, Any] = {}
    try:
        try:
            r.start()
        except StartFailed as exc:
            r.problems.append(str(exc))
            undone = True
        if not undone:
            for n, asks, rec in r.records():
                try:
                    r.step(n, asks, rec)
                except Exception as exc:  # noqa: BLE001 -- a step that broke is a problem; the next one runs
                    r.problems.append("step %d (%s): %s" % (n, asks, exc_text(exc)))
    except Stopped as exc:
        r.problems.append("stopped by signal %d before the steps ended" % exc.signum)
    finally:
        r.end()
        res = r.result()
        try:
            write_json(r.record / RESULT_FILE, res)
        except OSError as exc:
            print("drill.py run: the record could not be written (%s)" % (exc.strerror or type(exc).__name__), file=sys.stderr)
    print("drill.py run: verdict %s%s" % (res["verdict"], "".join("\n  " + p for p in res["problems"])), flush=True)
    if undone:
        return 2
    return 0 if res["verdict"] == "ok" else 1


# --- compare ---------------------------------------------------------------------------------------------------------

def cmd_compare(a: argparse.Namespace) -> int:
    try:
        roles = host_roles()
        hosts: List[Tuple[str, Dict[str, Any]]] = []
        for spec in a.host:
            role, sep, d = spec.partition("=")
            if not sep or not role or not d:
                raise DrillError("--host %r: ROLE=DIR" % spec)
            if role not in roles:
                raise DrillError("--host %s: one of stack.py's HOST_ROLES (%s)" % (role, ", ".join(roles)))
            if role in [h[0] for h in hosts]:
                raise DrillError("--host %s is given twice" % role)
            doc = read_json(Path(d) / RESULT_FILE, "%s's drill-result.json" % role)
            if not isinstance(doc, dict) or doc.get("format") != 1 or not isinstance(doc.get("steps"), list):
                raise DrillError("%s's drill-result.json is not a drill record (format 1)" % role)
            if doc.get("host_role") != role:
                raise DrillError("%s's drill-result.json is %s's" % (role, doc.get("host_role")))
            steps = doc["steps"]
            if len(steps) > len(STEPS) or any(not isinstance(s, dict) or s.get("n") != i + 1 for i, s in enumerate(steps)):
                raise DrillError("%s's drill-result.json does not hold steps 1 to %d in order (drill.py run's)" % (role, len(STEPS)))
            hosts.append((role, doc))
        out = abspath(a.out)
        if out.exists() and not out.is_dir():
            raise DrillError("--out exists and is not a directory")
        if (out / COMPARE_FILE).exists():
            raise DrillError("%s exists in --out: a compare is never overwritten" % COMPARE_FILE)
    except DrillError as exc:
        print("drill.py compare: refused: %s" % exc, file=sys.stderr)
        return 2
    # equal means 2.2's six steps, each answered, the same on every host: a step missing (a run refused or cut short) or
    # without an answer (no status) on any host is a difference at that step, even when every host lacks it alike
    seqs = [[tuple(s.get(k) for k in KEY) for s in doc["steps"]] for _role, doc in hosts]
    first: Optional[Dict[str, Any]] = None
    for i in range(len(STEPS)):
        vals = [s[i] if i < len(s) else None for s in seqs]
        missing = [role for (role, _d), v in zip(hosts, vals) if v is None]
        unanswered = [role for (role, _d), v in zip(hosts, vals) if v is not None and v[KEY.index("result")] is None]
        if missing or unanswered or any(v != vals[0] for v in vals):
            why = ("no step %d on %s" % (i + 1, ", ".join(missing)) if missing else
                   "step %d has no answer on %s" % (i + 1, ", ".join(unanswered)) if unanswered else "the hosts differ")
            first = {"n": i + 1, "why": why,
                     "by_host": {role: (dict(zip(KEY, v)) if v is not None else None) for (role, _d), v in zip(hosts, vals)}}
            break
    doc_out = {"format": 1, "key": list(KEY),
               "hosts": [{"role": role, **{k: d.get(k) for k in ("arch", "transport", "via", "verdict", "manifest_sha256", "repo_commit")}}
                         for role, d in hosts],
               "sequence": [dict(zip(KEY, v)) for v in seqs[0]],
               "equal": first is None, "first_difference": first}
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / COMPARE_FILE, doc_out)
    print("drill.py compare: %s" % ("equal on %d host(s)" % len(hosts) if first is None
                                    else "the first difference is step %d (%s)" % (first["n"], first["why"])))
    return 0 if first is None else 1


# --- command line ----------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="drill.py", description="the OTA drill (SDV Phase 6 WP3)")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest", help="write one host's drill manifest and run the updater's check on it")
    m.add_argument("--host-role", required=True, help="one of stack.py's HOST_ROLES (read at run time)")
    m.add_argument("--arch", required=True, choices=ARCHES)
    m.add_argument("--transport", required=True, choices=TRANSPORTS)
    m.add_argument("--stack-run", required=True, help="the stack.py up run directory (its in/sigsim.log and ownership.json)")
    m.add_argument("--out", required=True, help="the manifest, outside the repo")
    m.add_argument("--pins", default=None, help="the arm64 pins (default sdv/drill/drill-images.json)")
    m.add_argument("--store-ids", default=None, help="the amd64 store IDs (build_drill.py build --arch amd64)")
    m.add_argument("--tar", default=None, help="--transport tar: the save of the three arm64 IDs (build_drill.py save)")
    m.add_argument("--recording", default=None, help="the recording directory the stack staged from (a cross-check)")
    r = sub.add_parser("run", help="the six steps against a running stack and the updater")
    r.add_argument("--manifest", required=True)
    r.add_argument("--state", required=True, help="the updater's state directory: empty or absent (made here)")
    r.add_argument("--record", required=True, help="the run's record directory: absent (made here)")
    r.add_argument("--stack-run", required=True)
    r.add_argument("--sim-python", required=True, help="the sim venv's python (python-can's player)")
    r.add_argument("--ota-python", required=True, help="the updater's venv python (kuksa-client): the unit runs it")
    r.add_argument("--via", choices=VIAS, default="spool", help="spool: the drill writes each record; twin: the connector does")
    r.add_argument("--cpuset", default=None, help="the app container's CPU list and the unit's AllowedCPUs")
    r.add_argument("--registry-file", default=None, help="passed to the unit (ecr): never read here")
    r.add_argument("--docker-config", default=None, help="passed to the unit")
    r.add_argument("--home", default=None, help="passed to the unit")
    r.add_argument("--spool-dir", default=SPOOL_DIR)
    r.add_argument("--status-dir", default=STATUS_DIR)
    r.add_argument("--sudo", default="sudo -n", help="the prefix that reads the updater's root-only log and state")
    r.add_argument("--docker", default="docker", help="the Docker command, shlex-split")
    r.add_argument("--step-timeout-s", type=int, default=STEP_TIMEOUT_S)
    c = sub.add_parser("compare", help="the six steps' sequences of several hosts")
    c.add_argument("--host", action="append", required=True, help="ROLE=DIR: a run's record directory")
    c.add_argument("--out", required=True)
    return p


def main(argv: Optional[Sequence[str]] = None, runner: Optional[Runner] = None, popen: Optional[Callable[[Sequence[str]], Any]] = None,
         clock: Optional[Callable[[], float]] = None, sleep: Optional[Callable[[float], None]] = None) -> int:
    a = build_parser().parse_args(argv)
    run_cmd = runner if runner is not None else default_runner
    if a.cmd == "manifest":
        return cmd_manifest(a, run_cmd)
    if a.cmd == "compare":
        return cmd_compare(a)
    return cmd_run(a, run_cmd, popen or default_popen, clock or time.monotonic, sleep or time.sleep)


if __name__ == "__main__":
    install_signals()
    sys.exit(main())
