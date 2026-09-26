"""The frame-size sweep (Phase 3b / A6, 2026-09-26): the report on synthetic rounds where the round
trip grows linearly, where it steps at 256 B or at one segment, and where a check fails; the
endpoint's source and build; and the harness's header."""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
REPORT = os.path.join(GC, "sweep_report.py")
HARNESS = os.path.join(GC, "run-sweep.sh")
SRC = os.path.join(HERE, "..", "ipc-test", "qnx-server-net")
BUILD = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor", "ifs-sweep.build")
BASH = shutil.which("bash")
SIZES = (64, 96, 256, 512, 768, 1024, 1280, 1536, 1792, 2048)
K, N, WARM = 20, 1000, 200


def _run(out, g=None, b=None, drop=None, wrong_size=False, pkts=1):
    """g, b: functions S -> extra us over 64 B on each path; each round adds its own level and a
    small wobble, as a boot and a round would."""
    g = g or (lambda s: 0.004 * (s - 64))
    b = b or (lambda s: 0.002 * (s - 64))
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": N, "k": K, "warmup": WARM}))
    lines = []
    for r in range(1, K + 1):
        level = 3.0 * ((r * 7) % 5)
        for x, f, base in (("G", g, 190.0), ("B", b, 60.0)):
            for s in SIZES:
                tag = "%s%d_r%d" % (x, s, r)
                if drop == tag:
                    continue
                wob = 0.3 * (((r * 13 + s) % 7) - 3) / 3.0
                summ = {"p50_ms": (base + level + f(s) + wob) / 1000.0, "n": N, "bad": 0, "rejected_by_monitor": 0,
                        "frame_bytes": 64 if (wrong_size and tag == "G512_r3") else s}
                (out / ("lat-%s.json" % tag)).write_text(json.dumps({"summary": summ}))
                ex = N + WARM
                p = pkts if s > 1448 else 1
                lines.append("%s dev before 100 100 1000 1000" % tag)
                lines.append("%s dev after %d %d %d %d" % (tag, 100 + p * ex, 100 + p * ex, 1000 + ex * (s + 66 * p),
                                                             1000 + ex * (s + 66 * p)))
    (out / "counters.log").write_text("\n".join(lines) + "\n")


def _report(out, expected="as committed"):
    src = open(REPORT, encoding="utf-8").read()
    if expected != "as committed":
        src, n = re.subn(r"^STEP_EXPECTED = \w+ ", "STEP_EXPECTED = %s " % expected, src, count=1, flags=re.M)
        assert n == 1
    p = out.parent / ("report-%s.py" % out.name)
    p.write_text(src, encoding="utf-8")
    r = subprocess.run([sys.executable, str(p), str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


def test_a_linear_cost_holds_p1_and_p2_and_no_step(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o", expected=False)
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s
    sg = float(s.split("slope G below one segment: ")[1].split()[0])
    sb = float(s.split("slope B below one segment: ")[1].split()[0])
    assert abs(sg - 4.0) < 0.2 and abs(sb - 2.0) < 0.2, s


def test_a_256_byte_step_refutes_p1(tmp_path):
    _run(tmp_path / "o", g=lambda s: 0.004 * (s - 64) + (8.0 if s >= 256 else 0.0))
    s = _report(tmp_path / "o", expected=False)
    assert "-> REFUTED" in _line(s, "P1"), s


def test_equal_slopes_or_a_steep_one_refute_p2(tmp_path):
    _run(tmp_path / "a", g=lambda s: 0.002 * (s - 64))
    assert "-> REFUTED" in _line(_report(tmp_path / "a", expected=False), "P2")
    _run(tmp_path / "b", g=lambda s: 0.012 * (s - 64), b=lambda s: 0.002 * (s - 64))
    assert "-> REFUTED" in _line(_report(tmp_path / "b", expected=False), "P2")


def test_a_step_at_one_segment_is_scored_whichever_way_was_predicted(tmp_path):
    _run(tmp_path / "o", g=lambda s: 0.004 * (s - 64) + (12.0 if s > 1448 else 0.0), pkts=2)
    s_yes = _report(tmp_path / "o", expected=True)
    s_no = _report(tmp_path / "o", expected=False)
    assert "-> HELD" in _line(s_yes, "P3") and "-> REFUTED" in _line(s_no, "P3"), s_yes + s_no
    assert "2.00/ 2.00" in s_yes, s_yes           # packets per exchange above one segment
    assert "-> REFUTED" in _line(s_yes, "P4"), s_yes
    assert "NOT SCORED" in _line(_report(tmp_path / "o", expected=None), "P3")


def test_the_committed_prediction_is_no_step(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "want |median| <= 5" in _line(s, "P3") and "-> HELD" in _line(s, "P3"), s


def test_a_missing_arm_or_a_wrong_size_voids(tmp_path):
    _run(tmp_path / "a", drop="B768_r5")
    s = _report(tmp_path / "a", expected=False)
    assert "-> FAILED" in _line(s, "M1") and "VOID" in _line(s, "P1"), s
    _run(tmp_path / "b", wrong_size=True)
    s = _report(tmp_path / "b", expected=False)
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P2"), s


def test_the_interval_is_the_widest_95_percent_one(tmp_path):
    sys.path.insert(0, GC)
    try:
        import importlib
        rep = importlib.import_module("sweep_report")
    finally:
        sys.path.pop(0)
    lo, hi, cov = rep.interval(list(range(1, 21)))
    assert (lo, hi) == (6, 15) and abs(cov - 0.9586) < 1e-3
    lo, hi, cov = rep.interval(list(range(1, 13)))
    assert (lo, hi) == (3, 10) and abs(cov - 0.9614) < 1e-3


def test_the_endpoint_is_its_own_program_and_leaves_the_old_one_alone():
    src = open(os.path.join(SRC, "sweep.c"), encoding="utf-8").read()
    assert "The harness greps this line: keep it byte-identical." in src
    assert '"sweep: echo endpoint listening on 0.0.0.0:%u (frames %u..%u bytes, length at [%u..%u])\\n"' in src
    mk = open(os.path.join(SRC, "Makefile"), encoding="utf-8").read()
    assert "$(SWEEP): sweep.c ../common/frame.h" in mk and "$(BIN): server.c ../common/frame.h ../common/frame_io.h" in mk
    build = open(BUILD, encoding="utf-8").read()
    assert "/proc/boot/qnx-echo-server-sweep 7120 &" in build
    assert "[perms=555] qnx-echo-server-sweep=E:/Project/qnx-linux-dual-vm-proxy/ipc-test/qnx-server-net/qnx-echo-server-sweep" in build
    assert "qnx-safety-monitor-stamp" in build and "/proc/boot/qnx-safety-monitor 7103 stamp &" in build


def test_the_harness_parses_and_states_its_rule_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("S = 64 96 256 512 768 1024 1280 1536 1792 2048 B", "K=20 rounds in a Williams design",
              "It is not to be amended", "The owner asked for this run", "d_X(S) = p50(X_S) - p50(X_64)",
              "What this does NOT test", "tx-tcp-segmentation on",
              "P1 no step below one segment, on either path", "P2 the per-byte cost is small and larger through the guest",
              "P3 no step at one segment on the guest path", "P4 no segmentation on the guest path"):
        assert s in head, s
    assert "PREDICTIONS-HERE" not in head, "the prediction has not been written in"
    assert 'PROBE_FRAME_BYTES="${a:1}" m_probe' in body
    assert 'BANNER="sweep: echo endpoint listening on 0.0.0.0:$PORT (frames 64..4096 bytes, length at [62..63])"' in body
