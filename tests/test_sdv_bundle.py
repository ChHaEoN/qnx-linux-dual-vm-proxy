"""The upload bundle (sdv/stack/bundle.py; SDV Phase 3 WP1): build, verify, verify --loaded and
verify-upstream, against a fake docker (and a fake sudo) on PATH.

This file runs on Python 3.10 as well as CI's 3.12: bundle.py's verify side runs on the instance's system python3
before any venv exists. These tests must also run under Python 3.10; nothing here may need a later Python either.

What is tested, and how (every image, digest, label, commit and file here is synthetic, except where a test says it
reads the real images.json or python-aarch64.json):

- bundle.py parses as Python 3.10 (ast feature_version) and imports the standard library only.
- build: every member written under its fixed name (the image tar, the generation's tar, one tar per recording, the DBC
  as <sha256>.dbc, the python-build-standalone tarball under its upload name) and bundle.json last, with the format, the
  commit and per member its name, role, bytes and sha256; every name in [A-Za-z0-9._-]; the tars hold their files
  under one top directory with no owner name; the image tar is `docker save` of the three pins by ID, holding exactly
  them (a shared layer once); verify then passes.
- build's refusals, each before anything is written: a generation whose vss_contract.py, slice.dbc or catalog digest
  is not the bridge pin's label, or whose slice.dbc is not a recording's or the repo's; a generation holding a file
  its manifest does not list, or one whose hash is not the listed one; a recording whose sigsim.log is not its
  manifest line's; a missing DBC; a tarball whose hash is not the pin's; an upload name outside the set; an image pin
  missing from the daemon or not linux/arm64; --out inside the repo or not empty; a commit that is not 40 hex. A save
  that fails removes what the build wrote.
- verify's refusals: each member whose bytes differ, size kept (its own sha256 message); a member missing, a file
  extra, a name listed twice, a name the upload does not accept; the image tar's manifest whose config digest is not
  the pin's, a pin the tar's index does not list, an image the index lists beyond the pins, a layer blob that does not
  hash to its digest; the generation against the bridge's labels, the tarball against python-aarch64.json.
- The review's findings (WP12fix): the image tar is exactly what a save by ID writes (a name twice with the good copy
  last, an unreferenced blob, a stray file, a directory other than blobs/ and blobs/sha256/, a repositories file
  naming a tag, a legacy manifest.json naming another
  config, a tag or other layers, a link: each refused by name); bundle.json's `pins` against the repo's pin files; each
  member read through the handle it was hashed by (another consistent recording renamed over a member between its hash
  and its read: the hashed bytes are what is checked, and the swap is refused); the generation's manifest.json against
  the one the bridge image bakes in (the synthetic bridge's own layer is a gzipped tar holding it), in verify and in
  build (a regenerated vss-databroker.json with its manifest entry rewritten, the three labels unchanged).
- Every plan's recordings (SDV Phase 7 WP3b; spec-2 2.1 and 2.3): the plans' table, its four recordings (the sigsim
  pair and the CARLA pair WP5a named) each carried once, and each read by the log its manifest line names (a sigsim.log
  beside a CARLA recording's carla.log is never read): build writes the four tars and lists each with its log and the
  log's sha256; a line whose generator and log do not pair is refused naming both, and so is a log that is not its
  line's, a .sha256 that names another file, a missing log or summary; build refuses without the CARLA pair, and verify
  refuses a bundle that lacks it or whose CARLA tar's log does not hash to its line.
- verify --loaded after a load: each pin found in the daemon by ID, linux/arm64, the bridge with its labels; refused
  for a missing image, another ID, amd64, a label that differs. verify-upstream: the pinned set passes, and each of
  its checks refuses on its own (missing, image ID, revision label, RepoDigests, architecture); nothing is pulled.
- --docker 'sudo -n docker' reaches every docker argv of build, verify --loaded and verify-upstream; without it none
  goes through sudo.
- Each command prints one JSON line of selected fields, never a raw inspect.
- The real python-aarch64.json: release, asset, version, the release's URLs, sha256, bytes, upload name; when
  ~/sdv-bundle-src holds the downloaded sums (SDV_BUNDLE_SRC), the pin is the published line for the asset and the
  sums file is the one pinned. The real images.json gives the three arm64 pins and the bridge's three labels.

The opt-in integration test (SDV_BUNDLE=1, SDV_BUNDLE_COMMIT=<the source commit read in Git Bash>) builds the real
bundle under ~/sdv-bundle/ (SDV_BUNDLE_OUT), verifies it, removes the three arm64 tags, loads the tar, verifies with
--loaded, and tags the pins again; every other image is unchanged.

What this does NOT show: that the carry holds from the PC's Docker Engine to the instance's, or that the instance's
store is containerd's (V1); that the images run on the instance; anything about the guest; any timing.
"""
import ast
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import types
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STACK_DIR = REPO / "sdv" / "stack"
BUNDLE_FILE = STACK_DIR / "bundle.py"
PYTHON_JSON = REPO / "sdv" / "sim" / "python-aarch64.json"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(STACK_DIR) not in sys.path:
    sys.path.insert(0, str(STACK_DIR))
import bundle  # noqa: E402

sys.dont_write_bytecode = _saved

POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX only: a fake docker and sudo on PATH (WSL, the 3.10 container)")
NAME = re.compile(r"[A-Za-z0-9._-]+")
HEX64 = re.compile(r"[0-9a-f]{64}")
REV = "org.opencontainers.image.revision"
LABEL_KEYS = ("sdv.kind4.catalog_digest", "sdv.kind4.contract_sha256", "sdv.kind4.dbc_sha256")
UPSTREAM = ("kuksa-databroker", "kuksa-can-provider", "kuksa-csv-provider", "kuksa-mock-provider")
LOCAL = ("hard-brake-hazard", "kuksa-csv-provider-recorder")
SYN_COMMIT = "c0ffee" + "1" * 34
DBC = b'VERSION ""\n\nBO_ 256 SliceDynamics: 8 SIGSRC\n SG_ LongVel : 0|16@1- (0.01,0) [-327.68|327.67] "m/s" VSSRX\n'
CONTRACT = b"# a synthetic generated contract\nCATALOG_DIGEST = 0x12345678\n"
CATALOG = "0x12345678"
ASSET = "cpython-3.12.99+20990101-aarch64-unknown-linux-gnu-install_only.tar.gz"
UPLOAD = "cpython-3.12-aarch64-install_only.tar.gz"
RAW_MARK = "raw-inspect-field-never-printed"
MEMBERS = ("sdv-arm64-images.tar", "sdv-gen.tar", "rec-20260930-sigsim-1b.tar", "rec-20261002-sigsim-1b-inj4.tar", "rec-20261019-carla-1.tar",
           "rec-20261019-carla-1-inj.tar", "dbc", UPLOAD)
# spec-2 2.3: every plan's recordings, the honest and the injected one of each (v1 and v2 share the sigsim pair)
PLAN_RECORDINGS = {"v1": {"honest": "20260930-sigsim-1b", "injected": "20261002-sigsim-1b-inj4"},
                   "v2": {"honest": "20260930-sigsim-1b", "injected": "20261002-sigsim-1b-inj4"},
                   "carla": {"honest": "20261019-carla-1", "injected": "20261019-carla-1-inj"}}
REC_LOGS = {"sigsim": "sigsim.log", "carla": "carla.log"}     # a recording's log by its generator (spec-2 2.1), this file's spelling


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha(Path(path).read_bytes())


# ============================================================ a fake docker and a fake sudo

FAKE_DOCKER = r'''#!%(python)s
import io, json, os, sys, tarfile
argv = sys.argv[1:]
state_path = os.environ["FAKE_DOCKER_STATE"]
blobs = os.environ["FAKE_DOCKER_BLOBS"]
state = json.load(open(state_path))
with open(os.environ["FAKE_DOCKER_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "via_sudo": os.environ.get("FAKE_VIA_SUDO") == "1"}) + "\n")
code, out, err = 0, "", ""


def blob(d):
    return open(os.path.join(blobs, d.split(":", 1)[1]), "rb").read()


if argv[:2] == ["image", "inspect"]:
    ref = argv[-1]
    info = state["images"].get(state["refs"].get(ref, ref))
    if info is None:
        code, err = 1, "Error response from daemon: No such image: %%s" %% ref
    else:
        out = json.dumps([info])
elif argv[:1] == ["save"]:
    if os.environ.get("FAKE_SAVE_FAIL") == "1":
        code, err = 1, "Error response from daemon: a synthetic save failure"
    else:
        dest = argv[argv.index("-o") + 1]
        ids = [a for a in argv[1:] + list(json.loads(os.environ.get("FAKE_SAVE_EXTRA", "[]"))) if a.startswith("sha256:")]
        seen = set()
        index = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": []}
        legacy = []
        with tarfile.open(dest, "w") as tf:
            def add(name, data):
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
            for iid in ids:
                man = json.loads(blob(iid))
                index["manifests"].append({"mediaType": man["mediaType"], "digest": iid, "size": len(blob(iid))})
                legacy.append({"Config": "blobs/sha256/" + man["config"]["digest"].split(":", 1)[1], "RepoTags": None,
                               "Layers": ["blobs/sha256/" + lay["digest"].split(":", 1)[1] for lay in man["layers"]]})
                for d in [iid, man["config"]["digest"]] + [lay["digest"] for lay in man["layers"]]:
                    if d not in seen:
                        seen.add(d)
                        add("blobs/sha256/" + d.split(":", 1)[1], blob(d))
            add("index.json", json.dumps(index).encode())
            add("manifest.json", json.dumps(legacy).encode())
            add("oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
elif argv[:1] == ["version"]:
    out = "29.6.2"
elif argv[:1] == ["info"]:
    out = '[["driver-type","io.containerd.snapshotter.v1"]]'
else:
    code, err = 2, "fake docker: no %%r here" %% (argv,)
json.dump(state, open(state_path, "w"))
if out:
    print(out)
if err:
    print(err, file=sys.stderr)
sys.exit(code)
'''

