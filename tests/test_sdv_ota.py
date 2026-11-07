"""test_sdv_ota.py -- the updater ota-lite (sdv/ota; SDV Phase 6 WP1).

Every test runs on stand-ins: Docker is a fake that interprets the argv the updater
builds (and once an executable stand-in, for the save stream's subprocess path); sudo, systemd-run and systemctl are a
recording runner; the AppState source is a fake fed from the fake Docker's containers; the clock is a fake one. Nothing
starts a container, reaches a registry or the network, or writes under /run, /etc or /var/lib.

What it holds (spec.md sections 2.4, 2.6 and 3, and section 7's WP1 mutants):
  * the interfaces: the module-level names, the app's start argv word for word with stack.COMMON verbatim inside it,
    and the status record (three keys, compact, ASCII, in order, at most 256 bytes, by write-then-rename, mode 0644,
    and never a value outside the rules);
  * the manifest's loader: manifest-classes section 9's schema with the spec's changes, the cross-entry checks, the
    given host role and arch, a manifest inside the repo refused; the standard-library validator agrees with
    jsonschema's draft 2020-12 validator (the vss venv) on every case;
  * the spool reader: every record the connector's writer writes is read back, every one its rules refuse is refused,
    at most 256 bytes (refused on the 257th), duplicate keys refused, a record equal in bytes to the last processed one
    not processed again, across restarts too, until `reprocess`;
  * decisions 4 to 8 with D11 (no scenario request without the twin-control marker; the lock rule with it);
  * getting and proving an image by ecr, tar and local-build, the proof before the running container is touched, an
    index refused; the health check, its source's calls each bounded; the rollback to the rollback target, never to
    a crashed image or one gone from the store; the hour's bound on starts; the cpuset rule; the transient unit, which
    never opens the root-only registry file; teardown; a log with no registry host, never written through a link;
  * Docker's truth over the state: the status's image and "no restart" read from the running container's own label,
    so a crash between a start and the state's write leaves no false status; an old container that cannot be removed
    refuses the record before any start; a scenario's hand-off staged before anything is touched;
  * the bounds a mutant run showed untested: the lock held through the act (a second process's flock), the mark written
    before the act (a crash mid-check), the twelfth start, the health deadline from both sides, the unit's absolute
    paths and its read-back, the run loop as a process (reprocess while it runs, SIGTERM), and the size bounds of the
    manifest and the registry file.

Every digest, date, account id and host here is a documentation value. Does not demonstrate: the updater against a real
Docker, a real databroker or a real app (WP5 and the drill), a pull through the credential provider, any timing, or
secure OTA.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import types
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OTA_DIR = REPO / "sdv" / "ota"
CONNECTOR_DIR = REPO / "sdv" / "connector"
STACK_DIR = REPO / "sdv" / "stack"
FIX = HERE / "fixtures" / "ota"
FIXTURE_MANIFEST = FIX / "manifest.json"

OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
REGISTRY = "123456789012.dkr.ecr.us-east-1.amazonaws.com"      # AWS's documentation account id
APP = "hard-brake-hazard"
S42, S43 = "20990101-sigsim-42", "20990101-sigsim-43-brake"
SPEC_COMMON = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-opt", "max-size=10m",
               "--memory", "512m", "--memory-swap", "512m"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _import(directory: Path, name: str) -> Any:
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    try:
        return importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved


@pytest.fixture(scope="module")
def ota() -> Any:
    """The updater's modules, imported as the unit imports them: by name, from sdv/ota."""
    mods = {n: _import(OTA_DIR, "ota_" + n) for n in ("lite", "manifest", "docker", "health")}
    for mod in mods.values():
        assert Path(str(mod.__file__)).resolve().parent == OTA_DIR.resolve(), mod.__file__
    return types.SimpleNamespace(**mods)


@pytest.fixture(scope="module")
def spool() -> Any:
    """The connector's spool writer, the definition the reader is held to (spec 2.3)."""
    return _import(CONNECTOR_DIR, "spool")


# --- fakes -------------------------------------------------------------------------------------------------------

class Img(NamedTuple):
    tag: str
    config: bytes
    image_id: str        # the config digest
    manifest: bytes
    store_id: str        # the manifest digest: the containerd store's ID of a built or loaded image

    def blobs(self) -> Dict[str, bytes]:
        return {self.store_id: self.manifest, self.image_id: self.config}


def make_image(tag: str, arch: str = "amd64") -> Img:
    config = json.dumps({"architecture": arch, "os": "linux", "config": {"Labels": {"t": tag}}}, sort_keys=True).encode()
    cfg = "sha256:" + _sha(config)
    man = json.dumps({"schemaVersion": 2, "mediaType": OCI_MANIFEST, "config": {"mediaType": OCI_CONFIG, "digest": cfg,
                      "size": len(config)}, "layers": []}, sort_keys=True).encode()
    return Img(tag, config, cfg, man, "sha256:" + _sha(man))


def make_index(img: Img) -> Tuple[bytes, str]:
    idx = json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [
        {"mediaType": OCI_MANIFEST, "digest": img.store_id, "size": len(img.manifest),
         "platform": {"architecture": "amd64", "os": "linux"}}]}, sort_keys=True).encode()
    return idx, "sha256:" + _sha(idx)


