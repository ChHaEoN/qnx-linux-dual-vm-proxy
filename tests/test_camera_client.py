"""camera_client.py's file source (SDV plan Phase 7, WP9; phase7 spec section 8): --frames DIR reads a labelled
simulated frame set (spec 2.4) in place of a camera, --dry logs each frame and asks nothing, and the camera path stays
what it was.

Every test runs on a fake cv2 (CI has no OpenCV), a fake clock and, for the camera path, a fake /dev/video*: nothing
here opens a camera, a socket to a model or a monitor, or reads a photograph. THE CAMERA RULE: every frame below is a
generated pattern, 64x64 grey, written into pytest's tmp_path and nowhere else; the camera path's frames are
placeholders with a shape and no pixels.

The camera path's records are pinned against the reference version of camera_client.py: the expected lists below are what
that file wrote on the same fake world, times excepted, and the test passes on it unchanged.
"""
import hashlib
import importlib.util
import itertools
import json
import os
import re
import socket
import struct
import sys
import urllib.request
import zlib

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
EL = os.path.join(HERE, "..", "orin-native", "edge-llm")
LOCK = os.path.join(EL, "requirements-dry.lock")
TIMES = ("t", "t_send", "t_reply")
WHY = "reply '" + "x" * 130 + "' is not a space and one digit"
DROP = object()


@pytest.fixture
def cc(monkeypatch):
    """A fresh camera_client module per test, so that a patched global never outlives its test; the module puts its own
    directory on sys.path when it loads, and the session's sys.path is given back after the test."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("camera_client_under_test", os.path.join(EL, "camera_client.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ------------------------------------------------------------------ the fakes

class Clock:
    """time as camera_client sees it: monotonic() reads it, sleep() advances it, and only the fakes move it."""

    def __init__(self, now=100.0):
        self.now = now
        self.sleeps = []
        self.on_sleep = None

    def monotonic(self):
        return self.now

    def sleep(self, s):
        assert s >= 0, s
        self.sleeps.append(s)
        self.now += s
        if self.on_sleep:
            self.on_sleep(len(self.sleeps))


class Img:
    """An image with a shape and, in place of pixels, how it was made: enough to see each line of the reduction."""

    def __init__(self, shape, how):
        self.shape = shape
        self.how = how

    def __getitem__(self, key):
        rows, cols = key
        h = len(range(*rows.indices(self.shape[0])))
        w = len(range(*cols.indices(self.shape[1])))
        return Img((h, w) + self.shape[2:], ("crop", rows.start, rows.stop, cols.start, cols.stop, self.how))


class FakeCv2:
    """The cv2 calls camera_client makes. imwrite writes the image's history to the path, so the scratch exists while
    a run holds it; imread records the file and the clock's time and returns a colour image of the frame's size."""
    COLOR_BGR2GRAY = 6
    INTER_AREA = 3
    IMREAD_COLOR = 1
    CAP_V4L2 = 200
    CAP_PROP_BUFFERSIZE = 38

    def __init__(self, clock, world=None, imread_none=False):
        self.clock, self.world, self.imread_none = clock, world, imread_none
        self.reads, self.writes = [], []

    def imread(self, path, flag):
        self.reads.append((os.path.basename(path), flag, self.clock.now))
        if self.imread_none or not os.path.isfile(path):
            return None                               # as OpenCV's imread does for a path it cannot read
        return Img((64, 64, 3), ("imread", os.path.basename(path), flag))

    def cvtColor(self, img, code):
        return Img(img.shape[:2], ("cvtColor", code, img.how))

    def resize(self, img, dsize, interpolation=None):
        return Img((dsize[1], dsize[0]), ("resize", tuple(dsize), interpolation, img.how))

    def imwrite(self, path, img):
        with open(path, "w") as f:
            f.write(json.dumps(img.how))
        self.writes.append((path, img.how))
        return True

    def VideoCapture(self, dev, api):
        if self.world is None:
            raise AssertionError("a camera was opened: VideoCapture(%r)" % dev)
        return Cap(self.world, dev, api)


class CameraWorld:
    """/dev/video* as the camera path sees it: /dev/video0 a UVC metadata node (opens, never yields a frame),
    /dev/video1 the camera, which yields while it is plugged in (the `present` intervals of the fake clock)."""

    def __init__(self, clock, present):
        self.clock, self.present = clock, present
        self.trace = []
        self.n = 0

    def plugged(self):
        return any(a <= self.clock.now < b for a, b in self.present)

    def glob(self, pattern):
        assert pattern == "/dev/video*", pattern
        return ["/dev/video1", "/dev/video0"] if self.plugged() else []      # unsorted: the client sorts


class Cap:
    def __init__(self, world, dev, api):
        self.world, self.dev = world, dev
        world.trace.append(("open", dev, api))

    def isOpened(self):
        return self.world.plugged()

    def set(self, prop, value):
        self.world.trace.append(("set", self.dev, prop, value))
        return True

    def read(self):
        ok = self.dev == "/dev/video1" and self.world.plugged()
        self.world.trace.append(("read", self.dev, ok))
        if not ok:
            return False, None
        self.world.n += 1
        return True, Img((480, 640, 3), ("camera", self.dev, self.world.n))

    def release(self):
        self.world.trace.append(("release", self.dev))


class Model:
    """vlm_request.ask and vlm_client.exchange. The answers cycle: digit 7 at 0.93, an unclassifiable reply, digit 3
    at 0.41. An ask takes ASK_S of the fake clock (or the next of `ask_s`), an exchange EXCHANGE_S; the monitor
    accepts a confidence of 60 or more and rejects the rest as confidence-below-threshold (reason 3)."""
    ASK_S = 0.25
    EXCHANGE_S = 0.0625
    ANSWERS = ((7, 0.93), None, (3, 0.41))

    def __init__(self, cc, clock, ask_s=()):
        self.cc, self.clock, self.ask_s = cc, clock, list(ask_s)
        self.asked, self.sent = [], []

    def ask(self, server, path, timeout_s=60.0):
        with open(path) as f:
            self.asked.append((server, path, f.read()))
        self.clock.now += self.ask_s.pop(0) if self.ask_s else self.ASK_S
        ans = self.ANSWERS[(len(self.asked) - 1) % len(self.ANSWERS)]
        if ans is None:
            raise self.cc.vlm_request.Unclassifiable(WHY)
        return {"answer": str(ans[0]), "p_answer": ans[1], "prompt_ms": 200.0, "predicted_ms": 50.0,
                "prompt_n": 90, "predicted_n": 2, "wall_ms": 260.0, "digit_mass": 0.98}

    def exchange(self, host, port, frame):
        self.clock.now += self.EXCHANGE_S
        seq = struct.unpack_from("<Q", frame, 0)[0]
        self.sent.append((host, port, seq, frame[16], frame[17], frame[16 + 24]))
        got = bytearray(64)
        got[16 + 6], got[16 + 7] = (0, 0) if frame[17] >= 60 else (1, 3)
        return bytes(got)


class NoCamera:
    """glob as the file source must never use it: any call fails the test."""

    def __init__(self, touched):
        self.touched = touched

    def glob(self, pattern):
        self.touched.append("glob " + pattern)
        raise AssertionError("glob(%r) in a frames run" % pattern)


def _refuse(touched, name):
    def f(*_a, **_k):
        touched.append(name)
        raise AssertionError("touched " + name)
    return f


# ------------------------------------------------------------------ synthetic frame sets (generated patterns only)

def _chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def _png(seed, w=64, h=64, depth=8, colour=0, interlace=0, rows=None, extra=(), idat=None, filt=0):
    """A PNG of a generated gradient (never a photograph): 8-bit grey 64x64 unless told otherwise."""
    px = {0: 1, 2: 3}[colour] * (depth // 8)
    raw = b"".join(bytes([filt]) + bytes((x * 4 + y * 3 + seed * 17) % 256 for x in range(w * px))
                   for y in range(h if rows is None else rows))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, colour, 0, 0, interlace))
            + b"".join(_chunk(k, b) for k, b in extra) + _chunk(b"IDAT", zlib.compress(raw) if idat is None else idat(raw))
            + _chunk(b"IEND", b""))


def _ihdr(data, **fields):
    """data with IHDR's named fields replaced and its CRC made right again: only the field can be wrong."""
    v = dict(zip(("width", "height", "depth", "colour", "compression", "filter", "interlace"),
                 struct.unpack(">IIBBBBB", data[16:29])))
    v.update(fields)
    body = struct.pack(">IIBBBBB", v["width"], v["height"], v["depth"], v["colour"], v["compression"], v["filter"],
                       v["interlace"])
    crc = struct.pack(">I", zlib.crc32(b"IHDR" + body) & 0xFFFFFFFF)
    return data[:16] + body + crc + data[33:]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def make_set(root, order=(20, 40, 60), name="20261020-carla-7", **label):
    """A frame set of spec 2.4's form under root/name; a label key given DROP is left out."""
    d = root / name
    d.mkdir(parents=True)
    frames = []
    for i in order:
        data = _png(i)
        (d / ("frame-%06d.png" % i)).write_bytes(data)
        frames.append({"file": "frame-%06d.png" % i, "i": i, "frame": 5000 + i, "sha256": _sha(data)})
    doc = {"format": 1, "simulated": True, "generator": "carla", "name": name, "carla_version": "0.9.16",
           "town": "Town01", "seed": 7, "blueprint": "vehicle.toyota.prius",
           "camera": {"type": "sensor.camera.rgb", "width": 320, "height": 256, "mount": {"x": 1.5, "y": 0.0, "z": 1.6}},
           "reduction": {"grey": "BT.601", "crop": "centre-square", "size": 64, "resample": "4x4-block-mean"},
           "stride_steps": 20, "licence": "CARLA assets: CC-BY (CARLA's README). Simulated frames; never published.",
           "take_sha256": "0" * 64, "frames": frames}
    for k, v in label.items():
        if v is DROP:
            doc.pop(k)
        else:
            doc[k] = v
    (d / "frames.json").write_text(json.dumps(doc))
    return d


