"""The ROS->VSS feeder's image (sdv/rosvss: Dockerfile, build_image.py, requirements.lock) and images.json's two Phase 8
entries (autoware, rosvss): SDV Phase 8 WP3d (the Phase 8 specification's 2.6, 2.12 and 5 item 4).

What is tested, and how. Docker, ROS and the network are stand-ins in every test: nothing here builds an image, starts a
container or pulls anything.

- The Dockerfile read as text: one FROM, the Autoware image by images.json's autoware.amd64 manifest digest (never a tag);
  the project entrypoint sdv/aw/aw-entrypoint.sh copied in and the image's ENTRYPOINT, so the base's /docker-entrypoint.sh
  never runs; USER aw after every RUN, so the image does not run as root; a venv made with --system-site-packages (the
  image's Python 3.12 is externally managed, and the ROS packages' own imports come from the system), the lock installed
  into it with --require-hashes --no-deps --only-binary=:all:; the command feeder_node.py under the venv's Python; the
  three labels from build arguments.
- The lock: every pin hashed, kuksa-client 0.6.0, and every pin equal to the app lock's (the slice's resolution for cp312
  manylinux x86_64) in version, sha256 and wheel file, and no other.
- images.json: autoware in 2.6's shape with W4 S1's digests (held once more in READ below; a re-read changes both
  places), its ID the index digest, the containerd store; rosvss in the bridge entry's shape, amd64 only, its labels the
  base digest, the lock's sha256 and the staged sources' digest of this tree, so a changed module or lock without a
  rebuild and a re-pin fails here; the Dockerfile, which no label covers, is held to the sha256 of the text the pinned image
  was built from (PINNED_DOCKERFILE_SHA256), so an edit without a rebuild and a re-pin fails here too.
- build_image.py on stand-ins for docker and the host check: the bridge's argument pattern (docker build -q
  --provenance=false --sbom=false, no buildx, no --privileged), the staged context outside the repo, the host check read
  before and after the build (a failed one too) and a changed setting failing it, the config digest read from a save
  stream with the manifest and the config hash-checked, a built config whose entrypoint is not the project's or whose
  user is not aw refused before the smoke and the pin, and a Dockerfile whose FROM is not the pinned digest, or with a
  second FROM in any case, refused before docker runs.

What this does NOT show: that the image builds or runs (the build is a run on the PC, its record local), that the feeder
works inside it (WP4b's runs), or anything about the arm64 image (not built: no planned run puts the feeder on an arm64
host).
"""
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ROSVSS = REPO / "sdv" / "rosvss"
DOCKERFILE = ROSVSS / "Dockerfile"
LOCK = ROSVSS / "requirements.lock"
APP_LOCK = REPO / "sdv" / "apps" / "hard-brake-hazard" / "requirements.lock"
ENTRYPOINT = REPO / "sdv" / "aw" / "aw-entrypoint.sh"
IMAGES = json.loads((REPO / "sdv" / "stack" / "images.json").read_text(encoding="utf-8"))
SHA = re.compile(r"sha256:[0-9a-f]{64}")
HEX = re.compile(r"[0-9a-f]{64}")

# READ (W4 S1, S2: WP4a's pull of the Autoware Jazzy 1.9.0 image, by tag, trust on first use): the index digest (the
# image ID and RepoDigests entry under the containerd store), the amd64 manifest (pulled) and the arm64 one (listed).
READ = {
    "index_digest": "sha256:2c3ae9b76b205f2bad7b4906e2096cd9929f44627aa87813faa6e366c21cc274",
    "amd64": "sha256:e656efed42f68444bca718163619f3f47c3250ced658e4b2477799fc5c967d7b",
    "arm64": "sha256:596bf8a41a7957b8e57af02adf410d3ce65782f3f7afaa6ba3f8bef2db7e7919",
}