def save_tar(path: Path, img: Img, listed_type: str = OCI_MANIFEST) -> bytes:
    """A `docker save` tar of one image saved by its ID (an OCI layout); returns its bytes."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        def add(name: str, data: bytes) -> None:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        add("oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
        add("index.json", json.dumps({"schemaVersion": 2, "manifests": [
            {"mediaType": listed_type, "digest": img.store_id, "size": len(img.manifest)}]}).encode())
        add("blobs/sha256/" + img.store_id.split(":")[1], img.manifest)
        add("blobs/sha256/" + img.image_id.split(":")[1], img.config)
    data = buf.getvalue()
    path.write_bytes(data)
    return data


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0
        self.wall0 = 1900000000.0

    def mono(self) -> float:
        return self.t

    def time(self) -> float:
        return self.wall0 + self.t

    def sleep(self, dt: float) -> None:
        self.t += max(float(dt), 0.0)


class Container:
    def __init__(self, name: str, ref: str, image_id: str, labels: Dict[str, str], argv: List[str], t0: float) -> None:
        self.name, self.ref, self.image_id, self.labels, self.argv, self.t0 = name, ref, image_id, labels, argv, t0
        self.stopped_at: Optional[float] = None


def fake_docker(mod: Any, host: "Host") -> Any:
    """A Docker whose every command is interpreted here: the real class builds each argv, the fake answers it."""

    class FakeDocker(mod.Docker):  # type: ignore
        def __init__(self) -> None:
            super().__init__(["docker"])
            self.calls: List[Tuple[List[str], Optional[Dict[str, str]]]] = []
            self.store: Dict[str, Dict[str, bytes]] = {}
            self.pullable: Dict[str, Dict[str, bytes]] = {}
            self.containers: Dict[str, Container] = {}
            self.history: List[Container] = []
            self.run_rc = 0
            self.fail: set = set()       # "stop", "rm": that command ends non-zero and changes nothing

        def words(self) -> List[str]:
            return [c[0][0] if c[0][0] not in ("container", "image") else "inspect" for c in self.calls]

        def status_of(self, c: Container) -> str:
            if c.stopped_at is not None:
                return "exited"
            if host.behaviour.get(c.image_id) == "exits" and host.clock.t >= c.t0 + 2.0:
                return "exited"
            return "running"

        def call(self, args: Sequence[str], env: Optional[Dict[str, str]] = None, timeout: float = 120.0) -> Any:
            a = list(args)
            self.calls.append((a, dict(env) if env is not None else None))
            R = mod.Result
            if a[:1] == ["pull"]:
                if a[1] in self.pullable:
                    self.store[a[1]] = dict(self.pullable[a[1]])
                    return R(0, "", "")
                return R(1, "", "denied: %s not authorized for arn:aws:iam::123456789012:role/x" % a[1])
            if a[:2] == ["load", "-i"]:
                with tarfile.open(a[2], mode="r:") as tf:
                    blobs = {}
                    index = None
                    for m in tf:
                        f = tf.extractfile(m) if m.isreg() else None
                        if f is None:
                            continue
                        if m.name == "index.json":
                            index = json.loads(f.read())
                        elif m.name.startswith("blobs/sha256/"):
                            blobs["sha256:" + m.name.rsplit("/", 1)[1]] = f.read()
                assert index is not None
                self.store[index["manifests"][0]["digest"]] = blobs
                return R(0, "Loaded image ID: %s\n" % index["manifests"][0]["digest"], "")
            if a[:4] == ["container", "inspect", "--format", "{{.State.Status}}"]:
                c = self.containers.get(a[4])
                return R(0, self.status_of(c) + "\n", "") if c else R(1, "", "Error: No such container: %s" % a[4])
            if a[:4] == ["container", "inspect", "--format", '{{index .Config.Labels "sdv.ota.image"}}']:
                c = self.containers.get(a[4])
                return R(0, c.labels.get("sdv.ota.image", "<no value>") + "\n", "") if c else R(1, "", "Error: No such container")
            if a[:4] == ["image", "inspect", "--format", "{{.Id}}"]:
                return R(0, a[4] + "\n", "") if a[4] in self.store else R(1, "", "Error: No such image: %s" % a[4])
            if a[:3] == ["stop", "-t", "10"]:
                c = self.containers.get(a[3])
                if c is None:
                    return R(1, "", "No such container")
                if "stop" in self.fail:
                    return R(1, "", "Error response from daemon: cannot stop container")
                if c.stopped_at is None:
                    c.stopped_at = host.clock.t
                return R(0, a[3] + "\n", "")
            if a[:1] == ["rm"]:
                if "rm" in self.fail and a[1] in self.containers:
                    return R(1, "", "Error response from daemon: cannot remove container")
                return R(0, a[1] + "\n", "") if self.containers.pop(a[1], None) else R(1, "", "No such container")
            if a[:1] == ["ps"]:
                key = a[a.index("--filter") + 1].split("=", 1)[1]
                return R(0, "".join(n + "\n" for n, c in sorted(self.containers.items()) if key in c.labels), "")
            if a[:1] == ["run"]:
                if self.run_rc:
                    return R(self.run_rc, "", "docker: Error response from daemon")
                name = a[a.index("--name") + 1]
                if name in self.containers:
                    return R(125, "", "Conflict")
                ref = a[-1]
                if ref not in self.store:
                    return R(125, "", "Unable to find image")
                labels = dict(a[i + 1].split("=", 1) for i, w in enumerate(a) if w == "--label")
                env = dict(a[i + 1].split("=", 1) for i, w in enumerate(a) if w == "-e")
                c = Container(name, ref, env["APP_IMAGE_ID"], labels, a, host.clock.t)
                self.containers[name] = c
                self.history.append(c)
                return R(0, "0123abcd\n", "")
            return R(1, "", "unknown command")

        def save_blobs(self, ref: str) -> Dict[str, bytes]:
            self.calls.append((["save", ref], None))
            if ref not in self.store:
                raise mod.DockerError("docker save: exit 1")
            return dict(self.store[ref])

    return FakeDocker()


class FakeSource:
    """The databroker as the health check reads it: the latest heartbeat any container published, kept after its
    container stopped (the databroker keeps a signal's last value). A container publishes its first heartbeat 0.5 s
    after its start, then one a second, seq 1, 2, ...; its behaviour (Host.behaviour) may make it silent, degraded,
    exit after 2 s, or report another version."""

    def __init__(self, host: "Host") -> None:
        self.host = host
        self.reads = 0

    def record(self) -> Optional[Dict[str, Any]]:
        best: Optional[Tuple[float, Dict[str, Any]]] = None
        for c in self.host.docker.history:
            b = self.host.behaviour.get(c.image_id, "healthy")
            if b in ("silent", "exits"):
                continue
            end = c.stopped_at if c.stopped_at is not None else self.host.clock.t
            if end < c.t0 + 0.5:
                continue
            k = int((end - c.t0 - 0.5) // 1.0) + 1
            t_pub = c.t0 + 0.5 + (k - 1)
            rec = {"schema_version": 1, "app": c.labels["sdv.ota.app"],
                   "app_version": "9.9.9" if b == "other-version" else self.host.versions[c.image_id],
                   "image_id": c.image_id, "seq": k, "state": "degraded" if b == "degraded" else "running",
                   "hazard_requested": False, "actuate_result": "none"}
            if best is None or t_pub >= best[0]:
                best = (t_pub, rec)
        return best[1] if best else None

    def read(self, paths: Sequence[str]) -> Dict[str, Any]:
        self.reads += 1
        rec = self.record() or {}
        fields = self.host.fields
        return {p: rec.get(fields[p]) for p in paths}


class Host:
    """One host's worth of stand-ins and directories, under a directory whose path the manifest's path pattern takes."""

    def __init__(self, ota: Any, base: Path) -> None:
        self.ota, self.base = ota, base
        self.clock = FakeClock()
        self.v1, self.v2, self.v3 = make_image("v1"), make_image("v2"), make_image("v3")
        self.bridge, self.stranger = make_image("bridge"), make_image("stranger")
        self.versions = {self.v1.image_id: "1.0.0", self.v2.image_id: "1.1.0", self.v3.image_id: "1.2.0",
                         self.bridge.image_id: "0.1.0"}
        self.behaviour: Dict[str, str] = {}
        for d in ("state", "spool", "status", "runtime", "home"):
            (base / d).mkdir()
        self.state, self.spool_dir, self.status_dir, self.runtime = (base / d for d in ("state", "spool", "status", "runtime"))
        self.home = base / "home"
        self.docker_config = self.runtime / "docker"
        self.docker_config.mkdir()
        self.marker = base / "twin-control"
        self.lock = base / "scenario.lock"
        self.lock.write_bytes(b"")
        (self.home / "rec").mkdir()
        self.rec42, self.rec43 = self.home / "rec" / "42.log", self.home / "rec" / "43.log"
        self.rec42.write_bytes(b"(1.0) vcan0 123#00\n")
        self.rec43.write_bytes(b"(1.0) vcan0 123#01\n")
        self.tar = base / "v2.tar"
        self.tar_bytes = save_tar(self.tar, self.v2)
        self.registry_file = base / "registry.json"
        self.registry_file.write_text(json.dumps({"registry": REGISTRY, "region": "us-east-1",
                                                  "role_alias": "sdv-twin-ecr-pull"}), encoding="utf-8")
        os.chmod(self.registry_file, 0o600)
        self.docker = fake_docker(ota.docker, self)
        self.docker.store[self.v1.store_id] = self.v1.blobs()
        self.docker.store[self.bridge.store_id] = self.bridge.blobs()
        self.ecr_ref = REGISTRY + "/sdv-twin/hard-brake-hazard@" + self.v3.store_id
        self.docker.pullable[self.ecr_ref] = self.v3.blobs()
        self.source = FakeSource(self)
        _branch, self.fields = ota.health.leaf_fields(APP)
        self.hooks: List[List[str]] = []
        self.hook_rc = 0
        self.manifest_path = base / "manifest.json"
        self.write_manifest()

    def manifest_dict(self, host_role: str = "pc", arch: str = "amd64") -> Dict[str, Any]:
        both = [S42, S43]
        return {
            "manifest_version": 1, "host_role": host_role, "arch": arch, "written": "2099-01-02",
            "components": [
                {"name": APP, "class": "app", "form": "container", "image_id": self.v1.image_id,
                 "pull": {"via": "local-build", "store_id": self.v1.store_id}, "app_version": "1.0.0",
                 "allowed_scenarios": both, "added": "2099-01-01"},
                {"name": APP, "class": "app", "form": "container", "image_id": self.v2.image_id,
                 "pull": {"via": "tar", "tar_path": str(self.tar), "tar_sha256": "sha256:" + _sha(self.tar_bytes)},
                 "app_version": "1.1.0", "allowed_scenarios": both, "added": "2099-01-01"},
                {"name": APP, "class": "app", "form": "container", "image_id": self.v3.image_id,
                 "pull": {"via": "ecr", "ref": "<registry>/sdv-twin/hard-brake-hazard@" + self.v3.store_id,
                          "manifest_digest": self.v3.store_id},
                 "app_version": "1.2.0", "allowed_scenarios": [S42], "added": "2099-01-01"},
                {"name": "vss-claim-bridge", "class": "platform", "form": "container", "image_id": self.bridge.image_id,
                 "pull": {"via": "local-build", "store_id": self.bridge.store_id}, "added": "2099-01-01"},
            ],
            "scenarios": [
                {"name": S42, "recording": {"path": "~/rec/42.log", "sha256": "sha256:" + _sha(self.rec42.read_bytes()),
                                            "format": "candump-log"},
                 "source": {"generator": "sigsim", "vehicle": {"name": "sigsim-design-car", "wheelbase_mm": 2700},
                            "params": {"seed": 42}},
                 "profile_id": 1, "ownership": {"file": "~/rec/own42.json", "sha256": "sha256:" + "03" * 32}},
                {"name": S43, "recording": {"path": "~/rec/43.log", "sha256": "sha256:" + _sha(self.rec43.read_bytes()),
                                            "format": "candump-log"},
                 "source": {"generator": "sigsim", "vehicle": {"name": "sigsim-design-car", "wheelbase_mm": 2700},
                            "params": {"seed": 43}},
                 "profile_id": 1, "ownership": {"file": "~/rec/own43.json", "sha256": "sha256:" + "05" * 32}},
            ],
        }

    def write_manifest(self, m: Optional[Dict[str, Any]] = None) -> Path:
        self.manifest_path.write_text(json.dumps(m if m is not None else self.manifest_dict(), indent=1), encoding="utf-8")
        return self.manifest_path

    def hook(self, argv: Sequence[str]) -> int:
        self.hooks.append(list(argv))
        return self.hook_rc

    def updater(self, **kw: Any) -> Any:
        m = self.ota.manifest.load(self.manifest_path, kw.pop("host_role", "pc"), kw.pop("arch", "amd64"))
        args: Dict[str, Any] = dict(spool_dir=self.spool_dir, status_dir=self.status_dir, runtime_dir=self.runtime,
                                    docker_config=self.docker_config, marker=self.marker, lock=self.lock,
                                    registry_file=self.registry_file, cpuset=None, after_start=None, home=str(self.home),
                                    docker=self.docker, source_factory=lambda: self.source, clock=self.clock.mono,
                                    wall=self.clock.time, sleep=self.clock.sleep, hook=self.hook)
        args.update(kw)
        return self.ota.lite.Updater(m, self.state, **args)

    def spool(self, image_id: Optional[str] = None, scenario: Optional[str] = None, raw: Optional[bytes] = None) -> None:
        data = raw if raw is not None else json.dumps({"image_id": image_id, "scenario": scenario}, separators=(",", ":")).encode()
        (self.spool_dir / "desired.json").write_bytes(data)

    def status_bytes(self) -> Optional[bytes]:
        p = self.status_dir / "status.json"
        return p.read_bytes() if p.exists() else None

    def status(self) -> Dict[str, Any]:
        data = self.status_bytes()
        assert data is not None
        return json.loads(data)

    def log(self) -> List[Dict[str, Any]]:
        p = self.state / "ota-lite.jsonl"
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def started(self) -> List[str]:
        return [c.image_id for c in self.docker.history]


@pytest.fixture
def host(ota: Any, tmp_path_factory: Any) -> Host:
    return Host(ota, tmp_path_factory.mktemp("ota"))


def refusals(host: Host) -> List[Tuple[str, str]]:
    return [(e["step"], e["reason"]) for e in host.log() if e["event"] == "refused"]


def touching(host: Host) -> List[str]:
    """The docker commands that pull, load, save, stop, remove or start: everything but a read of a container's state."""
    return [w for w in host.docker.words() if w != "inspect"]


# --- the interfaces (spec 2.2, 2.4, 2.6) ---------------------------------------------------------------------------

def test_the_module_level_names_are_the_specs_constants(ota):
    lite = ota.lite
    assert lite.SPOOL_DIR == "/run/sdv-local/spool/v1"
    assert lite.STATUS_DIR == "/run/sdv-local/status/v1"
    assert lite.RUNTIME_DIR == "/run/sdv-local/ota"
    assert lite.DOCKER_CONFIG_DIR == "/run/sdv-local/ota/docker"
    assert lite.TWIN_CONTROL_MARKER == "/run/sdv-local/twin-control"
    assert lite.APP_CONTAINER == "sdv-ota-app"
    assert lite.UNIT == "ota-lite"
    assert callable(lite.app_run_argv) and callable(lite.write_status)
    assert (ota.health.DEADLINE_S, ota.health.BEATS) == (30.0, 3)
    assert lite.STARTS_PER_HOUR == 12


def test_the_poll_period_and_the_lock_path_are_the_specs(ota):
    """poll-every-0s (spec section 3 item 3: every second), lock-default-moved (the bridge image's designated path)."""
    assert ota.lite.POLL_S == 1.0
    assert ota.lite.SCENARIO_LOCK == _import(STACK_DIR, "stack").LOCK_IN_CONTAINER == "/run/lock/sdv-scenario.lock"


def test_run_sleeps_poll_s_between_two_reads_of_the_spool(host, ota):
    """run-loop-sleeps-5s: spec section 3 item 3, the spool is read every second (the loop sleeps POLL_S, not only defines it)."""
    import signal
    slept = []

    def sleep(s):
        slept.append(s)
        if len(slept) == 2:
            os.kill(os.getpid(), signal.SIGTERM)
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        rc = ota.lite.main(["run"] + _unit_args(host, "pc")[2:], docker=host.docker, source_factory=lambda: host.source,
                           clock=host.clock.mono, wall=host.clock.time, sleep=sleep, hook=host.hook)
    finally:
        for s, h in saved.items():
            signal.signal(s, h)
    assert rc == 0 and slept == [1.0, 1.0]


def test_app_run_argv_is_the_specs_start_word_for_word(ota):
    img = "sha256:" + "1" * 64
    ref = "sha256:" + "2" * 64
    tail = ["--network", "host", "--read-only", "--tmpfs", "/out:rw,nosuid,nodev,noexec,size=16m",
            "-e", "APP_IMAGE_ID=" + img, "-e", "KUKSA_ADDRESS=127.0.0.1:55555", "-e", "HBH_LOG=/out/hard-brake-hazard.jsonl",
            "--restart", "no", ref]
    head = ["run", "-d", "--name", "sdv-ota-app", "--label", "sdv.ota.app=" + APP, "--label", "sdv.ota.image=" + img]
    assert ota.lite.app_run_argv(APP, img, ref) == head + SPEC_COMMON + tail
    assert ota.lite.app_run_argv(APP, img, ref, "3,5") == head + SPEC_COMMON + ["--cpuset-cpus", "3,5"] + tail
    ecr = REGISTRY + "/sdv-twin/hard-brake-hazard@sha256:" + "3" * 64
    assert ota.lite.app_run_argv(APP, img, ecr)[-1] == ecr
    argv = ota.lite.app_run_argv(APP, img, ref, "3,5")
    assert not {"--privileged", "--user", "-u", "-v", "--volume", "--mount"} & set(argv)
    assert not any("docker.sock" in w for w in argv)


def test_app_run_argv_holds_the_stacks_common_flags_verbatim(ota):
    stack = _import(STACK_DIR, "stack")
    assert ota.lite.COMMON == stack.COMMON == SPEC_COMMON
    argv = ota.lite.app_run_argv(APP, "sha256:" + "1" * 64, "sha256:" + "2" * 64)
    i = argv.index(stack.COMMON[0])
    assert argv[i:i + len(stack.COMMON)] == stack.COMMON


@pytest.mark.parametrize("args", [
    (APP, "sha256:" + "1" * 64, "-v/var/run/docker.sock:/s"),
    (APP, "sha256:" + "1" * 64, "--privileged"),
    (APP, "sha256:" + "A" * 64, "sha256:" + "2" * 64),
    ("Hard-Brake", "sha256:" + "1" * 64, "sha256:" + "2" * 64),
    (APP, "sha256:" + "1" * 64, "sha256:" + "2" * 64, "3,4"),
    (APP, "sha256:" + "1" * 64, "sha256:" + "2" * 64, ""),
], ids=["a-flag-as-reference", "privileged-as-reference", "upper-case-image", "bad-name", "core-4", "empty-cpuset"])
def test_app_run_argv_refuses_a_value_that_could_change_the_start(ota, args):
    with pytest.raises(ValueError):
        ota.lite.app_run_argv(*args)


@pytest.mark.parametrize("values,expected", [
    (("sha256:" + "a" * 64, S42, "applied"), b'{"image_id":"sha256:' + b"a" * 64 + b'","scenario":"20990101-sigsim-42","result":"applied"}'),
    ((None, None, "refused"), b'{"image_id":null,"scenario":null,"result":"refused"}'),
    (("sha256:" + "0" * 64, None, "rolled-back"), b'{"image_id":"sha256:' + b"0" * 64 + b'","scenario":null,"result":"rolled-back"}'),
    ((None, "x" * 48, "applied"), b'{"image_id":null,"scenario":"' + b"x" * 48 + b'","result":"applied"}'),
])
def test_write_status_writes_the_three_keys_compact_in_order(ota, tmp_path, values, expected):
    old = os.umask(0o077)
    try:
        target = ota.lite.write_status(tmp_path, *values)
    finally:
        os.umask(old)
    assert target == tmp_path / "status.json"
    data = target.read_bytes()
    assert data == expected and len(data) <= 256
    data.decode("ascii")
    assert list(json.loads(data)) == ["image_id", "scenario", "result"]
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert sorted(p.name for p in tmp_path.iterdir()) == ["status.json"]


def test_write_status_is_write_then_rename(ota, tmp_path, monkeypatch):
    (tmp_path / "status.json").write_bytes(b"old")
    before = (tmp_path / "status.json").stat().st_ino
    seen: List[Tuple[str, str]] = []
    real = os.replace

    def spy(src: Any, dst: Any) -> None:
        seen.append((str(src), str(dst)))
        assert Path(dst).read_bytes() == b"old", "the file changed before the rename"
        real(src, dst)
    monkeypatch.setattr(ota.lite.os, "replace", spy)
    ota.lite.write_status(tmp_path, None, None, "refused")
    assert seen == [(str(tmp_path / ".status.json.tmp"), str(tmp_path / "status.json"))]
    assert (tmp_path / "status.json").stat().st_ino != before
    assert not (tmp_path / ".status.json.tmp").exists()


@pytest.mark.parametrize("values", [
    ("sha256:" + "A" * 64, None, "applied"), ("sha256:" + "a" * 63, None, "applied"), ("sha256:" + "a" * 64 + "\n", None, "applied"),
    (None, "Bad", "applied"), (None, "../etc", "applied"), (None, "x" * 49, "applied"), (None, "-x", "applied"),
    (None, None, "ok"), (None, None, "refused: the lock is held"), (None, None, None), (1, None, "applied"), (None, True, "applied"),
])
def test_write_status_refuses_a_value_outside_the_rules_and_touches_nothing(ota, tmp_path, values):
    with pytest.raises(ValueError):
        ota.lite.write_status(tmp_path, *values)
    assert list(tmp_path.iterdir()) == []


# --- the manifest (spec 2.5, section 3 item 2) -----------------------------------------------------------------------

def _fixture() -> Dict[str, Any]:
    return json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))


def _write(tmp: Path, m: Any, name: str = "manifest.json") -> Path:
    p = tmp / name
    p.write_text(json.dumps(m), encoding="utf-8")
    return p


def test_the_schema_is_manifest_classes_section_9_with_the_specs_changes(ota):
    schema = ota.manifest.load_schema()
    pulls = {p["properties"]["via"]["const"]: p for p in schema["$defs"]["pull"]["oneOf"]}
    assert pulls["local-build"]["required"] == ["via", "store_id"]
    assert pulls["local-build"]["properties"]["store_id"] == {"$ref": "#/$defs/sha256"}
    assert pulls["ecr"]["properties"]["ref"]["pattern"] == "^<registry>/sdv-twin/[a-z0-9][a-z0-9._-]*@sha256:[0-9a-f]{64}$"
    assert set(pulls) == {"ecr", "upstream", "tar", "local-build"}
    assert schema["$defs"]["sha256"]["pattern"] == "^sha256:[0-9a-f]{64}$"
    assert schema["$id"] == "urn:sdv-local:schema:manifest:1" and schema["additionalProperties"] is False


def test_the_fixture_manifest_loads_outside_the_repo(ota, tmp_path):
    m = ota.manifest.load(_write(tmp_path, _fixture()), "orin", "arm64")
    assert len(m["components"]) == 8 and len(m["scenarios"]) == 2


def test_a_manifest_inside_the_repo_is_refused(ota, tmp_path, capsys):
    with pytest.raises(ota.manifest.ManifestRefused) as exc:
        ota.manifest.load(FIXTURE_MANIFEST, "orin", "arm64")
    assert "inside the repo" in str(exc.value)
    link = tmp_path / "link.json"
    link.symlink_to(FIXTURE_MANIFEST)
    with pytest.raises(ota.manifest.ManifestRefused):
        ota.manifest.load(link, "orin", "arm64")
    assert ota.lite.main(["check", "--manifest", str(FIXTURE_MANIFEST), "--host-role", "orin", "--arch", "arm64"]) == 2
    assert "inside the repo" in capsys.readouterr().err