def _relist(d, edit):
    doc = json.loads((d / "frames.json").read_text())
    edit(doc)
    (d / "frames.json").write_text(json.dumps(doc))


def _replace_png(d, i, data):
    """frame i's bytes replaced, and listed with their own sha256: only the PNG's form can be wrong."""
    (d / ("frame-%06d.png" % i)).write_bytes(data)
    _relist(d, lambda doc: [f.update(sha256=_sha(data)) for f in doc["frames"] if f["i"] == i])


def _entry(at, **kv):
    """frames.json's entry for step `at` given these keys."""
    def edit(doc):
        for f in doc["frames"]:
            if f["i"] == at:
                f.update(kv)
    return edit


# ------------------------------------------------------------------ the reader (spec 2.4's refusals)

def test_the_reader_takes_a_labelled_set_in_its_listed_order(cc, tmp_path):
    d = make_set(tmp_path, order=(40, 20, 60))
    frames = cc.read_frames(str(d))
    assert [(f.i, f.file) for f in frames] == [(40, "frame-000040.png"), (20, "frame-000020.png"), (60, "frame-000060.png")]
    assert [f.path for f in frames] == [os.path.join(str(d), f.file) for f in frames]
    assert [f.sha256 for f in frames] == [_sha((d / f.file).read_bytes()) for f in frames]


