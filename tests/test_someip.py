"""The SOME/IP arm (Phase 3b / A6, 2026-09-27, OD12): latency_probe.py's someip, someipu, vsomeip and
vsomeipu transports against stand-in servers, and the guest's SOME/IP monitor (ipc-test/qnx-someip)
built natively and spoken to over loopback. The native build needs gcc on Linux: it runs in CI."""
import json
import os
import shutil
import socket
import stat
import struct
import subprocess
import sys
import threading
import time

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
PROBE = os.path.join(GC, "latency_probe.py")
IPC = os.path.join(HERE, "..", "ipc-test")
sys.path.insert(0, GC)
import latency_probe as lp  # noqa: E402

HDR = struct.Struct(">HHIHHBBBB")


def req(payload, svc=0x5AFE, meth=1, sess=7, proto=1, iface=1, mtype=0, client=0x0100):
    return HDR.pack(svc, meth, 8 + len(payload), client, sess, proto, iface, mtype, 0) + payload


def answer(msg, mtype=0x80, rc=0, sess=None, payload=None):
    """What a correct server says to msg: the ids back, a RESPONSE, the payload judged (verdict 0)."""
    svc, meth, _l, client, s, proto, iface, _t, _rc = HDR.unpack_from(msg)
    body = msg[16:] if payload is None else payload
    return HDR.pack(svc, meth, 8 + len(body), client, s if sess is None else sess, proto, iface, mtype, rc) + body


def _udp_server(behaviour):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(0.2)
    stop = threading.Event()

    def serve():
        n = 0
        while not stop.is_set():
            try:
                data, peer = srv.recvfrom(4096)
            except OSError:
                continue
            n += 1
            for out in behaviour(n, data):
                srv.sendto(out, peer)
    threading.Thread(target=serve, daemon=True).start()
    return srv, srv.getsockname()[1], stop


def _tcp_server(behaviour):
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen(1)
    stop = threading.Event()

    def serve():
        c, _ = ls.accept()
        n, buf = 0, b""
        while not stop.is_set():
            d = c.recv(4096)
            if not d:
                break
            buf += d
            while len(buf) >= 8 and len(buf) >= 8 + struct.unpack_from(">I", buf, 4)[0]:
                m = 8 + struct.unpack_from(">I", buf, 4)[0]
                n += 1
                for out in behaviour(n, buf[:m]):
                    c.sendall(out)
                buf = buf[m:]
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    return ls, ls.getsockname()[1], stop


def _probe(port, proto, tmp_path, *extra, n=40, env=None):
    out = tmp_path / "lat.json"
    cmd = [sys.executable, PROBE, "--host", "127.0.0.1", "--port", str(port), "--proto", proto,
           "--n", str(n), "--warmup", "5", "--interval-ms", "0", "--timeout-s", "1", "--tag", "s_r1",
           "--out", str(out)] + list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    return r, out


# ---- the wire helpers

def test_the_session_is_never_zero_and_wraps():
    assert lp.sip_session(1) == 1 and lp.sip_session(0xFFFF) == 0xFFFF and lp.sip_session(0x10000) == 1


def test_wrap_and_unwrap_round_trip_and_refuse_a_wrong_answer():
    frame = lp.build_frame(9)
    w = lp.sip_wrap(frame, 9)
    assert len(w) == 80 and HDR.unpack_from(w)[:9] == (0x5AFE, 1, 72, 0x0100, 9, 1, 1, 0, 0)
    assert lp.sip_unwrap(answer(w), 9) == (frame, "")
    assert "ERROR, return code 0x03" in lp.sip_unwrap(answer(w, mtype=0x81, rc=3, payload=b""), 9)[1]
    assert "expected" in lp.sip_unwrap(answer(w, sess=10), 9)[1]
    assert "short" in lp.sip_unwrap(b"\x00" * 10, 9)[1]


# ---- the probe against stand-ins