FAKE_SUDO = r'''#!%(python)s
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as f:
    f.write(json.dumps({"sudo": argv}) + "\n")
if argv[:1] != ["-n"] or len(argv) < 2:
    sys.exit(1)
os.environ["FAKE_VIA_SUDO"] = "1"
os.execvp(argv[1], argv[1:])
'''


def put_blob(blobs: Path, data: bytes) -> str:
    d = "sha256:" + sha(data)
    (blobs / d[7:]).write_bytes(data)
    return d


def make_image(blobs: Path, layers: List[bytes], labels: Dict[str, str], arch: str = "arm64") -> Dict[str, Any]:
    """A synthetic single-platform OCI image: its layers, config and manifest as blobs; returns its pin and the inspect
    record a containerd-store daemon gives for it (the ID is the manifest digest)."""
    lay = [put_blob(blobs, data) for data in layers]
    cfg = json.dumps({"architecture": arch, "os": "linux", "config": {"Labels": labels},
                      "rootfs": {"type": "layers", "diff_ids": lay}}, sort_keys=True).encode()
    cd = put_blob(blobs, cfg)
    man = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                      "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": cd, "size": len(cfg)},
                      "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar", "digest": d, "size": len(data)}
                                 for d, data in zip(lay, layers)]}, sort_keys=True).encode()
    mid = put_blob(blobs, man)
    info = {"Id": mid, "Architecture": arch, "Os": "linux", "Config": {"Labels": dict(labels)}, "RepoTags": [], "RepoDigests": [],
            "GraphDriver": {"Data": {"MergedDir": RAW_MARK}}}
    return {"id": mid, "config_digest": cd, "info": info}


def tar_layer(files: Dict[str, bytes]) -> bytes:
    """A gzipped layer tar (as a built image's layers are) holding files at their paths, deterministic."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime = len(data), 0
            tf.addfile(ti, io.BytesIO(data))
    return gzip.compress(buf.getvalue(), mtime=0)


def make_recording(d: Path, name: str, dbc_sha: str, events: bool, gen: str = "") -> None:
    """A recording as its tool writes one: the log its generator names (gen: by default carla for a name holding
    "-carla-", else sigsim), its .sha256, a manifest line whose recording.path names the log, summary.json and, for an
    injected one, events.json."""
    d.mkdir(parents=True)
    gen = gen or ("carla" if "-carla-" in name else "sigsim")
    log_name = REC_LOGS[gen]
    log = ("(0.000000) vcan0 100#%s\n" % name.encode().hex()[:16]).encode()
    (d / log_name).write_bytes(log)
    (d / (log_name + ".sha256")).write_text("%s  %s\n" % (sha(log), log_name), encoding="ascii")
    line = {"name": name, "profile_id": 3 if gen == "carla" else 1,
            "recording": {"format": "candump-log", "path": "~/sdv-recordings/%s/%s" % (name, log_name), "sha256": sha(log)},
            "source": {"generator": gen, "params": {"dbc_sha256": dbc_sha, "seed": 1}}}
    (d / "manifest-line.json").write_text(json.dumps(line), encoding="ascii")
    (d / "summary.json").write_text('{"name": "%s"}\n' % name, encoding="ascii")
    if events:
        (d / "events.json").write_text('{"events": []}\n', encoding="ascii")


def member_bytes(tf: tarfile.TarFile, member: Any) -> bytes:
    f = tf.extractfile(member)
    assert f is not None, member
    return f.read()


def json_lines(text: str) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def one_record(capsys) -> Dict[str, Any]:
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, out
    assert RAW_MARK not in out and "GraphDriver" not in out
    return json.loads(lines[0])


@pytest.fixture
def kit(tmp_path, monkeypatch):
    """A synthetic world: the fake docker (and sudo) on PATH holding the three arm64 pins and the four upstream images,
    images.json and python-aarch64.json pointing at them, a generation, the two recordings, the cached DBC, the repo's
    slice.dbc and the tarball; bundle's three file constants pointed at the synthetic files."""
    root = tmp_path
    blobs, bindir = root / "blobs", root / "bin"
    blobs.mkdir()
    bindir.mkdir()
    for name, text in (("docker", FAKE_DOCKER), ("sudo", FAKE_SUDO)):
        exe = bindir / name
        exe.write_text(text % {"python": sys.executable}, encoding="utf-8")
        exe.chmod(0o755)
    log, statef = root / "docker.jsonl", root / "docker-state.json"
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(statef))
    monkeypatch.setenv("FAKE_DOCKER_BLOBS", str(blobs))
    for var in ("FAKE_VIA_SUDO", "FAKE_SAVE_FAIL", "FAKE_SAVE_EXTRA"):
        monkeypatch.delenv(var, raising=False)
    dbc_sha = sha(DBC)
    labels = {"sdv.kind4.catalog_digest": CATALOG, "sdv.kind4.contract_sha256": sha(CONTRACT), "sdv.kind4.dbc_sha256": dbc_sha}
    # the generation
    gen = root / "gen"
    gen.mkdir()
    outputs = {}
    for name, data in (("vss_contract.py", CONTRACT), ("vss-databroker.json", b'{"Vehicle": {}}\n')):
        (gen / name).write_bytes(data)
        outputs[name] = {"sha256": sha(data), "bytes": len(data)}
    (gen / "manifest.json").write_text(json.dumps({"inputs": {"slice.dbc": dbc_sha}, "kind4": {"catalog_digest": CATALOG},
                                                   "outputs": outputs}), encoding="utf-8")
    # the images: two local and the bridge sharing a base layer, four upstream; the bridge's own layer bakes in the
    # generation's contract and manifest at the paths sdv/bridge/build_image.py stages them (app/sdv-out/gen/)
    bridge_layer = tar_layer({"app/sdv-out/gen/manifest.json": (gen / "manifest.json").read_bytes(),
                              "app/sdv-out/gen/vss_contract.py": CONTRACT})
    state: Dict[str, Any] = {"images": {}, "refs": {}}
    local, pins = {}, {}
    for name, label_set in [(n, {}) for n in LOCAL] + [("bridge", labels)]:
        own = bridge_layer if name == "bridge" else ("%s's own layer" % name).encode()
        img = make_image(blobs, [b"a shared base layer", own], label_set)
        tag = "sdv-local/%s:0.0.0-arm64" % name
        pins[name] = {"id": img["id"], "config_digest": img["config_digest"], "tag": tag, "lock": "x/requirements.aarch64.lock"}
        state["images"][img["id"]] = dict(img["info"], RepoTags=[tag])
        state["refs"][tag] = img["id"]
        if name != "bridge":
            local[name] = {"class": "app" if name == LOCAL[0] else "platform", "tag": tag[:-len("-arm64")], "arm64": pins[name]}
    upstream = {}
    for i, name in enumerate(UPSTREAM):
        index = "sha256:" + sha(("the index of %s" % name).encode())
        repo = "registry.invalid/sdv-test/%s" % name
        ref = "%s@%s" % (repo, index)
        rev = sha(name.encode())[:40]
        upstream[name] = {"repo": repo, "version": "0.0.%d" % i, "index_digest": index, "revision": rev}
        state["images"][index] = {"Id": index, "Architecture": "arm64", "Os": "linux", "Config": {"Labels": {REV: rev}},
                                  "RepoTags": [ref], "RepoDigests": [ref], "GraphDriver": {"Data": {"MergedDir": RAW_MARK}}}
        state["refs"][ref] = index
    images = {"format": 1, "upstream": upstream, "local": local, "bridge": {"arm64": pins["bridge"], "labels": labels}}
    images_file = root / "images.json"
    images_file.write_text(json.dumps(images, indent=1), encoding="utf-8")
    statef.write_text(json.dumps(state), encoding="utf-8")
    # the tarball and its pin
    src = root / "src"
    src.mkdir()
    pbs = b"a synthetic install_only tarball\n" * 64
    (src / ASSET).write_bytes(pbs)
    py = {"format": 1, "release": "20990101", "asset": ASSET, "python_version": "3.12.99", "target": "aarch64-unknown-linux-gnu",
          "flavor": "install_only", "sha256": sha(pbs), "bytes": len(pbs),
          "url": "https://example.invalid/releases/download/20990101/" + ASSET.replace("+", "%2B"),
          "sums_url": "https://example.invalid/releases/download/20990101/SHA256SUMS", "sums_sha256": "5" * 64,
          "upload_name": UPLOAD}
    python_file = root / "python-aarch64.json"
    python_file.write_text(json.dumps(py, indent=1), encoding="utf-8")
    # the recordings, the cached DBC, the repo's slice.dbc
    recs = root / "recordings"
    for name in bundle.RECORDINGS:
        make_recording(recs / name, name, dbc_sha, events=name in {p["injected"] for p in PLAN_RECORDINGS.values()})
    cache = root / "cache"
    (cache / "dbc").mkdir(parents=True)
    (cache / "dbc" / ("%s.dbc" % dbc_sha)).write_bytes(DBC)
    slice_dbc = root / "slice.dbc"
    slice_dbc.write_bytes(DBC)
    monkeypatch.setattr(bundle, "IMAGES_FILE", images_file)
    monkeypatch.setattr(bundle, "PYTHON_FILE", python_file)
    monkeypatch.setattr(bundle, "SLICE_DBC", slice_dbc)

    def build_args(out: Path, *extra: str) -> List[str]:
        return ["build", "--out", str(out), "--commit", SYN_COMMIT, "--gen", str(gen), "--recordings", str(recs),
                "--cache", str(cache), "--python-src", str(src)] + list(extra)

    def entries() -> List[Dict[str, Any]]:
        return json_lines(log.read_text(encoding="utf-8")) if log.exists() else []

    def calls() -> List[List[str]]:
        return [e["argv"] for e in entries() if "argv" in e]

    def get_state() -> Dict[str, Any]:
        return json.loads(statef.read_text(encoding="utf-8"))

    def put_state(s: Dict[str, Any]) -> None:
        statef.write_text(json.dumps(s), encoding="utf-8")

    def edit_json(path: Path, fn: Callable[[Any], None]) -> None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        fn(doc)
        path.write_text(json.dumps(doc, indent=1), encoding="utf-8")

    def remove_images() -> None:
        """The three arm64 images out of the store (as `docker image rm` of their tags), outside the fake's log."""
        s = get_state()
        for pin in pins.values():
            s["images"].pop(pin["id"], None)
            s["refs"].pop(pin["tag"], None)
        put_state(s)

    def load(tar: Path) -> List[str]:
        """`docker load -i tar` into the fake's store, outside its log: each manifest the index lists, untagged."""
        s, loaded = get_state(), []
        with tarfile.open(str(tar), "r:") as tf:
            index = json.loads(member_bytes(tf, "index.json"))
            for m in index["manifests"]:
                man = json.loads(member_bytes(tf, "blobs/sha256/" + m["digest"].split(":", 1)[1]))
                cfg = json.loads(member_bytes(tf, "blobs/sha256/" + man["config"]["digest"].split(":", 1)[1]))
                s["images"][m["digest"]] = {"Id": m["digest"], "Architecture": cfg["architecture"], "Os": cfg["os"],
                                            "Config": {"Labels": (cfg.get("config") or {}).get("Labels") or {}},
                                            "RepoTags": [], "RepoDigests": [], "GraphDriver": {"Data": {"MergedDir": RAW_MARK}}}
                loaded.append(m["digest"])
        put_state(s)
        return loaded

    return types.SimpleNamespace(root=root, gen=gen, recs=recs, cache=cache, src=src, slice_dbc=slice_dbc, images_file=images_file,
                                 python_file=python_file, pins=pins, labels=labels, upstream=upstream, dbc_sha=dbc_sha,
                                 bridge_layer="sha256:" + sha(bridge_layer),
                                 dbc_name="%s.dbc" % dbc_sha, build_args=build_args, entries=entries, calls=calls,
                                 get_state=get_state, put_state=put_state, edit_json=edit_json, remove_images=remove_images, load=load)