REFUSALS = [
    ("no-frames-json", lambda d: (d / "frames.json").unlink(), "no frames.json"),
    ("frames-json-a-directory", lambda d: ((d / "frames.json").unlink(), (d / "frames.json").mkdir()), "no frames.json"),
    ("not-json", lambda d: (d / "frames.json").write_text("{"), "frames.json is not a JSON object"),
    ("json-list", lambda d: (d / "frames.json").write_text("[]"), "frames.json is not a JSON object"),
    ("format-2", lambda d: _relist(d, lambda doc: doc.update(format=2)), "format is not 1"),
    ("format-true", lambda d: _relist(d, lambda doc: doc.update(format=True)), "format is not 1"),
    ("format-missing", lambda d: _relist(d, lambda doc: doc.pop("format")), "format is not 1"),
    ("unlabelled", lambda d: _relist(d, lambda doc: doc.pop("simulated")), "simulated is not true"),
    ("simulated-false", lambda d: _relist(d, lambda doc: doc.update(simulated=False)), "simulated is not true"),
    ("simulated-1", lambda d: _relist(d, lambda doc: doc.update(simulated=1)), "simulated is not true"),
    ("simulated-text", lambda d: _relist(d, lambda doc: doc.update(simulated="true")), "simulated is not true"),
    ("generator-sigsim", lambda d: _relist(d, lambda doc: doc.update(generator="sigsim")), "generator is not carla"),
    ("generator-missing", lambda d: _relist(d, lambda doc: doc.pop("generator")), "generator is not carla"),
    ("format-float", lambda d: _relist(d, lambda doc: doc.update(format=1.0)), "format is not 1"),
    ("simulated-null", lambda d: _relist(d, lambda doc: doc.update(simulated=None)), "simulated is not true"),
    ("generator-upper-case", lambda d: _relist(d, lambda doc: doc.update(generator="CARLA")), "generator is not carla"),
    ("licence-not-text", lambda d: _relist(d, lambda doc: doc.update(licence=["CC-BY"])), "no licence"),
    ("frames-empty-no-files", lambda d: (_relist(d, lambda doc: doc.update(frames=[])), [p.unlink() for p in d.glob("frame-*.png")]),
     "no frames listed"),
    ("licence-missing", lambda d: _relist(d, lambda doc: doc.pop("licence")), "no licence"),
    ("licence-empty", lambda d: _relist(d, lambda doc: doc.update(licence="")), "no licence"),
    ("licence-blank", lambda d: _relist(d, lambda doc: doc.update(licence="   ")), "no licence"),
    ("frames-empty", lambda d: _relist(d, lambda doc: doc.update(frames=[])), "no frames listed"),
    ("frames-not-a-list", lambda d: _relist(d, lambda doc: doc.update(frames={})), "no frames listed"),
    ("entry-not-an-object", lambda d: _relist(d, lambda doc: doc["frames"].append("frame-000080.png")),
     "frames.json's entry 3 is not"),
    ("i-not-an-integer", lambda d: _relist(d, _entry(40, i="40")), "frames.json's entry 1 is not"),
    ("i-a-boolean", lambda d: _relist(d, _entry(20, i=True)), "frames.json's entry 0 is not"),
    ("i-a-boolean-named-1", lambda d: ((d / "frame-000020.png").rename(d / "frame-000001.png"),
                                       _relist(d, _entry(20, i=True, file="frame-000001.png"))), "frames.json's entry 0 is not"),
    ("sha256-not-hex", lambda d: _relist(d, _entry(40, sha256="Z" * 64)), "frames.json's entry 1 is not"),
    ("sha256-missing", lambda d: _relist(d, lambda doc: doc["frames"][1].pop("sha256")), "frames.json's entry 1 is not"),
    ("sha256-upper-case", lambda d: _relist(d, lambda doc: doc["frames"][1].update(sha256=doc["frames"][1]["sha256"].upper())),
     "frames.json's entry 1 is not"),
    ("file-with-a-path", lambda d: _relist(d, _entry(40, file="../frame-000040.png")), "frames.json's entry 1 is not"),
    ("file-a-number", lambda d: _relist(d, _entry(40, file=40)), "frames.json's entry 1 is not"),
    ("file-another-name", lambda d: _relist(d, _entry(40, file="frame-40.png")), "frames.json's entry 1 is not"),
    ("file-seven-digits", lambda d: ((d / "frame-000040.png").rename(d / "frame-0000040.png"),
                                     _relist(d, _entry(40, file="frame-0000040.png"))), "frames.json's entry 1 is not"),
    ("file-not-its-i", lambda d: _relist(d, _entry(40, i=41)), "frame-000040.png does not name step 41"),
    ("listed-twice", lambda d: _relist(d, lambda doc: doc["frames"].append(dict(doc["frames"][0]))),
     "frame-000020.png is listed twice"),
    ("file-missing", lambda d: (d / "frame-000040.png").unlink(), "frame-000040.png is missing"),
    ("sha256-differs", lambda d: (d / "frame-000040.png").write_bytes(_png(41)), "frame-000040.png: sha256 differs"),
    ("unlisted-file", lambda d: (d / "notes.txt").write_text("x"), "notes.txt is in the set but not listed"),
    ("unlisted-png", lambda d: (d / "frame-000080.png").write_bytes(_png(80)), "frame-000080.png is in the set but not listed"),
    ("unlisted-hidden", lambda d: (d / ".frames.json.swp").write_bytes(b"x"), ".frames.json.swp is in the set but not listed"),
    ("unlisted-directory", lambda d: (d / "raw").mkdir(), "raw is in the set but not listed"),
    ("listed-directory", lambda d: ((d / "frame-000040.png").unlink(), (d / "frame-000040.png").mkdir()),
     "frame-000040.png is not a regular file"),
]
PNG_FORMS = [
    ("png-32x32", _png(40, w=32, h=32), "IHDR"),
    ("png-colour", _png(40, colour=2), "IHDR"),
    ("png-16-bit", _png(40, depth=16), "IHDR"),
    ("png-interlaced", _png(40, interlace=1), "IHDR"),
    ("png-ihdr-14-bytes", _png(40)[:8] + _chunk(b"IHDR", _png(40)[16:29] + b"\x00") + _png(40)[33:], "IHDR"),
    ("png-palette", _ihdr(_png(40), colour=3), "IHDR"),
    ("png-grey-alpha", _ihdr(_png(40), colour=4), "IHDR"),
    ("png-compression-1", _ihdr(_png(40), compression=1), "IHDR"),
    ("png-filter-method-1", _ihdr(_png(40), filter=1), "IHDR"),
    ("png-text-chunk", _png(40, extra=[(b"tEXt", b"Comment\x00x")]), "chunks"),
    ("png-63-rows", _png(40, rows=63), "image data"),
    ("png-65-rows", _png(40, rows=65), "image data"),
    ("png-data-after-the-stream", _png(40, idat=lambda raw: zlib.compress(raw) + b"\x00\x00"), "image data"),
    ("png-filter-type-5", _png(40, filt=5), "image data"),
    ("png-filter-type-5-last-row", _png(40, idat=lambda raw: zlib.compress(raw[:-65] + bytes([5]) + raw[-64:])), "image data"),
    ("png-idat-not-zlib", _png(40, idat=lambda raw: b"not zlib"), "IDAT does not inflate"),
    ("png-chunk-overruns", _png(40)[:50], "truncated"),
    ("png-bad-crc", _png(40)[:-1] + bytes([_png(40)[-1] ^ 0xFF]), "CRC"),
    ("png-truncated", _png(40)[:-6], "truncated"),
    ("png-after-iend", _png(40) + b"\x00", "after IEND"),
    ("not-a-png", b"GIF89a" + bytes(60), "signature"),
]


