#!/usr/bin/env python3
"""vlm_client.py -- the Compute end of the VLM service arm (OD13).

Phase 3b / A6. The successor to ipc-test/compute-client/compute_client.cpp,
the 2026-09-18 TensorRT client: ask a resident llama-server which MNIST digit
an image shows, then send the model's claim across the VM boundary to the QNX
guest's safety monitor as a kind-1 (vlm) frame, and report the verdict.

THE CLAIM IS THE MODEL'S OWN, never fabricated: the digit is the reply, parsed
strictly (vlm_request.py); the confidence is P(answer) at the digit's token
position; the time is llama-server's own. If the model cannot classify, this
exits non-zero and sends nothing.

THE FRAME (monitor.c's header is the authority): kind 1 at payload[24], the
same class/confidence/time slots as the mnist claim, and the vlm fields in
payload[25..47]. The total in [2..5] is the INTEGER SUM of the rounded prompt
and generation times -- the monitor checks that sum exactly, so rounding the
total separately would be rejected as inconsistent, correctly.

--corrupt REASON changes ONE field of a real claim, to show the monitor
refusing it, and says which field and what the model actually answered. It
exists for the demo record; a corrupted claim is never a measurement.

Standard library only.
"""
import os
import socket
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vlm_request  # noqa: E402

FRAME_TOTAL = 64
HEADER = 16
SENTINEL_SEQ = 0xFFFFFFFFFFFFFFFF
KIND_MNIST, KIND_VLM = 0, 1
MODEL_SMOLVLM_500M = 1
VLM_INFER_US_MAX = 1000000        # monitor.c's bound; used only to build the "slow" corruption

REASONS = {
    0: "ok", 1: "class-out-of-range", 2: "confidence-not-a-percentage",
    3: "confidence-below-threshold", 4: "inference-time-implausible",
    5: "claim-kind-unknown", 6: "vlm-model-unbounded", 7: "vlm-time-inconsistent",
}

# Each corruption: what it changes, and the reason the monitor should give.
CORRUPTIONS = {
    "class":     ("claims class 42, outside the label set", 1),
    "conf":      ("claims confidence 101%", 2),
    "conf-low":  ("claims confidence 59%, under CONF_MIN", 3),
    "slow":      ("claims a generation time that puts the total 1 us over the 1 s bound", 4),
    "kind":      ("claims kind 9, which names no claim kind", 5),
    "model":     ("claims model 2, for which the monitor has no measured bound", 6),
    "sum":       ("claims a total 1 us more than prompt_us + gen_us", 7),
    "as-mnist":  ("sends the honest claim as kind 0, the 2026-09-18 CNN contract", 4),
}


def claim_fields(r):
    """The integers a kind-1 frame carries, from a vlm_request.ask() result."""
    prompt_us = int(round(r["prompt_ms"] * 1000.0))
    gen_us = int(round(r["predicted_ms"] * 1000.0))
    return {
        "cls": int(r["answer"]),
        "conf": int(round(r["p_answer"] * 100.0)),
        "prompt_us": prompt_us,
        "gen_us": gen_us,
        "total_us": prompt_us + gen_us,           # the integer sum the monitor checks
        "prompt_n": int(r["prompt_n"]),
        "gen_n": int(r["predicted_n"]),
        "wall_us": int(round(r["wall_ms"] * 1000.0)),
        "mass_ppm": int(round(r["digit_mass"] * 1e6)),
        "kind": KIND_VLM,
        "model": MODEL_SMOLVLM_500M,
    }


def corrupt(f, how):
    """Change exactly one field of a real claim (a copy)."""
    f = dict(f)
    if how == "class":
        f["cls"] = 42
    elif how == "conf":
        f["conf"] = 101
    elif how == "conf-low":
        f["conf"] = 59
    elif how == "slow":
        f["gen_us"] = VLM_INFER_US_MAX + 1 - f["prompt_us"]
        f["total_us"] = f["prompt_us"] + f["gen_us"]
    elif how == "kind":
        f["kind"] = 9
    elif how == "model":
        f["model"] = 2
    elif how == "sum":
        f["total_us"] += 1
    elif how == "as-mnist":
        f["kind"] = KIND_MNIST
    else:
        raise ValueError("unknown corruption %r" % how)
    return f


