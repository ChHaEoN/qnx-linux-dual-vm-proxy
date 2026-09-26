"""What one guest call costs, by kind (Phase 3b / A6, 2026-09-26): the report on synthetic runs where
io-sock holds the cost, where the message pass does, and where a run failed; the bench's source and
image; and the harness's header."""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "ipcbench_report.py")
HARNESS = os.path.join(GC, "run-ipcbench.sh")
SRC = os.path.join(HERE, "..", "ipc-test", "qnx-ipcbench", "ipcbench.c")
BUILD = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor", "ifs-bench.build")
BASH = shutil.which("bash")
K = 12


def _run(out, guest=None, fail=None):
    guest = guest or {"clock": 0.3, "kcall": 0.6, "zero": 2.5, "msg": 2.8, "msgx": 9.0, "sock": 16.0}
    native = {"clock": 0.1, "kcall": 0.3, "zero": 0.5, "sock": 1.8}
    out.mkdir()
    for r in range(1, K + 1):
        for side, vals in (("G", guest), ("N", native)):
            lines = []
            for op, v in vals.items():
                for reg in ("tight", "spaced"):
                    w = v * (1.2 if reg == "spaced" else 1.0) + 0.05 * (r % 3)
                    ns = int(w * 1000)
                    lines.append("op %s regime %s n 500 p10_ns %d p50_ns %d p90_ns %d mean_ns %d" % (op, reg, ns - 50, ns, ns + 400, ns + 20))
            if fail == (side, r):
                lines.append("fail zero spaced errno 5")
            lines.append("done")
            (out / ("bench-%s_r%d.txt" % (side, r))).write_text("\n".join(lines) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_an_io_sock_cost_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_a_costly_message_pass_refutes_p1_p2_and_a_cheap_socket_refutes_p3(tmp_path):
    _run(tmp_path / "o", guest={"clock": 0.3, "kcall": 0.6, "zero": 14.0, "msg": 14.0, "msgx": 20.0, "sock": 6.0})
    s = _report(tmp_path / "o")
    for p in ("P1", "P2", "P3"):
        assert "-> REFUTED" in _line(s, p), s
    assert "-> HELD" in _line(s, "P4"), s


def test_a_failed_op_voids(tmp_path):
    _run(tmp_path / "o", fail=("G", 5))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M1") and "VOID (M1 failed)" in _line(s, "P1"), s


def test_the_bench_times_the_second_call_and_the_image_starts_it():
    src = open(SRC, encoding="utf-8").read()
    for s in ("long long t0 = now_ns();\n        int rc = op->call();\n        long long t1 = now_ns();",
              'fprintf(o, "op %s regime %s n %d p10_ns %lld p50_ns %lld p90_ns %lld mean_ns %lld\\n",',
              "MsgSend(coid[i], s, sizeof s, r, sizeof r)", "ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)1u);"):
        assert s in src, s
    build = open(BUILD, encoding="utf-8").read()
    assert "/proc/boot/qnx-ipcbench 7130 &" in build and "/proc/boot/qnx-safety-monitor 7103 stamp &" in build


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 the guest's message pass is cheap: msg, spaced, <= 5 us.",
              "P2 a read served by procnto is cheap: zero, spaced, <= 5 us.",
              "P3 an io-sock read is not: sock, spaced, >= 10 us.",
              "P4 a kernel call is cheap: kcall, spaced, <= 2 us.",
              "it prints no timing", "M1 every round has both sides' results"):
        assert s in head, s
    assert 'WARMUP=0' in body and '"$BENCH_BIN" local run "$N" "$GAP_US" "$rot"' in body
