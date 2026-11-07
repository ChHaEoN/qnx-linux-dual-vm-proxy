#!/usr/bin/env python3
"""bundle.py -- the upload bundle that carries the slice's arm64 images, the generation, the recordings, the DBC and the
host Python to an aarch64 instance, and its checks there (sdv/stack; SDV Phase 3 WP1).

Standard library only, and the verify side runs on Python 3.10 (the instance's system
python3, before any venv exists), so nothing here may need a later Python:

    python3 sdv/stack/bundle.py build --out DIR --commit SHA [--gen DIR] [--recordings DIR] [--cache DIR]
                                      [--python-src DIR] [--docker PREFIX]        # the PC, in WSL
    python3 sdv/stack/bundle.py verify --in DIR [--loaded] [--docker PREFIX]      # the instance; the PC's rehearsal
    python3 sdv/stack/bundle.py verify-upstream [--docker PREFIX]                 # the instance, after the pulls

Every docker call takes its argv prefix from --docker (default `docker`). The setup harness passes 'sudo -n docker':
its docker group membership applies only from its next login.

BUILD (the PC, in WSL, where git never runs: the source commit is read in Git Bash and passed as --commit). DIR must
be outside the repo, and empty or absent. Every input is checked before anything is written, and a refusal after that
removes what the build wrote. The members, each under a name the upload accepts ([A-Za-z0-9._-]):
  sdv-arm64-images.tar  `docker save` of the three arm64 images by their pinned IDs (images.json local.*.arm64 and
                        bridge.arm64), each first found in the daemon by that ID as linux/arm64, the bridge with images.json's
                        three labels; the tar is then checked as verify checks it.
  sdv-gen.tar           the generation (--gen; SDV_GEN or sdv-out/gen) under gen/: exactly manifest.json and the files its
                        outputs list, each with its listed sha256 and size. Refused unless vss_contract.py's sha256, the
                        manifest's slice.dbc and its kind4 catalog digest are the bridge pin's three labels (the bridge
                        image bakes the generation in), and that slice.dbc is every recording's DBC and the repo's
                        sdv/vss/slice.dbc; and, once the image tar is saved, unless manifest.json is the one the bridge
                        image bakes in (app/sdv-out/gen/manifest.json): the labels bind three outputs, the baked manifest
                        every one (vss-databroker.json and the mapping, which the databroker and the can-provider read).
  rec-<name>.tar        one per recording of every plan the suite runs (RECORDINGS: four, below), from --recordings
                        (default ~/sdv-recordings; read, never written), under <name>/: its regular files; its log, the one
                        its manifest line names, hashes to the line's sha256 and to <log>.sha256's, and the line names the
                        recording.
  <sha256>.dbc          the DBC, from <cache>/dbc/<sha256>.dbc (--cache; SDV_CACHE or ~/sdv-cache), hashing to its name.
  cpython-3.12-aarch64-install_only.tar.gz
                        the pinned python-build-standalone tarball (sdv/sim/python-aarch64.json: release, asset name,
                        sha256, bytes, the release's published sums), found in --python-src (SDV_BUNDLE_SRC or
                        ~/sdv-bundle-src) by its asset name and carried under the pin's upload name: the asset's own name
                        carries a '+', which the upload does not accept.
  bundle.json           written last: the format, the commit, and per member its name, role, bytes and sha256, with the
                        image pins, the labels, each recording's log and the log's sha256, the tarball's asset name and
                        release, and `pins`: the sha256 of the images.json and python-aarch64.json it was built from.

RECORDINGS (SDV Phase 7 WP3b; spec-2 2.1 and 2.3)  The plans' recordings (PLAN_RECORDINGS; vss_suite.py holds the same
  table): v1 and v2 replay the sigsim pair, 20260930-sigsim-1b and its injected twin 20261002-sigsim-1b-inj4; carla replays
  the CARLA pair, CARLA_HONEST (20261019-carla-1, the name Phase 7 WP5a recorded) and its twin CARLA_HONEST-inj. The bundle
  carries all four, each once, so that one bundle serves every plan. A recording's log is the basename of its manifest
  line's recording.path, which must be its source.generator's (LOG_NAMES: sigsim.log for sigsim, carla.log for carla,
  sdv/inject/inject.py's table); any other pair, another name or another generator is refused naming both.

VERIFY  bundle.json's `pins` against the repo's own images.json and python-aarch64.json (a bundle built from another pin
  set is named, whatever its content). Every member against bundle.json (its name in [A-Za-z0-9._-], its role, bytes and
  sha256), each member the bundle carries listed once, no file missing and none extra. Each member is opened once: its
  sha256 is taken through that handle and every content check below reads the same handle, so the bytes checked are the
  bytes bundle.json names; a member whose sha256 differs is not read further, and at the end each held member is read
  again through its handle and its path must still name that file ("changed while it was verified" otherwise). Then each
  member's content against the repo's own pins: the image tar's OCI layout against images.json (its index lists exactly
  the three pinned IDs; each ID's manifest blob is present and hashes to it, its config.digest is the pinned config
  digest, the config blob hashes to that and says linux/arm64, every layer blob hashes to its digest), and the tar is
  exactly what a save of the pins by ID writes (each name once; the blobs/ and blobs/sha256/ directories, index.json,
  oci-layout, a legacy manifest.json naming the pins' configs and layers and no tag, a repositories file only if it
  names nothing, and otherwise only blobs a pinned manifest references; no link); the generation against the bridge's
  labels as build checks it, and its manifest.json against the one the bridge image bakes in; the recordings against the
  generation's DBC, the DBC against its name, the tarball against python-aarch64.json. With --loaded (after `docker
  load`): each pin's ID found in the daemon with that ID, as linux/arm64, the bridge with its labels; and the daemon's
  server version and image store driver type recorded.
VERIFY-UPSTREAM  The four upstream images (images.json upstream), pulled before by repo@index-digest, inspected and
  never pulled: the image ID is the index digest (a pulled image's ID under the containerd store), the revision label is
  the pinned commit, repo@index-digest is among its RepoDigests, and it is linux/arm64. stack.py's `--images loaded` path
  applies the same rules (upstream_problems, loaded_problems).

OUTPUT  Each command prints one JSON line of selected fields, never a raw `docker inspect` or `docker info`. verify and
  verify-upstream exit 0 when every check holds, else 1 with the record's `problems`; build exits 0 with its record, or 1
  with one error line.

Does not demonstrate: that the carry holds from the PC's Docker Engine to the instance's, or that the instance's image
store is containerd's (verify --loaded there records both); that the images run on the instance; anything about the
guest; any timing.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
IMAGES_FILE = HERE / "images.json"
PYTHON_FILE = REPO / "sdv" / "sim" / "python-aarch64.json"
SLICE_DBC = REPO / "sdv" / "vss" / "slice.dbc"

FORMAT = 1
BUNDLE_JSON = "bundle.json"
IMAGES_TAR = "sdv-arm64-images.tar"
GEN_TAR = "sdv-gen.tar"
GEN_TOP = "gen"
REC_TAR = "rec-%s.tar"
# A recording's log by its manifest line's source.generator (spec-2 2.1; module docstring, RECORDINGS): the basename of
# the line's recording.path is its generator's. sdv/inject/inject.py's LOG_NAMES, held equal by tests/test_sdv_stack.py
# (this module is standard library only, so it keeps its own copy); stack.py reads it from here.
LOG_NAMES = {"sigsim": "sigsim.log", "carla": "carla.log"}
CARLA_HONEST = "20261019-carla-1"             # the honest CARLA recording Phase 7 WP5a recorded (spec-2 2.3): a name, not a result
# The plans' recordings (spec-2 2.3), each plan's honest one and its injected twin: v1 and v2 share the sigsim pair, carla
# replays the CARLA pair. orin-native/gpu-concurrency/vss_suite.py holds the same table (tests/test_vss_harness.py holds
# the two equal).
PLAN_RECORDINGS = {
    "v1": {"honest": "20260930-sigsim-1b", "injected": "20261002-sigsim-1b-inj4"},
    "v2": {"honest": "20260930-sigsim-1b", "injected": "20261002-sigsim-1b-inj4"},
    "carla": {"honest": CARLA_HONEST, "injected": CARLA_HONEST + "-inj"},
}
# The recordings the bundle carries: every plan's, each once, in the table's order (the four).
RECORDINGS = tuple(dict.fromkeys(n for p in PLAN_RECORDINGS.values() for n in (p["honest"], p["injected"])))
# What every recording holds besides its log and <log>.sha256, which its manifest line names (log_name_of).
RECORDING_NEEDS = ("manifest-line.json", "summary.json")
ROLES = ("images", "gen", "recording", "dbc", "python")
ARCH, OS = "arm64", "linux"
BRIDGE = "bridge"
REVISION = "org.opencontainers.image.revision"
CONTRACT_LABEL, DBC_LABEL, CATALOG_LABEL = "sdv.kind4.contract_sha256", "sdv.kind4.dbc_sha256", "sdv.kind4.catalog_digest"
LABELS = (CATALOG_LABEL, CONTRACT_LABEL, DBC_LABEL)
NAME_RULE = "[A-Za-z0-9._-]"
_NAME = re.compile(r"[A-Za-z0-9._-]+")
HEX64 = re.compile(r"[0-9a-f]{64}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
CHUNK = 1 << 20
SMALL = 64 << 20          # the most a generation or recording file, a manifest or a config may hold (read whole)
# What a `docker save` of the pins by ID writes besides the pins' blobs (check_images_tar).
TAR_DIRS = ("blobs", "blobs/sha256")
TAR_FILES = ("index.json", "oci-layout", "manifest.json", "repositories")
# Where sdv/bridge/build_image.py stages the generation's manifest in the bridge image (app/ + sdv-out/gen/manifest.json):
# the bridge pin's ID binds it, and through its outputs' sha256 every generated file.
BAKED_GEN_MANIFEST = "app/sdv-out/gen/manifest.json"


class BundleError(RuntimeError):
    pass


# --- small helpers ---------------------------------------------------------------------------------

def good_name(name: Any) -> bool:
    """A name the upload accepts ([A-Za-z0-9._-]), never `.` or `..`."""
    return isinstance(name, str) and bool(_NAME.fullmatch(name)) and name not in (".", "..")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_stream(f: Any) -> str:
    h = hashlib.sha256()
    for chunk in iter(lambda: f.read(CHUNK), b""):
        h.update(chunk)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    with open(str(path), "rb") as f:
        return sha256_stream(f)


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BundleError("%s: %s" % (Path(path).name, exc)) from exc


def tail(text: Optional[str], n: int = 300) -> str:
    return " ".join((text or "").split())[-n:]


def outside_repo(path: Path) -> Path:
    p = Path(path).expanduser()
    r, repo = p.resolve(), REPO.resolve()
    if r == repo or repo in r.parents:
        raise BundleError("%s is inside the repo: the bundle stays outside it" % p)
    return p


class Docker:
    """docker behind an argv prefix (--docker): every docker call of this module goes through run()."""

    def __init__(self, prefix: str = "docker") -> None:
        self.argv = shlex.split(prefix)
        if not self.argv:
            raise BundleError("--docker: an empty prefix")

    def run(self, args: Sequence[str], timeout: float = 120) -> subprocess.CompletedProcess:
        cmd = self.argv + list(args)
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BundleError("%s: %s" % (" ".join(cmd[:len(self.argv) + 2]), exc)) from exc

    def inspect(self, ref: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """The daemon's record of one image, or (None, why) when it has none."""
        p = self.run(["image", "inspect", ref])
        if p.returncode != 0:
            return None, tail(p.stderr or p.stdout) or "exit %d" % p.returncode
        try:
            data = json.loads(p.stdout)
        except ValueError:
            return None, "docker image inspect printed no JSON"
        if not (isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict)):
            return None, "docker image inspect printed no single record"
        return data[0], ""

    def facts(self) -> Dict[str, Optional[str]]:
        """The server's version and its image store's driver type (`driver-type` of DriverStatus), nothing else."""
        v = self.run(["version", "-f", "{{.Server.Version}}"])
        i = self.run(["info", "-f", "{{json .DriverStatus}}"])
        driver_type = None
        if i.returncode == 0:
            try:
                pairs = json.loads(i.stdout) or []
                driver_type = dict((str(k), str(val)) for k, val in pairs).get("driver-type")
            except (ValueError, TypeError):
                driver_type = None
        return {"server": v.stdout.strip() if v.returncode == 0 else None, "driver_type": driver_type}


