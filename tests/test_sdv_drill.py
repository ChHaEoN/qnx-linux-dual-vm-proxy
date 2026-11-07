"""test_sdv_drill.py -- the drill (sdv/drill; SDV Phase 6 WP3).

Every test runs on stand-ins: Docker is a fake image store that interprets the argv the
build tool builds, or a recording runner that answers the drill's read-only questions; sudo, systemctl and the updater's
launcher (ota_lite.py unit start, unit stop, teardown) are that runner; the updater itself is a fake that reads the spool
and writes the status record with WP1's own write_status and a log in WP1's event shapes; the player is a fake process;
the clock is a fake one, and the fake updater acts only when the drill sleeps. Nothing starts a container, reaches a
registry or the network, or writes under /run, /etc or /var/lib. The one real program run is WP1's `ota_lite.py check`,
the judge of every manifest `drill.py manifest` writes (its schema file is read where WP1 keeps it, never copied).

What it holds (the OTA drill contract sections 2.1 to 2.3 and 3, and section 3's mutants):
  * the command lines word for word, and the exit statuses (0 ok, 1 ran and not ok, 2 a refusal);
  * `manifest`: for each transport and architecture a manifest the updater's own check takes (and refuses once broken):
    the three drill versions of class app, the bridge of class platform, the stack run's scenario by path and sha256;
    tar transport as one tar per version that the updater's own tar reader takes; ecr naming only the placeholder; the
    host roles read from stack.py at run time;
  * `run`: the six steps' records in order on both architectures and both ways in (spool, twin), each step's status
    read only after its own status event (two consecutive refusals told apart), app_version from the manifest; a step
    with no status event a problem while the rest still run; the end (the player stopped, the unit stopped, the
    updater's teardown, the log and state copied) on every way out; the refusals before anything starts (a stack that
    is not up, a QEMU, an app container, an active unit, the twin-control marker, an existing record); the stack never
    started or stopped; no registry host and no outside path in the record;
  * `compare`: equal across architectures (image IDs never in the key), the first difference otherwise, a step missing
    or unanswered on every host alike included;
  * `build_drill.py`: v2's edit of exactly two constants on a staged copy (missing or doubled old text refused), v3's
    config differing from v2's in the entrypoint alone with no layer, an index refused, the build's and the save's argv,
    the pins file, the amd64 store IDs, and the v1 arm64 pin held equal to images.json's.

Every digest, date, account id and host here is a documentation value. Does not demonstrate: anything on a real stack,
updater, Docker or host; that v2's change shows on the bus or in the twin; any timing.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import importlib
import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DRILL_DIR = REPO / "sdv" / "drill"
OTA_DIR = REPO / "sdv" / "ota"
CONNECTOR_DIR = REPO / "sdv" / "connector"
STACK_FILE = REPO / "sdv" / "stack" / "stack.py"
IMAGES_FILE = REPO / "sdv" / "stack" / "images.json"
HAZARD_FILE = REPO / "sdv" / "apps" / "hard-brake-hazard" / "hazard.py"
OTA_LITE = OTA_DIR / "ota_lite.py"
FIX = HERE / "fixtures" / "drill"
STORE_IDS = FIX / "store-ids-amd64.json"

OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"
REGISTRY = "123456789012.dkr.ecr.us-east-1.amazonaws.com"      # AWS's documentation account id
APP = "hard-brake-hazard"
BRIDGE = "vss-claim-bridge"
SCENARIO = "20990101-sigsim-42"
VERSIONS = ("1.0.0", "1.1.0", "1.2.0")
SUDO = ["fakesudo", "-n"]
COMMIT = "0123456789abcdef0123456789abcdef01234567"
# spec-2 section 2.2's table: n, asks, app_version, scenario, result, the log's refusal step, a rollback event came
TABLE = [
    (1, "image v1", "1.0.0", None, "applied", None, False),
    (2, "image v2", "1.1.0", None, "applied", None, False),
    (3, "image v3", "1.1.0", None, "rolled-back", None, True),
    (4, "the bridge's image", "1.1.0", None, "refused", "5", False),
    (5, "an image ID in no entry", "1.1.0", None, "refused", "4", False),
    (6, "the drill's scenario", "1.1.0", None, "refused", "8", False),
]
USAGE = (
    "drill.py manifest --host-role R --arch amd64|arm64 --transport local-build|tar|ecr --stack-run DIR --out FILE",
    "[--pins FILE] [--store-ids FILE] [--tar FILE] [--recording DIR]",
    "drill.py run      --manifest FILE --state DIR --record DIR --stack-run DIR --sim-python PY --ota-python PY",
    "[--via spool|twin] [--cpuset LIST] [--registry-file F] [--docker-config D] [--home D]",
    "[--spool-dir D] [--status-dir D] [--sudo PREFIX] [--docker PREFIX] [--step-timeout-s N]",
    "drill.py compare  --host ROLE=DIR [--host ROLE=DIR ...] --out DIR",
)


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


@pytest.fixture()
def dr() -> Any:
    """drill.py, imported by name from sdv/drill as its own command line imports it."""
    mod = _import(DRILL_DIR, "drill")
    assert Path(str(mod.__file__)).resolve().parent == DRILL_DIR.resolve(), mod.__file__
    return mod


@pytest.fixture()
def bd() -> Any:
    mod = _import(DRILL_DIR, "build_drill")
    assert Path(str(mod.__file__)).resolve().parent == DRILL_DIR.resolve(), mod.__file__
    return mod


@pytest.fixture(scope="module")
def ota() -> Any:
    """WP1's updater modules: the status writer, the manifest loader, the tar reader. Read, never copied."""
    lite = _import(OTA_DIR, "ota_lite")
    return lite, _import(OTA_DIR, "ota_manifest"), _import(OTA_DIR, "ota_docker")


@pytest.fixture(scope="module")
def spool() -> Any:
    return _import(CONNECTOR_DIR, "spool")


# --- images: what a docker save holds ------------------------------------------------------------------------------

class Img(NamedTuple):
    id: str                 # the manifest digest: the containerd store's ID of a built or loaded image
    manifest: bytes
    config: bytes
    config_digest: str      # the image_id of every Phase 6 record
    layers: Tuple[bytes, ...]

    def blobs(self) -> Dict[str, bytes]:
        out = {self.id: self.manifest, self.config_digest: self.config}
        out.update({"sha256:" + _sha(lay): lay for lay in self.layers})
        return out


def config_doc(arch: str, layers: Sequence[bytes], version: str, entrypoint: Sequence[str]) -> Dict[str, Any]:
    return {"architecture": arch, "os": "linux", "created": "2099-01-01T00:00:00Z",
            "config": {"User": "10001:10001", "Env": ["PYTHONDONTWRITEBYTECODE=1"], "Entrypoint": list(entrypoint),
                       "WorkingDir": "/app", "Labels": {"org.opencontainers.image.version": version, "sdv.stack": "1"}},
            "rootfs": {"type": "layers", "diff_ids": ["sha256:" + _sha(lay) for lay in layers]},
            "history": [{"created": "2099-01-01T00:00:00Z", "created_by": "layer %d" % i} for i in range(len(layers))]}


def image_of(cfg: Dict[str, Any], layers: Sequence[bytes]) -> Img:
    config = json.dumps(cfg, separators=(",", ":")).encode()
    cd = "sha256:" + _sha(config)
    man = json.dumps({"schemaVersion": 2, "mediaType": OCI_MANIFEST,
                      "config": {"mediaType": OCI_CONFIG, "digest": cd, "size": len(config)},
                      "layers": [{"mediaType": OCI_LAYER, "digest": "sha256:" + _sha(lay), "size": len(lay)} for lay in layers]},
                     separators=(",", ":")).encode()
    return Img("sha256:" + _sha(man), man, config, cd, tuple(layers))


def synth(arch: str, layers: Sequence[bytes], version: str = "1.0.0",
          entrypoint: Sequence[str] = ("python", "/app/app.py")) -> Img:
    return image_of(config_doc(arch, layers, version, entrypoint), layers)


def drill_set(arch: str = "arm64") -> Dict[str, Img]:
    """v1, v2 (v1 plus one layer) and v3 (v2 with another entrypoint), each synthetic."""
    base = [("%s base layer %d " % (arch, i)).encode() * 8 for i in range(2)]
    top = base + [("%s v2 hazard layer" % arch).encode()]
    return {"1.0.0": synth(arch, base, "1.0.0"), "1.1.0": synth(arch, top, "1.1.0"),
            "1.2.0": synth(arch, top, "1.1.0", ("python", "-c", "raise SystemExit(3)"))}


