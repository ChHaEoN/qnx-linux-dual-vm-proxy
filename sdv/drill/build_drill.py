#!/usr/bin/env python3
"""build_drill.py -- the drill's images: v2 and v3 of hard-brake-hazard made on v1 for both architectures, pinned for
arm64, and saved for the bare-metal session (sdv/drill; SDV Phase 6 WP3).

Standard library only, and sdv/arm64's scanner (a64scan.py, standard library itself).
Run in WSL from the repo root, where Docker Engine runs (its containerd image store; buildx under the host's existing
qemu-aarch64 binfmt registration for arm64). No container is started, nothing is pulled, pushed or logged in to:

    python3 sdv/drill/build_drill.py build --arch arm64 [--write-pins] [--out FILE] [--docker PREFIX]
    python3 sdv/drill/build_drill.py build --arch amd64 --store-ids FILE [--out FILE] [--docker PREFIX]
    REPO_COMMIT=<commit> python3 sdv/drill/build_drill.py save --out DIR/sdv-drill.tar [--docker PREFIX]

THE IMAGES (the OTA drill contract section 2.3)
  v1  arm64: sdv/stack/images.json's local.hard-brake-hazard.arm64 pin, whose tag must name its ID. amd64: the PC's own
      build, the image images.json's local tag names (`stack.py prepare` builds it; it is never pinned).
  v2  v1 plus one layer: /app/hazard.py replaced by the app's own hazard.py edited on a staged copy outside the repo in
      exactly two constants, APP_VERSION "1.0.0" to "1.1.0" and DECEL_OFF_MPS2 3.0 to 2.5 (the design value whose
      change shows in the app's behaviour: the hazard lights go off once the deceleration falls below 2.5 m/s^2
      instead of 3.0; sigsim's ordinary braking, at most 2.0, still releases them). Each old text is a whole line and
      must stand exactly once (EDITS), so the module docstring's sentence about the old value is never a match. The
      Dockerfile is v2.Dockerfile.in with v1's tag after FROM (label org.opencontainers.image.version=1.1.0, the COPY
      of the one file), built with --provenance=false --sbom=false (arm64: buildx --platform linux/arm64 --load) and
      tagged sdv-drill/hard-brake-hazard:1.1.0 or :1.1.0-arm64. Its config's diff_ids must be v1's plus exactly one.
  v3  v2's image with only its entrypoint changed to one that exits non-zero at once (V3_ENTRYPOINT: no heartbeat
      ever): a config that is v2's with config.Entrypoint replaced and nothing else, and a manifest with v2's layers
      and that config, written here as an OCI layout and loaded with `docker load` (named
      sdv-drill/hard-brake-hazard:1.2.0 or :1.2.0-arm64 by its index annotation). No build, no layer: its config
      differs from v2's in the entrypoint alone (config_problems). Its label still says 1.1.0; its manifest entry says
      1.2.0, a version it never publishes.
  Every image's config digest is proved from a `docker save` of its store ID (the save lists that one ID as an image
  manifest, never an index; the manifest and the config hash-checked: drill.py's image_of), and every arm64 one is
  scanned with sdv/arm64's scanner (a64scan: no unguarded LSE, no LDAPR, no LOR word, every object read, at least
  SCAN_FLOOR_OBJECTS objects). The staged context and the save tars live under WORK_ROOT (SDV_CACHE's drill-build/, by
  default ~/sdv-cache/drill-build: never the repo) and are removed after.

PINS (--write-pins, arm64 only)  sdv/drill/drill-images.json: arm64.<version> {id, config_digest, tag, base} for v1 (a
  copy of images.json's pin, held equal by tests/test_sdv_drill.py), v2 (base: v1's pair) and v3 (base: v2's pair).
STORE IDS (amd64)  --store-ids FILE, outside the repo: format 1, arch amd64, images.<version> {store_id, config_digest}
  and bridge {store_id, config_digest} (the PC's bridge: SDV_BRIDGE_IMAGE, or BRIDGE_TAG), for drill.py manifest
  --store-ids. The amd64 images are never pinned.
SAVE  `docker save -o TAR` of the three arm64 IDs of drill-images.json, checked (drill.py check_save: exactly those
  three, each proved, every layer of its digest), and TAR.sha256 beside it in two lines: `<64 hex>  <TAR's name>` and
  `commit <REPO_COMMIT>`, the commit the session's repo tarball must be (the bare-metal harness reads both). The tar's
  sha256 is printed. REPO_COMMIT is required; an existing TAR is never overwritten. The Orin's images go by `twinctl
  push` (WP4), one call per version, never from here.

EXIT STATUS  0 done; 1 a build, proof, scan or check failed (no pins and no store IDs written); 2 a refusal before
  anything ran.

Does not demonstrate: that any image runs (no container is started here: the updater's health check on a real stack
is the drill's); that v2's change shows on the bus or in the twin; that the scanner's rule covers every post-v8.0
class (sdv/arm64/README.md); any timing.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
IMAGES_FILE = REPO / "sdv" / "stack" / "images.json"
PINS_FILE = HERE / "drill-images.json"
HAZARD = REPO / "sdv" / "apps" / "hard-brake-hazard" / "hazard.py"
V2_TEMPLATE = HERE / "v2.Dockerfile.in"
WORK_ROOT = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser() / "drill-build"

sys.dont_write_bytecode = True
for _d in (HERE, REPO / "sdv" / "arm64"):
    if str(_d) not in sys.path:
        sys.path.append(str(_d))
import a64scan  # noqa: E402  -- sdv/arm64's scanner
import drill  # noqa: E402  -- the drill's own image proof and save check

APP = drill.APP
VERSIONS = drill.VERSIONS
TAG = "sdv-drill/hard-brake-hazard:%s"            # the drill's own namespace: no tag of another package is touched
BRIDGE_TAG = "sdv-local/vss-claim-bridge:0.1.0"   # sdv/bridge/build_image.py's TAG: the PC's amd64 bridge
BRIDGE_ENV = "SDV_BRIDGE_IMAGE"                   # stack.py's: the bridge image's ID, when given
EDITS = (('\nAPP_VERSION = "1.0.0"\n', '\nAPP_VERSION = "1.1.0"\n'),
         ("\nDECEL_OFF_MPS2 = 3.0\n", "\nDECEL_OFF_MPS2 = 2.5\n"))
V2_VERSION_LABEL = "1.1.0"
V3_ENTRYPOINT = ["python", "-c", "raise SystemExit(3)"]
ARM64_PLATFORM = "linux/arm64"
SCAN_FLOOR_OBJECTS = 80        # sdv/arm64/arm64.py's LOCAL_FLOOR_OBJECTS: the python base's CPython layer alone
CALL_TIMEOUT_S = 120.0
BUILD_TIMEOUT_S = 3600.0
SAVE_TIMEOUT_S = 1800.0
NAME_ANNOTATION = "io.containerd.image.name"
REF_ANNOTATION = "org.opencontainers.image.ref.name"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
_TAG = re.compile(r"[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+|sha256:[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
PINS_ABOUT = ("The drill's arm64 images (sdv/drill/build_drill.py build --arch arm64 --write-pins; SDV Phase 6 WP3): v1 is a "
              "copy of sdv/stack/images.json's local.hard-brake-hazard.arm64 pin (tests/test_sdv_drill.py holds them equal), v2 "
              "is v1 plus one layer (hazard.py with APP_VERSION 1.1.0 and DECEL_OFF_MPS2 2.5), v3 is v2 with only its entrypoint "
              "changed to one that exits non-zero at once. Each id is the containerd store's ID of the built or loaded image "
              "(its manifest digest) and config_digest the identity every Phase 6 record carries; base is the pair it was made on.")


class BuildError(RuntimeError):
    pass


class Refused(Exception):
    pass


class Docker:
    """docker behind an argv prefix (--docker): every docker call of this module goes through run()."""

    def __init__(self, prefix: str = "docker") -> None:
        self.argv = shlex.split(prefix)
        if not self.argv:
            raise Refused("--docker: an empty prefix")

    def run(self, args: Sequence[str], timeout: float = CALL_TIMEOUT_S) -> drill.Done:
        try:
            p = subprocess.run(self.argv + list(args), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return drill.Done(-1, "", "did not end within %g s" % timeout)
        except OSError as exc:
            return drill.Done(-2, "", "could not be started: %s" % (exc.strerror or type(exc).__name__))
        return drill.Done(p.returncode, p.stdout, p.stderr)


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tail(text: Optional[str], n: int = 300) -> str:
    return " ".join((text or "").split())[-n:]


# --- v2: the edit and its staged context -------------------------------------------------------------------------------

def edit_v2(text: str) -> str:
    """The app's hazard.py with EDITS applied: each old text (a whole line) must stand exactly once."""
    for old, new in EDITS:
        n = text.count(old)
        if n != 1:
            raise BuildError("v2's edit: %r stands %d time(s) in hazard.py, not once" % (old.strip(), n))
        text = text.replace(old, new, 1)
    return text