@pytest.fixture
def built(kit, capsys):
    kit.out = kit.root / "out"
    assert bundle.main(kit.build_args(kit.out)) == 0, capsys.readouterr().err
    capsys.readouterr()
    return kit


def member_name(kit, member: str) -> str:
    return kit.dbc_name if member == "dbc" else member


def rehash(kit, name: str) -> None:
    """bundle.json's entry for a member changed on purpose, so only the content check can refuse it."""
    p = kit.out / name

    def fix(doc):
        for m in doc["members"]:
            if m["name"] == name:
                m["bytes"], m["sha256"] = p.stat().st_size, sha_file(p)
    kit.edit_json(kit.out / "bundle.json", fix)


def rewrite_tar(path: Path, change: Callable[[str, bytes], Any]) -> None:
    """The tar written again member by member; change(name, data) returns new bytes, or None to drop the member."""
    with tarfile.open(str(path), "r:") as tf:
        items = [(m.name, member_bytes(tf, m)) for m in tf.getmembers() if m.isreg()]
    with tarfile.open(str(path), "w") as tf:
        for name, data in items:
            new = change(name, data)
            if new is None:
                continue
            ti = tarfile.TarInfo(name)
            ti.size = len(new)
            tf.addfile(ti, io.BytesIO(new))


def verify(kit, capsys, *extra: str):
    rc = bundle.main(["verify", "--in", str(kit.out)] + list(extra))
    return rc, one_record(capsys)


def pin_file_problem(kit, key: str) -> str:
    """verify's problem for a repo pin file that is not the one bundle.json was built from (its `pins`)."""
    built_from = json.loads((kit.out / "bundle.json").read_text(encoding="utf-8"))["pins"][key]
    path = kit.images_file if key == "sdv/stack/images.json" else kit.python_file
    return "bundle.json: built against %s %s; this repo's hashes to %s" % (key, built_from, sha_file(path))


def write_items(path: Path, items: List[Any]) -> None:
    """A tar written from (name, data) pairs in order, or (TarInfo, None) for an entry with no data (a link)."""
    with tarfile.open(str(path), "w") as tf:
        for name, data in items:
            if isinstance(name, tarfile.TarInfo):
                tf.addfile(name)
                continue
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))


def tar_items(path: Path) -> List[Any]:
    with tarfile.open(str(path), "r:") as tf:
        return [(m.name, member_bytes(tf, m)) for m in tf.getmembers() if m.isreg()]


def other_recording_tar(kit, name: str) -> Path:
    """Another recording under the same name, internally consistent (its own sigsim.log, sigsim.log.sha256 and manifest
    line, the same DBC), as bundle.py's write_tar writes one."""
    d = kit.root / "other" / name
    make_recording(d, name, kit.dbc_sha, events=name.endswith("inj4"))
    log = b"(0.000000) vcan0 100#0102030405060708\n(0.010000) vcan0 100#0807060504030201\n"
    (d / "sigsim.log").write_bytes(log)
    (d / "sigsim.log.sha256").write_text("%s  sigsim.log\n" % sha(log), encoding="ascii")
    kit.edit_json(d / "manifest-line.json", lambda line: line["recording"].update(sha256=sha(log)))
    tar = kit.root / "other" / ("rec-%s.tar" % name)
    bundle.write_tar(tar, name, bundle.dir_files(d))
    assert bundle.recording_contents(name, bundle.read_tar(tar, name))[1] == []
    return tar


# ============================================================ the module itself

def test_bundle_py_parses_as_python_3_10_and_imports_the_standard_library_only():
    tree = ast.parse(BUNDLE_FILE.read_text(encoding="utf-8"), feature_version=(3, 10))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative import: bundle.py runs from the repo archive by path"
            mods.add((node.module or "").split(".")[0])
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    assert stdlib, "sys.stdlib_module_names exists from Python 3.10"
    assert mods <= stdlib | {"__future__"}, mods - stdlib


# ============================================================ build

