"""ota_docker.py -- the updater's Docker commands and the proof of an image's identity (sdv/ota; SDV Phase 6 WP1).

Standard library only.

ONE MEANING OF "IMAGE ID" (spec 2.1)  image_id is the config digest. What `docker run` and `docker image inspect` call an
  image's ID is the store's: under Docker Engine 29's containerd image store a built or loaded image's is its manifest
  digest and a pulled multi-platform image's its index digest (sdv/stack/images.json). The store's ID, or a reference
  by digest, is what the updater runs; the config digest is what it proves, and it carries only that one anywhere else.

THE PROOF  prove(ref, digest, image_id) reads a `docker save <ref>` stream (every blob up to BLOB_LIMIT bytes is kept;
  layers are larger and are skipped as they stream past) and requires, in order: the blob `digest` (the store ID, or
  the digest of a reference by digest) is there and hashes to its name; it is one platform's image manifest (an OCI or
  Docker v2 manifest with a config and layers) and not an index, which is refused as an index; its config blob is
  there and hashes to its name; and that config digest is the manifest entry's image_id. Anything else is a ProofError,
  and the updater refuses the record before the running container is touched.

WHAT IS NEVER LOGGED  A command whose argv names the registry (the pull of an ecr reference, its save, its run) can
  answer with the registry host, an account id or a role's name in its error text, so this module returns no standard
  error from a save at all and the updater logs only the exit status of every command that names the registry.

Docker is reached through `prefix` (default `docker`), which a test replaces with a stand-in. The class keeps every
  argument vector in one place, so a fake that answers call() and save_blobs() exercises the real argv.

Does not demonstrate: that a registry's manifest is the one a build made (the push tool reads that back, WP4), that an
image is safe to run, or any secure OTA property.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tarfile
import threading
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence

MANIFEST_TYPES = ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json")
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
BLOB_LIMIT = 4 << 20            # manifests and configs are small; layers are larger and are not kept
INDEX_LIMIT = 1 << 20           # a saved tar's index.json
CALL_TIMEOUT_S = 120.0          # inspect, stop, rm, ps, run
PULL_TIMEOUT_S = 900.0          # pull and load
SAVE_TIMEOUT_S = 900.0          # a save is killed past this
STOP_GRACE_S = 10               # docker stop -t 10 (spec section 3 item 6)

_SHA = re.compile(r"sha256:[0-9a-f]{64}")


class DockerError(RuntimeError):
    """A Docker command could not run or ended non-zero; the message holds no standard error."""


class ProofError(ValueError):
    """An image is not the one its manifest entry names."""


class Result(NamedTuple):
    rc: int
    out: str
    err: str


def sha256_file(path: Any) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def digest_of(ref: str) -> str:
    """The digest a store ID or a reference by digest names: the ID itself, or what follows the '@'."""
    d = ref.rsplit("@", 1)[-1]
    if not _SHA.fullmatch(d):
        raise ProofError("the reference names no sha256 digest")
    return d


def _hash_ok(raw: bytes, digest: str) -> bool:
    return "sha256:" + hashlib.sha256(raw).hexdigest() == digest


def proof(get: Callable[[str], Optional[bytes]], digest: str, image_id: str) -> None:
    """The proof of the module docstring over blobs read by get(digest) (None when absent); ProofError if it fails."""
    raw = get(digest)
    if raw is None:
        raise ProofError("the saved image holds no blob %s" % digest)
    if not _hash_ok(raw, digest):
        raise ProofError("the blob %s does not hash to its digest" % digest)
    try:
        man = json.loads(raw)
    except ValueError:
        raise ProofError("the blob %s is not JSON" % digest) from None
    if not isinstance(man, dict):
        raise ProofError("the blob %s is not a manifest" % digest)
    if man.get("mediaType") in INDEX_TYPES or "manifests" in man:
        raise ProofError("%s names an index, not one platform's image manifest: a reference that names an index is refused" % digest)
    if man.get("mediaType") not in MANIFEST_TYPES or not isinstance(man.get("config"), dict) or "layers" not in man:
        raise ProofError("%s is not one platform's image manifest" % digest)
    cd = man["config"].get("digest")
    if not isinstance(cd, str) or not _SHA.fullmatch(cd):
        raise ProofError("the manifest %s names no config digest" % digest)
    cfg = get(cd)
    if cfg is None:
        raise ProofError("the saved image holds no config blob %s" % cd)
    if not _hash_ok(cfg, cd):
        raise ProofError("the config %s does not hash to its digest" % cd)
    if cd != image_id:
        raise ProofError("the config digest is %s; the entry's image_id is %s" % (cd, image_id))


def tar_manifest_digest(path: Any) -> str:
    """The one manifest a `docker save` tar of one image lists in its index.json (its digest is the store's ID after
    `docker load`); ProofError when the tar lists none, several, or an index."""
    try:
        with tarfile.open(str(path), mode="r:") as tf:
            member = None
            for m in tf:
                if m.name in ("index.json", "./index.json"):
                    member = m
                    break
            if member is None or not member.isreg() or member.size > INDEX_LIMIT:
                raise ProofError("the tar has no index.json of at most %d bytes" % INDEX_LIMIT)
            f = tf.extractfile(member)
            raw = f.read() if f is not None else b""
    except (tarfile.TarError, EOFError):
        raise ProofError("the file is not a tar that can be read") from None
    try:
        index = json.loads(raw)
    except ValueError:
        raise ProofError("the tar's index.json is not JSON") from None
    listed = index.get("manifests") if isinstance(index, dict) else None
    if not isinstance(listed, list) or len(listed) != 1 or not isinstance(listed[0], dict):
        raise ProofError("the tar's index.json does not list exactly one image")
    d, mt = listed[0].get("digest"), listed[0].get("mediaType")
    if mt in INDEX_TYPES:
        raise ProofError("the tar lists an index, not one platform's image manifest")
    if mt not in MANIFEST_TYPES or not isinstance(d, str) or not _SHA.fullmatch(d):
        raise ProofError("the tar's index.json does not list one image manifest by its sha256")
    return d


class Docker:
    """Every Docker command the updater runs. call() and save_blobs() are the only two that reach a process."""

    def __init__(self, prefix: Sequence[str] = ("docker",)) -> None:
        self.prefix = list(prefix)

    def call(self, args: Sequence[str], env: Optional[Mapping[str, str]] = None, timeout: float = CALL_TIMEOUT_S) -> Result:
        full = None if env is None else dict(os.environ, **env)
        try:
            p = subprocess.run(self.prefix + list(args), capture_output=True, text=True, timeout=timeout, env=full,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return Result(-1, "", "did not end within %g s" % timeout)
        except OSError as exc:
            return Result(-1, "", "could not be started: %s" % (exc.strerror or type(exc).__name__))
        return Result(p.returncode, p.stdout, p.stderr)

    def save_blobs(self, ref: str) -> Dict[str, bytes]:
        """The blobs of `docker save <ref>` up to BLOB_LIMIT bytes each, by digest. DockerError, with no standard error
        in it, when the save cannot run, ends non-zero or is not a tar."""
        try:
            p = subprocess.Popen(self.prefix + ["save", ref], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL)
        except OSError as exc:
            raise DockerError("docker save could not be started: %s" % (exc.strerror or type(exc).__name__)) from None
        timer = threading.Timer(SAVE_TIMEOUT_S, p.kill)
        timer.start()
        blobs: Dict[str, bytes] = {}
        broken = False
        out = p.stdout
        assert out is not None
        try:
            try:
                with tarfile.open(fileobj=out, mode="r|") as tf:
                    for m in tf:
                        if m.isreg() and m.name.startswith("blobs/sha256/") and m.size <= BLOB_LIMIT:
                            f = tf.extractfile(m)
                            if f is not None:
                                blobs["sha256:" + m.name.rsplit("/", 1)[1]] = f.read()
            except tarfile.TarError:
                broken = True
            for _chunk in iter(lambda: out.read(1 << 20), b""):
                pass
        finally:
            out.close()
            rc = p.wait()
            timer.cancel()
        if rc != 0:
            raise DockerError("docker save: exit %d" % rc)
        if broken:
            raise DockerError("docker save: the stream is not a tar")
        return blobs

    def prove(self, ref: str, digest: str, image_id: str) -> None:
        """ProofError (or DockerError) unless the save of `ref` holds one platform's manifest `digest` whose config
        digest is `image_id`."""
        blobs = self.save_blobs(ref)
        proof(blobs.get, digest, image_id)

    def pull(self, ref: str, docker_config: Any) -> Result:
        return self.call(["pull", ref], env={"DOCKER_CONFIG": str(docker_config)}, timeout=PULL_TIMEOUT_S)

    def load(self, tar: Any) -> Result:
        return self.call(["load", "-i", str(tar)], timeout=PULL_TIMEOUT_S)

    def status(self, name: str) -> Optional[str]:
        """The container's state (running, exited, created, ...), or None when there is no such container."""
        r = self.call(["container", "inspect", "--format", "{{.State.Status}}", name])
        return r.out.strip() if r.rc == 0 else None

    def image_label(self, name: str) -> Optional[str]:
        """The container's own sdv.ota.image label (the config digest it was started as), or None when there is no such
        container. A container without the label answers `<no value>`, which no caller takes for a config digest."""
        r = self.call(["container", "inspect", "--format", '{{index .Config.Labels "sdv.ota.image"}}', name])
        return r.out.strip() if r.rc == 0 else None

    def has_image(self, ref: str) -> bool:
        """Whether the local store holds `ref` (`docker image inspect`: a read, which never pulls). Its standard error is
        not kept: for an ecr reference it can name the registry."""
        return self.call(["image", "inspect", "--format", "{{.Id}}", ref]).rc == 0

    def stop(self, name: str) -> Result:
        return self.call(["stop", "-t", str(STOP_GRACE_S), name], timeout=STOP_GRACE_S + CALL_TIMEOUT_S)

    def remove(self, name: str) -> Result:
        return self.call(["rm", name])

    def run(self, argv: Sequence[str]) -> Result:
        """`docker` + argv, where argv is ota_lite.app_run_argv(...) (it starts with 'run')."""
        return self.call(list(argv))

    def labelled(self, label: str) -> List[str]:
        """The names of every container, running or not, that carries the label key `label`."""
        r = self.call(["ps", "-a", "--filter", "label=" + label, "--format", "{{.Names}}"])
        if r.rc != 0:
            raise DockerError("docker ps: exit %d" % r.rc)
        return [n for n in r.out.split() if n]
