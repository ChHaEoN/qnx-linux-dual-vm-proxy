"""The probe's --arrival option and the library's PROBE_ARRIVAL/PROBE_SEED
(Phase 3b / A6, 2026-09-24, the arrival test): exponential sleeps with the set
mean, seeded and repeatable, recorded; the default unchanged."""
import json
import os
import socket
import subprocess
import sys
import threading

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
PROBE = os.path.join(GC, "latency_probe.py")


def _udp_echo():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                data, peer = srv.recvfrom(4096)
            except OSError:
                continue
            srv.sendto(data, peer)
    threading.Thread(target=serve, daemon=True).start()
    return srv, srv.getsockname()[1], stop


def _probe(tmp_path, name, *extra):
    srv, port, stop = _udp_echo()
    out = tmp_path / ("%s.json" % name)
    r = subprocess.run([sys.executable, PROBE, "--host", "127.0.0.1", "--port", str(port), "--proto", "udp",
                        "--n", "200", "--warmup", "5", "--timeout-s", "1", "--tag", name, "--out", str(out),
                        *extra], capture_output=True, text=True, timeout=120)
    stop.set()
    srv.close()
    return r, out


def test_the_default_is_unchanged(tmp_path):
    r, out = _probe(tmp_path, "c", "--interval-ms", "1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "arrival" not in json.loads(out.read_text())["summary"]


def test_exponential_sleeps_have_the_set_mean_and_are_recorded(tmp_path):
    r, out = _probe(tmp_path, "e", "--interval-ms", "1", "--arrival", "exp", "--seed", "7")
    assert r.returncode == 0, r.stdout + r.stderr
    a = json.loads(out.read_text())["summary"]["arrival"]
    assert a["kind"] == "exp" and a["seed"] == 7 and a["draws"] == 205       # warm-up included
    s = a["sleep_ms"]
    assert 0.7 < s["mean"] < 1.3, s                   # 205 draws: the mean's sd is ~7%
    assert 0.7 < s["sd"] / s["mean"] < 1.3, s         # an exponential's sd equals its mean
    assert s["p50"] < s["mean"], s                    # right-skewed: median ln2 of the mean


def test_the_same_seed_draws_the_same_sleeps(tmp_path):
    _, o1 = _probe(tmp_path, "s1", "--interval-ms", "0.5", "--arrival", "exp", "--seed", "3")
    _, o2 = _probe(tmp_path, "s2", "--interval-ms", "0.5", "--arrival", "exp", "--seed", "3")
    _, o3 = _probe(tmp_path, "s3", "--interval-ms", "0.5", "--arrival", "exp", "--seed", "4")
    m = [json.loads(o.read_text())["summary"]["arrival"]["sleep_ms"]["mean"] for o in (o1, o2, o3)]
    assert m[0] == m[1] and m[0] != m[2]


def test_exponential_needs_a_mean(tmp_path):
    r, _ = _probe(tmp_path, "z", "--interval-ms", "0", "--arrival", "exp")
    assert r.returncode == 2 and "--arrival exp needs a positive --interval-ms" in r.stderr


# The library's pass-through (PROBE_ARRIVAL, PROBE_SEED) is tested in test_measure_lib.py,
# beside PROBE_STAMPS's, where its bash runner lives.