@POSIX
def test_build_writes_every_member_and_bundle_json_last_and_verify_takes_it(kit, capsys):
    out = kit.root / "out"
    assert bundle.main(kit.build_args(out)) == 0
    rec = one_record(capsys)
    assert rec["ok"] is True and rec["commit"] == SYN_COMMIT
    doc = json.loads((out / "bundle.json").read_text(encoding="utf-8"))
    names = [m["name"] for m in doc["members"]]
    assert names == ["sdv-arm64-images.tar", "sdv-gen.tar", "rec-20260930-sigsim-1b.tar", "rec-20261002-sigsim-1b-inj4.tar",
                     "rec-20261019-carla-1.tar", "rec-20261019-carla-1-inj.tar", kit.dbc_name, UPLOAD]
    assert [m["role"] for m in doc["members"]] == ["images", "gen", "recording", "recording", "recording", "recording", "dbc", "python"]
    assert doc["format"] == 1 and doc["commit"] == SYN_COMMIT
    assert sorted(os.listdir(out)) == sorted(names + ["bundle.json"])
    for m in doc["members"]:
        assert NAME.fullmatch(m["name"]) and m["bytes"] == (out / m["name"]).stat().st_size and m["sha256"] == sha_file(out / m["name"])
    by = {m["role"]: m for m in doc["members"]}
    assert by["python"]["asset"] == ASSET and by["python"]["release"] == "20990101" and by["python"]["sha256"] == sha_file(kit.src / ASSET)
    assert {k: v["id"] for k, v in by["images"]["images"].items()} == {k: v["id"] for k, v in kit.pins.items()}
    assert by["gen"]["labels"] == kit.labels and (out / kit.dbc_name).read_bytes() == DBC
    recs = {m["recording"]: m for m in doc["members"] if m["role"] == "recording"}
    assert sorted(recs) == sorted(bundle.RECORDINGS)
    for r, m in recs.items():          # each recording's own log, by its line, and its sha256
        log = REC_LOGS["carla" if "-carla-" in r else "sigsim"]
        assert (m["log"], m["log_sha256"]) == (log, sha_file(kit.recs / r / log)) and "sigsim_sha256" not in m, m
    # the tars: their files under one top directory, owned by no name, the recordings' events file carried
    for name, top, files in (("sdv-gen.tar", "gen", ["manifest.json", "vss-databroker.json", "vss_contract.py"]),
                             ("rec-20261002-sigsim-1b-inj4.tar", "20261002-sigsim-1b-inj4",
                              ["events.json", "manifest-line.json", "sigsim.log", "sigsim.log.sha256", "summary.json"]),
                             ("rec-20261019-carla-1-inj.tar", "20261019-carla-1-inj",
                              ["carla.log", "carla.log.sha256", "events.json", "manifest-line.json", "summary.json"])):
        with tarfile.open(str(out / name), "r:") as tf:
            members = tf.getmembers()
        assert all(m.uname == "" and m.gname == "" and m.uid == 0 and m.gid == 0 for m in members)
        assert sorted(m.name for m in members if m.isreg()) == ["%s/%s" % (top, f) for f in files]
        assert all(m.isreg() or (m.isdir() and m.name == top) for m in members)
    assert bundle.main(["verify", "--in", str(out)]) == 0
    v = one_record(capsys)
    assert v["ok"] is True and v["problems"] == [] and v["commit"] == SYN_COMMIT and v["loaded"] is False
    assert sorted(m["name"] for m in v["members"]) == sorted(names) and all(m["sha256_ok"] for m in v["members"])


@POSIX
def test_build_saves_the_three_pins_by_id_into_a_tar_that_holds_exactly_them(built):
    saves = [c for c in built.calls() if c[:1] == ["save"]]
    assert len(saves) == 1
    ids = [p["id"] for p in built.pins.values()]
    argv = saves[0]
    assert argv[:2] == ["save", "-o"] and argv[2] == str(built.out / "sdv-arm64-images.tar") and sorted(argv[3:]) == sorted(ids)
    with tarfile.open(str(built.out / "sdv-arm64-images.tar"), "r:") as tf:
        index = json.load(tf.extractfile("index.json"))
        blobs = [m.name for m in tf.getmembers() if m.name.startswith("blobs/")]
    assert sorted(m["digest"] for m in index["manifests"]) == sorted(ids)
    assert len(blobs) == len(set(blobs)) == 3 + 3 + 1 + 3            # three manifests, three configs, one shared layer, three own
    assert not [c for c in built.calls() if c[:1] in (["pull"], ["build"], ["load"], ["tag"])]


def _gen_contract(kit):
    new = CONTRACT + b"# another generation\n"
    (kit.gen / "vss_contract.py").write_bytes(new)
    kit.edit_json(kit.gen / "manifest.json", lambda m: m["outputs"]["vss_contract.py"].update(sha256=sha(new), bytes=len(new)))


def _recording_dbc(kit):
    p = kit.recs / "20261002-sigsim-1b-inj4" / "manifest-line.json"
    kit.edit_json(p, lambda line: line["source"]["params"].update(dbc_sha256="d" * 64))


@POSIX
@pytest.mark.parametrize("change, why", [
    (_gen_contract, "vss_contract.py hashes to"),
    (lambda kit: kit.edit_json(kit.images_file, lambda i: i["bridge"]["labels"].update({"sdv.kind4.dbc_sha256": "e" * 64})),
     "the generation's slice.dbc is %s, the bridge pin's label says %s" % (sha(DBC), "e" * 64)),
    (lambda kit: kit.edit_json(kit.gen / "manifest.json", lambda m: m["kind4"].update(catalog_digest="0x87654321")),
     "catalog digest 0x87654321"),
    (_recording_dbc, "recording 20261002-sigsim-1b-inj4's is " + "d" * 64),
    (lambda kit: kit.slice_dbc.write_bytes(DBC + b"\n"), "the repo's sdv/vss/slice.dbc's is"),
])
def test_build_refuses_a_generation_that_is_not_the_bridge_pins_or_the_recordings(kit, capsys, change, why):
    change(kit)
    out = kit.root / "out"
    assert bundle.main(kit.build_args(out)) == 1
    err = capsys.readouterr().err
    assert why in err, err
    assert not out.exists() and not [c for c in kit.calls() if c[:1] == ["save"]]


@POSIX
@pytest.mark.parametrize("change, why", [
    (lambda kit: (kit.gen / "stray.txt").write_text("x", encoding="ascii"), "its manifest lists"),
    (lambda kit: (kit.gen / "vss-databroker.json").write_text("{}", encoding="ascii"), "vss-databroker.json: sha256"),
    (lambda kit: (kit.recs / "20260930-sigsim-1b" / "sigsim.log").write_bytes(b"(0.0) vcan0 1#00\n"), "the manifest line's"),
    (lambda kit: (kit.cache / "dbc" / ("%s.dbc" % sha(DBC))).unlink(), "no cached DBC"),
    (lambda kit: (kit.src / ASSET).write_bytes(b"another tarball"), "is not the pinned"),
    (lambda kit: kit.edit_json(kit.python_file, lambda p: p.update(upload_name=ASSET)), "[A-Za-z0-9._-]"),
    (lambda kit: kit.put_state(dict(kit.get_state(), images={k: v for k, v in kit.get_state()["images"].items()
                                                             if k != kit.pins["hard-brake-hazard"]["id"]})),
     "hard-brake-hazard: %s" % "sha256:"),
    (lambda kit: kit.put_state(dict(kit.get_state(), images=dict(kit.get_state()["images"], **{
        kit.pins["bridge"]["id"]: dict(kit.get_state()["images"][kit.pins["bridge"]["id"]], Architecture="amd64")}))),
     "bridge: linux/amd64, not linux/arm64"),
])
def test_build_refuses_its_inputs_before_writing_anything(kit, capsys, change, why):
    change(kit)
    out = kit.root / "out"
    assert bundle.main(kit.build_args(out)) == 1
    err = capsys.readouterr().err
    assert why in err, err
    assert not out.exists() and not [c for c in kit.calls() if c[:1] == ["save"]]


def test_the_bundle_carries_every_plans_recordings_each_once():
    """Spec-2 2.3: the plans' table (vss_suite.py holds the same, tests/test_vss_harness.py holds the two equal), the CARLA
    pair named by WP5a's CARLA_HONEST, and the four recordings the bundle carries in the table's order; spec-2 2.1's log
    table (tests/test_sdv_stack.py holds it equal to sdv/inject/inject.py's)."""
    assert bundle.PLAN_RECORDINGS == PLAN_RECORDINGS
    assert bundle.CARLA_HONEST == "20261019-carla-1" == bundle.PLAN_RECORDINGS["carla"]["honest"]
    assert bundle.PLAN_RECORDINGS["carla"]["injected"] == bundle.CARLA_HONEST + "-inj"
    assert bundle.RECORDINGS == ("20260930-sigsim-1b", "20261002-sigsim-1b-inj4", "20261019-carla-1", "20261019-carla-1-inj")
    assert bundle.LOG_NAMES == REC_LOGS


def _rec_files(tmp_path, name, **line_change):
    d = tmp_path / name
    make_recording(d, name, "a" * 64, events=False)
    if line_change:
        line = json.loads((d / "manifest-line.json").read_text(encoding="ascii"))
        for k, v in line_change.items():
            if k == "path":
                line["recording"]["path"] = v
            else:
                line["source"][k] = v
        (d / "manifest-line.json").write_text(json.dumps(line), encoding="ascii")
    return {p.name: p.read_bytes() for p in d.iterdir()}