def pack(f, seq):
    if seq == SENTINEL_SEQ:
        raise ValueError("seq UINT64_MAX is the keepalive sentinel, never a claim")
    frame = bytearray(FRAME_TOTAL)
    struct.pack_into("<QQ", frame, 0, seq, 0)
    p = HEADER
    frame[p + 0] = f["cls"] & 0xFF
    frame[p + 1] = f["conf"] & 0xFF
    struct.pack_into("<I", frame, p + 2, f["total_us"] & 0xFFFFFFFF)
    frame[p + 24] = f["kind"] & 0xFF
    frame[p + 25] = f["model"] & 0xFF
    struct.pack_into("<HHIIII", frame, p + 26,
                     min(f["prompt_n"], 0xFFFF), min(f["gen_n"], 0xFFFF),
                     f["prompt_us"] & 0xFFFFFFFF, f["gen_us"] & 0xFFFFFFFF,
                     min(f["wall_us"], 0xFFFFFFFF), min(f["mass_ppm"], 0xFFFFFFFF))
    return bytes(frame)


def exchange(host, port, frame, timeout_s=10.0):
    with socket.create_connection((host, port), timeout=timeout_s) as s:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.sendall(frame)
        got = b""
        while len(got) < FRAME_TOTAL:
            chunk = s.recv(FRAME_TOTAL - len(got))
            if not chunk:
                raise ConnectionError("short reply (%d bytes)" % len(got))
            got += chunk
    if got[:8] != frame[:8]:
        raise ConnectionError("reply seq does not match the claim's")
    return got


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--host", required=True, help="the QNX guest")
    ap.add_argument("--port", type=int, default=7102, help="the service's monitor instance (ifs-svc: 7102)")
    ap.add_argument("--server", default="http://127.0.0.1:8089", help="the resident llama-server")
    ap.add_argument("--digit", type=int, default=3)
    ap.add_argument("--images", default="/usr/src/tensorrt/data/mnist")
    ap.add_argument("--seq", type=int, default=1)
    ap.add_argument("--corrupt", choices=sorted(CORRUPTIONS), default=None)
    a = ap.parse_args(argv)

    image = "%s/%d.pgm" % (a.images, a.digit)
    try:
        r = vlm_request.ask(a.server, image)
    except vlm_request.Unclassifiable as e:
        print("vlm: cannot classify %s: %s -- nothing sent" % (image, e), file=sys.stderr)
        return 1
    f = claim_fields(r)
    print("vlm: image=%s truth=%d -> class=%d confidence=%.1f%% model_time=%.1f ms "
          "(prompt %.1f + gen %.1f; %d+%d tokens) digit_mass=%.6f" % (
              image, a.digit, f["cls"], r["p_answer"] * 100.0, f["total_us"] / 1000.0,
              f["prompt_us"] / 1000.0, f["gen_us"] / 1000.0, f["prompt_n"], f["gen_n"], r["digit_mass"]))
    if a.corrupt:
        what, want = CORRUPTIONS[a.corrupt]
        f = corrupt(f, a.corrupt)
        print("vlm: --corrupt %s: %s (expect reason %d, %s)" % (a.corrupt, what, want, REASONS[want]))

    try:
        got = exchange(a.host, a.port, pack(f, a.seq))
    except (OSError, ConnectionError) as e:
        print("vlm: exchange with %s:%d failed: %s" % (a.host, a.port, e), file=sys.stderr)
        return 1
    verdict, reason = got[HEADER + 6], got[HEADER + 7]
    print("vlm: QNX safety monitor verdict=%s reason=%s" % (
        "ACCEPT" if verdict == 0 else "REJECT", REASONS.get(reason, "unknown(%d)" % reason)))
    return 0 if verdict == 0 else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
