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

ANY FRAME IS ASKED ABOUT, digit or not. The grammar forces a digit, so a scene
with none gets a low confidence and a REJECT (confidence-below-threshold). That
is still a claim, and so still life: liveness is not correctness.

--check LOG CONSOLE judges a finished run by seq, not by time (the console has
no clock): every claim has its "client done" line and its verdict on the
console; and for every gap in the claim stream -- a camera away, or anything
else -- a gap of at least the deadline has exactly one MISS naming the claim
before it and one RESTORED naming the claim after, and a shorter one has
neither. Gaps within 100 ms of the deadline are reported, not judged.

Needs OpenCV only to stream (python3-opencv; the board's system python3 has it).
"""
import argparse
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vlm_client as vc  # noqa: E402
import vlm_request  # noqa: E402

SCRATCH = "/dev/shm/camera-claim.png"
AMBIGUOUS_S = 0.1


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


def stream(a):
    import cv2
    log = open(a.log, "a")
    t0 = time.monotonic()

    def emit(rec):
        rec["t"] = round(time.monotonic() - t0, 3)
        log.write(json.dumps(rec) + "\n")
        log.flush()
        print(json.dumps(rec), flush=True)

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
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = g.shape
            s = min(h, w)
            g = g[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
            cv2.imwrite(SCRATCH, cv2.resize(g, (a.size, a.size), interpolation=cv2.INTER_AREA))
            try:
                r = vlm_request.ask(a.server, SCRATCH)
            except vlm_request.Unclassifiable as e:
                emit({"event": "unclassifiable", "why": str(e)[:120]})
                continue
            f = vc.claim_fields(r)
            seq += 1
            t_send = time.monotonic() - t0
            got = vc.exchange(a.host, a.port, vc.pack(f, seq))
            t_reply = time.monotonic() - t0
            v, why = got[vc.HEADER + 6], got[vc.HEADER + 7]
            emit({"event": "claim", "seq": seq, "cls": f["cls"], "conf": f["conf"], "model_us": f["total_us"],
                  "verdict": "ACCEPT" if v == 0 else "REJECT", "reason": vc.REASONS.get(why, str(why)),
                  "t_send": round(t_send, 3), "t_reply": round(t_reply, 3)})
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
    rows.append("%d claims (%d ACCEPT, %d REJECT), %d camera outage(s) logged, %d gap(s) >= the deadline"
                % (len(claims), sum(c["verdict"] == "ACCEPT" for c in claims),
                   sum(c["verdict"] == "REJECT" for c in claims),
                   sum(r["event"] in ("camera-lost", "camera-absent") for r in recs), max(0, len(want_miss) - 1)))
    return rows, bad


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
    a = ap.parse_args(argv)
    if a.check:
        rows, bad = check(a.log, a.check, a.deadline_ms / 1000.0, a.opened_in_silence)
        print("\n".join(rows + ["FAILED " + b for b in bad]))
        print("PASS" if not bad else "FAIL: %d problem(s)" % len(bad))
        return 1 if bad else 0
    return stream(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