def _add(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    ti = tarfile.TarInfo(name)
    ti.size, ti.mode, ti.mtime = len(data), 0o644, 0
    tf.addfile(ti, io.BytesIO(data))


def save_tar(path: Path, imgs: Iterable[Img], index_type: str = OCI_MANIFEST, names: Optional[Dict[str, str]] = None) -> None:
    """What `docker save <ID>...` writes under the containerd store: an OCI layout (index.json naming each manifest),
    oci-layout, the legacy manifest.json naming no tag, an empty repositories, every blob once."""
    imgs = list(imgs)
    blobs: Dict[str, bytes] = {}
    for img in imgs:
        blobs.update(img.blobs())
    descs = []
    for img in imgs:
        d: Dict[str, Any] = {"mediaType": index_type, "digest": img.id, "size": len(img.manifest)}
        if names and img.id in names:
            d["annotations"] = {"io.containerd.image.name": "docker.io/" + names[img.id],
                                "org.opencontainers.image.ref.name": names[img.id].rsplit(":", 1)[1]}
        descs.append(d)
    legacy = [{"Config": "blobs/sha256/" + img.config_digest[7:], "RepoTags": None,
               "Layers": ["blobs/sha256/" + _sha(lay) for lay in img.layers]} for img in imgs]
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(path), "w") as tf:
        for dname in ("blobs", "blobs/sha256"):
            ti = tarfile.TarInfo(dname)
            ti.type, ti.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(ti)
        for digest, data in sorted(blobs.items()):
            _add(tf, "blobs/sha256/" + digest[7:], data)
        _add(tf, "index.json", json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": descs}).encode())
        _add(tf, "manifest.json", json.dumps(legacy).encode())
        _add(tf, "oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
        _add(tf, "repositories", b"{}")


def rewrite_tar(path: Path, replace: Dict[str, bytes]) -> None:
    """The tar at path again with the named regular members' bytes replaced, every name kept."""
    held: List[Tuple[tarfile.TarInfo, Optional[bytes]]] = []
    with tarfile.open(str(path)) as tf:
        for m in tf.getmembers():
            f = tf.extractfile(m) if m.isreg() else None
            held.append((m, f.read() if f is not None else None))
    assert set(replace) <= {m.name for m, _data in held}, "a member to replace is not in the tar"
    with tarfile.open(str(path), "w") as out:
        for m, data in held:
            if data is not None and m.name in replace:
                data = replace[m.name]
                m.size = len(data)
            out.addfile(m, io.BytesIO(data) if data is not None else None)


def tar_names(path: Path) -> List[str]:
    with tarfile.open(str(path)) as tf:
        return [m.name for m in tf.getmembers()]


def write_pins(path: Path, imgs: Dict[str, Img], ecr: Optional[Dict[str, str]] = None) -> Path:
    """drill-images.json's shape for imgs; with `ecr`, each version's ecr_manifest_digest (the digest the registry
    reports after `twinctl push`, which the orchestrator adds to the pins)."""
    v1, v2, v3 = (imgs[v] for v in VERSIONS)
    doc: Dict[str, Any] = {"format": 1, "app": APP, "arm64": {
        "1.0.0": {"id": v1.id, "config_digest": v1.config_digest, "tag": "sdv-local/hard-brake-hazard:1.0.0-arm64",
                  "base": "images.json local.hard-brake-hazard.arm64"},
        "1.1.0": {"id": v2.id, "config_digest": v2.config_digest, "tag": "sdv-drill/hard-brake-hazard:1.1.0-arm64",
                  "base": {"id": v1.id, "config_digest": v1.config_digest}},
        "1.2.0": {"id": v3.id, "config_digest": v3.config_digest, "tag": "sdv-drill/hard-brake-hazard:1.2.0-arm64",
                  "base": {"id": v2.id, "config_digest": v2.config_digest}}}}
    for v, digest in (ecr or {}).items():
        doc["arm64"][v]["ecr_manifest_digest"] = digest
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return path


# --- the stack run and the manifest ----------------------------------------------------------------------------------

def stack_run(tmp_path: Path, host_role: str = "pc") -> Path:
    """A stack run directory as `stack.py up` leaves it, from the fixture (whose recording is kept as sigsim.candump:
    the repo ignores *.log), its recording staged under the stack's own name."""
    d = tmp_path / "runs" / "20990101-ota-drill"
    shutil.copytree(str(FIX / "stack-run"), str(d))
    (d / "in" / "sigsim.candump").rename(d / "in" / "sigsim.log")
    (d / "up").mkdir()
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    m["host_role"] = host_role
    (d / "manifest.json").write_text(json.dumps(m, indent=1) + "\n", encoding="utf-8")
    return d


def manifest_argv(tmp_path: Path, host_role: str, arch: str, transport: str, sr: Path,
                  imgs: Optional[Dict[str, Img]] = None) -> Tuple[List[str], Path]:
    out = tmp_path / "work" / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = ["manifest", "--host-role", host_role, "--arch", arch, "--transport", transport, "--stack-run", str(sr),
            "--out", str(out)]
    if arch == "arm64":
        imgs = imgs or drill_set()
        argv += ["--pins", str(write_pins(tmp_path / "pins.json", imgs))]
    else:
        argv += ["--store-ids", str(STORE_IDS)]
    if transport == "tar":
        tar = tmp_path / "in" / "sdv-drill.tar"
        save_tar(tar, (imgs or drill_set()).values())
        argv += ["--tar", str(tar)]
    return argv, out


def updater_check(path: Path, host_role: str, arch: str) -> int:
    """WP1's `ota_lite.py check`, run as the drill runs it."""
    p = subprocess.run([sys.executable, "-B", str(OTA_LITE), "check", "--manifest", str(path), "--host-role", host_role,
                        "--arch", arch], capture_output=True, text=True, timeout=120)
    return p.returncode


def bridge_pin_arm64() -> Dict[str, str]:
    return json.loads(IMAGES_FILE.read_text(encoding="utf-8"))["bridge"]["arm64"]


# --- the command lines -----------------------------------------------------------------------------------------------

def test_the_usage_block_holds_the_three_command_lines_word_for_word(dr: Any) -> None:
    doc = " ".join((dr.__doc__ or "").split())
    for line in USAGE:
        assert " ".join(line.split()) in doc, line


@pytest.mark.parametrize("cmd, needed, optional", [
    ("manifest", ["--host-role", "--arch", "--transport", "--stack-run", "--out"], ["--pins", "--store-ids", "--tar", "--recording"]),
    ("run", ["--manifest", "--state", "--record", "--stack-run", "--sim-python", "--ota-python"],
     ["--via", "--cpuset", "--registry-file", "--docker-config", "--home", "--spool-dir", "--status-dir", "--sudo", "--docker",
      "--step-timeout-s"]),
    ("compare", ["--host", "--out"], []),
])
def test_each_command_takes_exactly_its_options(dr: Any, cmd: str, needed: List[str], optional: List[str]) -> None:
    sub = dr.build_parser()._subparsers._group_actions[0].choices[cmd]
    opts = {s for a in sub._actions for s in a.option_strings if s.startswith("--") and s != "--help"}
    assert opts == set(needed) | set(optional)
    required = {s for a in sub._actions for s in a.option_strings if a.required}
    assert required == set(needed)


def test_the_choices_are_the_specs(dr: Any) -> None:
    subs = dr.build_parser()._subparsers._group_actions[0].choices
    acts = {cmd: {a.option_strings[0]: a for a in p._actions if a.option_strings} for cmd, p in subs.items()}
    assert tuple(acts["manifest"]["--arch"].choices) == ("amd64", "arm64")
    assert tuple(acts["manifest"]["--transport"].choices) == ("local-build", "tar", "ecr")
    assert tuple(acts["run"]["--via"].choices) == ("spool", "twin")
    assert acts["run"]["--via"].default == "spool"
    assert acts["run"]["--step-timeout-s"].default == 300


def test_drill_and_build_drill_use_the_standard_library_only() -> None:
    repo_modules = {"drill", "spool", "limits", "a64scan"}
    for name in ("drill.py", "build_drill.py"):
        tree = ast.parse((DRILL_DIR / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split(".")[0]]
            else:
                continue
            for m in mods:
                assert m in sys.stdlib_module_names or m in repo_modules, (name, m)


def test_the_connector_dir_is_searched_before_the_pythonpath_and_the_site_packages(tmp_path: Path) -> None:
    """drill.py run as a script with a `spool` and a `limits` module that raise on PYTHONPATH (as site-packages might
    hold modules of those names): it still starts, because the connector's directory comes right after its own."""
    decoys = tmp_path / "decoys"
    decoys.mkdir()
    for name in ("spool", "limits"):
        (decoys / (name + ".py")).write_text("raise ImportError('a decoy %s module')\n" % name, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH" and not k.startswith(("GIT_", "REPO_"))}
    env.update(PYTHONPATH=str(decoys), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, "-B", str(DRILL_DIR / "drill.py"), "--help"], capture_output=True, text=True, env=env,
                       cwd=str(tmp_path), timeout=120)
    assert p.returncode == 0, p.stderr
    assert p.stdout.startswith("usage: drill.py")


# --- manifest ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("host_role, arch, transport", [
    ("pc", "amd64", "local-build"), ("a1-metal", "arm64", "local-build"), ("a1-metal", "arm64", "tar"), ("orin", "arm64", "ecr"),
])
def test_the_manifest_passes_the_updaters_own_check(dr: Any, ota: Any, tmp_path: Path, host_role: str, arch: str,
                                                     transport: str) -> None:
    sr = stack_run(tmp_path, host_role)
    imgs = drill_set()
    argv, out = manifest_argv(tmp_path, host_role, arch, transport, sr, imgs)
    assert dr.main(argv) == 0
    m = json.loads(out.read_text(encoding="utf-8"))
    assert ota[1].check(m, host_role, arch) == []                 # WP1's schema file, read where WP1 keeps it
    assert updater_check(out, host_role, arch) == 0
    assert (m["manifest_version"], m["host_role"], m["arch"]) == (1, host_role, arch)
    apps = [c for c in m["components"] if c["class"] == "app"]
    platform = [c for c in m["components"] if c["class"] == "platform"]
    assert [c["app_version"] for c in apps] == list(VERSIONS)
    assert all(c["name"] == APP and c["form"] == "container" and c["allowed_scenarios"] == [SCENARIO] for c in apps)
    if arch == "arm64":
        want = {v: (imgs[v].config_digest, imgs[v].id) for v in VERSIONS}
        bridge = bridge_pin_arm64()
        bridge_ids = (bridge["config_digest"], bridge["id"])
    else:
        ids = json.loads(STORE_IDS.read_text(encoding="utf-8"))
        want = {v: (ids["images"][v]["config_digest"], ids["images"][v]["store_id"]) for v in VERSIONS}
        bridge_ids = (ids["bridge"]["config_digest"], ids["bridge"]["store_id"])
    assert {c["app_version"]: c["image_id"] for c in apps} == {v: want[v][0] for v in VERSIONS}
    assert len(platform) == 1 and platform[0]["name"] == BRIDGE and platform[0]["form"] == "container"
    assert platform[0]["image_id"] == bridge_ids[0]
    assert platform[0]["pull"] == {"via": "local-build", "store_id": bridge_ids[1]}
    for c in apps:
        store = want[c["app_version"]][1]
        if transport == "local-build":
            assert c["pull"] == {"via": "local-build", "store_id": store}
        elif transport == "ecr":
            assert c["pull"] == {"via": "ecr", "ref": "<registry>/sdv-twin/hard-brake-hazard@" + store, "manifest_digest": store}
        else:
            assert c["pull"]["via"] == "tar" and Path(c["pull"]["tar_path"]).is_file()
    [scn] = m["scenarios"]
    log = sr / "in" / "sigsim.log"
    assert scn["name"] == SCENARIO
    assert scn["recording"] == {"path": str(log), "sha256": "sha256:" + _sha(log.read_bytes()), "format": "candump-log"}
    own = sr / "ownership.json"
    assert scn["ownership"] == {"file": str(own), "sha256": "sha256:" + _sha(own.read_bytes())}
    owned = json.loads(own.read_text(encoding="utf-8"))
    assert scn["source"] == owned["source"] and scn["profile_id"] == owned["profile_id"]


def test_tar_transport_gives_each_version_a_tar_of_its_one_image(dr: Any, ota: Any, tmp_path: Path) -> None:
    sr = stack_run(tmp_path, "a1-metal")
    imgs = drill_set()
    argv, out = manifest_argv(tmp_path, "a1-metal", "arm64", "tar", sr, imgs)
    assert dr.main(argv) == 0
    m = json.loads(out.read_text(encoding="utf-8"))
    paths = set()
    for c in (c for c in m["components"] if c["class"] == "app"):
        img = imgs[c["app_version"]]
        path = Path(c["pull"]["tar_path"])
        paths.add(path)
        assert c["pull"]["tar_sha256"] == "sha256:" + _sha(path.read_bytes())
        assert ota[2].tar_manifest_digest(path) == img.id          # the updater's own reader takes it
        names = set(tar_names(path))
        assert {"blobs/sha256/" + d[7:] for d in img.blobs()} <= names
        others = {i.id for v, i in imgs.items() if v != c["app_version"]}
        assert not {"blobs/sha256/" + d[7:] for d in others} & names
        # what a `docker save` of this one ID holds besides its blobs: the layout marker, and the legacy manifest.json
        # naming this version's config alone
        assert {"oci-layout", "index.json", "manifest.json"} <= names
        with tarfile.open(str(path)) as tf:
            legacy = json.loads(tf.extractfile("manifest.json").read())             # type: ignore[union-attr]
        assert [e["Config"] for e in legacy] == ["blobs/sha256/" + img.config_digest[7:]]
        assert Path(dr.__file__).resolve().parents[2] not in path.resolve().parents
    assert len(paths) == 3


def test_ecr_transport_names_the_placeholder_and_never_a_host(dr: Any, tmp_path: Path) -> None:
    sr = stack_run(tmp_path, "orin")
    argv, out = manifest_argv(tmp_path, "orin", "arm64", "ecr", sr)
    assert dr.main(argv) == 0
    text = out.read_text(encoding="utf-8")
    assert "dkr.ecr" not in text and REGISTRY not in text and "<registry>/sdv-twin/hard-brake-hazard@sha256:" in text


@pytest.mark.parametrize("transport", ["ecr", "local-build", "tar"])
def test_the_registrys_digest_in_the_pins_is_the_ecr_pulls_and_only_its(dr: Any, ota: Any, tmp_path: Path, transport: str) -> None:
    """A pin's optional ecr_manifest_digest (the digest the registry reports after `twinctl push`, added by the
    orchestrator) is the ecr pull's ref digest and manifest_digest; the image_id stays the config digest, and the other
    transports never use it."""
    role = "orin" if transport == "ecr" else "a1-metal"
    sr = stack_run(tmp_path, role)
    imgs = drill_set()
    argv, out = manifest_argv(tmp_path, role, "arm64", transport, sr, imgs)
    ecr = {v: "sha256:" + _sha(("the registry's manifest of %s" % v).encode()) for v in VERSIONS}
    write_pins(tmp_path / "pins.json", imgs, ecr)
    assert dr.main(argv) == 0
    m = json.loads(out.read_text(encoding="utf-8"))
    assert updater_check(out, role, "arm64") == 0
    for c in (c for c in m["components"] if c["class"] == "app"):
        v = c["app_version"]
        assert c["image_id"] == imgs[v].config_digest
        if transport == "ecr":
            assert c["pull"] == {"via": "ecr", "ref": "<registry>/sdv-twin/hard-brake-hazard@" + ecr[v], "manifest_digest": ecr[v]}
        elif transport == "local-build":
            assert c["pull"] == {"via": "local-build", "store_id": imgs[v].id}
        else:
            assert ota[2].tar_manifest_digest(Path(c["pull"]["tar_path"])) == imgs[v].id
    if transport != "ecr":
        text = out.read_text(encoding="utf-8")
        assert not any(d[7:] in text for d in ecr.values())


@pytest.mark.parametrize("transport", ["tar", "local-build"])
def test_manifest_never_overwrites_a_sessions_manifest_or_its_tars(dr: Any, tmp_path: Path, transport: str) -> None:
    """A second `manifest` into the same --out is refused: neither the manifest nor (tar transport) a split tar is
    replaced, and with the manifest gone the tars left in drill-tars/ still refuse it."""
    sr = stack_run(tmp_path, "a1-metal")
    argv, out = manifest_argv(tmp_path, "a1-metal", "arm64", transport, sr)
    assert dr.main(argv) == 0
    tars = sorted((out.parent / "drill-tars").glob("*.tar")) if transport == "tar" else []
    assert len(tars) == (3 if transport == "tar" else 0)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in [out] + tars}
    assert dr.main(argv) == 2
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in [out] + tars} == before
    if transport == "tar":
        out.unlink()
        assert dr.main(argv) == 2 and not out.exists()
        assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tars} == {p: before[p] for p in tars}
        assert sorted(p.name for p in (out.parent / "drill-tars").iterdir()) == [p.name for p in tars]


@pytest.mark.parametrize("breakage", ["bridge-as-app", "undefined-scenario", "two-v1"])
def test_a_broken_manifest_fails_the_updaters_check(dr: Any, tmp_path: Path, breakage: str) -> None:
    sr = stack_run(tmp_path, "pc")
    argv, out = manifest_argv(tmp_path, "pc", "amd64", "local-build", sr)
    assert dr.main(argv) == 0
    m = json.loads(out.read_text(encoding="utf-8"))
    if breakage == "bridge-as-app":
        next(c for c in m["components"] if c["name"] == BRIDGE)["class"] = "app"
    elif breakage == "undefined-scenario":
        m["components"][0]["allowed_scenarios"] = ["20990101-not-defined"]
    else:
        m["components"][1]["image_id"] = m["components"][0]["image_id"]
    broken = tmp_path / "work" / "broken.json"
    broken.write_text(json.dumps(m), encoding="utf-8")
    assert updater_check(broken, "pc", "amd64") == 2


def test_the_host_roles_are_stack_pys_read_at_run_time(dr: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = ast.parse(STACK_FILE.read_text(encoding="utf-8"))
    want = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "HOST_ROLES" for t in n.targets))
    assert tuple(dr.host_roles()) == tuple(want)
    fake = tmp_path / "stack.py"
    fake.write_text('"""a stand-in"""\nHOST_ROLES = ("pc", "x-metal")\n', encoding="utf-8")
    monkeypatch.setattr(dr, "STACK_FILE", fake)
    assert tuple(dr.host_roles()) == ("pc", "x-metal")
    sr = stack_run(tmp_path, "a1-metal")
    argv, out = manifest_argv(tmp_path, "a1-metal", "arm64", "local-build", sr)
    assert dr.main(argv) == 2 and not out.exists()


def test_c7g_metal_is_the_updaters_to_judge(dr: Any, tmp_path: Path) -> None:
    """stack.py's roles hold c7g-metal, so the drill writes the manifest; whether the updater takes it is its check's."""
    assert "c7g-metal" in dr.host_roles()
    sr = stack_run(tmp_path, "c7g-metal")
    argv, out = manifest_argv(tmp_path, "c7g-metal", "arm64", "local-build", sr)
    rc = dr.main(argv)
    assert json.loads(out.read_text(encoding="utf-8"))["host_role"] == "c7g-metal"
    assert rc == updater_check(out, "c7g-metal", "arm64")


