#!/usr/bin/env python3
"""build_image.py -- build the twin connector's container image, twin-connector, pin it, and scan its arm64 layers
(sdv/connector; SDV Phase 4 WP3).

Run in WSL, from the repo root, where Docker Engine runs. Never pushed anywhere.

    python3 sdv/connector/build_image.py build [--arch amd64|arm64|all] [--gen DIR] [--frozen FILE] [--smoke] [--write-pins] [--out FILE]
    python3 sdv/connector/build_image.py build --burst [--smoke] [--out FILE]
    python3 sdv/connector/build_image.py scan --out FILE [--work DIR]

build  It stages a context outside the repo (under ~/sdv-cache/connector-build/, SDV_CACHE moves the root; removed
       after the build): sdv/connector/Dockerfile, the architecture's lock as requirements.lock, and app/ with exactly
       the files the image runs, side by side (STAGED): the connector's modules, appstate.schema.json and the frozen
       allowlist twin_allowlist.py. No burst tool (its image is another: build --burst, below), no probe, no generator,
       no source list, nothing of a device.
       BEFORE it builds, the gate that nothing at run time repeats: the frozen module must import, the sha256 it
       records for the catalogue's id file, the source list and the schema must be those of the files this build
       reads (check_inputs), and it must be byte for byte what sdv/connector/gen_allowlist.py generates from them
       today (fresh_check: that generator's --check, run with the vss-tools venv's python, SDV_VENV). A stale or a
       hand-edited module is refused; no image is built from it.
       It builds with `docker buildx build -q --platform linux/<arch> --provenance=false --sbom=false --load` (no
       attestation: it would carry the build's time and give every rebuild of unchanged inputs a new image ID; arm64
       under the host's qemu-aarch64 binfmt registration, no privileged container), tags amd64 as TAG and arm64 as
       TAG-arm64, labels the image with the allowlist's version and digest and the catalogue's sha256, and prints one
       JSON record per architecture: the image ID, the tag, the base, the lock's and the Dockerfile's sha256, the
       sha256 of every staged file. An image the tag named before and the rebuild left untagged is removed (the tag
       is this script's alone); nothing else is pruned.
       --smoke (amd64 only) then runs the image once with no network and a read-only root: it imports the SDK, the
       databroker client and every staged module and prints what it found (SMOKE). --write-pins (with --arch all)
       reads each image's pin back from the daemon, {id, config_digest, tag, lock} as sdv/arm64/arm64.py reads the
       slice's, and writes sdv/stack/images.json's top-level `connector` entry: both architectures' pins and the three
       labels. The connector is in no deploy set and no bundle: the PC runs the amd64 image by ID in the stack's
       opt-in runs, and the arm64 image runs nowhere before Phase 5.
build --burst
       ANOTHER IMAGE, and nothing of the connector's: the breaker's burst tool (sdv/cloud/burst, prep gap y), TEST ONLY.
       A context of its own (under ~/sdv-cache/burst-build/, removed after the build): sdv/cloud/burst/Dockerfile,
       the connector's x86_64 lock as requirements.lock, and app/ with the tool's two files and the four modules of
       the connector they import by name (BURST_MODULES, BURST_FROM_CONNECTOR). The same base by the same index
       digest (a Dockerfile on another base is refused) and the same lock; amd64 only; its own tag, twin-burst. It
       takes no allowlist and no label of the connector's. IT IS NEVER PINNED: --write-pins, --arch arm64 and --arch
       all are refused with it, no function here writes a pin for its tag, and nothing that loads, bundles or scans
       reads it. The PC runs it by the ID the build prints. Nothing of it is staged into the connector's context
       (staged() holds no file of that directory), and this script loads nothing of it: it copies files.
scan   The arm64 pin's layers through sdv/arm64's scanner, with that tool's own functions and gate for a local image:
       the image saved from the daemon by its pinned ID, its manifest and config checked against the pin, every ELF in
       its layers read; 0 unguarded LSE words, 0 LDAPR and 0 LOR, its first layers the pinned base's arm64 layers, at
       least the base's objects. Writes one JSON record (outside the repo). Information for Phase 5: the Orin's cores
       have the extensions an ARMv8.0 core lacks.

Standard library only; the frozen allowlist is loaded to read what it records, and sdv/arm64/arm64.py for the pins and
the scan. Does not demonstrate: that the image connects to anything (the opt-in broker tests run it against a local
broker); that the arm64 image runs on any core (it is built under emulation and scanned, never started); that the SDK's
ARMv8.2 crypto code is dispatched by the CPU's capabilities (untraced); anything about a registry (there is none).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

TAG = "sdv-local/twin-connector:0.1.0"
DOCKERFILE = HERE / "Dockerfile"
ARCHES = ("amd64", "arm64")
TAGS: Dict[str, str] = {"amd64": TAG, "arm64": TAG + "-arm64"}
LOCKS: Dict[str, Path] = {"amd64": HERE / "requirements.lock", "arm64": HERE / "requirements.aarch64.lock"}
PLATFORMS = {"amd64": "linux/amd64", "arm64": "linux/arm64"}
# What the image runs, and nothing else of this directory: the entry point and every module it imports by name.
MODULES = ("appstate.py", "config.py", "connector.py", "envelope.py", "limiter.py", "limits.py", "pathset.py", "shadowdoc.py",
           "source.py", "spool.py", "startstamp.py", "status.py", "topics.py", "uplink.py", "uplink_aws.py")
FROZEN_NAME = "twin_allowlist.py"
SCHEMA = REPO / "sdv" / "apps" / "hard-brake-hazard" / "appstate.schema.json"
SOURCE_LIST = HERE / "twin_allowlist.json"
GEN_ALLOWLIST = HERE / "gen_allowlist.py"
DEFAULT_GEN = REPO / "sdv-out" / "gen"
DEFAULT_FROZEN = REPO / "sdv-out" / "twin" / FROZEN_NAME
IMAGES_FILE = REPO / "sdv" / "stack" / "images.json"
ARM64_TOOL = REPO / "sdv" / "arm64" / "arm64.py"
CACHE = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser()
LABELS = {"allowlist_version": "sdv.twin.allowlist_version", "allowlist_digest": "sdv.twin.allowlist_digest",
          "catalogue_sha256": "sdv.twin.catalogue_sha256"}
BUILD_ARGS = {"allowlist_version": "SDV_ALLOWLIST_VERSION", "allowlist_digest": "SDV_ALLOWLIST_DIGEST",
              "catalogue_sha256": "SDV_CATALOGUE_SHA256"}
PIN_KEYS = ("id", "config_digest", "tag", "lock")
ENTRY_ABOUT = ("The twin connector's images (sdv/connector/build_image.py build --arch all --write-pins; SDV Phase 4 WP3), in the "
               "bridge entry's shape, one member per architecture. Each bakes in the frozen allowlist: the labels are the allowlist "
               "version and digest and the sha256 of the catalogue's id file it was generated from, so a new generation, a new "
               "allowlist or a changed connector module means a rebuild and new pins. Built locally and never pushed to any "
               "registry; in no bundle and no deploy set. The PC's opt-in runs start the amd64 image by this ID; the arm64 image "
               "is built under emulation, scanned, and runs nowhere before Phase 5.")
# The burst tool's own image (prep gap y): test only, another directory, another Dockerfile, another tag, never a pin.
BURST_DIR = REPO / "sdv" / "cloud" / "burst"
BURST_DOCKERFILE = BURST_DIR / "Dockerfile"
BURST_TAG = "sdv-local/twin-burst:test-only"
BURST_MODULES = ("burst.py", "burst_link.py")                                  # the tool's own two files
BURST_FROM_CONNECTOR = ("limits.py", "topics.py", "uplink.py", "uplink_aws.py")    # ... and what they import by name
BURST_SMOKE = ("import importlib.metadata as md, json, os, sys; import awscrt, awsiot; import burst, burst_link, limits, topics, uplink, "
               "uplink_aws; uplink_aws.load_sdk(); "
               "print(json.dumps({'python': sys.version.split()[0], 'uid': os.getuid(), 'awsiotsdk': md.version('awsiotsdk'), "
               "'awscrt': md.version('awscrt'), 'ceilings': burst.CEILINGS, 'app': sorted(os.listdir('/app'))}, sort_keys=True))")
# --smoke: what the image must be able to import, and what it says of itself. No network, nothing of a device.
SMOKE = ("import importlib.metadata as md, json, os, sys; import awscrt, awsiot, grpc, kuksa_client; "
         "import appstate, config, connector, envelope, limiter, limits, pathset, shadowdoc, source, spool, startstamp, topics, uplink, "
         "uplink_aws, twin_allowlist as t; uplink_aws.load_sdk(); "
         "print(json.dumps({'python': sys.version.split()[0], 'uid': os.getuid(), 'awsiotsdk': md.version('awsiotsdk'), "
         "'awscrt': md.version('awscrt'), 'kuksa_client': md.version('kuksa-client'), 'allowlist_version': t.VERSION, "
         "'allowlist_digest': '0x%08X' % t.DIGEST, 'catalogue_sha256': t.CATALOGUE_SHA256, 'paths': len(t.PATHS), "
         "'app': sorted(os.listdir('/app'))}, sort_keys=True))")


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def staged(frozen: Path) -> Dict[str, Path]:
    """name in /app -> source: the modules, the AppState schema, the frozen allowlist. Flat, and nothing else."""
    out = {name: HERE / name for name in MODULES}
    out[SCHEMA.name] = SCHEMA
    out[FROZEN_NAME] = frozen
    return out


def load_frozen(frozen: Path) -> Any:
    """The frozen module, imported by its file to read what it records (it checks its own parts as it is imported)."""
    if not frozen.is_file():
        raise BuildError("no frozen allowlist %s: run ~/sdv-venv/bin/python sdv/connector/gen_allowlist.py first" % frozen)
    spec = importlib.util.spec_from_file_location("_twin_allowlist_for_build_image", str(frozen))
    if spec is None or spec.loader is None:
        raise BuildError("the frozen allowlist %s cannot be loaded" % frozen)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 -- its own check, or a syntax error: either way it is not built from
        raise BuildError("the frozen allowlist %s does not import (%s): generate it anew" % (frozen, type(exc).__name__)) from None
    finally:
        sys.dont_write_bytecode = saved
    return mod


def check_inputs(gen: Path, frozen: Path) -> Dict[str, str]:
    """The labels of an image built from `frozen`, or BuildError when the module was not made from the files this build
    reads: the catalogue's id file in `gen`, the source list, the AppState schema (each by the sha256 it records)."""
    mod = load_frozen(frozen)
    for path, recorded in ((gen / "vss-ids.vspec", mod.CATALOGUE_SHA256), (SOURCE_LIST, mod.SOURCE_SHA256), (SCHEMA, mod.SCHEMA_SHA256)):
        if not path.is_file():
            raise BuildError("%s is missing" % path)
        if sha256_file(path) != recorded:
            raise BuildError("%s (sha256 %s) is not the one %s was generated from (%s): run sdv/connector/gen_allowlist.py again"
                             % (path.name, sha256_file(path), frozen.name, recorded))
    return {"allowlist_version": str(int(mod.VERSION)), "allowlist_digest": "0x%08X" % int(mod.DIGEST),
            "catalogue_sha256": str(mod.CATALOGUE_SHA256)}


