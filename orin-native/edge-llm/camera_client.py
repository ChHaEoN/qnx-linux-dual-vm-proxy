#!/usr/bin/env python3
"""camera_client.py -- the liveness deadline's end-to-end demo (OD14): a USB
camera on L4T, SmolVLM reading each frame, every answer a kind-1 claim to the
deadline-mode monitor (ifs-live.bin, TCP 7102). Run by camera-demo.sh.

Phase 3b / A6. The claim stream is the camera's: a frame, the model, the claim,
back to back. Unplug the camera and the stream stops at its source, so two
seconds later the monitor prints LIVENESS MISS on the guest console; plug it
back and the next claim prints LIVENESS RESTORED. That is the fault the
deadline exists for: a Compute side whose perception input has died while its
process lives on.

NO FRAME IS KEPT. Each frame is cropped to its centre square, turned grey,
shrunk to --size pixels and written to one scratch file under /dev/shm for
llama-server to read; the next frame overwrites it and exit deletes it. The log
keeps what each claim carried -- digit, confidence, times, verdict -- and
nothing of the picture.

ANY FRAME IS ASKED ABOUT, digit or not. The grammar forces a digit regardless
of the scene; it does not establish that the answer is correct or uncertain.
A rejected claim still counts as life: liveness is not correctness.

--check LOG CONSOLE judges a finished run by seq, not by time (the console has
no clock): every claim has its "client done" line and its verdict on the
console; and for every gap in the claim stream -- a camera away, or anything
else -- a gap of at least the deadline has exactly one MISS naming the claim
before it and one RESTORED naming the claim after, and a shorter one has
neither. Gaps within 100 ms of the deadline are reported, not judged.

--frames DIR, THE FILE SOURCE (SDV plan Phase 7, WP9): frames from a set of
simulated CARLA frames in place of the camera, which is then never opened.
Only a labelled set is read (frames.json: format 1, simulated true, generator
carla, a licence; every file listed with its sha256, a 64x64 8-bit grey PNG,
nothing else in the directory, no git work tree around it); anything else is
refused before the log is opened. The frames go in the set's order, one per
--frame-interval seconds (a slow one is never caught up), once or with --loop
until --seconds, each read with cv2.imread and put through the same lines as a
camera frame into the same scratch file. Each is logged as a "frame" record;
without --dry its claim follows as from the camera. --dry asks no model, makes
no claim and opens no connection: the frame path alone. Once means the whole
set: a single pass that --seconds ends before its last frame is logged as a
"cut" record (the frames read, of how many) and exits 1. The set is only read:
the scratch stays the one image file this writes, and a frame whose bytes change
after the set was read, that can no longer be read, or that cv2 cannot read or
write to the scratch stops the run with the refusal line and exit 2, before
that frame is logged. A simulated frame is not a camera, and a verdict on one
says nothing about perception.

Needs OpenCV only to stream (python3-opencv; the board's system python3 has it;
on the PC, the dry run's venv from requirements-dry.lock).
"""
import argparse
import glob
import hashlib
import json
import math
import os
import re
import stat
import struct
import sys
import time
import zlib
from typing import NamedTuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vlm_client as vc  # noqa: E402
import vlm_request  # noqa: E402

SCRATCH = "/dev/shm/camera-claim.png"
AMBIGUOUS_S = 0.1

# The frame set: its manifest, its files' names, and each frame 64x64 8-bit grey.
FRAMES_JSON = "frames.json"
FRAME_FILE = re.compile(r"frame-(\d{6})\.png\Z")
SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
FRAME_SIDE = 64
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class FramesRefused(Exception):
    """A frame set the file source will not read, or a frame it could not carry to the scratch (changed or gone under
    the run, unreadable, its scratch not written); the message says why."""


class Frame(NamedTuple):
    i: int          # the step whose camera image it is
    file: str
    path: str
    sha256: str