@pytest.mark.parametrize("case", ["out-in-repo", "amd64-no-store-ids", "amd64-tar", "amd64-ecr", "tar-no-tar", "arm64-store-ids",
                                  "no-ownership", "no-recording", "other-host-role", "tar-other-images", "tar-an-index",
                                  "recording-differs", "pins-short", "pins-one-digest-twice", "amd64-store-ids-not-amd64",
                                  "out-dir-missing", "stack-run-path-with-a-space", "pins-ecr-digest-malformed",
                                  "pins-ecr-digest-twice", "pins-ecr-digest-another-versions-id", "tar-out-with-a-space",
                                  "tar-amd64-image", "tar-corrupt-layer", "recording-other-name"])
def test_manifest_refusals_write_nothing(dr: Any, tmp_path: Path, case: str) -> None:
    arch, transport, role = ("amd64", "local-build", "pc") if case.startswith("amd64") else ("arm64", "local-build", "a1-metal")
    if case in ("amd64-tar", "tar-no-tar", "tar-other-images", "tar-an-index", "tar-out-with-a-space", "tar-amd64-image",
                "tar-corrupt-layer"):
        transport = "tar"
    if case == "amd64-ecr" or case.startswith("pins-ecr"):
        transport = "ecr"
    sr = stack_run(tmp_path, role)
    imgs = drill_set()
    argv, out = manifest_argv(tmp_path, role, arch, "local-build", sr, imgs)
    argv[argv.index("--transport") + 1] = transport
    if case == "out-in-repo":
        out = DRILL_DIR / "manifest-from-a-test.json"
        argv[argv.index("--out") + 1] = str(out)
    elif case == "amd64-no-store-ids":
        i = argv.index("--store-ids")
        del argv[i:i + 2]
    elif case in ("amd64-tar", "tar-other-images", "tar-an-index"):
        tar = tmp_path / "in" / "sdv-drill.tar"
        if case == "tar-other-images":
            save_tar(tar, [imgs["1.0.0"], imgs["1.1.0"], synth("arm64", [b"another"], "9.9.9")])
        elif case == "tar-an-index":
            save_tar(tar, imgs.values(), index_type=OCI_INDEX)
        else:
            save_tar(tar, imgs.values())
        argv += ["--tar", str(tar)]
    elif case == "tar-out-with-a-space":
        # the split tars are named in the manifest by path, and a space is outside the schema's path form: the refusal
        # comes before the tars are written, not after
        tar = tmp_path / "in" / "sdv-drill.tar"
        save_tar(tar, imgs.values())
        argv += ["--tar", str(tar)]
        out = tmp_path / "work dir" / "manifest.json"
        out.parent.mkdir()
        argv[argv.index("--out") + 1] = str(out)
    elif case in ("tar-amd64-image", "tar-corrupt-layer"):
        tar = tmp_path / "in" / "sdv-drill.tar"
        if case == "tar-amd64-image":
            # the pins and the save agree on every digest: only one image's config says amd64
            odd = dict(imgs, **{"1.2.0": synth("amd64", [b"an amd64 layer"], "1.1.0", ("python", "-c", "raise SystemExit(3)"))})
            write_pins(tmp_path / "pins.json", odd)
            save_tar(tar, odd.values())
        else:
            save_tar(tar, imgs.values())
            top = json.loads(imgs["1.1.0"].manifest)["layers"][-1]["digest"]
            rewrite_tar(tar, {"blobs/sha256/" + top[7:]: b"bytes that are not the layer"})
        argv += ["--tar", str(tar)]
    elif case == "arm64-store-ids":
        argv += ["--store-ids", str(STORE_IDS)]
    elif case == "no-ownership":
        (sr / "ownership.json").unlink()
    elif case == "no-recording":
        (sr / "in" / "sigsim.log").unlink()
    elif case == "other-host-role":
        argv[argv.index("--host-role") + 1] = "orin"
    elif case == "recording-differs":
        rec = tmp_path / "recording"
        rec.mkdir()
        (rec / "sigsim.log").write_bytes(b"(0.000000) vcan0 0C8#FFFFFFFFFFFFFFFF\n")
        (rec / "manifest-line.json").write_text(json.dumps({"name": SCENARIO, "recording": {"sha256": "0" * 64}}), encoding="utf-8")
        argv += ["--recording", str(rec)]
    elif case == "recording-other-name":
        # the same bytes as the staged copy, listed under another scenario's name
        rec = tmp_path / "recording"
        rec.mkdir()
        data = (sr / "in" / "sigsim.log").read_bytes()
        (rec / "sigsim.log").write_bytes(data)
        (rec / "manifest-line.json").write_text(json.dumps({"name": "20990101-another-scenario", "recording": {"sha256": _sha(data)}}),
                                                encoding="utf-8")
        argv += ["--recording", str(rec)]
    elif case == "pins-short":
        doc = json.loads((tmp_path / "pins.json").read_text(encoding="utf-8"))
        del doc["arm64"]["1.2.0"]
        (tmp_path / "pins.json").write_text(json.dumps(doc), encoding="utf-8")
    elif case == "pins-one-digest-twice":
        doc = json.loads((tmp_path / "pins.json").read_text(encoding="utf-8"))
        doc["arm64"]["1.1.0"]["id"] = doc["arm64"]["1.0.0"]["id"]
        (tmp_path / "pins.json").write_text(json.dumps(doc), encoding="utf-8")
    elif case == "amd64-store-ids-not-amd64":
        doc = json.loads(STORE_IDS.read_text(encoding="utf-8"))
        doc["arch"] = "arm64"
        (tmp_path / "ids.json").write_text(json.dumps(doc), encoding="utf-8")
        argv[argv.index("--store-ids") + 1] = str(tmp_path / "ids.json")
    elif case == "out-dir-missing":
        out = tmp_path / "nowhere" / "manifest.json"
        argv[argv.index("--out") + 1] = str(out)
    elif case == "stack-run-path-with-a-space":
        spaced = tmp_path / "runs" / "with space"
        shutil.move(str(sr), str(spaced))
        argv[argv.index("--stack-run") + 1] = str(spaced)
    elif case.startswith("pins-ecr"):
        doc = json.loads((tmp_path / "pins.json").read_text(encoding="utf-8"))
        a = doc["arm64"]
        if case == "pins-ecr-digest-malformed":
            a["1.1.0"]["ecr_manifest_digest"] = "sha256:" + "z" * 64
        elif case == "pins-ecr-digest-twice":
            a["1.0.0"]["ecr_manifest_digest"] = a["1.1.0"]["ecr_manifest_digest"] = "sha256:" + "e" * 64
        else:
            a["1.1.0"]["ecr_manifest_digest"] = a["1.0.0"]["id"]
        (tmp_path / "pins.json").write_text(json.dumps(doc), encoding="utf-8")
    try:
        assert dr.main(argv) == 2
        assert not out.exists()
        assert not (out.parent / "drill-tars").exists() or not any((out.parent / "drill-tars").iterdir())
        if case == "tar-out-with-a-space":
            assert not (out.parent / "drill-tars").exists()          # refused before the directory is made, not emptied after
    finally:
        if case == "out-in-repo" and out.exists():
            out.unlink()


def test_a_recording_directory_that_matches_is_taken(dr: Any, tmp_path: Path) -> None:
    sr = stack_run(tmp_path, "pc")
    rec = tmp_path / "recording"
    rec.mkdir()
    data = (sr / "in" / "sigsim.log").read_bytes()
    (rec / "sigsim.log").write_bytes(data)
    (rec / "manifest-line.json").write_text(json.dumps({"name": SCENARIO, "recording": {"sha256": _sha(data)}}), encoding="utf-8")
    argv, out = manifest_argv(tmp_path, "pc", "amd64", "local-build", sr)
    assert dr.main(argv + ["--recording", str(rec)]) == 0 and out.exists()


# --- run: the world the drill runs against -------------------------------------------------------------------------

