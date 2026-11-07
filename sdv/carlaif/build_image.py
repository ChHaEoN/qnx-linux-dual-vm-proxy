#!/usr/bin/env python3
"""build_image.py -- build CARLA 0.10.0's ROS 2 interface image at the pinned commit, sdv-carlaif (sdv/carlaif; SDV Phase
8 WP9 P2), and read its proof.

The WP9 specification's 2.2 and section 1's items 1 and 13 (the project's local design
notes; not in this tree). Run in WSL, from the repo root, where Docker Engine runs:

    python3 sdv/carlaif/build_image.py build --source DIR --wheels DIR [--proof]
    python3 sdv/carlaif/build_image.py proof [--image ID]          (default: images.json's carlaif.amd64.id)

THE INPUTS. --source is a copy of simulator/autoware_carla_interface at the pin (PIN_COMMIT, its tree PIN_TREE): every file
pin.json lists, each checked by its git blob id computed from its bytes with no filters; a file the list does not hold, a
file it holds missing, or one whose blob id differs is refused, and pin.json itself is refused unless its list (each
entry's path, mode and blob id) hashes back to the tree id. The one file pin.json leaves out is checked if present and never
staged. --wheels is a folder holding the wheel wheel.lock names; its sha256 must be the lock's. Nothing is fetched: the
source and the wheel are local copies, the base must already be in the image store (read with `docker image inspect`
by images.json's autoware index digest), and the build runs with --pull=false and --network=none.

THE BUILD, on sdv/rosvss/build_image.py's pattern, amd64 only. It stages a context outside the repo (under
~/sdv-cache/carlaif-build/, SDV_CACHE moves the root; removed after the build): the Dockerfile, wheel.lock,
sdv/aw/aw-entrypoint.sh as aw-entrypoint.sh, wheels/<the wheel> (hashed again as staged) and
src/autoware_carla_interface/ with the pin's files, each with its pin mode (0755 for 100755, else 0644) and its blob id
checked again as staged. Before building it checks that the Dockerfile's one FROM (its keyword read in any case and after
leading whitespace, as docker reads it) is the Autoware image by images.json's autoware.amd64 manifest digest (never a
tag) and that no other line names an image (a COPY or ADD --from=, a RUN --mount from= that is not a stage name, a
`# syntax=` directive), and reads the host check (sdv/aw/hostcheck.sh, 2.12); a reading that fails stops it. It builds
with `docker build -q --provenance=false --sbom=false --pull=false --network=none` (check_build_argv refuses an argument
vector with provenance or an SBOM other than false, or any attestation), with the four labels as build arguments. It
reads the built image's config digest from a `docker save` stream of its ID (the manifest and the config each checked
against its digest by sdv/arm64/a64scan.py's reader; the config's platform linux/amd64) and refuses a config whose
entrypoint is not the project's, whose user is not aw or whose four labels are not the ones given, before anything is
proved or pinned. It reads the host check again and compares the two readings; a build that fails after the first
reading reads it again too. It prints one JSON record: the image ID, the config digest, the tag, the labels, the base,
the build's argument vector, the sha256 of the Dockerfile and of every staged project file, the host check's two
readings, and `pin`, the carlaif entry for sdv/stack/images.json ({"amd64": {id, config_digest, tag, lock}, "labels":
{...}}), entered by hand. An image this tag named before and the rebuild left untagged is removed (the tag is this
script's alone), unless it is the one images.json's carlaif.amd64 pins, which the runs take by its ID and which stays
until a re-pin; nothing else is pruned.

THE PROOF (--proof, or the proof command on an image already built), read inside the image by its ID under the project's
flags (--rm --network none --pull never --platform linux/amd64 --user aw --cap-drop ALL --security-opt no-new-privileges
--entrypoint /sdv-aw/aw-entrypoint.sh, the tree's sdv and sdv/aw mounted read-only) and with the exact environment the
launch step gives (LAUNCH_ENV: the overlay sourced, the venv's bin first): which python3 runs, carla's version and module,
the interface's module and share, the node's module imported, the package's version from its package.xml, the 0.52.0
copy's prefix, the node script's first line; proof_problems judges them. Then `ros2 launch --print` of each launch file
(a parse only; no node starts), with print_args' arguments (town10.py's t1 spawn point and map folder name), its output
kept in the record. The record is a functional result: it stays with the run, never in a tree file.

Standard library only (and sdv/arm64/a64scan.py, loaded by its file, for the save stream). Does not demonstrate: that the
interface drives a server or the taxi, that ROS's launch accepts the launch files beyond a parse, or anything on an arm64
host (no arm64 image is built: no arm64 client wheel exists).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
IMAGES_FILE = REPO / "sdv" / "stack" / "images.json"
A64SCAN_FILE = REPO / "sdv" / "arm64" / "a64scan.py"
HOSTCHECK = REPO / "sdv" / "aw" / "hostcheck.sh"
ENTRYPOINT_SRC = REPO / "sdv" / "aw" / "aw-entrypoint.sh"

TAG = "sdv-carlaif:local"
DOCKERFILE = HERE / "Dockerfile"
LOCK = HERE / "wheel.lock"
LOCK_REL = "sdv/carlaif/wheel.lock"
PIN_FILE = HERE / "pin.json"
BASE_REPO = "ghcr.io/autowarefoundation/autoware"
FROM_RE = re.compile(r"^\s*FROM(?:\s(.*))?$", re.IGNORECASE)     # a FROM instruction as docker reads one; group 1: what follows
# Where else a Dockerfile names an image: COPY/ADD --from=X, RUN --mount=...,from=X, a `# syntax=` parser directive.
FROM_OPT_RE = re.compile(r"(?:^|\s)--from[=\s]+(\S+)", re.IGNORECASE)
MOUNT_RE = re.compile(r"(?:^|\s)--mount[=\s]+(\S+)", re.IGNORECASE)
SYNTAX_RE = re.compile(r"^\s*#\s*syntax\s*=\s*(\S*)", re.IGNORECASE)
STAGE_RE = re.compile(r"^\s*FROM\s+\S+\s+AS\s+(\S+)\s*$", re.IGNORECASE)
ENTRYPOINT_IN_IMAGE = "/sdv-aw/aw-entrypoint.sh"           # the Dockerfile's COPY target and ENTRYPOINT
IMAGE_USER = "aw"                                           # the Dockerfile's USER: the base's own user (uid 1000)
# The pin (the specification's section 1 item 13, D2): autoware_universe's commit and the package's tree at it.
PIN_COMMIT = "94b8fbd3a8e4df661568270494369b06eb913d66"
PIN_TREE = "472ed962c44bdd6da71d32a5b8253a7fee6a5fc4"
PACKAGE = "autoware_carla_interface"
PACKAGE_VERSION = "0.53.0"                                  # the pin's package.xml (its setup.py's 0.50.0 is unused: ament_cmake)
IMAGE_COPY_VERSION = "0.52.0"                               # the base's own copy, under /opt/autoware
OVERLAY = "/opt/sdv-carlaif/install"                        # colcon's install base for the one package
VENV = "/opt/sdv-carlaif/venv"
WHEEL_VERSION = "0.10.0"
# What every command of this image is run under: the overlay sourced (after the entrypoint's two setup files) and the
# venv's bin first, so the node's `#!/usr/bin/env python3` is the venv's Python, which sees carla and, through the
# PYTHONPATH the setup files set, the ROS packages.
LAUNCH_ENV = "source %s/local_setup.bash && export PATH=%s/bin:$PATH" % (OVERLAY, VENV)
SRC_PREFIX = "src/%s/" % PACKAGE                            # where the pin's files are staged in the context
MODES = {"100644": 0o644, "100755": 0o755}
# What sdv.carlaif.sources_sha256 covers: the project files the build stages beside the pin's (the pin's are covered by
# their blob ids, through pin.json), in path order.
PROJECT_SOURCES = ("sdv/aw/aw-entrypoint.sh", "sdv/carlaif/pin.json", "sdv/carlaif/wheel.lock")
LABEL_KEYS = ("sdv.carlaif.base_digest", "sdv.carlaif.pin", "sdv.carlaif.sources_sha256", "sdv.carlaif.wheel_sha256")
CACHE = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser()
SAVE_BLOB_LIMIT = 4 << 20       # a save stream's blobs kept to read the manifest and its config (sdv/stack/stack.py's bound)
LOCK_RE = re.compile(r"^([a-z0-9-]+)==(\S+) \\\n\s+--hash=sha256:([0-9a-f]{64})\n\s+# (\S+\.whl)$", re.M)
# The proof's reads (2.2), by /usr/bin/env python3 under LAUNCH_ENV: one JSON line between two marker lines.
# The node's module is imported (a module import: carla_ros creates no node at import), so that its own top-level imports
# (carla, cv2, cv_bridge, transforms3d, the message packages) run under the venv's python; find_spec runs the package's
# __init__ only.
PROOF_PY = r"""
import importlib, importlib.metadata, importlib.util, json, os, re, shutil, sys
out = {"python3": shutil.which("python3"), "executable": sys.executable}
import carla
out["carla_file"] = carla.__file__
out["carla_version"] = importlib.metadata.version("carla")
try:
    out["client_version"] = carla.Client("127.0.0.1", 2000).get_client_version()
