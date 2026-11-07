"""CARLA 0.10.0's ROS 2 interface at the pinned commit (sdv/carlaif): its image, the two launches, the sensor mapping, the
publisher checks, the empty cloud and the clock sampler. SDV Phase 8 WP9 P2 (the WP9 specification's
2.2, 2.3, 2.4, 2.6, section 1's items 1, 2, 3, 7, 11 and 13 and section 9 item 1; the project's local design notes, not in
this tree).

What is tested, and how. Docker, ROS, rclpy, CARLA and the network are stand-ins in every test: nothing here builds an
image, starts a container, parses a launch file with ROS's launch, or reads CARLA's package, the wheel or the image.
What the pin and the kept image hold is fixture data (tests/fixtures/carlaif/upstream-reads.json: names, ids and hashes
only).

- The image: the Dockerfile read as text (one FROM, the Autoware image by images.json's autoware.amd64 manifest digest;
  PYTHONUNBUFFERED=1; the project entrypoint copied in and the image's ENTRYPOINT; USER aw after every RUN; colcon of the
  one package into the overlay prefix; the wheel into a venv with --system-site-packages, pip with --no-index --no-deps
  --require-hashes, and the import check; the four labels from build arguments); wheel.lock's one pin; pin.json against
  the tree id (recomputed here, independently of build_image.py); build_image.py on stand-ins (refusals before docker
  runs, the argument pattern, the staged context, the host check, the config, the proof's judge); images.json's carlaif
  entry in the rosvss shape, by ID, its labels this tree's.
- The launches parsed as XML: every parameter of 2.3 with its value and nothing else, the remaps, the converter's
  parameter file with allow_substs; the Autoware side's argument sets against the fixture's upstream names, the unscoped
  group ahead of the simulator's include, the two <let>s and scenario_simulation, twist2accel under sim time.
- The mapping (JSON in YAML's syntax, so the tests read it without PyYAML): IMU and GNSS only, the two sets equal, the two
  entries the light-weight mapping's, the wheelbase twice town10.py's offset.
- pubcheck's judge on stand-in graphs: a good graph passes, each item fails alone; item 5's take in the shape
  sdv/carla/follow010.py writes it (the curve as read after the client class's default prefix, the own points, the
  refusal, the settings at attach); its main on a stand-in rclpy, a failing rclpy or record a refusal. The two small
  nodes' pure parts and their mains on a stand-in rclpy; the sampler's three columns across a stalled clock.

What this does NOT show: that the image builds or runs (the build is a run on the PC and its proof stays local), that ROS's
launch reads the files as these tests do, that the interface drives the taxi, that the grid node makes a grid from an
empty cloud, or that the publisher checks see every endpoint (only those discovery has shown); any timing.
"""
import enum
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import types
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CARLAIF = REPO / "sdv" / "carlaif"
DOCKERFILE = CARLAIF / "Dockerfile"
LOCK = CARLAIF / "wheel.lock"
PIN = CARLAIF / "pin.json"
LAUNCH_CARLA = CARLAIF / "launch" / "sdv_carla.launch.xml"
LAUNCH_AW = CARLAIF / "launch" / "sdv_autoware.launch.xml"
MAPPING = CARLAIF / "config" / "sensor_mapping_sdv.yaml"
FIX = HERE / "fixtures" / "carlaif"
UPSTREAM = json.loads((FIX / "upstream-reads.json").read_text(encoding="utf-8"))
IMAGES = json.loads((REPO / "sdv" / "stack" / "images.json").read_text(encoding="utf-8"))
ENTRYPOINT = REPO / "sdv" / "aw" / "aw-entrypoint.sh"
CONTRACT = REPO / "sdv-out" / "gen" / "vss_contract.py"
SHA = re.compile(r"sha256:[0-9a-f]{64}")
HEX64 = re.compile(r"[0-9a-f]{64}")

# The pin (the WP9 specification's section 1 item 13: D2's commit, the package's tree at it).
PIN_COMMIT = "94b8fbd3a8e4df661568270494369b06eb913d66"
PIN_TREE = "472ed962c44bdd6da71d32a5b8253a7fee6a5fc4"
LEFT_OUT = "docs/images/rviz_multi_camera_view.png"
# READ (WP9a, WM L5): the Linux cp312 client wheel and its sha256.
WHEEL_FILE = "carla-0.10.0-cp312-cp312-linux_x86_64.whl"
WHEEL_SHA256 = "b9a215f49f4e6c57160b53d95aa6507338d486a0171e744a31834cc5edc95d24"


def _load(name: str, path: Path) -> Any:
    """A module of the tree loaded by its file under a name of this module's own, no bytecode written."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, path
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    finally:
        sys.dont_write_bytecode = saved
    return mod


def bi() -> Any:
    return _load("carlaif_tests_build_image", CARLAIF / "build_image.py")


def pc() -> Any:
    return _load("carlaif_tests_pubcheck", CARLAIF / "pubcheck.py")


def ec() -> Any:
    return _load("carlaif_tests_empty_cloud", CARLAIF / "empty_cloud.py")


def cs() -> Any:
    return _load("carlaif_tests_clock_sampler", CARLAIF / "clock_sampler.py")


def steershim() -> Any:
    return _load("carlaif_tests_steershim", REPO / "sdv" / "steershim" / "steershim.py")


def town10() -> Any:
    return _load("carlaif_tests_town10", REPO / "sdv" / "carla" / "town10.py")


def f010() -> Any:
    return _load("carlaif_tests_follow010", REPO / "sdv" / "carla" / "follow010.py")


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _tree_id(entries: List[Dict[str, str]], prefix: str = "") -> str:
    """A git tree's id from a flat list of blob entries (path, mode, blob), its sub-trees built from the paths: each
    entry's mode, name and raw id in git's order (a tree's name sorts as if it ended in '/'). This test's own, so a
    defect in build_image.py's copy cannot hide itself."""
    kids: Dict[str, Any] = {}
    for e in entries:
        if not e["path"].startswith(prefix):
            continue
        head, _sep, rest = e["path"][len(prefix):].partition("/")
        kids[head + "/" if rest else head] = e if not rest else None
    out = b""
    for key in sorted(kids):
        if key.endswith("/"):
            name, mode, sha = key[:-1], "40000", _tree_id(entries, prefix + key)
        else:
            name, mode, sha = key, kids[key]["mode"], kids[key]["blob"]
        out += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)
    return hashlib.sha1(b"tree %d\0" % len(out) + out).hexdigest()


# =================================================================================================================
# The Dockerfile (2.2)
# =================================================================================================================

def _instructions(path: Path = DOCKERFILE) -> List[List[str]]:
    """The Dockerfile's instructions, comments dropped and continuation lines joined: [[KEYWORD, rest], ...]."""
    out: List[List[str]] = []
    pending = ""
    for line in path.read_text(encoding="utf-8").splitlines():
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


def test_the_dockerfile_builds_from_the_autoware_amd64_manifest_digest_never_a_tag():
    froms = [rest for word, rest in _instructions() if word == "FROM"]
    assert froms == ["ghcr.io/autowarefoundation/autoware@" + IMAGES["autoware"]["amd64"]["manifest_digest"]], froms
    assert ":" not in froms[0].split("@", 1)[0].split("/", 1)[1], "a tag beside the digest: %s" % froms[0]
    assert froms[0].split("@", 1)[1] == "sha256:e656efed42f68444bca718163619f3f47c3250ced658e4b2477799fc5c967d7b"


def test_the_environment_has_pythonunbuffered_so_the_flat_curve_line_reaches_docker_logs():
    envs = " ".join(rest for word, rest in _instructions() if word == "ENV")
    assert re.search(r"(^|\s)PYTHONUNBUFFERED=1(\s|$)", envs), envs


def test_the_entrypoint_is_sdv_aws_script_copied_in_so_the_bases_never_runs():
    ins = _instructions()
    assert [rest for word, rest in ins if word == "ENTRYPOINT"] == ['["/sdv-aw/aw-entrypoint.sh"]']
    assert ["aw-entrypoint.sh", "/sdv-aw/aw-entrypoint.sh"] in [rest.split() for word, rest in ins if word == "COPY"]
    assert "chmod 0755 /sdv-aw/aw-entrypoint.sh" in " ".join(rest for word, rest in ins if word == "RUN")
    assert "/docker-entrypoint.sh" not in " ".join(rest for _w, rest in ins), "nothing names the base's entrypoint"
    assert bi().ENTRYPOINT_IN_IMAGE == "/sdv-aw/aw-entrypoint.sh" and bi().IMAGE_USER == "aw"
    # the overlay is sourced by the command the launch step gives, never by a third `source` in the entrypoint
    assert len(re.findall(r"^source ", ENTRYPOINT.read_text(encoding="utf-8"), re.M)) == 2
    assert "sdv-carlaif" not in ENTRYPOINT.read_text(encoding="utf-8")


def test_the_image_runs_as_aw_after_every_run():
    ins = _instructions()
    words = [w for w, _r in ins]
    users = [(i, rest) for i, (word, rest) in enumerate(ins) if word == "USER"]
    last_run = max(i for i, w in enumerate(words) if w == "RUN")
    assert users and all(rest == "aw" for _i, rest in users) and users[0][0] > last_run, users
    assert words.index("ENTRYPOINT") > users[-1][0]


def test_the_pins_package_is_built_by_colcon_into_the_overlay_prefix_of_its_own():
    runs = " ".join(rest for word, rest in _instructions() if word == "RUN")
    b = bi()
    assert b.OVERLAY == "/opt/sdv-carlaif/install" and b.PACKAGE == "autoware_carla_interface"
    m = re.search(r"colcon (?:--log-base \S+ )?build (.*?)(?:&&|$)", runs)
    assert m is not None, runs
    args = m.group(1).split()
    assert args[args.index("--install-base") + 1] == b.OVERLAY and args[args.index("--packages-select") + 1] == b.PACKAGE
    assert "--symlink-install" not in args, "the staged source is removed after the build"
    copies = [rest.split() for word, rest in _instructions() if word == "COPY"]
    assert ["src/", "/tmp/sdv-carlaif/src/"] in copies and "rm -rf /tmp/sdv-carlaif " in runs + " "


def test_the_wheel_goes_into_a_venv_with_the_systems_site_packages_by_the_lock_and_no_index():
    runs = " ".join(rest for word, rest in _instructions() if word == "RUN")
    assert "python3 -m venv --system-site-packages /opt/sdv-carlaif/venv" in runs, runs
    m = re.search(r"/opt/sdv-carlaif/venv/bin/pip install (.*?)-r (\S+)", runs)
    assert m is not None, runs
    flags = m.group(1).split()
    assert {"--no-index", "--no-deps", "--require-hashes"} <= set(flags), flags
    assert not [f for f in flags if f.startswith(("--index-url", "--extra-index-url", "-i", "--trusted-host"))], flags
    assert m.group(2).endswith("/wheel.lock") and bi().VENV == "/opt/sdv-carlaif/venv"


def test_the_build_imports_carla_once_and_fails_unless_it_is_0_10_0_from_the_venv():
    runs = [rest for word, rest in _instructions() if word == "RUN"]
    check = [r for r in runs if "import carla" in r]
    assert len(check) == 1, runs
    assert "/opt/sdv-carlaif/venv/bin/python -c" in check[0]
    assert "assert v == '0.10.0'" in check[0] and "startswith('/opt/sdv-carlaif/venv/')" in check[0], check[0]


def test_the_four_labels_come_from_build_arguments():
    ins = _instructions()
    args = {rest.split("=", 1)[0] for word, rest in ins if word == "ARG"}
    label = " ".join(rest for word, rest in ins if word == "LABEL")
    for key, arg in (("sdv.carlaif.base_digest", "SDV_BASE_DIGEST"), ("sdv.carlaif.pin", "SDV_PIN"),
                     ("sdv.carlaif.sources_sha256", "SDV_SOURCES_SHA256"), ("sdv.carlaif.wheel_sha256", "SDV_WHEEL_SHA256")):
        assert arg in args and '%s="${%s}"' % (key, arg) in label, (key, label)
    assert bi().LABEL_KEYS == ("sdv.carlaif.base_digest", "sdv.carlaif.pin", "sdv.carlaif.sources_sha256", "sdv.carlaif.wheel_sha256")


# =================================================================================================================
# wheel.lock and pin.json (2.2; section 1 item 13)
# =================================================================================================================

def test_the_lock_holds_one_pin_the_cp312_wheel_by_its_sha256():
    text = LOCK.read_text(encoding="ascii")
    pins = re.findall(r"^([a-z0-9-]+)==(\S+) \\\n\s+--hash=sha256:([0-9a-f]{64})\n\s+# (\S+\.whl)$", text, re.M)
    assert pins == [("carla", "0.10.0", WHEEL_SHA256, WHEEL_FILE)], pins
    assert len(re.findall(r"^[a-z0-9-]+==", text, re.M)) == 1 and text.count("--hash=") == 1
    assert bi().read_lock() == {"name": "carla", "version": "0.10.0", "sha256": WHEEL_SHA256, "file": WHEEL_FILE}
    assert bi().LOCK_REL == "sdv/carlaif/wheel.lock" and bi().WHEEL_VERSION == "0.10.0"


def _pin_doc() -> Dict[str, Any]:
    return json.loads(PIN.read_text(encoding="ascii"))


def test_pin_json_names_the_commit_and_its_list_hashes_back_to_the_tree_id():
    doc = _pin_doc()
    assert (doc["commit"], doc["tree"]) == (PIN_COMMIT, PIN_TREE)
    assert (doc["repository"], doc["path"]) == ("autowarefoundation/autoware_universe", "simulator/autoware_carla_interface")
    entries = doc["entries"]
    assert len(entries) == 38 and len({e["path"] for e in entries}) == 38
    assert _tree_id(entries) == PIN_TREE, "the list does not hash back to the pin's tree id"
    assert sorted(e["path"] for e in entries if e["mode"] == "100755") == [
        "scripts/autoware_carla_interface", "scripts/multi_camera_combiner", "scripts/spectator_follow",
        "src/autoware_carla_interface/multi_camera_combiner_node.py"]
    assert {e["mode"] for e in entries} == {"100644", "100755"}
    assert all(set(e) == {"path", "mode", "blob"} for e in entries)