def test_a_recording_is_read_by_the_log_its_line_names(tmp_path):
    name = "20261019-carla-1"
    files = _rec_files(tmp_path, name)
    info, bad = bundle.recording_contents(name, files)
    assert bad == [] and (info["log"], info["log_sha256"], info["dbc_sha256"]) == ("carla.log", sha(files["carla.log"]), "a" * 64)
    assert bundle.recording_contents(name, dict(files, **{"sigsim.log": b"never read"}))[1] == []
    sig = _rec_files(tmp_path, "20260930-sigsim-1b")
    info, bad = bundle.recording_contents("20260930-sigsim-1b", sig)
    assert bad == [] and info["log"] == "sigsim.log"


def _line_sha(f):
    line = json.loads(f["manifest-line.json"])
    line["recording"]["sha256"] = "0" * 64
    f["manifest-line.json"] = json.dumps(line).encode()


@pytest.mark.parametrize("change, why", [
    (lambda f: f.update(**{"carla.log": b"(0.0) vcan0 1#00\n"}), "recording 20261019-carla-1: carla.log hashes to"),
    (_line_sha, "the manifest line's sha256 is " + "0" * 64),             # the log and its .sha256 agree, the line does not
    (lambda f: f.update(**{"carla.log.sha256": b"%s  sigsim.log\n" % sha(f["carla.log"]).encode()}),
     "carla.log.sha256 names ['sigsim.log'], not carla.log"),
    (lambda f: f.pop("carla.log"), "recording 20261019-carla-1: no carla.log"),
    (lambda f: f.pop("carla.log.sha256"), "recording 20261019-carla-1: no carla.log.sha256"),
    (lambda f: f.pop("summary.json"), "recording 20261019-carla-1: no summary.json"),
])
def test_a_carla_recording_whose_log_is_not_its_lines_is_refused(tmp_path, change, why):
    files = _rec_files(tmp_path, "20261019-carla-1")
    change(files)
    assert [p for p in bundle.recording_contents("20261019-carla-1", files)[1] if why in p]


@pytest.mark.parametrize("name, line_change, both", [
    ("20261019-carla-1", {"path": "~/sdv-recordings/20261019-carla-1/sigsim.log"}, ("'carla'", "'sigsim.log'")),
    ("20260930-sigsim-1b", {"path": "~/sdv-recordings/20260930-sigsim-1b/carla.log"}, ("'sigsim'", "'carla.log'")),
    ("20261019-carla-1", {"path": "~/sdv-recordings/20261019-carla-1/drive.log"}, ("'carla'", "'drive.log'")),
    ("20260930-sigsim-1b", {"generator": "vtd"}, ("'vtd'", "'sigsim.log'")),
    ("20261019-carla-1", {"generator": None}, ("None", "'carla.log'")),
    ("20261019-carla-1", {"path": None}, ("'carla'", "None")),
])
def test_a_mismatched_generator_and_log_is_refused_naming_both(tmp_path, name, line_change, both):
    problems = bundle.recording_contents(name, _rec_files(tmp_path, name, **line_change))[1]
    assert [p for p in problems if all(w in p for w in both)], problems


@POSIX
def test_build_refuses_without_the_carla_pair_and_verify_refuses_a_bundle_that_lacks_it(kit, capsys):
    shutil.rmtree(str(kit.recs / "20261019-carla-1-inj"))
    out = kit.root / "out"
    assert bundle.main(kit.build_args(out)) == 1 and "20261019-carla-1-inj" in capsys.readouterr().err
    assert not out.exists()
    make_recording(kit.recs / "20261019-carla-1-inj", "20261019-carla-1-inj", kit.dbc_sha, events=True)
    assert bundle.main(kit.build_args(out)) == 0
    capsys.readouterr()
    kit.out = out
    for name in ("rec-20261019-carla-1.tar", "rec-20261019-carla-1-inj.tar"):
        (out / name).unlink()
    kit.edit_json(out / "bundle.json", lambda d: d.update(members=[m for m in d["members"] if "carla" not in m["name"]]))
    rc, rec = verify(kit, capsys)
    assert rc == 1 and sorted(x for x in rec["problems"] if "not in bundle.json" in x) == [
        "rec-20261019-carla-1-inj.tar: not in bundle.json", "rec-20261019-carla-1.tar: not in bundle.json"], rec["problems"]


@POSIX
def test_verify_refuses_a_carla_recording_tar_whose_log_hash_is_wrong(built, capsys):
    name = "rec-20261019-carla-1.tar"
    rewrite_tar(built.out / name, lambda n, d: d + b"(9.000000) vcan0 100#00\n" if n.endswith("/carla.log") else d)
    rehash(built, name)
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("recording 20261019-carla-1: carla.log hashes to")], rec["problems"]
    assert verify(built, capsys)[1]["contents"]["rec-20261019-carla-1-inj.tar"]["log"] == "carla.log"


@POSIX
def test_build_refuses_its_out_and_commit_and_a_failed_save_removes_what_it_wrote(kit, capsys, monkeypatch):
    inside = REPO / "sdv-out" / "bundle-test-never-written"
    assert bundle.main(kit.build_args(inside)) == 1 and "inside the repo" in capsys.readouterr().err
    assert not inside.exists()
    full = kit.root / "full"
    full.mkdir()
    (full / "x").write_text("x", encoding="ascii")
    assert bundle.main(kit.build_args(full)) == 1 and "not an empty directory" in capsys.readouterr().err
    assert os.listdir(full) == ["x"]
    args = kit.build_args(kit.root / "out")
    args[args.index("--commit") + 1] = "HEAD"
    assert bundle.main(args) == 1 and "40 lowercase hex" in capsys.readouterr().err
    monkeypatch.setenv("FAKE_SAVE_FAIL", "1")
    empty = kit.root / "empty"
    empty.mkdir()
    for out in (kit.root / "out", empty):
        assert bundle.main(kit.build_args(out)) == 1 and "docker save" in capsys.readouterr().err
    assert not (kit.root / "out").exists() and os.listdir(empty) == []


# ============================================================ verify: the members

@POSIX
@pytest.mark.parametrize("member", MEMBERS)
def test_verify_refuses_each_member_whose_bytes_differ(built, capsys, member):
    name = member_name(built, member)
    p = built.out / name
    data = bytearray(p.read_bytes())
    data[-1] ^= 0x01                                    # the same size, one bit
    p.write_bytes(bytes(data))
    rc, rec = verify(built, capsys)
    assert rc == 1 and rec["ok"] is False
    assert [x for x in rec["problems"] if x.startswith("%s: sha256 %s, bundle.json says " % (name, sha(bytes(data))))], rec["problems"]
    assert {m["name"]: m.get("sha256_ok") for m in rec["members"]}[name] is False


@POSIX
def test_verify_refuses_a_size_a_missing_member_an_extra_file_and_a_name_given_twice(built, capsys):
    (built.out / built.dbc_name).write_bytes(DBC + b"x")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("%s: %d bytes, bundle.json says %d" % (built.dbc_name, len(DBC) + 1, len(DBC)))]
    (built.out / built.dbc_name).write_bytes(DBC)
    (built.out / "stray.txt").write_text("x", encoding="ascii")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if "stray.txt" in x and "not in bundle.json" in x], rec["problems"]
    (built.out / "stray.txt").unlink()
    (built.out / UPLOAD).unlink()
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("%s: missing" % UPLOAD)], rec["problems"]
    (built.src / ASSET).replace(built.out / UPLOAD)
    built.edit_json(built.out / "bundle.json", lambda d: d["members"].append(dict(d["members"][0])))
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if "listed twice" in x], rec["problems"]


@POSIX
def test_verify_refuses_a_name_the_upload_does_not_accept(built, capsys):
    bad = "cpython-3.12+x.tar.gz"
    (built.out / UPLOAD).replace(built.out / bad)

    def rename(doc):
        for m in doc["members"]:
            if m["name"] == UPLOAD:
                m["name"] = bad
    built.edit_json(built.out / "bundle.json", rename)
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if bad in x and "[A-Za-z0-9._-]" in x], rec["problems"]
    for weird in ("..", "."):
        built.edit_json(built.out / "bundle.json", lambda d, w=weird: d["members"].append({"name": w, "role": "dbc", "bytes": 0, "sha256": "0" * 64}))
        rc, rec = verify(built, capsys)
        assert rc == 1 and [x for x in rec["problems"] if repr(weird) in x and "[A-Za-z0-9._-]" in x], rec["problems"]


