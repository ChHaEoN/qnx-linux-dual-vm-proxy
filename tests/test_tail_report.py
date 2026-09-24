"""The tail test's scoring (Phase 3b / A6, 2026-09-24): the thresholds run-tail.sh
fixed before any run, the interrupt check, the report end to end on a synthetic
run, and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import tail_report as tr  # noqa: E402

REPORT = os.path.join(GC, "tail_report.py")
HARNESS = os.path.join(GC, "run-tail.sh")
BASH = shutil.which("bash")


@pytest.mark.parametrize("d,want", [
    ([-5.0] * 12, "HELD"),
    ([-20.0] * 9 + [5.0] * 3, "HELD"),
    ([-20.0] * 8 + [5.0] * 4, "PARTIAL"),       # median -20 but only 8/12 below zero
    ([-4.9] * 12, "PARTIAL"),
    ([0.0] * 12, "REFUTED"),
    ([3.0] * 12, "REFUTED"),
])
def test_p1(d, want):
    assert tr.score_p1(d) == want


@pytest.mark.parametrize("d,want", [
    ([-0.1] * 12, "HELD"),
    ([-50.0] * 8 + [10.0] * 4, "HELD"),
    ([-50.0] * 7 + [10.0] * 5, "PARTIAL"),      # median < 0, 7/12
    ([0.0] * 12, "REFUTED"),
])
def test_p2(d, want):
    assert tr.score_p2(d) == want


@pytest.mark.parametrize("m,want", [(3.0, "HELD"), (-3.0, "HELD"), (3.1, "FAILED")])
def test_p3(m, want):
    assert tr.score_p3([m] * 12) == want


def test_m1():
    assert tr.check_m1([0, 1, 2]) and not tr.check_m1([0, 3]) and not tr.check_m1([])
    assert tr.RESTS_ON == {"P1": ("M1",), "P2": ("M1",), "P3": ("M1",)}


def _run(out, k, leak=0):
    out.mkdir()
    shape = {"base": (180.0, 300.0, 600.0), "irq": (180.0, 290.0, 560.0),
             "fifo": (179.5, 280.0, 520.0), "iso": (179.0, 270.0, 480.0)}
    for r in range(1, k + 1):
        for a, (p50, p99, p999) in shape.items():
            s = {"p50_ms": p50 / 1000, "p90_ms": (p50 + 10) / 1000, "p99_ms": p99 / 1000,
                 "p999_ms": p999 / 1000, "max_ms": 2.0, "server_us": {"p99": 0.6}}
            samples = [p50 / 1000] * 2990 + [0.6] * 10
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s, "samples_in_order": samples}))
            fired = leak if a in ("irq", "iso") else 40
            (out / ("irq-%s_r%d.before" % (a, r))).write_text("276: 100 0 0 0 0 0\n126: 50 0 0 0 0 0\n")
            (out / ("irq-%s_r%d.after" % (a, r))).write_text(
                "276: %d 0 0 %d 0 0\n126: 50 0 0 5 0 0\n" % (100 + fired, 0 if a in ("base", "fifo") else 30))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_the_report_scores_h_at_k_12(tmp_path):
    _run(tmp_path / "o", 12)
    s = _report(tmp_path / "o")
    assert "M1 moved irqs on cores 0-2 in irq/iso arm-rounds: max 0 (want <= 2); base median 40 -> ok" in s
    assert "P1  iso - base, p99    median   -30.0 us" in s and s.count("-> HELD") == 3, s
    assert "iso  - base p99.9" in s and "fifo - base p99" in s


def test_the_report_does_not_score_at_another_k(tmp_path):
    _run(tmp_path / "o", 4)
    s = _report(tmp_path / "o")
    assert s.count("not scored (k=4") == 3 and "HELD" not in s


def test_interrupts_left_on_the_qemu_cores_void_everything(tmp_path):
    _run(tmp_path / "o", 12, leak=3)
    s = _report(tmp_path / "o")
    assert "max 3 (want <= 2)" in s and s.count("VOID (M1 failed)") == 3


def test_the_harness_parses_and_states_its_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    h = open(HARNESS, encoding="utf-8").read()
    head = h.split("\nset -u\n")[0]
    for s in ("median <= -5 us, and below zero in >= 9/12", "REFUTED if the\n#      median >= 0",
              "median < 0 and below zero in >= 8/12", "|median| <= 3 us", "fired at most twice",
              "-> P1, P2, P3", "No latency was looked at"):
        assert s in head, s
    assert "irq_set restore" in h and 'qemu_policy other' in h