def test_pin_json_holds_ids_and_modes_only_and_names_the_one_file_left_out():
    doc = _pin_doc()
    assert set(doc) == {"format", "about", "repository", "path", "commit", "tree", "left_out", "entries"}
    assert doc["left_out"] == [LEFT_OUT] and LEFT_OUT in {e["path"] for e in doc["entries"]}
    by = {e["path"]: e for e in doc["entries"]}
    assert by[LEFT_OUT]["blob"] == "07da6662b78cfc059ed0c080fb22755ccc1645f7"
    assert by["config/raw_vehicle_cmd_converter.param.yaml"]["blob"] == UPSTREAM["converter_param_file"]["blob"]
    assert by["config/sensor_mapping_light_weight.yaml"]["blob"] == UPSTREAM["light_weight_mapping"]["blob"]
    assert all(re.fullmatch(r"[0-9a-f]{40}", e["blob"]) for e in doc["entries"])
    b = bi()
    assert (b.PIN_COMMIT, b.PIN_TREE) == (PIN_COMMIT, PIN_TREE) and b.load_pin()["tree"] == PIN_TREE


@pytest.mark.parametrize("change", ["mode", "blob", "drop", "path"])
def test_a_pin_json_changed_in_one_entry_is_refused_by_the_tree_id(tmp_path, change):
    """A mode changed (100644 to 100755), a blob id changed, an entry dropped or a path renamed: the list no longer hashes
    to the tree id, and build_image.py refuses the file before anything is staged."""
    doc = _pin_doc()
    e = next(x for x in doc["entries"] if x["path"] == "src/autoware_carla_interface/carla_ros.py")
    if change == "mode":
        e["mode"] = "100755"
    elif change == "blob":
        e["blob"] = "0" * 40
    elif change == "drop":
        doc["entries"].remove(e)
    else:
        e["path"] = "src/autoware_carla_interface/carla_ros2.py"
    assert _tree_id(doc["entries"]) != PIN_TREE
    f = tmp_path / "pin.json"
    f.write_text(json.dumps(doc), encoding="ascii")
    with pytest.raises(bi().BuildError, match="tree"):
        bi().load_pin(f)


def test_build_images_tree_id_agrees_with_this_tests_own():
    doc = _pin_doc()
    assert bi().tree_id(doc["entries"]) == _tree_id(doc["entries"]) == PIN_TREE
    assert bi().git_blob_id(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


# =================================================================================================================
# images.json's carlaif entry (2.2)
# =================================================================================================================

def test_the_carlaif_entry_is_the_rosvss_shape_amd64_only_run_by_id_and_its_labels_are_this_trees():
    e = IMAGES["carlaif"]
    assert set(e) == {"about", "amd64", "labels"}, set(e)
    pin = e["amd64"]
    assert set(pin) == {"id", "config_digest", "tag", "lock"}
    assert SHA.fullmatch(pin["id"]) and SHA.fullmatch(pin["config_digest"]) and pin["id"] != pin["config_digest"], "run by ID"
    assert pin["tag"] == "sdv-carlaif:local" == bi().TAG and pin["lock"] == "sdv/carlaif/wheel.lock"
    lbl = e["labels"]
    assert set(lbl) == set(bi().LABEL_KEYS)
    assert lbl["sdv.carlaif.base_digest"] == IMAGES["autoware"]["amd64"]["manifest_digest"]
    assert lbl["sdv.carlaif.pin"] == "%s:%s" % (PIN_COMMIT, PIN_TREE)
    assert lbl["sdv.carlaif.wheel_sha256"] == WHEEL_SHA256
    assert lbl["sdv.carlaif.sources_sha256"] == bi().sources_sha256(), "a changed staged source needs a rebuild and a re-pin"
    assert bi().labels(IMAGES) == lbl


def test_the_carlaif_entry_is_in_no_group_the_stack_pulls_builds_bundles_or_scans():
    for group in ("upstream", "local", "base", "test_only", "connector", "bridge"):
        assert "carlaif" not in IMAGES[group]
    assert "never pushed" in IMAGES["carlaif"]["about"] and "the stack never starts it" in IMAGES["carlaif"]["about"]


# The Dockerfile's sha256 as the pinned image was built from it (the build record's dockerfile_sha256). No label covers the
# Dockerfile (the labels name the base, the pin, the staged project sources and the wheel), so its text is held here.
PINNED_DOCKERFILE_SHA256 = "09d839ccf9ad8909b0446b51449dc753b2fde900e1b991ce7a7ec9041aa1fc34"


def test_the_dockerfile_is_the_text_the_pinned_image_was_built_from():
    got = hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()
    assert got == PINNED_DOCKERFILE_SHA256, (
        "sdv/carlaif/Dockerfile is not the text the image pinned in images.json's carlaif entry was built from (sha256 %s): an "
        "edit needs a rebuild (sdv/carlaif/build_image.py) and a re-pin, and PINNED_DOCKERFILE_SHA256 changed with them" % got)


def test_the_sources_digest_covers_the_entrypoint_the_pin_list_and_the_lock():
    b = bi()
    assert b.PROJECT_SOURCES == ("sdv/aw/aw-entrypoint.sh", "sdv/carlaif/pin.json", "sdv/carlaif/wheel.lock")
    lines = "".join("%s  %s\n" % (hashlib.sha256((REPO / rel).read_bytes()).hexdigest(), rel) for rel in b.PROJECT_SOURCES)
    assert b.sources_sha256() == hashlib.sha256(lines.encode("ascii")).hexdigest()


# =================================================================================================================
# build_image.py on stand-ins (2.2: it refuses a base by tag, a wheel whose sha256 is not the lock's, a source tree whose
# blob ids are not the pin's, and --provenance/--sbom other than false)
# =================================================================================================================

HOST = "format=1\nlo.flags=LOOPBACK,UP,LOWER_UP\nnet.core.rmem_max=1111111\nnet.ipv4.ipfrag_time=22\nnet.ipv4.ipfrag_high_thresh=3333333\n"
# (synthetic values: no reading of any host goes into a file of the tree)
PROJECT_CONFIG = {"User": "aw", "Entrypoint": ["/sdv-aw/aw-entrypoint.sh"]}
SYN_FILES = {"CMakeLists.txt": (b"project(x)\n", "100644"), "package.xml": (b"<package/>\n", "100644"),
             "scripts/run": (b"#!/usr/bin/env python3\n", "100755"), "src/m/__init__.py": (b"", "100644"),
             "docs/big.png": (b"\x89PNG", "100644")}


def _oci(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True).encode("utf-8")


def _save_stream(arch: str = "amd64", config_cfg: Any = None, labels: Optional[Dict[str, str]] = None):
    cfg = dict(PROJECT_CONFIG if config_cfg is None else config_cfg)
    if labels is not None:
        cfg["Labels"] = labels
    config = _oci({"architecture": arch, "os": "linux", "config": cfg})
    cd = "sha256:" + hashlib.sha256(config).hexdigest()
    man = _oci({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": cd, "size": len(config)}, "layers": []})
    md = "sha256:" + hashlib.sha256(man).hexdigest()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for digest, data in ((md, man), (cd, config)):
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
    """build_image.py's seams replaced, on a synthetic pin (five files, one left out) and a synthetic wheel and lock:
    docker (every call kept; `build` tags the image the save stream holds and records the staged context, `image
    inspect` of the base answers the index digest, `run` prints the proof's lines), the save stream, the host check and
    the staging root under tmp_path."""
    b = bi()
    src = tmp_path / "pin-copy"
    entries = []
    for rel, (data, mode) in SYN_FILES.items():
        entries.append({"path": rel, "mode": mode, "blob": _git_blob(data)})
        if rel != "docs/big.png":
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_bytes(data)
    tree = _tree_id(entries)
    pin = {"format": 1, "about": "synthetic", "repository": "example/repo", "path": "pkg", "commit": "c" * 40, "tree": tree,
           "left_out": ["docs/big.png"], "entries": entries}
    (tmp_path / "pin.json").write_text(json.dumps(pin), encoding="ascii")
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "carla-0.10.0-cp312-cp312-linux_x86_64.whl").write_bytes(b"a synthetic wheel")
    wsha = hashlib.sha256(b"a synthetic wheel").hexdigest()
    (tmp_path / "wheel.lock").write_text("# synthetic\ncarla==0.10.0 \\\n    --hash=sha256:%s\n    # %s\n" % (wsha, WHEEL_FILE),
                                         encoding="ascii")
    monkeypatch.setattr(b, "PIN_FILE", tmp_path / "pin.json")
    monkeypatch.setattr(b, "PIN_COMMIT", "c" * 40)
    monkeypatch.setattr(b, "PIN_TREE", tree)
    monkeypatch.setattr(b, "LOCK", tmp_path / "wheel.lock")
    monkeypatch.setattr(b, "CACHE", tmp_path / "cache")
    state: Dict[str, Any] = {"calls": [], "readings": [HOST, HOST], "tagged": None, "staged": None, "modes": None,
                             "base": IMAGES["autoware"]["index_digest"], "src": src, "wheels": wheels, "wsha": wsha, "tree": tree,
                             "proof_out": None}
    data, md, cd = _save_stream(labels=b.labels(IMAGES))
    state.update(data=data, md=md, cd=cd)

    def docker(*args: str, timeout: float = 120) -> str:
        state["calls"].append(list(args))
        if args[:1] == ("build",):
            ctx = Path(args[-1])
            files = sorted(p for p in ctx.rglob("*") if p.is_file())
            state["staged"] = sorted(str(p.relative_to(ctx)).replace("\\", "/") for p in files)   # a str sort (Windows sorts paths by case-folding)
            state["modes"] = {str(p.relative_to(ctx)).replace("\\", "/"): p.stat().st_mode & 0o777 for p in files}
            state["blobs"] = {str(p.relative_to(ctx)).replace("\\", "/"): _git_blob(p.read_bytes()) for p in files}
            state["tagged"] = state["md"]
        if args[:2] == ("image", "inspect"):
            return state["base"] or ""
        if args[:1] == ("run",):
            return state["proof_out"] if state["proof_out"] is not None else ""
        return ""

    def image_id(ref: str) -> Any:
        return state["tagged"] if ref == b.TAG else None

    def hostcheck(args: List[str]) -> subprocess.CompletedProcess:
        state["calls"].append(["hostcheck"] + list(args))
        if not args:
            return subprocess.CompletedProcess(args, 0, state["readings"].pop(0), "")
        before, after = (Path(a).read_text(encoding="utf-8").splitlines() for a in args[1:])
        changed = ["changed %s before=%s after=%s" % (x.split("=", 1)[0], x.split("=", 1)[1], y.split("=", 1)[1])
                   for x, y in zip(before, after) if x != y]
        return subprocess.CompletedProcess(args, 1 if changed else 0, "".join(c + "\n" for c in changed), "")

    monkeypatch.setattr(b, "docker", docker)
    monkeypatch.setattr(b, "image_id", image_id)
    monkeypatch.setattr(b, "hostcheck", hostcheck)
    monkeypatch.setattr(b, "docker_stream", lambda *a: (state["calls"].append(["stream"] + list(a)), _Popen(state["data"]))[1])
    state["b"] = b
    return state


def _build(rig, **kw):
    return rig["b"].build(IMAGES, rig["src"], rig["wheels"], **kw)


def test_the_build_stages_the_pins_files_the_wheel_and_the_project_files_outside_the_repo(rig):
    b = rig["b"]
    record = _build(rig)
    (argv,) = [c for c in rig["calls"] if c[:1] == ["build"]]
    assert rig["staged"] == sorted(["Dockerfile", "aw-entrypoint.sh", "wheel.lock", "wheels/" + WHEEL_FILE,
                                    "src/autoware_carla_interface/CMakeLists.txt", "src/autoware_carla_interface/package.xml",
                                    "src/autoware_carla_interface/scripts/run", "src/autoware_carla_interface/src/m/__init__.py"])
    assert "src/autoware_carla_interface/docs/big.png" not in rig["staged"], "the left-out file is never staged"
    if os.name != "nt":
        assert rig["modes"]["src/autoware_carla_interface/scripts/run"] == 0o755
        assert rig["modes"]["src/autoware_carla_interface/package.xml"] == 0o644
    assert rig["blobs"]["src/autoware_carla_interface/package.xml"] == _git_blob(b"<package/>\n")
    assert not str(Path(argv[-1])).startswith(str(REPO)) and not Path(argv[-1]).exists(), "staged outside the repo, removed after"
    assert record["image_id"] == rig["md"] and record["config_digest"] == rig["cd"]
    assert record["pin"] == {"amd64": {"id": rig["md"], "config_digest": rig["cd"], "tag": "sdv-carlaif:local",
                                       "lock": "sdv/carlaif/wheel.lock"}, "labels": b.labels(IMAGES)}


def test_the_build_arguments_are_the_bridges_pattern_with_no_network_no_pull_and_the_four_labels(rig):
    b = rig["b"]
    _build(rig)
    (argv,) = [c for c in rig["calls"] if c[:1] == ["build"]]
    lbl = b.labels(IMAGES)
    assert argv[:6] == ["build", "-q", "--provenance=false", "--sbom=false", "--pull=false", "--network=none"], argv
    assert argv[6:14] == ["--build-arg", "SDV_BASE_DIGEST=" + lbl["sdv.carlaif.base_digest"], "--build-arg", "SDV_PIN=" + lbl["sdv.carlaif.pin"],
                          "--build-arg", "SDV_SOURCES_SHA256=" + lbl["sdv.carlaif.sources_sha256"],
                          "--build-arg", "SDV_WHEEL_SHA256=" + lbl["sdv.carlaif.wheel_sha256"]], argv
    assert argv[argv.index("-t") + 1] == "sdv-carlaif:local" and "--privileged" not in argv
    assert not [c for c in rig["calls"] if c[:1] == ["buildx"]]
    assert lbl["sdv.carlaif.pin"] == "%s:%s" % ("c" * 40, rig["tree"]) and lbl["sdv.carlaif.wheel_sha256"] == rig["wsha"]


@pytest.mark.parametrize("bad", [["--provenance=true"], ["--sbom=true"], ["--provenance=mode=max"], ["--attest", "type=sbom"], []],
                         ids=["provenance-true", "sbom-true", "provenance-mode", "attest", "neither-false"])
def test_provenance_or_sbom_other_than_false_is_refused(bad):
    b = bi()
    argv = ["build", "-q"] + bad + (["--provenance=false", "--sbom=false"] if bad else ["--pull=false"]) + ["-t", b.TAG, "ctx"]
    with pytest.raises(b.BuildError, match="provenance|sbom|attest"):
        b.check_build_argv(argv)
    b.check_build_argv(["build", "-q", "--provenance=false", "--sbom=false", "-t", b.TAG, "ctx"])


def test_a_build_whose_argument_vector_has_provenance_on_never_reaches_docker(rig, monkeypatch):
    b = rig["b"]
    real = b.build_args
    monkeypatch.setattr(b, "build_args", lambda lbl, ctx: [a.replace("--provenance=false", "--provenance=true") for a in real(lbl, ctx)])
    with pytest.raises(b.BuildError, match="provenance"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] == ["build"]]


def test_a_dockerfile_from_a_tag_or_another_digest_is_refused_before_docker_runs(rig, monkeypatch, tmp_path):
    b = rig["b"]
    text = DOCKERFILE.read_text(encoding="utf-8")
    pinned = IMAGES["autoware"]["amd64"]["manifest_digest"]
    for other in (text.replace("@" + pinned, ":universe-jazzy-1.9.0"), text.replace(pinned, IMAGES["autoware"]["index_digest"]),
                  text + "from ubuntu:24.04\n"):
        f = tmp_path / "Dockerfile"
        f.write_text(other, encoding="utf-8")
        monkeypatch.setattr(b, "DOCKERFILE", f)
        with pytest.raises(b.BuildError, match="FROM"):
            _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], rig["calls"]


