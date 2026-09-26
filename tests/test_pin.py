"""The placement test (Phase 3b / A6, 2026-09-27): the report on synthetic runs where pinning io-sock
makes two vCPUs behave as one, where it changes nothing, and where a console line or a benchmark is
off; the two images; and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "pin_report.py")
HARNESS = os.path.join(GC, "run-pin.sh")
MON = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor")
BASH = shutil.which("bash")
K, N, WARM = 12, 1000, 200
FR = N + WARM


def _run(out, r2=None, drop_timing=None, bench_fail=None):
    r2 = r2 or {"U2": 17.0, "P2": 12.0, "U1": 12.0}
    base = {"U2": 184.0, "P2": 180.0, "U1": 176.0}
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": N, "k": K, "warmup": WARM}))
    for r in range(1, K + 1):
        for c in ("U2", "P2", "U1"):
            con = ["noise", "sweep: reads :7120 default frames=3 reads=3",
                   "sweep: timing :7120 default frames=3 r2_n=0 r2_p50_ns=-1 w_p50_ns=30000 svc_p50_ns=30500"]
            for mode, port, reads in (("d", 7120, 1), ("s", 7122, 2)):
                rtt = base[c] + (r2[c] + 0.5 if mode == "s" else 0.0) + 0.2 * (r % 3)
                s = {"p50_ms": rtt / 1000.0, "n": N, "bad": 0, "rejected_by_monitor": 0, "frame_bytes": 64}
                (out / ("lat-%s%s64_r%d.json" % (c, mode, r))).write_text(json.dumps({"summary": s}))
                con.append("sweep: reads :%d %s frames=%d reads=%d" % (port, "default" if mode == "d" else "split", FR, reads * FR))
                if drop_timing != (c, mode, r):
                    two = mode == "s"
                    con.append("sweep: timing :%d %s frames=%d r2_n=%d r2_p50_ns=%d w_p50_ns=%d svc_p50_ns=%d"
                               % (port, "default" if mode == "d" else "split", FR, FR if two else 0,
                                  int(r2[c] * 1000) if two else -1, 29000, int((29.5 + (r2[c] if two else 0)) * 1000)))
            (out / ("console-%s_r%d.log" % (c, r))).write_text("\n".join(con) + "\n")
            bl = ["op %s regime spaced n 300 p10_ns 1000 p50_ns %d p90_ns 3000 mean_ns 2000" % (o, v)
                  for o, v in (("kcall", 420), ("zero", 2800), ("msg", 2500), ("msgx", 15700), ("sock", 7000))]
            if bench_fail == (c, r):
                bl.append("fail sock tight errno 5")
            bl.append("done")
            (out / ("bench-%s_r%d.txt" % (c, r))).write_text("\n".join(bl) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_pinning_that_makes_two_vcpus_one_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_pinning_that_changes_nothing_refutes_p1_p2_p3(tmp_path):
    _run(tmp_path / "o", r2={"U2": 17.0, "P2": 17.0, "U1": 12.0})
    s = _report(tmp_path / "o")
    for p in ("P1", "P2", "P3"):
        assert "-> REFUTED" in _line(s, p), s
    assert "-> HELD" in _line(s, "P4"), s


def test_a_missing_timing_line_or_a_failed_benchmark_voids(tmp_path):
    _run(tmp_path / "a", drop_timing=("P2", "s", 4))
    s = _report(tmp_path / "a")
    assert "-> FAILED" in _line(s, "M2") and "VOID" in _line(s, "P1"), s
    _run(tmp_path / "b", bench_fail=("U1", 7))
    s = _report(tmp_path / "b")
    assert "-> FAILED" in _line(s, "M3"), s


def test_the_two_images_differ_in_the_io_sock_line_only():
    a = open(os.path.join(MON, "ifs-pina.build"), encoding="utf-8").read()
    b = open(os.path.join(MON, "ifs-pinb.build"), encoding="utf-8").read()
    for s in ("on -C 0 /proc/boot/qnx-echo-server-timed 7120 &", "on -C 0 /proc/boot/qnx-echo-server-timed 7122 split &",
              "/proc/boot/qnx-ipcbench 7130 &"):
        assert s in a and s in b, s
    assert "startup.sh=output/build/startup.sh" in a and "startup.sh=output/build/startup-pinio.sh" in b


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 pinning io-sock shortens the second read: r2(P2s64) - r2(U2s64) <= -3 us.",
              "P2 pinned, two vCPUs are one: r2(P2s64) - r2(U1s64) within 3 us of 0.",
              "P3 the round trip follows: (P2s64 - P2d64) - (U2s64 - U2d64) <= -3 us.",
              "P4 on one vCPU the extra read is still long: r2(U1s64) >= 8 us.",
              "Nothing was timed.", "M2 every arm's connection printed its reads and timing"):
        assert s in head, s
    assert "ARMS=(U2d64 U2s64 P2d64 P2s64 U1d64 U1s64)" in body and 'SMP="${SMPC[$c]}"' in body
