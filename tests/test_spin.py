"""The wait test (Phase 3b / A6, 2026-09-27): the report on synthetic runs where waiting shortens the
guest's second read, where it does not, and where a wait was not what was asked; the wait mode in the
endpoint and the image; and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "spin_report.py")
HARNESS = os.path.join(GC, "run-spin.sh")
SRC = os.path.join(HERE, "..", "ipc-test", "qnx-server-net", "sweep.c")
BUILD = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor", "ifs-spin.build")
BASH = shutil.which("bash")
K, N, WARM = 10, 1000, 200
FR = N + WARM
ARM = {"d": (7120, 1, 0), "s0": (7122, 2, 0), "s5": (7123, 2, 5), "s20": (7124, 2, 20), "s50": (7125, 2, 50)}


def _run(out, r2=None, spin_off=None):
    r2 = r2 or {"s0": 13.0, "s5": 11.0, "s20": 7.0, "s50": 6.5}
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": N, "k": K, "warmup": WARM}))
    for r in range(1, K + 1):
        for c in ("U1", "U2"):
            con = ["noise", "sweep: reads :7125 splitw frames=0 reads=1"]
            for a, (port, reads, spin) in ARM.items():
                two = reads == 2
                rr = r2[a] if two else -0.001
                rtt = 180.0 + (rr + 0.5 if two else 0.0) + spin + 0.2 * (r % 3)
                s = {"p50_ms": rtt / 1000.0, "n": N, "bad": 0, "rejected_by_monitor": 0, "frame_bytes": 64}
                (out / ("lat-%s%s_r%d.json" % (c, a, r))).write_text(json.dumps({"summary": s}))
                mode = "default" if a == "d" else ("split" if a == "s0" else "splitw")
                con.append("sweep: reads :%d %s frames=%d reads=%d" % (port, mode, FR, reads * FR))
                con.append("sweep: timing :%d %s frames=%d r2_n=%d r2_p50_ns=%d w_p50_ns=25000 svc_p50_ns=%d"
                           % (port, mode, FR, FR if two else 0, int(rr * 1000), int((25.5 + (rr if two else 0) + spin) * 1000)))
                if spin:
                    got = spin + (7 if spin_off == (c, a, r) else 0.001)
                    con.append("sweep: spin :%d frames=%d spin_us=%d spin_p50_ns=%d" % (port, FR, spin, int(got * 1000)))
            (out / ("console-%s_r%d.log" % (c, r))).write_text("\n".join(con) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_a_wait_that_shortens_the_read_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_a_wait_that_changes_nothing_refutes_everything(tmp_path):
    _run(tmp_path / "o", r2={"s0": 13.0, "s5": 13.0, "s20": 13.0, "s50": 13.0})
    s = _report(tmp_path / "o")
    for p in ("P1", "P2", "P3"):
        assert "-> REFUTED" in _line(s, p), s


def test_a_wait_off_what_was_asked_voids(tmp_path):
    _run(tmp_path / "o", spin_off=("U1", "s20", 3))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M3") and "VOID (M3 failed)" in _line(s, "P1"), s


def test_the_wait_mode_and_the_image():
    src = open(SRC, encoding="utf-8").read()
    for s in ('strcmp(argv[2], "splitw")', "spin_wait(g_spin_us);",
              'fprintf(stderr, "sweep: spin :%u frames=%llu spin_us=%ld spin_p50_ns=%lld\\n",', "#include <time.h>\n"):
        assert s in src, s
    build = open(BUILD, encoding="utf-8").read()
    for s in ("on -C 0 /proc/boot/qnx-echo-server-spin 7120 &", "on -C 0 /proc/boot/qnx-echo-server-spin 7122 split &",
              "on -C 0 /proc/boot/qnx-echo-server-spin 7125 splitw 50 &"):
        assert s in build, s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 on one vCPU a 50 us wait shortens the second read: r2(U1s50) - r2(U1s0) <= -4 us.",
              "P2 on one vCPU, after the wait, the read is as cheap as a loopback read: r2(U1s50) <= 8 us.",
              "P3 on two vCPUs the same: r2(U2s50) - r2(U2s0) <= -4 us.",
              "No read was timed by anyone looking.", "M3 the waits were what was asked"):
        assert s in head, s
    assert "ARMS=(U1d U1s0 U1s5 U1s20 U1s50 U2d U2s0 U2s5 U2s20 U2s50)" in body
    assert 'm_require_balanced_k "$K" "${#MODES[@]}"' in body