@pytest.mark.parametrize("add, named", [
    ("COPY --from=busybox:1.36 /bin/busybox /usr/local/bin/busybox\n", "busybox:1.36"),
    ("COPY --from=ghcr.io/example/tool@sha256:%s /tool /tool\n" % ("0" * 64), "ghcr.io/example/tool@sha256:"),
    ("COPY --chown=aw \\\n     --from=alpine /etc/os-release /tmp/os-release\n", "alpine"),
    ("RUN --mount=type=bind,from=alpine:3.20,target=/mnt true\n", "alpine:3.20"),
    ("SYNTAX", "docker/dockerfile:1")], ids=["copy-from-tag", "copy-from-digest", "copy-from-continued", "run-mount-from", "syntax"])
def test_a_dockerfile_naming_another_image_beside_its_from_is_refused_before_docker_runs(rig, monkeypatch, tmp_path, add, named):
    """The one FROM is not the only place a Dockerfile names an image: COPY --from=, RUN --mount=...,from= and a
    `# syntax=` parser directive (BuildKit's frontend image) each name one, by tag or digest. The FROM rule allows no stage
    name (`FROM ... AS name` is refused), so any --from names an image, and each is refused before the host check."""
    b = rig["b"]
    text = DOCKERFILE.read_text(encoding="utf-8")
    other = "# syntax=docker/dockerfile:1\n" + text if add == "SYNTAX" else text.replace("\nUSER aw\n", "\n" + add + "USER aw\n")
    assert other != text
    f = tmp_path / "Dockerfile"
    f.write_text(other, encoding="utf-8")
    monkeypatch.setattr(b, "DOCKERFILE", f)
    with pytest.raises(b.BuildError) as e:
        _build(rig)
    assert named in str(e.value) and "image" in str(e.value), str(e.value)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], rig["calls"]
    f.write_text(text, encoding="utf-8")
    assert b.check_inputs(IMAGES) == "%s@%s" % (b.BASE_REPO, IMAGES["autoware"]["amd64"]["manifest_digest"]), "the file as it stands"


def test_a_wheel_whose_sha256_is_not_the_locks_is_refused_before_docker_runs(rig):
    b = rig["b"]
    (rig["wheels"] / WHEEL_FILE).write_bytes(b"another wheel")
    with pytest.raises(b.BuildError, match="sha256"):
        _build(rig)
    (rig["wheels"] / WHEEL_FILE).unlink()
    with pytest.raises(b.BuildError, match="no wheel"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], "refused before the host check is read"


@pytest.mark.parametrize("change", ["edited", "missing", "extra", "left-out-edited"])
def test_a_source_tree_whose_blob_ids_are_not_the_pins_is_refused_before_docker_runs(rig, change):
    b = rig["b"]
    src = rig["src"]
    if change == "edited":
        (src / "package.xml").write_bytes(b"<package version='x'/>\n")
    elif change == "missing":
        (src / "CMakeLists.txt").unlink()
    elif change == "extra":
        (src / "setup.py").write_bytes(b"# not in the pin\n")
    else:
        (src / "docs").mkdir()
        (src / "docs" / "big.png").write_bytes(b"another png")
    with pytest.raises(b.BuildError, match="pin"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], "refused before the host check is read: %s" % rig["calls"]


def test_the_left_out_file_present_with_its_own_blob_is_checked_and_still_not_staged(rig):
    (rig["src"] / "docs").mkdir()
    (rig["src"] / "docs" / "big.png").write_bytes(b"\x89PNG")
    _build(rig)
    assert not [s for s in rig["staged"] if s.endswith("big.png")]


def test_a_base_missing_from_the_store_is_refused_nothing_is_pulled(rig):
    b = rig["b"]
    rig["base"] = None
    with pytest.raises(b.BuildError, match="not in the image store"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["pull"])]
    (inspect,) = [c for c in rig["calls"] if c[:2] == ["image", "inspect"]]
    assert inspect[-1] == "ghcr.io/autowarefoundation/autoware@" + IMAGES["autoware"]["index_digest"]


def test_the_host_check_is_read_before_and_after_and_a_changed_setting_fails_the_build(rig):
    b = rig["b"]
    record = _build(rig)
    order = [c[0] for c in rig["calls"] if c[0] in ("hostcheck", "build")]
    assert order[:3] == ["hostcheck", "build", "hostcheck"] and record["host_check"]["changed"] == []
    rig["readings"][:] = [HOST, HOST.replace("ipfrag_time=22", "ipfrag_time=3")]
    with pytest.raises(b.BuildError, match="changed net.ipv4.ipfrag_time before=22 after=3"):
        _build(rig)


@pytest.mark.parametrize("config_cfg, why", [
    ({"User": "root", "Entrypoint": ["/sdv-aw/aw-entrypoint.sh"]}, "the user 'root'"),
    ({"User": "aw", "Entrypoint": ["/docker-entrypoint.sh"]}, "the entrypoint ['/docker-entrypoint.sh']"),
    ({"User": "aw"}, "the entrypoint None")])
def test_a_built_config_that_is_not_the_projects_entrypoint_and_aw_is_refused_before_the_proof_and_the_pin(rig, config_cfg, why):
    b = rig["b"]
    data, md, cd = _save_stream(config_cfg=config_cfg, labels=b.labels(IMAGES))
    rig.update(data=data, md=md, cd=cd)
    with pytest.raises(b.BuildError) as e:
        _build(rig, proof=True)
    assert why in str(e.value) and "nothing is proved or pinned" in str(e.value)
    assert not [c for c in rig["calls"] if c[:1] == ["run"]]


def test_a_built_config_whose_labels_are_not_the_ones_given_is_refused(rig):
    b = rig["b"]
    lbl = dict(b.labels(IMAGES), **{"sdv.carlaif.wheel_sha256": "0" * 64})
    data, md, cd = _save_stream(labels=lbl)
    rig.update(data=data, md=md, cd=cd)
    with pytest.raises(b.BuildError, match="labels"):
        _build(rig)


def test_a_staging_root_inside_the_repo_is_refused_before_the_host_check_or_docker(rig, monkeypatch, tmp_path):
    b = rig["b"]
    monkeypatch.setattr(b, "REPO", tmp_path / "repo")
    monkeypatch.setattr(b, "CACHE", tmp_path / "repo" / "cache")
    with pytest.raises(b.BuildError, match="inside the repo"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])] and not (tmp_path / "repo").exists()


@pytest.mark.parametrize("pin", ["carla==0.9.16", "numpy==0.10.0"])
def test_a_lock_that_does_not_pin_carla_0_10_0_is_refused_before_docker_runs(rig, pin):
    """The lock's one pin is the cp312 client wheel of carla 0.10.0: another version or another package, however well formed
    and hashed, is refused by name and version before the host check is read."""
    b = rig["b"]
    b.LOCK.write_text("# synthetic\n%s \\\n    --hash=sha256:%s\n    # %s\n" % (pin, rig["wsha"], WHEEL_FILE), encoding="ascii")
    with pytest.raises(b.BuildError, match="not carla==0.10.0"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], rig["calls"]


def test_a_built_image_that_is_not_linux_amd64_is_refused_before_the_proof_and_the_pin(rig):
    """The save stream's config says its platform: an arm64 image (no arm64 client wheel exists) is refused though its
    entrypoint, user and labels are the project's."""
    b = rig["b"]
    data, md, cd = _save_stream(arch="arm64", labels=b.labels(IMAGES))
    rig.update(data=data, md=md, cd=cd)
    with pytest.raises(b.BuildError, match="linux/arm64, not linux/amd64"):
        _build(rig, proof=True)
    assert not [c for c in rig["calls"] if c[:1] == ["run"]]


def test_a_symlink_in_the_source_is_refused_though_its_target_has_the_pins_blob(rig):
    """A symlink named like a pin file and pointing at a file with the pin's bytes reads as that file under is_file(): it is
    refused as not a regular file (a copy of the pin is a folder of regular files). Skipped on a host that lets this user
    make no symlink (Windows without the privilege): nothing stands in for a link there."""
    b = rig["b"]
    pkg = rig["src"] / "package.xml"
    elsewhere = rig["src"].parent / "package-elsewhere.xml"
    elsewhere.write_bytes(pkg.read_bytes())
    pkg.unlink()
    try:
        pkg.symlink_to(elsewhere)
    except (OSError, NotImplementedError) as err:
        pytest.skip("this host lets this user make no symlink: %s" % err)
    with pytest.raises(b.BuildError, match="package.xml is not a regular file"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], rig["calls"]


def test_a_wheel_that_is_a_symlink_is_refused_though_its_target_has_the_locks_sha256(rig):
    """The lock's wheel must be a regular file in --wheels: a symlink of its name to a file with the same bytes reads as
    that file under is_file() and hashes to the lock's sha256, and is refused before the host check is read. Skipped on a
    host that lets this user make no symlink."""
    b = rig["b"]
    whl = rig["wheels"] / WHEEL_FILE
    elsewhere = rig["wheels"].parent / "wheel-elsewhere.whl"
    elsewhere.write_bytes(whl.read_bytes())
    whl.unlink()
    try:
        whl.symlink_to(elsewhere)
    except (OSError, NotImplementedError) as err:
        pytest.skip("this host lets this user make no symlink: %s" % err)
    with pytest.raises(b.BuildError, match="no wheel %s in .*a regular file" % re.escape(WHEEL_FILE)):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], rig["calls"]


@pytest.mark.parametrize("staged, why", [("src/autoware_carla_interface/package.xml", r"the staged package\.xml's blob id is not the pin's"),
                                         ("wheels/" + WHEEL_FILE, r"the staged wheel's sha256 is [0-9a-f]{64}, not the lock's")],
                         ids=["pin-file", "wheel"])
def test_a_file_whose_bytes_change_as_it_is_staged_is_refused_before_docker_builds(rig, monkeypatch, staged, why):
    """The context is checked again as staged: a pin file whose blob id, or the wheel whose sha256, is no longer the pin's or
    the lock's once copied (here a copy that alters that one file, put in place of build_image.py's own shutil alone,
    never the shutil module every caller shares) is refused, and docker never builds."""
    b = rig["b"]
    real = b.shutil

    def copyfile(src: Any, dst: Any) -> Any:
        got = real.copyfile(src, dst)
        if Path(dst).as_posix().endswith("/" + staged):
            Path(dst).write_bytes(Path(dst).read_bytes() + b"altered")
        return got
    monkeypatch.setattr(b, "shutil", types.SimpleNamespace(copyfile=copyfile, rmtree=real.rmtree))
    with pytest.raises(b.BuildError, match=why):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] == ["build"]], rig["calls"]


def test_a_base_the_store_answers_with_another_id_is_refused_nothing_is_pulled(rig):
    """The store's answer for the base's reference must be images.json's autoware index digest itself: any other ID is
    refused as the base not in the store, before the host check is read, and nothing is pulled or built."""
    b = rig["b"]
    rig["base"] = "sha256:" + "2" * 64
    assert rig["base"] != IMAGES["autoware"]["index_digest"]
    with pytest.raises(b.BuildError, match="not in the image store"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["pull"], ["hostcheck"])], rig["calls"]


def test_a_lock_with_a_second_requirement_line_beside_its_hashed_pin_is_refused_before_docker_runs(rig):
    """The lock holds one requirement line, the hashed wheel's: a second one without a hash or a wheel file beside it is
    refused by the count of requirement lines, before the host check is read."""
    b = rig["b"]
    b.LOCK.write_text(b.LOCK.read_text(encoding="ascii") + "numpy==1.0\n", encoding="ascii")
    with pytest.raises(b.BuildError, match="holds 1 pins with a hash and a wheel file, not one"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], rig["calls"]


def test_a_pin_json_entry_with_a_key_beside_path_mode_and_blob_is_refused_before_docker_runs(rig):
    """Each entry of pin.json is its path, mode and blob id and nothing else: an entry with a further key (which the tree id
    does not cover) is refused though the list still hashes back to the tree id."""
    b = rig["b"]
    doc = json.loads(b.PIN_FILE.read_text(encoding="ascii"))
    doc["entries"][0]["note"] = "a key the tree id does not cover"
    assert b.tree_id(doc["entries"]) == rig["tree"]
    b.PIN_FILE.write_text(json.dumps(doc), encoding="ascii")
    with pytest.raises(b.BuildError, match="an entry that is not a relative path with a blob mode and id"):
        _build(rig)
    assert not [c for c in rig["calls"] if c[:1] in (["build"], ["hostcheck"])], rig["calls"]


def test_a_host_check_comparison_that_cannot_be_made_fails_the_build(rig, monkeypatch):
    """hostcheck.sh --compare exits 0 (the settings equal) or 1 (a setting changed): any other exit is a comparison that
    could not be made, and the build fails rather than read it as no change."""
    b = rig["b"]
    real = b.hostcheck

    def hostcheck(args: List[str]) -> subprocess.CompletedProcess:
        if not args:
            return real(args)
        rig["calls"].append(["hostcheck"] + list(args))
        return subprocess.CompletedProcess(args, 2, "", "the stand-in cannot compare\n")
    monkeypatch.setattr(b, "hostcheck", hostcheck)
    with pytest.raises(b.BuildError, match=r"the host check's comparison failed \(exit 2\): the stand-in cannot compare"):
        _build(rig)
    assert [c[0] for c in rig["calls"] if c[0] in ("hostcheck", "build")][:3] == ["hostcheck", "build", "hostcheck"], rig["calls"]


@pytest.mark.parametrize("left", [["docs/nothing.png"], ["docs/big.png", "docs/nothing.png"], "docs/big.png", None],
                         ids=["names-no-entry", "one-of-two-names-no-entry", "a-string", "absent"])