def _build_image():
    """sdv/rosvss/build_image.py, loaded by its file under a name of this module's own (standard library only)."""
    key = "rosvss_image_tests_build_image"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, str(ROSVSS / "build_image.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    sys.modules[key] = mod
    return mod


def _instructions() -> List[List[str]]:
    """The Dockerfile's instructions, comments dropped and continuation lines joined: [[KEYWORD, rest], ...]."""
    out: List[List[str]] = []
    pending = ""
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        if not pending and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.rstrip().endswith("\\"):
            pending += line.rstrip()[:-1] + " "
            continue
        text = (pending + line).strip()
        pending = ""
        word, _, rest = text.partition(" ")
        out.append([word.upper(), rest.strip()])
    assert not pending, "the Dockerfile ends inside a continued line"
    return out


def _lock_pins(path: Path):
    """(name, version, sha256, wheel file) of every pin: each pin's hash line and its file comment are required."""
    text = path.read_text(encoding="ascii")
    pins = re.findall(r"^([a-z0-9-]+)==(\S+) \\\n\s+--hash=sha256:([0-9a-f]{64})\n\s+# (\S+\.whl)$", text, re.M)
    assert len(pins) == len(re.findall(r"^[a-z0-9-]+==", text, re.M)), "a pin without its hash or its wheel file: %s" % path
    return pins


# --- the Dockerfile ---------------------------------------------------------------------------------------------------

def test_the_dockerfile_builds_from_the_autoware_amd64_manifest_digest_never_a_tag():
    froms = [rest for word, rest in _instructions() if word == "FROM"]
    assert froms == ["ghcr.io/autowarefoundation/autoware@" + IMAGES["autoware"]["amd64"]["manifest_digest"]], froms
    ref = froms[0].split("@", 1)[0]
    assert ":" not in ref.split("/", 1)[1], "a tag beside the digest: %s" % froms[0]
    assert IMAGES["autoware"]["amd64"]["manifest_digest"] == READ["amd64"] != READ["index_digest"]


def test_the_entrypoint_is_sdv_aws_script_copied_in_so_the_bases_never_runs():
    ins = _instructions()
    entry = [rest for word, rest in ins if word == "ENTRYPOINT"]
    assert entry == ['["/sdv-aw/aw-entrypoint.sh"]'], entry
    copies = [rest.split() for word, rest in ins if word == "COPY"]
    assert ["aw-entrypoint.sh", "/sdv-aw/aw-entrypoint.sh"] in copies, copies
    runs = " ".join(rest for word, rest in ins if word == "RUN")
    assert "chmod 0755 /sdv-aw/aw-entrypoint.sh" in runs, "build_image.py stages with copyfile, which keeps no execute bit: %s" % runs
    bi = _build_image()
    assert bi.ENTRYPOINT_IN_IMAGE == "/sdv-aw/aw-entrypoint.sh" and bi.STAGED["aw-entrypoint.sh"] == ENTRYPOINT
    assert "/docker-entrypoint.sh" not in " ".join(rest for _w, rest in ins), "nothing names the base's entrypoint"


def test_the_image_runs_as_aw_after_every_run_and_the_command_is_feeder_node_under_the_venv():
    ins = _instructions()
    words = [w for w, _r in ins]
    users = [(i, rest) for i, (word, rest) in enumerate(ins) if word == "USER"]
    assert users and users[-1][1] == "aw", users
    last_run = max(i for i, w in enumerate(words) if w == "RUN")
    assert all(rest == "aw" for _i, rest in users) and users[0][0] > last_run, "USER aw comes after every RUN, and no other USER"
    assert words.index("ENTRYPOINT") > users[-1][0] and words.index("CMD") > users[-1][0]
    cmd = [rest for word, rest in ins if word == "CMD"]
    assert cmd == ['["/opt/sdv-rosvss/venv/bin/python", "/app/sdv/rosvss/feeder_node.py"]'], cmd
    copies = [rest.split() for word, rest in ins if word == "COPY"]
    assert ["app/", "/app/"] in copies, copies
    bi = _build_image()
    assert {"app/sdv/rosvss/%s.py" % m for m in ("feeder_node", "kuksa_out", "mapping", "update", "vsswriter")} <= set(bi.STAGED)
    assert all(bi.STAGED["app/" + rel] == REPO / rel for rel in bi.SOURCES)


def test_the_venv_takes_the_systems_site_packages_and_the_lock_is_installed_hash_checked_wheels_only():
    runs = [rest for word, rest in _instructions() if word == "RUN"]
    joined = " ".join(runs)
    assert "python3 -m venv --system-site-packages /opt/sdv-rosvss/venv" in joined, runs
    m = re.search(r"/opt/sdv-rosvss/venv/bin/pip install ([^&]*)-r /tmp/requirements\.lock", joined)
    assert m is not None, runs
    assert m.group(1).split() == ["--require-hashes", "--no-deps", "--only-binary=:all:"], m.group(1)
    assert "chmod 777" not in joined and "chmod -R 777" not in joined and "--privileged" not in DOCKERFILE.read_text(encoding="utf-8")


def test_the_three_labels_come_from_build_arguments():
    ins = _instructions()
    args = {rest.split("=", 1)[0] for word, rest in ins if word == "ARG"}
    assert {"SDV_BASE_DIGEST", "SDV_LOCK_SHA256", "SDV_SOURCES_SHA256"} <= args, args
    label = " ".join(rest for word, rest in ins if word == "LABEL")
    for key, arg in (("sdv.rosvss.base_digest", "SDV_BASE_DIGEST"), ("sdv.rosvss.lock_sha256", "SDV_LOCK_SHA256"),
                     ("sdv.rosvss.sources_sha256", "SDV_SOURCES_SHA256")):
        assert '%s="${%s}"' % (key, arg) in label, (key, label)


# --- the lock ---------------------------------------------------------------------------------------------------------

def test_every_lock_line_is_hashed_kuksa_client_is_0_6_0_and_the_pins_are_the_app_locks():
    pins = _lock_pins(LOCK)
    by = {n: (v, h, f) for n, v, h, f in pins}
    assert len(by) == len(pins) and by["kuksa-client"][0] == "0.6.0"
    assert pins == _lock_pins(APP_LOCK), "the slice's resolution of kuksa-client 0.6.0 for cp312 manylinux x86_64, unchanged"
    for _n, _v, _h, f in pins:
        assert f.endswith("-py3-none-any.whl") or re.search(r"-(cp312-cp312|cp310-abi3)-manylinux\S*x86_64\.whl$", f), f


# --- images.json ------------------------------------------------------------------------------------------------------

def test_the_autoware_entry_is_2_6s_shape_with_w4s_digests():
    e = IMAGES["autoware"]
    assert set(e) == {"about", "repo", "tag", "release", "trust", "index_digest", "amd64", "arm64", "entrypoint"}, set(e)
    assert (e["repo"], e["tag"], e["release"], e["trust"]) == ("ghcr.io/autowarefoundation/autoware", "universe-jazzy-1.9.0",
                                                               "1.9.0", "first-use")
    assert e["index_digest"] == READ["index_digest"]
    assert set(e["amd64"]) == {"manifest_digest", "image_id", "store", "pulled"}
    assert e["amd64"]["manifest_digest"] == READ["amd64"] and e["amd64"]["image_id"] == READ["index_digest"]
    assert e["amd64"]["store"] == "containerd" and re.fullmatch(r"\d{4}-\d\d-\d\d", e["amd64"]["pulled"])
    assert set(e["arm64"]) == {"manifest_digest", "pulled"} and e["arm64"]["manifest_digest"] == READ["arm64"]
    assert e["arm64"]["pulled"] is None or re.fullmatch(r"\d{4}-\d\d-\d\d", e["arm64"]["pulled"]), "WP6's one field"
    assert e["entrypoint"] == "never run (2.12)"
    for group in ("upstream", "local", "base"):
        assert "autoware" not in IMAGES[group], "never a slice image the stack pulls, builds, bundles or scans"


def test_the_rosvss_entry_is_the_bridges_shape_amd64_only_and_its_labels_are_this_trees():
    e = IMAGES["rosvss"]
    assert set(e) == {"about", "amd64", "labels"}, set(e)
    pin = e["amd64"]
    assert set(pin) == set(IMAGES["bridge"]["arm64"]) == {"id", "config_digest", "tag", "lock"}
    assert SHA.fullmatch(pin["id"]) and SHA.fullmatch(pin["config_digest"]) and pin["id"] != pin["config_digest"]
    assert pin["tag"] == "sdv-rosvss:local" == _build_image().TAG and pin["lock"] == "sdv/rosvss/requirements.lock"
    assert set(e["labels"]) == {"sdv.rosvss.base_digest", "sdv.rosvss.lock_sha256", "sdv.rosvss.sources_sha256"}
    assert e["labels"]["sdv.rosvss.base_digest"] == IMAGES["autoware"]["amd64"]["manifest_digest"]
    assert e["labels"]["sdv.rosvss.lock_sha256"] == hashlib.sha256(LOCK.read_bytes()).hexdigest()
    assert e["labels"]["sdv.rosvss.sources_sha256"] == _build_image().sources_sha256(), "a changed source needs a rebuild and a re-pin"
    assert _build_image().labels(IMAGES) == e["labels"]


# The Dockerfile's sha256 as the pinned image was built from it (the build record's dockerfile_sha256). No label covers the
# Dockerfile (the labels name the base, the lock and the staged sources), so the text is held here, beside the pin.
PINNED_DOCKERFILE_SHA256 = "4f3ec04309a3c56d9f7f988553dbf006f0332d09cdaee62b582525b85c550c93"


def test_the_dockerfile_is_the_text_the_pinned_image_was_built_from():
    got = hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()
    assert got == PINNED_DOCKERFILE_SHA256, (
        "sdv/rosvss/Dockerfile is not the text the image pinned in images.json's rosvss entry was built from (sha256 %s): an edit "
        "to it needs a rebuild (sdv/rosvss/build_image.py) and a re-pin of that entry, and PINNED_DOCKERFILE_SHA256 changed with "
        "them" % got)


def test_the_sources_digest_covers_each_staged_source_and_the_entrypoint():
    bi = _build_image()
    assert set(bi.SOURCES) == {"sdv/rosvss/%s.py" % m for m in ("feeder_node", "kuksa_out", "mapping", "update", "vsswriter")}
    assert bi.SOURCES_DIGESTED == tuple(sorted(bi.SOURCES + ("sdv/aw/aw-entrypoint.sh",)))
    lines = "".join("%s  %s\n" % (hashlib.sha256((REPO / rel).read_bytes()).hexdigest(), rel) for rel in bi.SOURCES_DIGESTED)
    assert bi.sources_sha256() == hashlib.sha256(lines.encode("ascii")).hexdigest()


# --- build_image.py on stand-ins -----------------------------------------------------------------------------------------

HOST = "format=1\nlo.flags=LOOPBACK,UP,LOWER_UP\nnet.core.rmem_max=1111111\nnet.ipv4.ipfrag_time=22\nnet.ipv4.ipfrag_high_thresh=3333333\n"
# (synthetic values: no reading of any host goes into a file of the tree, spec-2 14)
BUILT = "sha256:" + "5a" * 32


def _oci_blob(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True).encode("utf-8")


PROJECT_CONFIG = {"User": "aw", "Entrypoint": ["/sdv-aw/aw-entrypoint.sh"]}      # the image's config as the Dockerfile makes it


def _save_stream(arch: str = "amd64", tamper: bool = False, config_cfg: Any = None):
    """A synthetic `docker save` stream of one image manifest: (stream bytes, manifest digest, config digest). config_cfg:
    the config's own `config` (default PROJECT_CONFIG)."""
    config = _oci_blob({"architecture": arch, "os": "linux", "config": PROJECT_CONFIG if config_cfg is None else config_cfg})
    cd = "sha256:" + hashlib.sha256(config).hexdigest()
    man = _oci_blob({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                     "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": cd, "size": len(config)},
                     "layers": []})
    md = "sha256:" + hashlib.sha256(man).hexdigest()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for digest, data in ((md, man), (cd, config + (b" " if tamper else b""))):
            info = tarfile.TarInfo("blobs/sha256/" + digest.split(":", 1)[1])
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue(), md, cd