def stage_v2(ctx: Path, base: str) -> Dict[str, str]:
    """v2's build context in ctx (outside the repo): the edited copy of the app's hazard.py and the Dockerfile from
    v2.Dockerfile.in with `base` after FROM. The sha256 of each staged file."""
    if drill.inside_repo(ctx):
        raise BuildError("v2's staging directory is inside the repo: the edit is made on a staged copy outside it")
    if not _TAG.fullmatch(base):
        raise BuildError("v2's base is not an image reference")
    source = HAZARD.read_bytes().decode("utf-8")
    edited = edit_v2(source)
    template = V2_TEMPLATE.read_text(encoding="utf-8")
    if template.count("{base}") != 1:
        raise BuildError("v2.Dockerfile.in does not name its base once")
    (ctx / "hazard.py").write_bytes(edited.encode("utf-8"))
    (ctx / "Dockerfile").write_bytes(template.replace("{base}", base).encode("utf-8"))
    return {name: drill.sha256_file(ctx / name) for name in ("hazard.py", "Dockerfile")}


def layer_problems(v1: Dict[str, Any], v2: Dict[str, Any]) -> List[str]:
    """Why v2's config is not v1's plus exactly one layer."""
    a = list((v1.get("rootfs") or {}).get("diff_ids") or [])
    b = list((v2.get("rootfs") or {}).get("diff_ids") or [])
    if len(b) != len(a) + 1 or b[:len(a)] != a:
        return ["v2 is not v1 plus one layer (%d diff_ids on v1's %d, v1's first: %s)" % (len(b), len(a), b[:len(a)] == a)]
    return []