class Done(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


class FakeUpdater:
    """The updater as the drill sees it: it reads the spool when the drill sleeps, logs WP1's events, and after `lag`
    more polls decides as WP1's decision order does for the drill's records and writes the status with WP1's own
    write_status. Records for the images in `ignore` are never processed (no record event, no status)."""

    def __init__(self, w: "World", manifest: Path, state: Path) -> None:
        self.w = w
        m = json.loads(manifest.read_text(encoding="utf-8"))
        self.entries = {c["image_id"]: c for c in m["components"] if c["form"] == "container"}
        self.log_path = state / "ota-lite.jsonl"
        self.current: Optional[str] = None
        self.last: Optional[str] = None
        self.pending: Optional[List[Any]] = None
        self.log("updater-start", host_role=m["host_role"], arch=m["arch"])

    def log(self, event: str, **fields: Any) -> None:
        rec = dict(fields, t_wall=round(self.w.t, 3), event=event)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")

    def poll(self) -> None:
        if self.pending is not None:
            self.pending[1] -= 1
            if self.pending[1] <= 0:
                self.act(self.pending[0])
                self.pending = None
            return
        try:
            data = (self.w.spool / "desired.json").read_bytes()
        except FileNotFoundError:
            return
        mark = "sha256:" + _sha(data)
        if mark == self.last:
            return
        self.last = mark
        rec = json.loads(data)
        if rec["image_id"] in self.w.ignore:
            return
        self.log("record", mark=mark)
        self.log("request", image_id=rec["image_id"], scenario=rec["scenario"])
        self.pending = [rec, self.w.lag]

    def act(self, rec: Dict[str, Any]) -> None:
        img, result = rec["image_id"], "applied"
        if img is not None:
            e = self.entries.get(img)
            if e is None:
                self.log("refused", step="4", reason="the image ID is no container entry of the manifest")
                result = "refused"
            elif e["class"] != "app":
                self.log("refused", step="5", reason="the image ID's entry is of class platform, not app")
                result = "refused"
            elif e["app_version"] == "1.2.0":
                self.log("start", image_id=img, exit=0)
                self.log("check", image_id=img, ok=False, reason="the container exited", beats=0)
                self.log("rollback", to=self.current)
                result = "rolled-back"
            else:
                self.log("start", image_id=img, exit=0)
                self.current = img
        else:
            self.log("refused", step="8", reason="a scenario request with no twin-control marker")
            result = "refused"
        if self.w.status_broken:
            return
        self.w.ota[0].write_status(self.w.status, self.current, None, result)
        if self.w.reorder_status:
            doc = json.loads((self.w.status / "status.json").read_text(encoding="utf-8"))
            (self.w.status / "status.json").write_text(
                json.dumps({"result": doc["result"], "scenario": doc["scenario"], "image_id": doc["image_id"]}), encoding="utf-8")
        if self.w.break_status_at is not None and img is not None and self.entries.get(img, {}).get("app_version") == self.w.break_status_at:
            (self.w.status / "status.json").unlink()
            (self.w.status / "status.json").mkdir()         # an error whose text names a host path
            self.w.status_broken = True
        state: Dict[str, Any] = {"version": 1, "current": self.current, "previous": None, "scenario": None, "starts": []}
        (self.log_path.parent / "state.json").write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        self.log("status", image_id=self.current, scenario=None, result=result)


class FakeProc:
    def __init__(self, w: "World", cmd: List[str]) -> None:
        self.w, self.cmd, self.polls = w, cmd, 0
        self.returncode: Optional[int] = None
        self.args = cmd
        k = len(w.procs)                                  # this start's index: its exit status is player_rcs[k], or 0
        self.rc = w.player_rcs[k] if k < len(w.player_rcs) else 0

    def poll(self) -> Optional[int]:
        if self.returncode is None and self.w.player_exit_after is not None:
            self.polls += 1
            if self.polls >= self.w.player_exit_after:
                self.returncode = self.rc
        return self.returncode

    def terminate(self) -> None:
        self.w.calls.append(("terminate", self.cmd))
        if self.returncode is None:
            self.returncode = -15

    def kill(self) -> None:
        self.w.calls.append(("kill", self.cmd))
        if self.returncode is None:
            self.returncode = -9

    def wait(self, timeout: Optional[float] = None) -> int:
        if self.w.wait_timeouts > 0:                      # a player that does not end when asked: wait times out
            self.w.wait_timeouts -= 1
            raise subprocess.TimeoutExpired(self.cmd, timeout or 0)
        return self.returncode if self.returncode is not None else -15


class World:
    """The host as the drill's runner, popen, clock and sleep see it."""

    def __init__(self, tmp_path: Path, ota: Any, spool_mod: Any, monkeypatch: pytest.MonkeyPatch, dr: Any) -> None:
        self.tmp, self.ota, self.spool_mod = tmp_path, ota, spool_mod
        self.spool, self.status = tmp_path / "spool", tmp_path / "status"
        self.state, self.record = tmp_path / "ota-state", tmp_path / "record"
        self.spool.mkdir()
        self.status.mkdir()
        self.t = 1000.0
        self.calls: List[Any] = []
        self.procs: List[FakeProc] = []
        self.unexpected: List[List[str]] = []
        self.unit = "inactive"
        self.unit_start_rc = 0
        self.unit_start_err = ""                          # what a refused `unit start` says on its stderr
        self.on_unit_stop: Optional[Callable[[], None]] = None     # runs when the drill calls `unit stop`
        self.stack_run_name: Optional[str] = None         # the stack run directory's name: stack.py's label is `<name>/up`
        self.wait_timeouts = 0                            # the next waits on a player that raise TimeoutExpired
        self.reorder_status = False                       # the updater's status file holds its keys in another order
        self.updater: Optional[FakeUpdater] = None
        self.lag = 2
        self.ignore: Tuple[Optional[str], ...] = ()
        self.stack_up = True
        self.stack_names = ["sdv-stack-databroker", "sdv-stack-mock-provider", "sdv-stack-recorder", "sdv-stack-witness",
                            "sdv-stack-can-provider"]
        self.break_status_at: Optional[str] = None
        self.status_broken = False
        self.ota_app = False
        self.player_exit_after: Optional[int] = None
        self.player_rcs: List[int] = []                   # the k-th player's exit status (0 beyond the list)
        self.sudo_ok = True                               # False: the --sudo prefix cannot run (no NOPASSWD)
        self.popen_error = False
        self.cat_error_at: Optional[int] = None
        self.cats = 0
        self.stop_at_sleep: Optional[int] = None
        self.sleeps = 0
        self.twin = False
        self.twin_lag = 2
        self.twin_seen: Dict[int, int] = {}
        self.marker = tmp_path / "twin-control"
        monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(self.marker))
        monkeypatch.delenv("REPO_COMMIT", raising=False)
        self.proc = tmp_path / "proc"
        (self.proc / "1").mkdir(parents=True)
        (self.proc / "1" / "comm").write_text("systemd\n", encoding="utf-8")
        self.net = tmp_path / "net"
        (self.net / "vcan0").mkdir(parents=True)
        (self.net / "lo").mkdir()
        monkeypatch.setattr(dr, "PROC", str(self.proc))
        monkeypatch.setattr(dr, "NET_SYSFS", str(self.net))
        bins = tmp_path / "bin"
        bins.mkdir()
        self.sim_py, self.ota_py = str(bins / "sim-python"), str(bins / "ota-python")
        for p in (self.sim_py, self.ota_py):
            Path(p).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            os.chmod(p, 0o755)
        self.dr = dr

    # -- the seams --

    def runner(self, cmd: Sequence[str]) -> Done:
        cmd = list(cmd)
        self.calls.append(("run", cmd))
        inner = cmd[len(SUDO):] if cmd[:len(SUDO)] == SUDO else cmd
        if inner[:2] == ["cat", "--"] and len(inner) == 3:
            if cmd[:len(SUDO)] == SUDO and not self.sudo_ok:
                return Done(1, "", "sudo: a password is required")
            if inner[2] == "/dev/null":
                return Done(0, "", "")
            self.cats += 1
            if self.cat_error_at is not None and self.cats == self.cat_error_at:
                raise RuntimeError("a stand-in's runner broke")
            try:
                return Done(0, Path(inner[2]).read_text(encoding="utf-8"), "")
            except FileNotFoundError:
                return Done(1, "", "cat: no such file")
        if cmd == ["systemctl", "is-active", "ota-lite"]:
            return Done(0 if self.unit == "active" else 3, self.unit + "\n", "")
        if cmd[:2] == ["docker", "ps"]:
            if any(a.startswith("label=sdv.stack.run=") for a in cmd):
                # only stack.py's own label, `<run>/up`, names the stack's containers; any other filter finds none
                mine = cmd == ["docker", "ps", "--filter", "label=sdv.stack.run=%s/up" % self.stack_run_name, "--format", "{{.Names}}"]
                return Done(0, "".join(n + "\n" for n in self.stack_names) if self.stack_up and mine else "", "")
            if any(a.startswith("name=") for a in cmd):
                return Done(0, "sdv-ota-app\n" if self.ota_app else "", "")
        if cmd[:3] == [self.ota_py, "-B", str(OTA_LITE)]:
            sub = cmd[3:]
            if sub[:2] == ["unit", "start"]:
                if self.unit_start_rc == 0:
                    self.unit = "active"
                    self.updater = FakeUpdater(self, Path(sub[sub.index("--manifest") + 1]), Path(sub[sub.index("--state") + 1]))
                return Done(self.unit_start_rc, "ota-lite: unit ota-lite is %s\n" % self.unit, self.unit_start_err)
            if sub == ["unit", "stop"]:
                if self.on_unit_stop is not None:
                    self.on_unit_stop()
                self.unit = "inactive"
                return Done(0, "ota-lite: unit ota-lite is inactive\n", "")
            if sub == ["teardown", "--docker", "docker"]:
                return Done(0, "ota-lite teardown: 0 container(s) labelled sdv.ota.app removed, 0 left\n", "")
        self.unexpected.append(cmd)
        return Done(127, "", "not a call this stand-in knows")

    def popen(self, cmd: Sequence[str]) -> FakeProc:
        self.calls.append(("popen", list(cmd)))
        if self.popen_error:
            raise OSError(2, "No such file or directory")
        p = FakeProc(self, list(cmd))
        self.procs.append(p)
        return p

    def clock(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps += 1
        if self.stop_at_sleep is not None and self.sleeps == self.stop_at_sleep:
            raise self.dr.Stopped(signal.SIGTERM)
        self.t += s
        if self.twin:
            self.connector()
        if self.unit == "active" and self.updater is not None:
            self.updater.poll()

    def connector(self) -> None:
        """The twin connector's stand-in: the record next-step.json names reaches the spool a few polls later."""
        nxt = self.record / "next-step.json"
        if not nxt.exists():
            return
        doc = json.loads(nxt.read_text(encoding="utf-8"))
        n = doc["n"]
        self.twin_seen[n] = self.twin_seen.get(n, 0) + 1
        if self.twin_seen[n] == self.twin_lag:
            want = self.spool_mod.encode(doc["record"])
            try:
                assert (self.spool / "desired.json").read_bytes() != want, "the drill wrote the spool itself"
            except FileNotFoundError:
                pass
            self.spool_mod.write(self.spool, doc["record"])

    # -- reading what happened --

    def named(self) -> List[str]:
        out = []
        for c in self.calls:
            if c[0] in ("popen", "terminate", "kill"):
                out.append(c[0])
                continue
            cmd = c[1]
            inner = cmd[len(SUDO):] if cmd[:len(SUDO)] == SUDO else cmd
            if inner[:2] == ["cat", "--"]:
                out.append("cat " + Path(inner[2]).name)
            elif cmd[:3] == [self.ota_py, "-B", str(OTA_LITE)]:
                out.append(" ".join(cmd[3:5]) if cmd[3] == "unit" else cmd[3])
            else:
                out.append(" ".join(cmd[:2]))
        return out

    def unit_start(self) -> List[str]:
        return next(c[1] for c in self.calls if c[0] == "run" and c[1][3:5] == ["unit", "start"])


@pytest.fixture()
def world(tmp_path: Path, ota: Any, spool: Any, monkeypatch: pytest.MonkeyPatch, dr: Any) -> World:
    return World(tmp_path, ota, spool, monkeypatch, dr)


def write_manifest(dr: Any, tmp_path: Path, host_role: str, arch: str, transport: str = "local-build") -> Tuple[Path, Path]:
    sr = stack_run(tmp_path, host_role)
    argv, out = manifest_argv(tmp_path, host_role, arch, transport, sr)
    assert dr.main(argv) == 0
    return out, sr


def run_argv(w: World, manifest: Path, sr: Path, via: str = "spool", timeout: int = 20, extra: Sequence[str] = ()) -> List[str]:
    w.stack_run_name = sr.name
    return ["run", "--manifest", str(manifest), "--state", str(w.state), "--record", str(w.record), "--stack-run", str(sr),
            "--sim-python", w.sim_py, "--ota-python", w.ota_py, "--via", via, "--spool-dir", str(w.spool),
            "--status-dir", str(w.status), "--sudo", " ".join(SUDO), "--step-timeout-s", str(timeout)] + list(extra)


def drill_run(dr: Any, w: World, argv: List[str]) -> int:
    return int(dr.main(argv, runner=w.runner, popen=w.popen, clock=w.clock, sleep=w.sleep))


def result(w: World) -> Dict[str, Any]:
    return json.loads((w.record / "drill-result.json").read_text(encoding="utf-8"))


def rows(res: Dict[str, Any]) -> List[Tuple[Any, ...]]:
    return [(s["n"], s["asks"], s["app_version"], s["scenario"], s["result"], s["refused_step"], s["rollback"]) for s in res["steps"]]


def assert_the_end_ran(w: World) -> None:
    names = w.named()
    tail = names[max(i for i, n in enumerate(names) if n == "unit start") + 1:]
    assert "terminate" in tail and "unit stop" in tail and "teardown" in tail
    assert tail.index("terminate") < tail.index("unit stop") < tail.index("teardown")
    assert "cat state.json" in tail and "cat ota-lite.jsonl" in tail
    assert names.count("unit stop") == 1 and names.count("teardown") == 1
    assert w.unit == "inactive"
    assert w.procs and all(p.returncode is not None for p in w.procs)


# --- run: the six steps --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("host_role, arch, via", [("pc", "amd64", "spool"), ("a1-metal", "arm64", "spool"), ("pc", "amd64", "twin")])
def test_the_six_steps_records_in_order(dr: Any, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                        host_role: str, arch: str, via: str) -> None:
    monkeypatch.setenv("REPO_COMMIT", COMMIT)
    manifest, sr = write_manifest(dr, tmp_path, host_role, arch)
    world.twin = via == "twin"
    assert drill_run(dr, world, run_argv(world, manifest, sr, via)) == 0
    res = result(world)
    assert rows(res) == TABLE
    assert res["format"] == 1 and res["verdict"] == "ok" and res["problems"] == []
    assert (res["host_role"], res["arch"], res["transport"], res["via"], res["repo_commit"]) == (host_role, arch, "local-build", via, COMMIT)
    assert res["manifest_sha256"] == "sha256:" + _sha(manifest.read_bytes())
    m = json.loads(manifest.read_text(encoding="utf-8"))
    by_version = {c["app_version"]: c["image_id"] for c in m["components"] if c["class"] == "app"}
    want_ids = [by_version["1.0.0"]] + [by_version["1.1.0"]] * 5
    for step, want in zip(res["steps"], want_ids):
        raw = (world.record / ("status-%d.json" % step["n"])).read_bytes()
        assert json.loads(raw) == {"image_id": want, "scenario": None, "result": step["result"]}
        assert step["image_id"] == want and isinstance(step["waited_s"], (int, float)) and step["timed_out"] is False
    assert (world.record / "ota-lite.jsonl").read_bytes() == (world.state / "ota-lite.jsonl").read_bytes()
    assert_the_end_ran(world)
    assert world.unexpected == []
    if via == "twin":
        nxt = json.loads((world.record / "next-step.json").read_text(encoding="utf-8"))
        assert nxt["n"] == 6 and nxt["record"] == {"image_id": None, "scenario": SCENARIO}


def test_each_spool_record_is_the_connectors_form(dr: Any, world: World, tmp_path: Path, spool: Any) -> None:
    """The records the drill writes are spool.py's own bytes, one per step, the platform one naming the bridge."""
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    seen: List[bytes] = []
    real = world.sleep

    def watch(s: float) -> None:
        try:
            data = (world.spool / "desired.json").read_bytes()
        except FileNotFoundError:
            data = b""
        if data and (not seen or seen[-1] != data):
            seen.append(data)
        real(s)
    world_sleep = watch
    assert int(dr.main(run_argv(world, manifest, sr), runner=world.runner, popen=world.popen, clock=world.clock,
                       sleep=world_sleep)) == 0
    m = json.loads(manifest.read_text(encoding="utf-8"))
    apps = {c["app_version"]: c["image_id"] for c in m["components"] if c["class"] == "app"}
    bridge = next(c["image_id"] for c in m["components"] if c["class"] == "platform")
    recs = [{"image_id": apps["1.0.0"], "scenario": None}, {"image_id": apps["1.1.0"], "scenario": None},
            {"image_id": apps["1.2.0"], "scenario": None}, {"image_id": bridge, "scenario": None},
            {"image_id": dr.UNKNOWN_IMAGE_ID, "scenario": None}, {"image_id": None, "scenario": SCENARIO}]
    assert seen == [spool.encode(r) for r in recs]
    assert dr.UNKNOWN_IMAGE_ID not in json.dumps(m)


def test_app_version_is_the_manifests_on_amd64_whose_ids_no_pin_holds(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    pins = json.loads((DRILL_DIR / "drill-images.json").read_text(encoding="utf-8"))
    assert not set(json.dumps(pins).split('"')) & {c["image_id"] for c in json.loads(manifest.read_text())["components"]}
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 0
    assert [s["app_version"] for s in result(world)["steps"]] == ["1.0.0"] + ["1.1.0"] * 5


def test_a_slow_updater_is_waited_for(dr: Any, world: World, tmp_path: Path) -> None:
    """Each step's status is read only after its own status event: a lag of many polls changes nothing."""
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.lag = 9
    assert drill_run(dr, world, run_argv(world, manifest, sr, timeout=30)) == 0
    assert rows(result(world)) == TABLE


def test_two_consecutive_refusals_are_told_apart_by_their_events(dr: Any) -> None:
    """Steps 4 and 5 write the same status bytes; each step's outcome is the first status event after its own record."""
    status = {"event": "status", "image_id": "sha256:" + "a" * 64, "scenario": None, "result": "refused"}
    log = [{"event": "record", "mark": "sha256:" + "4" * 64}, {"event": "refused", "step": "5", "reason": "r"}, dict(status, t_wall=1.0),
           {"event": "record", "mark": "sha256:" + "5" * 64}]
    assert dr.outcome(log, "sha256:" + "4" * 64, 0)["refused_step"] == "5"
    assert dr.outcome(log, "sha256:" + "5" * 64, 0) is None
    log += [{"event": "refused", "step": "4", "reason": "r"}, dict(status, t_wall=2.0)]
    got = dr.outcome(log, "sha256:" + "5" * 64, 0)
    assert got["refused_step"] == "4" and got["status"]["t_wall"] == 2.0 and got["rollback"] is False
    assert dr.outcome(log, "sha256:" + "4" * 64, 3) is None          # an earlier step's events are not this one's


# --- run: a step that never gets its status, and the end on every way out --------------------------------------------

def test_a_step_without_its_status_event_is_a_problem_and_the_rest_still_run(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    v2 = next(c["image_id"] for c in json.loads(manifest.read_text())["components"] if c.get("app_version") == "1.1.0")
    world.ignore = (v2,)
    assert drill_run(dr, world, run_argv(world, manifest, sr, timeout=7)) == 1
    res = result(world)
    assert [s["n"] for s in res["steps"]] == [1, 2, 3, 4, 5, 6]
    s2 = res["steps"][1]
    assert s2["timed_out"] is True and s2["result"] is None and s2["app_version"] is None
    assert [s["result"] for s in res["steps"][2:]] == ["rolled-back", "refused", "refused", "refused"]
    assert res["verdict"] == "not ok" and any("step 2" in p for p in res["problems"])
    assert_the_end_ran(world)


def test_the_last_step_timing_out_still_stops_everything(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.ignore = (None,)                 # the scenario request (no image) is never processed
    assert drill_run(dr, world, run_argv(world, manifest, sr, timeout=5)) == 1
    assert result(world)["steps"][-1]["timed_out"] is True
    assert_the_end_ran(world)
    assert (world.record / "state.json").exists() and (world.record / "ota-lite.jsonl").exists()


def test_an_error_mid_run_still_runs_the_end(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.cat_error_at = 12
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 1
    res = result(world)
    assert res["verdict"] == "not ok" and res["problems"]
    assert_the_end_ran(world)


def test_an_error_naming_a_host_path_leaves_no_path_in_the_record(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.break_status_at = "1.1.0"
    assert drill_run(dr, world, run_argv(world, manifest, sr, timeout=5)) == 1
    res = result(world)
    assert any("step 2" in p and "IsADirectoryError" in p for p in res["problems"])
    for f in world.record.iterdir():
        text = f.read_text(encoding="utf-8")
        assert str(tmp_path) not in text and "/tmp/" not in text, f.name
    assert_the_end_ran(world)


def test_a_stop_signal_mid_run_still_runs_the_end(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.stop_at_sleep = 8
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 1
    res = result(world)
    assert len(res["steps"]) < 6 and any("signal" in p for p in res["problems"])
    assert_the_end_ran(world)


def test_sigterm_raises_stopped_once_the_handlers_are_installed(dr: Any) -> None:
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        dr.install_signals()
        with pytest.raises(dr.Stopped):
            os.kill(os.getpid(), signal.SIGTERM)
            for _ in range(1000):
                pass
    finally:
        for s, h in saved.items():
            signal.signal(s, h)


def test_a_second_stop_signal_while_the_end_runs_does_not_cut_the_end_short(dr: Any, world: World, tmp_path: Path) -> None:
    """The first stop signal comes mid-run; a second one comes while `ota_lite.py unit stop` runs (the caller's cap
    repeating itself). The end ignores it: the record is written and the teardown and the copies still happen."""
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.stop_at_sleep = 8
    world.on_unit_stop = lambda: os.kill(os.getpid(), signal.SIGTERM)
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        dr.install_signals()
        assert drill_run(dr, world, run_argv(world, manifest, sr)) == 1
    finally:
        for s, h in saved.items():
            signal.signal(s, h)
    assert (world.record / "drill-result.json").exists()
    names = world.named()
    tail = names[names.index("unit stop") + 1:]
    assert "teardown" in tail and "cat ota-lite.jsonl" in tail and "cat state.json" in tail
    assert names.count("unit stop") == 1 and names.count("teardown") == 1 and world.unit == "inactive"


def test_a_failed_unit_start_is_undone_and_refused(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.unit_start_rc = 1
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 2
    names = world.named()
    assert "unit stop" in names and "teardown" in names and "popen" not in names
    assert world.unexpected == []


def test_a_refused_unit_start_prints_the_updaters_reason_and_the_record_does_not_hold_it(
        dr: Any, world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A metal session's run.log is the drill's output: the launcher's reason (its stdout and stderr, line by line, each
    prefixed as the drill's own lines are) is there, and the record, which is the updater's and the drill's facts, holds
    none of it."""
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.unit_start_rc = 2
    world.unit_start_err = "ota-lite: refused: a stand-in's reason\nand its second line\n"
    capsys.readouterr()
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 2
    out = capsys.readouterr().out
    assert "drill.py run: ota_lite.py unit start exited 2\n" in out
    assert "drill.py run: ota-lite: refused: a stand-in's reason\n" in out and "drill.py run: and its second line\n" in out
    assert "drill.py run: ota-lite: unit ota-lite is inactive\n" in out                 # its stdout, the same way
    for f in world.record.iterdir():
        assert "a stand-in's reason" not in f.read_text(encoding="utf-8"), f.name


def test_a_player_that_cannot_start_is_undone_and_refused(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.popen_error = True
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 2
    names = world.named()
    assert names.index("unit start") < names.index("popen") < names.index("unit stop") < names.index("teardown")
    assert world.unit == "inactive"


def test_the_player_plays_the_stacks_recording_on_vcan0_in_a_loop(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.player_exit_after = 4
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 0
    starts = [c[1] for c in world.calls if c[0] == "popen"]
    assert len(starts) > 2
    assert all(cmd == [world.sim_py, "-m", "can.player", "-i", "socketcan", "-c", "vcan0", str(sr / "in" / "sigsim.log")]
               for cmd in starts)
    assert "terminate" in world.named()
    assert result(world)["player"]["starts"] == len(starts)


def test_a_player_that_never_played_is_a_problem(dr: Any, world: World, tmp_path: Path) -> None:
    """Every start of the player exiting non-zero at once (no python-can in the sim venv, no vcan0 access): the
    recording was never played, so the verdict is not ok whatever the updater said; the last start, which ended by
    itself before the end, counts as one of them."""
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.player_exit_after = 1
    world.player_rcs = [1] * 1000
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 1
    res = result(world)
    assert rows(res) == TABLE                                         # the updater's stand-in answers regardless
    assert res["player"]["starts"] == len(world.procs) > 2
    assert res["player"]["nonzero_exits"] == res["player"]["starts"]
    assert res["verdict"] == "not ok" and any("player never played" in p for p in res["problems"])
    names = world.named()
    assert "unit stop" in names and "teardown" in names and world.unit == "inactive"


def test_a_player_that_failed_once_and_then_played_is_no_problem(dr: Any, world: World, tmp_path: Path) -> None:
    """The rule is every start: one start that exited non-zero and later ones that played leave the verdict ok, and the
    one failure stands in the record's count."""
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.player_exit_after = 4
    world.player_rcs = [1]
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 0
    res = result(world)
    assert res["verdict"] == "ok" and res["player"]["nonzero_exits"] == 1 < res["player"]["starts"]


@pytest.mark.parametrize("rc, counted", [(1, 1), (0, 0)])
def test_a_player_that_ended_on_its_own_before_the_stop_is_counted_by_its_exit_status(dr: Any, rc: int, counted: int) -> None:
    """stop() finds a player that has already exited: a non-zero status is one of the record's nonzero_exits, a zero
    status is none."""
    class Ended:
        def poll(self) -> int:
            return rc

    p = dr.Player(["player"], lambda cmd: Ended(), lambda: 0.0)
    p.start()
    assert p.stop() is True
    assert p.record() == {"starts": 1, "nonzero_exits": counted}


def test_a_player_that_does_not_end_when_asked_is_killed(dr: Any, world: World, tmp_path: Path) -> None:
    """The first wait after terminate times out (a player that ignores it): the end kills it, and says it is stopped."""
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.wait_timeouts = 1
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 0
    names = world.named()
    assert names.index("terminate") < names.index("kill") < names.index("unit stop")
    assert result(world)["end"]["player_stopped"] is True


def test_a_status_file_with_its_keys_in_another_order_is_not_the_status_record(dr: Any, world: World, tmp_path: Path) -> None:
    """The status record is image_id, scenario, result in that order (write_status's bytes); the same keys in another
    order are not it, so no step reads a status from them."""
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.reorder_status = True
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 1
    res = result(world)
    assert len([p for p in res["problems"] if "not the status record" in p]) == 6
    assert all(s["result"] is None and s["app_version"] is None for s in res["steps"])
    assert res["verdict"] == "not ok"
    assert_the_end_ran(world)


def test_a_twin_record_that_never_reaches_the_spool_is_a_problem_that_names_the_spool(dr: Any, world: World, tmp_path: Path) -> None:
    """--via twin: the connector's stand-in never writes. Each step waits for the record in the spool, times out there
    (not later, at the updater's log) and the rest still run."""
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    world.twin, world.twin_lag = True, 10 ** 9
    assert drill_run(dr, world, run_argv(world, manifest, sr, "twin", timeout=4)) == 1
    res = result(world)
    assert [s["n"] for s in res["steps"]] == [1, 2, 3, 4, 5, 6] and all(s["timed_out"] and s["result"] is None for s in res["steps"])
    steps = [p for p in res["problems"] if p.startswith("step ")]
    assert len(steps) == 6 and all("did not reach the spool" in p for p in steps), steps
    assert not (world.spool / "desired.json").exists()
    assert_the_end_ran(world)


def test_the_unit_start_carries_the_runs_arguments(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "orin", "arm64", "ecr")
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"registry": REGISTRY}), encoding="utf-8")
    os.chmod(str(reg), 0o600)
    extra = ["--cpuset", "3,5", "--registry-file", str(reg), "--docker-config", str(tmp_path / "dcfg"), "--home", str(tmp_path)]
    assert drill_run(dr, world, run_argv(world, manifest, sr, extra=extra)) == 0
    argv = world.unit_start()
    pairs = {argv[i]: argv[i + 1] for i in range(5, len(argv) - 1) if argv[i].startswith("--")}
    assert argv[:5] == [world.ota_py, "-B", str(OTA_LITE), "unit", "start"]
    assert pairs["--manifest"] == str(manifest) and pairs["--host-role"] == "orin" and pairs["--arch"] == "arm64"
    assert pairs["--state"] == str(world.state) and pairs["--python"] == world.ota_py
    assert pairs["--cpuset"] == "3,5" and pairs["--cpus"] == "3,5" and pairs["--registry-file"] == str(reg)
    assert pairs["--spool-dir"] == str(world.spool) and pairs["--status-dir"] == str(world.status)
    assert pairs["--marker"] == str(world.marker) and pairs["--docker"] == "docker"
    assert pairs["--docker-config"] == str(tmp_path / "dcfg") and pairs["--home"] == str(tmp_path)
    # the record holds no registry host and no path outside it; the updater's log in it is the updater's own
    for f in world.record.iterdir():
        text = f.read_text(encoding="utf-8")
        assert REGISTRY not in text and "dkr.ecr" not in text, f.name
        assert str(tmp_path) not in text and "/tmp/" not in text, f.name


def test_the_log_and_state_are_read_through_sudo(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    (world.state).mkdir()
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 0
    cats = [c[1] for c in world.calls if c[0] == "run" and "cat" in c[1]]
    assert cats and all(c[:len(SUDO) + 2] == SUDO + ["cat", "--"] for c in cats)
    assert cats[0] == SUDO + ["cat", "--", "/dev/null"]          # the probe of --sudo, before anything starts
    assert world.named().index("cat null") < world.named().index("unit start")
    assert {Path(c[-1]).name for c in cats[1:]} == {"ota-lite.jsonl", "state.json"}


def test_run_never_starts_or_stops_the_stack(dr: Any, world: World, tmp_path: Path) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    assert drill_run(dr, world, run_argv(world, manifest, sr)) == 0
    for c in world.calls:
        if c[0] == "run":
            assert not any("stack.py" in a for a in c[1]), c
            if c[1][0] == "docker":
                assert c[1][1] == "ps", c
    assert world.unexpected == []


# --- run: the refusals before anything starts ------------------------------------------------------------------------

REFUSALS = ["no-stack-manifest", "stack-app-not-external", "stack-not-up", "stack-down", "databroker-not-running",
            "can-provider-not-running", "stack-other-host",
            "qemu", "ota-app", "unit-active", "marker", "record-exists", "state-not-empty", "spool-record", "no-vcan0",
            "repo-commit", "manifest-not-a-drills", "no-sim-python", "sudo-cannot-run", "unit-activating", "marker-unlookable",
            "marker-relative", "no-ota-python", "state-is-a-file", "step-timeout-zero", "state-in-repo",
            "manifest-holds-the-unknown-id"]


@pytest.mark.parametrize("case", REFUSALS)
def test_run_refuses_before_anything_starts(dr: Any, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    manifest, sr = write_manifest(dr, tmp_path, "pc", "amd64")
    argv = run_argv(world, manifest, sr)
    if case == "no-stack-manifest":
        (sr / "manifest.json").unlink()
    elif case == "stack-app-not-external":
        m = json.loads((sr / "manifest.json").read_text(encoding="utf-8"))
        m["app"] = "stack"
        (sr / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    elif case == "stack-not-up":
        (sr / "up").rmdir()
    elif case == "stack-down":
        world.stack_up = False
    elif case == "databroker-not-running":
        world.stack_names.remove("sdv-stack-databroker")
    elif case == "can-provider-not-running":
        world.stack_names.remove("sdv-stack-can-provider")
    elif case == "stack-other-host":
        m = json.loads((sr / "manifest.json").read_text(encoding="utf-8"))
        m["host_role"] = "a1-metal"
        (sr / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    elif case == "qemu":
        (world.proc / "4242").mkdir()
        (world.proc / "4242" / "comm").write_text("qemu-system-aar\n", encoding="utf-8")
    elif case == "ota-app":
        world.ota_app = True
    elif case == "unit-active":
        world.unit = "active"
    elif case == "marker":
        world.marker.write_text("", encoding="utf-8")
    elif case == "record-exists":
        world.record.mkdir()
    elif case == "state-not-empty":
        world.state.mkdir()
        (world.state / "processed").write_text("sha256:" + "0" * 64, encoding="utf-8")
    elif case == "spool-record":
        (world.spool / "desired.json").write_bytes(b'{"image_id":null,"scenario":"20990101-sigsim-42"}')
    elif case == "no-vcan0":
        (world.net / "vcan0").rmdir()
    elif case == "repo-commit":
        monkeypatch.setenv("REPO_COMMIT", "not-a-commit")
    elif case == "manifest-not-a-drills":
        m = json.loads(manifest.read_text(encoding="utf-8"))
        m["components"] = [c for c in m["components"] if c.get("app_version") != "1.2.0"]
        manifest.write_text(json.dumps(m), encoding="utf-8")
    elif case == "no-sim-python":
        os.unlink(world.sim_py)
    elif case == "sudo-cannot-run":
        world.sudo_ok = False                 # no NOPASSWD: every log read would fail and each step wait its whole timeout
    elif case == "unit-activating":
        world.unit = "activating"             # ACTIVE_STATES holds more than `active`
    elif case == "marker-unlookable":
        real_lstat = os.lstat

        def lstat(path: Any, *args: Any, **kwargs: Any) -> Any:
            if str(path) == str(world.marker):
                raise PermissionError(13, "Permission denied")        # the entry cannot be looked for: it counts as there
            return real_lstat(path, *args, **kwargs)
        monkeypatch.setattr(dr.os, "lstat", lstat)
    elif case == "marker-relative":
        monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", "twin-control")
    elif case == "no-ota-python":
        os.unlink(world.ota_py)
    elif case == "state-is-a-file":
        world.state.write_text("a file, not a directory", encoding="utf-8")
    elif case == "step-timeout-zero":
        argv = run_argv(world, manifest, sr, timeout=0)
    elif case == "state-in-repo":
        argv[argv.index("--state") + 1] = str(dr.REPO / "state-from-a-test")           # never made: the refusal comes first
    elif case == "manifest-holds-the-unknown-id":
        m = json.loads(manifest.read_text(encoding="utf-8"))
        m["components"][0]["image_id"] = dr.UNKNOWN_IMAGE_ID
        manifest.write_text(json.dumps(m), encoding="utf-8")
    before = world.record.exists()
    try:
        assert drill_run(dr, world, argv) == 2
    finally:
        if case == "state-in-repo" and (dr.REPO / "state-from-a-test").exists():
            shutil.rmtree(str(dr.REPO / "state-from-a-test"))
    names = world.named()
    assert "unit start" not in names and "popen" not in names and "teardown" not in names
    assert world.record.exists() == before
    if case == "record-exists":
        assert list(world.record.iterdir()) == []


@pytest.mark.parametrize("transport, cpuset, registry, rc", [
    ("ecr", "3,5", False, 2), ("ecr", None, True, 2), ("local-build", "3,5", False, 0), ("ecr", "3,5", True, 0)],
    ids=["ecr-without-registry-file", "orin-without-cpuset", "orin-local-build-needs-no-registry-file", "orin-ecr-with-both"])
def test_run_refuses_up_front_what_the_units_launcher_would_refuse(dr: Any, world: World, tmp_path: Path, transport: str,
                                                                   cpuset: Optional[str], registry: bool, rc: int) -> None:
    """ota_lite.py unit start refuses an ecr manifest without --registry-file and the orin without a CPU list; the drill
    refuses both before it makes the record directory, so a refused run leaves nothing that blocks the next."""
    manifest, sr = write_manifest(dr, tmp_path, "orin", "arm64", transport)
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"registry": REGISTRY}), encoding="utf-8")
    os.chmod(str(reg), 0o600)
    extra = (["--cpuset", cpuset] if cpuset else []) + (["--registry-file", str(reg)] if registry else [])
    assert drill_run(dr, world, run_argv(world, manifest, sr, extra=extra)) == rc
    names = world.named()
    if rc == 2:
        assert "unit start" not in names and "popen" not in names and "teardown" not in names
        assert not world.record.exists() and not world.state.exists()
    else:
        assert "unit start" in names and result(world)["verdict"] == "ok"


def test_a_qemu_is_found_by_its_comm_whole_or_cut(dr: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = tmp_path / "proc"
    for pid, comm in (("1", "systemd"), ("77", "qemu-system-aar"), ("78", "python3"), ("79", "qemu-kvm"), ("self", "pytest")):
        (proc / pid).mkdir(parents=True)
        (proc / pid / "comm").write_text(comm + "\n", encoding="utf-8")
    monkeypatch.setattr(dr, "PROC", str(proc))
    assert dr.qemu_pids() == [77, 79]                      # the older launcher name, qemu-kvm, is a QEMU too
    (proc / "77" / "comm").write_text("qemu-system-aarch64\n", encoding="utf-8")
    assert dr.qemu_pids() == [77, 79]
    shutil.rmtree(str(proc / "77"))
    assert dr.qemu_pids() == [79]
    shutil.rmtree(str(proc / "79"))
    assert dr.qemu_pids() == []


# --- compare -----------------------------------------------------------------------------------------------------------

def host_result(tmp_path: Path, role: str, arch: str, change: Optional[Tuple[int, str, Any]] = None) -> Path:
    ids = {"amd64": ("sha256:" + "1" * 64, "sha256:" + "2" * 64), "arm64": ("sha256:" + "3" * 64, "sha256:" + "4" * 64)}[arch]
    steps = []
    for n, asks, ver, scn, res, refused, rb in TABLE:
        steps.append({"n": n, "asks": asks, "image_id": ids[0] if n == 1 else ids[1], "app_version": ver, "scenario": scn,
                      "result": res, "refused_step": refused, "rollback": rb, "waited_s": 1.5 * n, "timed_out": False})
    if change:
        steps[change[0] - 1][change[1]] = change[2]
    d = tmp_path / role
    d.mkdir()
    doc = {"format": 1, "host_role": role, "arch": arch, "transport": "tar", "via": "spool", "repo_commit": None,
           "manifest_sha256": "sha256:" + _sha(role.encode()), "steps": steps, "verdict": "ok", "problems": []}
    (d / "drill-result.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return d


def test_compare_is_equal_across_architectures(dr: Any, tmp_path: Path) -> None:
    pc, metal = host_result(tmp_path, "pc", "amd64"), host_result(tmp_path, "a1-metal", "arm64")
    out = tmp_path / "cmp"
    assert dr.main(["compare", "--host", "pc=%s" % pc, "--host", "a1-metal=%s" % metal, "--out", str(out)]) == 0
    doc = json.loads((out / "compare.json").read_text(encoding="utf-8"))
    assert doc["equal"] is True and doc["first_difference"] is None
    assert doc["key"] == ["asks", "app_version", "scenario", "result", "refused_step"]
    assert [h["role"] for h in doc["hosts"]] == ["pc", "a1-metal"]


@pytest.mark.parametrize("change, n", [((5, "refused_step", "5"), 5), ((3, "result", "applied"), 3), ((2, "app_version", "1.0.0"), 2),
                                       ((6, "scenario", SCENARIO), 6), ((4, "asks", "image v1"), 4)])
def test_compare_names_the_first_difference(dr: Any, tmp_path: Path, change: Tuple[int, str, Any], n: int) -> None:
    pc, metal = host_result(tmp_path, "pc", "amd64"), host_result(tmp_path, "a1-metal", "arm64", change)
    out = tmp_path / "cmp"
    assert dr.main(["compare", "--host", "pc=%s" % pc, "--host", "a1-metal=%s" % metal, "--out", str(out)]) == 1
    doc = json.loads((out / "compare.json").read_text(encoding="utf-8"))
    assert doc["equal"] is False and doc["first_difference"]["n"] == n


def test_compare_ignores_what_is_not_in_the_key(dr: Any, tmp_path: Path) -> None:
    pc = host_result(tmp_path, "pc", "amd64", (3, "waited_s", 99.0))
    metal = host_result(tmp_path, "a1-metal", "arm64", (3, "rollback", False))
    assert dr.main(["compare", "--host", "pc=%s" % pc, "--host", "a1-metal=%s" % metal, "--out", str(tmp_path / "c")]) == 0


def test_compare_with_a_missing_step_is_a_difference(dr: Any, tmp_path: Path) -> None:
    pc, metal = host_result(tmp_path, "pc", "amd64"), host_result(tmp_path, "a1-metal", "arm64")
    doc = json.loads((metal / "drill-result.json").read_text(encoding="utf-8"))
    doc["steps"] = doc["steps"][:4]
    (metal / "drill-result.json").write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "cmp"
    assert dr.main(["compare", "--host", "pc=%s" % pc, "--host", "a1-metal=%s" % metal, "--out", str(out)]) == 1
    assert json.loads((out / "compare.json").read_text(encoding="utf-8"))["first_difference"]["n"] == 5


@pytest.mark.parametrize("case, n", [("no-steps", 1), ("the-same-two-steps", 3), ("no-answer-anywhere", 1),
                                     ("both-unanswered-at-step-2", 2)])
def test_compare_is_never_equal_without_six_answered_steps(dr: Any, tmp_path: Path, case: str, n: int) -> None:
    """Two records that lack the same steps (both runs refused at unit start, or cut by a signal after the same steps),
    or whose same step got no answer on both, do not hold 2.2's six-step sequence: they are a difference at the first
    missing or unanswered step, exit 1, never `equal`."""
    pc, metal = host_result(tmp_path, "pc", "amd64"), host_result(tmp_path, "a1-metal", "arm64")
    for d in (pc, metal):
        doc = json.loads((d / "drill-result.json").read_text(encoding="utf-8"))
        if case == "no-steps":
            doc["steps"] = []
        elif case == "the-same-two-steps":
            doc["steps"] = doc["steps"][:2]
        else:
            for s in doc["steps"] if case == "no-answer-anywhere" else doc["steps"][1:2]:
                s.update(image_id=None, app_version=None, scenario=None, result=None, refused_step=None, rollback=False,
                         timed_out=True)
        doc["verdict"] = "not ok"
        (d / "drill-result.json").write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "cmp"
    assert dr.main(["compare", "--host", "pc=%s" % pc, "--host", "a1-metal=%s" % metal, "--out", str(out)]) == 1
    doc = json.loads((out / "compare.json").read_text(encoding="utf-8"))
    assert doc["equal"] is False and doc["first_difference"]["n"] == n
    why = doc["first_difference"]["why"]
    assert ("no step %d on pc, a1-metal" % n if case in ("no-steps", "the-same-two-steps")
            else "step %d has no answer on pc, a1-metal" % n) == why


@pytest.mark.parametrize("case", ["role-mismatch", "missing-result", "same-role-twice", "no-equals", "compare-exists", "unknown-role",
                                  "steps-out-of-order", "seven-steps", "a-step-not-an-object", "out-is-a-file", "format-2"])
def test_compare_refusals(dr: Any, tmp_path: Path, case: str) -> None:
    pc, metal = host_result(tmp_path, "pc", "amd64"), host_result(tmp_path, "a1-metal", "arm64")
    out = tmp_path / "cmp"
    hosts = ["pc=%s" % pc, "a1-metal=%s" % metal]
    if case == "role-mismatch":
        hosts[1] = "orin=%s" % metal
    elif case == "unknown-role":
        hosts[1] = "laptop=%s" % host_result(tmp_path, "laptop", "arm64")     # its own role's record: only HOST_ROLES refuses it
    elif case in ("steps-out-of-order", "seven-steps", "a-step-not-an-object"):
        doc = json.loads((metal / "drill-result.json").read_text(encoding="utf-8"))
        if case == "steps-out-of-order":
            doc["steps"][2], doc["steps"][3] = doc["steps"][3], doc["steps"][2]
        elif case == "seven-steps":
            doc["steps"].append(dict(doc["steps"][-1], n=7))
        else:
            doc["steps"][2] = "step 3"
        (metal / "drill-result.json").write_text(json.dumps(doc), encoding="utf-8")
    elif case == "missing-result":
        (metal / "drill-result.json").unlink()
    elif case == "same-role-twice":
        # both records are a pc's, so only the duplicate role can refuse them
        doc = json.loads((metal / "drill-result.json").read_text(encoding="utf-8"))
        doc["host_role"] = "pc"
        (metal / "drill-result.json").write_text(json.dumps(doc), encoding="utf-8")
        hosts[1] = "pc=%s" % metal
    elif case == "format-2":
        doc = json.loads((metal / "drill-result.json").read_text(encoding="utf-8"))
        doc["format"] = 2
        (metal / "drill-result.json").write_text(json.dumps(doc), encoding="utf-8")
    elif case == "no-equals":
        hosts[1] = str(metal)
    elif case == "out-is-a-file":
        out.write_text("a file, not a directory", encoding="utf-8")
    elif case == "compare-exists":
        out.mkdir()
        (out / "compare.json").write_text("{}", encoding="utf-8")
    argv = ["compare"] + [x for h in hosts for x in ("--host", h)] + ["--out", str(out)]
    assert dr.main(argv) == 2
    if case != "compare-exists":
        assert not (out / "compare.json").exists()


@pytest.mark.parametrize("case", ["amd64-write-pins", "arm64-store-ids", "amd64-no-store-ids", "save-out-exists", "save-bad-commit"])
def test_build_drill_refusals(bd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    """A refusal is exit 2 before anything is asked of the image store."""
    store = FakeStore(tmp_path)
    argv = {"amd64-write-pins": ["build", "--arch", "amd64", "--store-ids", str(tmp_path / "ids.json"), "--write-pins"],
            "arm64-store-ids": ["build", "--arch", "arm64", "--store-ids", str(tmp_path / "ids.json")],
            "amd64-no-store-ids": ["build", "--arch", "amd64"],
            "save-out-exists": ["save", "--out", str(tmp_path / "sdv-drill.tar")],
            "save-bad-commit": ["save", "--out", str(tmp_path / "new.tar")]}[case]
    if case == "save-out-exists":
        monkeypatch.setenv("REPO_COMMIT", COMMIT)
        (tmp_path / "sdv-drill.tar").write_bytes(b"a tar already there")
    elif case == "save-bad-commit":
        monkeypatch.setenv("REPO_COMMIT", "abc")
    elif case == "amd64-no-store-ids":
        # outside the repo, so that `<cwd>/None` is no path inside it: the missing option is the only refusal left
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bd, "WORK_ROOT", tmp_path / "work")
    assert bd.main(argv, docker=store) == 2
    assert store.calls == []


# --- the images: v2's edit, v3's config, the proof -------------------------------------------------------------------

def test_v2s_edit_changes_exactly_the_two_constants(bd: Any, tmp_path: Path) -> None:
    src = HAZARD_FILE.read_text(encoding="utf-8")
    out = bd.edit_v2(src)
    diff = [d for d in difflib.ndiff(src.splitlines(), out.splitlines()) if d[:2] in ("- ", "+ ")]
    assert sorted(diff) == sorted(['- APP_VERSION = "1.0.0"', '+ APP_VERSION = "1.1.0"', "- DECEL_OFF_MPS2 = 3.0", "+ DECEL_OFF_MPS2 = 2.5"])
    assert "DECEL_OFF_MPS2 = 3.0 m/s^2." in out          # the docstring is not a constant
    f = tmp_path / "hazard_v2.py"
    f.write_text(out, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("hazard_v2", str(f))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.modules["hazard_v2"] = mod                       # a dataclass looks its module up while it is made
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
        del sys.modules["hazard_v2"]
    assert (mod.APP_VERSION, mod.DECEL_OFF_MPS2, mod.DECEL_ON_MPS2) == ("1.1.0", 2.5, 4.0)
    assert mod.decide(True, 2.6) is True and mod.decide(True, 2.4) is False     # the behaviour the change shows


@pytest.mark.parametrize("case", ["version-missing", "decel-missing", "version-doubled", "decel-doubled", "applied-twice"])
def test_v2s_edit_refuses_a_source_whose_old_text_is_missing_or_doubled(bd: Any, case: str) -> None:
    src = HAZARD_FILE.read_text(encoding="utf-8")
    if case == "version-missing":
        src = src.replace('\nAPP_VERSION = "1.0.0"\n', '\nAPP_VERSION = "1.0.1"\n')
    elif case == "decel-missing":
        src = src.replace("\nDECEL_OFF_MPS2 = 3.0\n", "\nDECEL_OFF_MPS2 = 3.5\n")
    elif case == "version-doubled":
        src = src + '\nAPP_VERSION = "1.0.0"\n'
    elif case == "decel-doubled":
        src = src + "\nDECEL_OFF_MPS2 = 3.0\n"
    else:
        src = bd.edit_v2(src)
    with pytest.raises(bd.BuildError):
        bd.edit_v2(src)


def test_the_apps_source_holds_each_old_text_once(bd: Any) -> None:
    src = HAZARD_FILE.read_text(encoding="utf-8")
    assert [src.count(old) for old, _new in bd.EDITS] == [1, 1]
    assert [old.strip() for old, _new in bd.EDITS] == ['APP_VERSION = "1.0.0"', "DECEL_OFF_MPS2 = 3.0"]


def test_v2s_staged_context_is_the_edited_copy_and_its_dockerfile(bd: Any, tmp_path: Path) -> None:
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    rec = bd.stage_v2(ctx, "sdv-local/hard-brake-hazard:1.0.0-arm64")
    assert sorted(p.name for p in ctx.iterdir()) == ["Dockerfile", "hazard.py"]
    assert (ctx / "hazard.py").read_text(encoding="utf-8") == bd.edit_v2(HAZARD_FILE.read_text(encoding="utf-8"))
    lines = [ln for ln in (ctx / "Dockerfile").read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    assert lines == ["FROM sdv-local/hard-brake-hazard:1.0.0-arm64", 'LABEL org.opencontainers.image.version="1.1.0"',
                     "COPY hazard.py /app/hazard.py"]
    assert rec["hazard.py"] == "sha256:" + _sha((ctx / "hazard.py").read_bytes())
    assert HAZARD_FILE.read_text(encoding="utf-8").count('APP_VERSION = "1.0.0"') == 1      # the repo's copy is untouched
    with pytest.raises(bd.BuildError):
        bd.stage_v2(DRILL_DIR, "sdv-local/hard-brake-hazard:1.0.0-arm64")


def _paths(a: Any, b: Any, at: str = "") -> List[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += _paths(a.get(k), b.get(k), at + "." + k if at else k)
        return out
    return [] if a == b else [at]


def test_v3s_config_differs_from_v2s_in_the_entrypoint_alone(bd: Any) -> None:
    v2 = drill_set()["1.1.0"]
    v3 = bd.v3_config(v2.config)
    a, b = json.loads(v2.config), json.loads(v3)
    assert _paths(a, b) == ["config.Entrypoint"]
    assert b["config"]["Entrypoint"] == ["python", "-c", "raise SystemExit(3)"]
    assert bd.config_problems(a, b) == []


@pytest.mark.parametrize("case, reason", [("a-layer", "layers are not v2's"), ("a-label", "beyond the entrypoint"),
                                          ("same-entrypoint", "entrypoint is v2's"), ("history", "history is not v2's")],
                         ids=["a-layer", "a-label", "same-entrypoint", "history"])
def test_config_problems_refuse_anything_but_the_entrypoint(bd: Any, case: str, reason: str) -> None:
    a = json.loads(drill_set()["1.1.0"].config)
    b = json.loads(bd.v3_config(json.dumps(a).encode()))
    if case == "a-layer":
        b["rootfs"]["diff_ids"].append("sha256:" + "9" * 64)
    elif case == "a-label":
        b["config"]["Labels"]["org.opencontainers.image.version"] = "1.2.0"
    elif case == "same-entrypoint":
        b["config"]["Entrypoint"] = a["config"]["Entrypoint"]
    else:
        b["history"].append({"created_by": "another"})
    problems = bd.config_problems(a, b)
    assert any(reason in p for p in problems), problems


def test_v3s_image_has_v2s_layers_and_no_other(bd: Any, tmp_path: Path) -> None:
    v2 = drill_set()["1.1.0"]
    src = tmp_path / "v2.tar"
    save_tar(src, [v2])
    out = tmp_path / "v3.tar"
    made = bd.v3_layout(src, v2.id, out, "sdv-drill/hard-brake-hazard:1.2.0-arm64")
    with tarfile.open(str(out)) as tf:
        idx = json.loads(tf.extractfile("index.json").read())                       # type: ignore[union-attr]
        [desc] = idx["manifests"]
        man_raw = tf.extractfile("blobs/sha256/" + desc["digest"][7:]).read()        # type: ignore[union-attr]
        man = json.loads(man_raw)
        names = {m.name for m in tf.getmembers()}
    v2man = json.loads(v2.manifest)
    assert man["layers"] == v2man["layers"] and man["mediaType"] == v2man["mediaType"]
    assert desc["digest"] == "sha256:" + _sha(man_raw) == made["id"]
    assert man["config"]["digest"] == made["config_digest"] != v2.config_digest
    assert desc["annotations"]["io.containerd.image.name"] == "docker.io/sdv-drill/hard-brake-hazard:1.2.0-arm64"
    layer_names = {"blobs/sha256/" + d["digest"][7:] for d in v2man["layers"]}
    assert names == {"oci-layout", "index.json", "blobs", "blobs/sha256", "blobs/sha256/" + desc["digest"][7:],
                     "blobs/sha256/" + made["config_digest"][7:]} | layer_names


@pytest.mark.parametrize("case", ["one-layer-more", "no-layer-more", "base-changed"])
def test_v2_is_v1_plus_one_layer(bd: Any, case: str) -> None:
    s = drill_set()
    v1, v2 = json.loads(s["1.0.0"].config), json.loads(s["1.1.0"].config)
    if case == "one-layer-more":
        assert bd.layer_problems(v1, v2) == []
        return
    if case == "no-layer-more":
        v2["rootfs"]["diff_ids"] = list(v1["rootfs"]["diff_ids"])
    else:
        v2["rootfs"]["diff_ids"][0] = "sha256:" + "8" * 64
    assert bd.layer_problems(v1, v2)


def test_an_index_is_refused_where_an_image_is_proved(dr: Any) -> None:
    img = drill_set()["1.0.0"]
    idx = json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [
        {"mediaType": OCI_MANIFEST, "digest": img.id, "size": len(img.manifest)}]}).encode()
    blobs = dict(img.blobs(), **{"sha256:" + _sha(idx): idx})
    man, cfg, cd = dr.image_of(blobs.get, img.id)
    assert cd == img.config_digest and cfg["architecture"] == "arm64"
    with pytest.raises(dr.DrillError, match="index"):
        dr.image_of(blobs.get, "sha256:" + _sha(idx))
    bare = json.dumps({"schemaVersion": 2, "manifests": []}).encode()        # an index with no mediaType
    with pytest.raises(dr.DrillError, match="index"):
        dr.image_of({"sha256:" + _sha(bare): bare}.get, "sha256:" + _sha(bare))
    with pytest.raises(dr.DrillError):
        dr.image_of({img.id: img.manifest + b" "}.get, img.id)              # a blob that is not its digest


# --- the pins ------------------------------------------------------------------------------------------------------------

def test_drill_images_pins_v1_as_images_json_does_and_v2_v3_on_their_bases() -> None:
    pins = json.loads((DRILL_DIR / "drill-images.json").read_text(encoding="utf-8"))
    pin = json.loads(IMAGES_FILE.read_text(encoding="utf-8"))["local"][APP]["arm64"]
    a = pins["arm64"]
    assert sorted(a) == list(VERSIONS)
    assert {k: a["1.0.0"][k] for k in ("id", "config_digest", "tag")} == {k: pin[k] for k in ("id", "config_digest", "tag")}
    assert a["1.1.0"]["base"] == {"id": a["1.0.0"]["id"], "config_digest": a["1.0.0"]["config_digest"]}
    assert a["1.2.0"]["base"] == {"id": a["1.1.0"]["id"], "config_digest": a["1.1.0"]["config_digest"]}
    assert (a["1.1.0"]["tag"], a["1.2.0"]["tag"]) == ("sdv-drill/hard-brake-hazard:1.1.0-arm64", "sdv-drill/hard-brake-hazard:1.2.0-arm64")
    ids = [a[v][k] for v in VERSIONS for k in ("id", "config_digest")]
    assert len(set(ids)) == 6 and all(len(i) == 71 and i.startswith("sha256:") for i in ids)


# --- build_drill.py against a stand-in image store ------------------------------------------------------------------

class FakeStore:
    """Docker's image store as build_drill.py's seam sees it: inspect, save -o, build and buildx build of a staged
    context (one layer holding the edited hazard.py), and load of an OCI layout named by its annotation."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.images: Dict[str, Img] = {}
        self.tags: Dict[str, str] = {}
        self.calls: List[List[str]] = []
        self.index_type = OCI_MANIFEST         # how a save's index.json types each image it lists
        self.keep_base_label = False           # a build leaves the base's version label as it was (it does not set 1.1.0)
        self.load_under_another_id = False     # a load registers the image under a manifest of the store's own: another ID
        self.save_extra: Optional[Img] = None  # a save of one ID lists this image too
        self.platform_check = True             # buildx refuses a --platform that is not its base's architecture

    def add(self, img: Img, tag: Optional[str] = None) -> None:
        self.images[img.id] = img
        if tag:
            self.tags[tag] = img.id

    def resolve(self, ref: str) -> Optional[Img]:
        if ref in self.images:
            return self.images[ref]
        return self.images.get(self.tags.get(ref, ""))

    def run(self, args: Sequence[str], timeout: Optional[float] = None) -> Done:
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["image", "inspect"] and args[2:4] == ["-f", "{{.Id}}"]:
            img = self.resolve(args[4])
            return Done(0, img.id + "\n", "") if img else Done(1, "", "Error: No such image")
        if args[:2] == ["save", "-o"]:
            imgs = [self.resolve(r) for r in args[3:]]
            if not all(imgs):
                return Done(1, "", "no such image")
            if self.save_extra is not None and len(imgs) == 1:
                imgs.append(self.save_extra)
            save_tar(Path(args[2]), [i for i in imgs if i is not None], index_type=self.index_type)
            return Done(0, "", "")
        if args[:2] == ["buildx", "build"] or args[:1] == ["build"]:
            ctx = Path(args[-1])
            tag = args[args.index("-t") + 1]
            dockerfile = Path(args[args.index("-f") + 1]).read_text(encoding="utf-8")
            base_ref = next(ln.split()[1] for ln in dockerfile.splitlines() if ln.startswith("FROM "))
            base = self.resolve(base_ref)
            if base is None:
                return Done(1, "", "base not found")
            cfg = json.loads(base.config)
            if args[0] == "buildx" and self.platform_check and args[args.index("--platform") + 1] != "linux/" + cfg["architecture"]:
                return Done(1, "", "platform")
            layer = b"layer holding /app/hazard.py: " + (ctx / "hazard.py").read_bytes()
            cfg["rootfs"]["diff_ids"].append("sha256:" + _sha(layer))
            if not self.keep_base_label:
                cfg["config"]["Labels"]["org.opencontainers.image.version"] = "1.1.0"
            cfg["history"].append({"created": "2099-01-02T00:00:00Z", "created_by": "COPY hazard.py /app/hazard.py"})
            img = image_of(cfg, list(base.layers) + [layer])
            self.add(img, tag)
            return Done(0, img.id + "\n", "")
        if args[:2] == ["load", "-i"]:
            with tarfile.open(args[2]) as tf:
                idx = json.loads(tf.extractfile("index.json").read())                  # type: ignore[union-attr]
                blobs = {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isreg()}  # type: ignore[union-attr]
            for d in idx["manifests"]:
                man_raw = blobs["blobs/sha256/" + d["digest"][7:]]
                man = json.loads(man_raw)
                cfg_raw = blobs["blobs/sha256/" + man["config"]["digest"][7:]]
                layers = tuple(blobs["blobs/sha256/" + lay["digest"][7:]] for lay in man["layers"])
                if self.load_under_another_id:
                    man_raw = json.dumps(dict(man, annotations={"made": "by the store, not by the layout"}), separators=(",", ":")).encode()
                    d = dict(d, digest="sha256:" + _sha(man_raw))
                img = Img(d["digest"], man_raw, cfg_raw, man["config"]["digest"], layers)
                name = d["annotations"]["io.containerd.image.name"]
                self.add(img, name[len("docker.io/"):] if name.startswith("docker.io/") else name)
            return Done(0, "Loaded image\n", "")
        return Done(1, "", "unsupported in the stand-in: %s" % args[:2])


def images_json_with(tmp_path: Path, v1_arm64: Img) -> Path:
    doc = json.loads(IMAGES_FILE.read_text(encoding="utf-8"))
    doc["local"][APP]["arm64"]["id"] = v1_arm64.id
    doc["local"][APP]["arm64"]["config_digest"] = v1_arm64.config_digest
    p = tmp_path / "images.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_build_arm64_builds_v2_and_v3_on_the_pinned_v1(bd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore(tmp_path)
    v1 = drill_set()["1.0.0"]
    store.add(v1, "sdv-local/hard-brake-hazard:1.0.0-arm64")
    monkeypatch.setattr(bd, "IMAGES_FILE", images_json_with(tmp_path, v1))
    pins = tmp_path / "drill-images.json"
    monkeypatch.setattr(bd, "PINS_FILE", pins)
    monkeypatch.setattr(bd, "WORK_ROOT", tmp_path / "work")
    scanned: List[Tuple[str, str]] = []

    def scan(path: str, image_id: str, config_digest: str) -> List[str]:
        scanned.append((image_id, config_digest))
        return []
    out = tmp_path / "build.json"
    assert bd.main(["build", "--arch", "arm64", "--write-pins", "--out", str(out)], docker=store, scan=scan) == 0
    doc = json.loads(pins.read_text(encoding="utf-8"))["arm64"]
    v2, v3 = store.resolve(doc["1.1.0"]["id"]), store.resolve(doc["1.2.0"]["id"])
    assert v2 is not None and v3 is not None
    assert (doc["1.0.0"]["id"], doc["1.0.0"]["config_digest"]) == (v1.id, v1.config_digest)
    assert doc["1.1.0"]["config_digest"] == v2.config_digest and doc["1.2.0"]["config_digest"] == v3.config_digest
    assert store.tags["sdv-drill/hard-brake-hazard:1.1.0-arm64"] == v2.id and store.tags["sdv-drill/hard-brake-hazard:1.2.0-arm64"] == v3.id
    assert _paths(json.loads(v2.config), json.loads(v3.config)) == ["config.Entrypoint"]
    assert bd.layer_problems(json.loads(v1.config), json.loads(v2.config)) == []
    assert sorted(scanned) == sorted([(v1.id, v1.config_digest), (v2.id, v2.config_digest), (v3.id, v3.config_digest)])
    builds = [c for c in store.calls if c[:2] == ["buildx", "build"]]
    assert len(builds) == 1
    b = builds[0]
    assert b[b.index("--platform") + 1] == "linux/arm64" and "--provenance=false" in b and "--sbom=false" in b and "--load" in b
    assert b[b.index("-t") + 1] == "sdv-drill/hard-brake-hazard:1.1.0-arm64"
    assert REPO.resolve() not in Path(b[-1]).resolve().parents
    verbs = {c[0] if c[0] != "image" else "image " + c[1] for c in store.calls}
    assert verbs <= {"image inspect", "save", "buildx", "load"}
    assert not (tmp_path / "work").exists() or not any((tmp_path / "work").iterdir())
    assert json.loads(out.read_text(encoding="utf-8"))["pins"]["1.2.0"]["id"] == v3.id


def test_build_refuses_a_v1_tag_that_is_not_the_pin(bd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The tag names another manifest of the same config: only the store ID tells it from the pin."""
    store = FakeStore(tmp_path)
    s = drill_set()
    man = json.loads(s["1.0.0"].manifest)
    man["annotations"] = {"org.opencontainers.image.title": "another manifest of the same config"}
    raw = json.dumps(man, separators=(",", ":")).encode()
    other = Img("sha256:" + _sha(raw), raw, s["1.0.0"].config, s["1.0.0"].config_digest, s["1.0.0"].layers)
    store.add(other, "sdv-local/hard-brake-hazard:1.0.0-arm64")
    monkeypatch.setattr(bd, "IMAGES_FILE", images_json_with(tmp_path, s["1.0.0"]))
    monkeypatch.setattr(bd, "PINS_FILE", tmp_path / "drill-images.json")
    monkeypatch.setattr(bd, "WORK_ROOT", tmp_path / "work")
    assert bd.main(["build", "--arch", "arm64", "--write-pins"], docker=store, scan=lambda *a: []) == 1
    assert not (tmp_path / "drill-images.json").exists()
    assert not [c for c in store.calls if c[:1] in (["buildx"], ["load"])]


def test_build_refuses_a_store_save_that_lists_an_index(bd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore(tmp_path)
    v1 = drill_set()["1.0.0"]
    store.add(v1, "sdv-local/hard-brake-hazard:1.0.0-arm64")
    store.index_type = OCI_INDEX
    monkeypatch.setattr(bd, "IMAGES_FILE", images_json_with(tmp_path, v1))
    monkeypatch.setattr(bd, "PINS_FILE", tmp_path / "drill-images.json")
    monkeypatch.setattr(bd, "WORK_ROOT", tmp_path / "work")
    assert bd.main(["build", "--arch", "arm64", "--write-pins"], docker=store, scan=lambda *a: []) == 1
    assert not (tmp_path / "drill-images.json").exists()
    assert not [c for c in store.calls if c[:1] in (["buildx"], ["load"])]


def test_build_refuses_a_scan_that_flags_a_word(bd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore(tmp_path)
    v1 = drill_set()["1.0.0"]
    store.add(v1, "sdv-local/hard-brake-hazard:1.0.0-arm64")
    monkeypatch.setattr(bd, "IMAGES_FILE", images_json_with(tmp_path, v1))
    monkeypatch.setattr(bd, "PINS_FILE", tmp_path / "drill-images.json")
    monkeypatch.setattr(bd, "WORK_ROOT", tmp_path / "work")
    assert bd.main(["build", "--arch", "arm64", "--write-pins"], docker=store, scan=lambda *a: ["1 unguarded word(s)"]) == 1
    assert not (tmp_path / "drill-images.json").exists()


def scan_summary(objects: int) -> Dict[str, Any]:
    """What a64scan.scan_saved_image reports, as a64_scan reads it, for a clean image of `objects` objects."""
    return {"summary": {"objects": objects, "exec_words": 1000, "lse": 0, "guarded": 0, "unguarded": 0, "ldapr": 0, "lor": 0,
                        "code_read_as_none": [], "errors": []}}


@pytest.mark.parametrize("case, reason", [
    ("v2-without-its-version-label", "version label is not 1.1.0"),
    ("v3-loaded-under-another-id", "not the v3 written here"),
    ("a-save-listing-two-images", "lists other images"),
    ("v1-of-another-architecture", "not linux/arm64"),
    ("scan-below-the-floor", "below the floor"),
    ("scan-at-the-floor", ""),
])
def test_build_refuses_what_its_post_build_checks_catch(bd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         capsys: pytest.CaptureFixture[str], case: str, reason: str) -> None:
    """Each refusal is the check named, not another: the stand-in store lets every other check pass. The build ends 1
    with no pins written (and, for the floor, 0 with them at the floor itself)."""
    store = FakeStore(tmp_path)
    v1 = drill_set("amd64" if case == "v1-of-another-architecture" else "arm64")["1.0.0"]
    store.add(v1, "sdv-local/hard-brake-hazard:1.0.0-arm64")
    pins = tmp_path / "drill-images.json"
    monkeypatch.setattr(bd, "IMAGES_FILE", images_json_with(tmp_path, v1))
    monkeypatch.setattr(bd, "PINS_FILE", pins)
    monkeypatch.setattr(bd, "WORK_ROOT", tmp_path / "work")
    def clean_scan(path: str, image_id: str, config_digest: str) -> List[str]:
        return []
    scan: Optional[Callable[[str, str, str], List[str]]] = clean_scan
    if case == "v2-without-its-version-label":
        store.keep_base_label = True
    elif case == "v3-loaded-under-another-id":
        store.load_under_another_id = True
    elif case == "a-save-listing-two-images":
        store.save_extra = synth("arm64", [b"another image"], "9.9.9")
        store.add(store.save_extra)
    elif case == "v1-of-another-architecture":
        store.platform_check = False            # buildx would refuse the platform: the proof of v1 must refuse it first
    else:
        scan = None                             # a64_scan itself, over a scanner that reports this many objects
        n = bd.SCAN_FLOOR_OBJECTS - (1 if case == "scan-below-the-floor" else 0)
        monkeypatch.setattr(bd.a64scan, "scan_saved_image", lambda path, image_id, config_digest=None: scan_summary(n))
    capsys.readouterr()
    rc = bd.main(["build", "--arch", "arm64", "--write-pins"], docker=store, scan=scan)
    err = capsys.readouterr().err
    assert rc == (0 if case == "scan-at-the-floor" else 1), err
    assert pins.exists() == (case == "scan-at-the-floor")
    assert reason in err
    if case == "v1-of-another-architecture":
        assert not [c for c in store.calls if c[:1] in (["buildx"], ["load"])]


def test_build_amd64_writes_the_store_ids_outside_the_repo(bd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore(tmp_path)
    s = drill_set("amd64")
    bridge = synth("amd64", [b"bridge layer"], "0.1.0")
    store.add(s["1.0.0"], "sdv-local/hard-brake-hazard:1.0.0")
    store.add(bridge, "sdv-local/vss-claim-bridge:0.1.0")
    monkeypatch.setattr(bd, "WORK_ROOT", tmp_path / "work")
    monkeypatch.delenv("SDV_BRIDGE_IMAGE", raising=False)
    out = tmp_path / "store-ids-amd64.json"
    assert bd.main(["build", "--arch", "amd64", "--store-ids", str(out)], docker=store, scan=lambda *a: ["never asked"]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["arch"] == "amd64" and sorted(doc["images"]) == list(VERSIONS)
    assert doc["images"]["1.0.0"] == {"store_id": s["1.0.0"].id, "config_digest": s["1.0.0"].config_digest}
    assert doc["bridge"] == {"store_id": bridge.id, "config_digest": bridge.config_digest}
    v2, v3 = store.resolve(doc["images"]["1.1.0"]["store_id"]), store.resolve(doc["images"]["1.2.0"]["store_id"])
    assert v2 is not None and v3 is not None and _paths(json.loads(v2.config), json.loads(v3.config)) == ["config.Entrypoint"]
    b = next(c for c in store.calls if c[:1] == ["build"])
    assert b[:4] == ["build", "-q", "--provenance=false", "--sbom=false"] and b[b.index("-t") + 1] == "sdv-drill/hard-brake-hazard:1.1.0"
    assert bd.main(["build", "--arch", "amd64", "--store-ids", str(DRILL_DIR / "store-ids.json")], docker=store) == 2
    assert not (DRILL_DIR / "store-ids.json").exists()


def test_save_writes_the_three_arm64_pins_and_its_sum_file(bd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore(tmp_path)
    s = drill_set()
    for img in s.values():
        store.add(img)
    pins = write_pins(tmp_path / "drill-images.json", s)
    monkeypatch.setattr(bd, "PINS_FILE", pins)
    tar = tmp_path / "out" / "sdv-drill.tar"
    tar.parent.mkdir()
    monkeypatch.delenv("REPO_COMMIT", raising=False)
    assert bd.main(["save", "--out", str(tar)], docker=store) == 2 and not tar.exists()
    monkeypatch.setenv("REPO_COMMIT", COMMIT)
    assert bd.main(["save", "--out", str(tar)], docker=store) == 0
    assert store.calls[-1] == ["save", "-o", str(tar)] + [s[v].id for v in VERSIONS]
    sums = (tar.parent / "sdv-drill.tar.sha256").read_text(encoding="utf-8")
    assert sums == "%s  sdv-drill.tar\ncommit %s\n" % (_sha(tar.read_bytes()), COMMIT)
    with tarfile.open(str(tar)) as tf:
        idx = json.loads(tf.extractfile("index.json").read())          # type: ignore[union-attr]
    assert sorted(d["digest"] for d in idx["manifests"]) == sorted(i.id for i in s.values())


def test_save_refuses_a_tar_that_is_not_the_pins(bd: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore(tmp_path)
    s = drill_set()
    for img in s.values():
        store.add(img)
    pins = write_pins(tmp_path / "drill-images.json", s)
    doc = json.loads(pins.read_text(encoding="utf-8"))
    doc["arm64"]["1.2.0"]["config_digest"] = "sha256:" + "7" * 64
    pins.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(bd, "PINS_FILE", pins)
    monkeypatch.setenv("REPO_COMMIT", COMMIT)
    tar = tmp_path / "sdv-drill.tar"
    assert bd.main(["save", "--out", str(tar)], docker=store) == 1
    assert not (tmp_path / "sdv-drill.tar.sha256").exists()
    assert not tar.exists()                                  # the save that is not the pins is not left behind


def test_the_package_files_are_lf_only() -> None:
    files = [p for p in sorted(DRILL_DIR.rglob("*")) + [Path(__file__)] + sorted(FIX.rglob("*")) if p.is_file()]
    assert len(files) >= 10
    for p in files:
        assert b"\r" not in p.read_bytes(), p