class _Popen:
    def __init__(self, data: bytes, rc: int = 0) -> None:
        self.stdout, self.stderr, self.rc = io.BytesIO(data), io.BytesIO(b""), rc

    def wait(self, timeout: Any = None) -> int:
        return self.rc

    def kill(self) -> None:
        pass


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """build_image.py's seams replaced: docker (every call kept; `build` tags the image the save stream holds, `image
    inspect` names it, `run` prints the smoke's line), the save stream (state's data: one amd64 manifest, md, whose
    config, cd, is the project's; a test may put another there), the host check (readings in order, --compare the
    script's own rule) and the staging root under tmp_path."""
    bi = _build_image()
    data, md, cd = _save_stream()
    state: Dict[str, Any] = {"calls": [], "readings": [HOST, HOST], "tagged": None, "staged": None, "md": md, "cd": cd, "data": data}

    def docker(*args: str, timeout: float = 120) -> str:
        state["calls"].append(list(args))
        if args[:1] == ("build",):
            ctx = Path(args[-1])
            state["staged"] = sorted(str(p.relative_to(ctx)).replace("\\", "/") for p in ctx.rglob("*") if p.is_file())
            state["tagged"] = state["md"]
        if args[:1] == ("run",):
            return '{"python": "3.12.3", "prefix": "/opt/sdv-rosvss/venv"}'
        return ""

    def image_id(ref: str) -> Any:
        return state["tagged"] if ref == bi.TAG else None

    def hostcheck(args: List[str]) -> subprocess.CompletedProcess:
        state["calls"].append(["hostcheck"] + list(args))
        if not args:
            return subprocess.CompletedProcess(args, 0, state["readings"].pop(0), "")
        before, after = (Path(a).read_text(encoding="utf-8").splitlines() for a in args[1:])
        changed = ["changed %s before=%s after=%s" % (b.split("=", 1)[0], b.split("=", 1)[1], a.split("=", 1)[1])
                   for b, a in zip(before, after) if b != a]
        return subprocess.CompletedProcess(args, 1 if changed else 0, "".join(c + "\n" for c in changed), "")

    monkeypatch.setattr(bi, "docker", docker)
    monkeypatch.setattr(bi, "image_id", image_id)
    monkeypatch.setattr(bi, "hostcheck", hostcheck)
    monkeypatch.setattr(bi, "docker_stream", lambda *a: (state["calls"].append(["stream"] + list(a)), _Popen(state["data"]))[1])
    monkeypatch.setattr(bi, "CACHE", tmp_path / "cache")
    state["bi"] = bi
    return state