def fresh_check(gen: Path, frozen: Path) -> None:
    """gen_allowlist.py --check: the module is byte for byte what the generator makes of the catalogue, the source list
    and the schema today. Run with the vss-tools venv's python (the id file is YAML); without that venv, no build."""
    python = Path(os.environ.get("SDV_VENV", "~/sdv-venv")).expanduser() / "bin" / "python"
    if not python.is_file():
        raise BuildError("the build's gate needs the vss-tools venv (%s is missing; SDV_VENV, sdv/vss/README.md): gen_allowlist.py "
                         "--check compares the frozen allowlist with a fresh generation" % python)
    p = subprocess.run([str(python), "-B", str(GEN_ALLOWLIST), "--check", "--gen", str(gen), "--source", str(SOURCE_LIST),
                        "--schema", str(SCHEMA), "--out", str(frozen)], capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise BuildError("%s is not a fresh generation (gen_allowlist.py --check exit %d): %s"
                         % (frozen, p.returncode, (p.stderr or p.stdout).strip()[-800:]))


def docker(*args: str, timeout: float = 120) -> str:
    p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise BuildError("docker %s: exit %d: %s" % (" ".join(args[:2]), p.returncode, (p.stderr or p.stdout).strip()[-2000:]))
    return p.stdout.strip()


def image_id(ref: str) -> Optional[str]:
    p = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", ref], capture_output=True, text=True, timeout=60)
    return p.stdout.strip() if p.returncode == 0 else None


def build_args(ids: Dict[str, str], ctx: Path, arch: str) -> List[str]:
    """docker's arguments: buildx for exactly one platform, no attestation, loaded into the local store. Never pushed."""
    args = ["buildx", "build", "-q", "--platform", PLATFORMS[arch], "--provenance=false", "--sbom=false", "--load"]
    for key in ("allowlist_version", "allowlist_digest", "catalogue_sha256"):
        args += ["--build-arg", "%s=%s" % (BUILD_ARGS[key], ids[key])]
    return args + ["-f", str(ctx / "Dockerfile"), "-t", TAGS[arch], str(ctx)]


def build(gen: Path, frozen: Path, arch: str = "amd64", smoke: bool = False) -> Dict[str, Any]:
    if arch not in ARCHES:
        raise BuildError("unknown --arch %r (known: %s)" % (arch, ", ".join(ARCHES)))
    if smoke and arch != "amd64":
        raise BuildError("--smoke with --arch %s: an emulated smoke shows nothing of an arm64 core; the arm64 image is scanned" % arch)
    tag, lock = TAGS[arch], LOCKS[arch]
    ids = check_inputs(gen, frozen)
    fresh_check(gen, frozen)
    root = CACHE / "connector-build"
    if str(root.resolve()).startswith(str(REPO.resolve()) + os.sep):
        raise BuildError("the staging root %s is inside the repo" % root)
    root.mkdir(parents=True, exist_ok=True)
    ctx = Path(tempfile.mkdtemp(prefix="ctx-", dir=str(root)))
    try:
        files = staged(frozen)
        (ctx / "app").mkdir()
        for name, src in files.items():
            shutil.copyfile(src, ctx / "app" / name)
        shutil.copyfile(DOCKERFILE, ctx / "Dockerfile")
        shutil.copyfile(lock, ctx / "requirements.lock")
        before = image_id(tag)
        args = build_args(ids, ctx, arch)
        docker(*args, timeout=3600)
        iid = image_id(tag)
        if iid is None:
            raise BuildError("the build left no image tagged %s" % tag)
        record: Dict[str, Any] = {
            "image_id": iid, "tag": tag, "arch": arch, "platform": PLATFORMS[arch],
            "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "base": next(ln.split(None, 1)[1] for ln in DOCKERFILE.read_text(encoding="utf-8").splitlines() if ln.startswith("FROM ")),
            "build": "docker " + " ".join(a if not a.startswith(str(ctx)) else "<ctx>" + a[len(str(ctx)):] for a in args),
            "labels": ids, "dockerfile_sha256": sha256_file(DOCKERFILE), "lock": lock.relative_to(REPO).as_posix(),
            "lock_sha256": sha256_file(lock), "staged": {name: sha256_file(src) for name, src in sorted(files.items())}}
        if before is not None and before != iid:
            if image_id(before) is None:
                record["replaced_image"] = {"id": before, "left": "gone (the image store dropped it with its tag)"}
            elif json.loads(docker("image", "inspect", "--format", "{{json .RepoTags}}", before) or "[]") == []:
                docker("image", "rm", before)
                record["replaced_image"] = {"id": before, "left": "removed (untagged by this build)"}
            else:
                record["replaced_image"] = {"id": before, "left": "kept (another tag names it)"}
        if smoke:
            out = docker("run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                         "--entrypoint", "python", iid, "-c", SMOKE)
            record["smoke"] = json.loads(out.splitlines()[-1])
        return record
    finally:
        shutil.rmtree(ctx, ignore_errors=True)


# --- the burst tool's own image ------------------------------------------------------------------------

def _from_line(dockerfile: Path) -> str:
    return next(ln.split(None, 1)[1] for ln in dockerfile.read_text(encoding="utf-8").splitlines() if ln.startswith("FROM "))


def burst_staged() -> Dict[str, Path]:
    """name in /app -> source, for the burst tool's image and for no other: its two files and the connector's four."""
    out = {name: BURST_DIR / name for name in BURST_MODULES}
    out.update({name: HERE / name for name in BURST_FROM_CONNECTOR})
    return out


def build_burst(smoke: bool = False) -> Dict[str, Any]:
    """The burst tool's test-only image, amd64, from the connector's base and x86_64 lock. Never pinned: the record
    this returns is printed, and no entry of images.json is written from it."""
    tag, lock = BURST_TAG, LOCKS["amd64"]
    if _from_line(BURST_DOCKERFILE) != _from_line(DOCKERFILE):
        raise BuildError("%s is not on the connector's base (the FROM line of %s): the burst image is built from the same base and lock"
                         % (BURST_DOCKERFILE.name, DOCKERFILE.relative_to(REPO).as_posix()))
    root = CACHE / "burst-build"
    if str(root.resolve()).startswith(str(REPO.resolve()) + os.sep):
        raise BuildError("the staging root %s is inside the repo" % root)
    root.mkdir(parents=True, exist_ok=True)
    ctx = Path(tempfile.mkdtemp(prefix="ctx-", dir=str(root)))
    try:
        files = burst_staged()
        (ctx / "app").mkdir()
        for name, src in files.items():
            shutil.copyfile(src, ctx / "app" / name)
        shutil.copyfile(BURST_DOCKERFILE, ctx / "Dockerfile")
        shutil.copyfile(lock, ctx / "requirements.lock")
        before = image_id(tag)
        args = ["buildx", "build", "-q", "--platform", PLATFORMS["amd64"], "--provenance=false", "--sbom=false", "--load",
                "-f", str(ctx / "Dockerfile"), "-t", tag, str(ctx)]
        docker(*args, timeout=3600)
        iid = image_id(tag)
        if iid is None:
            raise BuildError("the build left no image tagged %s" % tag)
        record: Dict[str, Any] = {
            "image_id": iid, "tag": tag, "arch": "amd64", "platform": PLATFORMS["amd64"], "pinned": False,
            "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "base": _from_line(BURST_DOCKERFILE),
            "build": "docker " + " ".join(a if not a.startswith(str(ctx)) else "<ctx>" + a[len(str(ctx)):] for a in args),
            "dockerfile": BURST_DOCKERFILE.relative_to(REPO).as_posix(), "dockerfile_sha256": sha256_file(BURST_DOCKERFILE),
            "lock": lock.relative_to(REPO).as_posix(), "lock_sha256": sha256_file(lock),
            "staged": {name: sha256_file(src) for name, src in sorted(files.items())}}
        if before is not None and before != iid and image_id(before) is not None:
            if json.loads(docker("image", "inspect", "--format", "{{json .RepoTags}}", before) or "[]") == []:
                docker("image", "rm", before)                       # the tag is this script's alone; nothing else is pruned
                record["replaced_image"] = {"id": before, "left": "removed (untagged by this build)"}
        if smoke:
            out = docker("run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                         "--entrypoint", "python", iid, "-c", BURST_SMOKE)
            record["smoke"] = json.loads(out.splitlines()[-1])
        return record
    finally:
        shutil.rmtree(ctx, ignore_errors=True)


# --- pins and the arm64 scan: sdv/arm64/arm64.py's own functions -------------------------------------

def arm64_tool() -> Any:
    """sdv/arm64/arm64.py, loaded by its file (it brings the stack's and the bridge's modules onto sys.path itself)."""
    name = "_sdv_arm64_for_connector_build"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(ARM64_TOOL))
    if spec is None or spec.loader is None:
        raise BuildError("cannot load %s" % ARM64_TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[name]
        raise
    return mod


def pin_of(record: Dict[str, Any]) -> Dict[str, str]:
    """One built image's pin, read back from the daemon: its ID and the config digest of the manifest that ID names in a
    `docker save` stream (each hash-checked by sdv/arm64's reader), which must be of the architecture it was built for."""
    tool = arm64_tool()
    man, cfg = tool.saved_from_daemon(record["image_id"])
    if cfg.get("architecture") != record["arch"] or cfg.get("os") != "linux":
        raise BuildError("%s (%s) is %s/%s, not %s" % (record["image_id"], record["tag"], cfg.get("os"), cfg.get("architecture"),
                                                       record["platform"]))
    return {"id": record["image_id"], "config_digest": man["config"]["digest"], "tag": record["tag"], "lock": record["lock"]}


def with_pins(images: Dict[str, Any], pins: Dict[str, Dict[str, str]], labels: Dict[str, str]) -> Dict[str, Any]:
    """images.json with the top-level `connector` entry set whole: both architectures' pins and the labels. No other
    entry is touched."""
    if sorted(pins) != sorted(ARCHES):
        raise BuildError("the connector entry takes both architectures' pins from one run (--arch all): got %s" % sorted(pins))
    out = json.loads(json.dumps(images))
    out["connector"] = dict({"about": ENTRY_ABOUT}, **{arch: {k: pins[arch][k] for k in PIN_KEYS} for arch in ARCHES},
                            labels={LABELS[k]: v for k, v in sorted(labels.items())})
    return out


def scan(work: Path) -> Dict[str, Any]:
    """The arm64 pin's layers through sdv/arm64's scanner and its gate for one local image."""
    tool = arm64_tool()
    a64 = tool.a64
    images = json.loads(IMAGES_FILE.read_text(encoding="utf-8"))
    pin = (images.get("connector") or {}).get("arm64")
    if not isinstance(pin, dict):
        raise BuildError("images.json has no connector.arm64 pin: build --arch all --write-pins first")
    work.mkdir(parents=True, exist_ok=True)
    base = images["base"]["python"]
    client = a64.RegistryClient(base["repo"])
    index = tool.check_index(client, base["index_digest"], base["arm64_manifest"])
    _man, base_cfg = tool.registry_image(client, base["arm64_manifest"])
    base_diff_ids = list((base_cfg.get("rootfs") or {}).get("diff_ids") or [])
    r = tool.scan_local("connector", pin, work, base_diff_ids)
    s = r["summary"]
    failures = list(a64.clean(s))
    if not index["ok"]:
        failures.append("base: the pinned index does not list the pinned arm64 manifest")
    if r.get("architecture") != "arm64":
        failures.append("architecture %r" % r.get("architecture"))
    if not r.get("base_layers_match"):
        failures.append("its first layers are not the base's arm64 layers")
    if s["objects"] < tool.LOCAL_FLOOR_OBJECTS:
        failures.append("below the floor: %d objects, the floor is %d" % (s["objects"], tool.LOCAL_FLOOR_OBJECTS))
    return {"format": 1, "image": "connector", "pin": dict(pin), "base_index": index, "summary": s,
            "sdk_objects": [{k: o.get(k) for k in ("path", "sha256", "exec_words", "lse", "guarded", "unguarded", "ldapr", "lor", "info")}
                            for o in r["objects"] if "awscrt" in o.get("path", "")],
            "flagged": [o["path"] for o in r["objects"] if any(o.get(k) for k in a64.GATED)],
            "base_layers_match": r.get("base_layers_match"), "architecture": r.get("architecture"),
            "tools": {"a64scan.py": sha256_file(ARM64_TOOL.parent / "a64scan.py"), "arm64.py": sha256_file(ARM64_TOOL)},
            "failures": failures, "verdict": "pass" if not failures else "FAIL"}


# --- command line ------------------------------------------------------------------------------------

def outside_repo(path: Path) -> Path:
    p = Path(path).expanduser()
    r, repo = p.resolve(), REPO.resolve()
    if r == repo or repo in r.parents:
        raise BuildError("%s is inside the repo: build and scan records stay outside it" % p)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the image for one architecture or both")
    b.add_argument("--arch", choices=ARCHES + ("all",), default=None)
    b.add_argument("--burst", action="store_true", help="build the burst tool's own test-only image instead (amd64; never pinned)")
    b.add_argument("--gen", default=None, help="the generated outputs' directory (default: SDV_GEN or sdv-out/gen)")
    b.add_argument("--frozen", default=None, help="the frozen allowlist (default: sdv-out/twin/twin_allowlist.py)")
    b.add_argument("--smoke", action="store_true", help="run the amd64 image's import check after its build")
    b.add_argument("--write-pins", action="store_true", help="with --arch all: write both pins into sdv/stack/images.json")
    b.add_argument("--out", default=None, help="also write the build record here (outside the repo)")
    s = sub.add_parser("scan", help="scan the arm64 pin's layers with sdv/arm64's scanner")
    s.add_argument("--out", required=True, help="the scan record (outside the repo)")
    s.add_argument("--work", default=str(CACHE / "connector-scan"), help="scratch for the saved image")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "scan":
            out = outside_repo(Path(a.out))
            rec = scan(outside_repo(Path(a.work)))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({k: rec[k] for k in ("verdict", "failures", "summary", "sdk_objects", "base_layers_match")}, indent=1, sort_keys=True))
            return 0 if rec["verdict"] == "pass" else 1
        if a.burst:
            if a.write_pins or a.arch not in (None, "amd64") or a.gen or a.frozen:
                print("build_image: --burst builds the burst tool's test-only image for amd64 and nothing else: it takes --smoke and --out, "
                      "no pin, no other architecture and no allowlist", file=sys.stderr)
                return 2
            if a.out:
                outside_repo(Path(a.out))
            made: Dict[str, Any] = {"burst": build_burst(smoke=a.smoke)}
            if a.out:
                Path(a.out).expanduser().parent.mkdir(parents=True, exist_ok=True)
                Path(a.out).expanduser().write_text(json.dumps(made, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(made, indent=1, sort_keys=True))
            return 0
        a.arch = a.arch or "amd64"
        if a.write_pins and a.arch != "all":
            print("build_image: --write-pins needs --arch all: the entry holds both architectures' pins from one run", file=sys.stderr)
            return 2
        if a.out:
            outside_repo(Path(a.out))
        gen = Path(a.gen or os.environ.get("SDV_GEN") or str(DEFAULT_GEN)).expanduser()
        frozen = Path(a.frozen).expanduser() if a.frozen else DEFAULT_FROZEN
        arches = ARCHES if a.arch == "all" else (a.arch,)
        records = {arch: build(gen, frozen, arch, smoke=a.smoke and arch == "amd64") for arch in arches}
        result: Dict[str, Any] = {"builds": records}
        if a.arch == "all":
            result["pins"] = {arch: pin_of(records[arch]) for arch in arches}
            result["labels"] = {LABELS[k]: v for k, v in sorted(records["amd64"]["labels"].items())}
            if records["amd64"]["labels"] != records["arm64"]["labels"]:
                raise BuildError("the two builds carry different labels: the inputs changed between them")
        if a.write_pins:
            new = with_pins(json.loads(IMAGES_FILE.read_text(encoding="utf-8")), result["pins"], records["amd64"]["labels"])
            IMAGES_FILE.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            result["written"] = True
        if a.out:
            Path(a.out).expanduser().parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).expanduser().write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    except (BuildError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as err:
        print("build_image: %s: %s" % (type(err).__name__, err), file=sys.stderr)
        return 1
    except Exception as err:  # noqa: BLE001 -- sdv/arm64's own error classes (a scan or a save that failed): one line, exit 1
        if type(err).__name__ in ("Arm64Error", "ScanError", "StackError"):
            print("build_image: %s: %s" % (type(err).__name__, err), file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