def _mutations() -> List[Tuple[str, Callable[[Dict[str, Any]], None]]]:
    """Each a manifest the schema refuses, from the fixture."""
    def comp(i: int, **kw: Any) -> Callable[[Dict[str, Any]], None]:
        def f(m: Dict[str, Any]) -> None:
            for k, v in kw.items():
                if v is None:
                    m["components"][i].pop(k, None)
                else:
                    m["components"][i][k] = v
        return f

    def top(**kw: Any) -> Callable[[Dict[str, Any]], None]:
        return lambda m: m.update(kw)

    def scen(i: int, **kw: Any) -> Callable[[Dict[str, Any]], None]:
        return lambda m: m["scenarios"][i].update(kw)
    return [
        ("a third key at the top", top(force=True)),
        ("manifest_version 2", top(manifest_version=2)),
        ("an unknown host role", top(host_role="laptop")),
        ("an unknown arch", top(arch="riscv64")),
        ("a written date that is no date", top(written="2099-1-2")),
        ("a component with mounts", comp(0, mounts=["/var/run/docker.sock:/s"])),
        ("a name with a word starting with a digit", comp(0, name="x-1a")),
        ("a name with a double hyphen", comp(0, name="a--b")),
        ("a name of 33 characters", comp(0, name="a" * 33)),
        ("an upper-case image id", comp(0, image_id="sha256:" + "A" * 64)),
        ("an app with no version", comp(0, app_version=None)),
        ("an app with no allowed scenarios", comp(0, allowed_scenarios=None)),
        ("an empty allowed list", comp(0, allowed_scenarios=[])),
        ("an allowed list with a repeat", comp(0, allowed_scenarios=[S42, S42])),
        ("an app that is a replay source", comp(0, replay_source=True)),
        ("an app as a host unit", comp(0, form="host-unit")),
        ("a platform entry with a version", comp(3, app_version="1.0.0")),
        ("a container with no pull", comp(0, pull=None)),
        ("an ecr ref with the registry host in it", comp(0, pull={"via": "ecr", "ref": REGISTRY + "/sdv-twin/x@sha256:" + "2" * 64,
                                                                  "manifest_digest": "sha256:" + "2" * 64})),
        ("an ecr ref outside sdv-twin/", comp(0, pull={"via": "ecr", "ref": "<registry>/example/x@sha256:" + "2" * 64,
                                                       "manifest_digest": "sha256:" + "2" * 64})),
        ("an ecr ref by tag", comp(0, pull={"via": "ecr", "ref": "<registry>/sdv-twin/x:1.1.0", "manifest_digest": "sha256:" + "2" * 64})),
        ("a local build without its store id", comp(2, pull={"via": "local-build"})),
        ("a local build with a short store id", comp(2, pull={"via": "local-build", "store_id": "sha256:" + "9" * 63})),
        ("a tar path with a parent segment", comp(1, pull={"via": "tar", "tar_path": "~/a/../b.tar", "tar_sha256": "sha256:" + "4" * 64})),
        ("a relative tar path", comp(1, pull={"via": "tar", "tar_path": "images/b.tar", "tar_sha256": "sha256:" + "4" * 64})),
        ("a host unit with an image", comp(7, image_id="sha256:" + "1" * 64)),
        ("a host unit of class app", comp(7, **{"class": "app"})),
        ("a scenario name with a dot", scen(0, name="a.b")),
        ("profile 0", scen(0, profile_id=0)),
        ("a wheelbase of 999", scen(0, source={"generator": "sigsim", "vehicle": {"name": "c", "wheelbase_mm": 999}, "params": {}})),
        ("a carla recording with no rtf", scen(1, source={"generator": "carla", "vehicle": {"name": "c", "wheelbase_mm": 2700}, "params": {}})),
        ("a sigsim recording with an rtf", scen(0, source={"generator": "sigsim", "vehicle": {"name": "c", "wheelbase_mm": 2700},
                                                           "params": {}, "rtf": {"min": 1, "mean": 1, "max": 1}})),
        ("an rtf of 0", scen(1, source={"generator": "carla", "vehicle": {"name": "c", "wheelbase_mm": 2700}, "params": {},
                                        "rtf": {"min": 0, "mean": 1, "max": 1}})),
        ("nine params", scen(0, source={"generator": "sigsim", "vehicle": {"name": "c", "wheelbase_mm": 2700},
                                        "params": {str(i): i for i in range(9)}})),
        ("a recording of another format", scen(0, recording={"path": "~/r.log", "sha256": "sha256:" + "1" * 64, "format": "pcap"})),
        # four parts, joined: written out, the value reads as an IPv4 address to tests/test_no_real_identifiers.py
        ("an app_version of four parts", comp(0, app_version=".".join(["1", "1", "0", "0"]))),
        ("an app_version with a leading zero", comp(0, app_version="01.1.0")),
        ("a form that is neither", comp(0, form="vm")),
        ("a class that is neither", comp(0, **{"class": "system"})),
        ("an added date with slashes", comp(0, added="2099/01/02")),
        ("a unit name without .service", comp(7, unit="ota-lite")),
        ("seventeen files on a host unit", comp(7, files=[{"path": "/x%d" % i, "sha256": "sha256:" + "e" * 64} for i in range(17)])),
        ("a tar_sha256 without its prefix", comp(1, pull={"via": "tar", "tar_path": "~/x.tar", "tar_sha256": "4" * 64})),
        ("an upstream ref by tag", comp(5, pull={"via": "upstream", "ref": "ghcr.io/x/y:1", "manifest_digest": "sha256:" + "a" * 64})),
        ("a vehicle name with a capital", scen(0, source={"generator": "sigsim", "vehicle": {"name": "Car", "wheelbase_mm": 2700}, "params": {}})),
        ("profile 256", scen(0, profile_id=256)),
        ("a param of 65 characters", scen(0, source={"generator": "sigsim", "vehicle": {"name": "c", "wheelbase_mm": 2700},
                                                      "params": {"town": "x" * 65}})),
        ("a param that is a list", scen(0, source={"generator": "sigsim", "vehicle": {"name": "c", "wheelbase_mm": 2700},
                                                    "params": {"seed": [1]}})),
        ("an ownership path with a space", scen(0, ownership={"file": "~/a b.json", "sha256": "sha256:" + "3" * 64})),
    ]


@pytest.mark.parametrize("what,mutate", _mutations(), ids=[w for w, _f in _mutations()])
def test_the_loader_refuses_each_schema_violation(ota, tmp_path, what, mutate):
    m = _fixture()
    mutate(m)
    assert ota.manifest.validate(ota.manifest.load_schema(), m) != [], what
    with pytest.raises(ota.manifest.ManifestRefused):
        ota.manifest.load(_write(tmp_path, m), "orin", "arm64")


def _cross() -> List[Tuple[str, Callable[[Dict[str, Any]], None]]]:
    """Each a manifest the schema takes and a cross-entry check refuses (manifest-classes:73-76, and the loader's own)."""
    def dup_pair(m: Dict[str, Any]) -> None:
        m["components"].append(dict(m["components"][0], added="2099-01-05"))

    def both_classes(m: Dict[str, Any]) -> None:
        m["components"][3]["image_id"] = m["components"][0]["image_id"]

    def one_image_two_names(m: Dict[str, Any]) -> None:
        m["components"].append(dict(m["components"][2], name="other-app"))     # a local build: no ecr repository to differ

    def undefined(m: Dict[str, Any]) -> None:
        m["components"][1]["allowed_scenarios"] = ["20990101-undefined"]

    def two_replay(m: Dict[str, Any]) -> None:
        m["components"][4]["replay_source"] = True

    def rtf(m: Dict[str, Any]) -> None:
        m["scenarios"][1]["source"]["rtf"] = {"min": 0.9, "mean": 0.75, "max": 1.0}

    def two_scenarios_one_name(m: Dict[str, Any]) -> None:
        m["scenarios"].append(dict(m["scenarios"][0]))

    def ecr_repo(m: Dict[str, Any]) -> None:
        m["components"][0]["pull"]["ref"] = "<registry>/sdv-twin/other-app@sha256:" + "2" * 64

    def ecr_digest(m: Dict[str, Any]) -> None:
        m["components"][0]["pull"]["manifest_digest"] = "sha256:" + "f" * 64

    def other_home(m: Dict[str, Any]) -> None:
        m["components"][1]["pull"]["tar_path"] = "~root/x.tar"
    return [("a repeated (name, image_id)", dup_pair), ("one image in both classes", both_classes),
            ("one image under two names", one_image_two_names), ("an allowed scenario that is not defined", undefined),
            ("two replay sources", two_replay), ("an rtf whose mean is below its min", rtf),
            ("two scenarios of one name", two_scenarios_one_name), ("an ecr repository that is not sdv-twin/<name>", ecr_repo),
            ("an ecr manifest digest that is not the ref's", ecr_digest), ("a path in another account's home", other_home)]


@pytest.mark.parametrize("what,mutate", _cross(), ids=[w for w, _f in _cross()])
def test_the_loader_refuses_each_cross_entry_check(ota, tmp_path, what, mutate):
    m = _fixture()
    mutate(m)
    assert ota.manifest.validate(ota.manifest.load_schema(), m) == [], what
    with pytest.raises(ota.manifest.ManifestRefused):
        ota.manifest.load(_write(tmp_path, m), "orin", "arm64")


@pytest.mark.parametrize("role,arch", [("pc", "arm64"), ("a1-metal", "arm64"), ("c7g-metal", "arm64"), ("orin", "amd64")])
def test_the_loader_refuses_another_host_role_or_arch(ota, tmp_path, role, arch):
    with pytest.raises(ota.manifest.ManifestRefused):
        ota.manifest.load(_write(tmp_path, _fixture()), role, arch)


# --- the c7g-metal role (SDV Phase 6 WP6) ---------------------------------------------------------------------------

def test_the_host_roles_are_the_stacks_in_the_schema_and_in_both_commands(ota):
    """The updater takes the roles sdv/stack/stack.py's HOST_ROLES names (c7g-metal: AWS c7g.metal, what a1-metal is on
    another bare-metal host), in the manifest schema's enum and in `check`'s, `run`'s and `unit start`'s choices."""
    stack = _import(STACK_DIR, "stack")
    assert ota.lite.HOST_ROLES == stack.HOST_ROLES == ("pc", "a1-metal", "c7g-metal", "orin")
    assert ota.manifest.load_schema()["properties"]["host_role"] == {"enum": list(stack.HOST_ROLES)}
    p = ota.lite.build_parser()
    for argv in (["check", "--manifest", "m.json", "--arch", "arm64"],
                 ["run", "--manifest", "m.json", "--arch", "arm64", "--state", "s"],
                 ["unit", "start", "--manifest", "m.json", "--arch", "arm64", "--state", "s"]):
        for role in stack.HOST_ROLES:
            assert p.parse_args(argv + ["--host-role", role]).host_role == role, (argv[0], role)
        with pytest.raises(SystemExit):
            p.parse_args(argv + ["--host-role", "c7g.metal"])


@pytest.mark.parametrize("role", ["a1-metal", "c7g-metal"])
def test_a_bare_metal_manifest_loads_for_its_own_role_only(ota, tmp_path, capsys, role):
    other = {"a1-metal": "c7g-metal", "c7g-metal": "a1-metal"}[role]
    m = dict(_fixture(), host_role=role)
    p = _write(tmp_path, m)
    assert ota.manifest.load(p, role, "arm64")["host_role"] == role
    with pytest.raises(ota.manifest.ManifestRefused, match="host_role is %s, the host's role is %s" % (role, other)):
        ota.manifest.load(p, other, "arm64")
    assert ota.lite.main(["check", "--manifest", str(p), "--host-role", role, "--arch", "arm64"]) == 0
    assert "ok" in capsys.readouterr().out
    assert ota.lite.main(["check", "--manifest", str(p), "--host-role", other, "--arch", "arm64"]) == 2