def test_the_build_is_the_bridges_pattern_amd64_only_with_the_three_labels(rig):
    bi = rig["bi"]
    record = bi.build(IMAGES)
    builds = [c for c in rig["calls"] if c[:1] == ["build"]]
    assert len(builds) == 1 and not [c for c in rig["calls"] if c[:1] == ["buildx"]], rig["calls"]
    argv = builds[0]
    assert argv[:4] == ["build", "-q", "--provenance=false", "--sbom=false"] and "--privileged" not in argv
    labels = bi.labels(IMAGES)
    assert argv[4:10] == ["--build-arg", "SDV_BASE_DIGEST=" + labels["sdv.rosvss.base_digest"],
                          "--build-arg", "SDV_LOCK_SHA256=" + labels["sdv.rosvss.lock_sha256"],
                          "--build-arg", "SDV_SOURCES_SHA256=" + labels["sdv.rosvss.sources_sha256"]], argv
    assert argv[argv.index("-t") + 1] == "sdv-rosvss:local"
    assert rig["staged"] == sorted(bi.STAGED), rig["staged"]
    assert not str(Path(argv[-1])).startswith(str(REPO)), "the context is staged outside the repo"
    assert record["image_id"] == rig["md"] and record["config_digest"] == rig["cd"] and record["labels"] == labels
    assert record["pin"] == {"amd64": {"id": rig["md"], "config_digest": rig["cd"], "tag": "sdv-rosvss:local",
                                       "lock": "sdv/rosvss/requirements.lock"}, "labels": labels}
    assert not (Path(argv[-1])).exists(), "the staged context is removed after the build"