# --- v3: v2 with only its entrypoint changed -------------------------------------------------------------------------

def v3_config(v2_config: bytes) -> bytes:
    """v3's config: v2's with config.Entrypoint V3_ENTRYPOINT and nothing else changed."""
    try:
        cfg = json.loads(v2_config)
    except ValueError:
        raise BuildError("v2's config is not JSON") from None
    if not isinstance(cfg, dict) or not isinstance(cfg.get("config"), dict):
        raise BuildError("v2's config has no container config")
    cfg["config"]["Entrypoint"] = list(V3_ENTRYPOINT)
    return json.dumps(cfg, separators=(",", ":")).encode("utf-8")


def config_problems(v2: Dict[str, Any], v3: Dict[str, Any]) -> List[str]:
    """Why v3's config is not v2's with the entrypoint alone changed: no new layer, the same history, another
    entrypoint, everything else equal."""
    out = []
    if v3.get("rootfs") != v2.get("rootfs"):
        out.append("v3's layers are not v2's")
    if v3.get("history") != v2.get("history"):
        out.append("v3's history is not v2's")
    c2, c3 = dict(v2.get("config") or {}), dict(v3.get("config") or {})
    if c3.pop("Entrypoint", None) == c2.pop("Entrypoint", None):
        out.append("v3's entrypoint is v2's")
    if dict(v2, config=c2) != dict(v3, config=c3):
        out.append("v3's config differs from v2's beyond the entrypoint")
    return out


