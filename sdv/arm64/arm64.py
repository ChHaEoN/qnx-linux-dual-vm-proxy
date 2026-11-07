#!/usr/bin/env python3
"""arm64.py -- the SDV slice's arm64 images on the PC: build and pin them, scan them for code an ARMv8.0 core lacks, and
smoke them under emulation as a Cortex-A72 (sdv/arm64; SDV Phase 3 WP0).

Standard library only. Run in WSL from the repo root, where Docker Engine runs (its
containerd image store; buildx under the host's existing qemu-aarch64 binfmt registration; no privileged container):

    python3 sdv/arm64/arm64.py build [--gen DIR] [--write-pins] [--out FILE]
    python3 sdv/arm64/arm64.py scan --out FILE [--work DIR]
    python3 sdv/arm64/arm64.py smoke [--out FILE]

build  The three local images for linux/arm64: the claim bridge through sdv/bridge/build_image.py --arch arm64, the app
       and the recorder through sdv/stack/stack.py's build_local_arm64, each from its own staged context with its
       aarch64 lock, each tagged <tag>-arm64 (never the amd64 tag). A build that exits 0 but leaves no image under its
       tag is an error on either path, in the same words ("the build left no image tagged <tag>": build_image's
       BuildError, stack's StackError), printed as the command's error line, and no pin is read. Each image's pin is
       read back from the daemon: its ID (the containerd store's ID of a built image is its manifest digest) and the
       config digest of the manifest that ID names in a `docker save` stream (the manifest hash-checked against the ID,
       the config against its digest, its architecture arm64). --write-pins writes them into sdv/stack/images.json: each
       local entry's `arm64` {id, config_digest, tag, lock}, and the top-level `bridge` entry (not under `local`, which
       build_local builds whole) with the bridge's pin and the three labels it was built with, so a new generation
       means a new bridge pin.
scan   Every ELF in the seven images' arm64 layers through a64scan.py: the three local images from a `docker save` tar of
       their pinned IDs (the manifest and config checked against the pins, every layer against its digest), the four
       upstream images from their pinned arm64 manifests (images.json upstream.*.arm64_manifest) fetched from the
       registry by digest, each blob hash-checked; and the two native wheels of sdv/sim/requirements.aarch64.lock
       (bitstruct, wrapt), fetched from PyPI by the lock's file name and checked against the lock's hash. Each pinned
       index is read too: its linux/arm64 entry must be the pinned arm64 manifest, the base's included, and every local
       image's first layers must be the base's arm64 layers (the config's diff_ids). It writes scan.json (never inside
       the repo) and passes when the gate holds:
         - 0 unguarded LSE words, 0 LDAPR and 0 LOR in every scanned object; no object unread; every object with an
           executable PT_LOAD read as more than 0 words (a64scan's rule); the post-v8.0 counts are listed, not gated,
           and so is where each flagged word sits (flagged_context: code-like or data-like neighbourhood, a64scan's
           CONTEXT OF A FLAGGED WORD), which never turns a flagged word into a pass;
         - the one exception, REVIEWED: an object whose sha256 is listed there, at the listed path in the listed image,
           and whose flagged words are exactly the listed ones (each identified as constant-table data kept in an
           executable section) is set aside and recorded under `reviewed` with its counts per class and the reason.
           Other bytes, another path or image, or one more or one fewer flagged word, and it is gated like any object;
           nothing else is set aside;
         - the floor: per upstream image at least UPSTREAM_FLOOR's objects and LSE words, the configured refusal
           floors, so a scan that reads less fails; every local image at least LOCAL_FLOOR_OBJECTS objects; every
           wheel at least one object. These are completeness gates, not evidence that all executable code was read.
smoke  Under emulation, after a canary: the arm64 python base reads getauxval(AT_HWCAP) through ctypes in a container
       run with -e QEMU_CPU=cortex-a72, and again with QEMU_CPU=max. HWCAP_ATOMICS (bit 8) must be clear under the
       first and set under the second, both on aarch64; otherwise a CPU setting that never reached qemu would pass every
       image, and no image smoke runs. Then per local image, with QEMU_CPU=cortex-a72 and --network none: the same
       HWCAP read inside the image (atomics clear), and its probe: the app and the recorder import
       kuksa_client, grpc, google.protobuf, websockets and wcwidth; the bridge runs `check` with a read-only root, and
       the contract sha256, catalog digest and DBC sha256 its check line reports must each equal images.json's bridge
       label (the generation the pin was built from; `label_problems` says which differs). A probe passes on exit 0
       only (132 is SIGILL).

Does not demonstrate: that any image runs on the a1.metal host (Phase 3 V1 runs them there); that the crypto libraries' v8.2
code is dispatched by HWCAP; post-v8.0 classes the scan does not classify (FP16 arithmetic, SVE, non-hint PAC, JSCVT,
LDAPUR); code generated or loaded at run time; that control never reaches a reviewed table (a static scan reads what
the bytes are, not where execution goes); under emulation, anything beyond the paths the probes run; any timing.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.dont_write_bytecode = True
for _d in (HERE, REPO / "sdv" / "bridge", REPO / "sdv" / "stack"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
import a64scan as a64  # noqa: E402
import build_image  # noqa: E402
import stack  # noqa: E402

PLATFORM = "linux/arm64"
A72 = "cortex-a72"
MAX = "max"
AT_HWCAP = 16
HWCAP_ATOMICS = 1 << 8
CANARY_EXPECT = {A72: False, MAX: True}      # HWCAP_ATOMICS set? A Cortex-A72 (ARMv8.0) has no LSE
CANARY_CODE = ("import ctypes, platform; g = ctypes.CDLL(None).getauxval; g.restype = ctypes.c_ulong; "
               "g.argtypes = [ctypes.c_ulong]; print(platform.machine(), g(%d))" % AT_HWCAP)
IMPORT_PROBE = "import kuksa_client, grpc, google.protobuf, websockets, wcwidth"
BRIDGE = "bridge"
LABEL_OF = {"catalog_digest": "sdv.kind4.catalog_digest", "contract_sha256": "sdv.kind4.contract_sha256",
            "dbc_sha256": "sdv.kind4.dbc_sha256"}
# Where the bridge's `check` line (sdv/bridge/bridge_sources.py check) reports each label's value: the contract's sha256
# and catalog digest it loaded, the DBC's sha256.
CHECK_FIELD_OF = {"contract_sha256": ("contract", "sha256"), "catalog_digest": ("contract", "digest"), "dbc_sha256": ("dbc", "sha256")}
BRIDGE_ABOUT = ("The claim bridge's arm64 image (sdv/bridge/build_image.py --arch arm64; SDV Phase 3 WP0), here and not "
                "under local, which build_local builds whole. It bakes in the generated contract: the labels are the "
                "generation it was built from, so a new generation means a rebuild and a new pin.")
# The refusal floors: per upstream image, (objects, LSE words) a scan must reach. They retain the thresholds selected
# from the preceding read-only scan; a scan reading less fails. They are not a complete-code proof.
UPSTREAM_FLOOR = {"kuksa-databroker": (1, 32), "kuksa-can-provider": (369, 165), "kuksa-csv-provider": (347, 150),
                  "kuksa-mock-provider": (231, 166)}
LOCAL_FLOOR_OBJECTS = 80       # the python base's CPython layer alone; every local image holds it
SIM_NATIVE = ("bitstruct", "wrapt")
SIM_LOCK = REPO / "sdv" / "sim" / "requirements.aarch64.lock"
PIN_KEYS = ("id", "config_digest", "tag", "lock")
# The reviewed exceptions (SDV Phase 3 WP0). Three objects of kuksa-mock-provider's base layer whose
# every flagged word lies in a constant table the library keeps in its executable section. Each span was checked against
# the table's definition: the P-256 multiples of the generator and the SHA-2 round constants (the cube roots of the
# first primes) rebuilt and found byte for byte equal to the object's bytes there; the cipher's four S-box tables found
# to obey their defining relations over the whole span. An entry holds for exactly its sha256 and exactly its words
# (a64scan.flagged_words' form), at exactly its path in exactly its image; `tables` names what each span holds.
REVIEWED: Dict[str, Dict[str, Any]] = {
    "2898dbeef76a7c24bf2b810364da840352832ead378f10293bc947ca907e2555": {
        "path": "usr/lib/aarch64-linux-gnu/libcrypto.so.1.1",
        "image": "kuksa-mock-provider",
        "tables": (
            (0x10E000, 0x133000, "P-256 precomputed multiples of the generator: 37 subtables of 64 affine points in Montgomery form, each "
                                 "subtable's bytes transposed with a 64-byte stride"),
            (0x196300, 0x196400, "SHA-256 round constants K[0..63], 32-bit little-endian words"),
            (0x198740, 0x1989C0, "SHA-512 round constants K[0..79], 64-bit little-endian words"),
        ),
        "words": (
            "0x10e7f0 lor 88d20dab", "0x10eaa8 lor 08dc2c7e", "0x10eadc lor 489806a2", "0x10f720 lor 48920eae", "0x10f750 lor 088f3c13",
            "0x10fa14 lor 48c041be", "0x11038c lor c8d15fcf", "0x110394 amo 38a932df", "0x110cb4 lor c8d540b5", "0x110e64 lor c8847a1b",
            "0x110eec lor 88dd1f6d", "0x111144 lor c8923cfe", "0x11185c lor 08c973f3", "0x112744 amo 7863d2d0", "0x112910 lor 88c517fe",
            "0x113130 lor 08990b30", "0x113804 lor 08da56b9", "0x113988 lor c8cb3c71", "0x1139d4 lor c8df647b", "0x113fa0 lor c891560b",
            "0x1142c8 amo b87a80b9", "0x11463c lor 88cb3489", "0x11502c amo f8fa1067", "0x115278 amo b860105d", "0x1153d8 lor 089b1974",
            "0x115598 amo 782831cd", "0x1157f0 amo 786bf2de", "0x11599c casp 086aff3f", "0x115b44 amo 3878023b", "0x115f8c lor 088e3b80",
            "0x11613c lor 0896015a", "0x11638c lor 889a269c", "0x1163cc amo f8b8d233", "0x11665c amo b829e3cf", "0x116bf8 amo f87bf1d8",
            "0x116df8 lor c88f7b13", "0x116ee8 amo 38a6d321", "0x11717c lor 489e66d7", "0x1171f8 amo 386e00e9", "0x117274 amo 78ed7251",
            "0x117358 lor 88c36fef", "0x117758 lor c8ca4658", "0x117c00 amo 782c5244", "0x118234 amo 38b12385", "0x118f58 amo b869e1eb",
            "0x11914c lor 48947a81", "0x1198a4 lor c8c66dd2", "0x119dcc amo 78bb9198", "0x11a04c lor 88c14ede", "0x11a1e4 amo f8be014a",
            "0x11a65c amo f8ff51d2", "0x11a664 lor 488e1a2a", "0x11a6bc lor c8933947", "0x11aff8 lor 88de1c47", "0x11b084 amo 78f030dd",
            "0x11b254 cas 88bc7e38", "0x11b65c lor 48de0a06", "0x11b750 amo b8a5a362", "0x11c558 amo 386d03a7", "0x11c5fc lor 488d6aef",
            "0x11c6b8 lor 888f2829", "0x11d028 lor 48de1167", "0x11e4dc lor 88cc66ff", "0x11e7e4 lor 48df2e37", "0x11e828 lor 089938a8",
            "0x11e864 amo f8f133bf", "0x11ed68 amo 38af3297", "0x11f5ac amo 387e22e6", "0x11f624 amo b873d362", "0x120028 lor c88a6572",
            "0x1212a4 amo 38f17150", "0x121538 lor 489c1edf", "0x121934 lor 48c4343f", "0x121c20 lor 88cb1251", "0x1220d8 amo 78f94057",
            "0x122d3c amo 38367068", "0x123120 amo f83e037f", "0x1236ac amo 38ed20d1", "0x12465c amo 382792e0", "0x124764 lor 48c72ffd",
            "0x124a54 cas 88a47da7", "0x1250f0 amo 7877c078", "0x125260 amo f8b68149", "0x125280 lor c89c4c13", "0x12540c amo 3878a151",
            "0x125774 lor 888371e5", "0x125b8c amo 38ff32a5", "0x125b94 amo 783c2096", "0x12623c lor c8cd3ba7", "0x1262f8 lor 888f0504",
            "0x126330 amo 78b24220", "0x1264bc lor c8cf506a", "0x1264f8 lor 88d82a43", "0x1267f0 lor 88c40c2e", "0x126f78 lor c8846e31",
            "0x127180 lor 08cf1dd1", "0x12723c lor c893041e", "0x1272bc cas c8a67cd2", "0x127454 casp 48677c79", "0x127664 amo 386bc0a8",
            "0x127814 amo 386b3140", "0x127a18 lor c8991036", "0x127aac amo 78fcc26f", "0x127c3c lor c8c311b0", "0x127e34 lor 48925c82",
            "0x127f60 amo 782ea205", "0x127f78 amo 78a663bd", "0x12801c lor c8d966b9", "0x129184 amo f8e5f19b", "0x129834 lor 08d41348",
            "0x129e90 lor 488c3321", "0x12a054 amo 386de3cd", "0x12a6e0 lor c88905f2", "0x12a72c lor 88de47f1", "0x12ab20 amo 78b6c1b1",
            "0x12ab80 amo b8f56188", "0x12abbc lor 48930c2d", "0x12ac50 lor c888694d", "0x12aca8 lor 48913cef", "0x12ad00 amo b8ff938f",
            "0x12ae38 lor 08995e07", "0x12b70c amo f8b972a9", "0x12b730 casp 483a7e67", "0x12b95c lor 48cb763e", "0x12bd2c lor c88444eb",
            "0x12bdbc lor c8c85134", "0x12be28 amo 386b203a", "0x12cb04 lor c89744bd", "0x12d3cc amo b8260137", "0x12dc24 lor 08861454",
            "0x12e284 amo 3874e0a6", "0x12e704 amo 787ae352", "0x12e8c0 lor 889705ad", "0x12e980 lor c8de13a5", "0x12e9b0 amo b82e8089",
            "0x12eaec amo b8a3a3e7", "0x12eea0 amo 7839a1f1", "0x12f094 lor c8c029f8", "0x12fa18 lor 888d5a33", "0x12fa58 lor 48c9253e",
            "0x130270 amo f826d279", "0x130d30 amo b8b7517b", "0x130ed4 lor 88c85eec", "0x130f70 amo 78383187", "0x131064 lor 0897171e",
            "0x1312a8 lor 88cc7f64", "0x131338 lor 088312e6", "0x1314ec amo 38e19074", "0x131528 lor 48c25d83", "0x131670 lor 08893221",
            "0x131750 amo 78a90343", "0x131bf0 amo 78ef42a0", "0x131f0c ldapr 38bfc197", "0x132abc amo 787a0148", "0x132c68 amo 78629071",
            "0x1963e4 amo 78a5636f", "0x19890c amo 78a5636f",
        ),
    },
    "d68ff3ebbdfd71e1a129df9c58d0da8b4376be10c1c198a27a5c70f7f7f2c080": {
        "path": "usr/lib/aarch64-linux-gnu/libgcrypt.so.20.2.8",
        "image": "kuksa-mock-provider",
        "tables": (
            (0x47020, 0x48020, "Camellia SP tables sp1110, sp0222, sp3033 and sp4404, interleaved per index, 256 x 16 bytes"),
            (0x60520, 0x60620, "SHA-256 round constants K[0..63], 32-bit little-endian words"),
        ),
        "words": (
            "0x475cc lor c8c800c8", "0x476ac amo 78780078", "0x4770c lor 88880088", "0x4774c amo f8f800f8", "0x4792c amo b8b800b8",
            "0x47f8c amo 38380038", "0x60604 amo 78a5636f",
        ),
    },
    "0646f0e0351faf3c0d6223542a9e8d3a5950ea0a22ee9534bc51d5f405d3cbc7": {
        "path": "usr/lib/aarch64-linux-gnu/libgnutls.so.30.29.1",
        "image": "kuksa-mock-provider",
        "tables": (
            (0x14FCC0, 0x14FDC0, "SHA-256 round constants K[0..63], 32-bit little-endian words"),
            (0x151BC0, 0x151E40, "SHA-512 round constants K[0..79], 64-bit little-endian words"),
        ),
        "words": (
            "0x14fda4 amo 78a5636f", "0x151d8c amo 78a5636f",
        ),
    },
}
REVIEWED_REASON = ("reviewed: every flagged word lies in a constant table kept in an executable section, each table checked "
                   "against its definition")


class Arm64Error(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def outside_repo(path: Path) -> Path:
    p = Path(path).expanduser()
    r, repo = p.resolve(), REPO.resolve()
    if r == repo or repo in r.parents:
        raise Arm64Error("%s is inside the repo: build, scan and smoke records stay outside it" % p)
    return p


def docker(args: Sequence[str], timeout: float = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["docker"] + list(args), capture_output=True, text=True, timeout=timeout)


def local_pins(images: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """The three arm64 pins: each local image's, and the bridge's (images.json's top-level bridge entry)."""
    out = {name: spec["arm64"] for name, spec in images["local"].items()}
    out[BRIDGE] = images[BRIDGE]["arm64"]
    return out


# --- build -----------------------------------------------------------------------------------------

def saved_from_daemon(image_id: str, config_digest: Optional[str] = None, limit: int = 4 << 20) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The manifest the ID names and its config, from a `docker save` stream (only blobs up to limit bytes are kept),
    each hash-checked; the config digest must be the expected one when given."""
    p = subprocess.Popen(["docker", "save", image_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    blobs: Dict[str, bytes] = {}
    assert p.stdout is not None and p.stderr is not None
    try:
        with tarfile.open(fileobj=p.stdout, mode="r|") as tf:
            for m in tf:
                if m.isreg() and m.name.startswith("blobs/sha256/") and m.size <= limit:
                    f = tf.extractfile(m)
                    if f is not None:
                        blobs["sha256:" + m.name.rsplit("/", 1)[1]] = f.read()
        for _chunk in iter(lambda: p.stdout.read(1 << 20), b""):    # type: ignore[union-attr]
            pass
    finally:
        err = p.stderr.read().decode("utf-8", "replace")
        rc = p.wait(timeout=600)
    if rc != 0:
        raise Arm64Error("docker save %s: exit %d: %s" % (image_id, rc, err.strip()[-500:]))

    def get(digest: str) -> bytes:
        if digest not in blobs:
            raise a64.ScanError("the saved image has no blob %s" % digest)
        return blobs[digest]
    return a64.saved_image(get, image_id, config_digest)


def pin_of(image_id: str, tag: str, lock: str) -> Dict[str, str]:
    man, cfg = saved_from_daemon(image_id)
    if cfg.get("architecture") != "arm64" or cfg.get("os") != "linux":
        raise Arm64Error("%s (%s) is %s/%s, not linux/arm64" % (image_id, tag, cfg.get("os"), cfg.get("architecture")))
    return {"id": image_id, "config_digest": man["config"]["digest"], "tag": tag, "lock": lock}


def build(gen: Path) -> Dict[str, Any]:
    images = stack.load_images()
    started = utc_now()
    bridge = build_image.build(gen, smoke=False, arch="arm64")
    local = stack.build_local_arm64(images)
    pins = {name: pin_of(r["image_id"], r["tag"], r["lock"]) for name, r in local.items()}
    pins[BRIDGE] = pin_of(bridge["image_id"], bridge["tag"], bridge["lock"])
    return {"started_utc": started, "finished_utc": utc_now(), "bridge": bridge, "local": local, "pins": pins,
            "bridge_labels": {LABEL_OF[k]: v for k, v in sorted(bridge["labels"].items())}}


def with_pins(images: Dict[str, Any], pins: Dict[str, Dict[str, str]], labels: Dict[str, str]) -> Dict[str, Any]:
    out = json.loads(json.dumps(images))
    for name in out["local"]:
        out["local"][name]["arm64"] = {k: pins[name][k] for k in PIN_KEYS}
    out[BRIDGE] = {"about": BRIDGE_ABOUT, "arm64": {k: pins[BRIDGE][k] for k in PIN_KEYS}, "labels": dict(labels)}
    return out


def write_pins(record: Dict[str, Any]) -> None:
    new = with_pins(stack.load_images(), record["pins"], record["bridge_labels"])
    stack.IMAGES_FILE.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- scan ------------------------------------------------------------------------------------------

def check_index(client: a64.RegistryClient, index_digest: str, arm64_manifest: str) -> Dict[str, Any]:
    idx = json.loads(client.manifest(index_digest))          # hash-checked against the index digest
    got = a64.platform_entry(idx)
    return {"index": index_digest, "arm64_entry": got, "ok": got == arm64_manifest}


def registry_image(client: a64.RegistryClient, manifest: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    man = a64.manifest_of(client.manifest(manifest), manifest)
    return man, json.loads(client.blob(man["config"]["digest"]))


def scan_local(name: str, pin: Dict[str, str], work: Path, base_diff_ids: List[str]) -> Dict[str, Any]:
    tar = work / ("%s.tar" % name)
    p = docker(["save", "-o", str(tar), pin["id"]], timeout=1800)
    if p.returncode != 0:
        raise Arm64Error("docker save %s: exit %d: %s" % (pin["id"], p.returncode, (p.stderr or p.stdout).strip()[-500:]))
    try:
        r = a64.scan_saved_image(str(tar), pin["id"], pin["config_digest"])
    finally:
        if tar.exists():
            tar.unlink()
    r["pin"] = dict(pin)
    r["base_layers_match"] = r["diff_ids"][:len(base_diff_ids)] == base_diff_ids
    return r


def scan_upstream(name: str, u: Dict[str, Any], work: Path) -> Dict[str, Any]:
    client = a64.RegistryClient(u["repo"])
    idx = check_index(client, u["index_digest"], u["arm64_manifest"])
    man, cfg = registry_image(client, u["arm64_manifest"])
    col = a64.Collector()
    blob = work / "layer.blob"
    try:
        for i, layer in enumerate(man["layers"]):
            client.blob_to(layer["digest"], str(blob))
            with open(blob, "rb") as f:
                a64.scan_layer(f, layer["digest"], col, "L%d:" % i)
    finally:
        if blob.exists():
            blob.unlink()
    return {"repo": u["repo"], "version": u.get("version"), "manifest": u["arm64_manifest"], "index": idx, "index_ok": idx["ok"],
            "config_digest": man["config"]["digest"], "architecture": cfg.get("architecture"), "variant": cfg.get("variant"),
            "layers": [lay["digest"] for lay in man["layers"]], "summary": col.summary(), "objects": col.objects}


def lock_files(lock: Path) -> Dict[str, Tuple[str, str, str]]:
    pins = re.findall(r"^([a-z0-9-]+)==(\S+) \\\n\s+--hash=sha256:([0-9a-f]{64})\n\s+# (\S+\.whl)$",
                      lock.read_text(encoding="ascii"), re.M)
    return {n: (v, h, w) for n, v, h, w in pins}


def scan_wheel(name: str) -> Dict[str, Any]:
    ver, sha, whl = lock_files(SIM_LOCK)[name]
    with urllib.request.urlopen("https://pypi.org/pypi/%s/%s/json" % (name, ver), timeout=60) as r:
        meta = json.loads(r.read())
    urls = [u["url"] for u in meta["urls"] if u["filename"] == whl]
    if len(urls) != 1:
        raise Arm64Error("PyPI lists %d files named %s" % (len(urls), whl))
    with urllib.request.urlopen(urls[0], timeout=300) as r:
        data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        raise Arm64Error("%s hashes to %s, the lock says %s" % (whl, got, sha))
    col = a64.Collector()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            col.blob("%s!%s" % (whl, member), z.read(member))
    return {"file": whl, "sha256": sha, "sha256_ok": True, "summary": col.summary(), "objects": col.objects}


def path_in_image(path: str) -> str:
    """An object's path inside its image: a64scan's path without its `L<n>:` layer prefix (a wheel's path has none)."""
    return re.sub(r"^L\d+:", "", path)


def reviewed_split(r: Dict[str, Any], where: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[str]]:
    """One image's or wheel's record (`where` is its name) with REVIEWED applied: its summary without the gated words of
    every object that matches its entry exactly (sha256, the path in the image, the image, and the whole set of flagged
    words), those objects with their counts per class and the reason, and why an object whose sha256 is listed did not
    match (it then stays in the summary)."""
    s = dict(r["summary"])
    taken: List[Dict[str, Any]] = []
    why: List[str] = []
    for o in r.get("objects", ()):
        entry = REVIEWED.get(o.get("sha256", ""))
        if entry is None:
            continue
        if entry["image"] != where or path_in_image(o["path"]) != entry["path"]:
            why.append("%s (sha256 %s): reviewed as %s in %s, not this path in this image"
                       % (o["path"], o["sha256"], entry["path"], entry["image"]))
            continue
        got, want = set(a64.flagged_words(o)), set(entry["words"])
        if got != want:
            order = sorted(got ^ want, key=lambda w: int(w.split()[0], 16))
            why.append("%s (sha256 %s, reviewed): flagged word(s) not in the review %s; reviewed word(s) not flagged %s"
                       % (o["path"], o["sha256"], [w for w in order if w in got][:10], [w for w in order if w in want][:10]))
            continue
        for k in a64.GATED:
            s[k] -= o[k]
        s["flagged"] = [p for p in s["flagged"] if p != o["path"]]
        taken.append({"path": o["path"], "sha256": o["sha256"], "words": len(got), **{k: o[k] for k in a64.GATED},
                      "reason": REVIEWED_REASON, "tables": [["0x%x" % lo, "0x%x" % hi, what] for lo, hi, what in entry["tables"]]})
    return s, taken, why


def gate(rec: Dict[str, Any], pins: Dict[str, Dict[str, str]]) -> List[str]:
    """Why a scan record fails WP0's exit: see the module docstring."""
    out: List[str] = []
    if not rec.get("base_index_ok"):
        out.append("base: the pinned index does not list the pinned arm64 manifest")
    imgs = rec.get("images", {})
    for name in list(UPSTREAM_FLOOR) + list(pins):
        r = imgs.get(name)
        if r is None:
            out.append("%s: not scanned" % name)
            continue
        s = r["summary"]
        if r.get("architecture") != "arm64":
            out.append("%s: architecture %r" % (name, r.get("architecture")))
        s_rest, _taken, mismatch = reviewed_split(r, name)
        out += ["%s: %s" % (name, why) for why in a64.clean(s_rest) + mismatch]
        if name in UPSTREAM_FLOOR:
            n, lse = UPSTREAM_FLOOR[name]
            if not r.get("index_ok"):
                out.append("%s: the pinned index does not list the pinned arm64 manifest" % name)
            if s["objects"] < n or s["lse"] < lse:
                out.append("%s: below the floor: %d objects and %d LSE words, the floor is %d and %d" % (name, s["objects"], s["lse"], n, lse))
        else:
            if not r.get("base_layers_match"):
                out.append("%s: its first layers are not the base's arm64 layers" % name)
            if s["objects"] < LOCAL_FLOOR_OBJECTS:
                out.append("%s: below the floor: %d objects, the floor is %d" % (name, s["objects"], LOCAL_FLOOR_OBJECTS))
    for w in SIM_NATIVE:
        r = rec.get("wheels", {}).get(w)
        if r is None:
            out.append("wheel %s: not scanned" % w)
            continue
        if not r.get("sha256_ok"):
            out.append("wheel %s: not the lock's file" % w)
        if r["summary"]["objects"] < 1:
            out.append("wheel %s: below the floor: no object" % w)
        s_rest, _taken, mismatch = reviewed_split(r, w)
        out += ["wheel %s: %s" % (w, why) for why in a64.clean(s_rest) + mismatch]
    return out


def scan(images: Dict[str, Any], work: Path) -> Dict[str, Any]:
    pins = local_pins(images)
    work.mkdir(parents=True, exist_ok=True)
    rec: Dict[str, Any] = {"format": 1, "started_utc": utc_now(), "floor": {"upstream": UPSTREAM_FLOOR, "local_objects": LOCAL_FLOOR_OBJECTS},
                           "rule": {"guard": a64.GUARD_SHAPE, "fallback_window_words": a64.FALLBACK_WINDOW,
                                    "onefile_depth": a64.PYI_MAX_DEPTH, "gated": list(a64.GATED), "info": sorted(a64.INFO),
                                    "reviewed": {sha: {"path": e["path"], "image": e["image"], "words": len(e["words"]),
                                                       "tables": [["0x%x" % lo, "0x%x" % hi, what] for lo, hi, what in e["tables"]]}
                                                 for sha, e in sorted(REVIEWED.items())}},
                           "tools": {"a64scan.py": stack.sha256_file(HERE / "a64scan.py"), "arm64.py": stack.sha256_file(HERE / "arm64.py")},
                           "images": {}, "wheels": {}}
    base = images["base"]["python"]
    client = a64.RegistryClient(base["repo"])
    rec["base_index"] = check_index(client, base["index_digest"], base["arm64_manifest"])
    rec["base_index_ok"] = rec["base_index"]["ok"]
    _man, base_cfg = registry_image(client, base["arm64_manifest"])
    base_diff_ids = list((base_cfg.get("rootfs") or {}).get("diff_ids") or [])
    rec["base_diff_ids"] = base_diff_ids
    for name, pin in pins.items():
        rec["images"][name] = scan_local(name, pin, work, base_diff_ids)
    for name, u in images["upstream"].items():
        rec["images"][name] = scan_upstream(name, u, work)
    for w in SIM_NATIVE:
        rec["wheels"][w] = scan_wheel(w)
    rec["finished_utc"] = utc_now()
    rec["failures"] = gate(rec, pins)
    rec["verdict"] = "pass" if not rec["failures"] else "FAIL"
    # The objects REVIEWED set aside, per image or wheel, and any entry no scanned object matched.
    rec["reviewed"] = {}
    for kind, group in (("image", rec["images"]), ("wheel", rec["wheels"])):
        for name, r in group.items():
            taken = reviewed_split(r, name)[1]
            if taken:
                rec["reviewed"]["%s %s" % (kind, name)] = taken
    seen = {t["sha256"] for ts in rec["reviewed"].values() for t in ts}
    rec["reviewed_unused"] = sorted(set(REVIEWED) - seen)
    # Information, never a pass (a64scan, CONTEXT OF A FLAGGED WORD): where the flagged words sit, per object.
    rec["flagged_context"] = {
        "%s %s" % (kind, name): [{"path": o["path"], "code_like": o["flagged_code_like"], "data_like": o["flagged_data_like"],
                                  "min_share": o["flagged_min_share"]} for o in r["objects"] if any(o[k] for k in a64.GATED)]
        for kind, group in (("image", rec["images"]), ("wheel", rec["wheels"])) for name, r in group.items()
        if r["summary"]["flagged"]}
    return rec


# --- smoke -----------------------------------------------------------------------------------------

def parse_canary(text: str) -> Tuple[Optional[str], Optional[int]]:
    """(machine, AT_HWCAP) from the canary's last `<machine> <decimal>` line."""
    for ln in reversed((text or "").splitlines()):
        m = re.fullmatch(r"(\S+) (\d+)", ln.strip())
        if m:
            return m.group(1), int(m.group(2))
    return None, None


def run_hwcap(ref: str, cpu: str) -> Dict[str, Any]:
    args = ["run", "--rm", "--network", "none", "--platform", PLATFORM, "-e", "QEMU_CPU=" + cpu, "--entrypoint", "python", ref,
            "-c", CANARY_CODE]
    p = docker(args, timeout=600)
    machine, hwcap = parse_canary(p.stdout)
    return {"qemu_cpu": cpu, "image": ref, "exit": p.returncode, "machine": machine, "hwcap": hwcap,
            "hwcap_hex": None if hwcap is None else "0x%x" % hwcap,
            "atomics": None if hwcap is None else bool(hwcap & HWCAP_ATOMICS), "stderr_tail": (p.stderr or "")[-400:]}


def canary_verdict(runs: Dict[str, Dict[str, Any]]) -> List[str]:
    """Why the canary fails: HWCAP_ATOMICS must be clear under cortex-a72 and set under max, both read on aarch64."""
    out = []
    for cpu, want in CANARY_EXPECT.items():
        r = runs.get(cpu)
        if r is None:
            out.append("%s: not run" % cpu)
        elif r["exit"] != 0 or r["machine"] != "aarch64" or r["hwcap"] is None:
            out.append("%s: exit %s, machine %r, hwcap %r" % (cpu, r["exit"], r["machine"], r["hwcap"]))
        elif bool(r["hwcap"] & HWCAP_ATOMICS) != want:
            out.append("%s: HWCAP_ATOMICS %s, expected %s" % (cpu, "set" if not want else "clear", "set" if want else "clear"))
    return out


def check_label_problems(check: Any, labels: Dict[str, str]) -> List[str]:
    """Why the bridge's `check` line does not match images.json's bridge labels: the contract sha256, catalog digest
    and DBC sha256 the image reports must each equal the label its pin was built with. A field the line lacks, or a
    label images.json lacks, is a difference."""
    out = []
    for key, (part, field) in CHECK_FIELD_OF.items():
        section = check.get(part) if isinstance(check, dict) else None
        got = section.get(field) if isinstance(section, dict) else None
        want = labels.get(LABEL_OF[key])
        if want is None or got != want:
            out.append("check reports %s.%s %r, images.json's bridge label %s is %r" % (part, field, got, LABEL_OF[key], want))
    return out


def probe_args(name: str, image_id: str) -> List[str]:
    common = ["run", "--rm", "--network", "none", "--platform", PLATFORM]
    if name == BRIDGE:
        return common + ["--read-only", "-e", "QEMU_CPU=" + A72, image_id, "check"]
    return common + ["-e", "QEMU_CPU=" + A72, "--entrypoint", "python", image_id, "-c", IMPORT_PROBE]


def smoke(images: Dict[str, Any]) -> Dict[str, Any]:
    base = images["base"]["python"]
    ref = "%s@%s" % (base["repo"], base["index_digest"])
    rec: Dict[str, Any] = {"started_utc": utc_now(), "qemu_cpu": A72, "canary_ref": ref, "images": {}}
    rec["canary"] = {cpu: run_hwcap(ref, cpu) for cpu in CANARY_EXPECT}
    rec["canary_problems"] = canary_verdict(rec["canary"])
    if rec["canary_problems"]:
        rec["ok"] = False
        rec["finished_utc"] = utc_now()
        return rec
    pins = local_pins(images)
    for name, pin in pins.items():
        hw = run_hwcap(pin["id"], A72)
        hw_ok = hw["exit"] == 0 and hw["machine"] == "aarch64" and hw["hwcap"] is not None and not hw["hwcap"] & HWCAP_ATOMICS
        args = probe_args(name, pin["id"])
        p = docker(args, timeout=900)
        entry: Dict[str, Any] = {"id": pin["id"], "hwcap": hw, "hwcap_ok": hw_ok, "probe": args[args.index(pin["id"]) + 1:],
                                 "exit": p.returncode, "sigill": p.returncode == 132, "stdout_tail": (p.stdout or "")[-600:],
                                 "stderr_tail": (p.stderr or "")[-600:]}
        ok = hw_ok and p.returncode == 0
        if name == BRIDGE and p.returncode == 0:
            try:
                entry["check"] = json.loads(p.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                entry["label_problems"] = ["check printed no JSON line"]
            else:
                entry["label_problems"] = check_label_problems(entry["check"], images[BRIDGE]["labels"])
            ok = ok and not entry["label_problems"]
        entry["ok"] = ok
        rec["images"][name] = entry
    rec["ok"] = len(rec["images"]) == len(pins) and all(e["ok"] for e in rec["images"].values())
    rec["finished_utc"] = utc_now()
    return rec


# --- command line ----------------------------------------------------------------------------------

def _dump(obj: Any, out: Optional[str]) -> None:
    text = json.dumps(obj, indent=1, sort_keys=True) + "\n"
    if out:
        path = outside_repo(Path(out))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the three arm64 images and read their pins back")
    b.add_argument("--gen", default=None, help="the generated contract's directory (default: SDV_GEN or sdv-out/gen)")
    b.add_argument("--write-pins", action="store_true", help="write the pins into sdv/stack/images.json")
    b.add_argument("--out", default=None, help="also write the build record here (outside the repo)")
    s = sub.add_parser("scan", help="scan the seven images and the two native sim wheels; write scan.json")
    s.add_argument("--out", required=True, help="scan.json (outside the repo)")
    s.add_argument("--work", default=str(stack.CACHE / "arm64-scan"), help="scratch for the save tars and layer blobs")
    m = sub.add_parser("smoke", help="the HWCAP canary, then each local image's probe under QEMU_CPU=cortex-a72")
    m.add_argument("--out", default=None, help="also write the smoke record here (outside the repo)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            if a.out:
                outside_repo(Path(a.out))
            gen = build_image.vf.contract_path(a.gen).parent
            rec = build(gen)
            if a.write_pins:
                write_pins(rec)
            _dump(rec, a.out)
            print(json.dumps({"pins": rec["pins"], "bridge_labels": rec["bridge_labels"], "written": a.write_pins}, indent=1,
                             sort_keys=True))
            return 0
        if a.cmd == "scan":
            out = outside_repo(Path(a.out))
            work = outside_repo(Path(a.work))
            rec = scan(stack.load_images(), work)
            _dump(rec, str(out))
            for name, r in sorted(rec["images"].items()) + sorted(rec["wheels"].items()):
                s_ = r["summary"]
                print("%-28s objects %5d  exec words %10d  lse %4d (guarded %4d, unguarded %d)  ldapr %d  lor %d  flagged in "
                      "code-like/data-like context %d/%d  info %s"
                      % (name, s_["objects"], s_["exec_words"], s_["lse"], s_["guarded"], s_["unguarded"], s_["ldapr"], s_["lor"],
                         s_["flagged_code_like"], s_["flagged_data_like"], json.dumps(s_["info"], sort_keys=True)))
            for where, taken in sorted(rec["reviewed"].items()):
                for t in taken:
                    print("reviewed, set aside: %s %s (sha256 %s, %d flagged words, exactly the listed ones: unguarded %d, "
                          "ldapr %d, lor %d)" % (where, t["path"], t["sha256"], t["words"], t["unguarded"], t["ldapr"], t["lor"]))
            if rec["reviewed_unused"]:
                print("reviewed entries no scanned object matched: %s" % rec["reviewed_unused"])
            print("verdict: %s%s" % (rec["verdict"], "".join("\n  " + f for f in rec["failures"])))
            return 0 if rec["verdict"] == "pass" else 1
        rec = smoke(stack.load_images())
        _dump(rec, a.out)
        print(json.dumps({"canary": {k: {f: v[f] for f in ("exit", "machine", "hwcap_hex", "atomics")} for k, v in rec["canary"].items()},
                          "canary_problems": rec["canary_problems"],
                          "images": {k: {f: v[f] for f in ("exit", "sigill", "hwcap_ok", "ok", "label_problems") if f in v}
                                     for k, v in rec["images"].items()},
                          "ok": rec["ok"]}, indent=1, sort_keys=True))
        return 0 if rec["ok"] else 1
    except (Arm64Error, a64.ScanError, stack.StackError, build_image.BuildError, OSError, ValueError, KeyError,
            subprocess.TimeoutExpired) as err:
        print("arm64: %s: %s" % (type(err).__name__, err), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