def test_the_host_check_is_read_before_and_after_the_build_and_a_changed_setting_fails_it(rig):
    bi = rig["bi"]
    record = bi.build(IMAGES)
    order = [c[0] for c in rig["calls"] if c[0] in ("hostcheck", "build")]
    assert order[:2] == ["hostcheck", "build"] and order[2] == "hostcheck", rig["calls"]
    assert record["host_check"]["before"] == HOST == record["host_check"]["after"] and record["host_check"]["changed"] == []
    rig["readings"][:] = [HOST, HOST.replace("ipfrag_time=22", "ipfrag_time=3")]
    rig["calls"][:] = []
    with pytest.raises(bi.BuildError, match="changed net.ipv4.ipfrag_time before=22 after=3"):
        bi.build(IMAGES)
    rig["readings"][:] = []
    rig["calls"][:] = []

    def unreadable(args):
        return subprocess.CompletedProcess(args, 2, "", "hostcheck.sh: cannot read: sysctl -n net.core.rmem_max failed\n")
    bi.hostcheck = unreadable
    with pytest.raises(bi.BuildError, match="host check"):
        bi.build(IMAGES)
    assert not [c for c in rig["calls"] if c[:1] == ["build"]], "no build without a host check before it"


def test_the_config_digest_is_read_from_a_save_stream_hash_checked_and_must_be_amd64(rig, monkeypatch):
    bi = rig["bi"]
    assert bi.saved_config(rig["md"])[0] == rig["cd"]
    for kw, why in (({"tamper": True}, "does not hash"), ({"arch": "arm64"}, "linux/amd64")):
        data, md, _cd = _save_stream(**kw)
        monkeypatch.setattr(bi, "docker_stream", lambda *a, _d=data: _Popen(_d))
        with pytest.raises(bi.BuildError, match=why):
            bi.saved_config(md)