def v3_layout(src: Path, v2_id: str, out: Path, tag: str) -> Dict[str, str]:
    """v3 as an OCI layout `docker load` takes, from v2's save (src): v2's layers, v3's config (v3_config) and v2's
    manifest with only its config descriptor changed; its index names it `tag`. v3's store ID and config digest."""
    with drill.OciTar(src) as tar:
        man, _cfg, cd = drill.image_of(tar.blob, v2_id)
        craw = tar.blob(cd)
        assert craw is not None
        cfg3 = v3_config(craw)
        cd3 = drill.sha256_bytes(cfg3)
        man3 = dict(man)
        man3["config"] = dict(man["config"], digest=cd3, size=len(cfg3))
        man3["layers"] = man["layers"]
        raw3 = json.dumps(man3, separators=(",", ":")).encode("utf-8")
        id3 = drill.sha256_bytes(raw3)
        layers: List[str] = []
        for lay in man["layers"]:
            d = str(lay.get("digest"))
            if tar.blob_hash(d) != d:
                raise BuildError("v2's save: the layer %s is missing or not of its digest" % d)
            if d not in layers:
                layers.append(d)
        desc = {"mediaType": man.get("mediaType"), "digest": id3, "size": len(raw3),
                "annotations": {NAME_ANNOTATION: "docker.io/" + tag, REF_ANNOTATION: tag.rsplit(":", 1)[1]}}
        tmp = out.with_name("." + out.name + ".tmp")
        try:
            with tarfile.open(str(tmp), "w") as w:
                for dname in ("blobs", "blobs/sha256"):
                    ti = tarfile.TarInfo(dname)
                    ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, 0o755, 0
                    w.addfile(ti)
                for d in layers:
                    m = tar.members["blobs/sha256/" + d[7:]]
                    ti = tarfile.TarInfo("blobs/sha256/" + d[7:])
                    ti.size, ti.mode, ti.mtime = m.size, 0o644, 0
                    w.addfile(ti, tar.tf.extractfile(m))
                drill._add(w, "blobs/sha256/" + cd3[7:], cfg3)
                drill._add(w, "blobs/sha256/" + id3[7:], raw3)
                drill._add(w, "index.json", json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [desc]},
                                                       separators=(",", ":")).encode("utf-8"))
                drill._add(w, "oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
            os.replace(str(tmp), str(out))
        finally:
            if tmp.exists():
                tmp.unlink()
    return {"id": id3, "config_digest": cd3}


# --- the store: IDs, proofs, scans -------------------------------------------------------------------------------------

def store_id(docker: Any, ref: str) -> str:
    r = docker.run(["image", "inspect", "-f", "{{.Id}}", ref])
    sid = (r.stdout or "").strip()
    if r.returncode != 0 or not drill.digest_ok(sid):
        raise BuildError("%s is not in the image store (%s)" % (ref, tail(r.stderr) or "exit %d" % r.returncode))
    return sid


def prove(docker: Any, sid: str, work: Path, arch: str) -> Tuple[Dict[str, Any], str, Path]:
    """(the config, the config digest, the save tar) of the store ID sid, from a `docker save` of it: that one ID listed
    as an image manifest (an index is refused), the manifest and the config hash-checked, of linux/arch."""
    path = work / ("save-%s.tar" % sid[7:19])
    r = docker.run(["save", "-o", str(path), sid], timeout=SAVE_TIMEOUT_S)
    if r.returncode != 0:
        raise BuildError("docker save %s: exit %d: %s" % (sid, r.returncode, tail(r.stderr)))
    with drill.OciTar(path) as tar:
        _idx, listed = tar.index()
        if [d.get("digest") for d in listed] != [sid]:
            raise BuildError("the save of %s lists other images" % sid)
        if listed[0].get("mediaType") not in drill.MANIFEST_TYPES:
            raise BuildError("the save lists %s as %s, not one platform's image manifest: an index is refused"
                             % (sid, listed[0].get("mediaType")))
        _man, cfg, cd = drill.image_of(tar.blob, sid)
    if (cfg.get("os"), cfg.get("architecture")) != ("linux", arch):
        raise BuildError("%s is %s/%s, not linux/%s" % (sid, cfg.get("os"), cfg.get("architecture"), arch))
    return cfg, cd, path


def a64_scan(path: str, image_id: str, config_digest: str) -> List[str]:
    """sdv/arm64's gate on one saved image: a64scan's clean() and the object floor."""
    r = a64scan.scan_saved_image(path, image_id, config_digest)
    s = r["summary"]
    print("build_drill: scanned %s: %d objects, %d exec words, lse %d (guarded %d, unguarded %d), ldapr %d, lor %d"
          % (image_id, s["objects"], s["exec_words"], s["lse"], s["guarded"], s["unguarded"], s["ldapr"], s["lor"]), flush=True)
    out = a64scan.clean(s)
    if s["objects"] < SCAN_FLOOR_OBJECTS:
        out.append("below the floor: %d objects, the floor is %d" % (s["objects"], SCAN_FLOOR_OBJECTS))
    return out


Scan = Callable[[str, str, str], List[str]]


def scanned(scan: Optional[Scan], path: Path, sid: str, cd: str) -> str:
    if scan is None:
        return "not scanned (amd64)"
    problems = scan(str(path), sid, cd)
    if problems:
        raise BuildError("the scan of %s: %s" % (sid, "; ".join(problems)))
    return "clean"


def build_on(docker: Any, scan: Optional[Scan], work: Path, arch: str, v1_tag: str, v1_pin: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """v1 proved (and held to its pin when given), v2 built on it, v3 made from v2 and loaded; each proved (and scanned
    for arm64). The record."""
    suffix = "-arm64" if arch == "arm64" else ""
    started = utc_now()
    id1 = store_id(docker, v1_tag)
    if v1_pin is not None and id1 != v1_pin["id"]:
        raise BuildError("%s names %s, not images.json's pin %s" % (v1_tag, id1, v1_pin["id"]))
    cfg1, cd1, t1 = prove(docker, id1, work, arch)
    if v1_pin is not None and cd1 != v1_pin["config_digest"]:
        raise BuildError("v1's config digest is %s, images.json's pin %s" % (cd1, v1_pin["config_digest"]))
    scans = {"1.0.0": scanned(scan, t1, id1, cd1)}
    t1.unlink()
    ctx = work / "v2-context"
    ctx.mkdir()
    staged = stage_v2(ctx, v1_tag)
    tag2 = TAG % ("1.1.0" + suffix)
    common = ["-q", "--provenance=false", "--sbom=false"]
    args = (["buildx", "build", "-q", "--platform", ARM64_PLATFORM, "--provenance=false", "--sbom=false", "--load"] if arch == "arm64"
            else ["build"] + common)
    r = docker.run(args + ["-f", str(ctx / "Dockerfile"), "-t", tag2, str(ctx)], timeout=BUILD_TIMEOUT_S)
    if r.returncode != 0:
        raise BuildError("v2's build: exit %d: %s" % (r.returncode, tail(r.stderr or r.stdout, 1500)))
    shutil.rmtree(str(ctx))
    id2 = store_id(docker, tag2)
    cfg2, cd2, t2 = prove(docker, id2, work, arch)
    bad = layer_problems(cfg1, cfg2)
    if ((cfg2.get("config") or {}).get("Labels") or {}).get("org.opencontainers.image.version") != V2_VERSION_LABEL:
        bad.append("v2's version label is not %s" % V2_VERSION_LABEL)
    if bad:
        raise BuildError("; ".join(bad))
    scans["1.1.0"] = scanned(scan, t2, id2, cd2)
    tag3 = TAG % ("1.2.0" + suffix)
    layout = work / "v3-layout.tar"
    made = v3_layout(t2, id2, layout, tag3)
    t2.unlink()
    r = docker.run(["load", "-i", str(layout)], timeout=SAVE_TIMEOUT_S)
    if r.returncode != 0:
        raise BuildError("v3's load: exit %d: %s" % (r.returncode, tail(r.stderr or r.stdout)))
    layout.unlink()
    id3 = store_id(docker, tag3)
    if id3 != made["id"]:
        raise BuildError("%s names %s, not the v3 written here (%s)" % (tag3, id3, made["id"]))
    cfg3, cd3, t3 = prove(docker, id3, work, arch)
    bad = ([] if cd3 == made["config_digest"] else ["v3's config digest is not the one written here"]) + config_problems(cfg2, cfg3)
    if bad:
        raise BuildError("; ".join(bad))
    scans["1.2.0"] = scanned(scan, t3, id3, cd3)
    t3.unlink()
    images = {"1.0.0": {"id": id1, "config_digest": cd1, "tag": v1_tag},
              "1.1.0": {"id": id2, "config_digest": cd2, "tag": tag2, "base": {"id": id1, "config_digest": cd1}},
              "1.2.0": {"id": id3, "config_digest": cd3, "tag": tag3, "base": {"id": id2, "config_digest": cd2}}}
    return {"format": 1, "tool": "build_drill.py build", "arch": arch, "started_utc": started, "finished_utc": utc_now(),
            "staged": staged, "edits": [[old.strip(), new.strip()] for old, new in EDITS], "v3_entrypoint": V3_ENTRYPOINT,
            "pins": images, "scans": scans}


def pins_doc(rec: Dict[str, Any]) -> Dict[str, Any]:
    p = rec["pins"]
    v1 = dict(p["1.0.0"], base="images.json local.%s.arm64" % APP)
    return {"format": 1, "about": PINS_ABOUT, "app": APP,
            "arm64": {"1.0.0": v1, "1.1.0": p["1.1.0"], "1.2.0": p["1.2.0"]},
            "edits": rec["edits"], "v3_entrypoint": rec["v3_entrypoint"]}


def save(docker: Any, out: Path, commit: str) -> str:
    """docker save -o out of the three arm64 pins, checked, and out.sha256 beside it; the tar's sha256 (hex)."""
    pins = drill.read_pins(PINS_FILE)
    r = docker.run(["save", "-o", str(out)] + [pins[v]["id"] for v in VERSIONS], timeout=SAVE_TIMEOUT_S)
    if r.returncode != 0:
        raise BuildError("docker save: exit %d: %s" % (r.returncode, tail(r.stderr)))
    try:
        with drill.OciTar(out) as tar:
            drill.check_save(tar, pins, "arm64")
    except drill.DrillError as exc:
        if out.exists():
            out.unlink()
        raise BuildError("the save is not the pins: %s" % exc) from None
    hexd = drill.sha256_file(out)[7:]
    (out.parent / (out.name + ".sha256")).write_bytes(("%s  %s\ncommit %s\n" % (hexd, out.name, commit)).encode("ascii"))
    return hexd


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="build_drill.py", description="the drill's images (SDV Phase 6 WP3)")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="v2 and v3 on v1 for one architecture, proved (and scanned for arm64)")
    b.add_argument("--arch", required=True, choices=drill.ARCHES)
    b.add_argument("--write-pins", action="store_true", help="arm64: write sdv/drill/drill-images.json")
    b.add_argument("--store-ids", default=None, help="amd64: the store IDs file, outside the repo")
    b.add_argument("--out", default=None, help="also write the build record here (outside the repo)")
    b.add_argument("--docker", default="docker")
    s = sub.add_parser("save", help="docker save of the three arm64 pins, and its sum file")
    s.add_argument("--out", required=True, help="the tar (sdv-drill.tar), outside the repo; never overwritten")
    s.add_argument("--docker", default="docker")
    return p


