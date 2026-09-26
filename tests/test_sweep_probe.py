"""The frame-size sweep's probe option (Phase 3b / A6, 2026-09-26): latency_probe.py --frame-bytes
against a stand-in for qnx-echo-server-sweep that follows sweep.c's wire rule (the length is a
little-endian uint16 in bytes 62..63, 0 meaning 64); without the option, nothing changes."""
import json
import os
import socket
import struct
import subprocess
import sys
import threading

HERE = os.path.dirname(__file__)
PROBE = os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "latency_probe.py")
SWEEP_C = os.path.join(HERE, "..", "ipc-test", "qnx-server-net", "sweep.c")


def _read(c, n):
    b = b""
    while len(b) < n:
        x = c.recv(n - len(b))
        if not x:
            return None
        b += x
    return b


def _server(mode="sweep"):
    """A TCP endpoint on a free port: 'sweep' echoes sweep.c's way; 'fixed' is a 64-byte echo
    (the monitor's framing); 'flip' corrupts the last byte of every frame over 64 bytes."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    lens = []

    def run():
        c, _ = srv.accept()
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        while True:
            h = _read(c, 64)
            if h is None:
                break
            n = 64 if mode == "fixed" else (struct.unpack_from("<H", h, 62)[0] or 64)
            body = h + (_read(c, n - 64) or b"") if n > 64 else h
            lens.append(n)
            if mode == "flip" and n > 64:
                body = body[:-1] + bytes([body[-1] ^ 1])
            c.sendall(body)
        c.close()
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1], lens


def _probe(port, tmp_path, *extra, n=30):
    out = tmp_path / "lat.json"
    r = subprocess.run([sys.executable, PROBE, "--host", "127.0.0.1", "--port", str(port), "--n", str(n),
                        "--warmup", "5", "--interval-ms", "0", "--timeout-s", "3", "--out", str(out), *extra],
                       capture_output=True, text=True, timeout=60)
    return r, (json.load(open(out)) if out.exists() else None)


def test_the_default_is_unchanged(tmp_path):
    port, lens = _server()
    r, body = _probe(port, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "frame_bytes" not in body["summary"] and set(lens) == {64}


def test_every_size_is_sent_whole_and_checked(tmp_path):
    for size in (64, 96, 1500, 2048):
        port, lens = _server()
        r, body = _probe(port, tmp_path, "--frame-bytes", str(size))
        assert r.returncode == 0, r.stdout + r.stderr
        assert body["summary"]["frame_bytes"] == size and set(lens) == {size}, (size, set(lens))
        assert body["summary"]["n"] == 30


def test_a_corrupted_echo_is_broken_not_timed(tmp_path):
    port, _ = _server("flip")
    r, body = _probe(port, tmp_path, "--frame-bytes", "512")
    assert r.returncode != 0 and body is None
    assert "differs from what was sent" in r.stdout, r.stdout


def test_a_fixed_frame_endpoint_stalls_the_arm(tmp_path):
    # 96, not a multiple of 64: a plain 64-byte echo passes whole multiples through unchanged
    port, _ = _server("fixed")
    r, body = _probe(port, tmp_path, "--frame-bytes", "96", n=3)
    assert r.returncode != 0 and body is None


def test_the_option_is_tcp_only_and_bounded(tmp_path):
    for extra in (("--frame-bytes", "63"), ("--frame-bytes", "4097"), ("--frame-bytes", "256", "--proto", "udp")):
        r = subprocess.run([sys.executable, PROBE, "--host", "127.0.0.1", "--port", "9", *extra],
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 2 and "--frame-bytes needs" in r.stderr, (extra, r.stderr)


def test_the_probe_and_the_endpoint_agree_on_the_wire():
    src = open(SWEEP_C, encoding="utf-8").read()
    assert "#define SWEEP_LEN_OFF    (FRAME_TOTAL_BYTES - 2u)" in src
    assert "#define SWEEP_MAX_BYTES  4096u" in src
    assert "len = FRAME_TOTAL_BYTES;" in src          # 0 means 64
    text = open(PROBE, encoding="utf-8").read()
    assert "SWEEP_LEN_OFF = FRAME_TOTAL - 2" in text and "SWEEP_MAX = 4096" in text