@pytest.mark.parametrize("proto", ["someip", "someipu"])
def test_the_probe_times_a_clean_someip_arm(tmp_path, proto):
    seen = []

    def ok(n, m):
        seen.append(m)
        return [answer(m)]
    srv, port, stop = (_udp_server if proto == "someipu" else _tcp_server)(ok)
    r, out = _probe(port, proto, tmp_path)
    stop.set()
    srv.close()
    assert r.returncode == 0, r.stdout + r.stderr
    s = json.loads(out.read_text())["summary"]
    assert s["proto"] == proto and s["n"] == 40 and s["rejected_by_monitor"] == 0
    assert all(len(m) == 80 and m[:2] == b"\x5a\xfe" for m in seen) and len(seen) == 45


@pytest.mark.parametrize("bad,why", [
    (lambda m: answer(m, mtype=0x81, rc=9, payload=b""), "SOME/IP ERROR, return code 0x09"),
    (lambda m: answer(m, sess=HDR.unpack_from(m)[4] + 1), "expected"),
])
def test_a_wrong_someip_answer_breaks_the_arm(tmp_path, bad, why):
    srv, port, stop = _udp_server(lambda n, m: [bad(m) if n == 10 else answer(m)])
    r, out = _probe(port, "someipu", tmp_path)
    stop.set()
    srv.close()
    assert r.returncode == lp.EXIT_BROKEN and why in r.stdout and not out.exists(), r.stdout + r.stderr


def test_a_rejected_claim_is_counted_not_timed(tmp_path):
    def judge(n, m):
        p = bytearray(m[16:])
        p[16 + 6] = 1 if n == 12 else 0
        return [answer(m, payload=bytes(p))]
    srv, port, stop = _udp_server(judge)
    r, out = _probe(port, "someipu", tmp_path)
    stop.set()
    srv.close()
    assert r.returncode == 0, r.stdout + r.stderr
    s = json.loads(out.read_text())["summary"]
    assert s["rejected_by_monitor"] == 1 and s["n"] == 39


# ---- the vsomeip wrapper, with a stand-in someip_vprobe

needs_posix = pytest.mark.skipif(os.name != "posix", reason="the stand-in client is a shell script")


