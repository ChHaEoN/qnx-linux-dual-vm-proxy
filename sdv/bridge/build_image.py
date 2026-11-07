#!/usr/bin/env python3
"""build_image.py -- build the claim bridge's container image, vss-claim-bridge (sdv/bridge; Phase 2 WP7).

Run in WSL, from the repo root, where Docker Engine runs:

    python3 sdv/bridge/build_image.py [--gen DIR] [--smoke]
    python3 sdv/bridge/build_image.py --arch arm64 [--gen DIR]

It stages a build context outside the repo (under ~/sdv-cache/bridge-build/, SDV_CACHE moves the root; removed
after the build): sdv/bridge/Dockerfile, sdv/bridge/requirements.lock, and app/ with the files the image runs,
laid out as in the repo (STAGED). Before building it checks that slice.dbc is the one the contract was
generated from (the generation manifest's slice.dbc sha256) and that the contract loads. It builds with
`docker build -q --provenance=false --sbom=false` (no attestation: it would carry the build's time and give
every rebuild of unchanged inputs a new image ID), labels the image with the catalogue digest and the sha256
of the contract and of slice.dbc, and prints one JSON record: the image ID, the tag, the base, the sha256 of
every staged file, the lock's and the Dockerfile's. --smoke then runs the image's `check` (no network, a
read-only root) and adds what it printed. An image this tag named before and the rebuild left untagged is
removed (the tag is this script's alone), and the record says what became of it; nothing else is pruned.

--arch arm64 (SDV Phase 3 WP0) builds the linux/arm64 image from the same Dockerfile and the same staged files,
with sdv/bridge/requirements.aarch64.lock staged as the context's requirements.lock, by `docker buildx build -q
--platform linux/arm64 --provenance=false --sbom=false --load` (under the host's qemu-aarch64 binfmt registration;
the Dockerfile's FROM index digest resolves to the base's arm64 manifest), tagged TAG-arm64: never the amd64 tag, so
an arm64 build can neither move it nor remove the amd64 image. The record adds `arch` and `lock`. Without --arch
the build's argument vector is the one every amd64 bridge image was built with, word for word. --smoke is refused
with --arch arm64: an emulated smoke shows nothing until a canary shows the emulated CPU is the one asked for, so
sdv/arm64/arm64.py smoke runs it (QEMU_CPU=cortex-a72, after its HWCAP canary). sdv/stack/images.json's top-level
`bridge` entry pins the arm64 image's ID, config digest, tag and lock, and the three labels it was built with.

Standard library only (and sdv/frame's codec, to load the contract). Does not demonstrate: that the image runs a
bridge (the tests and Phase 2 WP8 do), or that the arm64 image runs on an ARMv8.0 core (sdv/arm64's scan and smoke
are static and emulated; Phase 3 V1 runs it).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
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
sys.path.insert(0, str(REPO / "sdv" / "frame"))
import vssframe as vf  # noqa: E402

TAG = "sdv-local/vss-claim-bridge:0.1.0"
DOCKERFILE = HERE / "Dockerfile"
LOCK = HERE / "requirements.lock"
# --arch arm64 (Phase 3 WP0): its own lock, its own tag, buildx for that one platform.
ARCHES = ("arm64",)
TAGS: Dict[Optional[str], str] = {None: TAG, "arm64": TAG + "-arm64"}
LOCKS: Dict[Optional[str], Path] = {None: LOCK, "arm64": HERE / "requirements.aarch64.lock"}
PLATFORMS = {"arm64": "linux/arm64"}
CODE = ("sdv/frame/vssframe.py", "sdv/frame/rules.py", "sdv/bridge/vss_claim_bridge.py", "sdv/bridge/reasonsets.py",
        "sdv/bridge/bridge_sources.py", "sdv/vss/slice.dbc")
GENERATED = ("vss_contract.py", "manifest.json")
CACHE = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser()


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def staged(gen: Path) -> Dict[str, Path]:
    """app-relative path -> source: the code as in the repo, the generated pair under sdv-out/gen."""
    out = {rel: REPO / rel for rel in CODE}
    out.update({"sdv-out/gen/" + name: gen / name for name in GENERATED})
    return out


def check_inputs(gen: Path) -> Dict[str, Any]:
    contract = vf.load_contract(gen)
    manifest = json.loads((gen / "manifest.json").read_text(encoding="utf-8"))
    dbc = sha256_file(REPO / "sdv" / "vss" / "slice.dbc")
    if manifest.get("inputs", {}).get("slice.dbc") != dbc:
        raise BuildError("sdv/vss/slice.dbc (sha256 %s) is not the one %s was generated from (%s): regenerate first"
                         % (dbc, gen, manifest.get("inputs", {}).get("slice.dbc")))
    return {"catalog_digest": "0x%08X" % contract.CATALOG_DIGEST, "contract_sha256": sha256_file(gen / "vss_contract.py"),
            "dbc_sha256": dbc}


def docker(*args: str, timeout: float = 120) -> str:
    p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise BuildError("docker %s: exit %d: %s" % (" ".join(args[:2]), p.returncode, (p.stderr or p.stdout).strip()[-2000:]))
    return p.stdout.strip()


def image_id(ref: str) -> Optional[str]:
    p = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", ref], capture_output=True, text=True, timeout=60)
    return p.stdout.strip() if p.returncode == 0 else None


def build_args(ids: Dict[str, str], ctx: Path, arch: Optional[str] = None) -> List[str]:
    """docker's arguments: without arch, the amd64 build's, word for word as before arm64 builds existed."""
    labels = ["--build-arg", "SDV_CATALOG_DIGEST=" + ids["catalog_digest"],
              "--build-arg", "SDV_CONTRACT_SHA256=" + ids["contract_sha256"],
              "--build-arg", "SDV_DBC_SHA256=" + ids["dbc_sha256"],
              "-f", str(ctx / "Dockerfile"), "-t", TAGS[arch], str(ctx)]
    if arch is None:
        return ["build", "-q", "--provenance=false", "--sbom=false"] + labels
    return ["buildx", "build", "-q", "--platform", PLATFORMS[arch], "--provenance=false", "--sbom=false", "--load"] + labels


def build(gen: Path, smoke: bool, arch: Optional[str] = None) -> Dict[str, Any]:
    if arch is not None and arch not in ARCHES:
        raise BuildError("unknown --arch %r (known: %s)" % (arch, ", ".join(ARCHES)))
    if arch is not None and smoke:
        raise BuildError("--smoke with --arch %s: run sdv/arm64/arm64.py smoke, which runs the HWCAP canary first" % arch)
    tag, lock = TAGS[arch], LOCKS[arch]
    ids = check_inputs(gen)
    root = CACHE / "bridge-build"
    if str(root.resolve()).startswith(str(REPO.resolve()) + os.sep):
        raise BuildError("the staging root %s is inside the repo" % root)
    root.mkdir(parents=True, exist_ok=True)
    ctx = Path(tempfile.mkdtemp(prefix="ctx-", dir=str(root)))
    try:
        files = staged(gen)
        for rel, src in files.items():
            dst = ctx / "app" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        shutil.copyfile(DOCKERFILE, ctx / "Dockerfile")
        shutil.copyfile(lock, ctx / "requirements.lock")
        before = image_id(tag)
        args = build_args(ids, ctx, arch)
        docker(*args, timeout=1800 if arch is None else 3600)
        iid = image_id(tag)
        if iid is None:
            raise BuildError("the build left no image tagged %s" % tag)
        record: Dict[str, Any] = {
            "image_id": iid, "tag": tag, "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "base": next(ln.split(None, 1)[1] for ln in DOCKERFILE.read_text(encoding="utf-8").splitlines() if ln.startswith("FROM ")),
            "build": "docker " + " ".join(a if not a.startswith(str(ctx)) else "<ctx>" + a[len(str(ctx)):] for a in args),
            "labels": ids, "dockerfile_sha256": sha256_file(DOCKERFILE), "lock_sha256": sha256_file(lock),
            "staged": {rel: sha256_file(src) for rel, src in sorted(files.items())}}
        if arch is not None:
            record["arch"] = arch
            record["lock"] = lock.relative_to(REPO).as_posix()
        if before is not None and before != iid:
            if image_id(before) is None:
                record["replaced_image"] = {"id": before, "left": "gone (the image store dropped it with its tag)"}
            elif json.loads(docker("image", "inspect", "--format", "{{json .RepoTags}}", before) or "[]") == []:
                docker("image", "rm", before)
                record["replaced_image"] = {"id": before, "left": "removed (untagged by this build)"}
            else:
                record["replaced_image"] = {"id": before, "left": "kept (another tag names it)"}
        if smoke:
            out = docker("run", "--rm", "--network", "none", "--read-only", iid, "check")
            record["smoke"] = json.loads(out.splitlines()[-1])
        return record
    finally:
        shutil.rmtree(ctx, ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--gen", default=None, help="the generated contract's directory (default: SDV_GEN or sdv-out/gen)")
    ap.add_argument("--smoke", action="store_true", help="run the image's check after the build (amd64 only)")
    ap.add_argument("--arch", choices=ARCHES, default=None,
                    help="build for this architecture with its own lock and tag (default: the host's, as always)")
    a = ap.parse_args(argv)
    if a.arch is not None and a.smoke:
        print("build_image: --smoke with --arch %s is refused: run sdv/arm64/arm64.py smoke, which runs the HWCAP canary "
              "first" % a.arch, file=sys.stderr)
        return 2
    gen = vf.contract_path(a.gen).parent
    try:
        record = build(gen, a.smoke, a.arch)
    except (BuildError, vf.ContractError, OSError, ValueError, subprocess.TimeoutExpired) as err:
        print("build_image: %s" % err, file=sys.stderr)
        return 1
    print(json.dumps(record, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
