"""Where one guest read() goes (Phase 3b / A6, 2026-09-26): the report on synthetic traces and
rounds where the extra read costs two blocked wake-ups on two vCPUs and nothing on one, where one
vCPU does not help, and where the read counts are off; and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "readpath_report.py")
HARNESS = os.path.join(GC, "run-readpath.sh")
BASH = shutil.which("bash")
ARMS = ("2d64", "2s64", "1d64", "1s64")
PORT = {"d64": 7120, "s64": 7122}
K, N, WARM = 12, 500, 100


def _bp(path, blocked, exchanges=20):
    """A reduced trace: per exchange a request, the virtio-net line, `blocked` blocked halt ends
    (the first is V), the transmit notify and the reply."""
    lines, t = [], 1.0
    for _ in range(exchanges):
        lines.append("%.6f 1 X 130" % t)
        lines.append("%.6f 1 I 45 1 o" % (t + 5e-6))
        for j in range(blocked):
            lines.append("%.6f 1 K wait 1000 v%d" % (t + (15 + 10 * j) * 1e-6, j % 2))
        lines.append("%.6f 1 W m v0" % (t + 100e-6))
        lines.append("%.6f 0 R 130" % (t + 110e-6))
        t += 0.002
    open(path, "w").write("\n".join(lines) + "\n")


def _run(out, cost=None, blocked=None, reads=None):
    cost = cost or {"2d64": 0.0, "2s64": 16.0, "1d64": -6.0, "1s64": -4.0}
    blocked = blocked or {"2d64": 3, "2s64": 5, "1d64": 1, "1s64": 1}
    reads = reads or {"d64": 1, "s64": 2}
    out.mkdir()
    for r in range(1, K + 1):
        level = 2.0 * ((r * 5) % 7)
        for c in "21":
            con = []
            for m in ("d64", "s64"):
                a = c + m
                wob = 0.3 * (((r * 7 + len(a) + int(c)) % 5) - 2)
                s = {"p50_ms": (180.0 + level + cost[a] + wob) / 1000.0, "n": N, "bad": 0, "rejected_by_monitor": 0}
                (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
                _bp(out / ("bp-%s_r%d.log" % (a, r)), blocked[a])
                con.append("sweep: reads :%d x frames=3 reads=3" % PORT[m])
                con.append("sweep: reads :%d %s frames=%d reads=%d" % (PORT[m], "default" if m == "d64" else "split",
                                                                       N + WARM, reads[m] * (N + WARM)))
            (out / ("console-smp%s_r%d.log" % (c, r))).write_text("\n".join(con) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), str(N), str(WARM)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_two_wake_ups_on_two_vcpus_and_none_on_one_hold_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_one_vcpu_that_does_not_help_refutes_p2_and_equal_wake_ups_refute_p1(tmp_path):
    _run(tmp_path / "o", cost={"2d64": 0.0, "2s64": 16.0, "1d64": -6.0, "1s64": 10.0},
         blocked={"2d64": 3, "2s64": 3, "1d64": 1, "1s64": 1})
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P3"), s


def test_a_partial_and_a_wake_up_on_one_vcpu(tmp_path):
    _run(tmp_path / "o", cost={"2d64": 0.0, "2s64": 16.0, "1d64": -6.0, "1s64": 1.5},
         blocked={"2d64": 3, "2s64": 4, "1d64": 1, "1s64": 2})
    s = _report(tmp_path / "o")
    assert "-> PARTIAL" in _line(s, "P1") and "-> PARTIAL" in _line(s, "P2") and "-> REFUTED" in _line(s, "P4"), s


def test_read_counts_off_the_design_void(tmp_path):
    _run(tmp_path / "o", reads={"d64": 1, "s64": 1})
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M1") and "VOID (M1 failed)" in _line(s, "P1"), s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 (the trace, two vCPUs) 2s64 has 2 more blocked halts in [I, TX] than 2d64",
              "P2 (one vCPU) the extra read is cheap: 1s64 - 1d64, round trip, <= +5 us",
              "P3 (two vCPUs, replication) 2s64 - 2d64, round trip, >= +10 us",
              "P4 (the trace, one vCPU) 1s64 and 1d64 have the same blocked halts",
              "M1 the read counts are the design's", "halt_poll_ns at its default 500000"):
        assert s in head, s
    assert "ARMS=(2d64 2s64 1d64 1s64)" in body and 'PROBE_FRAME_BYTES=64 m_probe' in body
    assert 'SMP="$c"' in body and "THREAD_NAMES=1" in body