@POSIX
def test_verify_refuses_bundle_json_with_another_format_or_commit(built, capsys):
    built.edit_json(built.out / "bundle.json", lambda d: d.update(format=2, commit="HEAD"))
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if "format 2" in x] and [x for x in rec["problems"] if "'HEAD'" in x]
    (built.out / "bundle.json").unlink()
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if "bundle.json" in x], rec["problems"]


# ============================================================ verify: the contents against the pins

@POSIX
def test_verify_refuses_an_image_tar_whose_config_digest_is_not_the_pins(built, capsys):
    other = "sha256:" + "0" * 64
    built.edit_json(built.images_file, lambda i: i["local"]["hard-brake-hazard"]["arm64"].update(config_digest=other))
    rc, rec = verify(built, capsys)
    cd = built.pins["hard-brake-hazard"]["config_digest"]
    # the repo's images.json is not the one the bundle was built from, and the tar holds another config than its pin
    assert rc == 1 and rec["problems"] == [pin_file_problem(built, "sdv/stack/images.json"),
                                           "hard-brake-hazard: the manifest's config digest is %s, pinned %s" % (cd, other)]


@POSIX
def test_verify_refuses_a_pin_the_tar_does_not_hold_and_an_image_beyond_the_pins(built, capsys):
    other = "sha256:" + "1" * 64
    built.edit_json(built.images_file, lambda i: i["bridge"]["arm64"].update(id=other))
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("sdv-arm64-images.tar: index.json lists")]
    assert [x for x in rec["problems"] if x == "bridge: the tar has no manifest blob %s" % other], rec["problems"]
    built.edit_json(built.images_file, lambda i: i["bridge"]["arm64"].update(id=built.pins["bridge"]["id"]))
    # a tar saved with a fourth image: its index lists more than the pins
    s = built.get_state()
    extra = make_image(Path(os.environ["FAKE_DOCKER_BLOBS"]), [b"another layer"], {})
    s["images"][extra["id"]] = extra["info"]
    built.put_state(s)
    os.environ["FAKE_SAVE_EXTRA"] = json.dumps([extra["id"]])
    try:
        (built.out / "sdv-arm64-images.tar").unlink()
        ids = [built.pins[n]["id"] for n in sorted(built.pins)]
        subprocess.run(["docker", "save", "-o", str(built.out / "sdv-arm64-images.tar")] + ids, check=True)
    finally:
        del os.environ["FAKE_SAVE_EXTRA"]
    rehash(built, "sdv-arm64-images.tar")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("sdv-arm64-images.tar: index.json lists") and extra["id"] in x]


@POSIX
def test_verify_refuses_a_layer_or_a_manifest_that_does_not_hash_to_its_digest(built, capsys):
    tar = built.out / "sdv-arm64-images.tar"
    layer = built.bridge_layer
    rewrite_tar(tar, lambda n, d: b"tampered" if n == "blobs/sha256/" + layer[7:] else d)
    rehash(built, "sdv-arm64-images.tar")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("bridge: layer blob %s hashes to sha256:%s" % (layer, sha(b"tampered")))]
    mid = built.pins["hard-brake-hazard"]["id"]
    rewrite_tar(tar, lambda n, d: d + b" " if n == "blobs/sha256/" + mid[7:] else d)
    rehash(built, "sdv-arm64-images.tar")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("hard-brake-hazard: the manifest blob hashes to")], rec["problems"]
    rewrite_tar(tar, lambda n, d: None if n == "index.json" else d)
    rehash(built, "sdv-arm64-images.tar")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if "no index.json" in x], rec["problems"]


@POSIX
def test_verify_checks_the_generation_against_the_bridges_labels_and_the_tarball_against_its_pin(built, capsys):
    built.edit_json(built.images_file, lambda i: i["bridge"]["labels"].update({"sdv.kind4.contract_sha256": "f" * 64}))
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if "vss_contract.py hashes to %s, the bridge pin's label says %s" % (sha(CONTRACT), "f" * 64) in x]
    built.edit_json(built.images_file, lambda i: i["bridge"]["labels"].update({"sdv.kind4.contract_sha256": sha(CONTRACT)}))
    assert verify(built, capsys)[0] == 0
    built.edit_json(built.python_file, lambda p: p.update(sha256="a" * 64))
    rc, rec = verify(built, capsys)
    assert rc == 1 and rec["problems"] == [pin_file_problem(built, "sdv/sim/python-aarch64.json"),
                                           "%s: sha256 %s, %d bytes is not the pinned %s, %d bytes" % (
        UPLOAD, sha_file(built.out / UPLOAD), (built.out / UPLOAD).stat().st_size, "a" * 64, (built.out / UPLOAD).stat().st_size)]


@POSIX
def test_verify_refuses_a_gen_or_recording_tar_with_a_member_outside_its_directory(built, capsys):
    with tarfile.open(str(built.out / "sdv-gen.tar"), "a") as tf:
        ti = tarfile.TarInfo("../escape.txt")
        ti.size = 1
        tf.addfile(ti, io.BytesIO(b"x"))
    rehash(built, "sdv-gen.tar")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if "'../escape.txt'" in x], rec["problems"]


# ============================================================ verify: the image tar is exactly what docker save wrote

@POSIX
def test_verify_refuses_a_name_the_image_tar_holds_twice_even_when_its_last_copy_is_the_good_one(built, capsys):
    """A tampered copy of the bridge's layer blob first, the good one last: a reader that takes the last entry would pass
    it, and a loader that takes the first would not. The tar holds each name once."""
    tar = built.out / "sdv-arm64-images.tar"
    blob = "blobs/sha256/" + built.bridge_layer[7:]
    write_items(tar, [(blob, b"tampered")] + tar_items(tar))
    rehash(built, "sdv-arm64-images.tar")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x == "sdv-arm64-images.tar: %s is in it twice" % blob], rec["problems"]


def dir_entry(name: str) -> tarfile.TarInfo:
    """A directory entry with no data, for write_items."""
    ti = tarfile.TarInfo(name)
    ti.type = tarfile.DIRTYPE
    return ti


@POSIX
@pytest.mark.parametrize("extra, why", [
    (("blobs/sha256/" + sha(b"an unreferenced blob"), b"an unreferenced blob"), "is not a blob any pinned image references"),
    (("stray.txt", b"x"), "is not a blob any pinned image references"),
    (("repositories", b'{"registry.invalid/evil": {"latest": "x"}}'), "repositories names"),
    # only blobs/ and blobs/sha256/ are directories a save by ID writes
    ((dir_entry("blobs/other"), None), "blobs/other is a directory, not a regular file"),
])
def test_verify_refuses_an_image_tar_entry_docker_save_by_id_does_not_write(built, capsys, extra, why):
    tar = built.out / "sdv-arm64-images.tar"
    write_items(tar, tar_items(tar) + [extra])
    rehash(built, "sdv-arm64-images.tar")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("sdv-arm64-images.tar: ") and why in x], rec["problems"]


@POSIX
def test_verify_refuses_a_legacy_manifest_json_that_is_not_the_saved_pins(built, capsys):
    """docker save writes a legacy manifest.json beside index.json; a graph-driver store loads from it. Naming another
    config, other layers or a tag, it is not what a save by ID wrote."""
    tar = built.out / "sdv-arm64-images.tar"
    good = tar_items(tar)
    other_cfg = "blobs/sha256/" + built.pins["hard-brake-hazard"]["config_digest"][7:]
    for change, why in ((lambda e: e.update(Config=other_cfg), "manifest.json"),
                        (lambda e: e.update(RepoTags=["registry.invalid/evil:latest"]), "manifest.json names a tag"),
                        (lambda e: e["Layers"].pop(), "manifest.json")):
        def edit(name, data, change=change):
            if name != "manifest.json":
                return data
            doc = json.loads(data)
            bridge = [e for e in doc if e["Config"].endswith(built.pins["bridge"]["config_digest"][7:])]
            change(bridge[0])
            return json.dumps(doc).encode()
        write_items(tar, [(n, edit(n, d)) for n, d in good])
        rehash(built, "sdv-arm64-images.tar")
        rc, rec = verify(built, capsys)
        assert rc == 1 and [x for x in rec["problems"] if x.startswith("sdv-arm64-images.tar: ") and why in x], (why, rec["problems"])


@POSIX
def test_verify_refuses_a_link_in_the_image_tar(built, capsys):
    tar = built.out / "sdv-arm64-images.tar"
    path = "blobs/sha256/" + built.pins["bridge"]["id"][7:]
    link = tarfile.TarInfo(path)
    link.type, link.linkname = tarfile.SYMTYPE, "blobs/sha256/" + built.pins["hard-brake-hazard"]["id"][7:]
    write_items(tar, [(n, d) for n, d in tar_items(tar) if n != path] + [(link, None)])
    rehash(built, "sdv-arm64-images.tar")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if path in x], rec["problems"]


# ============================================================ verify: the pins it was built from, one read per member

