"""frameset.py -- the simulated camera frames of a CARLA take: the reduction, the PNG and the set (sdv/carla).

Phase 7 spec 2.4 and the camera rule (spec 12, plan decision D4): no real camera frame
is ever kept, and a simulated CARLA frame is kept only reduced -- grey, the centre square, 64 x 64, as
orin-native/edge-llm/camera_client.py would make it -- labelled as simulated with its licence, outside every work tree.
Standard library only (zlib and struct), so the Windows capture client needs nothing installed.

    REDUCTION  from the camera's BGRA buffer (WIDTH x HEIGHT), in memory: Y = (299 R + 587 G + 114 B + 500) // 1000 per
               pixel (BT.601 in per mille, rounded half up); the centre HEIGHT columns (CROP_X0 .. CROP_X0 + HEIGHT - 1)
               of all rows; each output pixel (the sum of its BLOCK x BLOCK block + 8) // 16. No other form of the frame
               is ever written: the writer takes the reduced bytes only.
    PNG        SIZE x SIZE, 8-bit greyscale (colour type 0), not interlaced, chunks IHDR, IDAT, IEND only, every row
               filter 0.
    THE SET    <root>/<name>/frame-%06d.png (the step index whose image it is) and frames.json, written last by
               close(); the writer refuses a set directory that exists, a name that is not a take's name, a root that
               is not absolute or lies inside a work tree (a directory or an ancestor holding .git).
    READER     read_set refuses, as spec 2.4 says a reader must: no frames.json; format not 1; simulated not true;
               generator not carla; a listed file missing or with another sha256; a file in the directory that is
               neither frames.json nor listed; a PNG not 64 x 64 grey; a set inside a work tree; a listed file whose
               name is not frame-%06d.png of the step index it is listed for (a later reader names a step by that
               index, so a file listed for another step than its name says would name the wrong one).
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

WIDTH, HEIGHT = 320, 256                  # the camera of spec 2.1
SIZE = 64                                 # camera_client.py's --size default
CROP_X0 = (WIDTH - HEIGHT) // 2           # the centre square's first column
BLOCK = HEIGHT // SIZE                    # each output pixel is the mean of a BLOCK x BLOCK block
GREY_WEIGHTS = (299, 587, 114)            # R, G, B per mille (BT.601)
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
FRAMES_JSON = "frames.json"
FRAME_FILE = re.compile(r"frame-(\d{6})\.png")
CARLA_VERSION = "0.9.16"
CAMERA = {"type": "sensor.camera.rgb", "width": WIDTH, "height": HEIGHT, "mount": {"x": 1.5, "y": 0.0, "z": 1.6}}
REDUCTION = {"grey": "BT.601", "crop": "centre-square", "size": SIZE, "resample": "%dx%d-block-mean" % (BLOCK, BLOCK)}
LICENCE = "CARLA assets: CC-BY (CARLA's README). Simulated frames; never published."
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
assert BLOCK * BLOCK == 16 and HEIGHT == SIZE * BLOCK


class FrameSetError(ValueError):
    """A frame or a set this module refuses to write or read."""


def inside_work_tree(path: Path) -> bool:
    """True when the path or any ancestor holds .git (a directory, or the file a linked worktree has)."""
    p = Path(path).expanduser().absolute()
    return any((d / ".git").exists() for d in [p] + list(p.parents))


def reduce_bgra(raw: bytes, width: int = WIDTH, height: int = HEIGHT) -> bytes:
    """The camera's BGRA buffer as SIZE x SIZE grey bytes, row by row (the module docstring's REDUCTION)."""
    if (width, height) != (WIDTH, HEIGHT) or len(raw) != width * height * 4:
        raise FrameSetError("a %dx%d BGRA buffer of %d bytes is expected, got %dx%d and %d bytes"
                            % (WIDTH, HEIGHT, WIDTH * HEIGHT * 4, width, height, len(raw)))
    wr, wg, wb = GREY_WEIGHTS
    stride = width * 4
    out = bytearray(SIZE * SIZE)
    sums = [0] * SIZE
    for row in range(height):
        base = row * stride + CROP_X0 * 4
        seg = raw[base:base + HEIGHT * 4]
        grey = [(wr * r + wg * g + wb * b + 500) // 1000 for b, g, r in zip(seg[0::4], seg[1::4], seg[2::4])]
        for k in range(SIZE):
            sums[k] += grey[BLOCK * k] + grey[BLOCK * k + 1] + grey[BLOCK * k + 2] + grey[BLOCK * k + 3]
        if row % BLOCK == BLOCK - 1:
            o = (row // BLOCK) * SIZE
            for k in range(SIZE):
                out[o + k] = (sums[k] + 8) // 16
            sums = [0] * SIZE
    return bytes(out)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_bytes(grey: bytes, size: int = SIZE) -> bytes:
    """SIZE x SIZE grey bytes as a PNG: 8-bit greyscale, not interlaced, IHDR, one IDAT, IEND, filter 0 on every row."""
    if size != SIZE or len(grey) != SIZE * SIZE:
        raise FrameSetError("a reduced frame is %d grey bytes, got %d" % (SIZE * SIZE, len(grey)))
    rows = b"".join(b"\x00" + grey[r * SIZE:(r + 1) * SIZE] for r in range(SIZE))
    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 0, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(rows, 9)) + _chunk(b"IEND", b"")


def png_info(data: bytes) -> Dict[str, Any]:
    """The PNG's header fields and chunk types (CRCs checked)."""
    if data[:8] != PNG_SIGNATURE:
        raise FrameSetError("not a PNG")
    k, chunks, idat = 8, [], b""
    ihdr: Optional[bytes] = None
    while k < len(data):
        if k + 8 > len(data):
            raise FrameSetError("a truncated chunk")
        (n,) = struct.unpack(">I", data[k:k + 4])
        kind, body = data[k + 4:k + 8], data[k + 8:k + 8 + n]
        if len(body) != n or k + 12 + n > len(data):
            raise FrameSetError("a truncated chunk")
        (crc,) = struct.unpack(">I", data[k + 8 + n:k + 12 + n])
        if crc != zlib.crc32(kind + body) & 0xFFFFFFFF:
            raise FrameSetError("a chunk's CRC does not hold")
        chunks.append(kind.decode("latin-1"))
        if kind == b"IHDR":
            ihdr = body
        elif kind == b"IDAT":
            idat += body
        k += 12 + n
    if ihdr is None or len(ihdr) != 13:
        raise FrameSetError("no IHDR")
    w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", ihdr)
    return {"width": w, "height": h, "bit_depth": depth, "colour_type": ctype, "compression": comp, "filter": filt,
            "interlace": inter, "chunks": chunks, "idat": idat}


