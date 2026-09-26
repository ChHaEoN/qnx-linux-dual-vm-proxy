"""The read-count test (Phase 3b / A6, 2026-09-26): the report on synthetic rounds where the step is
the extra read(), where it is the frame's size, and where the read counts or a connection do not
match the design; the endpoint's modes and the image; and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "reads_report.py")
HARNESS = os.path.join(GC, "run-reads.sh")
SRC = os.path.join(HERE, "..", "ipc-test", "qnx-server-net")
BUILD = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor", "ifs-reads.build")
BASH = shutil.which("bash")
ARMS = ["Gd64", "Gd96", "Gg64", "Gg96", "Gs64", "Gd1024", "Gd1280", "Gd1536", "Gg1024", "Gg1280", "Gg1536",
        "Bd64", "Bd96", "Bg64", "Bg96", "Bs64"]
PORT = {"d": 7120, "g": 7121, "s": 7122}
MODE = {"d": "default", "g": "greedy", "s": "split"}
K, N, WARM = 16, 1000, 200


def designed_reads(arm):
    mode, size = arm[1], int(arm[2:])
    if mode == "g":
        return 1
    return (2 if mode == "s" else 1) + (1 if size > 64 else 0)


def _run(out, cost=None, reads=designed_reads, drop_line=None):
    """cost(arm, reads) -> us over the path's base."""
    cost = cost or (lambda a, rd: (14.0 if a[0] == "G" else 1.4) * (rd - 1) + 0.005 * (int(a[2:]) - 64)
                    + (10.0 if a == "Gd1280" or a == "Gg1280" else 0.0))
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": N, "k": K, "warmup": WARM}))
    guest, ns = ["noise line", "sweep: reads :7121 greedy frames=3 reads=3"], {p: [] for p in PORT.values()}
    order, counters = [], []
    for r in range(1, K + 1):
        row = ARMS[r % len(ARMS):] + ARMS[:r % len(ARMS)]
        order.append("round %d order: %s" % (r, " ".join(row)))
        level = 2.0 * ((r * 5) % 7)
        for a in row:
            rd = reads(a)
            base = 180.0 if a[0] == "G" else 55.0
            wob = 0.2 * (((r * 11 + len(a)) % 5) - 2)
            summ = {"p50_ms": (base + level + cost(a, designed_reads(a)) + wob) / 1000.0, "n": N, "bad": 0,
                    "rejected_by_monitor": 0, "frame_bytes": int(a[2:])}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": summ}))
            line = "sweep: reads :%d %s frames=%d reads=%d" % (PORT[a[1]], MODE[a[1]], N + WARM, rd * (N + WARM))
            if drop_line != (a, r):
                (guest if a[0] == "G" else ns[PORT[a[1]]]).append(line)
            counters += ["%s_r%d dev before 1 1 1 1" % (a, r), "%s_r%d dev after 2 2 2 2" % (a, r)]
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "guest-console.log").write_text("\n".join(guest) + "\n")
    for p, lines in ns.items():
        (out / ("reads-ns-%d.log" % p)).write_text("\n".join(["sweep: reads :%d x frames=0 reads=0" % p] + lines) + "\n")
    (out / "counters.log").write_text("\n".join(counters) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_a_step_that_is_the_read_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4", "P5"):
        assert "-> HELD" in _line(s, p), s
    assert "reads/frame 2.000" in s and "reads/frame 1.000" in s


def test_a_step_that_is_the_size_refutes_p1_and_p2(tmp_path):
    _run(tmp_path / "o", cost=lambda a, rd: (15.0 if a[0] == "G" and int(a[2:]) > 64 else 0.0))
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P3"), s
    assert "-> REFUTED" in _line(s, "P5"), s


def test_read_counts_off_the_design_void(tmp_path):
    _run(tmp_path / "o", reads=lambda a: 2 if a == "Gg96" else designed_reads(a))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M2") and "Gg96 round" in s and "VOID (M2 failed)" in _line(s, "P1"), s


def test_a_missing_connection_voids(tmp_path):
    _run(tmp_path / "o", drop_line=("Bs64", 3))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M2") and "B :7122: 15 connections" in s, s


def test_the_endpoint_has_the_modes_and_the_image_runs_one_per_port():
    src = open(os.path.join(SRC, "sweep.c"), encoding="utf-8").read()
    for s in ('strcmp(argv[2], "greedy")', 'strcmp(argv[2], "split")',
              'fprintf(stderr, "sweep: reads :%u %s frames=%llu reads=%llu\\n"',
              "The harness greps this line: keep it byte-identical."):
        assert s in src, s
    mk = open(os.path.join(SRC, "Makefile"), encoding="utf-8").read()
    assert "$(READS): sweep.c ../common/frame.h" in mk and "READS := qnx-echo-server-reads" in mk
    build = open(BUILD, encoding="utf-8").read()
    for s in ("/proc/boot/qnx-echo-server-reads 7120 &", "/proc/boot/qnx-echo-server-reads 7121 greedy &",
              "/proc/boot/qnx-echo-server-reads 7122 split &", "/proc/boot/qnx-safety-monitor 7103 stamp &"):
        assert s in build, s
    assert "qnx-echo-server-sweep=" not in build and "/proc/boot/qnx-echo-server-sweep" not in build


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 one read removes the step: Gg96 - Gg64 is within 3 us of 0",
              "P2 two reads make it at 64 B: Gs64 - Gd64 >= +10 us",
              "P3 the step replicates in the default mode: Gd96 - Gd64 >= +10 us",
              "P4 natively an extra read is cheap", "P5 the 1280 B bump replicates",
              "M2 the read counts are the design's", "K=16 rounds in a Williams design"):
        assert s in head, s
    assert "ARMS=(" + " ".join(ARMS) + ")" in body
    assert 'PROBE_FRAME_BYTES="${a:2}" m_probe' in body