@pytest.mark.parametrize("break_it,why", [c[1:] for c in REFUSALS], ids=[c[0] for c in REFUSALS])
def test_the_reader_refuses_each_set_spec_2_4_refuses(cc, tmp_path, break_it, why):
    d = make_set(tmp_path)
    break_it(d)
    with pytest.raises(cc.FramesRefused) as e:
        cc.read_frames(str(d))
    assert why in str(e.value), str(e.value)


@pytest.mark.parametrize("data,why", [c[1:] for c in PNG_FORMS], ids=[c[0] for c in PNG_FORMS])
def test_the_reader_refuses_a_listed_png_that_is_not_64x64_8_bit_grey(cc, tmp_path, data, why):
    d = make_set(tmp_path)
    _replace_png(d, 40, data)
    with pytest.raises(cc.FramesRefused) as e:
        cc.read_frames(str(d))
    assert "frame-000040.png is not a 64x64 8-bit grey PNG" in str(e.value) and why in str(e.value), str(e.value)
    assert cc.png_problem(_png(40)) is None


@pytest.mark.parametrize("dot_git", ["file", "directory"])
@pytest.mark.parametrize("depth", [0, 1, 2])
def test_the_reader_refuses_a_set_inside_a_git_work_tree(cc, tmp_path, dot_git, depth):
    """A worktree's .git is a file, a checkout's a directory; either in the set's directory or any ancestor."""
    top = tmp_path / "tree"
    d = make_set(top / "a" / "b", name="20261020-carla-7")
    holder = [d, d.parent, top][depth]
    if dot_git == "file":
        (holder / ".git").write_text("gitdir: elsewhere\n")
    else:
        (holder / ".git").mkdir()
    with pytest.raises(cc.FramesRefused) as e:
        cc.read_frames(str(d))
    assert "inside a git work tree" in str(e.value), str(e.value)


def test_the_reader_refuses_a_set_reached_through_a_link_into_a_work_tree(cc, tmp_path):
    top = tmp_path / "tree"
    d = make_set(top)
    (top / ".git").mkdir()
    link = tmp_path / "outside"
    try:
        os.symlink(str(d), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    with pytest.raises(cc.FramesRefused) as e:
        cc.read_frames(str(link))
    assert "inside a git work tree" in str(e.value)


def test_the_reader_refuses_a_set_reached_through_a_link_inside_a_work_tree(cc, tmp_path):
    """The other half of the link case: the set lies outside any work tree, the path given runs through a link inside one."""
    d = make_set(tmp_path / "outside")
    top = tmp_path / "tree"
    (top / ".git").mkdir(parents=True)
    link = top / "frames"
    try:
        os.symlink(str(d), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    with pytest.raises(cc.FramesRefused) as e:
        cc.read_frames(str(link))
    assert "inside a git work tree" in str(e.value)


def test_the_reader_refuses_a_listed_frame_that_is_a_link(cc, tmp_path):
    d = make_set(tmp_path)
    elsewhere = tmp_path / "elsewhere.png"
    elsewhere.write_bytes((d / "frame-000040.png").read_bytes())
    (d / "frame-000040.png").unlink()
    try:
        os.symlink(str(elsewhere), str(d / "frame-000040.png"))
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    with pytest.raises(cc.FramesRefused) as e:
        cc.read_frames(str(d))
    assert "frame-000040.png is not a regular file" in str(e.value)


def test_the_reader_refuses_what_is_not_a_directory(cc, tmp_path):
    for p in (tmp_path / "absent", tmp_path / "a-file"):
        if p.name == "a-file":
            p.write_text("x")
        with pytest.raises(cc.FramesRefused) as e:
            cc.read_frames(str(p))
        assert "is not a directory" in str(e.value)


# ------------------------------------------------------------------ the file source's run

def _frames_run(cc, monkeypatch, tmp_path, argv, cv2=None, model=None, clock=None):
    """main() on a frame set with the camera booby-trapped: any glob of /dev/video*, VideoCapture or open_camera fails
    the test. Returns (rc, the log's records, cv2, clock, scratch)."""
    clock = clock or Clock()
    cv2 = cv2 or FakeCv2(clock)
    touched = []
    scratch = tmp_path / "shm" / "camera-claim.png"
    scratch.parent.mkdir(exist_ok=True)
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setattr(cc, "time", clock)
    monkeypatch.setattr(cc, "glob", NoCamera(touched))
    monkeypatch.setattr(cc, "open_camera", _refuse(touched, "open_camera"))
    monkeypatch.setattr(cc, "SCRATCH", str(scratch))
    if model is not None:
        monkeypatch.setattr(cc.vlm_request, "ask", model.ask)
        monkeypatch.setattr(cc.vc, "exchange", model.exchange)
    log = tmp_path / "claims.jsonl"
    if log.exists():
        log.unlink()                                  # each run its own log: the client appends
    rc = cc.main(argv + ["--log", str(log)])
    assert touched == [], touched
    recs = [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else None
    return rc, recs, cv2, clock, scratch


def test_frames_go_through_the_reduction_into_the_scratch_in_the_sets_order(cc, monkeypatch, tmp_path, capsys):
    d = make_set(tmp_path / "frames", order=(40, 20, 60))
    rc, recs, cv2, _clock, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry"])
    assert rc == 0
    assert [(r["event"], r["i"], r["file"]) for r in recs] == [("frame", 40, "frame-000040.png"), ("frame", 20, "frame-000020.png"),
                                                               ("frame", 60, "frame-000060.png")]
    assert [list(r) for r in recs] == [["event", "i", "file", "t"]] * 3
    assert [x[:2] for x in cv2.reads] == [("frame-000040.png", 1), ("frame-000020.png", 1), ("frame-000060.png", 1)]
    # the existing lines, cvtColor to imwrite: grey, the centre square (all of a 64x64 frame), --size with INTER_AREA
    assert cv2.writes == [(str(scratch), ("resize", (64, 64), 3, ("crop", 0, 64, 0, 64, ("cvtColor", 6, ("imread", f, 1)))))
                          for f in ("frame-000040.png", "frame-000020.png", "frame-000060.png")]
    assert capsys.readouterr().out.splitlines() == [json.dumps(r) for r in recs]


def test_frames_are_one_per_interval_and_a_slow_frame_is_never_caught_up(cc, monkeypatch, tmp_path):
    d = make_set(tmp_path / "frames")
    rc, recs, cv2, clock, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry"])
    assert rc == 0 and [x[2] for x in cv2.reads] == [100.0, 101.0, 102.0] and clock.sleeps == [1.0, 1.0]
    assert [r["t"] for r in recs] == [0.0, 1.0, 2.0]
    rc, recs, cv2, clock, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry", "--frame-interval", "0.25"])
    assert rc == 0 and [x[2] for x in cv2.reads] == [100.0, 100.25, 100.5] and clock.sleeps == [0.25, 0.25]
    # The first frame's model call takes 1.75 s: the second starts the moment the first is done, the third one interval
    # after the second. No frame is hurried to make up for the slow one.
    clock = Clock()
    rc, recs, cv2, clock, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d)], clock=clock,
                                           model=Model(cc, clock, ask_s=[1.75]))
    assert rc == 0 and [x[2] for x in cv2.reads] == [100.0, 101.8125, 102.8125], cv2.reads
    assert clock.sleeps == [1.0 - Model.ASK_S]       # the third frame's wait; the second waited for nothing