def png_problem(data):
    """None when `data` is a PNG of the set's form -- IHDR (64x64, 8-bit grey, not interlaced), one or more IDAT, IEND,
    every CRC right, the image data exactly 64 rows of a filter byte and 64 pixels -- else what is wrong."""
    if data[:8] != PNG_SIGNATURE:
        return "no PNG signature"
    pos, kinds, idat, ihdr = 8, [], [], b""
    while pos < len(data):
        if pos + 12 > len(data):
            return "truncated chunk"
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if pos + 12 + n > len(data):
            return "truncated chunk"
        body = data[pos + 8:pos + 8 + n]
        if zlib.crc32(kind + body) & 0xFFFFFFFF != struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])[0]:
            return "bad CRC in %r" % kind
        kinds.append(kind)
        if kind == b"IHDR":
            ihdr = body
        elif kind == b"IDAT":
            idat.append(body)
        pos += 12 + n
        if kind == b"IEND":
            break
    if pos != len(data):
        return "bytes after IEND"
    if len(kinds) < 3 or kinds[0] != b"IHDR" or kinds[-1] != b"IEND" or set(kinds[1:-1]) != {b"IDAT"}:
        return "chunks are not IHDR, IDAT..., IEND"
    if len(ihdr) != 13 or struct.unpack(">IIBBBBB", ihdr) != (FRAME_SIDE, FRAME_SIDE, 8, 0, 0, 0, 0):
        return "IHDR is not 64x64, 8-bit grey, not interlaced"
    want = FRAME_SIDE * (FRAME_SIDE + 1)
    z = zlib.decompressobj()
    try:
        raw = z.decompress(b"".join(idat), want + 1)
    except zlib.error:
        return "IDAT does not inflate"
    if len(raw) != want or not z.eof or z.unconsumed_tail or z.unused_data or any(raw[r] > 4 for r in range(0, len(raw), FRAME_SIDE + 1)):
        return "image data is not 64 rows of 64 pixels"
    return None