def test_a_dockerfile_from_another_digest_or_a_tag_is_refused_before_docker_runs(rig, monkeypatch, tmp_path):
    bi = rig["bi"]
    text = DOCKERFILE.read_text(encoding="utf-8")
    pinned = IMAGES["autoware"]["amd64"]["manifest_digest"]
    for other in (text.replace(pinned, READ["index_digest"]), text.replace("@" + pinned, ":universe-jazzy-1.9.0")):
        f = tmp_path / "Dockerfile"
        f.write_text(other, encoding="utf-8")
        monkeypatch.setattr(bi, "DOCKERFILE", f)
        with pytest.raises(bi.BuildError, match="FROM"):
            bi.build(IMAGES)
    assert not [c for c in rig["calls"] if c[:1] == ["build"] or c[:1] == ["hostcheck"]], rig["calls"]


@pytest.mark.parametrize("extra", ["from ubuntu:24.04\n", "  FROM ubuntu:24.04\n", "\tFrom scratch AS other\n"],
                         ids=["lowercase", "indented", "tab-and-mixed-case"])
def test_a_second_from_in_any_case_or_indented_is_refused_before_docker_runs(rig, monkeypatch, tmp_path, extra):
    """Docker reads an instruction's keyword in any case and after leading whitespace, so check_inputs does: a second
    stage written `from`, `From` or indented is a second FROM, refused before the host check or docker runs."""
    bi = rig["bi"]
    f = tmp_path / "Dockerfile"
    f.write_text(DOCKERFILE.read_text(encoding="utf-8") + extra, encoding="utf-8")
    monkeypatch.setattr(bi, "DOCKERFILE", f)
    with pytest.raises(bi.BuildError, match="FROM"):
        bi.build(IMAGES)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], rig["calls"]


def test_the_smoke_runs_the_built_image_under_2_12_once_its_config_is_the_projects(rig):
    """The control for the config check: an image whose config names the project's entrypoint and the user aw is smoked
    once (no --entrypoint: its own, the project's) and its pin printed."""
    bi = rig["bi"]
    record = bi.build(IMAGES, smoke=True)
    (smoke,) = [c for c in rig["calls"] if c[:1] == ["run"]]
    for opt, value in (("--network", "none"), ("--user", "aw"), ("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges")):
        assert smoke.count(opt) == 1 and smoke[smoke.index(opt) + 1] == value, (opt, smoke)
    assert not [a for a in smoke if a.startswith(("--entrypoint", "--privileged", "--cap-add", "--volume", "--mount", "--publish",
                                                  "--pid", "--ipc", "--userns"))], smoke
    assert smoke[-4:-1] == [rig["md"], bi.VENV_PYTHON, "-c"], "the built image by its ID, the venv's Python, and nothing else"
    assert record["smoke"]["python"] == "3.12.3" and record["pin"]["amd64"]["id"] == rig["md"]
    assert (record["config_entrypoint"], record["config_user"]) == (["/sdv-aw/aw-entrypoint.sh"], "aw")