def test_jsonschema_takes_every_host_role_and_refuses_another(ota):
    gate = importlib.import_module("twin_gate")
    py = gate.vss_venv()
    cases = [dict(_fixture(), host_role=r) for r in ("pc", "a1-metal", "c7g-metal", "orin", "c7g.metal", "laptop")]
    r = subprocess.run([str(py), "-B", "-c", _ORACLE, str(ota.manifest.SCHEMA_FILE)], input=json.dumps(cases),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    mine = [ota.manifest.validate(ota.manifest.load_schema(), c) == [] for c in cases]
    assert json.loads(r.stdout) == mine == [True, True, True, True, False, False]


def test_the_loader_refuses_duplicate_keys_and_what_is_not_json(ota, tmp_path):
    text = FIXTURE_MANIFEST.read_text(encoding="utf-8").replace('"host_role": "orin",', '"host_role": "orin", "host_role": "orin",', 1)
    assert text.count('"host_role"') == 2
    for data in (text.encode(), b"\xff\xfe{}", b"[]", b"{"):
        p = tmp_path / "m.json"
        p.write_bytes(data)
        with pytest.raises(ota.manifest.ManifestRefused):
            ota.manifest.load(p, "orin", "arm64")


def test_O9_a_manifest_over_a_mebibyte_is_refused(host, ota):
    text = json.dumps(host.manifest_dict())
    limit = ota.manifest.MAX_BYTES
    assert len(text) < limit == 1 << 20
    host.manifest_path.write_text(text + " " * (limit - len(text)), encoding="utf-8")
    assert host.manifest_path.stat().st_size == limit
    assert ota.manifest.load(host.manifest_path, "pc", "amd64")["host_role"] == "pc"      # exactly the bound is read
    host.manifest_path.write_text(text + " " * (limit + 1 - len(text)), encoding="utf-8")
    with pytest.raises(ota.manifest.ManifestRefused, match="over %d bytes" % limit):
        ota.manifest.load(host.manifest_path, "pc", "amd64")


def test_check_prints_ok_or_refuses(ota, tmp_path, capsys):
    p = _write(tmp_path, _fixture())
    assert ota.lite.main(["check", "--manifest", str(p), "--host-role", "orin", "--arch", "arm64"]) == 0
    assert "ok" in capsys.readouterr().out
    assert ota.lite.main(["check", "--manifest", str(p), "--host-role", "pc", "--arch", "arm64"]) == 2


_ORACLE = ("import json, sys, jsonschema\n"
           "schema = json.load(open(sys.argv[1], encoding='utf-8'))\n"
           "jsonschema.Draft202012Validator.check_schema(schema)\n"
           "v = jsonschema.Draft202012Validator(schema)\n"
           "json.dump([v.is_valid(c) for c in json.load(sys.stdin)], sys.stdout)\n")


def test_the_validator_agrees_with_jsonschema_on_every_case(ota):
    gate = importlib.import_module("twin_gate")
    py = gate.vss_venv()
    cases = [_fixture()]
    for _what, mutate in _mutations() + _cross():
        m = _fixture()
        mutate(m)
        cases.append(m)
    r = subprocess.run([str(py), "-B", "-c", _ORACLE, str(ota.manifest.SCHEMA_FILE)], input=json.dumps(cases),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    verdicts = json.loads(r.stdout)
    mine = [ota.manifest.validate(ota.manifest.load_schema(), c) == [] for c in cases]
    assert verdicts == mine
    assert verdicts[0] is True and verdicts.count(True) == 1 + len(_cross())


def test_a_pattern_is_matched_to_the_end_of_the_value_not_before_a_trailing_newline(ota):
    """pattern-dollar-python: the validator's ECMA-262 `$`, stricter than jsonschema's (so not in the oracle's cases)."""
    m = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    m["components"][0]["image_id"] += "\n"
    assert ota.manifest.validate(ota.manifest.load_schema(), m) != []


def test_an_integer_is_never_a_float(ota):
    """integer-takes-float: profile_id 1.0 (jsonschema takes it, so it is not in the oracle's cases)."""
    m = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    m["scenarios"][0]["profile_id"] = 1.0
    assert ota.manifest.validate(ota.manifest.load_schema(), m) != []


def test_a_boolean_is_never_an_integer(ota):
    """integer-takes-a-boolean: profile_id true (jsonschema refuses it too; true == 1 would pass minimum 1)."""
    m = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    m["scenarios"][0]["profile_id"] = True
    assert ota.manifest.validate(ota.manifest.load_schema(), m) != []


# --- the spool reader (section 3 item 3) ---------------------------------------------------------------------------

def test_every_record_the_connectors_writer_writes_is_read_back(ota, spool, tmp_path):
    for image_id, scenario in [("sha256:" + "a" * 64, None), (None, S42), ("sha256:" + "0" * 64, "x" * 48), (None, "0"),
                               ("sha256:" + "f" * 64, "a-b-c")]:
        spool.write(tmp_path, spool.record(image_id, scenario))
        data = ota.lite.read_spool(tmp_path)
        assert ota.lite.parse_spool(data) == {"image_id": image_id, "scenario": scenario}


def _form_cases() -> List[Any]:
    i = "sha256:" + "a" * 64
    return [{"image_id": i, "scenario": None, "force": True}, {"image_id": None, "scenario": None},
            {"image_id": "hard-brake-hazard:latest", "scenario": None}, {"image_id": None, "scenario": "../etc"},
            {"image_id": "sha256:" + "A" * 64, "scenario": None}, {"image_id": i + "\n", "scenario": None},
            {"image_id": None, "scenario": S42 + "\n"}, {"image_id": None, "scenario": "x" * 49}, {"image_id": None, "scenario": "-x"},
            {"image_id": None, "scenario": ""}, {"image_id": 7, "scenario": None}, {"image_id": None, "scenario": [S42]},
            {"image_id": i}, {}, [], "x", None,
            {"image_id": "sha256:" + "a" * 64, "scenario": "A"}, {"image_id": None, "scenario": "a b"}, {"image_id": None, "scenario": "a/b"},
            {"image_id": None, "scenario": "a.b"}, {"image_id": None, "scenario": "a\\b"}, {"image_id": "", "scenario": None},
            {"image_id": "sha256:" + "a" * 65, "scenario": None}, {"image_id": True, "scenario": None}, {"image_id": None, "scenario": False},
            {"scenario": S42}, {"IMAGE_ID": None, "scenario": S42}]


@pytest.mark.parametrize("rec", _form_cases(), ids=[str(i) for i in range(len(_form_cases()))])
def test_the_reader_refuses_what_the_writers_rules_refuse(ota, spool, rec):
    assert spool.problems(rec)
    with pytest.raises(ota.lite.SpoolRefused) as exc:
        ota.lite.parse_spool(json.dumps(rec).encode())
    assert exc.value.step in ("2", "3")


def test_257_bytes_are_refused_and_256_are_read(ota, tmp_path):
    body = json.dumps({"image_id": "sha256:" + "a" * 64, "scenario": None}).encode()
    at = body + b" " * (256 - len(body))
    assert len(at) == 256 and ota.lite.parse_spool(at)["image_id"] == "sha256:" + "a" * 64
    over = at + b" "
    with pytest.raises(ota.lite.SpoolRefused) as exc:
        ota.lite.parse_spool(over)
    assert exc.value.step == "1"
    (tmp_path / "desired.json").write_bytes(over + b" " * 100000)
    assert len(ota.lite.read_spool(tmp_path)) == 257


@pytest.mark.parametrize("data", [
    b'{"image_id": null, "scenario": "20990101-sigsim-42", "scenario": "20990101-sigsim-43-brake"}',
    b'{"image_id": "sha256:' + b"a" * 64 + b'", "image_id": "sha256:' + b"b" * 64 + b'", "scenario": null}',
], ids=["scenario-twice", "image-twice"])
def test_a_duplicate_key_is_refused(ota, data):
    with pytest.raises(ota.lite.SpoolRefused) as exc:
        ota.lite.parse_spool(data)
    assert exc.value.step == "2"


@pytest.mark.parametrize("data", [b"\xff\xfe\x00", b"\xef\xbb\xbf{}", b"not json", b'{"image_id": NaN, "scenario": null}', b"[1]", b""],
                         ids=["not-utf8", "bom", "not-json", "nan", "a-list", "empty"])
def test_what_is_not_one_json_object_in_utf8_is_refused_at_step_2(ota, data):
    with pytest.raises(ota.lite.SpoolRefused) as exc:
        ota.lite.parse_spool(data)
    assert exc.value.step == "2"


def test_a_spool_path_that_is_not_a_regular_file_is_refused(ota, tmp_path):
    assert ota.lite.read_spool(tmp_path) is None
    target = tmp_path / "real.json"
    target.write_bytes(b'{"image_id":null,"scenario":"x"}')
    (tmp_path / "desired.json").symlink_to(target)
    with pytest.raises(ota.lite.SpoolRefused) as exc:
        ota.lite.read_spool(tmp_path)
    assert exc.value.step == "1"
    (tmp_path / "desired.json").unlink()
    (tmp_path / "desired.json").mkdir()
    with pytest.raises(ota.lite.SpoolRefused):
        ota.lite.read_spool(tmp_path)
    (tmp_path / "desired.json").rmdir()
    os.mkfifo(str(tmp_path / "desired.json"))
    with pytest.raises(ota.lite.SpoolRefused):
        ota.lite.read_spool(tmp_path)


# --- processing: marks, status, the log (section 3 items 3, 10; spec 2.4) ------------------------------------------

def test_no_status_file_exists_before_the_first_record_is_processed(host):
    u = host.updater()
    assert u.poll_once() is None and host.status_bytes() is None
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    assert host.status() == {"image_id": host.v1.image_id, "scenario": None, "result": "applied"}


def test_a_record_equal_in_bytes_to_the_last_processed_is_not_processed_again_even_after_a_restart(host, ota):
    u = host.updater()
    host.spool(host.stranger.image_id)
    assert u.poll_once() == "refused"
    os.remove(host.status_dir / "status.json")
    assert u.poll_once() is None
    assert host.updater().poll_once() is None
    assert host.status_bytes() is None, "the same record did not rewrite the status"
    host.spool(raw=json.dumps({"image_id": host.stranger.image_id, "scenario": None}).encode())   # other bytes, same meaning
    assert host.updater().poll_once() == "refused"
    assert sum(1 for e in host.log() if e["event"] == "record") == 2


def test_reprocess_clears_the_mark(host, ota, capsys):
    u = host.updater()
    host.spool(host.stranger.image_id)
    assert u.poll_once() == "refused" and u.poll_once() is None
    assert ota.lite.main(["reprocess", "--state", str(host.state)]) == 0
    assert u.poll_once() == "refused"


def test_O14_a_spool_link_is_a_processed_refusal_once(host):
    target = host.base / "elsewhere.json"
    target.write_bytes(json.dumps({"image_id": host.v1.image_id, "scenario": None}).encode())
    (host.spool_dir / "desired.json").symlink_to(target)
    u = host.updater()
    assert u.poll_once() == "refused" and u.poll_once() is None
    assert [s for s, _r in refusals(host)] == ["1"] and host.started() == []
    assert host.status() == {"image_id": None, "scenario": None, "result": "refused"}


def test_a_refusal_writes_refused_with_no_cause_and_the_cause_only_in_the_log(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.spool(host.bridge.image_id)
    assert u.poll_once() == "refused"
    assert host.status_bytes() == b'{"image_id":"%s","scenario":null,"result":"refused"}' % host.v1.image_id.encode()
    assert refusals(host)[-1][0] == "5" and "platform" in refusals(host)[-1][1]


def test_the_status_has_no_image_when_none_runs(host):
    u = host.updater()
    host.spool(host.stranger.image_id)
    assert u.poll_once() == "refused"
    assert host.status_bytes() == b'{"image_id":null,"scenario":null,"result":"refused"}'


def test_the_status_has_no_image_when_the_container_has_exited(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.behaviour[host.v1.image_id] = "exits"
    host.clock.sleep(5.0)
    host.spool(host.stranger.image_id)
    assert u.poll_once() == "refused"
    assert "sdv-ota-app" in host.docker.containers and host.docker.status("sdv-ota-app") == "exited"
    assert host.status() == {"image_id": None, "scenario": None, "result": "refused"}


def test_a_running_sdv_ota_app_without_the_image_label_is_no_image(host):
    """label-not-checked: a container of that name the updater did not start (no sdv.ota.image label) names no image."""
    host.docker.containers["sdv-ota-app"] = Container("sdv-ota-app", "r", "x", {"sdv.ota.app": APP}, [], host.clock.t)
    u = host.updater()
    host.spool(host.stranger.image_id)
    assert u.poll_once() == "refused"
    assert host.status() == {"image_id": None, "scenario": None, "result": "refused"}


@pytest.mark.parametrize("label", ["sha256:" + "A" * 64, "sha256:" + "a" * 63, "sha256:"])
def test_a_running_sdv_ota_app_whose_image_label_is_no_config_digest_is_no_image(host, label):
    """label-any-sha256-prefix: a label that only starts like a config digest names no image either."""
    host.docker.containers["sdv-ota-app"] = Container("sdv-ota-app", "r", "x", {"sdv.ota.app": APP, "sdv.ota.image": label}, [],
                                                      host.clock.t)
    u = host.updater()
    host.spool(host.stranger.image_id)
    assert u.poll_once() == "refused"
    assert host.status() == {"image_id": None, "scenario": None, "result": "refused"}


def test_O1_the_status_says_no_image_once_the_app_has_exited(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.docker.containers["sdv-ota-app"].stopped_at = host.clock.t       # the app is marked exited: its container is still there
    host.spool(host.bridge.image_id)
    assert u.poll_once() == "refused"
    assert host.docker.status("sdv-ota-app") == "exited"
    assert host.status() == {"image_id": None, "scenario": None, "result": "refused"}


class Crash(BaseException):
    """A kill or a power cut: nothing in the updater catches it."""


def _crash() -> Any:
    raise Crash()


def test_O2_a_record_cut_short_by_a_crash_is_never_retried(host):
    host.spool(host.v1.image_id)
    with pytest.raises(Crash):
        host.updater(source_factory=_crash).poll_once()          # `docker run` has run; the check never ends
    assert host.docker.words().count("run") == 1 and host.status_bytes() is None
    assert host.updater().poll_once() is None                    # the unit restarts: the mark was written first
    assert host.docker.words().count("run") == 1 and [e["event"] for e in host.log()].count("record") == 1


def crash_after_the_start(host: Host, img: Img) -> None:
    """v1 applied, then the record for IMG cut short between `docker run` and the state's write, as a kill or a full disk
    would cut it: the after-start hook turns the log into a directory, so the next log line raises. IMG's container runs
    and the state still names v1 as the current image."""
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    log = host.state / "ota-lite.jsonl"

    def hook(argv: Sequence[str]) -> int:
        os.remove(log)
        os.mkdir(log)
        return 0
    host.spool(img.image_id)
    with pytest.raises(OSError):
        host.updater(after_start=["/usr/local/bin/repin"], hook=hook).poll_once()
    os.rmdir(log)
    assert host.docker.containers["sdv-ota-app"].image_id == img.image_id
    assert json.loads((host.state / "state.json").read_text(encoding="utf-8"))["current"]["image_id"] == host.v1.image_id


def test_after_a_crash_between_the_start_and_the_state_write_the_status_and_the_next_record_follow_docker(host):
    crash_after_the_start(host, host.v2)
    u = host.updater()                         # the unit restarts
    host.spool(host.stranger.image_id)
    assert u.poll_once() == "refused"
    assert host.status() == {"image_id": host.v2.image_id, "scenario": None, "result": "refused"}, "the image Docker runs"
    host.spool(raw=json.dumps({"image_id": host.v1.image_id, "scenario": None}).encode())
    assert u.poll_once() == "applied"
    assert host.started() == [host.v1.image_id, host.v2.image_id, host.v1.image_id], "v1 does not run, so it is started"
    assert host.docker.containers["sdv-ota-app"].image_id == host.v1.image_id
    assert host.status() == {"image_id": host.v1.image_id, "scenario": None, "result": "applied"}


def test_a_container_that_runs_unrecorded_is_started_again_and_checked_never_taken_as_applied(host):
    crash_after_the_start(host, host.v2)       # v2 runs but never passed its check
    u = host.updater()
    host.spool(raw=json.dumps({"image_id": host.v2.image_id, "scenario": None}).encode())
    assert u.poll_once() == "applied"
    assert host.started() == [host.v1.image_id, host.v2.image_id, host.v2.image_id]
    assert [e["image_id"] for e in host.log() if e["event"] == "check"][-1] == host.v2.image_id


# --- decisions 4 to 8 and D11 (section 3 item 4) ---------------------------------------------------------------------

def test_an_image_outside_the_manifest_is_refused_at_step_4_and_nothing_is_touched(host):
    u = host.updater()
    host.spool(host.stranger.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host) == [("4", refusals(host)[0][1])]
    assert touching(host) == []


def test_a_platform_class_image_is_refused_at_step_5_and_nothing_is_touched(host):
    u = host.updater()
    host.spool(host.bridge.image_id)
    assert u.poll_once() == "refused"
    assert [s for s, _r in refusals(host)] == ["5"]
    assert touching(host) == []


def test_an_unknown_scenario_is_refused_at_step_6(host):
    host.marker.write_bytes(b"")
    u = host.updater()
    host.spool(None, "20990101-unknown")
    assert u.poll_once() == "refused"
    assert [s for s, _r in refusals(host)] == ["6"]


def test_a_pair_outside_allowed_scenarios_is_refused_at_step_7_both_ways(host):
    host.marker.write_bytes(b"")
    u = host.updater()
    host.spool(host.v1.image_id, S43)
    assert u.poll_once() == "applied"
    host.spool(host.v3.image_id)          # v3 allows only S42; the current scenario is S43
    assert u.poll_once() == "refused"
    host.spool(host.v1.image_id, S42)
    assert u.poll_once() == "applied"
    host.spool(host.v3.image_id)
    assert u.poll_once() == "applied"
    host.spool(None, S43)                  # the current image v3 does not allow S43
    assert u.poll_once() == "refused"
    assert [s for s, _r in refusals(host)] == ["7", "7"]
    assert host.status() == {"image_id": host.v3.image_id, "scenario": S42, "result": "refused"}


def test_a_scenario_alone_is_paired_with_the_image_docker_runs_not_the_one_the_state_names(host):
    crash_after_the_start(host, host.v3)       # v3 (only S42 allowed) runs; the state still names v1 (both allowed)
    host.marker.write_bytes(b"")
    u = host.updater()
    host.spool(None, S43)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "7" and not (host.runtime / "scenario.json").exists()


def test_every_scenario_request_is_refused_without_the_marker(host):
    u = host.updater()
    for rec in ((None, S42), (host.v1.image_id, S42), (None, S43)):
        host.spool(*rec)
        assert u.poll_once() == "refused"
    assert [s for s, _r in refusals(host)] == ["8", "8", "8"]
    assert all("marker" in r for _s, r in refusals(host))
    assert touching(host) == [] and not (host.runtime / "scenario.json").exists()


def test_a_dangling_link_is_no_twin_control_marker(host):
    """marker-lexists: a link to nothing is no marker, so a scenario request is refused (D11 is never weaker here)."""
    host.marker.symlink_to(host.base / "nowhere")
    u = host.updater()
    host.spool(None, S42)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "8" and "marker" in refusals(host)[-1][1]


def test_a_directory_is_a_twin_control_marker(host):
    """marker-must-be-a-regular-file: the marker's existence is the mode (spec 2.2, D11), whatever kind of entry it is."""
    host.marker.mkdir()
    u = host.updater()
    host.spool(None, S42)
    assert u.poll_once() == "applied"
    assert host.status() == {"image_id": None, "scenario": S42, "result": "applied"}


def test_with_the_marker_a_scenario_is_refused_while_the_lock_is_held_and_handed_off_when_free(host):
    import fcntl
    host.marker.write_bytes(b"")
    u = host.updater()
    fd = os.open(str(host.lock), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        host.spool(None, S42)
        assert u.poll_once() == "refused"
        assert refusals(host)[-1][0] == "8" and "held" in refusals(host)[-1][1]
        assert not (host.runtime / "scenario.json").exists()
    finally:
        os.close(fd)
    assert ota_reprocess(host) and u.poll_once() == "applied"
    handed = json.loads((host.runtime / "scenario.json").read_bytes())
    assert handed == {"scenario": S42, "recording": {"path": str(host.rec42), "sha256": "sha256:" + _sha(host.rec42.read_bytes())}}
    assert host.status() == {"image_id": None, "scenario": S42, "result": "applied"}
    assert touching(host) == []


def ota_reprocess(host: Host) -> bool:
    return host.ota.lite.main(["reprocess", "--state", str(host.state)]) == 0


def test_a_missing_lock_file_refuses_a_scenario(host):
    host.marker.write_bytes(b"")
    host.lock.unlink()
    u = host.updater()
    host.spool(None, S42)
    assert u.poll_once() == "refused" and refusals(host)[-1][0] == "8"
    assert not host.lock.exists(), "the updater never creates the lock file"


def test_O5_a_lock_path_that_is_a_directory_refuses_a_scenario(host):
    host.marker.write_bytes(b"")
    host.lock.unlink()
    host.lock.mkdir()                                  # an flock on a directory works, so only the regular-file check refuses it
    u = host.updater()
    host.spool(None, S42)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "8" and "not a regular file" in refusals(host)[-1][1]
    assert not (host.runtime / "scenario.json").exists()


def test_the_lock_is_held_through_the_act_and_released_after(host):
    import fcntl

    def state():
        fd = os.open(str(host.lock), os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return "free"
        except BlockingIOError:
            return "held"
        finally:
            os.close(fd)
    host.marker.write_bytes(b"")
    seen = []
    u = host.updater(after_start=["/usr/local/bin/repin"], hook=lambda argv: seen.append(state()) or 0)
    host.spool(host.v1.image_id, S42)
    assert u.poll_once() == "applied" and seen == ["held"] and state() == "free"


_LOCK_PROBE = ("import fcntl, os, sys\n"
               "fd = os.open(sys.argv[1], os.O_RDWR)\n"
               "try:\n"
               "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
               "    print('free')\n"
               "except BlockingIOError:\n"
               "    print('held')\n")


def _lock_seen_by_another_process(lock: Path) -> str:
    done = subprocess.run([sys.executable, "-B", "-c", _LOCK_PROBE, str(lock)], capture_output=True, text=True, timeout=60)
    return done.stdout.strip()


def test_the_updater_holds_the_lock_through_a_switch_with_a_scenario(host):
    """The lock is the updater's through the whole act (the owner's 2026-10-01 call, MC step 8): a child process's
    non-blocking flock reads `held` at every read of the health check, and `free` once the record is done."""
    host.marker.write_bytes(b"")
    seen = []

    class Probing:
        def read(self, paths):
            seen.append(_lock_seen_by_another_process(host.lock))
            return host.source.read(paths)
    u = host.updater(source_factory=Probing)
    host.spool(host.v1.image_id, S43)
    assert u.poll_once() == "applied"
    assert seen and set(seen) == {"held"}, seen
    assert _lock_seen_by_another_process(host.lock) == "free"
    assert host.status() == {"image_id": host.v1.image_id, "scenario": S43, "result": "applied"}


def test_a_switch_that_rolls_back_does_not_accept_its_scenario(host):
    host.marker.write_bytes(b"")
    u = host.updater()
    host.spool(host.v1.image_id, S42)
    assert u.poll_once() == "applied"
    host.behaviour[host.v2.image_id] = "silent"
    host.spool(host.v2.image_id, S43)
    assert u.poll_once() == "rolled-back"
    assert host.status() == {"image_id": host.v1.image_id, "scenario": S42, "result": "rolled-back"}
    assert json.loads((host.runtime / "scenario.json").read_bytes())["scenario"] == S42, "the hand-off is still the accepted one"
    assert not (host.runtime / ".scenario.json.tmp").exists()


def test_a_recording_whose_sha256_is_not_the_manifests_is_refused(host):
    host.marker.write_bytes(b"")
    u = host.updater()
    host.rec42.write_bytes(b"changed\n")
    host.spool(None, S42)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "recording" and not (host.runtime / "scenario.json").exists()


def test_an_image_and_a_scenario_whose_hand_off_cannot_be_written_are_refused_before_the_running_container_is_touched(host):
    host.marker.write_bytes(b"")
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.docker.calls.clear()
    u = host.updater(runtime_dir=host.base / "no-runtime")
    host.spool(host.v2.image_id, S42)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "handoff"
    assert touching(host) == [] and host.started() == [host.v1.image_id]
    assert host.status() == {"image_id": host.v1.image_id, "scenario": None, "result": "refused"}


def test_O18_a_scenario_whose_handoff_cannot_be_written_is_refused(host):
    host.marker.write_bytes(b"")
    u = host.updater(runtime_dir=host.base / "no-runtime")
    host.spool(None, S42)
    assert u.poll_once() == "refused"
    step, reason = refusals(host)[-1]
    assert step == "handoff" and "cannot be written" in reason and "nothing is touched" in reason, reason
    assert host.status() == {"image_id": None, "scenario": None, "result": "refused"}
    assert touching(host) == [] and not (host.base / "no-runtime").exists()


def test_a_hand_off_whose_rename_fails_after_the_image_passed_is_applied_with_the_scenario_unchanged(host, ota, monkeypatch):
    """The one case the staged hand-off leaves (README, One record): the image moved and passed, so `applied` stands; the
    status keeps the old scenario, the log says why, and no temporary file is left."""
    host.marker.write_bytes(b"")
    u = host.updater()
    real = os.replace

    def replace(src: Any, dst: Any) -> None:
        if str(dst).endswith("scenario.json"):
            raise OSError(5, "Input/output error")
        real(src, dst)
    monkeypatch.setattr(ota.lite.os, "replace", replace)
    host.spool(host.v1.image_id, S42)
    assert u.poll_once() == "applied"
    assert host.status() == {"image_id": host.v1.image_id, "scenario": None, "result": "applied"}
    assert [e for e in host.log() if e["event"] == "handoff-failed"]
    assert sorted(p.name for p in host.runtime.iterdir()) == ["docker"]


def test_a_scenario_alone_whose_hand_off_cannot_be_renamed_is_refused(host, ota, monkeypatch):
    """A failed rename in a scenario-only update leaves nothing applied."""
    import os
    host.marker.write_bytes(b"")
    u = host.updater()
    real = os.replace

    def replace(src, dst):
        if str(dst).endswith("scenario.json"):
            raise OSError(5, "Input/output error")
        real(src, dst)
    monkeypatch.setattr(ota.lite.os, "replace", replace)
    host.spool(None, S42)
    assert u.poll_once() == "refused" and refusals(host)[-1][0] == "handoff"
    assert host.status() == {"image_id": None, "scenario": None, "result": "refused"}


def test_an_accepted_scenario_is_kept_across_a_restart(host):
    """accepted-scenario-not-saved: spec 2.4's scenario is the one last accepted, also after the unit restarts."""
    host.marker.write_bytes(b"")
    u = host.updater()
    host.spool(None, S42)
    assert u.poll_once() == "applied"
    host.spool(host.stranger.image_id)
    assert host.updater().poll_once() == "refused"
    assert host.status() == {"image_id": None, "scenario": S42, "result": "refused"}


# --- getting and proving an image (section 3 item 5) ---------------------------------------------------------------

def test_a_local_build_is_proved_before_anything_is_stopped_and_started_with_the_specs_flags(host, ota):
    u = host.updater(cpuset="3,5")
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.spool(host.v2.image_id)
    host.docker.calls.clear()
    assert u.poll_once() == "applied"
    words = touching(host)
    assert words.index("save") < words.index("stop") < words.index("rm") < words.index("run")
    run = [c for c, _e in host.docker.calls if c[0] == "run"][-1]
    assert run == ota.lite.app_run_argv(APP, host.v2.image_id, host.v2.store_id, "3,5")


def test_a_tar_is_hash_checked_before_it_is_loaded(host):
    u = host.updater()
    host.tar.write_bytes(host.tar_bytes + b"\0" * 512)
    host.spool(host.v2.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "load" and "load" not in host.docker.words()


def test_O7_a_tar_that_lists_two_images_is_refused_before_load(host):
    index = {"schemaVersion": 2, "manifests": [{"mediaType": OCI_MANIFEST, "digest": i.store_id, "size": len(i.manifest)}
                                               for i in (host.v2, host.v1)]}
    members = [("index.json", json.dumps(index).encode())]
    for i in (host.v2, host.v1):
        members += [("blobs/sha256/" + i.store_id.split(":")[1], i.manifest), ("blobs/sha256/" + i.image_id.split(":")[1], i.config)]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    host.tar_bytes = buf.getvalue()
    host.tar.write_bytes(host.tar_bytes)
    host.write_manifest()                                   # the manifest names this tar's sha256
    u = host.updater()
    host.spool(host.v2.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "load" and "exactly one image" in refusals(host)[-1][1]
    assert "load" not in host.docker.words()


def test_a_tar_whose_index_cannot_be_read_names_no_path_in_the_log(host, ota, monkeypatch):
    """The reason keeps the OSError's strerror only: its str() carries the filename, a path under a login's home."""
    def unreadable(path):
        raise OSError(13, "Permission denied", str(path))
    monkeypatch.setattr(ota.docker, "tar_manifest_digest", unreadable)
    u = host.updater()
    host.spool(host.v2.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1] == ("load", "the tar's index: Permission denied")
    assert str(host.tar) not in (host.state / "ota-lite.jsonl").read_text(encoding="utf-8")


def test_docker_loads_standard_error_is_logged_with_the_tars_path_struck(host, ota, monkeypatch):
    seen = []

    def failing_load(path):
        seen.append(str(path))
        return ota.docker.Result(1, "", "open %s: permission denied" % path)
    monkeypatch.setattr(host.docker, "load", failing_load)
    u = host.updater()
    host.spool(host.v2.image_id)
    assert u.poll_once() == "refused" and seen == [str(host.tar)]
    assert str(host.tar) not in (host.state / "ota-lite.jsonl").read_text(encoding="utf-8")
    assert [e["err"] for e in host.log() if e["event"] == "load"] == ["open <tar>: permission denied"]


def test_an_ecr_image_is_pulled_by_its_substituted_reference_with_the_credentials_directory(host):
    u = host.updater()
    host.spool(host.v3.image_id)
    assert u.poll_once() == "applied"
    pulls = [(c, e) for c, e in host.docker.calls if c[0] == "pull"]
    assert pulls == [(["pull", host.ecr_ref], {"DOCKER_CONFIG": str(host.docker_config)})]
    assert not [c for c, _e in host.docker.calls if c[0] in ("login", "logout")]
    assert host.docker.history[-1].ref == host.ecr_ref


@pytest.mark.parametrize("via,index", [("local-build", 0), ("tar", 1), ("ecr", 2)])
def test_a_config_digest_that_is_not_the_entrys_is_refused_before_the_running_container_is_touched(host, via, index):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    other = make_image("other")
    m = host.manifest_dict()
    m["components"][index]["image_id"] = other.image_id      # what the pull, load or store ID gives has another config
    host.write_manifest(m)
    u = host.updater()
    host.docker.calls.clear()
    host.spool(other.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "proof"
    assert {"local-build": "save", "tar": "load", "ecr": "pull"}[via] in host.docker.words()
    assert not [w for w in touching(host) if w in ("stop", "rm", "run")]
    assert host.docker.containers["sdv-ota-app"].stopped_at is None
    assert host.status()["image_id"] == host.v1.image_id


@pytest.mark.parametrize("blob", ["manifest", "config"])
def test_a_blob_that_does_not_hash_to_its_digest_is_refused(host, blob):
    v3 = host.v3
    host.docker.pullable[host.ecr_ref] = {v3.store_id: v3.manifest + (b" " if blob == "manifest" else b""),
                                          v3.image_id: v3.config + (b" " if blob == "config" else b"")}
    u = host.updater()
    host.spool(v3.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "proof" and "run" not in host.docker.words()


def test_a_store_reference_that_names_an_index_is_refused(host):
    idx, idx_d = make_index(host.v1)
    m = host.manifest_dict()
    m["components"][0]["pull"]["store_id"] = idx_d
    host.write_manifest(m)
    host.docker.store[idx_d] = dict(host.v1.blobs(), **{idx_d: idx})
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "proof" and "index" in refusals(host)[-1][1]
    assert "run" not in host.docker.words()


def test_a_failed_pull_is_refused_once_and_never_retried(host):
    host.docker.pullable.clear()
    u = host.updater()
    host.spool(host.v3.image_id)
    assert u.poll_once() == "refused"
    for _ in range(3):
        assert u.poll_once() is None
    assert host.docker.words().count("pull") == 1


def test_the_log_holds_no_registry_host_and_no_account_id(host):
    u = host.updater()
    host.spool(host.v3.image_id)
    assert u.poll_once() == "applied"
    host.docker.pullable.clear()
    host.docker.store.pop(host.ecr_ref)
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.spool(host.v3.image_id)
    assert u.poll_once() == "refused"
    for name in ("ota-lite.jsonl", "state.json", "processed"):
        text = (host.state / name).read_text(encoding="utf-8")
        assert REGISTRY not in text and "123456789012" not in text and "arn:" not in text, name
    assert host.status_bytes() is not None and b"123456789012" not in host.status_bytes()


def test_the_log_is_never_written_through_a_symbolic_link(host, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere") / "file"
    elsewhere.write_bytes(b"")
    (host.state / "ota-lite.jsonl").symlink_to(elsewhere)
    u = host.updater()
    host.spool(host.stranger.image_id)
    with pytest.raises(OSError):
        u.poll_once()
    assert elsewhere.read_bytes() == b""


@pytest.mark.parametrize("problem", ["missing", "group-readable", "no-registry", "another-host", "inside-repo"])
def test_the_registry_file_rules(host, problem):
    reg = host.registry_file
    if problem == "missing":
        reg.unlink()
    elif problem == "group-readable":
        os.chmod(reg, 0o640)
    elif problem == "no-registry":
        reg.write_text(json.dumps({"region": "us-east-1"}), encoding="utf-8")
    elif problem == "another-host":
        reg.write_text(json.dumps({"registry": "registry.example.com"}), encoding="utf-8")
    u = host.updater(registry_file=FIXTURE_MANIFEST if problem == "inside-repo" else reg)
    host.spool(host.v3.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "pull" and "pull" not in host.docker.words()
    if problem == "inside-repo":
        assert "inside the repo" in refusals(host)[-1][1]


def _run_args(host: Host, role: str = "pc", arch: str = "amd64") -> List[str]:
    return ["run", "--once", "--manifest", str(host.manifest_path), "--host-role", role, "--arch", arch, "--state", str(host.state),
            "--spool-dir", str(host.spool_dir), "--status-dir", str(host.status_dir), "--runtime-dir", str(host.runtime),
            "--docker-config", str(host.docker_config), "--marker", str(host.marker), "--lock", str(host.lock),
            "--registry-file", str(host.registry_file), "--home", str(host.home)]


def test_O15_a_registry_file_over_4096_bytes_is_refused(host, ota, capsys):
    body = json.dumps({"registry": REGISTRY})
    limit = ota.lite.REGISTRY_FILE_MAX_BYTES
    assert limit == 4096
    host.registry_file.write_text(body + " " * (limit - len(body)), encoding="utf-8")
    os.chmod(host.registry_file, 0o600)
    assert host.registry_file.stat().st_size == limit and ota.lite.registry_host(host.registry_file) == REGISTRY
    host.registry_file.write_text(body + " " * (limit + 1 - len(body)), encoding="utf-8")
    os.chmod(host.registry_file, 0o600)
    with pytest.raises(ValueError, match="over 4096 bytes"):
        ota.lite.registry_host(host.registry_file)
    assert ota.lite.main(_run_args(host), docker=host.docker) == 2         # `run` reads the file before anything starts
    assert "over 4096 bytes" in capsys.readouterr().err and host.docker.calls == []


def test_an_app_entry_pulled_from_upstream_is_refused(host):
    m = host.manifest_dict()
    m["components"][0]["pull"] = {"via": "upstream", "ref": "ghcr.io/example/app@" + host.v1.store_id, "manifest_digest": host.v1.store_id}
    host.write_manifest(m)
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "refused" and refusals(host)[-1][0] == "pull"
    assert touching(host) == []


def test_the_save_stream_is_read_through_a_stand_in_executable(ota, tmp_path, monkeypatch):
    img = make_image("cli")
    tar = tmp_path / "save.tar"
    save_tar(tar, img)
    script = tmp_path / "docker-stand-in.py"
    script.write_text("import os, sys\n"
                      "a = sys.argv[1:]\n"
                      "if a[:1] == ['save'] and a[1] != 'missing':\n"
                      "    sys.stdout.buffer.write(open(os.environ['OTA_SAVE_TAR'], 'rb').read())\n"
                      "    sys.exit(0)\n"
                      "if a[:1] == ['save']:\n"
                      "    sys.stderr.write('Error: no such image: missing\\n')\n"
                      "    sys.exit(1)\n"
                      "print(' '.join(a))\n", encoding="utf-8")
    monkeypatch.setenv("OTA_SAVE_TAR", str(tar))
    d = ota.docker.Docker([sys.executable, "-B", str(script)])
    d.prove(img.store_id, img.store_id, img.image_id)
    with pytest.raises(ota.docker.ProofError):
        d.prove(img.store_id, img.store_id, "sha256:" + "0" * 64)
    with pytest.raises(ota.docker.DockerError):
        d.save_blobs("missing")
    assert d.call(["container", "inspect", "x"]).out.strip() == "container inspect x"
    assert ota.docker.tar_manifest_digest(tar) == img.store_id
    save_tar(tar, img, listed_type=OCI_INDEX)
    with pytest.raises(ota.docker.ProofError):
        ota.docker.tar_manifest_digest(tar)


def test_O8_a_save_that_exits_non_zero_is_no_proof(ota, tmp_path):
    img = make_image("fails-late")
    tar = tmp_path / "save.tar"
    save_tar(tar, img)
    script = tmp_path / "docker-stand-in.py"
    script.write_text("import sys\n"
                      "sys.stdout.buffer.write(open(%r, 'rb').read())\n"      # a whole, valid stream ...
                      "sys.exit(1)\n" % str(tar), encoding="utf-8")            # ... and then a failure
    d = ota.docker.Docker([sys.executable, "-B", str(script)])
    with pytest.raises(ota.docker.DockerError, match="exit 1"):
        d.save_blobs(img.store_id)
    with pytest.raises(ota.docker.DockerError):
        d.prove(img.store_id, img.store_id, img.image_id)


def test_a_pull_keeps_the_environment_and_adds_docker_config(ota, tmp_path, monkeypatch):
    """call-env-without-environ."""
    script = tmp_path / "env-stand-in.py"
    script.write_text("import json, os\nprint(json.dumps({k: os.environ.get(k) for k in ('DOCKER_CONFIG', 'OTA_MARK')}))\n",
                      encoding="utf-8")
    monkeypatch.setenv("OTA_MARK", "kept")
    r = ota.docker.Docker([sys.executable, "-B", str(script)]).pull("sha256:" + "a" * 64, tmp_path / "dc")
    assert json.loads(r.out) == {"DOCKER_CONFIG": str(tmp_path / "dc"), "OTA_MARK": "kept"}


def test_a_saves_standard_error_reaches_no_one(ota, tmp_path, capfd):
    """save-stderr-inherited: for an ecr reference docker's error text can name the registry."""
    img = make_image("quiet")
    tar = tmp_path / "save.tar"
    save_tar(tar, img)
    script = tmp_path / "save-stand-in.py"
    script.write_text("import sys\nsys.stderr.write('the registry host is named here\\n')\n"
                      "sys.stdout.buffer.write(open(%r, 'rb').read())\n" % str(tar), encoding="utf-8")
    ota.docker.Docker([sys.executable, "-B", str(script)]).prove(img.store_id, img.store_id, img.image_id)
    assert "registry host" not in capfd.readouterr().err


# --- the health check (section 3 item 7) -----------------------------------------------------------------------------

class Scripted:
    """A source that replays records at times: each (t, record) holds from t on."""

    def __init__(self, fields: Dict[str, str], clock: FakeClock, script: List[Tuple[float, Optional[Dict[str, Any]]]]) -> None:
        self.fields, self.clock, self.script = fields, clock, script

    def read(self, paths: Sequence[str]) -> Dict[str, Any]:
        rec: Optional[Dict[str, Any]] = None
        for t, r in self.script:
            if self.clock.t >= t:
                rec = r
        return {p: (rec or {}).get(self.fields[p]) for p in paths}


IMG = "sha256:" + "c" * 64
OLD = "sha256:" + "d" * 64


def beat(seq: int, state: str = "running", image_id: str = IMG, app: str = APP, version: str = "1.1.0") -> Dict[str, Any]:
    return {"schema_version": 1, "app": app, "app_version": version, "image_id": image_id, "seq": seq, "state": state,
            "hazard_requested": False, "actuate_result": "none"}


def run_check(ota: Any, script: List[Tuple[float, Optional[Dict[str, Any]]]],
              status: Callable[[], Optional[str]] = lambda: "running") -> Tuple[bool, str, int, FakeClock]:
    clock = FakeClock()
    _branch, fields = ota.health.leaf_fields(APP)
    src = Scripted(fields, clock, [(clock.t + t, r) for t, r in script])
    ok, reason, beats = ota.health.check(src, APP, "1.1.0", IMG, status, clock.mono, clock.sleep)
    return ok, reason, beats, clock


def test_the_eight_leaves_are_the_schemas(ota):
    branch, fields = ota.health.leaf_fields(APP)
    assert branch == "Vehicle.DualVm.AppState.HardBrakeHazard"
    assert fields == {branch + "." + leaf: prop for leaf, prop in [
        ("SchemaVersion", "schema_version"), ("App", "app"), ("AppVersion", "app_version"), ("ImageId", "image_id"),
        ("Seq", "seq"), ("State", "state"), ("IsHazardRequested", "hazard_requested"), ("ActuateResult", "actuate_result")]}
    hazard = _import(REPO / "sdv" / "apps" / "hard-brake-hazard", "hazard")     # what the app publishes, read from its core
    assert hazard.BRANCH == branch and fields == {branch + "." + leaf: prop for prop, leaf, _t in hazard.LEAVES}


def test_three_rising_heartbeats_of_the_started_image_pass(ota):
    ok, reason, beats, clock = run_check(ota, [(0.5, beat(1)), (1.5, beat(2)), (2.5, beat(3))])
    assert ok and beats == 3, reason
    assert clock.t < 100.0 + 5


def test_heartbeats_with_another_image_id_never_count(ota):
    script = [(0.0, beat(40, image_id=OLD))] + [(0.5 + i, beat(41 + i, image_id=OLD)) for i in range(40)]
    ok, reason, beats, clock = run_check(ota, script)
    assert not ok and beats == 0, reason
    assert clock.t >= 100.0 + 30.0


def test_a_falling_seq_is_not_counted(ota):
    ok, reason, beats, _c = run_check(ota, [(0.5, beat(5)), (1.5, beat(3)), (2.5, beat(4))])
    assert not ok and beats < 3, reason
    ok, reason, beats, _c = run_check(ota, [(0.5, beat(5)), (1.5, beat(3)), (2.5, beat(4)), (3.5, beat(5))])
    assert ok and beats == 3, reason


def test_a_last_state_of_degraded_fails(ota):
    ok, reason, _b, _c = run_check(ota, [(0.5, beat(1)), (1.5, beat(2)), (2.5, beat(3, "degraded"))])
    assert not ok, reason
    ok, reason, _b, _c = run_check(ota, [(0.5, beat(1, "degraded")), (1.5, beat(2, "starting")), (2.5, beat(3))])
    assert ok, reason


def test_a_container_that_exits_fails_at_once(ota):
    ok, reason, _b, clock = run_check(ota, [(0.5, beat(1)), (1.5, beat(2)), (2.5, beat(3))], lambda: "exited")
    assert not ok and "exited" in reason
    assert clock.t < 100.0 + 1.0
    ok, reason, _b, clock = run_check(ota, [(0.5, beat(1)), (1.5, beat(2)), (2.5, beat(3))], lambda: None)
    assert not ok and clock.t < 100.0 + 1.0


def test_a_record_that_fails_the_schema_or_names_another_app_or_version_never_counts(ota):
    bad = dict(beat(2), seq=0)
    for script in ([(0.5, beat(1)), (1.5, bad), (2.5, dict(beat(3), extra=1))],
                   [(0.5 + i, beat(1 + i, app="other-app")) for i in range(5)],
                   [(0.5 + i, beat(1 + i, version="1.0.0")) for i in range(5)],
                   [(0.5 + i, dict(beat(1 + i), seq=float(1 + i))) for i in range(5)]):
        ok, reason, beats, _c = run_check(ota, script)
        assert not ok and beats < 3, reason


def test_health_the_third_beat_after_the_deadline_is_too_late(ota):
    ok, reason, beats, clock = run_check(ota, [(0.5, beat(1)), (1.5, beat(2)), (30.7, beat(3))])
    assert not ok and beats == 2, reason
    assert 100.0 + 30.0 <= clock.t <= 100.0 + 31.0, "the check ends at its deadline, not at the late beat or after it"


def test_health_a_source_that_always_raises_fails_at_the_deadline_not_before(ota):
    class Down:
        def read(self, paths):
            raise RuntimeError("the databroker is down")
    clock = FakeClock()
    ok, reason, beats = ota.health.check(Down(), APP, "1.1.0", IMG, lambda: "running", clock.mono, clock.sleep)
    assert not ok and beats == 0 and "unreadable reads" in reason, reason
    assert 100.0 + 30.0 <= clock.t <= 100.0 + 31.0


def test_O22_health_a_sawtooth_seq_never_passes(ota):
    """Seqs 1, 2, 1, 2, ...: the counted records are not strictly rising from one to the next, so the count restarts at
    every fall and never reaches three."""
    ok, reason, beats, _c = run_check(ota, [(0.5 * k, beat(1 if k % 2 else 2)) for k in range(1, 80)])
    assert not ok and beats < 3, reason


def test_the_kuksa_source_bounds_every_call_and_makes_none_when_it_connects(ota, monkeypatch):
    """kuksa-client 0.6.0's sync VSSClient (its signatures read in the extracted wheel): connect() calls get_server_info()
    with no deadline unless ensure_startup_connection is False, and every call takes grpc's `timeout` through
    **rpc_kwargs. A stand-in of that interface records what ota_kuksa asks of it."""
    import importlib.util
    calls = []

    class VSSClient:
        def __init__(self, host: str, port: int, token: Any = None, root_certificates: Any = None,
                     ensure_startup_connection: bool = True, connected: bool = False, tls_server_name: Any = None) -> None:
            calls.append(("init", host, port, ensure_startup_connection))
            self.ensure = ensure_startup_connection

        def connect(self, target_host: Any = None) -> None:
            calls.append(("connect",))
            if self.ensure:
                self.get_server_info()

        def get_server_info(self, **rpc_kwargs: Any) -> None:
            calls.append(("get_server_info", rpc_kwargs))

        def get_current_values(self, paths: Any, **rpc_kwargs: Any) -> Dict[str, Any]:
            calls.append(("get_current_values", list(paths), rpc_kwargs))
            return {"A.B": types.SimpleNamespace(value=7), "A.C": None}

        def disconnect(self) -> None:
            calls.append(("disconnect",))
    grpc_mod = types.ModuleType("kuksa_client.grpc")
    grpc_mod.VSSClient = VSSClient  # type: ignore[attr-defined]
    pkg = types.ModuleType("kuksa_client")
    pkg.grpc = grpc_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kuksa_client", pkg)
    monkeypatch.setitem(sys.modules, "kuksa_client.grpc", grpc_mod)
    spec = importlib.util.spec_from_file_location("ota_kuksa_under_test", str(OTA_DIR / "ota_kuksa.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec.loader.exec_module(mod)
    src = mod.KuksaSource("127.0.0.1:55555")
    assert calls == [("init", "127.0.0.1", 55555, False), ("connect",)], "connecting makes no call"
    assert src.read(["A.B", "A.C", "A.D"]) == {"A.B": 7, "A.C": None, "A.D": None}
    rpcs = [c for c in calls if c[0] in ("get_server_info", "get_current_values")]
    assert rpcs and all(c[-1] == {"timeout": mod.RPC_TIMEOUT_S} for c in rpcs)
    assert 0 < mod.RPC_TIMEOUT_S <= 1.0


def test_only_one_module_imports_kuksa_client_and_nothing_imports_it_at_module_level(ota):
    users = []
    for p in sorted(OTA_DIR.glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(n.split(".")[0] == "kuksa_client" for n in names):
                users.append(p.name)
        top = [n for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
               for n in ([a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""])]
        if p.name != "ota_kuksa.py":
            assert "ota_kuksa" not in top and not any(n.startswith("kuksa") for n in top), p.name
    assert sorted(set(users)) == ["ota_kuksa.py"]


def test_the_health_checks_source_is_made_for_the_kuksa_address_given(host, ota, monkeypatch):
    """kuksa-argument-ignored."""
    seen = []
    monkeypatch.setattr(ota.lite, "kuksa_source", lambda address: seen.append(address) or host.source)
    u = host.updater(source_factory=None, kuksa="127.0.0.1:55556")
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied" and seen == ["127.0.0.1:55556"]


# --- acting, rollback, bounds (section 3 items 6, 8, 9) ------------------------------------------------------------

def test_v1_then_v2_then_a_broken_v3_rolls_back_to_v2(host):
    host.behaviour[host.v3.image_id] = "silent"
    u = host.updater()
    seq = []
    for img in (host.v1, host.v2, host.v3):
        host.spool(img.image_id)
        seq.append((u.poll_once(), host.status()))
    assert seq == [("applied", {"image_id": host.v1.image_id, "scenario": None, "result": "applied"}),
                   ("applied", {"image_id": host.v2.image_id, "scenario": None, "result": "applied"}),
                   ("rolled-back", {"image_id": host.v2.image_id, "scenario": None, "result": "rolled-back"})]
    assert host.started() == [host.v1.image_id, host.v2.image_id, host.v3.image_id, host.v2.image_id]
    assert list(host.docker.containers) == ["sdv-ota-app"]
    assert host.docker.containers["sdv-ota-app"].image_id == host.v2.image_id
    assert host.docker.containers["sdv-ota-app"].ref == host.v2.store_id, "the rollback runs the recorded image's own reference"


@pytest.mark.parametrize("behaviour", ["silent", "exits", "degraded", "other-version"])
def test_each_failed_check_rolls_back(host, behaviour):
    host.behaviour[host.v2.image_id] = behaviour
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.spool(host.v2.image_id)
    assert u.poll_once() == "rolled-back"
    assert host.started()[-1] == host.v1.image_id and host.status()["image_id"] == host.v1.image_id


def test_a_failed_check_with_no_previous_image_leaves_none_running(host):
    host.behaviour[host.v1.image_id] = "silent"
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "rolled-back"
    assert host.started() == [host.v1.image_id] and host.docker.containers == {}
    assert host.status() == {"image_id": None, "scenario": None, "result": "rolled-back"}


def test_rollback_starts_only_the_recorded_previous_image(host):
    host.behaviour[host.v3.image_id] = "silent"
    u = host.updater()
    for img in (host.v1, host.v2):
        host.spool(img.image_id)
        assert u.poll_once() == "applied"
    m = host.manifest_dict()
    del m["components"][1]                  # v2, the previous image, is no longer an entry
    host.write_manifest(m)
    u = host.updater()
    host.spool(host.v3.image_id)
    assert u.poll_once() == "rolled-back"
    assert host.started() == [host.v1.image_id, host.v2.image_id, host.v3.image_id]
    assert host.status()["image_id"] is None


def test_a_rollback_whose_check_fails_leaves_none_running(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.behaviour[host.v1.image_id] = "silent"
    host.behaviour[host.v2.image_id] = "silent"
    host.spool(host.v2.image_id)
    assert u.poll_once() == "rolled-back"
    assert host.started() == [host.v1.image_id, host.v2.image_id, host.v1.image_id]
    assert host.docker.containers == {} and host.status()["image_id"] is None


def test_a_re_request_of_an_image_whose_container_exited_rolls_back_to_the_last_image_that_ran(host):
    u = host.updater()
    for img in (host.v1, host.v2):
        host.spool(img.image_id)
        assert u.poll_once() == "applied"
    host.behaviour[host.v2.image_id] = "exits"          # v2 crashes after it passed, and again when it is started
    host.clock.sleep(5.0)
    host.spool(raw=json.dumps({"image_id": host.v2.image_id, "scenario": None}).encode())
    assert u.poll_once() == "rolled-back"
    assert host.started() == [host.v1.image_id, host.v2.image_id, host.v2.image_id, host.v1.image_id]
    assert host.status() == {"image_id": host.v1.image_id, "scenario": None, "result": "rolled-back"}
    state = json.loads((host.state / "state.json").read_text(encoding="utf-8"))
    assert state["previous"]["image_id"] == state["current"]["image_id"] == host.v1.image_id, "a crashed image is no target"


def test_a_rollback_to_an_image_no_longer_in_the_store_is_never_started(host):
    u = host.updater()
    host.spool(host.v3.image_id)                         # by ecr
    assert u.poll_once() == "applied"
    host.docker.store.pop(host.ecr_ref)                  # pruned, or removed before the updater was stopped
    host.docker.pullable.clear()
    host.behaviour[host.v2.image_id] = "silent"
    host.spool(host.v2.image_id)
    assert u.poll_once() == "rolled-back"
    runs = [c[-1] for c, _e in host.docker.calls if c[0] == "run"]
    assert runs == [host.ecr_ref, host.v2.store_id], "no `docker run` that could pull the gone image implicitly"
    assert host.docker.words().count("pull") == 1 and host.docker.containers == {}
    assert host.status() == {"image_id": None, "scenario": None, "result": "rolled-back"}
    assert "no longer in the store" in [e for e in host.log() if e["event"] == "rollback"][-1]["reason"]
    assert REGISTRY not in (host.state / "ota-lite.jsonl").read_text(encoding="utf-8")


def test_a_previous_image_reclassed_as_platform_is_never_rolled_back_to(host):
    """app-entry-any-class: the updater never starts a platform image, a rollback's included (manifest-classes section 5)."""
    host.behaviour[host.v3.image_id] = "silent"
    u = host.updater()
    for img in (host.v1, host.v2):
        host.spool(img.image_id)
        assert u.poll_once() == "applied"
    m = host.manifest_dict()
    v2 = m["components"][1]
    v2["class"] = "platform"
    del v2["app_version"], v2["allowed_scenarios"]
    host.write_manifest(m)
    u = host.updater()
    host.spool(host.v3.image_id)
    assert u.poll_once() == "rolled-back"
    assert host.started() == [host.v1.image_id, host.v2.image_id, host.v3.image_id] and host.status()["image_id"] is None


def test_a_record_is_refused_at_stop_when_the_old_container_cannot_be_removed(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.docker.fail = {"stop", "rm"}
    host.spool(host.v2.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "stop"
    assert host.started() == [host.v1.image_id] and host.docker.containers["sdv-ota-app"].image_id == host.v1.image_id
    assert host.status() == {"image_id": host.v1.image_id, "scenario": None, "result": "refused"}
    state = json.loads((host.state / "state.json").read_text(encoding="utf-8"))
    assert state["current"]["image_id"] == host.v1.image_id and state["previous"] is None and len(state["starts"]) == 1
    host.docker.fail = set()                            # the refusal set no rollback target, not even in memory:
    host.behaviour[host.v1.image_id] = "exits"           # v1 then crashes, and a failed v2 has nothing to go back to
    host.clock.sleep(5.0)
    host.behaviour[host.v2.image_id] = "silent"
    host.spool(raw=json.dumps({"image_id": host.v2.image_id, "scenario": None}).encode())
    assert u.poll_once() == "rolled-back"
    assert host.started() == [host.v1.image_id, host.v2.image_id] and host.status()["image_id"] is None


def test_when_the_started_container_cannot_be_removed_no_rollback_is_started_and_the_status_says_what_runs(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.behaviour[host.v2.image_id] = "silent"

    def hook(argv: Sequence[str]) -> int:
        host.docker.fail = {"stop", "rm"}                # from here on the started container cannot be removed
        return 0
    u = host.updater(after_start=["/usr/local/bin/repin"], hook=hook)
    host.spool(host.v2.image_id)
    assert u.poll_once() == "rolled-back"
    assert [c for c, _e in host.docker.calls if c[0] == "run"] == [c.argv for c in host.docker.history]
    assert host.started() == [host.v1.image_id, host.v2.image_id] and len(host.docker.history) == 2
    assert host.status() == {"image_id": host.v2.image_id, "scenario": None, "result": "rolled-back"}
    assert "could not be removed" in [e for e in host.log() if e["event"] == "rollback"][-1]["reason"]


def test_the_after_start_command_gets_the_containers_name_and_a_failure_is_a_failed_start(host):
    u = host.updater(after_start=["/usr/local/bin/repin", "--read"])
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    assert host.hooks == [["/usr/local/bin/repin", "--read", "sdv-ota-app"]]
    host.hook_rc = 3
    host.spool(host.v2.image_id)
    assert u.poll_once() == "rolled-back"
    assert any(e["event"] == "after-start" and e["exit"] == 3 for e in host.log())


def test_O19_a_hung_or_missing_after_start_command_is_a_failure(ota, monkeypatch):
    monkeypatch.setattr(ota.lite, "AFTER_START_TIMEOUT_S", 0.3)
    assert ota.lite.run_hook([sys.executable, "-B", "-c", "import time; time.sleep(5)"]) != 0
    assert ota.lite.run_hook(["/nonexistent/after-start"]) != 0
    assert ota.lite.run_hook([sys.executable, "-B", "-c", "raise SystemExit(0)"]) == 0
    assert ota.lite.run_hook([sys.executable, "-B", "-c", "raise SystemExit(7)"]) == 7


def test_a_failed_docker_run_is_a_failed_start(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.docker.run_rc = 125
    host.spool(host.v2.image_id)
    assert u.poll_once() == "rolled-back"


def test_a_record_for_the_image_already_running_is_applied_without_a_restart(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.spool(raw=json.dumps({"image_id": host.v1.image_id, "scenario": None}).encode())
    host.docker.calls.clear()
    assert u.poll_once() == "applied"
    assert touching(host) == [] and host.started() == [host.v1.image_id]


def test_O4_a_record_for_the_recorded_image_whose_container_died_restarts_it(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.docker.containers["sdv-ota-app"].stopped_at = host.clock.t       # the app died after it passed its check
    host.spool(raw=json.dumps({"image_id": host.v1.image_id, "scenario": None}).encode())
    assert u.poll_once() == "applied"
    assert host.started() == [host.v1.image_id, host.v1.image_id], "the recorded image's container is gone, so it is started"
    assert host.status() == {"image_id": host.v1.image_id, "scenario": None, "result": "applied"}


def test_twelve_starts_in_an_hour_and_never_a_thirteenth(host):
    now = host.clock.time()
    (host.state / "state.json").write_text(json.dumps({"version": 1, "current": None, "previous": None, "scenario": None,
                                                       "starts": [now - 100.0 - i for i in range(11)]}), encoding="utf-8")
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"           # 11 in the hour + 1, and no previous image to roll back to: the 12th is allowed
    assert len(json.loads((host.state / "state.json").read_text(encoding="utf-8"))["starts"]) == 12
    host.spool(host.v2.image_id)
    assert u.poll_once() == "refused" and refusals(host)[-1][0] == "bounds"        # 12 + the start + its rollback
    assert host.started() == [host.v1.image_id]
    host.clock.sleep(3600.0)                    # the hour has passed
    host.spool(raw=json.dumps({"image_id": host.v2.image_id, "scenario": None}).encode())
    assert u.poll_once() == "applied" and [s for s, _r in refusals(host)] == ["bounds"]


def test_the_13th_start_in_an_hour_is_refused(host, ota):
    now = host.clock.time()
    (host.state / "state.json").write_text(json.dumps({"version": 1, "current": None, "previous": None, "scenario": None,
                                                       "starts": [now - 3500 + i for i in range(12)]}), encoding="utf-8")
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "refused"
    assert refusals(host)[-1][0] == "bounds" and "run" not in host.docker.words()


def test_eleven_starts_leave_room_for_one_but_not_for_a_start_and_its_rollback(host):
    now = host.clock.time()
    (host.state / "state.json").write_text(json.dumps({"version": 1, "current": None, "previous": None, "scenario": None,
                                                       "starts": [now - 3500 + i for i in range(10)] + [now - 4000]}), encoding="utf-8")
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"           # 10 in the hour (one is older) + 1
    host.spool(host.v2.image_id)
    assert u.poll_once() == "refused"           # 11 + the start + a rollback would be 13
    assert refusals(host)[-1][0] == "bounds"


def test_starts_older_than_an_hour_do_not_count(host):
    now = host.clock.time()
    (host.state / "state.json").write_text(json.dumps({"version": 1, "current": None, "previous": None, "scenario": None,
                                                       "starts": [now - 3601 - i for i in range(12)]}), encoding="utf-8")
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    state = json.loads((host.state / "state.json").read_text(encoding="utf-8"))
    assert state["starts"] == [now], "a start is kept for an hour and then dropped"


def test_starts_are_kept_in_the_state_across_restarts(host):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    state = json.loads((host.state / "state.json").read_text(encoding="utf-8"))
    assert len(state["starts"]) == 1 and state["current"]["image_id"] == host.v1.image_id


# --- placement, the unit, teardown (section 3 items 8, 11, 12) -----------------------------------------------------

CPUSET_CASES = [
    (None, "orin", False), (None, "pc", True), (None, "a1-metal", True), ("3,5", "orin", True), ("3", "orin", True),
    ("", "pc", False), ("3,4", "orin", False), ("4", "pc", False), ("0", "a1-metal", False), ("1,3", "orin", False),
    ("2", "orin", False), ("3,3", "orin", False), ("03", "orin", False), ("3-5", "orin", False), (" 3", "orin", False),
    ("3,", "orin", False), ("3,5,6", "orin", True),
    ("5,3", "orin", True), ("10", "pc", True), ("3, 5", "orin", False), ("3;5", "orin", False), ("+3", "orin", False),
    ("3.0", "orin", False), ("4", "a1-metal", False),
    (None, "c7g-metal", True), ("3,5", "c7g-metal", True), ("4", "c7g-metal", False), ("", "c7g-metal", False),
]


@pytest.mark.parametrize("value,role,ok", CPUSET_CASES)
def test_the_cpuset_rule_is_the_stacks(ota, value, role, ok):
    if ok:
        assert ota.lite.cpu_list(value, role, "--cpuset") == value
    else:
        with pytest.raises(ValueError):
            ota.lite.cpu_list(value, role, "--cpuset")


@pytest.mark.parametrize("value,role,ok", CPUSET_CASES)
def test_the_stacks_cpuset_rule_refuses_exactly_what_the_updaters_refuses(ota, monkeypatch, value, role, ok):
    stack = _import(STACK_DIR, "stack")
    if value is None:
        monkeypatch.delenv(stack.CPUSET_ENV, raising=False)
    else:
        monkeypatch.setenv(stack.CPUSET_ENV, value)
    if ok:
        assert stack.container_cpuset(role) == value
    else:
        with pytest.raises(stack.StackError):
            stack.container_cpuset(role)


class Runner:
    """sudo, systemd-run and systemctl as a recording runner; is-active answers from a list."""

    def __init__(self, states: Sequence[str]) -> None:
        self.cmds: List[List[str]] = []
        self.states = list(states)

    def __call__(self, cmd: Sequence[str]) -> Any:
        c = list(cmd)
        self.cmds.append(c)
        if c[:2] == ["systemctl", "is-active"]:
            state = self.states.pop(0) if self.states else "inactive"
            return subprocess.CompletedProcess(c, 0 if state == "active" else 3, state + "\n", "")
        return subprocess.CompletedProcess(c, 0, "", "")


def _unit_args(host: Host, role: str = "orin") -> List[str]:
    host.write_manifest(host.manifest_dict(role, "arm64" if role == "orin" else "amd64"))
    return ["unit", "start", "--manifest", str(host.manifest_path), "--host-role", role,
            "--arch", "arm64" if role == "orin" else "amd64", "--state", str(host.state), "--spool-dir", str(host.spool_dir),
            "--status-dir", str(host.status_dir), "--runtime-dir", str(host.runtime), "--docker-config", str(host.docker_config),
            "--registry-file", str(host.registry_file), "--home", str(host.home)]


def test_unit_start_makes_the_directories_and_starts_a_transient_unit_with_allowed_cpus_on_the_orin(host, ota):
    r = Runner(["inactive", "active"])
    assert ota.lite.main(_unit_args(host) + ["--cpus", "3,5", "--cpuset", "3,5", "--python", "/opt/venv/bin/python"], runner=r) == 0
    assert r.cmds[0] == ["systemctl", "is-active", "ota-lite"]
    uid, gid = str(os.getuid()), str(os.getgid())
    assert r.cmds[1:5] == [
        ["sudo", "-n", "install", "-d", "-m", "0755", "-o", uid, "-g", gid, str(host.spool_dir)],
        ["sudo", "-n", "install", "-d", "-m", "0755", "-o", "root", "-g", "root", str(host.status_dir)],
        ["sudo", "-n", "install", "-d", "-m", "0700", "-o", "root", "-g", "root", str(host.runtime)],
        ["sudo", "-n", "install", "-d", "-m", "0700", "-o", "root", "-g", "root", str(host.docker_config)]]
    run = r.cmds[5]
    i = run.index("run")
    assert run[:i] == ["sudo", "-n", "systemd-run", "--unit=ota-lite", "--property=Type=exec", "--property=NoNewPrivileges=yes",
                       "--property=AllowedCPUs=3,5", "--collect", "/opt/venv/bin/python", "-B", str(OTA_DIR / "ota_lite.py")]
    back = ota.lite.build_parser().parse_args(run[i:])
    assert (back.cpuset, back.host_role, back.state, back.home) == ("3,5", "orin", str(host.state), str(host.home))
    assert r.cmds[6] == ["systemctl", "is-active", "ota-lite"] and len(r.cmds) == 7
    assert not [w for c in r.cmds for w in c if w.startswith(("/etc", "/var/lib"))]


def test_unit_start_off_the_orin_needs_no_cpus(host, ota):
    r = Runner(["inactive", "active"])
    assert ota.lite.main(_unit_args(host, "pc"), runner=r) == 0
    assert not [w for w in r.cmds[5] if w.startswith("--property=AllowedCPUs")]


@pytest.mark.parametrize("role", ["a1-metal", "c7g-metal"])
def test_unit_start_on_a_bare_metal_role_needs_no_cpus_and_hands_the_unit_its_role(host, ota, role):
    """WP6: the bare-metal session's updater (spec-2 section 4 item 3: off the Orin the updater takes no cpuset)."""
    host.write_manifest(host.manifest_dict(role, "arm64"))
    r = Runner(["inactive", "active"])
    args = ["unit", "start", "--manifest", str(host.manifest_path), "--host-role", role, "--arch", "arm64",
            "--state", str(host.state), "--spool-dir", str(host.spool_dir), "--status-dir", str(host.status_dir),
            "--runtime-dir", str(host.runtime), "--docker-config", str(host.docker_config),
            "--registry-file", str(host.registry_file), "--home", str(host.home)]
    assert ota.lite.main(args, runner=r) == 0
    run = r.cmds[5]
    assert run[:3] == ["sudo", "-n", "systemd-run"] and not [w for w in run if w.startswith("--property=AllowedCPUs")]
    back = ota.lite.build_parser().parse_args(run[run.index("run"):])
    assert (back.host_role, back.arch, back.cpuset) == (role, "arm64", None)


@pytest.mark.parametrize("role", ["a1-metal", "c7g-metal"])
def test_the_updater_runs_a_record_on_a_bare_metal_role(host, ota, role):
    host.write_manifest(host.manifest_dict(role, "arm64"))
    u = host.updater(host_role=role, arch="arm64")
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied" and host.status()["image_id"] == host.v1.image_id


@pytest.mark.parametrize("extra", [["--cpuset", "3,5"], ["--cpus", "3,5"], ["--cpus", "3,4", "--cpuset", "3,5"],
                                   ["--cpus", "", "--cpuset", "3,5"]], ids=["no-cpus", "no-cpuset", "cpus-core-4", "cpus-empty"])
def test_unit_start_on_the_orin_refuses_before_anything_runs(host, ota, extra):
    r = Runner(["inactive", "active"])
    assert ota.lite.main(_unit_args(host) + extra, runner=r) == 2
    assert r.cmds == []


def test_unit_start_refuses_when_the_unit_is_active(host, ota):
    r = Runner(["active"])
    assert ota.lite.main(_unit_args(host) + ["--cpus", "3,5", "--cpuset", "3,5"], runner=r) == 2
    assert r.cmds == [["systemctl", "is-active", "ota-lite"]]


def test_O16_unit_start_refuses_an_activating_unit(host, ota):
    r = Runner(["activating"])
    assert ota.lite.main(_unit_args(host, "pc"), runner=r) == 2
    assert r.cmds == [["systemctl", "is-active", "ota-lite"]]


def test_O10_unit_start_fails_when_the_unit_does_not_read_back_active(host, ota):
    r = Runner(["inactive", "failed"])
    assert ota.lite.main(_unit_args(host, "pc"), runner=r) == 1
    assert r.cmds[5][:3] == ["sudo", "-n", "systemd-run"] and r.cmds[-1] == ["systemctl", "is-active", "ota-lite"]


def test_O23_unit_start_hands_the_unit_absolute_paths_from_relative_ones(host, ota, monkeypatch):
    host.write_manifest()
    monkeypatch.chdir(host.base)
    r = Runner(["inactive", "active"])
    rel = ["unit", "start", "--manifest", "manifest.json", "--host-role", "pc", "--arch", "amd64", "--state", "state",
           "--spool-dir", "spool", "--status-dir", "status", "--runtime-dir", "runtime", "--docker-config", "runtime/docker",
           "--marker", "twin-control", "--lock", "scenario.lock", "--registry-file", "registry.json", "--home", "home"]
    assert ota.lite.main(rel, runner=r) == 0
    assert all(os.path.isabs(c[-1]) for c in r.cmds[1:5]), r.cmds[1:5]
    run = r.cmds[5]
    back = ota.lite.build_parser().parse_args(run[run.index("run"):])
    for key, value in (("manifest", "manifest.json"), ("state", "state"), ("spool_dir", "spool"), ("status_dir", "status"),
                       ("runtime_dir", "runtime"), ("docker_config", "runtime/docker"), ("marker", "twin-control"),
                       ("lock", "scenario.lock"), ("registry_file", "registry.json"), ("home", "home")):
        assert getattr(back, key) == os.path.join(os.getcwd(), value), key


def test_unit_start_hands_the_unit_its_docker_prefix_and_kuksa_address(host, ota):
    """unit-drops-docker, unit-drops-kuksa."""
    r = Runner(["inactive", "active"])
    args = _unit_args(host, "pc") + ["--docker", "docker --context sdv", "--kuksa", "127.0.0.1:55556"]
    assert ota.lite.main(args, runner=r) == 0
    run = r.cmds[5]
    back = ota.lite.build_parser().parse_args(run[run.index("run"):])
    assert (back.docker, back.kuksa) == ("docker --context sdv", "127.0.0.1:55556")


@pytest.mark.parametrize("where", ["file", "parent"])
def test_unit_start_never_opens_the_registry_file_and_run_still_reads_it(host, ota, capsys, where):
    """The registry file is root-only on a pulling host (D7, spec 2.5); unit start runs as the login. Mode 0 on the file,
    or a parent the login cannot search, stands for root's file as the login sees it: the launcher starts the unit and
    `run`, which reads the file as root in the unit, still refuses it when it cannot be read."""
    if os.geteuid() == 0:
        pytest.skip("root reads any file")
    args = _unit_args(host) + ["--cpus", "3,5", "--cpuset", "3,5"]
    locked = host.registry_file if where == "file" else host.base / "root-only"
    if where == "parent":
        locked.mkdir()
        os.replace(host.registry_file, locked / "registry.json")
        args[args.index("--registry-file") + 1] = str(locked / "registry.json")
    os.chmod(locked, 0)
    try:
        r = Runner(["inactive", "active"])
        assert ota.lite.main(args, runner=r) == 0
        assert len(r.cmds) == 7 and r.cmds[5][r.cmds[5].index("--registry-file") + 1] == args[args.index("--registry-file") + 1]
        run = ["run", "--once"] + args[2:-4] + ["--cpuset", "3,5"]
        assert ota.lite.main(run, docker=host.docker) == 2
        assert "the registry file cannot be opened" in capsys.readouterr().err and host.docker.calls == []
    finally:
        os.chmod(locked, 0o700 if where == "parent" else 0o600)


@pytest.mark.parametrize("problem", ["missing", "link", "group-readable", "a-directory", "inside-repo", "none"])
def test_unit_start_refuses_a_registry_file_by_what_its_path_shows_before_anything_runs(host, ota, capsys, problem):
    args = _unit_args(host) + ["--cpus", "3,5", "--cpuset", "3,5"]
    i = args.index("--registry-file") + 1
    if problem == "missing":
        host.registry_file.unlink()
    elif problem == "link":
        link = host.base / "registry-link.json"
        link.symlink_to(host.registry_file)
        args[i] = str(link)
    elif problem == "group-readable":
        os.chmod(host.registry_file, 0o640)
    elif problem == "a-directory":
        args[i] = str(host.runtime)
    elif problem == "inside-repo":
        args[i] = str(FIXTURE_MANIFEST)
    else:
        del args[i - 1:i + 1]
    r = Runner(["inactive", "active"])
    assert ota.lite.main(args, runner=r) == 2
    assert r.cmds == [] and "registry" in capsys.readouterr().err


def test_unit_stop_stops_and_reads_back_inactive(ota):
    r = Runner(["inactive"])
    assert ota.lite.main(["unit", "stop"], runner=r) == 0
    assert r.cmds == [["sudo", "-n", "systemctl", "stop", "ota-lite"], ["systemctl", "is-active", "ota-lite"]]
    assert ota.lite.main(["unit", "stop"], runner=Runner(["active"])) == 1


def test_unit_status_says_the_units_state(ota, capsys):
    assert ota.lite.main(["unit", "status"], runner=Runner(["active"])) == 0
    assert "active" in capsys.readouterr().out
    assert ota.lite.main(["unit", "status"], runner=Runner(["inactive"])) == 1


def test_teardown_removes_every_labelled_container_and_says_how_many(host, ota, capsys):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    assert ota.lite.main(["teardown"], docker=host.docker) == 0
    assert host.docker.containers == {}
    assert "1 container(s) labelled sdv.ota.app removed, 0 left" in capsys.readouterr().out
    assert ota.lite.main(["teardown"], docker=host.docker) == 0


def test_teardown_leaves_a_container_without_the_label_and_exits_1_when_a_removal_fails(host, ota, capsys):
    host.docker.containers["old-one"] = Container("old-one", "r", "x", {"sdv.ota.app": APP}, [], host.clock.t)
    host.docker.containers["old-one"].stopped_at = host.clock.t
    host.docker.containers["not-ours"] = Container("not-ours", "r", "x", {"x": "y"}, [], host.clock.t)
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    assert ota.lite.main(["teardown"], docker=host.docker) == 0
    assert list(host.docker.containers) == ["not-ours"]
    assert "2 container(s) labelled sdv.ota.app removed, 0 left" in capsys.readouterr().out
    host.docker.containers["sdv-ota-app"] = Container("sdv-ota-app", "r", "x", {"sdv.ota.app": APP}, [], host.clock.t)
    host.docker.fail = {"rm"}
    assert ota.lite.main(["teardown"], docker=host.docker) == 1
    assert list(host.docker.containers) == ["not-ours", "sdv-ota-app"]


def test_teardown_exits_1_and_says_how_many_are_left_when_a_removal_fails(host, ota, capsys):
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.docker.fail = {"rm"}
    assert ota.lite.main(["teardown"], docker=host.docker) == 1
    assert "0 container(s) labelled sdv.ota.app removed, 1 left" in capsys.readouterr().out


def test_teardown_lists_every_container_with_ps_a_and_stops_each_before_removing_it(host, ota):
    """ps-without-a, teardown-without-stop."""
    u = host.updater()
    host.spool(host.v1.image_id)
    assert u.poll_once() == "applied"
    host.docker.calls.clear()
    assert ota.lite.main(["teardown"], docker=host.docker) == 0
    ps = [c for c, _e in host.docker.calls if c[0] == "ps"]
    assert ps and all(c[:2] == ["ps", "-a"] for c in ps)
    assert [c for c, _e in host.docker.calls if c[0] in ("stop", "rm")] == [["stop", "-t", "10", "sdv-ota-app"], ["rm", "sdv-ota-app"]]


@pytest.mark.parametrize("where", ["repo", "var-lib", "missing"])
def test_the_state_directory_may_not_be_inside_the_repo_or_var_lib(host, ota, where):
    state = {"repo": str(REPO / "sdv" / "ota"), "var-lib": "/var/lib/ota-lite", "missing": str(host.base / "nope")}[where]
    args = ["run", "--once", "--manifest", str(host.manifest_path), "--host-role", "pc", "--arch", "amd64", "--state", state,
            "--registry-file", str(host.registry_file)]
    assert ota.lite.main(args, docker=host.docker, source_factory=lambda: host.source) == 2
    assert host.docker.calls == []


def test_O17_a_state_file_that_is_not_the_updaters_stops_the_run(host, ota):
    (host.state / "state.json").write_text(json.dumps({"version": 1, "current": None, "previous": None, "scenario": None,
                                                       "starts": [], "extra": 1}), encoding="utf-8")
    host.spool(host.v1.image_id)
    with pytest.raises(ValueError, match="not the updater's"):
        host.updater()
    with pytest.raises(ValueError, match="not the updater's"):
        ota.lite.main(_run_args(host), docker=host.docker, source_factory=lambda: host.source, clock=host.clock.mono,
                      wall=host.clock.time, sleep=host.clock.sleep)
    assert host.docker.calls == [] and host.status_bytes() is None


def test_var_lib_itself_and_anything_under_it_is_refused_by_rule_not_only_by_absence(ota):
    for p in ("/var/lib", "/var/lib/ota-lite", "/var/lib/../lib/x"):
        found = ota.lite.state_dir_problems(p)
        assert found and "/var/lib" in found[0], p


def test_run_once_through_main_processes_one_record(host, ota):
    host.spool(host.v1.image_id)
    args = ["run", "--once", "--manifest", str(host.manifest_path), "--host-role", "pc", "--arch", "amd64",
            "--state", str(host.state), "--spool-dir", str(host.spool_dir), "--status-dir", str(host.status_dir),
            "--runtime-dir", str(host.runtime), "--docker-config", str(host.docker_config), "--marker", str(host.marker),
            "--lock", str(host.lock), "--registry-file", str(host.registry_file), "--home", str(host.home)]
    assert ota.lite.main(args, docker=host.docker, source_factory=lambda: host.source, clock=host.clock.mono,
                         wall=host.clock.time, sleep=host.clock.sleep) == 0
    assert host.status()["result"] == "applied"
    assert ota.lite.main(args[:2] + ["--manifest", str(FIXTURE_MANIFEST)] + args[4:], docker=host.docker) == 2


def test_the_run_loop_as_a_process(host, ota, tmp_path):
    """`run` without --once, as the unit starts it: one record is processed, `reprocess` makes a running updater read the
    same record again, and SIGTERM ends it after the record in hand with exit 0 and an `updater-stop` line. The record is
    a platform-class image (refused at step 5), so the only Docker command is the status read, which the stand-in
    executable answers as `no such container`."""
    import shlex
    import signal
    import time
    stand_in = tmp_path / "docker-stand-in.py"
    stand_in.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    host.spool(host.bridge.image_id)
    args = [w for w in _run_args(host) if w != "--once"] + ["--docker", shlex.join([sys.executable, "-B", str(stand_in)])]
    proc = subprocess.Popen([sys.executable, "-B", str(OTA_DIR / "ota_lite.py")] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))

    def wait_for_status() -> bool:
        t0 = time.time()
        while host.status_bytes() is None and time.time() - t0 < 20:
            time.sleep(0.1)
        return host.status_bytes() is not None
    try:
        assert wait_for_status()
        os.remove(host.status_dir / "status.json")
        assert ota.lite.main(["reprocess", "--state", str(host.state)]) == 0
        assert wait_for_status(), "the running updater read the cleared mark and processed the record again"
        proc.send_signal(signal.SIGTERM)
        rc = proc.wait(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    assert rc == 0, "exit status %s, standard error %r" % (rc, stderr)
    events = [e["event"] for e in host.log()]
    assert events[0] == "updater-start" and events[-1] == "updater-stop" and events.count("record") == 2, events
    assert host.status() == {"image_id": None, "scenario": None, "result": "refused"}