class OverClock(Clock):
    """A clock whose first sleep overshoots by 0.05 s, as a real sleep may."""

    def sleep(self, s):
        Clock.sleep(self, s + (0.05 if not self.sleeps else 0.0))


def test_no_frame_starts_sooner_than_one_interval_after_the_previous_one_started(cc, monkeypatch, tmp_path):
    d = make_set(tmp_path / "frames")
    rc, recs, cv2, clock, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry"], clock=OverClock())
    starts = [x[2] for x in cv2.reads]
    assert rc == 0 and all(round(b - a, 9) >= 1.0 for a, b in zip(starts, starts[1:])), starts


def test_a_frame_whose_turn_comes_after_seconds_because_the_one_before_was_slow_is_not_started(cc, monkeypatch, tmp_path):
    """--seconds ends the run at the moment a frame would really start: the first frame's model call takes 1.75 s, so the
    second would start at 1.8125 s, past --seconds 1.5, though one interval after the first frame's start is only 1.0 s."""
    d = make_set(tmp_path / "frames")
    clock = Clock()
    rc, recs, cv2, clock, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--seconds", "1.5"], clock=clock,
                                           model=Model(cc, clock, ask_s=[1.75]))
    assert rc == 1 and [r["event"] for r in recs] == ["frame", "claim", "cut"] and len(cv2.reads) == 1, recs
    assert (recs[-1]["frames"], recs[-1]["of"]) == (1, 3)


def test_a_set_is_read_once_or_with_loop_until_seconds(cc, monkeypatch, tmp_path):
    d = make_set(tmp_path / "frames")
    order = ["frame-000020.png", "frame-000040.png", "frame-000060.png"]
    rc, recs, cv2, clock, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry", "--seconds", "7.5"])
    assert rc == 0 and [r["file"] for r in recs] == order and clock.sleeps == [1.0, 1.0]     # no wait after the last
    rc, recs, cv2, clock, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry", "--seconds", "7.5", "--loop"])
    assert rc == 0 and [r["file"] for r in recs] == (order * 3)[:8] and [x[2] for x in cv2.reads] == [100.0 + k for k in range(8)]
    assert clock.now == 107.0                        # the ninth frame would start at 8.0 s: past --seconds, so no wait for it
    rc, recs, cv2, clock, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry", "--seconds", "1.5"])
    assert rc == 1 and [r.get("file") for r in recs] == order[:2] + [None] and recs[-1]["event"] == "cut"   # one pass, cut


def test_a_single_pass_that_seconds_cuts_short_is_logged_as_cut_and_fails(cc, monkeypatch, tmp_path):
    """Without --loop the whole set is asked for: a pass that --seconds ends before its last frame logs a "cut" record
    (the frames read, of how many) and exits 1, so a dry run on part of a set cannot pass for one on all of it."""
    d = make_set(tmp_path / "frames", order=(20, 40, 60, 80, 100))
    rc, recs, cv2, clock, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry", "--seconds", "2.5"])
    assert rc == 1 and [r["event"] for r in recs] == ["frame"] * 3 + ["cut"], recs
    assert list(recs[-1]) == ["event", "frames", "of", "t"] and (recs[-1]["frames"], recs[-1]["of"]) == (3, 5)
    assert len(cv2.reads) == 3 and clock.sleeps == [1.0, 1.0] and not scratch.exists()     # no wait for the frame cut
    # the last frame starting before --seconds makes the pass whole; with --loop, --seconds is the run's end by design
    rc, recs, cv2, _c, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry", "--seconds", "4.5"])
    assert rc == 0 and [r["event"] for r in recs] == ["frame"] * 5
    rc, recs, cv2, _c, _s = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry", "--seconds", "2.5", "--loop"])
    assert rc == 0 and [r["event"] for r in recs] == ["frame"] * 3


