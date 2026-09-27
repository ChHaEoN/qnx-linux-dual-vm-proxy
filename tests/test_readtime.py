"""The extra read timed inside the endpoint (Phase 3b / A6, 2026-09-26): the report on synthetic runs
where the read call holds the cost, where it does not, and where a timing line is off the design;
the timed build's source; and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "readtime_report.py")
HARNESS = os.path.join(GC, "run-readtime.sh")
SRC = os.path.join(HERE, "..", "ipc-test", "qnx-server-net")
BUILD = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor", "ifs-timed.build")
BASH = shutil.which("bash")
ARMS = ["Gd64", "Gd96", "Gs64", "Gg64", "Bd64", "Bs64"]
PORT = {"d": 7120, "g": 7121, "s": 7122}
MODE = {"d": "default", "g": "greedy", "s": "split"}
READS = {"Gd64": 1, "Gg64": 1, "Bd64": 1, "Gd96": 2, "Gs64": 2, "Bs64": 2}
K, N, WARM = 12, 1000, 200


def _run(out, r2_us=13.0, rtt_step=16.0, w_shift=0.0, bad_r2n=None):
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": N, "k": K, "warmup": WARM}))
    order, ns = [], {p: [] for p in PORT.values()}
    guest = ["noise", "sweep: timing :7120 default frames=3 r2_n=0 r2_p50_ns=-1 w_p50_ns=9000 svc_p50_ns=9500"]
    fr = N + WARM
    for r in range(1, K + 1):
        row = ARMS[r % len(ARMS):] + ARMS[:r % len(ARMS)]
        order.append("round %d order: %s" % (r, " ".join(row)))
        level = 2.0 * ((r * 5) % 7)
        for a in row:
            two = READS[a] == 2
            g = a[0] == "G"
            rtt = (180.0 if g else 55.0) + level + ((rtt_step if g else 1.2) if two else 0.0) + 0.1 * (r % 3)
            summ = {"p50_ms": rtt / 1000.0, "n": N, "bad": 0, "rejected_by_monitor": 0, "frame_bytes": int(a[2:])}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": summ}))
            r2 = (r2_us if g else 1.5) if two else -0.001
            w = (9.0 if g else 2.0) + (w_shift if a == "Gs64" else 0.0)
            svc = w + (r2 if two else 0.0) + 0.5
            r2n = fr if two else 0
            if bad_r2n == (a, r):
                r2n = fr - 5
            lines = ["sweep: reads :%d %s frames=%d reads=%d" % (PORT[a[1]], MODE[a[1]], fr, READS[a] * fr),
                     "sweep: timing :%d %s frames=%d r2_n=%d r2_p50_ns=%d w_p50_ns=%d svc_p50_ns=%d"
                     % (PORT[a[1]], MODE[a[1]], fr, r2n, int(r2 * 1000), int(w * 1000), int(svc * 1000))]
            (guest if g else ns[PORT[a[1]]]).extend(lines)
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "guest-console.log").write_text("\n".join(guest) + "\n")
    for p, lines in ns.items():
        (out / ("reads-ns-%d.log" % p)).write_text("\n".join(lines) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_a_cost_inside_the_call_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_a_short_call_refutes_p1_and_p2_and_a_moved_write_refutes_p3(tmp_path):
    _run(tmp_path / "a", r2_us=2.0)
    s = _report(tmp_path / "a")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P4"), s
    _run(tmp_path / "b", w_shift=4.0)
    s = _report(tmp_path / "b")
    assert "-> REFUTED" in _line(s, "P3"), s


def test_a_frame_without_its_second_read_voids(tmp_path):
    _run(tmp_path / "o", bad_r2n=("Gs64", 4))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M3") and "VOID (M3 failed)" in _line(s, "P1"), s


def test_the_timed_build_is_opt_in_and_the_image_runs_it():
    src = open(os.path.join(SRC, "sweep.c"), encoding="utf-8").read()
    assert "#ifdef SWEEP_TIMING" in src and "#define FRAME_BEGIN() ((void)0)" in src
    assert '"sweep: timing :%u %s frames=%llu r2_n=%llu r2_p50_ns=%lld w_p50_ns=%lld svc_p50_ns=%lld\\n"' in src
    mk = open(os.path.join(SRC, "Makefile"), encoding="utf-8").read()
    assert "$(CC) $(TARGET) $(CFLAGS) -DSWEEP_TIMING -o $@ sweep.c $(LDFLAGS)" in mk and "TIMED := qnx-echo-server-timed" in mk
    build = open(BUILD, encoding="utf-8").read()
    for s in ("/proc/boot/qnx-echo-server-timed 7120 &", "/proc/boot/qnx-echo-server-timed 7121 greedy &",
              "/proc/boot/qnx-echo-server-timed 7122 split &"):
        assert s in build, s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 the guest's second read is long", "P2 it shows in the guest's service time",
              "P3 the write does not depend on the read mode", "P4 the round trip replicates",
              "so a native prediction would not be blind", "M3 every arm's connection printed its timing"):
        assert s in head, s
    assert "ARMS=(Gd64 Gd96 Gs64 Gg64 Bd64 Bs64)" in body and "-DSWEEP_TIMING" in body
    assert "lan_default_route" in body