def _is_reduced_png(info: Dict[str, Any]) -> bool:
    ch = info["chunks"]
    return ((info["width"], info["height"], info["bit_depth"], info["colour_type"], info["compression"], info["filter"],
             info["interlace"]) == (SIZE, SIZE, 8, 0, 0, 0, 0)
            and len(ch) >= 3 and ch[0] == "IHDR" and ch[-1] == "IEND" and set(ch[1:-1]) == {"IDAT"})


def png_pixels(data: bytes) -> bytes:
    """The grey bytes of a PNG this module writes (64 x 64, 8-bit grey, every row filter 0)."""
    info = png_info(data)
    if not _is_reduced_png(info):
        raise FrameSetError("not a %dx%d 8-bit grey PNG with IHDR, IDAT, IEND only" % (SIZE, SIZE))
    raw = zlib.decompress(info["idat"])
    if len(raw) != SIZE * (SIZE + 1):
        raise FrameSetError("the image data is not %d rows of %d bytes" % (SIZE, SIZE + 1))
    rows = [raw[r * (SIZE + 1):(r + 1) * (SIZE + 1)] for r in range(SIZE)]
    if any(row[0] != 0 for row in rows):
        raise FrameSetError("a row filter other than 0")
    return b"".join(row[1:] for row in rows)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FrameSetWriter:
    """Writes one frame set: frames as they come (add), frames.json last (close)."""

    def __init__(self, root: Path, name: str, *, seed: int, stride_steps: int, town: str, blueprint: str) -> None:
        root = Path(root)
        if not root.is_absolute():
            raise FrameSetError("the frame-set root %s is not an absolute path" % root)
        if not NAME_PATTERN.fullmatch(name or ""):
            raise FrameSetError("the set's name %r is not [a-z0-9][a-z0-9-]{0,47}" % (name,))
        if inside_work_tree(root):
            raise FrameSetError("the frame-set root %s lies inside a work tree: frames are never kept there" % root)
        self.dir = root / name
        if self.dir.exists():
            raise FrameSetError("the frame set %s exists: a set is never rewritten" % self.dir)
        self.dir.mkdir(parents=True)
        self.name, self.seed, self.stride_steps, self.town, self.blueprint = name, int(seed), int(stride_steps), town, blueprint
        self.frames: List[Dict[str, Any]] = []
        self.closed = False

    def add(self, i: int, frame: int, grey: bytes) -> None:
        """Write step i's reduced frame (grey bytes from reduce_bgra) as frame-%06d.png."""
        if self.closed:
            raise FrameSetError("frames.json is written: no frame after it")
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i <= 999999:
            raise FrameSetError("step index %r outside 0..999999" % (i,))
        if any(f["i"] == i for f in self.frames):
            raise FrameSetError("step %d has a frame already" % i)
        png = png_bytes(grey)
        name = "frame-%06d.png" % i
        (self.dir / name).write_bytes(png)
        self.frames.append({"file": name, "i": i, "frame": int(frame), "sha256": _sha256(png)})

    def close(self, take_sha256: str) -> Dict[str, Any]:
        """Write frames.json, last: the label, the licence, the take's hash and every frame's hash."""
        if self.closed:
            raise FrameSetError("frames.json is written already")
        doc = {"format": 1, "simulated": True, "generator": "carla", "name": self.name, "carla_version": CARLA_VERSION,
               "town": self.town, "seed": self.seed, "blueprint": self.blueprint, "camera": json.loads(json.dumps(CAMERA)),
               "reduction": dict(REDUCTION), "stride_steps": self.stride_steps, "licence": LICENCE, "take_sha256": take_sha256,
               "frames": sorted(self.frames, key=lambda f: f["i"])}
        (self.dir / FRAMES_JSON).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        self.closed = True
        return doc