def test_dry_mode_asks_nothing_claims_nothing_and_connects_nowhere(cc, monkeypatch, tmp_path):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    srv.setblocking(False)
    host, port = srv.getsockname()
    d = make_set(tmp_path / "frames")
    touched = []
    try:
        with monkeypatch.context() as m:
            m.setattr(socket, "socket", _refuse(touched, "socket.socket"))
            m.setattr(socket, "create_connection", _refuse(touched, "socket.create_connection"))
            m.setattr(urllib.request, "urlopen", _refuse(touched, "urllib.request.urlopen"))
            m.setattr(cc.vlm_request, "ask", _refuse(touched, "vlm_request.ask"))
            m.setattr(cc.vc, "exchange", _refuse(touched, "vlm_client.exchange"))
            m.setattr(cc.vc, "pack", _refuse(touched, "vlm_client.pack"))
            rc, recs, cv2, _c, scratch = _frames_run(cc, m, tmp_path, ["--frames", str(d), "--dry", "--loop", "--seconds", "5",
                                                                       "--host", host, "--port", str(port),
                                                                       "--server", "http://%s:%d" % (host, port)])
        assert touched == [], touched
        with pytest.raises(BlockingIOError):
            srv.accept()                              # the fake monitor and server: nobody came
    finally:
        srv.close()
    assert rc == 0 and [r["event"] for r in recs] == ["frame"] * 5 and len(cv2.writes) == 5


def test_without_dry_each_frame_is_logged_and_then_claimed_as_from_the_camera(cc, monkeypatch, tmp_path):
    d = make_set(tmp_path / "frames")
    clock = Clock()
    model = Model(cc, clock)
    rc, recs, cv2, clock, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--seq", "700"],
                                                clock=clock, model=model)
    assert rc == 0
    got = [[(k, v) for k, v in r.items() if k not in TIMES] for r in recs]
    assert got == [
        [("event", "frame"), ("i", 20), ("file", "frame-000020.png")],
        [("event", "claim"), ("seq", 701), ("cls", 7), ("conf", 93), ("model_us", 250000), ("verdict", "ACCEPT"), ("reason", "ok")],
        [("event", "frame"), ("i", 40), ("file", "frame-000040.png")],
        [("event", "unclassifiable"), ("why", WHY[:120])],
        [("event", "frame"), ("i", 60), ("file", "frame-000060.png")],
        [("event", "claim"), ("seq", 702), ("cls", 3), ("conf", 41), ("model_us", 250000), ("verdict", "REJECT"),
         ("reason", "confidence-below-threshold")]]
    # the model was asked about the scratch, holding the frame of the moment; the claims went to the default monitor
    assert [(s, p) for s, p, _x in model.asked] == [("http://127.0.0.1:8089", str(scratch))] * 3
    assert [json.loads(x)[3][5][2][1] for _s, _p, x in model.asked] == ["frame-000020.png", "frame-000040.png", "frame-000060.png"]
    assert model.sent == [("192.168.100.10", 7102, 701, 7, 93, 1), ("192.168.100.10", 7102, 702, 3, 41, 1)]


def test_the_scratch_is_the_only_file_a_frames_run_writes_and_it_is_gone_at_exit(cc, monkeypatch, tmp_path):
    root = tmp_path / "frames"
    d = make_set(root)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    seen = []
    clock = Clock()
    clock.on_sleep = lambda n: seen.append(os.path.exists(str(tmp_path / "shm" / "camera-claim.png")))
    rc, recs, cv2, clock, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry"], clock=clock)
    assert rc == 0 and seen == [True, True]          # held between frames
    assert {p for p, _h in cv2.writes} == {str(scratch)} and not scratch.exists()
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["claims.jsonl", "frames", "shm"] and list((tmp_path / "shm").iterdir()) == []
    assert sorted(p.name for p in root.iterdir()) == [d.name]


def test_the_scratch_is_removed_when_a_frames_run_is_interrupted(cc, monkeypatch, tmp_path):
    d = make_set(tmp_path / "frames")
    clock = Clock()

    def interrupt(n):
        raise KeyboardInterrupt
    clock.on_sleep = interrupt
    with pytest.raises(KeyboardInterrupt):
        _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry"], clock=clock)
    assert not (tmp_path / "shm" / "camera-claim.png").exists()


def test_a_frame_that_changes_after_the_set_was_read_stops_the_run_before_it_is_read(cc, monkeypatch, tmp_path, capsys):
    d = make_set(tmp_path / "frames")
    clock = Clock()
    clock.on_sleep = lambda n: (d / "frame-000040.png").write_bytes(_png(41)) if n == 1 else None
    rc, recs, cv2, clock, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry"], clock=clock)
    assert rc == 2 and [x[0] for x in cv2.reads] == ["frame-000020.png"] and [r["i"] for r in recs] == [20]
    assert "refused: frame-000040.png changed after the set was read" in capsys.readouterr().err
    assert not scratch.exists()


def test_a_frame_cv2_cannot_read_stops_the_run(cc, monkeypatch, tmp_path, capsys):
    d = make_set(tmp_path / "frames")
    clock = Clock()
    rc, recs, cv2, clock, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry"], clock=clock,
                                                cv2=FakeCv2(clock, imread_none=True))
    assert rc == 2 and recs == [] and cv2.writes == []
    assert "refused: cv2 could not read frame-000020.png" in capsys.readouterr().err


class NoWriteCv2(FakeCv2):
    """A cv2 whose imwrite fails from its `fail_from`-th call on (1: the first): it returns False and writes nothing, as
    OpenCV's does when it cannot write the file (no /dev/shm, a full tmpfs)."""

    def __init__(self, clock, fail_from):
        FakeCv2.__init__(self, clock)
        self.fail_from, self.calls = fail_from, 0

    def imwrite(self, path, img):
        self.calls += 1
        return False if self.calls >= self.fail_from else FakeCv2.imwrite(self, path, img)