def _work_tree(path):
    """The first of `path` and its ancestors, as given and with links resolved, that holds a .git; else None."""
    for d in (os.path.abspath(path), os.path.realpath(path)):
        while True:
            if os.path.lexists(os.path.join(d, ".git")):
                return d
            up = os.path.dirname(d)
            if up == d:
                break
            d = up
    return None


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_frames(path):
    """The frames of a labelled simulated set, in its listed order; FramesRefused otherwise. Reads
    only: nothing in the set is written, moved or removed."""
    if not os.path.isdir(path):
        raise FramesRefused("%s is not a directory" % path)
    tree = _work_tree(path)
    if tree is not None:
        raise FramesRefused("the set is inside a git work tree (%s holds .git)" % tree)
    mf = os.path.join(path, FRAMES_JSON)
    if not os.path.isfile(mf):
        raise FramesRefused("no %s" % FRAMES_JSON)
    try:
        with open(mf, encoding="utf-8") as f:
            doc = json.load(f)
    except (ValueError, UnicodeDecodeError):
        doc = None
    if not isinstance(doc, dict):
        raise FramesRefused("%s is not a JSON object" % FRAMES_JSON)
    if type(doc.get("format")) is not int or doc["format"] != 1:
        raise FramesRefused("format is not 1")
    if doc.get("simulated") is not True:
        raise FramesRefused("simulated is not true: an unlabelled set")
    if doc.get("generator") != "carla":
        raise FramesRefused("generator is not carla")
    if not isinstance(doc.get("licence"), str) or not doc["licence"].strip():
        raise FramesRefused("no licence")
    listed = doc.get("frames")
    if not isinstance(listed, list) or not listed:
        raise FramesRefused("no frames listed")
    frames, seen = [], set()
    for k, e in enumerate(listed):
        m = FRAME_FILE.match(e.get("file", "")) if isinstance(e, dict) and isinstance(e.get("file"), str) else None
        if m is None or type(e.get("i")) is not int or not isinstance(e.get("sha256"), str) or not SHA256_HEX.match(e["sha256"]):
            raise FramesRefused("%s's entry %d is not {file: frame-NNNNNN.png, i: <int>, sha256: <64 hex>}" % (FRAMES_JSON, k))
        if int(m.group(1)) != e["i"]:
            raise FramesRefused("%s does not name step %d" % (e["file"], e["i"]))
        if e["file"] in seen:
            raise FramesRefused("%s is listed twice" % e["file"])
        seen.add(e["file"])
        frames.append(Frame(e["i"], e["file"], os.path.join(path, e["file"]), e["sha256"]))
    names = set(os.listdir(path))
    for fr in frames:
        if fr.file not in names:
            raise FramesRefused("%s is missing" % fr.file)
    extra = sorted(names - seen - {FRAMES_JSON})
    if extra:
        raise FramesRefused("%s is in the set but not listed" % extra[0])
    for fr in frames:
        if not stat.S_ISREG(os.lstat(fr.path).st_mode):
            raise FramesRefused("%s is not a regular file" % fr.file)
        with open(fr.path, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() != fr.sha256:
            raise FramesRefused("%s: sha256 differs from %s's" % (fr.file, FRAMES_JSON))
        why = png_problem(data)
        if why:
            raise FramesRefused("%s is not a 64x64 8-bit grey PNG (%s)" % (fr.file, why))
    return frames


def open_camera(cv2):
    """The first /dev/video* that opens AND yields a frame: a UVC camera also
    registers a metadata node that opens but never delivers one."""
    for dev in sorted(glob.glob("/dev/video*")):
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ok, _f = cap.read()
            if ok:
                return cap, dev
        cap.release()
    return None, None


def to_scratch(cv2, frame, size):
    """The claim's image, the one image file a run writes: the frame grey, its centre square, `size` pixels a side. Returns
    imwrite's result: the file source stops on False; the camera path ignores it, as it always did."""
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    s = min(h, w)
    g = g[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
    return cv2.imwrite(SCRATCH, cv2.resize(g, (size, size), interpolation=cv2.INTER_AREA))


def claim(a, emit, t0, seq):
    """Ask the model about the scratch and send its answer as a kind-1 claim. Returns the last seq used."""
    try:
        r = vlm_request.ask(a.server, SCRATCH)
    except vlm_request.Unclassifiable as e:
        emit({"event": "unclassifiable", "why": str(e)[:120]})
        return seq
    f = vc.claim_fields(r)
    seq += 1
    t_send = time.monotonic() - t0
    got = vc.exchange(a.host, a.port, vc.pack(f, seq))
    t_reply = time.monotonic() - t0
    v, why = got[vc.HEADER + 6], got[vc.HEADER + 7]
    emit({"event": "claim", "seq": seq, "cls": f["cls"], "conf": f["conf"], "model_us": f["total_us"],
          "verdict": "ACCEPT" if v == 0 else "REJECT", "reason": vc.REASONS.get(why, str(why)),
          "t_send": round(t_send, 3), "t_reply": round(t_reply, 3)})
    return seq


def from_frames(a, cv2, emit, t0, frames):
    """The file source: each frame of the set, in order, one per --frame-interval (a frame starts no sooner than one
    interval after the one before, and never early to make up for a slow one), once or with --loop, until --seconds.
    Returns 0, or 1 when --seconds ends a single pass (no --loop) before its last frame: the whole set was asked for, so
    a "cut" record says how many of its frames were read. A frame changed, gone or unreadable, or a scratch cv2 could
    not write, stops the run with FramesRefused before that frame is logged."""
    seq, last = a.seq, None
    try:
        while True:
            for k, fr in enumerate(frames):
                now = time.monotonic()
                start = now if last is None else max(now, last + a.frame_interval)
                if start - t0 >= a.seconds:
                    if a.loop:
                        return 0
                    emit({"event": "cut", "frames": k, "of": len(frames)})
                    return 1
                if start > now:
                    time.sleep(start - now)
                last = time.monotonic()
                try:
                    changed = _sha256(fr.path) != fr.sha256
                except OSError as e:
                    raise FramesRefused("%s cannot be read: %s" % (fr.file, e.strerror or e))
                if changed:
                    raise FramesRefused("%s changed after the set was read" % fr.file)
                frame = cv2.imread(fr.path, cv2.IMREAD_COLOR)
                if frame is None:
                    raise FramesRefused("cv2 could not read %s" % fr.file)
                if not to_scratch(cv2, frame, a.size):
                    raise FramesRefused("cv2 could not write the scratch for %s" % fr.file)
                emit({"event": "frame", "i": fr.i, "file": fr.file})
                if not a.dry:
                    seq = claim(a, emit, t0, seq)
            if not a.loop:
                return 0
    finally:
        try:
            os.unlink(SCRATCH)
        except FileNotFoundError:
            pass


def stream(a, frames=None):
    import cv2
    log = open(a.log, "a")
    t0 = time.monotonic()

    def emit(rec):
        rec["t"] = round(time.monotonic() - t0, 3)
        log.write(json.dumps(rec) + "\n")
        log.flush()
        print(json.dumps(rec), flush=True)

    if frames is not None:
        return from_frames(a, cv2, emit, t0, frames)
    cap, seq, absent = None, a.seq, False
    ever_open, lost, outages, reopened_at = False, False, 0, None
    try:
        while time.monotonic() - t0 < a.seconds:
            # --outages N: the run waits for the owner. It ends once N outages
            # have ended and --tail seconds of claims have followed the last.
            if a.outages and outages >= a.outages and time.monotonic() - reopened_at >= a.tail:
                emit({"event": "done", "outages": outages})
                break
            if cap is None:
                cap, dev = open_camera(cv2)
                if cap is None:
                    if not absent:
                        emit({"event": "camera-absent"})
                        absent = True
                    lost = lost or ever_open
                    time.sleep(0.2)
                    continue
                emit({"event": "camera-open", "device": dev})
                absent = False
                if lost:                    # an outage has ended: the camera was open before
                    outages += 1
                    reopened_at = time.monotonic()
                    lost = False
                ever_open = True
            ok, frame = cap.read()
            if not ok:
                emit({"event": "camera-lost"})
                lost = True
                cap.release()
                cap = None
                continue
            to_scratch(cv2, frame, a.size)
            seq = claim(a, emit, t0, seq)
    finally:
        if cap is not None:
            cap.release()
        try:
            os.unlink(SCRATCH)
        except FileNotFoundError:
            pass
    return 0


def check(log_path, console_path, deadline_s, opened_in_silence=False):
    """The run judged by seq against the guest console. Returns (rows, failures).
    opened_in_silence: the monitor had already reported a silence when the run
    began (camera-demo.sh reads that from the console before its mark), so the
    run's first claim must print RESTORED; on a boot never armed it must not."""
    recs = [json.loads(x) for x in open(log_path) if x.strip()]
    claims = [r for r in recs if r["event"] == "claim"]
    console = open(console_path, errors="replace").read().replace("\0", "").replace("\r", "")
    done = re.findall(r"client done: seen=(\d+) accepted=(\d+) rejected=(\d+)", console)
    rejects = {int(m.group(1)): m.group(2) for m in re.finditer(r"REJECT seq=(\d+) .*?reason=([a-z-]+)", console)}
    misses = [int(m.group(1)) for m in re.finditer(r"LIVENESS MISS: no claim for \d+ ms since seq=(\d+)", console)]
    restored = [int(m.group(1)) for m in re.finditer(r"LIVENESS RESTORED: seq=(\d+) ", console)]
    rows, bad = [], []

    if len(done) != len(claims):
        bad.append("%d claims sent, %d 'client done' lines on the console" % (len(claims), len(done)))
    for c, (seen, acc, rej) in zip(claims, done):
        want = ("1", "1", "0") if c["verdict"] == "ACCEPT" else ("1", "0", "1")
        if (seen, acc, rej) != want or (c["verdict"] == "REJECT") != (c["seq"] in rejects) \
                or (c["seq"] in rejects and rejects[c["seq"]] != c["reason"]):
            bad.append("seq %d: client %s/%s, console seen=%s acc=%s rej=%s %s"
                       % (c["seq"], c["verdict"], c["reason"], seen, acc, rej, rejects.get(c["seq"], "")))

    want_miss, want_restored = [], []
    if opened_in_silence and claims:
        want_restored.append(claims[0]["seq"])
        rows.append("the run opened in a reported silence -> RESTORED at seq=%d" % claims[0]["seq"])
    for prev, nxt in zip(claims, claims[1:]):
        gap = nxt["t_send"] - prev["t_reply"]
        if abs(gap - deadline_s) < AMBIGUOUS_S:
            rows.append("gap after seq %d: %.2f s, within %.1f s of the deadline -- not judged"
                        % (prev["seq"], gap, AMBIGUOUS_S))
            misses = [m for m in misses if m != prev["seq"]]
            restored = [r for r in restored if r != nxt["seq"]]
            continue
        if gap >= deadline_s:
            want_miss.append(prev["seq"])
            want_restored.append(nxt["seq"])
            rows.append("gap after seq %d: %.2f s -> MISS since seq=%d, RESTORED at seq=%d"
                        % (prev["seq"], gap, prev["seq"], nxt["seq"]))
    if claims:
        want_miss.append(claims[-1]["seq"])          # the run's own trailing silence
    if misses != want_miss:
        bad.append("MISS lines name seqs %s; the claim stream calls for %s" % (misses, want_miss))
    if restored != want_restored:
        bad.append("RESTORED lines name seqs %s; the claim stream calls for %s" % (restored, want_restored))
    # An outage logs camera-lost and then camera-absent, so count them by the
    # reopen that ends each one (the first open is the run's start), plus one
    # still open at the end.
    events = [r["event"] for r in recs if r["event"] in ("camera-open", "camera-lost", "camera-absent")]
    outages = max(0, events.count("camera-open") - 1) + (1 if events and events[-1] != "camera-open" else 0)
    rows.append("%d claims (%d ACCEPT, %d REJECT), %d camera outage(s), %d gap(s) >= the deadline"
                % (len(claims), sum(c["verdict"] == "ACCEPT" for c in claims),
                   sum(c["verdict"] == "REJECT" for c in claims), outages, max(0, len(want_miss) - 1)))
    return rows, bad


def _interval(text):
    try:
        v = float(text)
    except ValueError:
        v = math.nan
    if not (v > 0 and math.isfinite(v)):
        raise argparse.ArgumentTypeError("not a positive, finite number of seconds: %r" % text)
    return v


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="192.168.100.10")
    ap.add_argument("--port", type=int, default=7102)
    ap.add_argument("--server", default="http://127.0.0.1:8089")
    ap.add_argument("--size", type=int, default=64, help="the square the frame is shrunk to, pixels")
    ap.add_argument("--seconds", type=float, default=240.0, help="the run's length, or with --outages its limit")
    ap.add_argument("--outages", type=int, default=0,
                    help="end once this many camera outages have ended (0: run for --seconds)")
    ap.add_argument("--tail", type=float, default=10.0, help="seconds of claims to keep after the last outage")
    ap.add_argument("--seq", type=int, default=5000, help="the first claim's seq is this plus one")
    ap.add_argument("--log", required=True)
    ap.add_argument("--check", metavar="CONSOLE", help="judge a finished run's LOG against this console slice")
    ap.add_argument("--deadline-ms", type=int, default=2000)
    ap.add_argument("--opened-in-silence", action="store_true",
                    help="--check: the monitor had reported a silence before the run began")
    ap.add_argument("--frames", metavar="DIR",
                    help="read a labelled set of simulated frames instead of the camera, which is then never opened")
    ap.add_argument("--frame-interval", type=_interval, default=1.0, help="--frames: seconds from one frame to the next")
    ap.add_argument("--loop", action="store_true",
                    help="--frames: start the set again after its last frame, until --seconds (without it: one whole pass, "
                         "which fails if --seconds cuts it short)")
    ap.add_argument("--dry", action="store_true",
                    help="--frames: ask no model, make no claim, open no connection; log each frame only")
    a = ap.parse_args(argv)
    if (a.dry or a.loop) and a.frames is None:
        ap.error("--dry and --loop need --frames")
    if a.frames is not None and a.outages:
        ap.error("--outages counts camera outages: there is no camera with --frames")
    if a.check:
        rows, bad = check(a.log, a.check, a.deadline_ms / 1000.0, a.opened_in_silence)
        print("\n".join(rows + ["FAILED " + b for b in bad]))
        print("PASS" if not bad else "FAIL: %d problem(s)" % len(bad))
        return 1 if bad else 0
    try:
        return stream(a, read_frames(a.frames) if a.frames is not None else None)
    except FramesRefused as e:
        print("camera_client: --frames %s refused: %s" % (a.frames, e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
