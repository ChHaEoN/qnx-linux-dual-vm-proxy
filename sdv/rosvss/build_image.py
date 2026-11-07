#!/usr/bin/env python3
"""build_image.py -- build the ROS->VSS feeder's container image, ros-vss-feeder (sdv/rosvss; SDV Phase 8 WP3d).

Run in WSL, from the repo root, where Docker Engine runs:

    python3 sdv/rosvss/build_image.py [--smoke]

The bridge's pattern (sdv/bridge/build_image.py), amd64 only. It stages a build context outside the repo (under
~/sdv-cache/rosvss-build/, SDV_CACHE moves the root; removed after the build): sdv/rosvss/Dockerfile, requirements.lock,
sdv/aw/aw-entrypoint.sh as aw-entrypoint.sh (the image's ENTRYPOINT, so the base's never runs: the Phase 8
specification's 2.12) and app/ with the feeder's five modules laid out as in the repo (STAGED). Before building it checks
that the Dockerfile's one FROM (its keyword read in any case and after leading whitespace, as docker reads it) is the
Autoware image by images.json's autoware.amd64 manifest digest (never a tag) and reads the host check
(sdv/aw/hostcheck.sh, 2.12); a reading that fails stops it. It builds with `docker build -q --provenance=false
--sbom=false` (no attestation: it would carry the build's time and give every rebuild of unchanged inputs a new image ID;
no --privileged builder, no buildx), with the three labels as build arguments: the base digest, the lock's sha256 and the
staged sources' digest (sources_sha256). It reads the built image's config digest from a `docker save` stream of its ID
(the manifest and the config each checked against its digest by sdv/arm64/a64scan.py's reader; an index refused; the
config's platform linux/amd64) and refuses a config whose entrypoint is not the project's or whose user is not aw before
anything is smoked or pinned. It reads the host check again and compares the two readings: any difference fails the
build with the setting named, and nothing reverts it; a build that fails after the first reading (docker build, the save
stream, the config, the smoke) reads it again too and adds what it says to the failure. It prints one JSON record: the
image ID, the config digest, the tag, the labels, the base, the build's argument vector, the sha256 of every staged file,
the host check's two readings, and `pin`, the rosvss entry for sdv/stack/images.json ({"amd64": {id, config_digest, tag,
lock}, "labels": {...}}), which is entered by hand. --smoke then runs the image once, under 2.12 (--network none, --user
aw, --cap-drop ALL, no-new-privileges, removed after), importing rclpy, the message packages, kuksa_client and the
feeder's modules through the image's own entrypoint, and adds what it printed; inside the host check's two readings. An
image this tag named before and the rebuild left untagged is removed (the tag is this script's alone), and the record
says what became of it; nothing else is pruned.

Standard library only (and sdv/arm64/a64scan.py, loaded by its file, for the save stream). Does not demonstrate: that the
feeder runs right in the image (WP4b's runs), or anything on an arm64 host (no arm64 image is built).
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

TAG = "sdv-rosvss:local"
DOCKERFILE = HERE / "Dockerfile"
LOCK = HERE / "requirements.lock"
LOCK_REL = "sdv/rosvss/requirements.lock"
BASE_REPO = "ghcr.io/autowarefoundation/autoware"
FROM_RE = re.compile(r"^\s*FROM(?:\s(.*))?$", re.IGNORECASE)     # a FROM instruction as docker reads one; group 1: what follows
ENTRYPOINT_IN_IMAGE = "/sdv-aw/aw-entrypoint.sh"           # the Dockerfile's COPY target and ENTRYPOINT
IMAGE_USER = "aw"                                           # the Dockerfile's USER: the base's own user (uid 1000)
VENV_PYTHON = "/opt/sdv-rosvss/venv/bin/python"
SOURCES = ("sdv/rosvss/feeder_node.py", "sdv/rosvss/kuksa_out.py", "sdv/rosvss/mapping.py", "sdv/rosvss/update.py",
           "sdv/rosvss/vsswriter.py")
# What sdv.rosvss.sources_sha256 covers: the five modules and the entrypoint the image copies in, in path order.
SOURCES_DIGESTED = tuple(sorted(SOURCES + ("sdv/aw/aw-entrypoint.sh",)))
# The context, staged path -> source.
STAGED: Dict[str, Path] = dict({"Dockerfile": DOCKERFILE, "requirements.lock": LOCK, "aw-entrypoint.sh": REPO / "sdv" / "aw" / "aw-entrypoint.sh"},
                               **{"app/" + rel: REPO / rel for rel in SOURCES})
CACHE = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser()
SAVE_BLOB_LIMIT = 4 << 20       # a save stream's blobs kept to read the manifest and its config (sdv/stack/stack.py's bound)
SMOKE = ("import json, sys; sys.path.insert(0, '/app/sdv/rosvss'); import rclpy, kuksa_client.grpc, autoware_vehicle_msgs.msg, "
         "geometry_msgs.msg, std_msgs.msg, feeder_node; print(json.dumps({'python': sys.version.split()[0], 'prefix': sys.prefix, "
         "'rclpy': rclpy.__file__, 'kuksa_client': kuksa_client.__file__, 'feeder_node': feeder_node.__file__}))")


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources_sha256(repo: Path = REPO) -> str:
    """sha256 of `<sha256>  <path>\\n` for each of SOURCES_DIGESTED in order (sha256sum's lines): the sources label."""
    lines = "".join("%s  %s\n" % (sha256_file(repo / rel), rel) for rel in SOURCES_DIGESTED)
    return hashlib.sha256(lines.encode("ascii")).hexdigest()


def labels(images: Dict[str, Any]) -> Dict[str, str]:
    """The three labels: the base digest (images.json's autoware.amd64 manifest digest), the lock's sha256, the sources'."""
    return {"sdv.rosvss.base_digest": images["autoware"]["amd64"]["manifest_digest"], "sdv.rosvss.lock_sha256": sha256_file(LOCK),
            "sdv.rosvss.sources_sha256": sources_sha256()}


def check_inputs(images: Dict[str, Any]) -> str:
    """The Dockerfile's one FROM, which must be BASE_REPO@<images.json's autoware.amd64 manifest digest> (never a tag); every
    staged file present. Returns the FROM's reference. A FROM is read as docker reads an instruction: its keyword in any
    case, after leading whitespace (FROM_RE)."""
    want = "%s@%s" % (BASE_REPO, images["autoware"]["amd64"]["manifest_digest"])
    found = (FROM_RE.match(ln) for ln in DOCKERFILE.read_text(encoding="utf-8").splitlines())
    froms = [(m.group(1) or "").strip() for m in found if m is not None]
    if froms != [want]:
        raise BuildError("the Dockerfile's FROM lines are %s, not the one %s (images.json's autoware.amd64 manifest digest)" % (froms, want))
    missing = [rel for rel, src in STAGED.items() if not src.is_file()]
    if missing:
        raise BuildError("missing staged files: %s" % missing)
    return want


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
    key = "_sdv_a64scan_for_rosvss_build"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, str(A64SCAN_FILE))
    if spec is None or spec.loader is None:
        raise BuildError("cannot load %s" % A64SCAN_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[key] = mod
    return mod


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
    """docker's arguments: the bridge's amd64 build, with the three labels as build arguments."""
    return ["build", "-q", "--provenance=false", "--sbom=false",
            "--build-arg", "SDV_BASE_DIGEST=" + lbl["sdv.rosvss.base_digest"],
            "--build-arg", "SDV_LOCK_SHA256=" + lbl["sdv.rosvss.lock_sha256"],
            "--build-arg", "SDV_SOURCES_SHA256=" + lbl["sdv.rosvss.sources_sha256"],
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
    """What the host check says after a build that failed: read again and compared with the reading before it (spec-2
    2.12), or why that could not be done. Nothing is reverted."""
    try:
        changed = compare_host(before_host, read_host(), where)
    except (BuildError, OSError, subprocess.SubprocessError) as exc:
        return "the host check after it could not be read or compared: %s" % exc
    if changed:
        return "the host check after it: %s (nothing reverted it)" % "; ".join(changed)
    return "the host check after it: the four settings as before"


def built_record(lbl: Dict[str, str], base: str, ctx: Path, smoke: bool) -> Dict[str, Any]:
    """Stage the context in ctx, build, read the config digest from the save stream, refuse a config that is not the
    project's entrypoint and user aw (before anything is smoked or pinned), take care of the image the tag named before,
    and smoke when asked: the record, without the host check's second reading."""
    for rel, src in STAGED.items():
        dst = ctx / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    before = image_id(TAG)
    args = build_args(lbl, ctx)
    docker(*args, timeout=3600)
    iid = image_id(TAG)
    if iid is None:
        raise BuildError("the build left no image tagged %s" % TAG)
    config_digest, cfg = saved_config(iid)
    conf = cfg.get("config") or {}
    if conf.get("Entrypoint") != [ENTRYPOINT_IN_IMAGE] or str(conf.get("User") or "").split(":")[0] != IMAGE_USER:
        raise BuildError("the built image %s has the entrypoint %r and the user %r, not [%r] and %s: the base's entrypoint would "
                         "run, or the image as root (spec-2 2.12); nothing is smoked or pinned" % (
                             iid, conf.get("Entrypoint"), conf.get("User"), ENTRYPOINT_IN_IMAGE, IMAGE_USER))
    record: Dict[str, Any] = {
        "image_id": iid, "config_digest": config_digest, "tag": TAG,
        "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "base": base,
        "build": "docker " + " ".join(a if not a.startswith(str(ctx)) else "<ctx>" + a[len(str(ctx)):] for a in args),
        "labels": lbl, "config_user": conf.get("User"), "config_entrypoint": conf.get("Entrypoint"),
        "dockerfile_sha256": sha256_file(DOCKERFILE), "lock_sha256": sha256_file(LOCK),
        "staged": {rel: sha256_file(src) for rel, src in sorted(STAGED.items())},
        "pin": {"amd64": {"id": iid, "config_digest": config_digest, "tag": TAG, "lock": LOCK_REL}, "labels": dict(lbl)}}
    if before is not None and before != iid:
        if image_id(before) is None:
            record["replaced_image"] = {"id": before, "left": "gone (the image store dropped it with its tag)"}
        elif json.loads(docker("image", "inspect", "--format", "{{json .RepoTags}}", before) or "[]") == []:
            docker("image", "rm", before)
            record["replaced_image"] = {"id": before, "left": "removed (untagged by this build)"}
        else:
            record["replaced_image"] = {"id": before, "left": "kept (another tag names it)"}
    if smoke:
        out = docker("run", "--rm", "--network", "none", "--user", "aw", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                     iid, VENV_PYTHON, "-c", SMOKE, timeout=300)
        record["smoke"] = json.loads(out.splitlines()[-1])
    return record


def build(images: Dict[str, Any], smoke: bool = False) -> Dict[str, Any]:
    """check_inputs, the host check read, built_record in a staged context, the host check read again and compared: a
    difference fails the build with the setting named. A build that fails after the first reading is failed with the
    second reading's words added (host_after_failure)."""
    base = check_inputs(images)
    lbl = labels(images)
    root = CACHE / "rosvss-build"
    if str(root.resolve()).startswith(str(REPO.resolve()) + os.sep):
        raise BuildError("the staging root %s is inside the repo" % root)
    before_host = read_host()
    root.mkdir(parents=True, exist_ok=True)
    ctx = Path(tempfile.mkdtemp(prefix="ctx-", dir=str(root)))
    try:
        try:
            record = built_record(lbl, base, ctx, smoke)
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
    ap.add_argument("--smoke", action="store_true", help="run the image's import check after the build, under 2.12")
    a = ap.parse_args(argv)
    try:
        images = json.loads(IMAGES_FILE.read_text(encoding="utf-8"))
        record = build(images, a.smoke)
    except (BuildError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as err:
        print("build_image: %s" % err, file=sys.stderr)
        return 1
    print(json.dumps(record, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