def outside(path: str, what: str) -> Path:
    p = drill.abspath(path)
    if drill.inside_repo(p):
        raise Refused("%s is inside the repo" % what)
    if not p.parent.is_dir():
        raise Refused("%s's directory does not exist" % what)
    return p


def main(argv: Optional[Sequence[str]] = None, docker: Any = None, scan: Optional[Scan] = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "save":
            commit = os.environ.get("REPO_COMMIT") or ""
            if not _COMMIT.fullmatch(commit):
                raise Refused("REPO_COMMIT must be the commit the session's repo tarball is made from (40 hex digits)")
            out = outside(a.out, "--out")
            if os.path.lexists(str(out)):
                raise Refused("--out exists: a session's tar is never overwritten")
            d = docker if docker is not None else Docker(a.docker)
            print(save(d, out, commit))
            return 0
        rec_out = outside(a.out, "--out") if a.out else None
        ids_out: Optional[Path] = None
        if a.arch == "amd64":
            if a.write_pins:
                raise Refused("--write-pins is arm64's: the amd64 images are never pinned")
            if a.store_ids is None:
                raise Refused("amd64 needs --store-ids (the file drill.py manifest --store-ids reads)")
            ids_out = outside(a.store_ids, "--store-ids")
        elif a.store_ids is not None:
            raise Refused("--store-ids is amd64's: arm64's images are pinned")
        d = docker if docker is not None else Docker(a.docker)
        if drill.inside_repo(WORK_ROOT):
            raise Refused("the work directory is inside the repo")
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="drill-", dir=str(WORK_ROOT)))
        try:
            if a.arch == "arm64":
                images = drill.read_json(IMAGES_FILE, "images.json")
                pin = images["local"][APP]["arm64"]
                rec = build_on(d, scan if scan is not None else a64_scan, work, "arm64", pin["tag"],
                               {"id": pin["id"], "config_digest": pin["config_digest"]})
            else:
                images = drill.read_json(IMAGES_FILE, "images.json")
                bridge_ref = os.environ.get(BRIDGE_ENV) or BRIDGE_TAG
                bid = store_id(d, bridge_ref)
                _bcfg, bcd, bt = prove(d, bid, work, "amd64")
                bt.unlink()
                rec = build_on(d, None, work, "amd64", images["local"][APP]["tag"], None)
                rec["bridge"] = {"store_id": bid, "config_digest": bcd}
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
            try:
                WORK_ROOT.rmdir()                 # only when empty: another build's directory stays
            except OSError:
                pass
        if a.arch == "arm64" and a.write_pins:
            drill.write_json(PINS_FILE, pins_doc(rec))
        if ids_out is not None:
            drill.write_json(ids_out, {"format": 1, "about": "the PC's amd64 drill images (build_drill.py build --arch amd64): store "
                                       "IDs and config digests for drill.py manifest --store-ids; never pinned, never in the repo",
                                       "arch": "amd64",
                                       "images": {v: {"store_id": rec["pins"][v]["id"], "config_digest": rec["pins"][v]["config_digest"]}
                                                  for v in VERSIONS},
                                       "bridge": rec["bridge"]})
        if rec_out is not None:
            drill.write_json(rec_out, rec)
        print(json.dumps({"pins": rec["pins"], "scans": rec["scans"], "pins_written": bool(a.write_pins)}, indent=1, sort_keys=True))
        return 0
    except Refused as exc:
        print("build_drill: refused: %s" % exc, file=sys.stderr)
        return 2
    except (BuildError, drill.DrillError, a64scan.ScanError, OSError, KeyError, TypeError, ValueError) as exc:
        print("build_drill: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