def test_a_pin_json_whose_left_out_is_not_a_list_of_its_own_entries_is_refused(rig, tmp_path, left):
    b = rig["b"]
    b.load_pin()
    doc = json.loads(b.PIN_FILE.read_text(encoding="ascii"))
    doc["left_out"] = left
    f = tmp_path / "p.json"
    f.write_text(json.dumps(doc), encoding="ascii")
    with pytest.raises(b.BuildError, match="left_out"):
        b.load_pin(f)


def test_a_proof_by_tag_or_by_anything_but_a_full_id_is_refused_before_docker_runs(rig):
    """The proof runs the image by its ID: the tag moves with the next build, and what ran would not be what was pinned."""
    b = rig["b"]
    for ref in (b.TAG, "sdv-carlaif", "sha256:abc", "sha256:" + "A" * 64, "0" * 64):
        with pytest.raises(b.BuildError, match="by its ID"):
            b.proof(ref)
    assert rig["calls"] == [], rig["calls"]


def _image_before(rig, monkeypatch, before: str, repo_tags: List[str]) -> None:
    """The rig with the tag naming BEFORE until the build, BEFORE still in the store afterwards, and its tags after the build
    REPO_TAGS (what `docker image inspect --format {{json .RepoTags}}` prints)."""
    b = rig["b"]
    rig["tagged"] = before
    real_docker, real_image_id = b.docker, b.image_id

    def docker(*args: str, timeout: float = 120) -> str:
        if args[:2] == ("image", "inspect") and "{{json .RepoTags}}" in args:
            rig["calls"].append(list(args))
            return json.dumps(repo_tags)
        return real_docker(*args, timeout=timeout)

    monkeypatch.setattr(b, "docker", docker)
    monkeypatch.setattr(b, "image_id", lambda ref: before if ref == before else real_image_id(ref))


def test_a_rebuild_keeps_the_image_images_json_pins_though_the_tag_no_longer_names_it(rig, monkeypatch):
    """The image the tag named before and the rebuild left untagged is removed by ID (the rosvss pattern), except the one
    images.json's carlaif.amd64 pins: the runs take that image by its ID with --pull never, so it stays until a re-pin."""
    b = rig["b"]
    pinned = IMAGES["carlaif"]["amd64"]["id"]
    _image_before(rig, monkeypatch, pinned, [])
    record = _build(rig)
    assert record["image_id"] == rig["md"] != pinned
    assert not [c for c in rig["calls"] if c[:2] == ["image", "rm"]], rig["calls"]
    assert record["replaced_image"] == {"id": pinned, "left": "kept (images.json pins it)"}
    assert b.TAG == "sdv-carlaif:local"


def test_a_rebuild_removes_by_its_id_the_untagged_image_the_tag_named_before_when_images_json_does_not_pin_it(rig, monkeypatch):
    """The tag is this script's alone: the image it named before and the rebuild left untagged goes (docker image rm by its
    ID), and the record says so."""
    old = "sha256:" + "1" * 64
    assert old != IMAGES["carlaif"]["amd64"]["id"]
    _image_before(rig, monkeypatch, old, [])
    record = _build(rig)
    assert ["image", "rm", old] in rig["calls"], rig["calls"]
    assert record["replaced_image"] == {"id": old, "left": "removed (untagged by this build)"}
    assert record["image_id"] == rig["md"] != old


def test_a_rebuild_keeps_the_old_image_another_tag_still_names(rig, monkeypatch):
    old = "sha256:" + "1" * 64
    _image_before(rig, monkeypatch, old, ["other:tag"])
    record = _build(rig)
    assert not [c for c in rig["calls"] if c[:2] == ["image", "rm"]], rig["calls"]
    assert record["replaced_image"] == {"id": old, "left": "kept (another tag names it)"}


# --- the proof (2.2), read inside the built image ---------------------------------------------------------------------

def _proof_doc(**over: Any) -> Dict[str, Any]:
    b = bi()
    base = {"python3": "/opt/sdv-carlaif/venv/bin/python3", "executable": "/opt/sdv-carlaif/venv/bin/python3",
            "carla_file": "/opt/sdv-carlaif/venv/lib/python3.12/site-packages/carla.cpython-312-x86_64-linux-gnu.so",
            "carla_version": "0.10.0", "client_version": "0.10.0",
            "interface_file": b.OVERLAY + "/autoware_carla_interface/lib/python3.12/site-packages/autoware_carla_interface/__init__.py",
            "carla_ros_file": b.OVERLAY + "/autoware_carla_interface/lib/python3.12/site-packages/autoware_carla_interface/carla_ros.py",
            "share": b.OVERLAY + "/autoware_carla_interface/share/autoware_carla_interface",
            "prefix": b.OVERLAY + "/autoware_carla_interface", "package_version": "0.53.0",
            "image_copy_prefix": "/opt/autoware/autoware_carla_interface", "image_copy_version": "0.52.0",
            "script_shebang": "#!/usr/bin/env python3", "carla_ros_imported": True}
    base.update(over)
    return base


def test_the_proofs_judge_passes_the_pins_package_and_the_venvs_carla():
    assert bi().proof_problems(_proof_doc()) == []


@pytest.mark.parametrize("over, why", [
    ({"package_version": "0.52.0"}, "0.53.0"),
    ({"interface_file": "/opt/autoware/autoware_carla_interface/lib/python3.12/site-packages/autoware_carla_interface/__init__.py"},
     "overlay"),
    ({"share": "/opt/autoware/autoware_carla_interface/share/autoware_carla_interface"}, "overlay"),
    ({"prefix": "/opt/autoware/autoware_carla_interface"}, "0.52.0 copy"),
    ({"carla_version": "0.9.16"}, "0.10.0"),
    ({"carla_file": "/opt/ros/jazzy/lib/python3.12/site-packages/carla.so"}, "venv"),
    ({"python3": "/usr/bin/python3"}, "python3"),
    ({"script_shebang": "#!/usr/bin/python3"}, "shebang")])
def test_the_proofs_judge_names_each_way_the_running_node_would_not_be_the_pins(over, why):
    problems = bi().proof_problems(_proof_doc(**over))
    assert problems and any(why in p for p in problems), problems


def test_the_proof_runs_the_built_image_by_id_under_the_projects_flags_with_the_tree_read_only(rig):
    b = rig["b"]
    out = "\n".join(["== reads", json.dumps(_proof_doc()), "== end"])
    rig["proof_out"] = out
    record = _build(rig, proof=True)
    runs = [c for c in rig["calls"] if c[:1] == ["run"]]
    assert len(runs) == 3, runs
    for argv in runs:
        for opt, value in (("--network", "none"), ("--pull", "never"), ("--platform", "linux/amd64"), ("--user", "aw"),
                           ("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges"), ("--entrypoint", "/sdv-aw/aw-entrypoint.sh")):
            assert argv.count(opt) == 1 and argv[argv.index(opt) + 1] == value, (opt, argv)
        assert "--rm" in argv and rig["md"] in argv and b.TAG not in argv, "by ID, never by tag"
        assert not [a for a in argv if a.startswith(("--privileged", "--cap-add", "--publish", "--pid", "--ipc", "--userns"))]
        mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
        assert all(m.endswith(":ro") for m in mounts), mounts
        assert b.LAUNCH_ENV in " ".join(argv)
    launches = [r for r in runs if "ros2 launch --print" in " ".join(r)]
    assert len(launches) == 2 and {"/sdv/sdv/carlaif/launch/sdv_carla.launch.xml", "/sdv/sdv/carlaif/launch/sdv_autoware.launch.xml"} <= set(
        w for r in launches for w in " ".join(r).split())
    assert record["proof"]["problems"] == [] and record["proof"]["reads"]["package_version"] == "0.53.0"


def test_a_proof_that_reads_the_052_copy_fails_the_build_and_pins_nothing(rig):
    b = rig["b"]
    rig["proof_out"] = "\n".join(["== reads", json.dumps(_proof_doc(prefix="/opt/autoware/autoware_carla_interface")), "== end"])
    with pytest.raises(b.BuildError, match="proof"):
        _build(rig, proof=True)


def test_the_launch_environment_sources_the_overlay_and_puts_the_venv_first():
    b = bi()
    assert b.LAUNCH_ENV == "source /opt/sdv-carlaif/install/local_setup.bash && export PATH=/opt/sdv-carlaif/venv/bin:$PATH"


@pytest.mark.parametrize("value", ["error: ModuleNotFoundError: No module named 'transforms3d'", None, "True"],
                         ids=["import-error", "not-read", "not-a-boolean"])
def test_the_proof_imports_the_nodes_own_module_and_its_judge_requires_that_import(value):
    """find_spec of autoware_carla_interface.carla_ros runs the package's __init__ only; the node's module imports carla,
    cv2, cv_bridge, transforms3d and the message packages at its top, so the proof imports it (a module import: it creates
    no node) under the venv's python, and the judge names a proof whose import failed or was not read."""
    b = bi()
    assert 'importlib.import_module("autoware_carla_interface.carla_ros")' in b.PROOF_PY
    assert '"carla_ros_imported"' in b.PROOF_PY
    over = {} if value is None else {"carla_ros_imported": value}
    doc = _proof_doc(**over)
    if value is None:
        doc.pop("carla_ros_imported")
    problems = b.proof_problems(doc)
    assert problems and any("carla_ros" in p for p in problems), problems
    assert b.proof_problems(_proof_doc()) == []


def test_the_proofs_parse_takes_t1s_spawn_point_and_the_map_folders_name_from_town10(rig, monkeypatch, tmp_path):
    """The launch arguments the proof parses with: town10.py's spawn point of t1's start and its map folder's name, read
    from the file, so a change there reaches the parse; the host is RFC 5737's documentation address."""
    b = rig["b"]
    t = town10()
    assert b.print_args("sdv_carla.launch.xml") == ["host:=192.0.2.1", "spawn_point:=" + t.scenario_spawn_point("t1")]
    assert b.print_args("sdv_autoware.launch.xml") == ["map_path:=/maps/" + t.MAP_NAME]
    stand_in = tmp_path / "town10.py"
    stand_in.write_text("MAP_NAME = 'Town-x'\n\ndef scenario_spawn_point(sid):\n    return '1.5,2.5,3.5,0.0,0.0,%s' % len(sid)\n",
                        encoding="ascii")
    monkeypatch.setattr(b, "TOWN10_FILE", stand_in)
    rig["proof_out"] = "\n".join(["== reads", json.dumps(_proof_doc()), "== end"])
    _build(rig, proof=True)
    printed = [" ".join(c) for c in rig["calls"] if c[:1] == ["run"] and "ros2 launch --print" in " ".join(c)]
    assert len(printed) == 2 and "spawn_point:=1.5,2.5,3.5,0.0,0.0,2" in printed[0] and "map_path:=/maps/Town-x" in printed[1], printed


# =================================================================================================================
# The vehicle side's launch (2.3)
# =================================================================================================================

def _xml(path: Path) -> ET.Element:
    return ET.parse(str(path)).getroot()


def _params(node: ET.Element) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in node.findall("param"):
        if p.get("name") is not None:
            assert p.get("name") not in out, "a parameter given twice: %s" % p.get("name")
            out[p.get("name") or ""] = p.get("value") or ""
    return out


def _remaps(node: ET.Element) -> Dict[str, str]:
    return {r.get("from") or "": r.get("to") or "" for r in node.findall("remap")}


def _step_s() -> float:
    if not CONTRACT.is_file():
        if os.environ.get("SDV_REQUIRE_GEN") == "1":
            pytest.fail("no generated contract at %s" % CONTRACT)
        pytest.skip("needs the generated contract (sdv-out/gen)")
    m = re.search(r"^CARLA_STEP_MS = (\d+)$", CONTRACT.read_text(encoding="utf-8"), re.M)
    assert m is not None
    return int(m.group(1)) / 1000


# 2.3's parameters of the interface node, each with its value; the host and the spawn point are the launch's two
# arguments (the gateway read at run time; town10.py's string), use_sim_time is 2.1's.
INTERFACE_PARAMS = {
    "host": "$(var host)", "port": "2000", "timeout": "20", "sync_mode": "True", "fixed_delta_seconds": "0.05",
    "carla_map": "Carla/Maps/Town10HD_Opt", "ego_vehicle_role_name": "ego_vehicle", "spawn_point": "$(var spawn_point)",
    "vehicle_type": "vehicle.taxi.ford", "use_traffic_manager": "False", "max_real_delta_seconds": "0.05", "tick_follower": "False",
    "max_substep_delta_time": "0.0", "publish_ground_truth_localization": "true", "publish_ground_truth_objects": "true",
    "sensor_mapping_file": "$(dirname)/../config/sensor_mapping_sdv.yaml", "flatten_steering_curve": "true",
    "wake_sleeping_physics": "true", "use_sim_time": "true"}
CONVERTER_REMAPS = {"~/input/control_cmd": "/control/command/control_cmd", "~/input/odometry": "/localization/kinematic_state",
                    "~/input/steering": "/vehicle/status/steering_status", "~/output/actuation_cmd": "/control/command/actuation_cmd"}


def _nodes(root: ET.Element) -> Dict[str, ET.Element]:
    found = list(root.iter("node"))
    by = {n.get("name") or "": n for n in found}
    assert len(by) == len(found)
    return by


def test_the_vehicle_side_starts_the_interface_and_the_converter_and_nothing_else():
    root = _xml(LAUNCH_CARLA)
    assert set(_nodes(root)) == {"autoware_carla_interface", "autoware_raw_vehicle_cmd_converter"}
    assert not list(root.iter("include")) and not list(root.iter("node_container")) and not list(root.iter("composable_node"))
    ifc = _nodes(root)["autoware_carla_interface"]
    assert (ifc.get("pkg"), ifc.get("exec")) == ("autoware_carla_interface", "autoware_carla_interface")
    conv = _nodes(root)["autoware_raw_vehicle_cmd_converter"]
    assert (conv.get("pkg"), conv.get("exec")) == ("autoware_raw_vehicle_cmd_converter", "autoware_raw_vehicle_cmd_converter_node")
    assert pc().INTERFACE_NODE == "autoware_carla_interface" and pc().CONVERTER_NODE == "autoware_raw_vehicle_cmd_converter"


def test_the_interfaces_output_is_the_screen_so_its_flat_curve_line_reaches_docker_logs():
    """Item 5's first source is the interface's flat-curve line in `docker logs`: a node's output="log" would send it to ROS's
    log files in the container instead (PYTHONUNBUFFERED, in the Dockerfile, is the other half)."""
    assert _nodes(_xml(LAUNCH_CARLA))["autoware_carla_interface"].get("output") == "screen"