except Exception as err:
    out["client_version"] = "error: %s" % err
import autoware_carla_interface
out["interface_file"] = autoware_carla_interface.__file__
out["carla_ros_file"] = importlib.util.find_spec("autoware_carla_interface.carla_ros").origin
try:
    importlib.import_module("autoware_carla_interface.carla_ros")
    out["carla_ros_imported"] = True
except Exception as err:
    out["carla_ros_imported"] = "error: %s: %s" % (type(err).__name__, err)
from ament_index_python.packages import get_package_prefix, get_package_share_directory
out["share"] = get_package_share_directory("autoware_carla_interface")
out["prefix"] = get_package_prefix("autoware_carla_interface")
xml = open(os.path.join(out["share"], "package.xml"), encoding="utf-8").read()
out["package_version"] = re.search(r"<version>([^<]*)</version>", xml).group(1)
copy = "/opt/autoware/autoware_carla_interface"
out["image_copy_prefix"] = copy if os.path.isdir(copy) else None
cx = os.path.join(copy, "share", "autoware_carla_interface", "package.xml")
out["image_copy_version"] = re.search(r"<version>([^<]*)</version>", open(cx, encoding="utf-8").read()).group(1) if os.path.isfile(cx) else None
script = os.path.join(out["prefix"], "lib", "autoware_carla_interface", "autoware_carla_interface")
out["script_shebang"] = open(script, encoding="utf-8").readline().rstrip("\n")
print("== reads")
print(json.dumps(out, sort_keys=True))
print("== end")
"""
LAUNCH_FILES = ("sdv_carla.launch.xml", "sdv_autoware.launch.xml")
TOWN10_FILE = REPO / "sdv" / "carla" / "town10.py"
PROOF_SCENARIO = "t1"                                       # R0's scenario: the parse takes its start's spawn point


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_id(data: bytes) -> str:
    """git's blob id of the bytes as they are (no filters: no line-ending or attribute conversion)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def tree_id(entries: Sequence[Dict[str, str]], prefix: str = "") -> str:
    """git's tree id of a flat list of blob entries (path, mode, blob), each sub-tree built from the paths: every entry's
    mode, name and raw id, in git's order (a sub-tree's name sorts as if it ended in '/')."""
    kids: Dict[str, Optional[Dict[str, str]]] = {}
    for e in entries:
        if e["path"].startswith(prefix):
            head, _sep, rest = e["path"][len(prefix):].partition("/")
            kids[head + "/" if rest else head] = None if rest else e
    body = b""
    for key in sorted(kids):
        entry = kids[key]
        if entry is None:
            name, mode, sha = key[:-1], "40000", tree_id(entries, prefix + key)
        else:
            name, mode, sha = key, entry["mode"], entry["blob"]
        body += mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(sha)
    return hashlib.sha1(b"tree %d\0" % len(body) + body).hexdigest()