def _fake_vprobe(tmp_path, body):
    p = tmp_path / "someip_vprobe"
    p.write_text("#!/bin/sh\necho 'a vsomeip log line'\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, SOMEIP_VPROBE=str(p))
    return env


@needs_posix
def test_the_vsomeip_arm_is_built_from_the_clients_samples_and_its_own_scheduling(tmp_path):
    rtt = [150000 + 10 * i for i in range(40)]
    res = {"rtt_ns": rtt, "send_ns": [2000000 * i for i in range(40)], "rejected": 0,
           "sched": {"sched_policy": "SCHED_OTHER", "sched_priority": 0, "cpu_affinity": [4]},
           "vsomeip": "3.4.10"}
    env = _fake_vprobe(tmp_path, "echo '%s'" % json.dumps(res))
    r, out = _probe(1, "vsomeipu", tmp_path, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    s = json.loads(out.read_text())["summary"]
    assert s["proto"] == "vsomeipu" and s["n"] == 40 and s["cpu_affinity"] == [4] and s["vsomeip"] == "3.4.10"
    assert abs(s["p50_ms"] - 0.150195) < 1e-3 and abs(s["period_us"]["p50"] - 2000.0) < 1e-6


@needs_posix
def test_a_vsomeip_client_error_breaks_the_arm(tmp_path):
    env = _fake_vprobe(tmp_path, "echo '{\"error\": \"sample 3: not an E_OK response\"}'; exit 5")
    r, out = _probe(1, "vsomeip", tmp_path, env=env)
    assert r.returncode == lp.EXIT_BROKEN and "not an E_OK response" in r.stdout and not out.exists(), r.stdout


def test_the_vsomeip_arm_needs_its_client(tmp_path):
    env = dict(os.environ, SOMEIP_VPROBE="")
    r, out = _probe(1, "vsomeip", tmp_path, env=env)
    assert r.returncode == 2 and "SOMEIP_VPROBE" in r.stdout


def test_the_vsomeip_arm_refuses_options_its_client_cannot_honour(tmp_path):
    r, _ = _probe(1, "vsomeip", tmp_path, "--claim", "vlm")
    assert r.returncode == 2 and "sends the mnist claim" in r.stderr


# ---- the guest's SOME/IP monitor, built natively

@pytest.fixture(scope="module")
def someip_server(tmp_path_factory):
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        pytest.skip("needs gcc on Linux: runs in CI's tooling job")
    d = tmp_path_factory.mktemp("someip")
    exe = str(d / "someip")
    c = os.path.join(IPC, "common")
    subprocess.run([gcc, "-std=gnu99", "-Wall", "-Wextra", "-Wformat=2", "-Werror", "-O2", "-pthread", "-I", c,
                    "-o", exe, os.path.join(IPC, "qnx-someip", "someip.c"), os.path.join(c, "shm_map_posix.c"),
                    os.path.join(c, "ivshm_client.c")], check=True, capture_output=True, text=True)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    log = open(d / "server.log", "w")
    p = subprocess.Popen([exe, str(port)], stdout=log, stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    yield port, d / "server.log"
    p.terminate()
    p.wait(timeout=5)
    log.close()


def _claim(conf=95):
    f = bytearray(lp.build_frame(21))
    f[16 + 1] = conf
    return bytes(f)


def _tcp_exchange(port, data, want):
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    s.sendall(data)
    got = b""
    while len(got) < want:
        d = s.recv(4096)
        if not d:
            break
        got += d
    s.close()
    return got


def test_the_server_judges_a_claim_as_the_monitor_does(someip_server):
    port, _ = someip_server
    got = _tcp_exchange(port, req(_claim(95), sess=3) + req(_claim(10), sess=4), 160)
    h1, h2 = HDR.unpack_from(got), HDR.unpack_from(got, 80)
    assert h1 == (0x5AFE, 1, 72, 0x0100, 3, 1, 1, 0x80, 0) and h2[4] == 4 and h2[7] == 0x80
    assert got[16 + 16 + 6:16 + 16 + 8] == b"\x00\x00"           # accept, reason ok
    assert got[96 + 16 + 6:96 + 16 + 8] == b"\x01\x03"           # reject, conf-low: monitor.c's rule
    assert got[16:16 + 16] == _claim()[:16] and got[96:96 + 16] == _claim()[:16]


@pytest.mark.parametrize("msg,code", [
    (req(bytes(64), svc=0x1234), 0x02),
    (req(bytes(64), meth=2), 0x03),
    (req(bytes(64), proto=2), 0x07),
    (req(bytes(64), iface=2), 0x08),
    (req(bytes(63)), 0x09),
])
def test_the_server_answers_a_bad_request_with_its_error_code(someip_server, msg, code):
    port, _ = someip_server
    got = _tcp_exchange(port, msg, 16)
    h = HDR.unpack_from(got)
    assert len(got) == 16 and h[2] == 8 and h[7] == 0x81 and h[8] == code, h


def test_udp_answers_every_message_of_a_datagram_in_one_and_skips_no_return(someip_server):
    port, _ = someip_server
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.settimeout(3)
    u.sendto(req(_claim(), sess=5) + req(_claim(), sess=6, mtype=0x01) + req(bytes(64), meth=9, sess=7),
             ("127.0.0.1", port))
    d = u.recv(4096)
    u.close()
    assert len(d) == 80 + 16
    assert HDR.unpack_from(d)[4] == 5 and HDR.unpack_from(d, 80)[4] == 7 and HDR.unpack_from(d, 80)[8] == 0x03


def test_the_probe_runs_a_clean_arm_against_the_server(someip_server, tmp_path):
    port, _ = someip_server
    for proto in ("someip", "someipu"):
        r, out = _probe(port, proto, tmp_path, n=100)
        assert r.returncode == 0, r.stdout + r.stderr
        s = json.loads(out.read_text())["summary"]
        assert s["proto"] == proto and s["n"] == 100 and s["rejected_by_monitor"] == 0


def test_a_broken_length_closes_the_connection(someip_server):
    port, log = someip_server
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    s.sendall(HDR.pack(0x5AFE, 1, 4, 0x0100, 1, 1, 1, 0, 0))
    assert s.recv(16) == b""
    s.close()
    time.sleep(0.2)
    assert "tcp client done (bad length)" in log.read_text()


# ---- the report on synthetic runs, and the harness's header

REPORT = os.path.join(GC, "someip_report.py")
HARNESS = os.path.join(GC, "run-someip.sh")
BASE_P50 = {"T": 180.0, "U": 175.0, "ST": 181.0, "SU": 176.0, "CT": 170.0, "CU": 166.0, "VT": 200.0, "VU": 195.0}
ARM_PROTO = {"T": "tcp", "U": "udp", "ST": "someip", "SU": "someipu", "CT": "csomeip", "CU": "csomeipu",
             "VT": "vsomeip", "VU": "vsomeipu"}


def _someip_run(out, p50=None, k=16, drop_console=None, vsomeip_ct="none"):
    p50 = dict(BASE_P50, **(p50 or {}))
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": 1000, "warmup": 200, "pin": {"probe": 4}}))
    for r in range(1, k + 1):
        for a, v in p50.items():
            s = {"p50_ms": (v + 0.3 * (r % 3)) / 1000.0, "p99_ms": (v + 40) / 1000.0, "n": 1000, "bad": 0,
                 "rejected_by_monitor": 0, "proto": ARM_PROTO[a], "cpu_affinity": [4]}
            if a in ("VT", "VU"):
                s["vsomeip"] = "3.4.10"
            elif a in ("CT", "CU"):
                s["vsomeip"] = None if vsomeip_ct == "none" else vsomeip_ct
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
        lines = ["someip: tcp client done (eof): seen=1 accepted=1 rejected=0 errors=0 dropped=0"]
        for _ in ("ST", "CT", "VT"):
            if drop_console == r:
                continue
            lines.append("someip: tcp client done (eof): seen=1200 accepted=1200 rejected=0 errors=0 dropped=0")
        (out / ("console-A_r%d.log" % r)).write_text("\n".join(lines) + "\n")


def _someip_report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_a_free_header_and_a_modest_vsomeip_cost_hold_everything(tmp_path):
    _someip_run(tmp_path / "o")
    s = _someip_report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_a_costly_header_refutes_p1_and_a_heavy_vsomeip_refutes_p3(tmp_path):
    _someip_run(tmp_path / "o", {"SU": 185.0, "VT": 240.0})
    s = _someip_report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> HELD" in _line(s, "P2") and "-> REFUTED" in _line(s, "P3"), s


def test_a_cheap_vsomeip_refutes_p2(tmp_path):
    _someip_run(tmp_path / "o", {"VU": 170.0})
    s = _someip_report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P2"), s


def test_a_missing_guest_connection_voids(tmp_path):
    _someip_run(tmp_path / "o", drop_console=5)
    s = _someip_report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M3") and "round 5" in s and "VOID (M3 failed)" in _line(s, "P1"), s


def test_a_c_arm_that_ran_vsomeip_voids(tmp_path):
    _someip_run(tmp_path / "o", vsomeip_ct="3.4.10")
    s = _someip_report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P2"), s


def test_the_someip_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    bash = shutil.which("bash")
    if bash is not None:
        r = subprocess.run([bash, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run", "P1 ST - T and SU - U are each within 3 us of 0.",
              "P2 VT - CT >= +10 us and VU - CU >= +10 us.",
              "P3 VT - CT <= 0.25 x the median of CT's p50, and VU - CU <= 0.25 x the median of CU's p50.",
              "only its exit codes, error lines and the guest's per-connection counts were",
              "M3 every boot's guest console has one"):
        assert s in head, s
    assert 'ARM_PROTOS="U=udp ST=someip SU=someipu CT=csomeip CU=csomeipu VT=vsomeip VU=vsomeipu"' in body
    assert 'm_probe "$OUT" "$a"_r"$r" "$GUEST" "${PORT[$a]}" "" "${PROTO[$a]}"' in body


# ---- the follow-up (run-someip0.sh): vsomeip without its nPDU retention

REPORT0 = os.path.join(GC, "someip0_report.py")
HARNESS0 = os.path.join(GC, "run-someip0.sh")
P50_0 = {"CT": 170.0, "VT": 5235.0, "VT0": 195.0, "CU": 150.0, "VU": 5215.0, "VU0": 172.0}
PROTO0 = {"CT": "csomeip", "VT": "vsomeip", "VT0": "vsomeip", "CU": "csomeipu", "VU": "vsomeipu", "VU0": "vsomeipu"}
NPDU0 = {"debounce-time-request": "0", "debounce-time-response": "0", "max-retention-time-request": "0",
         "max-retention-time-response": "0"}


def _someip0_run(out, p50=None, k=12, npdu_on=("tcp0", "udp0")):
    p50 = dict(P50_0, **(p50 or {}))
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": 1000, "warmup": 200, "pin": {"probe": 4}}))
    for name in ("tcp", "udp", "tcp0", "udp0"):
        cfg = {"unicast": "192.168.100.1", "services": []}
        if name in npdu_on:
            cfg["npdu-default-timings"] = dict(NPDU0)
        (out / ("vsomeip-%s.json" % name)).write_text(json.dumps(cfg))
    for r in range(1, k + 1):
        for a, v in p50.items():
            s = {"p50_ms": (v + 0.2 * (r % 3)) / 1000.0, "p99_ms": (v + 40) / 1000.0, "n": 1000, "bad": 0,
                 "rejected_by_monitor": 0, "proto": PROTO0[a], "cpu_affinity": [4],
                 "vsomeip": None if a in ("CT", "CU") else "3.4.10"}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
        line = "someip: tcp client done (eof): seen=1200 accepted=1200 rejected=0 errors=0 dropped=0"
        (out / ("console-A_r%d.log" % r)).write_text("\n".join([line] * 3) + "\n")


def _report0(out):
    r = subprocess.run([sys.executable, REPORT0, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_the_retention_explained_and_a_small_vsomeip_hold_everything(tmp_path):
    _someip0_run(tmp_path / "o")
    s = _report0(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_a_retention_that_explains_nothing_refutes_p1(tmp_path):
    _someip0_run(tmp_path / "o", {"VT0": 5230.0})
    s = _report0(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P3"), s


def test_a_free_vsomeip_refutes_p2(tmp_path):
    _someip0_run(tmp_path / "o", {"VU0": 152.0})
    s = _report0(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P3"), s


def test_a_configuration_without_the_zero_timings_voids(tmp_path):
    _someip0_run(tmp_path / "o", npdu_on=("tcp0",))
    s = _report0(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M4") and "VOID (M4 failed)" in _line(s, "P1"), s


def test_the_someip0_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    bash = shutil.which("bash")
    if bash is not None:
        r = subprocess.run([bash, "-n", HARNESS0], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS0, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run", "P1 is not blind",
              "P1 VT - VT0 and VU - VU0 each lie in [4800, 5200] us.", "P2 VT0 - CT >= +10 us and VU0 - CU >= +10 us.",
              "M4 the four configurations are as described"):
        assert s in head, s
    assert 'declare -A CFG=([CT]=tcp [VT]=tcp [VT0]=tcp0 [CU]=udp [VU]=udp [VU0]=udp0)' in body
    assert '"max-retention-time-request": "0"' in body