@pytest.mark.parametrize("dry,fail_from", [(True, 1), (False, 1), (True, 2)], ids=["dry-first", "claims-first", "dry-second"])
def test_a_scratch_cv2_cannot_write_stops_the_run_before_that_frame_is_logged(cc, monkeypatch, tmp_path, capsys, dry, fail_from):
    """imwrite returning False wrote no scratch: that frame is not logged, no model is asked about a scratch that is not
    there, and the run ends with the refusal line and exit 2; the frames before it stay logged, the scratch is gone."""
    d = make_set(tmp_path / "frames")
    clock = Clock()
    touched = []
    monkeypatch.setattr(cc.vlm_request, "ask", _refuse(touched, "vlm_request.ask"))
    monkeypatch.setattr(cc.vc, "exchange", _refuse(touched, "vlm_client.exchange"))
    rc, recs, cv2, clock, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d)] + (["--dry"] if dry else []),
                                                clock=clock, cv2=NoWriteCv2(clock, fail_from))
    order = ["frame-000020.png", "frame-000040.png"]
    assert rc == 2 and [r["file"] for r in recs] == order[:fail_from - 1] and touched == [], (rc, recs, touched)
    assert cv2.calls == fail_from and len(cv2.writes) == fail_from - 1 and not scratch.exists()
    assert "refused: cv2 could not write the scratch for %s" % order[fail_from - 1] in capsys.readouterr().err


@pytest.mark.parametrize("how", ["removed", "a-directory"])
def test_a_frame_that_can_no_longer_be_read_stops_the_run_with_the_refusal_line(cc, monkeypatch, tmp_path, capsys, how):
    """A frame removed, or replaced by a directory, after the set was read ends the run as a changed one does -- the
    refusal line, exit 2, the scratch gone -- and not with a traceback."""
    d = make_set(tmp_path / "frames")
    gone = d / "frame-000040.png"
    clock = Clock()

    def take_it_away(n):
        if n == 1:
            gone.unlink()
            if how == "a-directory":
                gone.mkdir()
    clock.on_sleep = take_it_away
    rc, recs, cv2, clock, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry"], clock=clock)
    assert rc == 2 and [x[0] for x in cv2.reads] == ["frame-000020.png"] and [r["i"] for r in recs] == [20]
    assert "refused: frame-000040.png cannot be read: " in capsys.readouterr().err
    assert not scratch.exists()


def test_a_refused_set_writes_nothing_and_touches_no_cv2(cc, monkeypatch, tmp_path, capsys):
    d = make_set(tmp_path / "frames", simulated=DROP)
    rc, recs, cv2, _c, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry"])
    assert rc == 2 and recs is None and cv2.reads == [] and cv2.writes == [] and not scratch.exists()
    err = capsys.readouterr().err
    assert err.startswith("camera_client: --frames %s refused: simulated is not true" % d), err


def test_an_empty_frames_dir_is_refused_and_never_falls_through_to_the_camera(cc, monkeypatch, tmp_path, capsys):
    """--frames "" (an unset shell variable) names no set: the reader refuses it; the camera path is not reached."""
    rc, recs, cv2, _c, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", "", "--dry"])
    assert rc == 2 and recs is None and cv2.reads == [] and not scratch.exists()
    assert "refused:  is not a directory" in capsys.readouterr().err


def test_frames_given_as_empty_text_is_refused_and_never_reaches_the_camera(cc, monkeypatch, tmp_path, capsys):
    """spec 8 item 1: the camera is never opened when --frames is given, an empty DIR included (an unset variable)."""
    rc, recs, cv2, _c, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", ""])
    assert rc == 2 and recs is None and cv2.reads == []
    assert "refused:  is not a directory" in capsys.readouterr().err


def test_size_is_honoured_on_the_file_source(cc, monkeypatch, tmp_path):
    d = make_set(tmp_path / "frames")
    rc, recs, cv2, _c, scratch = _frames_run(cc, monkeypatch, tmp_path, ["--frames", str(d), "--dry", "--size", "32"])
    assert rc == 0 and [h[1] for _p, h in cv2.writes] == [(32, 32)] * 3


@pytest.mark.parametrize("extra,why", [
    (["--dry"], "--dry and --loop need --frames"),
    (["--loop"], "--dry and --loop need --frames"),
    (["--frames", "SET", "--outages", "1"], "--outages counts camera outages"),
    (["--frames", "", "--outages", "1"], "--outages counts camera outages"),
    (["--frames", "SET", "--frame-interval", "0"], "argument --frame-interval: not a positive, finite number of seconds"),
    (["--frames", "SET", "--frame-interval", "-1"], "argument --frame-interval: not a positive, finite number of seconds"),
    (["--frames", "SET", "--frame-interval", "nan"], "argument --frame-interval: not a positive, finite number of seconds"),
    (["--frames", "SET", "--frame-interval", "inf"], "argument --frame-interval: not a positive, finite number of seconds"),
    (["--frames", "SET", "--frame-interval", "soon"], "argument --frame-interval: not a positive, finite number of seconds"),
])
def test_the_file_source_options_are_refused_where_they_mean_nothing(cc, monkeypatch, tmp_path, capsys, extra, why):
    d = make_set(tmp_path / "frames")
    monkeypatch.setattr(cc, "stream", _refuse([], "stream"))
    with pytest.raises(SystemExit) as e:
        cc.main([str(d) if x == "SET" else x for x in extra] + ["--log", str(tmp_path / "claims.jsonl")])
    assert e.value.code == 2 and why in capsys.readouterr().err
    assert not (tmp_path / "claims.jsonl").exists()


def test_the_file_source_options_default_to_off_and_one_second(cc, monkeypatch, tmp_path):
    got = []
    monkeypatch.setattr(cc, "stream", lambda a, frames=None: got.append(a) or 0)
    assert cc.main(["--log", str(tmp_path / "claims.jsonl")]) == 0
    a = got[0]
    assert (a.frames, a.dry, a.loop, a.frame_interval) == (None, False, False, 1.0)


# ------------------------------------------------------------------ the camera path, unchanged