def _safe_rel(rel: str) -> bool:
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and "\\" not in rel and all(p not in ("", ".", "..") for p in parts)


def load_pin(path: Optional[Path] = None) -> Dict[str, Any]:
    """pin.json, refused unless it names PIN_COMMIT and PIN_TREE, every entry is a relative path with a blob mode and a blob
    id, no path twice, left_out names entries of the list, and the list hashes back to the tree id."""
    p = path if path is not None else PIN_FILE
    try:
        doc = json.loads(Path(p).read_text(encoding="ascii"))
    except (OSError, ValueError) as err:
        raise BuildError("pin.json %s cannot be read: %s" % (p, err)) from None
    if not isinstance(doc, dict) or (doc.get("commit"), doc.get("tree")) != (PIN_COMMIT, PIN_TREE):
        raise BuildError("pin.json %s does not name the pin's commit %s and tree %s" % (p, PIN_COMMIT, PIN_TREE))
    entries = doc.get("entries")
    if not isinstance(entries, list) or not entries:
        raise BuildError("pin.json %s has no entries" % p)
    seen = set()
    for e in entries:
        if (not isinstance(e, dict) or set(e) != {"path", "mode", "blob"} or not isinstance(e["path"], str) or not _safe_rel(e["path"])
                or e["mode"] not in MODES or not re.fullmatch(r"[0-9a-f]{40}", str(e["blob"])) or e["path"] in seen):
            raise BuildError("pin.json %s: an entry that is not a relative path with a blob mode and id, or a path twice: %r" % (p, e))
        seen.add(e["path"])
    left = doc.get("left_out")
    if not isinstance(left, list) or not set(left) <= seen:
        raise BuildError("pin.json %s: left_out %r names no entry of its list" % (p, left))
    got = tree_id(entries)
    if got != PIN_TREE:
        raise BuildError("pin.json %s: its list hashes to the tree %s, not the pin's tree %s" % (p, got, PIN_TREE))
    return doc


def read_lock(path: Optional[Path] = None) -> Dict[str, str]:
    """The lock's one pin: name, version, sha256 and the wheel's file name."""
    p = path if path is not None else LOCK
    text = Path(p).read_text(encoding="ascii")
    pins = LOCK_RE.findall(text)
    if len(pins) != 1 or len(re.findall(r"^[a-z0-9-]+==", text, re.M)) != 1:
        raise BuildError("the lock %s holds %d pins with a hash and a wheel file, not one" % (p, len(pins)))
    name, version, sha, wheel = pins[0]
    if (name, version) != ("carla", WHEEL_VERSION):
        raise BuildError("the lock %s pins %s==%s, not carla==%s" % (p, name, version, WHEEL_VERSION))
    return {"name": name, "version": version, "sha256": sha, "file": wheel}