def read_set(path: Path) -> Dict[str, Any]:
    """frames.json of a set this module wrote, after every check of the module docstring's READER."""
    d = Path(path)
    if inside_work_tree(d):
        raise FrameSetError("the set %s lies inside a work tree" % d)
    fj = d / FRAMES_JSON
    if not fj.is_file():
        raise FrameSetError("%s has no frames.json" % d)
    try:
        doc = json.loads(fj.read_text(encoding="utf-8"))
    except ValueError as err:
        raise FrameSetError("frames.json is not JSON: %s" % err) from err
    if not isinstance(doc, dict) or doc.get("format") != 1 or isinstance(doc.get("format"), bool):
        raise FrameSetError("frames.json's format is not 1")
    if doc.get("simulated") is not True:
        raise FrameSetError("frames.json does not say simulated: true")
    if doc.get("generator") != "carla":
        raise FrameSetError("frames.json's generator is not carla")
    frames = doc.get("frames")
    if not isinstance(frames, list):
        raise FrameSetError("frames.json has no frames list")
    listed = set()
    for f in frames:
        name = f.get("file") if isinstance(f, dict) else None
        if not isinstance(name, str) or not FRAME_FILE.fullmatch(name) or name in listed:
            raise FrameSetError("frames.json lists %r" % (f,))
        step = f.get("i")
        if isinstance(step, bool) or not isinstance(step, int) or name != "frame-%06d.png" % step:
            raise FrameSetError("%s is listed for step %r, which it is not named for" % (name, step))
        listed.add(name)
        p = d / name
        if not p.is_file():
            raise FrameSetError("%s is listed but missing" % name)
        data = p.read_bytes()
        if _sha256(data) != f.get("sha256"):
            raise FrameSetError("%s does not have its listed sha256" % name)
        if not _is_reduced_png(png_info(data)):
            raise FrameSetError("%s is not a %dx%d grey PNG" % (name, SIZE, SIZE))
    extra = sorted(p.name for p in d.iterdir() if p.name != FRAMES_JSON and p.name not in listed)
    if extra:
        raise FrameSetError("files in the set that frames.json does not list: %s" % ", ".join(extra))
    return doc