def test_the_camera_paths_defaults_and_scratch_are_unchanged(cc, monkeypatch, tmp_path):
    assert cc.SCRATCH == "/dev/shm/camera-claim.png"
    got = []
    monkeypatch.setattr(cc, "stream", lambda a, frames=None: got.append(a) or 0)
    assert cc.main(["--log", str(tmp_path / "claims.jsonl")]) == 0
    a = got[0]
    assert {k: getattr(a, k) for k in ("host", "port", "server", "size", "seconds", "outages", "tail", "seq", "check",
                                       "deadline_ms", "opened_in_silence")} == {
        "host": "192.168.100.10", "port": 7102, "server": "http://127.0.0.1:8089", "size": 64, "seconds": 240.0,
        "outages": 0, "tail": 10.0, "seq": 5000, "check": None, "deadline_ms": 2000, "opened_in_silence": False}


def _camera_run(cc, monkeypatch, tmp_path, capsys, argv):
    """The camera path on CameraWorld: the camera plugged in 0.5-2.0 s and from 4.0 s on (fake time from the start)."""
    clock = Clock()
    world = CameraWorld(clock, [(clock.now + 0.5, clock.now + 2.0), (clock.now + 4.0, 1e9)])
    cv2 = FakeCv2(clock, world)
    model = Model(cc, clock)
    scratch = tmp_path / "shm" / "camera-claim.png"
    scratch.parent.mkdir()
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setattr(cc, "time", clock)
    monkeypatch.setattr(cc, "glob", world)
    monkeypatch.setattr(cc, "SCRATCH", str(scratch))
    monkeypatch.setattr(cc.vlm_request, "ask", model.ask)
    monkeypatch.setattr(cc.vc, "exchange", model.exchange)
    log = tmp_path / "claims.jsonl"
    rc = cc.main(argv + ["--log", str(log)])
    lines = log.read_text().splitlines()
    assert capsys.readouterr().out.splitlines() == lines
    assert not scratch.exists()
    assert {p for p, _h in cv2.writes} == {str(scratch)}
    assert [h for _p, h in cv2.writes] == [("resize", (64, 64), 3, ("crop", 0, 480, 80, 560, ("cvtColor", 6, ("camera", "/dev/video1", n))))
                                           for n in [h[3][5][2][2] for _p, h in cv2.writes]]
    pairs = [json.loads(x, object_pairs_hook=list) for x in lines]
    assert all([k for k, _v in p if k in TIMES] == (["t_send", "t_reply", "t"] if p[0][1] == "claim" else ["t"])
               for p in pairs), pairs
    untimed = [[(k, v) for k, v in p if k not in TIMES] for p in pairs]
    return rc, untimed, [e for e in world.trace if e[0] != "read"], model


def _rec(**kv):
    return list(kv.items())


A1 = _rec(event="claim", seq=0, cls=7, conf=93, model_us=250000, verdict="ACCEPT", reason="ok")
U = _rec(event="unclassifiable", why=WHY[:120])
R3 = _rec(event="claim", seq=0, cls=3, conf=41, model_us=250000, verdict="REJECT", reason="confidence-below-threshold")


def _claims(first_seq, n, start=0):
    """n records of the answer cycle (accept, unclassifiable, reject) from position `start`, seqs from first_seq."""
    out, seq = [], first_seq
    for k in range(start, start + n):
        r = [A1, U, R3][k % 3]
        if r is not U:
            r = [(key, seq if key == "seq" else v) for key, v in r]
            seq += 1
        out.append(r)
    return out


CAMERA_OPEN = _rec(event="camera-open", device="/dev/video1")
# open_camera's walk: the metadata node opens, is set to one buffer, yields nothing and is released; the camera yields.
OPENS = [("open", "/dev/video0", 200), ("set", "/dev/video0", 38, 1), ("release", "/dev/video0"),
         ("open", "/dev/video1", 200), ("set", "/dev/video1", 38, 1)]


def test_the_camera_path_writes_the_base_files_records(cc, monkeypatch, tmp_path, capsys):
    rc, recs, opens, model = _camera_run(cc, monkeypatch, tmp_path, capsys, ["--seconds", "6"])
    assert rc == 0
    assert recs == ([_rec(event="camera-absent"), CAMERA_OPEN] + _claims(5001, 5) + [_rec(event="camera-lost"), _rec(event="camera-absent"),
                    CAMERA_OPEN] + _claims(5004, 7, start=5)), recs
    assert opens == OPENS + [("release", "/dev/video1")] + OPENS + [("release", "/dev/video1")]
    assert model.sent[0] == ("192.168.100.10", 7102, 5001, 7, 93, 1)


def test_the_camera_path_with_outages_ends_as_the_base_file_did(cc, monkeypatch, tmp_path, capsys):
    rc, recs, opens, model = _camera_run(cc, monkeypatch, tmp_path, capsys, ["--outages", "1", "--tail", "1", "--seconds", "60",
                                                                            "--seq", "40"])
    assert rc == 0
    assert recs == ([_rec(event="camera-absent"), CAMERA_OPEN] + _claims(41, 5) + [_rec(event="camera-lost"), _rec(event="camera-absent"),
                    CAMERA_OPEN] + _claims(44, 4, start=5) + [_rec(event="done", outages=1)]), recs


# ------------------------------------------------------------------ the dry run's lock

def test_the_dry_run_lock_pins_opencv_headless_and_numpy_by_hash_and_nothing_else():
    with open(LOCK, "rb") as f:
        text = f.read().decode("ascii")
    assert "\r" not in text
    body = [x for x in text.split("\n") if x and not x.lstrip().startswith("#")]
    pins = re.findall(r"^([a-z0-9-]+)==([0-9]+(?:\.[0-9]+)+) \\\n    --hash=sha256:([0-9a-f]{64})$", "\n".join(body), re.M)
    assert sorted(n for n, _v, _h in pins) == ["numpy", "opencv-python-headless"]
    assert len(body) == 2 * len(pins)                 # every line not a comment is a pin or its one hash
    head = "\n".join(itertools.takewhile(lambda x: x.startswith("#"), text.split("\n")))
    for need in ("requirements-dry.lock -- ", "--require-hashes --no-deps", "~/sdv-camera-venv", "--dry", "x86_64", "CPython 3.12"):
        assert need in head, need