def project_files() -> Dict[str, Path]:
    """PROJECT_SOURCES' paths as this build reads them (the module's own, so that they can be moved together)."""
    return {"sdv/aw/aw-entrypoint.sh": ENTRYPOINT_SRC, "sdv/carlaif/pin.json": PIN_FILE, "sdv/carlaif/wheel.lock": LOCK}


def sources_sha256() -> str:
    """sha256 of `<sha256>  <path>\\n` for each of PROJECT_SOURCES in order (sha256sum's lines): the sources label."""
    files = project_files()
    lines = "".join("%s  %s\n" % (sha256_file(files[rel]), rel) for rel in PROJECT_SOURCES)
    return hashlib.sha256(lines.encode("ascii")).hexdigest()


def labels(images: Dict[str, Any]) -> Dict[str, str]:
    """The four labels: the base digest (images.json's autoware.amd64 manifest digest), the pin (commit:tree), the staged
    project files' digest, the wheel's sha256 (the lock's)."""
    pin = load_pin()
    return {"sdv.carlaif.base_digest": images["autoware"]["amd64"]["manifest_digest"],
            "sdv.carlaif.pin": "%s:%s" % (pin["commit"], pin["tree"]), "sdv.carlaif.sources_sha256": sources_sha256(),
            "sdv.carlaif.wheel_sha256": read_lock()["sha256"]}


def other_images(text: str) -> List[str]:
    """What a Dockerfile names as an image beside its FROM lines: a `# syntax=` parser directive (BuildKit's frontend image,
    looked for on any comment line), and every COPY or ADD --from= and RUN --mount=...,from= whose value is not a stage name
    a `FROM ... AS name` declares (docker reads stage names in any case). Continued lines are joined first, comment and
    empty lines skipped as docker skips them, also inside a continued instruction."""
    out: List[str] = []
    instructions: List[str] = []
    pending = ""
    for ln in text.splitlines():
        m = SYNTAX_RE.match(ln)
        if m is not None:
            out.append("# syntax=%s" % m.group(1))
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if ln.rstrip().endswith("\\"):
            pending += ln.rstrip()[:-1] + " "
            continue
        instructions.append(pending + ln)
        pending = ""
    if pending:
        instructions.append(pending)
    stages = {m.group(1).lower() for m in (STAGE_RE.match(i) for i in instructions) if m is not None}
    for ins in instructions:
        word = ins.strip().split(None, 1)[0].upper() if ins.strip() else ""
        named = FROM_OPT_RE.findall(ins) if word in ("COPY", "ADD") else []
        if word == "RUN":
            for opt in MOUNT_RE.findall(ins):
                named += [kv.split("=", 1)[1] for kv in opt.split(",") if kv.lower().startswith("from=")]
        out += ["%s --from=%s" % (word, v) for v in named if v.strip("\"'").lower() not in stages]
    return out


def check_inputs(images: Dict[str, Any]) -> str:
    """The Dockerfile's one FROM, which must be BASE_REPO@<images.json's autoware.amd64 manifest digest> (never a tag), and
    no other image named in it (other_images); every project file present. Returns the FROM's reference."""
    want = "%s@%s" % (BASE_REPO, images["autoware"]["amd64"]["manifest_digest"])
    text = DOCKERFILE.read_text(encoding="utf-8")
    found = (FROM_RE.match(ln) for ln in text.splitlines())
    froms = [(m.group(1) or "").strip() for m in found if m is not None]
    if froms != [want]:
        raise BuildError("the Dockerfile's FROM lines are %s, not the one %s (images.json's autoware.amd64 manifest digest)" % (froms, want))
    others = other_images(text)
    if others:
        raise BuildError("the Dockerfile names another image beside its FROM (by tag or digest, a second base nothing pins): %s"
                         % "; ".join(others))
    missing = [rel for rel, src in project_files().items() if not src.is_file()]
    if missing:
        raise BuildError("missing project files: %s" % missing)
    return want


def check_wheel(wheels: Path, lock: Dict[str, str]) -> Path:
    """The lock's wheel in the folder, its sha256 the lock's."""
    f = Path(wheels) / lock["file"]
    if not f.is_file() or f.is_symlink():
        raise BuildError("no wheel %s in %s (the lock's file, a regular file)" % (lock["file"], wheels))
    got = sha256_file(f)
    if got != lock["sha256"]:
        raise BuildError("the wheel %s has sha256 %s, not the lock's %s" % (f, got, lock["sha256"]))
    return f