def test_every_parameter_of_2_3_is_given_with_its_value_and_no_other():
    """Exactly 2.3's set: flatten_steering_curve and wake_sleeping_physics true, max_substep_delta_time 0.0 (a double: the
    code declares it so), timeout given (the code has no default), publish_ground_truth_localization true directly,
    publish_ground_truth_objects true, and max_wheel_steer_angle_deg, min_positive_throttle and no_rendering_mode absent."""
    ifc = _nodes(_xml(LAUNCH_CARLA))["autoware_carla_interface"]
    assert _params(ifc) == INTERFACE_PARAMS
    assert not ifc.findall("param[@from]"), "no parameter file beside 2.3's values"
    declared = set(UPSTREAM["interface_parameters"])
    assert set(INTERFACE_PARAMS) - {"use_sim_time"} <= declared, set(INTERFACE_PARAMS) - declared
    for absent in ("max_wheel_steer_angle_deg", "min_positive_throttle", "no_rendering_mode", "traffic_light.publish"):
        assert absent in declared and absent not in _params(ifc)


def test_the_step_is_the_contracts_and_the_spawn_point_and_host_are_required_arguments():
    root = _xml(LAUNCH_CARLA)
    assert float(INTERFACE_PARAMS["fixed_delta_seconds"]) == _step_s()
    args = {a.get("name"): a for a in root.findall("arg")}
    assert set(args) == {"host", "spawn_point"}
    assert all(a.get("default") is None for a in args.values()), "no default: the gateway is read at run time, the spawn per scenario"
    assert town10().spawn_point(136).count(",") == 5, "the string P1's town10.py writes, six numbers"


def test_the_interfaces_two_remaps_are_2_10s():
    ss = steershim()
    ifc = _nodes(_xml(LAUNCH_CARLA))["autoware_carla_interface"]
    assert _remaps(ifc) == {ss.IN_ACTUATION: ss.OUT_ACTUATION, ss.OUT_REPORT: ss.IN_REPORT}
    assert _remaps(ifc) == {"/control/command/actuation_cmd": "/sdv/steershim/actuation_cmd",
                            "/vehicle/status/steering_status": "/sdv/steershim/steering_status_raw"}


def test_the_converter_takes_the_pins_param_file_with_allow_substs_and_its_four_remaps():
    conv = _nodes(_xml(LAUNCH_CARLA))["autoware_raw_vehicle_cmd_converter"]
    files = conv.findall("param[@from]")
    assert len(files) == 1
    assert files[0].get("from") == "$(find-pkg-share autoware_carla_interface)/" + UPSTREAM["converter_param_file"]["path"]
    assert files[0].get("allow_substs") == "true", "its csv paths are $(find-pkg-share ...): literal ones throw at start"
    assert _params(conv) == {"use_sim_time": "true"}
    assert _remaps(conv) == CONVERTER_REMAPS


@pytest.mark.parametrize("path", [LAUNCH_CARLA, LAUNCH_AW], ids=["vehicle-side", "autoware-side"])
def test_no_rviz_e2e_planning_or_simulator_interface_switch_in_either_launch(path):
    text = path.read_text(encoding="utf-8")
    for word in ("use_e2e_planning", "launch_simulator_interface", "e2e_simulator.launch"):
        assert word not in text, word
    root = _xml(path)
    assert not [n for n in root.iter("node") if "rviz" in (n.get("pkg") or "") + (n.get("exec") or "") + (n.get("name") or "")]
    if path == LAUNCH_CARLA:
        assert "rviz" not in text


# =================================================================================================================
# The Autoware side's launch (2.3)
# =================================================================================================================

AW_INCLUDE = "$(find-pkg-share autoware_launch)/launch/autoware.launch.xml"
SIM_INCLUDE = "$(find-pkg-share autoware_launch)/launch/components/tier4_simulator_component.launch.xml"
T2A_INCLUDE = "$(find-pkg-share autoware_twist2accel)/launch/twist2accel.launch.xml"
# The values 2.3 names (changed from planning_simulator.launch.xml's, or added to them).
AW_CHANGED = {"map_path": "$(var map_path)", "vehicle_model": "sample_vehicle", "sensor_model": "sample_sensor_kit",
              "system_run_mode": "planning_simulation", "is_simulation": "true", "use_sim_time": "true", "launch_sensing": "false",
              "launch_sensing_driver": "false", "launch_localization": "false", "launch_perception": "false", "launch_vehicle": "true",
              "launch_vehicle_interface": "false", "launch_system_monitor": "false", "launch_dummy_diag_publisher": "true", "rviz": "false"}
AW_ADDED = {"use_sim_time", "launch_sensing_driver", "launch_vehicle"}
SIM_CHANGED = {"launch_dummy_vehicle": "false", "launch_dummy_perception": "false", "launch_dummy_doors": "false",
               "localization_sim_mode": "api", "perception/enable_object_recognition": "true", "perception/enable_traffic_light": "false",
               "launch_scenario_simulator_v2_adapter": "false", "vehicle_model": "sample_vehicle"}
# Every other argument at its value in planning_simulator.launch.xml (the kept image's), its substitutions resolved as
# that file resolves them with scenario_simulation false.
AW_UPSTREAM = {"data_path": "$(env HOME)/autoware_data/ml_models", "planning_module_preset": "default", "control_module_preset": "default",
               "diagnostic_graph_aggregator_graph_path": "$(find-pkg-share autoware_launch)/config/system/diagnostics/autoware-main.yaml",
               "lanelet2_map_file": "lanelet2_map.osm", "pointcloud_map_file": "pointcloud_map.pcd",
               "rviz_config": "$(find-pkg-share autoware_launch)/rviz/autoware.rviz", "rviz_respawn": "true",
               "enable_all_modules_auto_mode": "false"}
SIM_UPSTREAM = {"perception/enable_detection_failure": "true", "dummy_traffic_light_mode": "empty", "perception/use_base_link_z": "true",
                "sensing/visible_range": "300.0", "initial_engage_state": "true",
                "vehicle_info_param_file": "$(find-pkg-share sample_vehicle_description)/config/vehicle_info.param.yaml",
                "raw_vehicle_cmd_converter_param_path":
                    "$(find-pkg-share autoware_launch)/config/vehicle/raw_vehicle_cmd_converter/raw_vehicle_cmd_converter.param.yaml",
                "data_path": "$(env HOME)/autoware_data/ml_models"}


def _include(root: ET.Element, file: str) -> ET.Element:
    found = [i for i in root.iter("include") if i.get("file") == file]
    assert len(found) == 1, file
    return found[0]


def _include_args(inc: ET.Element) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for a in inc.findall("arg"):
        assert a.get("name") not in out, a.get("name")
        out[a.get("name") or ""] = a.get("value") or ""
    return out


def _parents(root: ET.Element) -> Dict[ET.Element, ET.Element]:
    return {c: p for p in root.iter() for c in p}


def test_the_autoware_include_takes_upstreams_arguments_with_2_3s_changes_and_no_other():
    names = UPSTREAM["planning_simulator_include_args"]["autoware.launch.xml"]
    args = _include_args(_include(_xml(LAUNCH_AW), AW_INCLUDE))
    assert set(args) == set(names) | AW_ADDED, (set(names) | AW_ADDED) ^ set(args)
    assert set(AW_CHANGED) | set(AW_UPSTREAM) == set(args) and not set(AW_CHANGED) & set(AW_UPSTREAM)
    assert {k: args[k] for k in AW_CHANGED} == AW_CHANGED
    assert {k: args[k] for k in AW_UPSTREAM} == AW_UPSTREAM


def test_the_simulator_include_takes_upstreams_arguments_with_2_3s_changes_and_no_other():
    names = UPSTREAM["planning_simulator_include_args"]["tier4_simulator_component.launch.xml"]
    args = _include_args(_include(_xml(LAUNCH_AW), SIM_INCLUDE))
    assert set(args) == set(names), set(names) ^ set(args)
    assert set(SIM_CHANGED) | set(SIM_UPSTREAM) == set(args) and not set(SIM_CHANGED) & set(SIM_UPSTREAM)
    assert {k: args[k] for k in SIM_CHANGED} == SIM_CHANGED
    assert {k: args[k] for k in SIM_UPSTREAM} == SIM_UPSTREAM


def test_autoware_launch_sits_in_an_unscoped_group_ahead_of_the_simulators_include():
    root = _xml(LAUNCH_AW)
    parents = _parents(root)
    aw, sim = _include(root, AW_INCLUDE), _include(root, SIM_INCLUDE)
    group = parents[aw]
    assert group.tag == "group" and group.get("scoped") == "false" and parents[group] is root, "planning_simulator.launch.xml:54's form"
    assert [c for c in group] == [aw], "nothing else in that group"
    order = list(root.iter())
    assert order.index(aw) < order.index(sim)
    sim_group = parents[sim]
    assert sim_group.tag == "group" and sim_group.get("scoped") in (None, "true") and parents[sim_group] is root


def test_the_two_lets_and_scenario_simulation_are_set_at_the_top_before_any_include():
    root = _xml(LAUNCH_AW)
    lets = {e.get("name"): e.get("value") for e in root.findall("let")}
    assert lets == {"rviz_initial_pose_auto_fix_target": "vector_map", "gnss_initial_pose_auto_fix_target": "vector_map",
                    "scenario_simulation": "false"}, lets
    kids = list(root)
    first_group = min(i for i, e in enumerate(kids) if e.tag == "group")
    assert all(i < first_group for i, e in enumerate(kids) if e.tag == "let")
    assert not [a for a in root.iter("arg") if a.get("name") == "scenario_simulation" and a.get("default") not in (None, "false")]


def test_the_map_path_is_the_one_required_argument():
    root = _xml(LAUNCH_AW)
    assert [(a.get("name"), a.get("default")) for a in root.findall("arg")] == [("map_path", None)]


def test_twist2accel_is_the_packages_launch_on_the_kinematic_state_under_sim_time():
    root = _xml(LAUNCH_AW)
    inc = _include(root, T2A_INCLUDE)
    assert _include_args(inc) == {"in_odom": "/localization/kinematic_state", "out_accel": "/localization/acceleration"}
    group = _parents(root)[inc]
    assert group.tag == "group" and group.get("scoped") in (None, "true")
    sets = [(s.get("name"), s.get("value")) for s in group.findall("set_parameter")]
    assert sets == [("use_sim_time", "true")]
    assert "accel_lowpass_gain" not in LAUNCH_AW.read_text(encoding="utf-8"), "the package's param file, not the pin's 0.5"


def test_the_autoware_side_starts_no_node_of_its_own_and_three_includes():
    root = _xml(LAUNCH_AW)
    assert not list(root.iter("node")) and len(list(root.iter("include"))) == 3


# =================================================================================================================
# The sensor mapping (2.4)
# =================================================================================================================