@POSIX
def test_verify_refuses_a_bundle_built_against_other_pin_files(built, capsys):
    """bundle.json records the sha256 of the images.json and python-aarch64.json it was built from; verify checks the
    content against the repo's own, so a bundle from another pin set is named as such."""
    built.edit_json(built.out / "bundle.json", lambda d: d.update(pins={k: "0" * 64 for k in d["pins"]}))
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("bundle.json: built against ")] == [
        "bundle.json: built against sdv/stack/images.json %s; this repo's hashes to %s" % ("0" * 64, sha_file(built.images_file)),
        "bundle.json: built against sdv/sim/python-aarch64.json %s; this repo's hashes to %s" % ("0" * 64, sha_file(built.python_file))]
    built.edit_json(built.out / "bundle.json", lambda d: d.pop("pins"))
    rc, rec = verify(built, capsys)
    assert rc == 1 and len([x for x in rec["problems"] if x.startswith("bundle.json: built against ")]) == 2, rec["problems"]


@POSIX
def test_verify_reads_each_member_through_the_handle_it_hashed_and_refuses_one_swapped_during_the_check(built, capsys, monkeypatch):
    """Another recording tar, internally consistent, renamed over a member after its hash was taken and before its
    content is read: the content checked is still the hashed bytes, and the swap is refused by name."""
    name = "rec-20260930-sigsim-1b.tar"
    first = verify(built, capsys)[1]["contents"][name]["log_sha256"]
    other = other_recording_tar(built, "20260930-sigsim-1b")
    real = bundle.read_tar
    swapped: List[str] = []

    def swap_then_read(path, *a, **kw):
        if Path(path).name == name and not swapped:
            os.replace(str(other), str(built.out / name))
            swapped.append(name)
        return real(path, *a, **kw)
    monkeypatch.setattr(bundle, "read_tar", swap_then_read)
    rc, rec = verify(built, capsys)
    assert swapped == [name]
    assert rc == 1 and [x for x in rec["problems"] if x.startswith(name + ": changed while it was verified")], rec["problems"]
    assert rec["contents"][name]["log_sha256"] == first, "the bytes checked are the ones bundle.json names"


# ============================================================ the generation as a whole: the bridge image bakes its manifest in

def _regenerated(kit, files: Dict[str, bytes]) -> Dict[str, bytes]:
    """The same generation with vss-databroker.json replaced and its manifest's outputs entry rewritten to match: the
    contract, the DBC and the catalog digest (the bridge pin's three labels) unchanged."""
    new = b'{"Vehicle": {"Speed": {"type": "sensor"}}}\n'
    man = json.loads(files["manifest.json"])
    man["outputs"]["vss-databroker.json"] = {"sha256": sha(new), "bytes": len(new)}
    return dict(files, **{"vss-databroker.json": new, "manifest.json": json.dumps(man).encode()})


@POSIX
def test_verify_refuses_a_generation_whose_manifest_is_not_the_one_the_bridge_image_bakes_in(built, capsys):
    tar = built.out / "sdv-gen.tar"
    files = bundle.read_tar(tar, "gen")
    regen = _regenerated(built, files)
    write_items(tar, [("gen/" + n, regen[n]) for n in sorted(regen)])
    rehash(built, "sdv-gen.tar")
    rc, rec = verify(built, capsys)
    assert rc == 1 and [x for x in rec["problems"] if "the bridge image bakes in" in x], rec["problems"]
    assert not [x for x in rec["problems"] if "the bridge pin's label" in x], "the three labels still agree"


@POSIX
def test_build_refuses_a_generation_whose_manifest_is_not_the_one_the_bridge_image_bakes_in(kit, capsys):
    files = {n: (kit.gen / n).read_bytes() for n in ("manifest.json", "vss-databroker.json", "vss_contract.py")}
    for n, data in _regenerated(kit, files).items():
        (kit.gen / n).write_bytes(data)
    out = kit.root / "out"
    assert bundle.main(kit.build_args(out)) == 1
    err = capsys.readouterr().err
    assert "the bridge image bakes in" in err, err
    assert not out.exists(), "a refusal after the save removes what the build wrote"


# ============================================================ verify --loaded

@POSIX
def test_verify_loaded_finds_each_pin_in_the_daemon_after_a_load(built, capsys):
    built.remove_images()
    rc, rec = verify(built, capsys, "--loaded")
    assert rc == 1 and len([x for x in rec["problems"] if "is not in the image store" in x]) == 3
    assert sorted(built.load(built.out / "sdv-arm64-images.tar")) == sorted(p["id"] for p in built.pins.values())
    rc, rec = verify(built, capsys, "--loaded")
    assert rc == 0 and rec["ok"] is True and rec["loaded"] is True, rec["problems"]
    assert rec["docker"] == {"server": "29.6.2", "driver_type": "io.containerd.snapshotter.v1"}
    assert {k: v["id"] for k, v in rec["loaded_images"].items()} == {k: v["id"] for k, v in built.pins.items()}
    assert all(v["platform"] == "linux/arm64" for v in rec["loaded_images"].values())
    assert not [c for c in built.calls() if c[:1] in (["pull"], ["load"], ["build"])]


@POSIX
@pytest.mark.parametrize("change, why", [
    ("missing", "is not in the image store"),
    ("id", "image ID sha256:%s, pinned" % ("2" * 64)),
    ("arch", "linux/amd64, not linux/arm64"),
    ("label", "labels differ from the pin's"),
])
def test_verify_loaded_refuses_each_check(built, capsys, change, why):
    s = built.get_state()
    iid = built.pins["bridge"]["id"]
    if change == "missing":
        del s["images"][iid]
    elif change == "id":
        s["images"][iid]["Id"] = "sha256:" + "2" * 64
    elif change == "arch":
        s["images"][iid]["Architecture"] = "amd64"
    else:
        s["images"][iid]["Config"]["Labels"]["sdv.kind4.contract_sha256"] = "3" * 64
    built.put_state(s)
    assert verify(built, capsys)[0] == 0                       # the files are the same; only the daemon differs
    rc, rec = verify(built, capsys, "--loaded")
    assert rc == 1 and [x for x in rec["problems"] if x.startswith("bridge: ") and why in x], rec["problems"]


# ============================================================ verify-upstream

@POSIX
def test_verify_upstream_takes_the_pinned_set_and_pulls_nothing(kit, capsys):
    assert bundle.main(["verify-upstream"]) == 0
    rec = one_record(capsys)
    assert rec["ok"] is True and sorted(rec["images"]) == sorted(UPSTREAM)
    for name, u in kit.upstream.items():
        r = rec["images"][name]
        assert r["id"] == u["index_digest"] and r["revision"] == u["revision"] and r["platform"] == "linux/arm64" and r["in_repo_digests"]
    assert [c[:2] for c in kit.calls()] == [["image", "inspect"]] * 4


@POSIX
@pytest.mark.parametrize("change, why", [
    ("missing", "is not in the image store"),
    ("id", "image ID sha256:%s, not the pinned index digest" % ("4" * 64)),
    ("revision", "revision label '%s', pinned" % ("5" * 40)),
    ("repo_digests", "is not among the image's repo digests"),
    ("arch", "linux/amd64, not linux/arm64"),
])
def test_verify_upstream_refuses_each_of_its_checks_on_its_own(kit, capsys, change, why):
    s = kit.get_state()
    u = kit.upstream["kuksa-can-provider"]
    info = s["images"][u["index_digest"]]
    if change == "missing":
        del s["images"][u["index_digest"]]
    elif change == "id":
        info["Id"] = "sha256:" + "4" * 64
    elif change == "revision":
        info["Config"]["Labels"][REV] = "5" * 40
    elif change == "repo_digests":
        info["RepoDigests"] = ["%s@sha256:%s" % (u["repo"], "6" * 64)]
    else:
        info["Architecture"] = "amd64"
    kit.put_state(s)
    assert bundle.main(["verify-upstream"]) == 1
    rec = one_record(capsys)
    assert rec["ok"] is False and len(rec["problems"]) == 1 and rec["problems"][0].startswith("kuksa-can-provider: ") and why in rec["problems"][0]
    assert not [c for c in kit.calls() if c[:1] == ["pull"]]


# ============================================================ --docker, the record