def check_source(source: Path, pin: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(path, mode) of every file to stage: each entry of the pin's list but left_out, present in the source as a regular
    file whose blob id is the pin's. A file of the source the list does not hold, or a left-out file present with another
    blob id, is refused."""
    source = Path(source)
    if not source.is_dir():
        raise BuildError("the source %s is not a directory" % source)
    by = {e["path"]: e for e in pin["entries"]}
    left = set(pin["left_out"])
    problems: List[str] = []
    present = set()
    for p in sorted(source.rglob("*")):
        rel = p.relative_to(source).as_posix()
        if p.is_symlink() or (not p.is_file() and not p.is_dir()):
            problems.append("%s is not a regular file" % rel)
        elif p.is_file():
            present.add(rel)
            if rel not in by:
                problems.append("%s is not in the pin's tree" % rel)
            elif git_blob_id(p.read_bytes()) != by[rel]["blob"]:
                problems.append("%s's blob id is not the pin's %s" % (rel, by[rel]["blob"]))
    for rel in sorted(set(by) - left - present):
        problems.append("%s of the pin's tree is missing" % rel)
    if problems:
        raise BuildError("the source %s is not the pin's tree %s: %s" % (source, PIN_TREE, "; ".join(problems)))
    return [(e["path"], e["mode"]) for e in pin["entries"] if e["path"] not in left]


def check_build_argv(argv: Sequence[str]) -> None:
    """docker build's argument vector must carry --provenance=false and --sbom=false, each once, and no other provenance,
    SBOM or attestation argument (an attestation would carry the build's time into the image)."""
    wanted = {"--provenance=false", "--sbom=false"}
    risky = [a for a in argv if a.startswith(("--provenance", "--sbom", "--attest"))]
    if sorted(risky) != sorted(wanted):
        raise BuildError("docker build's provenance, sbom and attest arguments are %s, not exactly --provenance=false and --sbom=false" % risky)


def docker(*args: str, timeout: float = 120) -> str:
    p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise BuildError("docker %s: exit %d: %s" % (" ".join(args[:2]), p.returncode, (p.stderr or p.stdout).strip()[-2000:]))
    return p.stdout.strip()


def docker_stream(*args: str) -> "subprocess.Popen[bytes]":
    """`docker ARGS` with its stdout and stderr as pipes, for the save stream read as it comes (a seam the tests replace)."""
    return subprocess.Popen(["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def image_id(ref: str) -> Optional[str]:
    p = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", ref], capture_output=True, text=True, timeout=60)
    return p.stdout.strip() if p.returncode == 0 else None


def check_base(images: Dict[str, Any]) -> str:
    """The base in the image store, read by images.json's autoware index digest (under the containerd store a pulled
    image's ID is its index digest): absent, it is refused and nothing is pulled."""
    ref = "%s@%s" % (BASE_REPO, images["autoware"]["index_digest"])
    try:
        got = docker("image", "inspect", "--format", "{{.Id}}", ref)
    except BuildError:
        got = ""
    if got != images["autoware"]["index_digest"]:
        raise BuildError("the base %s is not in the image store (read %r): nothing is pulled; the base is kept, never fetched" % (ref, got))
    return ref


def hostcheck(args: List[str]) -> subprocess.CompletedProcess:
    """sdv/aw/hostcheck.sh with args (no argument: read; --compare BEFORE AFTER), under bash; a seam the tests replace."""
    return subprocess.run(["bash", str(HOSTCHECK)] + list(args), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)


def read_host() -> str:
    p = hostcheck([])
    if p.returncode != 0 or not p.stdout.startswith("format="):
        raise BuildError("the host check (sdv/aw/hostcheck.sh, spec-2 2.12) cannot be read (exit %d): %s"
                         % (p.returncode, (p.stderr or p.stdout).strip()[-300:] or "no output"))
    return p.stdout


def _a64scan() -> Any:
    key = "_sdv_a64scan_for_carlaif_build"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, str(A64SCAN_FILE))
    if spec is None or spec.loader is None:
        raise BuildError("cannot load %s" % A64SCAN_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[key] = mod
    return mod


def _town10() -> Any:
    """sdv/carla/town10.py (TOWN10_FILE), loaded by its file afresh at each call and no bytecode written."""
    spec = importlib.util.spec_from_file_location("_sdv_town10_for_carlaif_build", str(TOWN10_FILE))
    if spec is None or spec.loader is None:
        raise BuildError("cannot load %s" % TOWN10_FILE)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


def print_args(name: str) -> List[str]:
    """The launch arguments the proof's parse gives the launch file NAME: documentation values (RFC 5737's address; a map
    folder under /maps that need not exist: --print starts nothing and reads no map) and, from town10.py, the spawn point of
    PROOF_SCENARIO's start and the map folder's name."""
    t = _town10()
    if name == "sdv_carla.launch.xml":
        return ["host:=192.0.2.1", "spawn_point:=" + t.scenario_spawn_point(PROOF_SCENARIO)]
    return ["map_path:=/maps/" + t.MAP_NAME]


def saved_config(store_id: str) -> Tuple[str, Dict[str, Any]]:
    """(config digest, config) of the manifest store_id names, from a `docker save` stream read once and to its end: the
    manifest must hash to the ID and be one image manifest (an index is refused), the config to its digest, and the config's
    platform must be linux/amd64."""
    p = docker_stream("save", store_id)
    assert p.stdout is not None and p.stderr is not None
    blobs: Dict[str, bytes] = {}
    try:
        try:
            with tarfile.open(fileobj=p.stdout, mode="r|") as tf:
                for m in tf:
                    if m.isreg() and m.name.startswith("blobs/sha256/") and m.size <= SAVE_BLOB_LIMIT:
                        f = tf.extractfile(m)
                        if f is not None:
                            blobs["sha256:" + m.name.rsplit("/", 1)[1]] = f.read()
        except tarfile.TarError as exc:
            raise BuildError("docker save %s: not a tar stream (%s)" % (store_id, exc)) from None
        for _chunk in iter(lambda: p.stdout.read(1 << 20), b""):    # type: ignore[union-attr]
            pass
    except BaseException:
        p.kill()
        raise
    finally:
        err = p.stderr.read().decode("utf-8", "replace")
        rc = p.wait(timeout=1800)
    if rc != 0:
        raise BuildError("docker save %s: exit %d: %s" % (store_id, rc, err.strip()[-500:]))
    a64 = _a64scan()

    def get(digest: str) -> bytes:
        if digest not in blobs:
            raise a64.ScanError("the save stream has no blob %s" % digest)
        return blobs[digest]
    try:
        man, cfg = a64.saved_image(get, store_id)
    except (a64.ScanError, ValueError, KeyError, TypeError) as exc:
        raise BuildError("the image %s: its config digest is not proved by its save stream: %s" % (store_id, exc)) from None
    if (cfg.get("os"), cfg.get("architecture")) != ("linux", "amd64"):
        raise BuildError("the image %s is %s/%s, not linux/amd64" % (store_id, cfg.get("os"), cfg.get("architecture")))
    return str(man["config"]["digest"]), cfg


def build_args(lbl: Dict[str, str], ctx: Path) -> List[str]:
    """docker's arguments: the rosvss build's, no pull and no network for RUN, with the four labels as build arguments."""
    return ["build", "-q", "--provenance=false", "--sbom=false", "--pull=false", "--network=none",
            "--build-arg", "SDV_BASE_DIGEST=" + lbl["sdv.carlaif.base_digest"], "--build-arg", "SDV_PIN=" + lbl["sdv.carlaif.pin"],
            "--build-arg", "SDV_SOURCES_SHA256=" + lbl["sdv.carlaif.sources_sha256"],
            "--build-arg", "SDV_WHEEL_SHA256=" + lbl["sdv.carlaif.wheel_sha256"],
            "-f", str(ctx / "Dockerfile"), "-t", TAG, str(ctx)]


def compare_host(before: str, after: str, where: Path) -> List[str]:
    """hostcheck.sh --compare on the two readings (written into where): the `changed` lines; a comparison that cannot be
    made is a BuildError."""
    (where / "host-before.txt").write_text(before, encoding="utf-8")
    (where / "host-after.txt").write_text(after, encoding="utf-8")
    p = hostcheck(["--compare", str(where / "host-before.txt"), str(where / "host-after.txt")])
    if p.returncode not in (0, 1):
        raise BuildError("the host check's comparison failed (exit %d): %s" % (p.returncode, (p.stderr or "").strip()[-300:]))
    return [ln.strip() for ln in p.stdout.splitlines() if ln.startswith("changed ")]


def host_after_failure(before_host: str, where: Path) -> str:
    """What the host check says after a build that failed, compared with the reading before it. Nothing is reverted."""
    try:
        changed = compare_host(before_host, read_host(), where)
    except (BuildError, OSError, subprocess.SubprocessError) as exc:
        return "the host check after it could not be read or compared: %s" % exc
    if changed:
        return "the host check after it: %s (nothing reverted it)" % "; ".join(changed)
    return "the host check after it: the four settings as before"


def stage(ctx: Path, files: List[Tuple[str, str]], source: Path, pin: Dict[str, Any], wheel: Path, lock: Dict[str, str]) -> Dict[str, str]:
    """The context: the project files, the wheel (hashed again as staged) and the pin's files with their modes (each blob id
    checked again as staged). Returns the sha256 of each staged project file and of the wheel."""
    out: Dict[str, str] = {}
    for name, src in (("Dockerfile", DOCKERFILE), ("wheel.lock", LOCK), ("aw-entrypoint.sh", ENTRYPOINT_SRC)):
        shutil.copyfile(src, ctx / name)
        out[name] = sha256_file(ctx / name)
    (ctx / "wheels").mkdir()
    staged_wheel = ctx / "wheels" / lock["file"]
    shutil.copyfile(wheel, staged_wheel)
    out["wheels/" + lock["file"]] = sha256_file(staged_wheel)
    if out["wheels/" + lock["file"]] != lock["sha256"]:
        raise BuildError("the staged wheel's sha256 is %s, not the lock's %s" % (out["wheels/" + lock["file"]], lock["sha256"]))
    by = {e["path"]: e["blob"] for e in pin["entries"]}
    for rel, mode in files:
        dst = ctx / (SRC_PREFIX + rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(source) / rel, dst)
        os.chmod(dst, MODES[mode])
        if git_blob_id(dst.read_bytes()) != by[rel]:
            raise BuildError("the staged %s's blob id is not the pin's %s" % (rel, by[rel]))
    return out


def proof_problems(reads: Dict[str, Any]) -> List[str]:
    """Why the proof's reads do not show the pin's package and the venv's carla running (2.2)."""
    out: List[str] = []

    def under(path: Any, root: str) -> bool:
        return isinstance(path, str) and path.startswith(root.rstrip("/") + "/")
    if reads.get("package_version") != PACKAGE_VERSION:
        out.append("the package's version is %r, not the pin's %s" % (reads.get("package_version"), PACKAGE_VERSION))
    for key, what in (("interface_file", "the interface's module"), ("carla_ros_file", "carla_ros.py"),
                      ("share", "find-pkg-share autoware_carla_interface")):
        if not under(reads.get(key), OVERLAY):
            out.append("%s is %r, not under the overlay %s" % (what, reads.get(key), OVERLAY))
    prefix = reads.get("prefix")
    if not under(prefix, OVERLAY) or prefix == reads.get("image_copy_prefix") or under(prefix, "/opt/autoware"):
        out.append("the package's prefix %r is the image's %s copy or not under the overlay %s" % (prefix, IMAGE_COPY_VERSION, OVERLAY))
    if reads.get("carla_version") != WHEEL_VERSION:
        out.append("carla's version is %r, not %s" % (reads.get("carla_version"), WHEEL_VERSION))
    if not under(reads.get("carla_file"), VENV):
        out.append("carla's module %r is not the venv's (%s)" % (reads.get("carla_file"), VENV))
    if reads.get("python3") != VENV + "/bin/python3" or not under(reads.get("executable"), VENV):
        out.append("python3 resolves to %r (%r), not the venv's %s/bin/python3" % (reads.get("python3"), reads.get("executable"), VENV))
    if reads.get("script_shebang") != "#!/usr/bin/env python3":
        out.append("the node script's shebang is %r, not #!/usr/bin/env python3" % reads.get("script_shebang"))
    if reads.get("carla_ros_imported") is not True:
        out.append("the node's module carla_ros was not imported under the venv's python: %r" % reads.get("carla_ros_imported"))
    return out


def run_argv(image: str, command: str) -> List[str]:
    """docker run of the image by its ID under the project's flags, the tree's sdv and sdv/aw read-only, the command
    under LAUNCH_ENV through bash."""
    return ["run", "--rm", "--network", "none", "--pull", "never", "--platform", "linux/amd64", "--user", IMAGE_USER,
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--entrypoint", ENTRYPOINT_IN_IMAGE,
            "-e", "ROS_LOG_DIR=/tmp/ros-log", "-v", "%s:/sdv/sdv:ro" % (REPO / "sdv"), "-v", "%s:/sdv-aw:ro" % (REPO / "sdv" / "aw"),
            image, "bash", "-c", "%s && %s" % (LAUNCH_ENV, command)]


def proof(image: str) -> Dict[str, Any]:
    """The proof's reads and the two launch files' parse, inside the image by its ID; problems as proof_problems names them."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise BuildError("the proof runs an image by its ID, never by tag: %r" % image)
    out = docker(*run_argv(image, "exec /usr/bin/env python3 -c %s" % _sh_quote(PROOF_PY)), timeout=600)
    lines = out.splitlines()
    try:
        reads = json.loads(lines[lines.index("== reads") + 1])
    except (ValueError, IndexError) as err:
        raise BuildError("the proof's reads gave no record (%s): %s" % (err, out[-1000:])) from None
    printed: Dict[str, str] = {}
    for name in LAUNCH_FILES:
        printed[name] = docker(*run_argv(image, "exec ros2 launch --print /sdv/sdv/carlaif/launch/%s %s" % (name, " ".join(print_args(name)))),
                               timeout=600)
    return {"image": image, "reads": reads, "problems": proof_problems(reads), "launch_print": printed}


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def built_record(images: Dict[str, Any], lbl: Dict[str, str], base: str, ctx: Path, files: List[Tuple[str, str]], source: Path,
                 pin: Dict[str, Any], wheel: Path, lock: Dict[str, str], with_proof: bool) -> Dict[str, Any]:
    """Stage, build, read the config digest from the save stream, refuse a config that is not the project's entrypoint, user
    aw and the four labels given (before anything is proved or pinned), take care of the image the tag named before, and
    prove when asked: the record, without the host check's second reading."""
    staged = stage(ctx, files, source, pin, wheel, lock)
    before = image_id(TAG)
    args = build_args(lbl, ctx)
    check_build_argv(args)
    docker(*args, timeout=7200)
    iid = image_id(TAG)
    if iid is None:
        raise BuildError("the build left no image tagged %s" % TAG)
    config_digest, cfg = saved_config(iid)
    conf = cfg.get("config") or {}
    if conf.get("Entrypoint") != [ENTRYPOINT_IN_IMAGE] or str(conf.get("User") or "").split(":")[0] != IMAGE_USER:
        raise BuildError("the built image %s has the entrypoint %r and the user %r, not [%r] and %s: the base's entrypoint would "
                         "run, or the image as root (spec-2 2.12); nothing is proved or pinned" % (
                             iid, conf.get("Entrypoint"), conf.get("User"), ENTRYPOINT_IN_IMAGE, IMAGE_USER))
    got = {k: (conf.get("Labels") or {}).get(k) for k in LABEL_KEYS}
    if got != lbl:
        raise BuildError("the built image %s carries the labels %s, not the ones given %s; nothing is proved or pinned" % (iid, got, lbl))
    record: Dict[str, Any] = {
        "image_id": iid, "config_digest": config_digest, "tag": TAG,
        "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "base": base,
        "build": "docker " + " ".join(a if not a.startswith(str(ctx)) else "<ctx>" + a[len(str(ctx)):] for a in args),
        "labels": lbl, "config_user": conf.get("User"), "config_entrypoint": conf.get("Entrypoint"),
        "dockerfile_sha256": sha256_file(DOCKERFILE), "staged": staged, "pin_files": len(files),
        "pin": {"amd64": {"id": iid, "config_digest": config_digest, "tag": TAG, "lock": LOCK_REL}, "labels": dict(lbl)}}
    if before is not None and before != iid:
        if image_id(before) is None:
            record["replaced_image"] = {"id": before, "left": "gone (the image store dropped it with its tag)"}
        elif before == ((images.get("carlaif") or {}).get("amd64") or {}).get("id"):
            record["replaced_image"] = {"id": before, "left": "kept (images.json pins it)"}
        elif json.loads(docker("image", "inspect", "--format", "{{json .RepoTags}}", before) or "[]") == []:
            docker("image", "rm", before)
            record["replaced_image"] = {"id": before, "left": "removed (untagged by this build)"}
        else:
            record["replaced_image"] = {"id": before, "left": "kept (another tag names it)"}
    if with_proof:
        record["proof"] = proof(iid)
        if record["proof"]["problems"]:
            raise BuildError("the proof of %s: %s" % (iid, "; ".join(record["proof"]["problems"])))
    return record


def build(images: Dict[str, Any], source: Path, wheels: Path, proof: bool = False) -> Dict[str, Any]:
    """check_inputs, pin.json, the source and the wheel checked, the base found in the store, the host check read,
    built_record in a staged context, the host check read again and compared: a difference fails the build with the setting
    named. A build that fails after the first reading is failed with the second reading's words added."""
    base = check_inputs(images)
    pin = load_pin()
    lock = read_lock()
    files = check_source(source, pin)
    wheel = check_wheel(wheels, lock)
    lbl = labels(images)
    root = CACHE / "carlaif-build"
    if str(root.resolve()).startswith(str(Path(REPO).resolve()) + os.sep):
        raise BuildError("the staging root %s is inside the repo" % root)
    check_base(images)
    before_host = read_host()
    root.mkdir(parents=True, exist_ok=True)
    ctx = Path(tempfile.mkdtemp(prefix="ctx-", dir=str(root)))
    try:
        try:
            record = built_record(images, lbl, base, ctx, files, source, pin, wheel, lock, proof)
        except Exception as err:
            raise BuildError("%s; %s" % (err, host_after_failure(before_host, ctx))) from err
        after_host = read_host()
        changed = compare_host(before_host, after_host, ctx)
        record["host_check"] = {"before": before_host, "after": after_host, "changed": changed}
        if changed:
            raise BuildError("the host check changed during the build (spec-2 2.12), nothing reverted it: %s" % "; ".join(changed))
        return record
    finally:
        shutil.rmtree(ctx, ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the image from a verified copy of the pin and the locked wheel")
    b.add_argument("--source", required=True, type=Path, help="a copy of the pinned package's tree")
    b.add_argument("--wheels", required=True, type=Path, help="the folder holding the wheel wheel.lock names")
    b.add_argument("--proof", action="store_true", help="read the proof inside the built image")
    p = sub.add_parser("proof", help="read the proof inside an image already built")
    p.add_argument("--image", help="the image ID (default: images.json's carlaif.amd64.id)")
    a = ap.parse_args(argv)
    try:
        images = json.loads(IMAGES_FILE.read_text(encoding="utf-8"))
        if a.cmd == "build":
            record = build(images, a.source, a.wheels, a.proof)
        else:
            record = proof(a.image or images["carlaif"]["amd64"]["id"])
    except (BuildError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as err:
        print("build_image: %s" % err, file=sys.stderr)
        return 1
    print(json.dumps(record, indent=1, sort_keys=True))
    if a.cmd == "proof" and record["problems"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
