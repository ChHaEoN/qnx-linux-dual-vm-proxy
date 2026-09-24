"""The thermal-phase test (Phase 3b / A6, 2026-09-24): tjphase_trace.py's reduction,
the classes and scoring run-tjphase.sh fixed before any run, the report end to end
on synthetic rounds (a window that follows the moved poll, and one that stays at the
old phase), and the harness's header."""
import os
import json
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import tjphase_report as tr  # noqa: E402
import tjphase_trace as tt  # noqa: E402

REPORT = os.path.join(GC, "tjphase_report.py")
HARNESS = os.path.join(GC, "run-tjphase.sh")
BASH = shutil.which("bash")

RAW = """# tracer: nop
#
# entries-in-buffer/entries-written: 3/3   #P:6
#
     python3-5000    [004] ..s1.   900.000100: net_dev_xmit: dev=tap-qnx skbaddr=00000000abcdef01 len=130 rc=0
 kworker/u12:1-60    [003] ...1.   900.004000: thermal_temperature: thermal_zone=tj-thermal id=8 temp_prev=45000 temp=45500
 kworker/u12:1-60    [003] ...1.   900.004100: thermal_temperature: thermal_zone=cpu-thermal id=0 temp_prev=44000 temp=44000
"""


def test_reduce_keeps_frames_and_zones_only():
    out, err = tt.reduce(RAW.splitlines(True))
    assert err is None, err
    assert out == ["900.000100 004 X 130", "900.004000 003 T tj-thermal", "900.004100 003 T cpu-thermal"]
    assert "lost events" in tt.reduce(RAW.replace("3/3", "3/4").splitlines(True))[1]
    assert "other than tap-qnx" in tt.reduce(RAW.replace("dev=tap-qnx", "dev=br0").splitlines(True))[1]
    bad = RAW + "  foo-1 [000] d..2. 900.1: sched_switch: prev_comm=foo\n"
    assert "unparsed line" in tt.reduce(bad.splitlines(True))[1]


def test_classes_and_phase():
    P = tr.PERIOD
    assert tr.cdist(1000.0, P - 1000.0) == 2000.0
    ph, spread = tr.old_phase([5000.0, 5000.0 + P, 5200.0 + 2 * P])
    assert abs(ph - 5000.0) < 1e-6 and abs(spread - 200.0) < 1e-6
    assert tr.old_phase([1.0]) == (None, None)
    # FOUND BY THE SMOKE RUN: two reads 1020 ms apart, the first a jiffy late. The phase
    # is the earliest read's, the fire jiffy's, and one jiffy of lag passes M3.
    ph, spread = tr.old_phase([12_000.0, 12_000.0 + P - 4000.0])
    assert abs(ph - 8000.0) < 1e-6 and abs(spread - 4000.0) < 1e-6 and spread <= tr.LATE
    ph, spread = tr.old_phase([P - 1000.0, 2 * P + 1000.0])          # across the cycle's end
    assert abs(ph - (P - 1000.0)) < 1e-6 and abs(spread - 2000.0) < 1e-6
    assert tr.classify(10_000.0, [9_600.0], None, []) == "tj"          # 0.4 ms after a read
    assert tr.classify(9_600.0 - 400.0, [9_600.0], None, []) == "tj"   # 0.4 ms before
    assert tr.classify(9_600.0 - 600.0, [9_600.0], None, []) == "out"
    assert tr.classify(3 * P + 5_000.0 + 5_900.0, [], 5_000.0, []) == "old"
    assert tr.classify(50_000.0, [], 5_000.0, [49_000.0]) == "other"
    assert tr.classify(50_000.0, [49_500.0], 49_000.0, [49_000.0]) == "tj"   # the first match wins


def test_scoring():
    assert tr.score_ratio_high(10.0, 1.0) == "HELD"
    assert tr.score_ratio_high(3.0, 1.0) == "PARTIAL"
    assert tr.score_ratio_high(2.9, 1.0) == "REFUTED"
    assert tr.score_ratio_high(1.0, 0.0) == "HELD" and tr.score_ratio_high(0.0, 0.0) == "REFUTED"
    assert tr.score_quiet(9.99) == "HELD" and tr.score_quiet(10.0) == "REFUTED"


def _run(out, k, follows=True, n=1000, warm=200, seed=5, fixed_ph=None):
    """Requests every 2250 us. tj-thermal is read at a new random phase each round (the
    old phase, 8 ms into the cycle, before the first toggle); the other zones at 768 ms.
    Exchanges starting within 0..5 ms after the SLOW phase take 600 us, the rest 200 us:
    the slow phase is the round's tj read when follows, else the old phase. The fast
    ones carry up to 50 us of noise, so a round's p99 is not simply the fast value."""
    out.mkdir()
    P = tr.PERIOD
    rng = random.Random(seed)
    old = 8_000.0
    base0 = 1_000_000_000.0
    (out / "tp-before.log").write_text("\n".join("%.6f 003 T tj-thermal" % ((base0 - 3 * P + i * P + old - base0 % P) / 1e6)
                                                 for i in range(2)) + "\n")
    for r in range(1, k + 1):
        base = base0 + r * 4 * P
        ph = fixed_ph if fixed_ph is not None else rng.choice([x * 32_000.0 for x in range(4, 20)])
        lines, samples = [], []
        for i in range(warm + n):
            t0 = base + i * 2250.0
            lines.append("%.6f 004 X 130" % (t0 / 1e6))
            if i >= warm:
                slow_ph = ph if follows else old
                d = (t0 - slow_ph) % P
                samples.append(0.6 if d <= 5000.0 else 0.2 + 0.05 * rng.random())
        for m in range(4):
            lines.append("%.6f 003 T tj-thermal" % ((base + m * P + ph - (base % P)) / 1e6))
            lines.append("%.6f 003 T cpu-thermal" % ((base + m * P + 768_000.0 - (base % P)) / 1e6))
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(sorted(lines, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_a_window_that_follows_the_poll_holds_everything(tmp_path):
    _run(tmp_path / "o", 24)
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    assert "P1  the tail follows the moved poll" in s and "-> HELD" in s.split("P1")[1].split("\n")[0], s
    assert "-> HELD" in s.split("P2")[1].split("\n")[0], s
    assert "-> HELD" in s.split("P3")[1].split("\n")[0], s


def test_a_window_that_stays_at_the_old_phase_refutes_p1_and_p3(tmp_path):
    _run(tmp_path / "o", 24, follows=False)
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in s.split("P1")[1].split("\n")[0], s
    assert "-> REFUTED" in s.split("P3")[1].split("\n")[0], s


def test_a_poll_that_did_not_move_voids_p1_and_p3_and_another_k_is_not_scored(tmp_path):
    _run(tmp_path / "o", 24, fixed_ph=8_000.0)            # every round's reads at the old phase
    s = _report(tmp_path / "o")
    assert "moved >= 32 ms away in 0 of 24 rounds" in s and "-> FAILED" in s.split("M3")[1].split("\n")[0], s
    assert "VOID (M3 failed)" in s.split("P1")[1].split("\n")[0] and "VOID (M3 failed)" in s.split("P3")[1], s
    _run(tmp_path / "p", 4)
    assert "not scored (k=4; the prediction is for k=24)" in _report(tmp_path / "p")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("at or above its round's p99 round trip", "tj class's tail rate is >= 10x the out\n#      class's",
              "PARTIAL at 3-10x", "other class's tail rate is\n#      below 10%",
              "old class's tail\n#      rate is below 10%", "every\n#      tj-thermal read is >= 32 ms from it",
              "Scored only at k = 24", "It is not to be amended"):
        assert s in head, s
