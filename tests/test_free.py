"""The last-byte test (Phase 3b / A6, 2026-09-27): the report on synthetic runs where a second read that
leaves bytes behind is cheap, where it is not, and where a boot's connections do not match its arms;
and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "free_report.py")
HARNESS = os.path.join(GC, "run-free.sh")
BASH = shutil.which("bash")
K, N, WARM = 12, 1000, 200
FR = N + WARM
ARMS = ["U1d64", "U1d96", "U1s64", "U1s96"]
READS = {"U1d64": 1, "U1d96": 2, "U1s64": 2, "U1s96": 3}


def _run(out, r2=None, drop=None):
    r2 = r2 or {"U1d96": 12.6, "U1s64": 12.8, "U1s96": 7.0}
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": N, "k": K, "warmup": WARM}))
    order = []
    for r in range(1, K + 1):
        row = ARMS[r % 4:] + ARMS[:r % 4]
        order.append("round %d order: %s" % (r, " ".join(row)))
        con = ["noise", "sweep: reads :7120 default frames=3 reads=3"]
        for a in row:
            rr = r2.get(a, -0.001)
            rtt = 172.0 + (0 if a == "U1d64" else rr + 0.5) + (12.0 if a == "U1s96" else 0.0) + 0.2 * (r % 3)
            s = {"p50_ms": rtt / 1000.0, "n": N, "bad": 0, "rejected_by_monitor": 0, "frame_bytes": int(a[3:])}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
            port = 7120 if a[2] == "d" else 7122
            name = "default" if a[2] == "d" else "split"
            if drop == (a, r):
                continue
            con.append("sweep: reads :%d %s frames=%d reads=%d" % (port, name, FR, READS[a] * FR))
            con.append("sweep: timing :%d %s frames=%d r2_n=%d r2_p50_ns=%d w_p50_ns=25000 svc_p50_ns=%d"
                       % (port, name, FR, 0 if a == "U1d64" else FR, int(rr * 1000), 26000))
        (out / ("console-U1_r%d.log" % r)).write_text("\n".join(con) + "\n")
    (out / "order.log").write_text("\n".join(order) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_a_cheap_read_that_leaves_bytes_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_a_read_that_costs_the_same_either_way_refutes_p1_p2(tmp_path):
    _run(tmp_path / "o", r2={"U1d96": 12.6, "U1s64": 12.8, "U1s96": 12.7})
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P3"), s


def test_a_missing_connection_voids(tmp_path):
    _run(tmp_path / "o", drop=("U1s96", 5))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M2") and "round 5 :7122" in s and "VOID (M2 failed)" in _line(s, "P1"), s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 a second read that leaves bytes behind is cheaper: r2(s96) - r2(s64) <= -3 us.",
              "P2 it is as cheap as a loopback read: r2(s96) <= 8.5 us.",
              "P3 two second reads that both take the last bytes cost the same", "M2 every arm's connection printed"):
        assert s in head, s
    assert "ARMS=(U1d64 U1d96 U1s64 U1s96)" in body and 'PROBE_FRAME_BYTES="${SIZE[$2]}" m_probe' in body