# --- the pins and the rules stack.py shares ----------------------------------------------------------

def labels_of(info: Dict[str, Any]) -> Dict[str, Any]:
    return (info.get("Config") or {}).get("Labels") or {}


def arm64_pins(images: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """The three arm64 pins: each local image's (images.json local.*.arm64) and the bridge's (bridge.arm64)."""
    try:
        pins = {name: dict(spec["arm64"]) for name, spec in sorted(images["local"].items())}
        pins[BRIDGE] = dict(images[BRIDGE]["arm64"])
    except (KeyError, TypeError, AttributeError) as exc:
        raise BundleError("images.json has no arm64 pin for every local image and the bridge (%r)" % (exc,)) from exc
    for name, pin in pins.items():
        if not (DIGEST.fullmatch(str(pin.get("id"))) and DIGEST.fullmatch(str(pin.get("config_digest")))):
            raise BundleError("images.json: %s's arm64 pin is not {id, config_digest} as sha256:<64 hex>: %r" % (name, pin))
    return pins


def bridge_labels(images: Dict[str, Any]) -> Dict[str, str]:
    labels = (images.get(BRIDGE) or {}).get("labels") or {}
    missing = [k for k in LABELS if not isinstance(labels.get(k), str)]
    if missing:
        raise BundleError("images.json: the bridge entry has no %s label" % ", ".join(missing))
    return {k: labels[k] for k in LABELS}


def upstream_ref(u: Dict[str, Any]) -> str:
    return "%s@%s" % (u["repo"], u["index_digest"])


def platform_problem(name: str, info: Dict[str, Any]) -> List[str]:
    if (info.get("Os"), info.get("Architecture")) != (OS, ARCH):
        return ["%s: %s/%s, not %s/%s" % (name, info.get("Os"), info.get("Architecture"), OS, ARCH)]
    return []


def upstream_problems(name: str, u: Dict[str, Any], info: Optional[Dict[str, Any]], why: str = "") -> List[str]:
    """Why a pulled upstream image is not its pin: not in the store (it is pulled before the run, never by this check),
    its image ID not the index digest, its revision label not the pinned commit, repo@index-digest not among its
    RepoDigests, or not linux/arm64."""
    ref = upstream_ref(u)
    if info is None:
        return ["%s: %s is not in the image store (%s); it is pulled before the run, never here" % (name, ref, why or "no record")]
    out = []
    if info.get("Id") != u["index_digest"]:
        out.append("%s: image ID %s, not the pinned index digest %s" % (name, info.get("Id"), u["index_digest"]))
    rev = labels_of(info).get(REVISION)
    if rev != u["revision"]:
        out.append("%s: revision label %r, pinned %r" % (name, rev, u["revision"]))
    if ref not in (info.get("RepoDigests") or []):
        out.append("%s: %s is not among the image's repo digests %r" % (name, ref, info.get("RepoDigests")))
    return out + platform_problem(name, info)


def loaded_problems(name: str, pin: Dict[str, str], info: Optional[Dict[str, Any]], why: str = "",
                    labels: Optional[Dict[str, str]] = None) -> List[str]:
    """Why a loaded (or built) arm64 image is not its pin: not in the store, another image ID, not linux/arm64, or
    (labels given) a label that differs."""
    if info is None:
        return ["%s: %s (%s) is not in the image store (%s)" % (name, pin["id"], pin.get("tag"), why or "no record")]
    out = []
    if info.get("Id") != pin["id"]:
        out.append("%s: image ID %s, pinned %s" % (name, info.get("Id"), pin["id"]))
    out += platform_problem(name, info)
    if labels:
        got = labels_of(info)
        wrong = {k: {"image": got.get(k), "pinned": v} for k, v in sorted(labels.items()) if got.get(k) != v}
        if wrong:
            out.append("%s: labels differ from the pin's: %s" % (name, json.dumps(wrong, sort_keys=True)))
    return out


def pin_files() -> List[Tuple[str, Path]]:
    """The repo's pin files a bundle is built from and verified against (bundle.json's `pins`: their sha256 at build)."""
    return [("sdv/stack/images.json", IMAGES_FILE), ("sdv/sim/python-aarch64.json", PYTHON_FILE)]


def python_pin(py: Any) -> Dict[str, Any]:
    """python-aarch64.json, checked for what the bundle reads: the asset, its sha256 and bytes, the upload name."""
    if not isinstance(py, dict):
        raise BundleError("python-aarch64.json is not an object")
    for key in ("release", "asset", "sha256", "bytes", "upload_name", "sums_url"):
        if key not in py:
            raise BundleError("python-aarch64.json has no %s" % key)
    if not HEX64.fullmatch(str(py["sha256"])):
        raise BundleError("python-aarch64.json: sha256 %r is not 64 hex digits" % (py["sha256"],))
    if not isinstance(py["bytes"], int) or isinstance(py["bytes"], bool) or py["bytes"] <= 0:
        raise BundleError("python-aarch64.json: bytes %r" % (py["bytes"],))
    if not good_name(py["upload_name"]):
        raise BundleError("python-aarch64.json: upload_name %r: the upload takes only %s names" % (py["upload_name"], NAME_RULE))
    if not isinstance(py["asset"], str) or "/" in py["asset"] or py["asset"] in ("", ".", ".."):
        raise BundleError("python-aarch64.json: asset %r is not a file name" % (py["asset"],))
    return py


# --- the image tar ------------------------------------------------------------------------------------

def legacy_problems(tar_name: str, raw: Optional[bytes], expected: Dict[str, List[str]]) -> List[str]:
    """The legacy manifest.json `docker save` writes beside index.json (a graph-driver store loads from it): one entry per
    saved image, its Config and Layers the blob paths the pinned manifest names (expected: config path -> layer paths),
    and no tag, since the save is by ID."""
    try:
        doc = json.loads(raw.decode("utf-8")) if raw is not None else None
    except ValueError:
        doc = None
    if not isinstance(doc, list) or not all(isinstance(e, dict) for e in doc):
        return ["%s: manifest.json is not a list of image entries" % tar_name]
    out = []
    configs = sorted(str(e.get("Config")) for e in doc)
    if configs != sorted(expected):
        out.append("%s: manifest.json lists the configs %s, the pinned manifests' are %s" % (tar_name, configs, sorted(expected)))
    for e in doc:
        if e.get("RepoTags"):
            out.append("%s: manifest.json names a tag (%r): a save by ID names none" % (tar_name, e.get("RepoTags")))
        want = expected.get(str(e.get("Config")))
        if want is not None and e.get("Layers") != want:
            out.append("%s: manifest.json's layers for %s are not the pinned manifest's" % (tar_name, e.get("Config")))
    return out


def check_images_tar(path: Path, pins: Dict[str, Dict[str, str]], f: Optional[Any] = None) -> Tuple[Dict[str, Any], List[str]]:
    """A `docker save` tar's OCI layout against the pins: index.json lists exactly the pinned IDs; each ID's manifest blob
    is present and hashes to it (the containerd store's ID of a built or loaded image is its manifest digest), its
    config.digest is the pinned config digest, the config blob hashes to that and says linux/arm64, and every layer blob
    is present and hashes to its digest. The tar is exactly what a save of the pins by ID writes: each name once, the
    directories blobs/ and blobs/sha256/, index.json, oci-layout, manifest.json naming the pins' configs and layers and no
    tag, a repositories file only if it names nothing, and otherwise only blobs a pinned manifest references; no link.
    The bridge's report carries the sha256 of the generation manifest its image bakes in (BAKED_GEN_MANIFEST, from its
    topmost layer holding it). f: an open file of path's bytes to read instead of opening path (verify's one handle per
    member). Returns a report per pin and the problems."""
    report: Dict[str, Any] = {}
    problems: List[str] = []
    if f is not None:
        f.seek(0)
    with (tarfile.open(fileobj=f, mode="r:") if f is not None else tarfile.open(str(path), "r:")) as tf:
        members: Dict[str, tarfile.TarInfo] = {}
        names: Set[str] = set()
        for m in tf.getmembers():
            if m.name in names:
                problems.append("%s: %s is in it twice" % (path.name, m.name))
            names.add(m.name)
            if m.isdir() and m.name.rstrip("/") in TAR_DIRS:
                continue
            if not m.isreg():
                kind = "a link" if m.issym() or m.islnk() else "a directory" if m.isdir() else "type %r" % m.type
                problems.append("%s: %s is %s, not a regular file" % (path.name, m.name, kind))
                continue
            members.setdefault(m.name, m)

        def read_small(name: str) -> Optional[bytes]:
            m = members.get(name)
            if m is None or m.size > SMALL:
                return None
            mf = tf.extractfile(m)
            return mf.read() if mf is not None else None

        def blob_path(digest: str) -> str:
            return "blobs/sha256/" + digest.split(":", 1)[1]

        hashed: Dict[str, Optional[str]] = {}

        def blob_sha(digest: str) -> Optional[str]:
            if digest not in hashed:
                m = members.get(blob_path(digest))
                bf = tf.extractfile(m) if m is not None else None
                hashed[digest] = None if bf is None else "sha256:" + sha256_stream(bf)
            return hashed[digest]

        def baked(layers: List[str], want: str) -> Tuple[Optional[bytes], str]:
            """The file want as the image holds it: from its topmost layer that has it (a pinned image's layers are fixed
            by its ID, and the bridge's Dockerfile deletes nothing, so no whiteout is looked for)."""
            for d in reversed(layers):
                lf = tf.extractfile(members[blob_path(d)])
                try:
                    with tarfile.open(fileobj=lf, mode="r|*") as lt:
                        for lm in lt:
                            n = lm.name[2:] if lm.name.startswith("./") else lm.name
                            if n.lstrip("/") != want:
                                continue
                            if not lm.isreg() or lm.size > SMALL:
                                return None, "the image's %s is not a regular file of at most %d bytes" % (want, SMALL)
                            data = lt.extractfile(lm)
                            return (data.read() if data is not None else b""), ""
                except tarfile.TarError as exc:
                    return None, "its layer %s does not read as a tar (%s)" % (d, exc)
            return None, "the image holds no %s" % want

        raw_index = read_small("index.json")
        if raw_index is None:
            return report, problems + ["%s: no index.json (not an OCI layout)" % path.name]
        index = json.loads(raw_index.decode("utf-8"))
        listed = sorted(str(m.get("digest")) for m in (index.get("manifests") or []) if isinstance(m, dict))
        want = sorted(p["id"] for p in pins.values())
        if listed != want:
            problems.append("%s: index.json lists %s, the pins are %s" % (path.name, listed, want))
        referenced: Set[str] = set()       # every blob a pinned manifest names, the manifest's own included
        legacy: Dict[str, List[str]] = {}  # the legacy manifest.json's entries a save of the pins writes: config -> layers
        for name, pin in pins.items():
            r: Dict[str, Any] = {"id": pin["id"], "config_digest": pin["config_digest"], "ok": False}
            report[name] = r
            referenced.add(blob_path(pin["id"]))
            raw = read_small(blob_path(pin["id"]))
            if raw is None:
                problems.append("%s: the tar has no manifest blob %s" % (name, pin["id"]))
                continue
            if "sha256:" + sha256_bytes(raw) != pin["id"]:
                problems.append("%s: the manifest blob hashes to sha256:%s, not its ID %s" % (name, sha256_bytes(raw), pin["id"]))
                continue
            man = json.loads(raw.decode("utf-8"))
            cd = (man.get("config") or {}).get("digest")
            named = [str(lay.get("digest")) for lay in (man.get("layers") or []) if isinstance(lay, dict)]
            if DIGEST.fullmatch(str(cd)) and all(DIGEST.fullmatch(d) for d in named):
                referenced.update(blob_path(d) for d in [str(cd)] + named)
                legacy[blob_path(str(cd))] = [blob_path(d) for d in named]
            if cd != pin["config_digest"]:
                problems.append("%s: the manifest's config digest is %s, pinned %s" % (name, cd, pin["config_digest"]))
                continue
            craw = read_small(blob_path(cd))
            if craw is None or "sha256:" + sha256_bytes(craw) != cd:
                problems.append("%s: the config blob %s is missing or does not hash to its digest" % (name, cd))
                continue
            cfg = json.loads(craw.decode("utf-8"))
            r["platform"] = "%s/%s" % (cfg.get("os"), cfg.get("architecture"))
            bad = [] if (cfg.get("os"), cfg.get("architecture")) == (OS, ARCH) else ["%s: the config says %s, not %s/%s" % (
                name, r["platform"], OS, ARCH)]
            layers = named
            r["layers"] = len(layers)
            if not layers:
                bad.append("%s: the manifest lists no layer" % name)
            for d in layers:
                if not DIGEST.fullmatch(d):
                    bad.append("%s: layer digest %r" % (name, d))
                    continue
                got = blob_sha(d)
                if got is None:
                    bad.append("%s: the tar has no layer blob %s" % (name, d))
                elif got != d:
                    bad.append("%s: layer blob %s hashes to %s" % (name, d, got))
            if name == BRIDGE and not bad:
                data, why = baked(layers, BAKED_GEN_MANIFEST)
                if data is None:
                    bad.append("%s: %s" % (name, why))
                else:
                    r["gen_manifest_sha256"] = sha256_bytes(data)
            problems += bad
            r["ok"] = not bad
        for entry in sorted(members):
            if entry not in TAR_FILES and entry not in referenced:
                problems.append("%s: %s is not a blob any pinned image references, nor one of %s" % (path.name, entry, ", ".join(TAR_FILES)))
        if "manifest.json" in members:
            problems += legacy_problems(path.name, read_small("manifest.json"), legacy)
        if "repositories" in members:
            try:
                repos = json.loads((read_small("repositories") or b"").decode("utf-8"))
            except ValueError:
                repos = None
            if repos != {}:
                problems.append("%s: repositories names %r: a save by ID names no tag" % (path.name, repos))
    return report, problems


# --- the generation and the recordings ----------------------------------------------------------------

def gen_problems(man: Dict[str, Any], contract_sha: str, labels: Dict[str, str], dbc_shas: Dict[str, str]) -> List[str]:
    """Why a generation is not the one the bridge pin was built from (its three labels), or not the recordings' and the
    repo's DBC (dbc_shas: who -> sha256)."""
    out = []
    if contract_sha != labels[CONTRACT_LABEL]:
        out.append("the generation's vss_contract.py hashes to %s, the bridge pin's label says %s" % (contract_sha, labels[CONTRACT_LABEL]))
    dbc = (man.get("inputs") or {}).get("slice.dbc")
    if dbc != labels[DBC_LABEL]:
        out.append("the generation's slice.dbc is %s, the bridge pin's label says %s" % (dbc, labels[DBC_LABEL]))
    cat = (man.get("kind4") or {}).get("catalog_digest")
    if cat != labels[CATALOG_LABEL]:
        out.append("the generation's catalog digest %s, the bridge pin's label says %s" % (cat, labels[CATALOG_LABEL]))
    for who, sha in sorted(dbc_shas.items()):
        if sha != dbc:
            out.append("the generation's slice.dbc is %s, %s's is %s" % (dbc, who, sha))
    return out


def baked_gen_problems(manifest_sha: str, report: Dict[str, Any]) -> List[str]:
    """Why a generation is not the one the bridge image was built from as a whole: its manifest.json (whose outputs list
    every generated file's sha256) is not the one the bridge image bakes in (check_images_tar's report). The three labels
    bind only the contract, the DBC and the catalog digest; this binds the rest (vss-databroker.json, the mapping, ...)."""
    baked = (report.get(BRIDGE) or {}).get("gen_manifest_sha256")
    if baked == manifest_sha:
        return []
    return ["the generation's manifest.json hashes to %s; the bridge image bakes in %s (%s): the generation is not the one the "
            "bridge image was built from" % (manifest_sha, baked, BAKED_GEN_MANIFEST)]


def gen_contents(files: Dict[str, bytes]) -> Tuple[Dict[str, Any], List[str]]:
    """A generation's files ({name: bytes}): exactly manifest.json and the outputs it lists, each with its listed sha256
    and size. Returns the manifest and the problems."""
    if "manifest.json" not in files:
        return {}, ["the generation has no manifest.json"]
    man = json.loads(files["manifest.json"].decode("utf-8"))
    outputs = man.get("outputs") if isinstance(man, dict) else None
    if not isinstance(outputs, dict) or not outputs or "vss_contract.py" not in outputs:
        return {}, ["the generation's manifest lists no outputs, or not vss_contract.py"]
    out = []
    want = sorted(list(outputs) + ["manifest.json"])
    if sorted(files) != want:
        out.append("the generation holds %s; its manifest lists %s" % (sorted(files), want))
    for name in sorted(outputs):
        o = outputs[name] if isinstance(outputs[name], dict) else {}
        data = files.get(name)
        if data is not None and (sha256_bytes(data) != o.get("sha256") or len(data) != o.get("bytes")):
            out.append("%s: sha256 %s, %d bytes; the generation's manifest says %s, %s bytes" % (
                name, sha256_bytes(data), len(data), o.get("sha256"), o.get("bytes")))
    return man, out


def log_name_of(line: Any) -> Tuple[Optional[str], Optional[str]]:
    """A recording's log by its manifest line (spec-2 2.1): (its name, None), the basename of recording.path when that is
    its source.generator's (LOG_NAMES); or (None, why) for any other pair, another name or a generator not in the table,
    the why naming both the generator and the log. The one rule of the stack and step 3 too (vss_setup.py's log_name is
    held equal to it by a test); the form of the path is not read."""
    rec = line.get("recording") if isinstance(line, dict) else None
    source = line.get("source") if isinstance(line, dict) else None
    gen = source.get("generator") if isinstance(source, dict) else None
    path = rec.get("path") if isinstance(rec, dict) else None
    base = path.rsplit("/", 1)[-1] if isinstance(path, str) else None
    if not isinstance(gen, str) or gen not in LOG_NAMES:
        return None, "its manifest line pairs generator %r with the log %r: a recording's generator is one of %s" % (
            gen, base, ", ".join(sorted(LOG_NAMES)))
    if base != LOG_NAMES[gen]:
        return None, "its manifest line pairs generator %r with the log %r: a %s recording's log is %s, and no other name is read" % (
            gen, base, gen, LOG_NAMES[gen])
    return base, None


def recording_contents(name: str, files: Dict[str, bytes]) -> Tuple[Dict[str, Any], List[str]]:
    """One recording's files: its log is the one its manifest line names (log_name_of: sigsim.log or carla.log), and hashes
    to the line's sha256 and to <log>.sha256's, which names no file but the log; the line names the recording. Returns its
    summary (its log and the log's sha256, with the DBC the line names) and the problems."""
    missing = [f for f in RECORDING_NEEDS if f not in files]
    if missing:
        return {}, ["recording %s: no %s" % (name, ", ".join(missing))]
    try:
        line = json.loads(files["manifest-line.json"].decode("utf-8"))
        want, dbc, lname = line["recording"]["sha256"], line["source"]["params"]["dbc_sha256"], line["name"]
    except (ValueError, KeyError, TypeError) as exc:
        return {}, ["recording %s: its manifest line does not parse (%s: %s)" % (name, type(exc).__name__, exc)]
    log, why = log_name_of(line)
    if log is None:
        return {}, ["recording %s: %s" % (name, why)]
    missing = [f for f in (log, log + ".sha256") if f not in files]
    if missing:
        return {}, ["recording %s: no %s" % (name, ", ".join(missing))]
    sha = sha256_bytes(files[log])
    listed = files[log + ".sha256"].decode("ascii", "replace").split()
    out = []
    if lname != name:
        out.append("recording %s: its manifest line names %r" % (name, lname))
    if sha != want:
        out.append("recording %s: %s hashes to %s, the manifest line's sha256 is %s" % (name, log, sha, want))
    if not listed or listed[0] != sha:
        out.append("recording %s: %s hashes to %s, %s.sha256 says %s" % (name, log, sha, log, listed[0] if listed else "nothing"))
    if len(listed) > 1 and listed[1:] != [log]:
        out.append("recording %s: %s.sha256 names %s, not %s" % (name, log, listed[1:], log))
    return {"recording": name, "log": log, "log_sha256": sha, "dbc_sha256": dbc, "files": sorted(files)}, out


def dir_files(d: Path) -> List[Tuple[str, Path]]:
    """A directory's files, sorted: regular files with names the upload accepts, nothing else."""
    try:
        entries = sorted(d.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        raise BundleError("%s: %s" % (d, exc)) from exc
    out = []
    for p in entries:
        if p.is_symlink() or not p.is_file() or not good_name(p.name):
            raise BundleError("%s holds %s, which is not a regular file named %s" % (d, p.name, NAME_RULE))
        out.append((p.name, p))
    return out


def write_tar(dest: Path, top: str, files: Sequence[Tuple[str, Path]]) -> None:
    """A ustar archive of files under top/: owner 0 with no owner name (no user name of the PC travels), 0644 files with
    their own mtimes, in the order given."""
    with tarfile.open(str(dest), "w", format=tarfile.USTAR_FORMAT) as tf:
        d = tarfile.TarInfo(top)
        d.type, d.mode, d.mtime = tarfile.DIRTYPE, 0o755, max(int(p.stat().st_mtime) for _n, p in files)
        tf.addfile(d)
        for name, src in files:
            data = Path(src).read_bytes()
            ti = tarfile.TarInfo("%s/%s" % (top, name))
            ti.size, ti.mode, ti.mtime = len(data), 0o644, int(Path(src).stat().st_mtime)
            tf.addfile(ti, io.BytesIO(data))


def read_tar(path: Path, top: str, f: Optional[Any] = None) -> Dict[str, bytes]:
    """The files of a tar write_tar wrote: the directory top/ and regular files top/<name> with names the upload
    accepts, each once; any other entry (a link, a device, a path outside top/, a name twice) is refused. f: an open file
    of path's bytes to read instead of opening path (verify's one handle per member)."""
    out: Dict[str, bytes] = {}
    if f is not None:
        f.seek(0)
    with (tarfile.open(fileobj=f, mode="r:") if f is not None else tarfile.open(str(path), "r:")) as tf:
        for m in tf:
            if m.isdir() and m.name.rstrip("/") == top:
                continue
            head, sep, name = m.name.partition("/")
            if not (m.isreg() and head == top and sep and good_name(name)):
                raise BundleError("%s: member %r is not a regular file %s/<name>" % (path.name, m.name, top))
            if name in out:
                raise BundleError("%s: %s/%s is in it twice" % (path.name, top, name))
            if m.size > SMALL:
                raise BundleError("%s: %s/%s holds %d bytes" % (path.name, top, name, m.size))
            f = tf.extractfile(m)
            out[name] = f.read() if f is not None else b""
    return out


# --- build -------------------------------------------------------------------------------------------

def build(out: Path, commit: str, docker: Docker, gen: Path, recordings: Path, cache: Path, python_src: Path) -> Dict[str, Any]:
    """Write the bundle into out (see the module docstring) and return bundle.json's document."""
    if not COMMIT.fullmatch(commit or ""):
        raise BundleError("--commit %r: the source commit as 40 lowercase hex digits (read in Git Bash)" % (commit,))
    out = outside_repo(out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise BundleError("%s exists and is not an empty directory" % out)
    images = load_json(IMAGES_FILE)
    pins, labels = arm64_pins(images), bridge_labels(images)
    py = python_pin(load_json(PYTHON_FILE))
    # every input, before anything is written
    gen_files = dir_files(gen)
    man, bad = gen_contents({n: p.read_bytes() for n, p in gen_files})
    if bad:
        raise BundleError("%s: %s" % (gen, "; ".join(bad)))
    rec_files: Dict[str, List[Tuple[str, Path]]] = {}
    rec_info: Dict[str, Dict[str, Any]] = {}
    dbc_shas = {"the repo's sdv/vss/slice.dbc": sha256_file(SLICE_DBC)}
    for name in RECORDINGS:
        files = dir_files(recordings / name)
        summary, bad = recording_contents(name, {n: p.read_bytes() for n, p in files})
        if bad:
            raise BundleError("; ".join(bad))
        rec_files[name], rec_info[name] = files, summary
        dbc_shas["recording " + name] = summary["dbc_sha256"]
    bad = gen_problems(man, sha256_file(gen / "vss_contract.py"), labels, dbc_shas)
    if bad:
        raise BundleError("the generation is not the bridge pin's or the recordings': " + "; ".join(bad))
    dbc_sha = man["inputs"]["slice.dbc"]
    dbc_src = cache / "dbc" / ("%s.dbc" % dbc_sha)
    if not dbc_src.is_file():
        raise BundleError("no cached DBC %s (stack.py prepare's resolve_dbc says how to export it)" % dbc_src)
    if sha256_file(dbc_src) != dbc_sha:
        raise BundleError("%s hashes to %s" % (dbc_src, sha256_file(dbc_src)))
    py_src = python_src / py["asset"]
    if not py_src.is_file():
        raise BundleError("no %s in %s (python-aarch64.json's asset)" % (py["asset"], python_src))
    got, size = sha256_file(py_src), py_src.stat().st_size
    if (got, size) != (py["sha256"], py["bytes"]):
        raise BundleError("%s: sha256 %s, %d bytes is not the pinned %s, %d bytes (sdv/sim/python-aarch64.json)" % (
            py["asset"], got, size, py["sha256"], py["bytes"]))
    for name, pin in pins.items():
        info, why = docker.inspect(pin["id"])
        bad = loaded_problems(name, pin, info, why, labels if name == BRIDGE else None)
        if bad:
            raise BundleError("; ".join(bad))
    # the members, then bundle.json last
    names = [IMAGES_TAR, GEN_TAR] + [REC_TAR % r for r in RECORDINGS] + ["%s.dbc" % dbc_sha, py["upload_name"]]
    created = not out.exists()
    out.mkdir(parents=True, exist_ok=True)
    try:
        p = docker.run(["save", "-o", str(out / IMAGES_TAR)] + [pin["id"] for pin in pins.values()], timeout=3600)
        if p.returncode != 0:
            raise BundleError("docker save: exit %d: %s" % (p.returncode, tail(p.stderr or p.stdout)))
        report, bad = check_images_tar(out / IMAGES_TAR, pins)
        if bad:
            raise BundleError("the saved tar: " + "; ".join(bad))
        bad = baked_gen_problems(sha256_file(gen / "manifest.json"), report)
        if bad:
            raise BundleError("; ".join(bad))
        write_tar(out / GEN_TAR, GEN_TOP, gen_files)
        for r in RECORDINGS:
            write_tar(out / (REC_TAR % r), r, rec_files[r])
        shutil.copyfile(str(dbc_src), str(out / names[-2]))
        shutil.copyfile(str(py_src), str(out / py["upload_name"]))
        roles = ["images", "gen"] + ["recording"] * len(RECORDINGS) + ["dbc", "python"]
        members: List[Dict[str, Any]] = []
        for name, role in zip(names, roles):
            members.append({"name": name, "role": role, "bytes": (out / name).stat().st_size, "sha256": sha256_file(out / name)})
        if members[-2]["sha256"] != dbc_sha or members[-1]["sha256"] != py["sha256"]:
            raise BundleError("a copied member does not hash to its source")
        members[0]["images"] = {n: {"id": pin["id"], "config_digest": pin["config_digest"], "tag": pin.get("tag")} for n, pin in pins.items()}
        members[1].update(labels=labels, contract_sha256=labels[CONTRACT_LABEL], dbc_sha256=dbc_sha)
        for m, r in zip(members[2:2 + len(RECORDINGS)], RECORDINGS):
            m.update(recording=r, log=rec_info[r]["log"], log_sha256=rec_info[r]["log_sha256"], files=rec_info[r]["files"])
        members[-1].update(asset=py["asset"], release=py["release"])
        doc = {"format": FORMAT,
               "about": "The upload bundle for the VSS slice on an aarch64 instance (sdv/stack/bundle.py build; SDV Phase 3 WP1): "
                        "check it with `bundle.py verify --in <dir>` from the commit named here.",
               "commit": commit, "built_utc": utc_now(), "members": members,
               "pins": {key: sha256_file(p) for key, p in pin_files()}, "images_report": report}
        tmp = out / (BUNDLE_JSON + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(out / BUNDLE_JSON))
    except BaseException:
        for name in names + [BUNDLE_JSON, BUNDLE_JSON + ".tmp"]:
            try:
                (out / name).unlink()
            except FileNotFoundError:
                pass
        if created:
            try:
                out.rmdir()
            except OSError:
                pass
        raise
    return doc


def build_record(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {"tool": "bundle.py build", "ok": True, "commit": doc["commit"],
            "members": [{k: m[k] for k in ("name", "role", "bytes", "sha256")} for m in doc["members"]]}


# --- verify ------------------------------------------------------------------------------------------

def verify(in_dir: Path, docker: Docker, loaded: bool) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"tool": "bundle.py verify", "loaded": loaded, "ok": False, "problems": []}
    try:
        _verify(in_dir, docker, loaded, rec)
    except BundleError as exc:
        rec["problems"].append(str(exc))
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        rec["problems"].append("%s: %s" % (type(exc).__name__, exc))
    rec["ok"] = not rec["problems"]
    return rec


def _verify(in_dir: Path, docker: Docker, loaded: bool, rec: Dict[str, Any]) -> None:
    with contextlib.ExitStack() as opened:          # every member's one handle, closed at the end
        _verify_members(in_dir, docker, loaded, rec, opened)


def _verify_members(in_dir: Path, docker: Docker, loaded: bool, rec: Dict[str, Any], opened: contextlib.ExitStack) -> None:
    """verify's checks (module docstring, VERIFY). Each member is opened once: its sha256 is taken through that handle and
    its content is read through it, so the bytes checked are the bytes bundle.json names; at the end each is read again
    through it and its path must still name that file."""
    problems: List[str] = rec["problems"]
    doc = load_json(in_dir / BUNDLE_JSON)
    if not isinstance(doc, dict):
        raise BundleError("bundle.json is not an object")
    if doc.get("format") != FORMAT:
        problems.append("bundle.json: format %r, this tool reads %d" % (doc.get("format"), FORMAT))
    commit = doc.get("commit")
    rec["commit"] = commit if isinstance(commit, str) and COMMIT.fullmatch(commit) else None
    if rec["commit"] is None:
        problems.append("bundle.json: commit %r is not 40 lowercase hex digits" % (commit,))
    members = doc.get("members")
    if not isinstance(members, list) or not all(isinstance(m, dict) for m in members):
        raise BundleError("bundle.json has no member list")
    images = load_json(IMAGES_FILE)
    pins, labels = arm64_pins(images), bridge_labels(images)
    py = python_pin(load_json(PYTHON_FILE))
    # 0. the pin files the bundle was built from are the repo's: the content checks below use the repo's
    built_from: Dict[str, Any] = doc["pins"] if isinstance(doc.get("pins"), dict) else {}
    for key, pin_path in pin_files():
        here = sha256_file(pin_path)
        if built_from.get(key) != here:
            problems.append("bundle.json: built against %s %s; this repo's hashes to %s" % (key, built_from.get(key), here))
    # 1. every member against bundle.json
    fixed = {IMAGES_TAR: "images", GEN_TAR: "gen", py["upload_name"]: "python"}
    fixed.update({REC_TAR % r: "recording" for r in RECORDINGS})
    held: Dict[str, Tuple[str, Path, Any, str]] = {}
    listed: List[str] = []
    rec["members"] = []
    for m in members:
        name, role = m.get("name"), m.get("role")
        entry: Dict[str, Any] = {"name": name, "role": role}
        rec["members"].append(entry)
        if not good_name(name):
            problems.append("member name %r: the upload takes only %s names, never . or .." % (name, NAME_RULE))
            continue
        if name in listed:
            problems.append("%s: listed twice in bundle.json" % name)
            continue
        listed.append(name)
        want_role = fixed.get(name, "dbc" if re.fullmatch(r"[0-9a-f]{64}\.dbc", name) else None)
        if want_role is None or role != want_role:
            problems.append("%s: role %r; this bundle carries %s" % (name, role, "no such member" if want_role is None else want_role))
            continue
        path = in_dir / name
        if not path.is_file():
            problems.append("%s: missing" % name)
            continue
        f = opened.enter_context(open(str(path), "rb"))
        entry["bytes"] = os.fstat(f.fileno()).st_size
        if entry["bytes"] != m.get("bytes"):
            problems.append("%s: %d bytes, bundle.json says %s" % (name, entry["bytes"], m.get("bytes")))
            continue
        got = sha256_stream(f)
        entry["sha256_ok"] = got == m.get("sha256")
        if not entry["sha256_ok"]:
            problems.append("%s: sha256 %s, bundle.json says %s" % (name, got, m.get("sha256")))
            continue
        held[name] = (role, path, f, got)
    for name in sorted(set(fixed) - set(listed)):
        problems.append("%s: not in bundle.json" % name)
    if len([n for n in listed if n.endswith(".dbc")]) != 1:
        problems.append("bundle.json lists %d DBC members, the bundle carries one" % len([n for n in listed if n.endswith(".dbc")]))
    extra = sorted(set(os.listdir(str(in_dir))) - set(listed) - {BUNDLE_JSON})
    for name in extra:
        problems.append("%s: in the bundle directory, not in bundle.json" % name)
    # 2. each held member's content against the repo's pins
    contents: Dict[str, Any] = {}
    rec["contents"] = contents
    by_role: Dict[str, List[Tuple[str, Path, Any, str]]] = {}
    for name, (role, path, f, got) in held.items():
        by_role.setdefault(role, []).append((name, path, f, got))

    def guarded(what: str, fn: Any) -> None:
        try:
            fn()
        except BundleError as exc:
            problems.append(str(exc))
        except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
            problems.append("%s: %s: %s" % (what, type(exc).__name__, exc))

    for name, path, f, _got in by_role.get("images", []):
        def images_tar(path: Path = path, f: Any = f) -> None:
            report, bad = check_images_tar(path, pins, f)
            rec["images"] = report
            problems.extend(bad)
        guarded(name, images_tar)
    dbc_shas = {"the repo's sdv/vss/slice.dbc": sha256_file(SLICE_DBC)}
    for name, path, f, _got in by_role.get("recording", []):
        def recording(name: str = name, path: Path = path, f: Any = f) -> None:
            r = name[len("rec-"):-len(".tar")]
            info, bad = recording_contents(r, read_tar(path, r, f))
            problems.extend(bad)
            if info:
                contents[name] = {k: info[k] for k in ("recording", "log", "log_sha256", "dbc_sha256")}
                dbc_shas["recording " + r] = info["dbc_sha256"]
        guarded(name, recording)
    gen_dbc: List[str] = []
    for name, path, f, _got in by_role.get("gen", []):
        def generation(path: Path = path, f: Any = f) -> None:
            files = read_tar(path, GEN_TOP, f)
            man, bad = gen_contents(files)
            problems.extend(bad)
            if man:
                contract = sha256_bytes(files.get("vss_contract.py", b""))
                problems.extend(gen_problems(man, contract, labels, dbc_shas))
                gen_dbc.append(str((man.get("inputs") or {}).get("slice.dbc")))
                mine = sha256_bytes(files["manifest.json"])
                contents[GEN_TAR] = {"contract_sha256": contract, "dbc_sha256": gen_dbc[0],
                                     "catalog_digest": (man.get("kind4") or {}).get("catalog_digest"), "manifest_sha256": mine}
                if ((rec.get("images") or {}).get(BRIDGE) or {}).get("gen_manifest_sha256") is not None:
                    # (else the image tar was not held, or its bridge failed a check: that problem is named already)
                    problems.extend(baked_gen_problems(mine, rec["images"]))
        guarded(name, generation)
    for name, _path, _f, got in by_role.get("dbc", []):
        if name != "%s.dbc" % got:
            problems.append("%s: hashes to %s, not its name" % (name, got))
        elif gen_dbc and got != gen_dbc[0]:
            problems.append("%s: not the generation's slice.dbc %s" % (name, gen_dbc[0]))
    for name, _path, f, got in by_role.get("python", []):
        size = os.fstat(f.fileno()).st_size
        if (got, size) != (py["sha256"], py["bytes"]):
            problems.append("%s: sha256 %s, %d bytes is not the pinned %s, %d bytes" % (name, got, size, py["sha256"], py["bytes"]))
        else:
            contents[name] = {"asset": py["asset"], "release": py["release"]}
    # 3. the bytes checked are still the bytes hashed, and each path still names the file that was read
    for name, (_role, path, f, got) in sorted(held.items()):
        f.seek(0)
        again, now = sha256_stream(f), os.fstat(f.fileno())
        try:
            there = os.stat(str(path))
            same = (there.st_dev, there.st_ino) == (now.st_dev, now.st_ino)
        except OSError:
            same = False
        if again != got or not same:
            problems.append("%s: changed while it was verified (%s)" % (
                name, "its bytes now hash to %s" % again if again != got else "the path now names another file"))
    # 4. with --loaded: the daemon's images
    if loaded:
        rec["docker"] = docker.facts()
        rec["loaded_images"] = {}
        for name, pin in pins.items():
            info, why = docker.inspect(pin["id"])
            problems.extend(loaded_problems(name, pin, info, why, labels if name == BRIDGE else None))
            rec["loaded_images"][name] = None if info is None else {
                "id": info.get("Id"), "platform": "%s/%s" % (info.get("Os"), info.get("Architecture"))}


def verify_upstream(docker: Docker) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"tool": "bundle.py verify-upstream", "ok": False, "images": {}, "problems": []}
    try:
        images = load_json(IMAGES_FILE)
        for name, u in sorted(images["upstream"].items()):
            info, why = docker.inspect(upstream_ref(u))
            rec["problems"] += upstream_problems(name, u, info, why)
            rec["images"][name] = None if info is None else {
                "ref": upstream_ref(u), "id": info.get("Id"), "revision": labels_of(info).get(REVISION),
                "platform": "%s/%s" % (info.get("Os"), info.get("Architecture")),
                "in_repo_digests": upstream_ref(u) in (info.get("RepoDigests") or [])}
    except BundleError as exc:
        rec["problems"].append(str(exc))
    except (KeyError, TypeError, AttributeError) as exc:
        rec["problems"].append("images.json: %s: %s" % (type(exc).__name__, exc))
    rec["ok"] = not rec["problems"]
    return rec


# --- command line ------------------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the bundle into --out (the PC)")
    b.add_argument("--out", required=True, help="the bundle's directory, outside the repo, empty or absent")
    b.add_argument("--commit", required=True, help="the source commit (40 hex digits, read in Git Bash)")
    b.add_argument("--gen", default=os.environ.get("SDV_GEN", str(REPO / "sdv-out" / "gen")))
    b.add_argument("--recordings", default="~/sdv-recordings", help="the recordings' root (read only)")
    b.add_argument("--cache", default=os.environ.get("SDV_CACHE", "~/sdv-cache"), help="where dbc/<sha256>.dbc is")
    b.add_argument("--python-src", default=os.environ.get("SDV_BUNDLE_SRC", "~/sdv-bundle-src"),
                   help="where python-aarch64.json's asset was downloaded")
    v = sub.add_parser("verify", help="check a bundle directory against bundle.json and the repo's pins")
    v.add_argument("--in", dest="in_dir", required=True)
    v.add_argument("--loaded", action="store_true", help="also check the loaded images in the daemon")
    u = sub.add_parser("verify-upstream", help="check the four pulled upstream images (never pulls)")
    for p in (b, v, u):
        p.add_argument("--docker", default="docker", help="the docker argv prefix, e.g. 'sudo -n docker' (default: docker)")
    a = ap.parse_args(argv)
    tool = "bundle.py " + a.cmd
    try:
        docker = Docker(a.docker)
        if a.cmd == "build":
            doc = build(Path(a.out).expanduser(), a.commit, docker, Path(a.gen).expanduser(), Path(a.recordings).expanduser(),
                        Path(a.cache).expanduser(), Path(a.python_src).expanduser())
            print(json.dumps(build_record(doc), sort_keys=True))
            return 0
        rec = verify(Path(a.in_dir).expanduser(), docker, a.loaded) if a.cmd == "verify" else verify_upstream(docker)
    except (BundleError, OSError, ValueError, tarfile.TarError) as exc:
        if a.cmd == "build":
            print("bundle.py: %s" % exc, file=sys.stderr)
            return 1
        rec = {"tool": tool, "ok": False, "problems": [str(exc)]}
    print(json.dumps(rec, sort_keys=True))
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
