"""The arrival test's scoring (Phase 3b / A6, 2026-09-24): the thresholds
run-arrival.sh fixed before any run, the checks, what rests on them, and the
report end to end on a synthetic run; and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import arrival_report as ar  # noqa: E402

REPORT = os.path.join(GC, "arrival_report.py")
HARNESS = os.path.join(GC, "run-arrival.sh")
BASH = shutil.which("bash")


@pytest.mark.parametrize("m,want", [(10.0, "HELD"), (25.0, "HELD"), (9.9, "PARTIAL"), (3.1, "PARTIAL"),
                                    (3.0, "REFUTED"), (-2.0, "REFUTED")])
def test_p1(m, want):
    assert ar.score_p1([m] * 12) == want


@pytest.mark.parametrize("e,c,want", [(0.80, 0.90, "HELD"), (0.5, 0.99, "HELD"), (0.85, 0.99, "PARTIAL"),
                                      (0.70, 0.89, "PARTIAL"), (0.90, 0.99, "REFUTED"), (0.95, 0.99, "REFUTED")])
def test_p2(e, c, want):
    assert ar.score_p2(e, c) == want


@pytest.mark.parametrize("m,want", [(5.0, "HELD"), (-5.0, "HELD"), (5.1, "FAILED"), (-6.0, "FAILED")])
def test_p3(m, want):
    assert ar.score_p3([m] * 12) == want


@pytest.mark.parametrize("m,want", [(3.0, "HELD"), (-3.0, "HELD"), (3.1, "FAILED")])
def test_c1(m, want):
    assert ar.score_c1([m] * 12) == want


def test_checks():
    assert ar.check_m1([(0.2, 0.2, 0.2), (2.0, 2.19, 2.19), (2.0, 1.81, 1.46)])      # just inside 10% and 0.8
    assert not ar.check_m1([(0.2, 0.2, 0.2), (2.0, 2.21, 2.21)])          # mean 10.5% off
    assert not ar.check_m1([(0.2, 0.2, 0.15)])                            # sd/mean 0.75: not exponential
    assert not ar.check_m1([(0.2, 0.2, 0.25)])                            # 1.25
    assert ar.check_m2(0.90, 0.20) and not ar.check_m2(0.89, 0.1) and not ar.check_m2(0.95, 0.21)
    assert ar.RESTS_ON == {"P1": ("M1", "M2"), "P2": ("M1", "M2"), "P3": ("M1", "M2"), "C1": ("M1",)}


CELLS = {  # arm: (p50 us, successful, attempted, wake per exchange)
    "Dc200us": (140.0, 4.4, 4.45, 0.05), "De200us": (165.0, 2.0, 3.5, 2.0),
    "Dc2ms": (184.0, 0.12, 2.5, 5.2), "De2ms": (185.0, 0.2, 2.6, 5.1),
    "Ac200us": (50.0, 0.0, 0.0, 0.03), "Ae200us": (51.0, 0.0, 0.0, 0.03)}


def _run(out, k, sd_ratio=1.0):
    out.mkdir()
    for r in range(1, k + 1):
        for a, (p50, okp, att, wk) in CELLS.items():
            s = {"p50_ms": p50 / 1000, "p90_ms": p50 * 1.1 / 1000, "p99_ms": p50 * 1.5 / 1000,
                 "period_us": {"p50": 400.0, "mean": 420.0}}
            if a in ar.EXP_ARMS:
                m = ar.MEAN_MS[a]
                s["arrival"] = {"kind": "exp", "seed": 100 * r, "draws": 1200,
                                "sleep_ms": {"mean": m, "p50": m * 0.69, "sd": m * sd_ratio, "max": m * 7}}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
            snap = lambda v: {"t_ns": 0, "counters": v}
            b = {"halt_attempted_poll": 0, "halt_successful_poll": 0, "halt_wakeup": 0}
            e = {"halt_attempted_poll": int(att * 1200), "halt_successful_poll": int(okp * 1200),
                 "halt_wakeup": int(wk * 1200)}
            (out / ("kvm-%s_r%d.json" % (a, r))).write_text(json.dumps({"before": snap(b), "after": snap(e)}))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_the_report_scores_h_at_k_12(tmp_path):
    _run(tmp_path / "o", 12)
    s = _report(tmp_path / "o")
    assert "-> ok" in s and s.count("-> HELD") == 4, s
    assert "P1  De200us - Dc200us, p50: median +25.0 us" in s


def test_the_report_does_not_score_at_another_k(tmp_path):
    _run(tmp_path / "o", 6)
    s = _report(tmp_path / "o")
    assert s.count("not scored (k=6") == 4 and "HELD" not in s


def test_sleeps_that_are_not_exponential_void_everything(tmp_path):
    _run(tmp_path / "o", 12, sd_ratio=0.5)
    s = _report(tmp_path / "o")
    assert "M1 exponential sleeps" in s and "-> FAILED" in s
    assert s.count("VOID (M1 failed)") == 4


def test_the_harness_parses_and_states_its_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    h = open(HARNESS, encoding="utf-8").read()
    head = h.split("\nset -u\n")[0]
    for s in ("median >= +10 us", "REFUTED if <= +3 us", "De200us <= 0.80 while Dc200us >= 0.90",
              "REFUTED if De200us >= 0.90", "|median| <= 5 us", "|median| <= 3 us",
              "within 10% of the set mean", "between 0.8 and 1.2", "-> P1, P2, P3, C1", "-> P1, P2, P3"):
        assert s in head, s
    assert 'PROBE_ARRIVAL="$(arrival_of "$a")"' in h