@POSIX
def test_the_docker_prefix_reaches_every_docker_argv(kit, capsys):
    pre = ["--docker", "sudo -n docker"]
    kit.out = kit.root / "out"
    assert bundle.main(kit.build_args(kit.out) + pre) == 0
    kit.remove_images()
    kit.load(kit.out / "sdv-arm64-images.tar")
    assert bundle.main(["verify", "--in", str(kit.out), "--loaded"] + pre) == 0
    assert bundle.main(["verify-upstream"] + pre) == 0
    capsys.readouterr()
    entries = kit.entries()
    dockers = [e for e in entries if "argv" in e]
    sudos = [e["sudo"] for e in entries if "sudo" in e]
    assert dockers and all(e["via_sudo"] for e in dockers), [e["argv"] for e in dockers if not e["via_sudo"]]
    assert len(sudos) == len(dockers) and all(s[:2] == ["-n", "docker"] and s[2:] == e["argv"] for s, e in zip(sudos, dockers))
    kinds = {tuple(e["argv"][:2]) if e["argv"][0] == "image" else (e["argv"][0],) for e in dockers}
    assert kinds == {("image", "inspect"), ("save",), ("version",), ("info",)}
    # without --docker: plain docker, never sudo
    n = len(entries)
    assert bundle.main(["verify", "--in", str(kit.out), "--loaded"]) == 0 and bundle.main(["verify-upstream"]) == 0
    capsys.readouterr()
    later = kit.entries()[n:]
    assert later and all("argv" in e and not e["via_sudo"] for e in later)


def test_an_empty_docker_prefix_is_refused(capsys):
    assert bundle.main(["verify-upstream", "--docker", " "]) == 1
    rec = one_record(capsys)
    assert rec["ok"] is False and [x for x in rec["problems"] if "--docker" in x]


@POSIX
def test_each_command_prints_one_json_line_of_selected_fields(built, capsys):
    built.remove_images()
    built.load(built.out / "sdv-arm64-images.tar")
    for argv in (["verify", "--in", str(built.out), "--loaded"], ["verify-upstream"]):
        assert bundle.main(argv) == 0
        rec = one_record(capsys)                       # one line; no raw inspect field
        assert set(rec) <= {"tool", "ok", "problems", "loaded", "commit", "members", "images", "loaded_images", "docker", "contents"}
        text = json.dumps(rec)
        for raw in ("RepoTags", "GraphDriver", "Config", "RootFS", "DriverStatus"):
            assert raw not in text


# ============================================================ the real pins

def test_the_python_pin_names_a_release_asset_its_urls_and_the_upload_name():
    py = json.loads(PYTHON_JSON.read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{8}", py["release"])
    m = re.fullmatch(r"cpython-(3\.12\.\d+)\+(\d{8})-aarch64-unknown-linux-gnu-install_only\.tar\.gz", py["asset"])
    assert m and m.group(1) == py["python_version"] and m.group(2) == py["release"]
    assert (py["target"], py["flavor"]) == ("aarch64-unknown-linux-gnu", "install_only")
    base = "https://github.com/astral-sh/python-build-standalone/releases/download/%s/" % py["release"]
    assert py["url"] == base + py["asset"].replace("+", "%2B") and py["sums_url"] == base + "SHA256SUMS"
    assert HEX64.fullmatch(py["sha256"]) and HEX64.fullmatch(py["sums_sha256"])
    assert isinstance(py["bytes"], int) and not isinstance(py["bytes"], bool) and py["bytes"] > 0
    assert py["upload_name"] == UPLOAD and NAME.fullmatch(py["upload_name"]) and "+" in py["asset"]
    assert bundle.python_pin(py) == py


SRC = Path(os.environ.get("SDV_BUNDLE_SRC", "~/sdv-bundle-src")).expanduser()


@pytest.mark.skipif(not (SRC / "SHA256SUMS").is_file(), reason="needs the release's downloaded SHA256SUMS in %s" % SRC)
def test_the_python_pin_is_the_published_sums_line_for_its_asset():
    py = json.loads(PYTHON_JSON.read_text(encoding="utf-8"))
    sums = (SRC / "SHA256SUMS").read_bytes()
    assert sha(sums) == py["sums_sha256"]
    lines = [ln.split() for ln in sums.decode("ascii").splitlines() if ln.strip()]
    assert [h for h, n in lines if n == py["asset"]] == [py["sha256"]]
    tarball = SRC / py["asset"]
    if tarball.is_file():
        assert tarball.stat().st_size == py["bytes"] and sha_file(tarball) == py["sha256"]


def test_the_real_images_json_gives_the_three_arm64_pins_and_the_bridges_labels():
    images = json.loads((STACK_DIR / "images.json").read_text(encoding="utf-8"))
    pins = bundle.arm64_pins(images)
    assert sorted(pins) == ["bridge", "hard-brake-hazard", "kuksa-csv-provider-recorder"]
    assert all(p["tag"].endswith("-arm64") for p in pins.values())
    assert sorted(bundle.bridge_labels(images)) == sorted(LABEL_KEYS)
    assert sorted(images["upstream"]) == sorted(UPSTREAM)
    for u in images["upstream"].values():
        assert bundle.upstream_ref(u) == "%s@%s" % (u["repo"], u["index_digest"])


def test_the_shared_checks_name_what_they_refuse():
    u = {"repo": "registry.invalid/x", "index_digest": "sha256:" + "7" * 64, "revision": "8" * 40}
    ref = bundle.upstream_ref(u)
    good = {"Id": u["index_digest"], "Architecture": "arm64", "Os": "linux", "Config": {"Labels": {REV: u["revision"]}}, "RepoDigests": [ref]}
    assert bundle.upstream_problems("x", u, good) == []
    assert bundle.upstream_problems("x", u, None, "no such image")[0].startswith("x: %s is not in the image store (no such image)" % ref)
    pin = {"id": "sha256:" + "9" * 64, "config_digest": "sha256:" + "a" * 64, "tag": "t-arm64"}
    info = {"Id": pin["id"], "Architecture": "arm64", "Os": "linux", "Config": {"Labels": {"k": "v"}}}
    assert bundle.loaded_problems("y", pin, info) == [] and bundle.loaded_problems("y", pin, info, labels={"k": "v"}) == []
    assert bundle.loaded_problems("y", pin, dict(info, Os="windows"))[0] == "y: windows/arm64, not linux/arm64"


# ============================================================ opt-in: the real carry on this PC

def _docker_lines(*args: str) -> List[str]:
    p = subprocess.run(["docker"] + list(args), capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stderr
    return p.stdout.splitlines()


@pytest.mark.skipif(os.environ.get("SDV_BUNDLE") != "1",
                    reason="opt-in (SDV_BUNDLE=1, SDV_BUNDLE_COMMIT): the real build, save, rm, load and verify on this PC's Docker")
def test_the_bundle_carries_the_arm64_images_through_save_rm_and_load(capsys):
    commit = os.environ.get("SDV_BUNDLE_COMMIT", "")
    assert re.fullmatch(r"[0-9a-f]{40}", commit), "SDV_BUNDLE_COMMIT: the source commit, read in Git Bash"
    out = Path(os.environ.get("SDV_BUNDLE_OUT", "~/sdv-bundle/wp1-%s" % commit[:12])).expanduser()
    images = json.loads((STACK_DIR / "images.json").read_text(encoding="utf-8"))
    pins = bundle.arm64_pins(images)
    tags, ids = {p["tag"] for p in pins.values()}, {p["id"] for p in pins.values()}

    def others() -> List[str]:
        return sorted(ln for ln in _docker_lines("images", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}")
                      if ln.split()[0] not in tags and ln.split()[-1] not in ids)
    before = others()
    for p in pins.values():
        assert _docker_lines("image", "inspect", "-f", "{{.Id}}", p["tag"]) == [p["id"]]
    assert bundle.main(["build", "--out", str(out), "--commit", commit]) == 0
    built_rec = one_record(capsys)
    assert bundle.main(["verify", "--in", str(out)]) == 0
    verify_rec = one_record(capsys)
    tar = out / "sdv-arm64-images.tar"
    loaded = False
    try:
        for p in pins.values():
            _docker_lines("image", "rm", p["tag"])
        for p in pins.values():
            r = subprocess.run(["docker", "image", "inspect", p["id"]], capture_output=True, text=True, timeout=120)
            assert r.returncode != 0, "%s is still in the store after its tag was removed" % p["id"]
        _docker_lines("load", "-i", str(tar))
        loaded = True
        assert bundle.main(["verify", "--in", str(out), "--loaded"]) == 0
        loaded_rec = one_record(capsys)
    finally:
        if not loaded:
            subprocess.run(["docker", "load", "-i", str(tar)], capture_output=True, text=True, timeout=1800)
        for p in pins.values():                     # the PC's tags back, as before the carry
            subprocess.run(["docker", "tag", p["id"], p["tag"]], capture_output=True, text=True, timeout=120)
    for p in pins.values():
        assert _docker_lines("image", "inspect", "-f", "{{.Id}}", p["tag"]) == [p["id"]]
    assert others() == before
    assert loaded_rec["docker"]["driver_type"] == "io.containerd.snapshotter.v1"
    record = os.environ.get("SDV_BUNDLE_RECORD")
    if record:
        Path(record).expanduser().write_text(json.dumps({"build": built_rec, "verify": verify_rec, "verify_loaded": loaded_rec},
                                                        indent=1, sort_keys=True) + "\n", encoding="utf-8")