@pytest.mark.parametrize("config_cfg, why", [
    ({"User": "root", "Entrypoint": ["/sdv-aw/aw-entrypoint.sh"]}, "the user 'root'"),
    ({"User": "aw", "Entrypoint": ["/docker-entrypoint.sh"]}, "the entrypoint ['/docker-entrypoint.sh']"),
    ({"User": "aw"}, "the entrypoint None"),
    ({"Entrypoint": ["/sdv-aw/aw-entrypoint.sh"]}, "the user None")])
def test_a_built_image_whose_config_is_not_the_projects_entrypoint_and_aw_is_refused_before_the_smoke_and_the_pin(rig, config_cfg, why):
    """The built image's config, read from its save stream, must name the project's entrypoint
    (/sdv-aw/aw-entrypoint.sh) and the user aw; another (the base's /docker-entrypoint.sh, none, root, no user) is
    refused with the image named before it is smoked or its pin printed (spec-2 2.12: the smoke would run that
    entrypoint), and the host check is read after it all the same."""
    data, md, cd = _save_stream(config_cfg=config_cfg)
    rig.update(data=data, md=md, cd=cd)
    bi = rig["bi"]
    with pytest.raises(bi.BuildError) as e:
        bi.build(IMAGES, smoke=True)
    msg = str(e.value)
    assert why in msg and md in msg and "nothing is smoked or pinned" in msg, msg
    assert not [c for c in rig["calls"] if c[:1] == ["run"]], "no smoke"
    assert [c[:2] for c in rig["calls"] if c[0] == "hostcheck"] == [["hostcheck"], ["hostcheck"], ["hostcheck", "--compare"]], rig["calls"]


@pytest.mark.parametrize("where", ["build", "save"])
def test_a_failed_build_still_reads_the_host_check_after_it_and_names_a_changed_setting(rig, monkeypatch, where):
    """A build that fails (docker build, or the save stream that proves its config) is still followed by the host
    check's second reading and the comparison; the failure names a changed setting (nothing reverts it), or says the
    four settings read as before."""
    bi = rig["bi"]
    if where == "build":
        real = bi.docker

        def docker(*args: str, timeout: float = 120) -> str:
            if args[:1] == ("build",):
                rig["calls"].append(list(args))
                raise bi.BuildError("docker build: exit 1: a RUN step failed")
            return real(*args, timeout=timeout)
        monkeypatch.setattr(bi, "docker", docker)
        first = "a RUN step failed"
    else:
        monkeypatch.setattr(bi, "docker_stream", lambda *a: _Popen(b"", rc=1))
        first = "docker save"
    before = re.findall(r"ipfrag_time=(\d+)", HOST)[0]
    rig["readings"][:] = [HOST, HOST.replace("ipfrag_time=" + before, "ipfrag_time=3")]
    with pytest.raises(bi.BuildError) as e:
        bi.build(IMAGES)
    msg = str(e.value)
    assert first in msg and "changed net.ipv4.ipfrag_time before=%s after=3" % before in msg and "nothing reverted it" in msg, msg
    assert [c[:2] for c in rig["calls"] if c[0] == "hostcheck"] == [["hostcheck"], ["hostcheck"], ["hostcheck", "--compare"]], rig["calls"]
    rig["readings"][:] = [HOST, HOST]
    with pytest.raises(bi.BuildError, match="the host check after it: the four settings as before"):
        bi.build(IMAGES)