def _mapping() -> Dict[str, Any]:
    """The mapping's document: '#' comment lines first, then a JSON body (JSON is YAML, so PyYAML reads the same)."""
    lines = MAPPING.read_text(encoding="utf-8").splitlines()
    body = [i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")]
    assert body and all(lines[i].lstrip().startswith("#") or not lines[i].strip() for i in range(body[0])), "comments only before the body"
    assert not [ln for ln in lines[body[0]:] if ln.lstrip().startswith("#")], "no comment inside the JSON body"
    return json.loads("\n".join(lines[body[0]:]))


def test_the_mapping_enables_exactly_the_imu_and_the_gnss_and_the_two_sets_are_equal():
    m = _mapping()
    assert m["enabled_sensors"] == ["tamagawa/imu_link", "gnss_link"]
    assert set(m["sensor_mappings"]) == set(m["enabled_sensors"])
    assert set(m) == {"default_sensor_kit_name", "sensor_mappings", "normalization", "vehicle_config", "enabled_sensors"}


def test_the_mapping_has_no_lidar_and_no_camera():
    for name, entry in _mapping()["sensor_mappings"].items():
        assert entry["carla_type"] in ("sensor.other.imu", "sensor.other.gnss"), name
        assert not entry["carla_type"].startswith(("sensor.lidar.", "sensor.camera.")), name


def test_the_two_entries_are_the_light_weight_mappings_and_the_rest_upstreams():
    m = _mapping()
    canon = json.dumps({k: m["sensor_mappings"][k] for k in ("tamagawa/imu_link", "gnss_link")}, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest() == UPSTREAM["light_weight_mapping"]["imu_gnss_sha256"]
    assert m["default_sensor_kit_name"] == "carla_sensor_kit_description"
    assert m["normalization"] == {"strip_suffixes": ["_base_link", "_link", "/camera_link"]}


def test_the_wheelbase_is_twice_town10s_base_link_offset():
    wb = _mapping()["vehicle_config"]["wheelbase"]
    assert isinstance(wb, float) and wb == 2 * town10().BASE_LINK_OFFSET_M == 2.53
    assert wb not in (2 * 1.425, 2 * 1.47, 2.85)


# =================================================================================================================
# pubcheck's judge (2.6) on stand-in graphs
# =================================================================================================================

ACT = "tier4_vehicle_msgs/msg/ActuationCommandStamped"
FLAT = "[autoware_carla_interface-1] INFO: Applied a flat steering curve to the ego vehicle.\n"


def _ep(node: str, typ: str = "x/msg/Y", ns: str = "/") -> Dict[str, str]:
    return {"node": node, "namespace": ns, "type": typ}


def good_graph() -> Dict[str, Any]:
    pubs = {
        "/control/command/actuation_cmd": [_ep("autoware_raw_vehicle_cmd_converter", ACT)],
        "/sdv/steershim/actuation_cmd": [_ep("sdv_steershim", ACT)],
        "/sdv/steershim/steering_status_raw": [_ep("autoware_carla_interface", "autoware_vehicle_msgs/msg/SteeringReport")],
        "/vehicle/status/steering_status": [_ep("sdv_steershim", "autoware_vehicle_msgs/msg/SteeringReport")],
        "/localization/kinematic_state": [_ep("autoware_carla_interface", "nav_msgs/msg/Odometry")],
        "/clock": [_ep("autoware_carla_interface", "rosgraph_msgs/msg/Clock")],
        "/localization/acceleration": [_ep("twist2accel", "geometry_msgs/msg/AccelWithCovarianceStamped")],
        "/perception/obstacle_segmentation/pointcloud": [_ep("sdv_empty_cloud", "sensor_msgs/msg/PointCloud2")],
        "/perception/occupancy_grid_map/map": [_ep("occupancy_grid_map_node", "nav_msgs/msg/OccupancyGrid", "/perception/occupancy_grid_map")],
        "/perception/object_recognition/detection/objects": [_ep("autoware_carla_interface", "autoware_perception_msgs/msg/DetectedObjects")],
        "/sensing/imu/tamagawa/imu_raw": [_ep("autoware_carla_interface", "sensor_msgs/msg/Imu")],
        "/rosout": [_ep("autoware_carla_interface", "rcl_interfaces/msg/Log"), _ep("sdv_steershim", "rcl_interfaces/msg/Log")],
    }
    subs = {
        "/control/command/actuation_cmd": [_ep("sdv_steershim", ACT)],
        "/sdv/steershim/actuation_cmd": [_ep("autoware_carla_interface", ACT)],
        "/sdv/steershim/steering_status_raw": [_ep("sdv_steershim", "autoware_vehicle_msgs/msg/SteeringReport")],
        "/clock": [_ep("autoware_raw_vehicle_cmd_converter", "rosgraph_msgs/msg/Clock")],
        "/sensing/lidar/top/pointcloud": [_ep("some_listener", "sensor_msgs/msg/PointCloud2")],
    }
    nodes = [["autoware_carla_interface", "/"], ["autoware_raw_vehicle_cmd_converter", "/"], ["sdv_steershim", "/"],
             ["sdv_empty_cloud", "/"], ["twist2accel", "/"], ["occupancy_grid_map_node", "/perception/occupancy_grid_map"]]
    return {"publishers": pubs, "subscriptions": subs, "nodes": nodes}


# W9 E14 (READ, WP9a's probe): the flattened taxi's steering curve as read -- the client class's default prefix
# (0,1),(10,0.5) (W9 E11, LIB), then the vehicle's own points, the interface's flattening (0,1),(120,1).
E14_READ_BACK = [[0.0, 1.0], [10.0, 0.5], [0.0, 1.0], [120.0, 1.0]]
# W9 E11 (READ, LIB): the shipped taxi's curve as read, the prefix and then its own four points (tests/test_sdv_carla010.py's).
E11_SHIPPED = [[0.0, 1.0], [10.0, 0.5], [0.0, 1.0], [20.0, 0.9], [60.0, 0.8], [120.0, 0.7]]
FLAT_OWN = [[0.0, 1.0], [120.0, 1.0]]
# a world settings read as follow010.py records it (worldtie.READ_BACK's keys); the substep values are synthetic
ATTACH = {"synchronous_mode": True, "fixed_delta_seconds": 0.05, "no_rendering_mode": False, "substepping": True,
          "max_substep_delta_time": 0.01, "max_substeps": 5}


def _take(curve: Optional[List[List[float]]] = None, own: Any = "follow010", refused: Any = None,
          settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """capture.json's keys item 5 reads, as sdv/carla/follow010.py writes them: refused, world_settings (the read at attach
    first, then one at the end) and physics_read (each wheel's maximum angle, the curve as read, and own_points, the second
    value of follow010.curve_problems on that curve unless OWN is given)."""
    curve = E14_READ_BACK if curve is None else curve
    pts = f010().curve_problems(curve)[1] if own == "follow010" else own
    s = dict(ATTACH if settings is None else settings)
    return {"refused": refused, "completed": refused is None,
            "world_settings": [{"at": "attach", "after_frame": None, "settings": s}, {"at": "end", "after_frame": 2400, "settings": s}],
            "physics_read": {"max_steer_angle": [70.0] * 4, "steering_curve": curve, "own_points": pts}}


def test_a_good_graph_with_the_flat_curve_line_passes_every_item():
    assert pc().judge(good_graph(), FLAT) == []
    assert pc().judge(good_graph(), FLAT, _take()) == []


def test_a_take_follow010_accepts_after_the_flattening_passes_item_5_and_the_shipped_curve_fails_item_5_alone():
    """W9 E14's read-back is the curve follow010 accepts (its own points the flattening, after the class default's prefix),
    and item 5 passes it; W9 E11's shipped curve is the one it refuses, and item 5 fails it, naming the own points."""
    problems, own = f010().curve_problems(E14_READ_BACK)
    assert problems == [] and own == FLAT_OWN
    assert pc().judge(good_graph(), FLAT, _take(E14_READ_BACK)) == []
    problems, own = f010().curve_problems(E11_SHIPPED)
    assert problems and own == [[0.0, 1.0], [20.0, 0.9], [60.0, 0.8], [120.0, 0.7]]
    got = pc().judge(good_graph(), FLAT, _take(E11_SHIPPED))
    assert got and {p.split(":", 1)[0] for p in got} == {"item 5"} and all("own steering-curve points" in p for p in got), got


def _with(change):
    g = good_graph()
    change(g)
    return g


CASES = {
    "two-on-steering-status": ("1", lambda g: g["publishers"]["/vehicle/status/steering_status"].append(_ep("autoware_carla_interface"))),
    "interface-report-not-remapped": ("1", lambda g: g["publishers"]["/vehicle/status/steering_status"].__setitem__(
        0, _ep("autoware_carla_interface", "autoware_vehicle_msgs/msg/SteeringReport"))),
    "no-cloud": ("1", lambda g: g["publishers"].pop("/perception/obstacle_segmentation/pointcloud")),
    "no-grid": ("1", lambda g: g["publishers"].pop("/perception/occupancy_grid_map/map")),
    "two-clouds": ("1", lambda g: g["publishers"]["/perception/obstacle_segmentation/pointcloud"].append(_ep("dummy_perception"))),
    "cloud-from-another-node": ("1", lambda g: g["publishers"].__setitem__("/perception/obstacle_segmentation/pointcloud", [_ep("other")])),
    # the cloud node's name under another namespace is another node: the node is named /namespace/name
    "cloud-from-a-namespaced-impostor": ("1", lambda g: g["publishers"].__setitem__(
        "/perception/obstacle_segmentation/pointcloud", [_ep("sdv_empty_cloud", "sensor_msgs/msg/PointCloud2", "/impostor")])),
    "no-acceleration": ("1", lambda g: g["publishers"].pop("/localization/acceleration")),
    "second-clock": ("1", lambda g: g["publishers"]["/clock"].append(_ep("simple_planning_simulator"))),
    "kinematic-state-from-another": ("1", lambda g: g["publishers"].__setitem__("/localization/kinematic_state", [_ep("ekf_localizer")])),
    "clock-from-another": ("1", lambda g: g["publishers"].__setitem__("/clock", [_ep("simple_planning_simulator", "rosgraph_msgs/msg/Clock")])),
    "raw-report-from-another": ("1", lambda g: g["publishers"].__setitem__(
        "/sdv/steershim/steering_status_raw", [_ep("other", "autoware_vehicle_msgs/msg/SteeringReport")])),
    "shim-actuation-from-another": ("1", lambda g: g["publishers"].__setitem__("/sdv/steershim/actuation_cmd", [_ep("other", ACT)])),
    "actuation-from-another": ("1", lambda g: g["publishers"].__setitem__("/control/command/actuation_cmd", [_ep("raw_vehicle_cmd_converter", ACT)])),
    "unequal-actuation-type": ("2", lambda g: g["subscriptions"]["/sdv/steershim/actuation_cmd"].__setitem__(
        0, _ep("autoware_carla_interface", "autoware_vehicle_msgs/msg/ActuationCommandStamped"))),
    "unequal-actuation-type-converter": ("2", lambda g: g["publishers"]["/control/command/actuation_cmd"].__setitem__(
        0, _ep("autoware_raw_vehicle_cmd_converter", "autoware_vehicle_msgs/msg/ActuationCommandStamped"))),
    "interface-on-autowares-actuation": ("3", lambda g: g["subscriptions"]["/control/command/actuation_cmd"].append(
        _ep("autoware_carla_interface", ACT))),
    "interface-not-on-shims-actuation": ("3", lambda g: g["subscriptions"].__setitem__("/sdv/steershim/actuation_cmd", [_ep("x", ACT)])),
    "lidar-publisher": ("4", lambda g: g["publishers"].__setitem__("/sensing/lidar/top/pointcloud_before_sync", [_ep("autoware_carla_interface")])),
    "camera-publisher": ("4", lambda g: g["publishers"].__setitem__("/sensing/camera/CAM_FRONT/image_raw", [_ep("autoware_carla_interface")])),
    "rviz-node": ("4", lambda g: g["nodes"].append(["rviz2", "/"])),
    "rviz-exact": ("4", lambda g: g["nodes"].append(["rviz", "/"])),
    "objects-from-another": ("6", lambda g: g["publishers"]["/perception/object_recognition/detection/objects"].append(_ep("dummy_perception"))),
    "objects-only-from-another": ("6", lambda g: g["publishers"].__setitem__("/perception/object_recognition/detection/objects",
                                                                              [_ep("dummy_perception")])),
    "no-objects": ("6", lambda g: g["publishers"].pop("/perception/object_recognition/detection/objects")),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_item_fails_alone_on_a_graph_that_breaks_it(case):
    item, change = CASES[case]
    problems = pc().judge(_with(change), FLAT)
    assert problems, case
    assert {p.split(":", 1)[0] for p in problems} == {"item " + item}, problems


@pytest.mark.parametrize("topic", [t for t, _w in pc().ONE_PUBLISHER])
@pytest.mark.parametrize("how", ["none", "two"])
def test_each_one_publisher_topic_with_none_or_two_publishers_fails_item_1_alone(topic, how):
    g = good_graph()
    if how == "none":
        g["publishers"].pop(topic)
    else:
        # the second publisher keeps the topic's own type, so that item 2 still holds
        g["publishers"][topic].append(_ep("another_node", g["publishers"][topic][0]["type"]))
    problems = pc().judge(g, FLAT)
    assert problems and {p.split(":", 1)[0] for p in problems} == {"item 1"}, problems


NAMED_PUBLISHERS = [(t, w) for t, w in pc().ONE_PUBLISHER if w is not None]


@pytest.mark.parametrize("topic, who", NAMED_PUBLISHERS, ids=[t.strip("/").replace("/", "-") for t, _w in NAMED_PUBLISHERS])
def test_each_topic_whose_publisher_is_named_fails_item_1_alone_when_its_one_publisher_is_another_node(topic, who):
    """Item 1 names the node beside each topic the project names one for: a single publisher of the topic's own type that is
    another node is not the named one (for every named topic, so that none of the nine names can be dropped unseen)."""
    g = good_graph()
    (only,) = g["publishers"][topic]
    assert only["node"] == who, "the good graph has the named node there"
    g["publishers"][topic] = [_ep("another_node", only["type"])]
    problems = pc().judge(g, FLAT)
    assert problems and {p.split(":", 1)[0] for p in problems} == {"item 1"}, problems
    assert any(topic in p and "another_node" in p for p in problems), problems


def test_the_interface_in_a_namespace_fails_items_1_3_and_6_alone():
    """The interface is /autoware_carla_interface, at the root: the same node name under /carla is another node, so the
    publishers it is named for (item 1), its presence (item 3) and the objects (item 6) fail, and nothing else does."""
    g = good_graph()
    for eps in list(g["publishers"].values()) + list(g["subscriptions"].values()):
        for e in eps:
            if e["node"] == "autoware_carla_interface":
                e["namespace"] = "/carla"
    g["nodes"] = [[n, "/carla" if n == "autoware_carla_interface" else ns] for n, ns in g["nodes"]]
    problems = pc().judge(g, FLAT)
    assert {p.split(":", 1)[0] for p in problems} == {"item 1", "item 3", "item 6"}, problems


def test_a_node_list_holding_the_interface_only_under_another_namespace_fails_item_3_alone():
    """Item 3 asks the node list for /autoware_carla_interface itself: its name under /carla is not it, even where the
    endpoints discovery showed are the root node's."""
    g = good_graph()
    g["nodes"] = [[n, "/carla" if n == "autoware_carla_interface" else ns] for n, ns in g["nodes"]]
    problems = pc().judge(g, FLAT)
    assert {p.split(":", 1)[0] for p in problems} == {"item 3"} and "no node /autoware_carla_interface" in problems[0], problems


def test_a_publisher_under_sensing_lidar_or_camera_is_item_4_only_on_the_topic_or_below_it_never_on_a_longer_name():
    """The forbidden prefixes bind at the slash: /sensing/lidar_top/x is no topic under /sensing/lidar."""
    g = good_graph()
    g["publishers"]["/sensing/lidar_top/x"] = [_ep("x")]
    g["publishers"]["/sensing/camera_front"] = [_ep("x")]
    assert pc().judge(g, FLAT) == []
    for topic in ("/sensing/lidar", "/sensing/camera", "/sensing/camera/CAM_FRONT"):
        g2 = good_graph()
        g2["publishers"][topic] = [_ep("x")]
        problems = pc().judge(g2, FLAT)
        assert problems and {p.split(":", 1)[0] for p in problems} == {"item 4"}, (topic, problems)


def test_the_interface_missing_from_the_graph_fails_item_3_and_the_publisher_items():
    g = good_graph()
    g["nodes"] = [n for n in g["nodes"] if n[0] != "autoware_carla_interface"]
    assert "item 3" in {p.split(":", 1)[0] for p in pc().judge(g, FLAT)}


def test_a_subscriber_under_sensing_lidar_is_no_publisher():
    g = good_graph()
    assert "/sensing/lidar/top/pointcloud" in g["subscriptions"] and pc().judge(g, FLAT) == []


@pytest.mark.parametrize("log, take, why", [
    ("", None, "has no line"),
    ("[autoware_carla_interface-1] WARNING: Failed to flatten the steering curve: no ego\n", None, "flattening failed"),
    (FLAT + "[autoware_carla_interface-1] WARNING: Failed to flatten the steering curve: x\n", None, "flattening failed"),
    ("INFO: Applied a flat steering curve to another vehicle.\n", None, "has no line"),
    (FLAT, lambda: _take([[0.0, 1.0], [10.0, 0.5], [0.0, 1.0], [10.0, 0.5]]), "own steering-curve points"),
    (FLAT, lambda: _take([]), "own steering-curve points"),
    (FLAT, lambda: _take(FLAT_OWN), "own steering-curve points"),
    (FLAT, lambda: _take(E14_READ_BACK[:2]), "own steering-curve points"),
    (FLAT, lambda: _take([[0.0, 1.0], [10.0, 0.5], [0.0, 1.0], [10.0, 0.5]], own=FLAT_OWN), "in the curve as read"),
    (FLAT, lambda: _take(E14_READ_BACK, own=[[0.0, 1.0], [20.0, 0.9], [60.0, 0.8], [120.0, 0.7]]), "follow010.py recorded"),
    (FLAT, lambda: _take(E14_READ_BACK, own=None), "follow010.py recorded"),
    (FLAT, lambda: dict(_take(), physics_read=None), "own steering-curve points"),
], ids=["no-line", "failed", "line-and-failure", "other-line", "curve-not-flat", "curve-empty", "curve-without-prefix",
        "curve-prefix-alone", "read-not-flat-own-flat", "own-not-flat-read-flat", "own-points-absent", "no-physics-read"])
def test_item_5_needs_the_flat_curve_line_and_a_flat_curve_when_the_take_is_given(log, take, why):
    """The curve cases are takes in follow010's shape: the curve as read begins with the client class's default prefix and
    the vehicle's own points follow it; both sources of those points (the read and own_points) must be the flattening. A
    curve without the prefix (the flattening's two points alone) is one follow010 never writes, and fails."""
    problems = pc().judge(good_graph(), log, None if take is None else take())
    assert problems and {p.split(":", 1)[0] for p in problems} == {"item 5"}, problems
    assert any(why in p for p in problems), problems


def test_a_take_follow010_refused_fails_item_5_with_its_reason():
    """follow010.py refuses a take whose world is not synchronous at the step at attach (or at a re-read or the end), or whose
    curve is not flattened, and marks it refused: such a take never passes item 5, even with a flat curve recorded."""
    why = "the world settings read at the end, after frame 2400: the world is not synchronous (synchronous_mode False)"
    problems = pc().judge(good_graph(), FLAT, _take(refused=why))
    assert {p.split(":", 1)[0] for p in problems} == {"item 5"} and any("refused" in p and why in p for p in problems), problems
    assert pc().judge(good_graph(), FLAT, dict(_take(), refused="")) == [], "an empty reason is no refusal (follow010 writes null)"


@pytest.mark.parametrize("change", [
    lambda t: t["world_settings"][0]["settings"].update(synchronous_mode=False),
    lambda t: t["world_settings"][0]["settings"].update(fixed_delta_seconds=0.1),
    lambda t: t["world_settings"][0]["settings"].update(fixed_delta_seconds=0.0505),
    lambda t: t["world_settings"][0]["settings"].update(fixed_delta_seconds=0.050001),
    lambda t: t["world_settings"][0]["settings"].update(fixed_delta_seconds=True),
    lambda t: t["world_settings"][0]["settings"].update(fixed_delta_seconds=float("nan")),
    lambda t: t["world_settings"][0]["settings"].pop("fixed_delta_seconds"),
    lambda t: t["world_settings"][0].update(at="reread"),
    lambda t: t.update(world_settings=[]),
    lambda t: t.update(world_settings=None),
], ids=["asynchronous", "another-step", "step-half-a-millisecond-off", "step-a-microsecond-off", "step-a-boolean", "step-nan", "no-step",
        "first-read-not-at-attach", "no-read", "settings-absent"])
def test_a_take_whose_settings_at_attach_are_not_synchronous_at_the_step_fails_item_5(change):
    """The server's settings as follow010.py reads them at attach: synchronous, at the launch's step (CARLA_STEP_MS / 1000,
    within a double's read-back); the substep is recorded, not judged."""
    t = _take()
    change(t)
    problems = pc().judge(good_graph(), FLAT, t)
    assert problems and {p.split(":", 1)[0] for p in problems} == {"item 5"} and all("attach" in p for p in problems), problems


def test_the_takes_step_is_the_launchs_and_the_contracts():
    ifc = _nodes(_xml(LAUNCH_CARLA))["autoware_carla_interface"]
    assert pc().TAKE_STEP_S == float(_params(ifc)["fixed_delta_seconds"]) == _step_s()
    t = _take(settings=dict(ATTACH, fixed_delta_seconds=0.05000000000000001, max_substeps=7))
    assert pc().judge(good_graph(), FLAT, t) == [], "a double read back across the RPC; the substep is not judged"


def test_the_actuation_type_is_steershims_and_tier4s():
    assert pc().ACTUATION_TYPE_NAME == ACT == pc().type_name(steershim().ACTUATION_TYPE)
    assert pc().SHIM_NODE == _load("carlaif_tests_shim_node", REPO / "sdv" / "steershim" / "shim_node.py").NODE_NAME
    assert pc().CLOUD_NODE == ec().NODE_NAME


def test_a_steershim_whose_actuation_type_is_not_tier4s_fails_item_2_alone(monkeypatch):
    """Item 2 compares the type the graph shows with the steering shim's own ACTUATION_TYPE (loaded by its file, as the
    container loads it): a shim that moved to the autoware_vehicle_msgs type fails item 2 even on a graph of tier4's type."""
    assert pc().judge(good_graph(), FLAT) == []
    monkeypatch.setattr(pc()._steershim(), "ACTUATION_TYPE", ("autoware_vehicle_msgs.msg", "ActuationCommandStamped"))
    problems = pc().judge(good_graph(), FLAT)
    assert problems and {p.split(":", 1)[0] for p in problems} == {"item 2"}, problems
    assert any("the steering shim's ACTUATION_TYPE is autoware_vehicle_msgs/msg/ActuationCommandStamped" in p for p in problems), problems


def test_the_one_publisher_list_is_2_6s_nine_topics():
    assert [t for t, _w in pc().ONE_PUBLISHER] == [
        "/control/command/actuation_cmd", "/sdv/steershim/actuation_cmd", "/sdv/steershim/steering_status_raw",
        "/vehicle/status/steering_status", "/localization/kinematic_state", "/clock", "/localization/acceleration",
        "/perception/obstacle_segmentation/pointcloud", "/perception/occupancy_grid_map/map"]


class _Info:
    def __init__(self, node, ns, typ):
        self.node_name, self.node_namespace, self.topic_type = node, ns, typ


class _GraphNode:
    def __init__(self, g):
        self.g = g

    def get_topic_names_and_types(self):
        return [(t, ["x"]) for t in sorted(set(self.g["publishers"]) | set(self.g["subscriptions"]))]

    def get_publishers_info_by_topic(self, t):
        return [_Info(e["node"], e["namespace"], e["type"]) for e in self.g["publishers"].get(t, [])]

    def get_subscriptions_info_by_topic(self, t):
        return [_Info(e["node"], e["namespace"], e["type"]) for e in self.g["subscriptions"].get(t, [])]

    def get_node_names_and_namespaces(self):
        return [tuple(n) for n in self.g["nodes"]]


def test_read_graph_gathers_every_topics_endpoints_and_the_nodes():
    g = good_graph()
    got = pc().read_graph(_GraphNode(g))
    assert got["publishers"] == g["publishers"] and got["subscriptions"] == g["subscriptions"], "every topic, none left empty"
    assert got["nodes"] == g["nodes"]


def test_pubcheck_main_refuses_an_unreadable_log_with_2(tmp_path, capsys):
    assert pc().main(["--log", str(tmp_path / "absent.txt")]) == 2


def _install_rclpy_graph(monkeypatch, graph):
    """rclpy and rclpy.node as pubcheck.main uses them: init (the arguments are kept), spin_once and try_shutdown (nothing),
    and a Node that is a _GraphNode over a copy of GRAPH taken when the node is constructed, with destroy_node (counted).
    Returns the dict that records the calls."""
    calls = {"init": None, "node": None, "destroyed": 0}
    rclpy = types.ModuleType("rclpy")
    node_mod = types.ModuleType("rclpy.node")

    def init(args=None):
        calls["init"] = args

    def spin_once(node, timeout_sec=None):
        pass

    def try_shutdown():
        pass

    class StandInNode(_GraphNode):
        def __init__(self, name, **kw):
            _GraphNode.__init__(self, json.loads(json.dumps(graph)))
            calls["node"] = (name, kw)

        def destroy_node(self):
            calls["destroyed"] += 1

    rclpy.init, rclpy.spin_once, rclpy.try_shutdown, rclpy.node = init, spin_once, try_shutdown, node_mod
    node_mod.Node = StandInNode
    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.node", node_mod)
    return calls


def test_pubcheck_main_judges_the_stand_in_graph_and_writes_its_record(monkeypatch, tmp_path):
    log = tmp_path / "log.txt"
    log.write_text(FLAT, encoding="utf-8")
    calls = _install_rclpy_graph(monkeypatch, good_graph())
    out = tmp_path / "r.json"
    rc = pc().main(["--log", str(log), "--settle-s", "0", "--out", str(out)])
    assert rc == 0
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["ok"] is True and record["problems"] == []
    assert record["one_publisher"]["/clock"] == ["/autoware_carla_interface"]
    assert record["one_publisher"].get("/perception/object_recognition/detection/objects") == ["/autoware_carla_interface"], record
    assert record["capture_judged"] is False
    assert calls["init"] == sys.argv[:1] and calls["node"][0] == pc().NODE_NAME and calls["destroyed"] == 1
    # no parameter services, and the context's global arguments (a remap or a parameter of the container's command) ignored
    assert calls["node"][1] == {"start_parameter_services": False, "use_global_arguments": False}
    assert pc().SETTLE_S == 5.0, "the design value: discovery on one host's loopback"
    # the same run on a graph with a second publisher on Autoware's steering report
    g = good_graph()
    g["publishers"]["/vehicle/status/steering_status"].append(_ep("another_node", "autoware_vehicle_msgs/msg/SteeringReport"))
    _install_rclpy_graph(monkeypatch, g)
    out2 = tmp_path / "r2.json"
    rc = pc().main(["--log", str(log), "--settle-s", "0", "--out", str(out2)])
    assert rc == 1
    record = json.loads(out2.read_text(encoding="utf-8"))
    assert record["ok"] is False and record["problems"] and all(p.startswith("item 1") for p in record["problems"]), record


def test_pubcheck_main_with_a_take_follow010_accepted_passes_and_records_the_settings_at_attach(monkeypatch, tmp_path):
    """A take given with --capture: a take in follow010's shape, flattened, passes; the record keeps the
    settings follow010 read at attach (the substep among them) and says the take was judged."""
    log = tmp_path / "log.txt"
    log.write_text(FLAT, encoding="utf-8")
    cap = tmp_path / "capture.json"
    cap.write_text(json.dumps(_take()), encoding="utf-8")
    _install_rclpy_graph(monkeypatch, good_graph())
    out = tmp_path / "r.json"
    assert pc().main(["--log", str(log), "--capture", str(cap), "--settle-s", "0", "--out", str(out)]) == 0
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["ok"] is True and record["capture_judged"] is True and record["take_attach_settings"] == ATTACH, record
    assert pc().main(["--log", str(log), "--settle-s", "0", "--out", str(tmp_path / "r2.json")]) == 0
    assert json.loads((tmp_path / "r2.json").read_text(encoding="utf-8"))["take_attach_settings"] is None


@pytest.mark.parametrize("text", ["[1, 2]", "null", "3", '"capture.json"', "", "{"], ids=["list", "null", "number", "string", "empty", "truncated"])
def test_pubcheck_main_refuses_with_2_a_capture_that_is_not_a_json_object(monkeypatch, tmp_path, capsys, text):
    """A --capture that cannot be read as the take's JSON object is the refusal 2 (not judged), never a traceback's 1 that
    the runbook would read as a failed item, and never a silent pass for a `null` that reads as no take; rclpy is not reached."""
    log = tmp_path / "log.txt"
    log.write_text(FLAT, encoding="utf-8")
    cap = tmp_path / "capture.json"
    cap.write_text(text, encoding="utf-8")
    calls = _install_rclpy_graph(monkeypatch, good_graph())
    out = tmp_path / "r.json"
    assert pc().main(["--log", str(log), "--capture", str(cap), "--settle-s", "0", "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "take" in err, err
    assert calls["init"] is None and calls["node"] is None and not out.exists(), "nothing was judged or written"


@pytest.mark.parametrize("where", ["init", "node", "graph", "spin"])
def test_pubcheck_main_refuses_with_2_when_rclpy_cannot_start_or_the_graph_cannot_be_read(monkeypatch, tmp_path, capsys, where):
    """No RMW, a bad ROS_DOMAIN_ID, a node that cannot be made or a graph read that fails: no item was judged, so the exit is
    the refusal 2, never the 1 the runbook reads as a failed item (an uncaught exception would exit 1)."""
    log = tmp_path / "log.txt"
    log.write_text(FLAT, encoding="utf-8")
    calls = _install_rclpy_graph(monkeypatch, good_graph())
    rclpy, node_mod = sys.modules["rclpy"], sys.modules["rclpy.node"]

    def boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("rcl_init failed: the stand-in's %s" % where)
    if where == "init":
        monkeypatch.setattr(rclpy, "init", boom)
    elif where == "node":
        monkeypatch.setattr(node_mod, "Node", boom)
    elif where == "spin":
        monkeypatch.setattr(rclpy, "spin_once", boom)
    else:
        monkeypatch.setattr(node_mod.Node, "get_topic_names_and_types", boom)
    out = tmp_path / "r.json"
    assert pc().main(["--log", str(log), "--settle-s", "0.2", "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "rclpy could not start or the graph could not be read" in err and where in err, err
    assert not out.exists()
    assert calls["destroyed"] == (1 if where in ("spin", "graph") else 0), "a node that was made is destroyed"


def test_pubcheck_main_refuses_with_2_when_its_record_cannot_be_written(monkeypatch, tmp_path, capsys):
    """A clean judgement whose --out cannot be written (here a directory) is a refusal 2, not an escaped OSError's 1."""
    log = tmp_path / "log.txt"
    log.write_text(FLAT, encoding="utf-8")
    _install_rclpy_graph(monkeypatch, good_graph())
    assert pc().main(["--log", str(log), "--settle-s", "0", "--out", str(tmp_path)]) == 2
    assert "the record cannot be written" in capsys.readouterr().err


# =================================================================================================================
# The two small nodes (section 1 item 11; section 9 item 1) on a stand-in rclpy
# =================================================================================================================

class _Msg:
    """A stand-in message: attributes given as keywords, a header with a stamp and a frame."""

    def __init__(self, **kw: Any) -> None:
        self.header = types.SimpleNamespace(stamp=None, frame_id="")
        self.fields: List[Any] = []
        self.data: Any = [1, 2, 3]
        self.height, self.width = 7, 7
        self.__dict__.update(kw)


class _Field:
    FLOAT32 = 7

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def test_the_empty_cloud_has_no_point_its_frame_base_link_and_xyz_fields():
    m = ec().fill_cloud(_Msg(), _Field, "STAMP")
    assert (m.height, m.width, list(m.data), m.row_step) == (0, 0, [], 0)
    assert m.header.frame_id == "base_link" and m.header.stamp == "STAMP"
    assert [(f.name, f.offset, f.datatype, f.count) for f in m.fields] == [("x", 0, 7, 1), ("y", 4, 7, 1), ("z", 8, 7, 1)]
    assert m.point_step == 12 and m.is_dense is True and m.is_bigendian is False
    assert ec().cloud_problems(m) == []


def test_the_empty_clouds_topic_is_the_obstacle_cloud_never_the_grids_and_its_rate_10_hz_of_sim_time():
    e = ec()
    assert e.TOPIC == "/perception/obstacle_segmentation/pointcloud" != "/perception/occupancy_grid_map/map"
    assert e.PERIOD_S == 0.1 and e.FRAME_ID == "base_link" and e.NODE_NAME == "sdv_empty_cloud"


@pytest.mark.parametrize("change, why", [(lambda m: setattr(m, "width", 1), "point"), (lambda m: setattr(m, "data", [0] * 12), "point"),
                                         (lambda m: setattr(m.header, "frame_id", "map"), "frame")], ids=["width", "data", "frame"])
def test_a_cloud_with_a_point_or_another_frame_is_named(change, why):
    m = ec().fill_cloud(_Msg(), _Field, "S")
    change(m)
    assert any(why in p for p in ec().cloud_problems(m))


class FakeRos:
    """rclpy as the two nodes use it: init, spin (runs each timer's callback `ticks` times, delivering `clocks` to the
    /clock subscription first, then raises KeyboardInterrupt), try_shutdown; node.Node with a publisher, a subscription,
    timers and a clock; parameter.Parameter; qos; clock.Clock and ClockType; the two message packages."""

    def __init__(self, ticks: int = 2, clocks=(), events=None) -> None:
        self.ticks, self.clocks = ticks, list(clocks)
        self.events = None if events is None else list(events)     # in order: a /clock message, "tick" (every timer once), or a hook
        self.pubs: List[Any] = []
        self.subs: List[Any] = []
        self.timers: List[Any] = []
        self.published: List[Any] = []
        self.node_kwargs: Any = None
        self.init_args: Any = None

    def modules(self):
        ros = self
        rclpy = types.ModuleType("rclpy")
        node_mod = types.ModuleType("rclpy.node")
        qos = types.ModuleType("rclpy.qos")
        param = types.ModuleType("rclpy.parameter")
        clock = types.ModuleType("rclpy.clock")
        executors = types.ModuleType("rclpy.executors")

        class ExternalShutdownException(Exception):
            pass

        class Parameter:
            class Type(enum.Enum):
                BOOL = 1

            def __init__(self, name, type_=None, value=None):
                self.name, self.type_, self.value = name, type_, value

        class ClockType(enum.Enum):
            ROS_TIME = 1
            STEADY_TIME = 2

        class Clock:
            def __init__(self, clock_type=None):
                self.clock_type = clock_type

        class _Now:
            def to_msg(self):
                return "SIM-STAMP"

        class _NodeClock:
            def now(self):
                return _Now()

        class Publisher:
            def __init__(self, topic):
                self.topic = topic

            def publish(self, msg):
                ros.published.append((self.topic, msg))

        class Node:
            def __init__(self, name, **kw):
                ros.node_kwargs = dict(kw, name=name)
                self.cb: Dict[str, Any] = {}

            def create_publisher(self, t, topic, q):
                ros.pubs.append((t, topic, q))
                return Publisher(topic)

            def create_subscription(self, t, topic, cb, q):
                ros.subs.append((t, topic, q))
                self.cb[topic] = cb

            def create_timer(self, period, cb, clock=None):
                ros.timers.append((period, clock))
                self.cb.setdefault("timers", []).append(cb)

            def get_clock(self):
                return _NodeClock()

            def get_logger(self):
                return types.SimpleNamespace(error=print, info=print, warning=print)

            def destroy_node(self):
                pass

        class QoSProfile:
            def __init__(self, depth=None, history=None, reliability=None, durability=None):
                self.depth, self.history, self.reliability, self.durability = depth, history, reliability, durability

        def spin(n):
            if ros.events is not None:
                for ev in ros.events:
                    if callable(ev):            # a hook between events (a test reading what is on disk so far)
                        ev()
                        continue
                    if ev != "tick":
                        n.cb["/clock"](ev)
                        continue
                    for cb in n.cb.get("timers", []):
                        cb()
                raise KeyboardInterrupt
            for c in ros.clocks:
                n.cb["/clock"](c)
            for _ in range(ros.ticks):
                for cb in n.cb.get("timers", []):
                    cb()
            raise KeyboardInterrupt

        def init(args=None):
            ros.init_args = args

        rclpy.init, rclpy.spin, rclpy.try_shutdown = init, spin, (lambda: None)
        rclpy.node, rclpy.qos, rclpy.parameter, rclpy.clock, rclpy.executors = node_mod, qos, param, clock, executors
        node_mod.Node, param.Parameter, clock.Clock, clock.ClockType = Node, Parameter, Clock, ClockType
        executors.ExternalShutdownException = ExternalShutdownException
        qos.QoSProfile = QoSProfile
        qos.ReliabilityPolicy = enum.Enum("ReliabilityPolicy", "RELIABLE BEST_EFFORT")
        qos.HistoryPolicy = enum.Enum("HistoryPolicy", "KEEP_LAST KEEP_ALL")
        qos.DurabilityPolicy = enum.Enum("DurabilityPolicy", "VOLATILE TRANSIENT_LOCAL")
        sm = types.ModuleType("sensor_msgs.msg")
        sm.PointCloud2, sm.PointField = _Msg, _Field
        rg = types.ModuleType("rosgraph_msgs.msg")
        rg.Clock = type("Clock", (), {})
        out = {"rclpy": rclpy, "rclpy.node": node_mod, "rclpy.qos": qos, "rclpy.parameter": param, "rclpy.clock": clock,
               "rclpy.executors": executors, "sensor_msgs.msg": sm, "rosgraph_msgs.msg": rg}
        for pkg in ("sensor_msgs", "rosgraph_msgs"):
            p = types.ModuleType(pkg)
            p.msg = out[pkg + ".msg"]
            out[pkg] = p
        return out


def _install(monkeypatch, ros: FakeRos) -> None:
    for name, mod in ros.modules().items():
        monkeypatch.setitem(sys.modules, name, mod)


def _clock(sec: int, nanosec: int) -> Any:
    return types.SimpleNamespace(clock=types.SimpleNamespace(sec=sec, nanosec=nanosec))


def test_empty_cloud_main_publishes_on_its_one_topic_reliable_under_sim_time_on_a_sim_time_timer(monkeypatch):
    ros = FakeRos(ticks=3)
    _install(monkeypatch, ros)
    assert ec().main([]) == 0
    assert [topic for _t, topic, _q in ros.pubs] == ["/perception/obstacle_segmentation/pointcloud"]
    q = ros.pubs[0][2]
    assert (q.reliability.name, q.history.name, q.depth, q.durability.name) == ("RELIABLE", "KEEP_LAST", 1, "VOLATILE")
    assert ros.timers == [(0.1, None)], "the node's own clock: ROS time, sim time once use_sim_time is set"
    (over,) = ros.node_kwargs["parameter_overrides"]
    assert (over.name, over.value) == ("use_sim_time", True)
    assert ros.node_kwargs["use_global_arguments"] is False and ros.init_args == sys.argv[:1]
    assert ros.node_kwargs["start_parameter_services"] is False
    assert len(ros.published) == 3 and all(t == ec().TOPIC for t, _m in ros.published)
    for _t, m in ros.published:
        assert (m.width, m.height, list(m.data)) == (0, 0, []) and m.header.stamp == "SIM-STAMP" and m.header.frame_id == "base_link"
    assert ros.subs == []


def test_empty_cloud_main_never_publishes_a_message_cloud_problems_refuses(monkeypatch, capsys):
    """A message fill_cloud would make with a point (here fill_cloud replaced, on the module alone, by one that leaves a
    width of 1) is named by cloud_problems at each tick, logged as refused and never published."""
    ros = FakeRos(ticks=2)
    _install(monkeypatch, ros)
    real = ec().fill_cloud

    def with_a_point(msg: Any, field_cls: Any, stamp: Any) -> Any:
        m = real(msg, field_cls, stamp)
        m.width = 1
        return m
    monkeypatch.setattr(ec(), "fill_cloud", with_a_point)
    assert ec().main([]) == 0
    assert ros.published == [], ros.published
    assert capsys.readouterr().out.count("empty_cloud: refused to publish: the cloud holds a point") == 2


def test_the_sampler_pairs_the_last_clock_with_its_monotonic_receipt_and_writes_nothing_before_one():
    s = cs().Sampler()
    assert s.line(500) is None
    s.on_clock(cs().sim_ns(_clock(12, 500)), 1000)
    s.on_clock(cs().sim_ns(_clock(12, 50_000_500)), 2000)
    assert s.line(2500) == "12050000500 2000 2500\n" and s.line(3500) == "12050000500 2000 3500\n"


def test_a_stalled_clock_reads_as_a_held_receipt_column_while_the_tick_column_advances():
    """A stall: /clock at 10.000 s received at mono 1000, nothing for three ticks, then 10.050 s received at 4000. In two
    columns the three held lines read as three samples of one instant a second apart, and a claim at mono 2500 would
    interpolate to 10.025 s; with the tick's own CLOCK_MONOTONIC beside the receipt the held lines show the clock standing
    still (the receipt column equal while the tick column advances), so a reader holds 10.000 s there."""
    s = cs().Sampler()
    s.on_clock(10_000_000_000, 1000)
    held = [s.line(t) for t in (2000, 3000, 3999)]
    s.on_clock(10_050_000_000, 4000)
    rows = [tuple(int(x) for x in str(ln).split()) for ln in held + [s.line(4100)]]
    assert rows == [(10_000_000_000, 1000, 2000), (10_000_000_000, 1000, 3000), (10_000_000_000, 1000, 3999),
                    (10_050_000_000, 4000, 4100)]
    assert cs().HEADER.startswith("# clock_sampler 2: SIM_NS MONO_RECEIPT_NS MONO_TICK_NS") and cs().HEADER.endswith("\n")


def test_clock_sampler_main_subscribes_clock_with_its_publishers_qos_and_writes_each_second_by_a_steady_timer(monkeypatch, tmp_path):
    """Each line SIM_NS MONO_RECEIPT_NS MONO_TICK_NS: the last /clock with time.monotonic_ns at its receipt, and
    time.monotonic_ns when the steady timer wrote the line; across a stall the receipt column holds. The header is on disk
    (read by another handle while the file is still open) before the first /clock, and each line as soon as its tick has
    written it. The node has no parameter services and ignores the context's global arguments; rclpy is given the
    program's name alone. Only the module's own `time` is replaced, never the time module every thread shares."""
    out = tmp_path / "clock.txt"
    on_disk = []

    def read_disk():
        on_disk.append(out.read_text(encoding="ascii").splitlines())
    ros = FakeRos(events=[read_disk, _clock(10, 0), "tick", read_disk, "tick", read_disk, "tick", read_disk, _clock(10, 50_000_000), "tick",
                          read_disk])
    _install(monkeypatch, ros)
    mono = iter([1000, 2000, 3000, 4000, 4500, 5000])     # in order: receipt, three ticks, receipt, tick
    monkeypatch.setattr(cs(), "time", types.SimpleNamespace(monotonic_ns=lambda: next(mono)))
    assert cs().main(["--out", str(out)]) == 0
    assert ros.node_kwargs["start_parameter_services"] is False and ros.node_kwargs["use_global_arguments"] is False
    assert ros.init_args == sys.argv[:1]
    ((_t, topic, q),) = ros.subs
    assert topic == "/clock" and (q.reliability.name, q.history.name, q.depth, q.durability.name) == ("RELIABLE", "KEEP_LAST", 10, "VOLATILE")
    ((period, clock),) = ros.timers
    assert period == 1.0 and clock.clock_type.name == "STEADY_TIME"
    (over,) = ros.node_kwargs["parameter_overrides"]
    assert (over.name, over.value) == ("use_sim_time", False), "the sampler keeps its own clock"
    lines = out.read_text(encoding="ascii").splitlines()
    assert lines[0] + "\n" == cs().HEADER
    want = ["10000000000 1000 2000", "10000000000 1000 3000", "10000000000 1000 4000", "10050000000 4500 5000"]
    assert lines[1:] == want, lines
    assert on_disk[0] == [cs().HEADER.rstrip("\n")], ("the header is on disk before the first /clock", on_disk)
    later = on_disk[1:]
    assert [d[0] + "\n" for d in later] == [cs().HEADER] * 4 and [d[1:] for d in later] == [want[:k] for k in (1, 2, 3, 4)], on_disk
    assert ros.pubs == []


def test_clock_sampler_refuses_an_out_file_that_exists(monkeypatch, tmp_path):
    _install(monkeypatch, FakeRos())
    out = tmp_path / "clock.txt"
    out.write_text("kept\n", encoding="ascii")
    assert cs().main(["--out", str(out)]) == 2 and out.read_text(encoding="ascii") == "kept\n"


# =================================================================================================================
# The directory
# =================================================================================================================

def test_no_module_here_shares_a_name_with_a_module_ci_type_checks_beside_it():
    mine = {p.stem for p in CARLAIF.glob("*.py")} - {"build_image"}
    assert mine == {"pubcheck", "empty_cloud", "clock_sampler"} and not (CARLAIF / "__init__.py").exists()
    others = set()
    for d in ("scripts/ci", "scripts/aws", "scripts/twin", "tests", "sdv/connector", "sdv/cloud", "sdv/ota", "sdv/carla", "sdv/feeder",
              "sdv/ctl", "sdv/rosvss", "sdv/steershim", "sdv/drill"):
        if (REPO / d).is_dir():
            others |= {p.stem for p in (REPO / d).rglob("*.py")}
    assert not mine & others, mine & others


def test_the_directory_holds_2_2s_files_and_no_upstream_file():
    files = sorted(str(p.relative_to(CARLAIF)).replace("\\", "/") for p in CARLAIF.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    assert files == ["Dockerfile", "README.md", "build_image.py", "clock_sampler.py", "config/sensor_mapping_sdv.yaml", "empty_cloud.py",
                     "launch/sdv_autoware.launch.xml", "launch/sdv_carla.launch.xml", "pin.json", "pubcheck.py", "wheel.lock"]
    blobs = {e["blob"] for e in _pin_doc()["entries"]}
    assert not [f for f in files if _git_blob((CARLAIF / f).read_bytes()) in blobs], "no file of the pin's tree is vendored"