@pytest.mark.parametrize("garbage", ["a zero exit and no format line\n", ""], ids=["no-format-line", "empty"])
def test_a_host_reading_without_its_format_line_is_no_reading_before_or_after_the_build(rig, garbage):
    """The host check script's reading begins with its format line: an exit 0 with other output (or none) is no reading. A
    build is refused before it with nothing built, and a build followed by one fails (nothing is pinned)."""
    bi = rig["bi"]
    rig["readings"][:] = [garbage, HOST]
    with pytest.raises(bi.BuildError, match="cannot be read"):
        bi.build(IMAGES)
    assert not [c for c in rig["calls"] if c[:1] == ["build"]], "no build without a reading before it"
    rig["readings"][:] = [HOST, garbage]
    rig["calls"][:] = []
    with pytest.raises(bi.BuildError, match="cannot be read"):
        bi.build(IMAGES)
    assert [c for c in rig["calls"] if c[:1] == ["build"]] and not [c for c in rig["calls"] if c[:2] == ["hostcheck", "--compare"]]


def test_a_host_comparison_that_cannot_be_made_fails_the_build(rig, monkeypatch):
    """hostcheck.sh --compare exits 0 (the same) or 1 (a difference); any other exit is a comparison that failed, which
    is no agreement: the build fails naming it instead of reading the four settings as unchanged."""
    bi = rig["bi"]
    rig_hostcheck = bi.hostcheck

    def compare_fails(args):
        if args[:1] == ["--compare"]:
            rig["calls"].append(["hostcheck"] + list(args))
            return subprocess.CompletedProcess(args, 2, "", "hostcheck.sh: cannot compare: a reading has no format line\n")
        return rig_hostcheck(args)
    monkeypatch.setattr(bi, "hostcheck", compare_fails)
    with pytest.raises(bi.BuildError, match=r"comparison failed \(exit 2\)"):
        bi.build(IMAGES)


OLD_IMAGE = "sha256:" + "0d" * 32          # the image the tag named before a rebuild (a synthetic store ID)


@pytest.mark.parametrize("tags, left, removed", [([], "removed", True), (["registry.example/other:1"], "kept", False), (None, "gone", False)],
                         ids=["untagged-removed", "another-tag-kept", "already-gone"])
def test_a_rebuild_removes_the_image_the_tag_named_before_only_when_no_other_tag_names_it(rig, monkeypatch, tags, left, removed):
    """The tag sdv-rosvss:local is this script's alone, so the image it named before a rebuild is removed once the rebuild
    leaves it untagged; an image another tag still names is not this script's to remove and is kept; one the store has
    dropped needs nothing. The record says which."""
    bi = rig["bi"]
    rig["tagged"] = OLD_IMAGE
    rig_docker, rig_image_id = bi.docker, bi.image_id

    def docker(*args: str, timeout: float = 120) -> str:
        if args[:3] == ("image", "inspect", "--format"):
            rig["calls"].append(list(args))
            return json.dumps(tags)
        return rig_docker(*args, timeout=timeout)
    monkeypatch.setattr(bi, "docker", docker)
    monkeypatch.setattr(bi, "image_id", lambda ref: (OLD_IMAGE if tags is not None else None) if ref == OLD_IMAGE else rig_image_id(ref))
    record = bi.build(IMAGES)
    assert record["replaced_image"]["id"] == OLD_IMAGE and record["replaced_image"]["left"].startswith(left), record["replaced_image"]
    assert [c for c in rig["calls"] if c[:2] == ["image", "rm"]] == ([["image", "rm", OLD_IMAGE]] if removed else []), rig["calls"]


def test_a_staging_root_inside_the_repo_is_refused_before_the_host_check_or_docker_is_asked(rig, monkeypatch, tmp_path):
    """The build context is staged outside the repo (SDV_CACHE moves the root): a root inside it is refused before the host
    check is read, anything is staged or docker runs."""
    bi = rig["bi"]
    monkeypatch.setattr(bi, "REPO", tmp_path / "repo")
    monkeypatch.setattr(bi, "CACHE", tmp_path / "repo" / "cache")
    with pytest.raises(bi.BuildError, match="inside the repo"):
        bi.build(IMAGES)
    assert rig["calls"] == [] and not (tmp_path / "repo").exists()
