"""The one-vCPU test (Phase 3b / A6, 2026-09-24): the scoring of its predictions
and manipulation checks at the thresholds run-smp.sh fixed before any run
(smp_report.py), end to end on synthetic reduced traces, and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import smp_report as sr  # noqa: E402

REPORT = os.path.join(GC, "smp_report.py")
HARNESS = os.path.join(GC, "run-smp.sh")
BASH = shutil.which("bash")


@pytest.mark.parametrize("b,want", [(1.0, "HELD"), (0.5, "HELD"), (1.5, "REFUTED"), (2.0, "REFUTED"), (3.0, "REFUTED")])
def test_p1(b, want):
    assert sr.score_p1(b) == want


@pytest.mark.parametrize("m,want", [(-10.0, "HELD"), (-17.0, "HELD"), (-9.9, "PARTIAL"), (-3.1, "PARTIAL"),
                                    (-3.0, "REFUTED"), (2.0, "REFUTED")])
def test_p2(m, want):
    assert sr.score_p2([m] * 12) == want


@pytest.mark.parametrize("m,want", [(8.0, "HELD"), (17.0, "HELD"), (7.9, "PARTIAL"), (2.1, "PARTIAL"),
                                    (2.0, "REFUTED"), (-4.0, "REFUTED")])
def test_p3(m, want):
    assert sr.score_p3([m] * 12) == want


def test_checks_and_what_rests_on_them():
    assert sr.checks(0.9, 0.1, 3) == {"M1": True, "M2": True}
    assert sr.checks(0.89, 0.1, 3)["M1"] is False
    assert sr.checks(0.9, 0.11, 3)["M1"] is False
    assert sr.checks(0.9, 0.1, 2)["M2"] is False
    assert sr.RESTS_ON == {"P1": ("M1", "M2"), "P2": ("M1",), "P3": ("M1", "M2")}


def _exchange(t0, kind):
    """Reduced-trace lines of one exchange, times in us from t0. Segments by kind:
    two-vCPU blocked: A 20, B 16, C 100 (two more blocked halts), D 20;
    one-vCPU blocked: A 20, B 16, C 80, D 20; polled: A 20, B 2, C 70, D 20."""
    ev = [(0, "X 130"), (20, "I 78 1 m")]
    if kind == "b2":
        ev += [(22, "W v0 m"), (30, "S v0"), (36, "K wait 1900000 v0"),
               (60, "W v1 v0"), (64, "S v1"), (68, "K wait 900000 v1"),
               (90, "W v1 v0"), (94, "S v1"), (98, "K wait 20000 v1"), (136, "W m v0")]
        out = 156
    elif kind == "b1":
        ev += [(22, "W v0 m"), (30, "S v0"), (36, "K wait 1900000 v0"), (116, "W m v0")]
        out = 136
    else:
        ev += [(22, "K poll 150000 v0"), (50, "K poll 90000 v1"), (92, "W m v0")]
        out = 112
    ev += [(out, "R 116")]
    return ["%.6f 001 %s" % ((t0 + t) / 1e6, e) for t, e in ev]


def _run(out, k, kinds, rtts):
    out.mkdir()
    for r in range(1, k + 1):
        for a in sr.ARMS:
            lines = []
            for i in range(20):
                lines += _exchange(1000_000_000 + r * 1_000_000 + i * 2000, kinds[a])
            (out / ("bp-%s_r%d.log" % (a, r))).write_text("\n".join(lines) + "\n")
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": {"p50_ms": rtts[a] / 1000.0}}))


KINDS = {"2D200us": "p", "2D2ms": "b2", "2B200us": "p", "2B2ms": "p",
         "1D200us": "p", "1D2ms": "b1", "1B200us": "p", "1B2ms": "p"}
RTTS = {"2D200us": 140.0, "2D2ms": 188.0, "2B200us": 143.0, "2B2ms": 155.0,
        "1D200us": 138.0, "1D2ms": 170.0, "1B200us": 141.0, "1B2ms": 154.0}


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "500", "100"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_the_report_scores_h_at_k_12(tmp_path):
    _run(tmp_path / "o", 12, KINDS, RTTS)
    s = _report(tmp_path / "o")
    assert "M1 first halt blocked: 1D2ms 1.00 (want >= 0.9), 1B2ms 0.00 (want <= 0.1) -> ok" in s
    assert "M2 2D2ms blocked halts in [I, TX]: 3.0 (want 3) -> ok" in s
    assert "P1  1D2ms blocked halts in [I, TX]: 1.0 (2D2ms 3.0) -> HELD" in s
    assert "P2  1D2ms - 2D2ms, rtt: median -18.0 us" in s and s.count("-> HELD") == 3
    assert "P3  (2D2ms - 2B2ms) - (1D2ms - 1B2ms), rtt: median +17.0 us" in s
    assert "segment C, blocked - polled at 2 ms: two vCPUs +30.0 us, one vCPU +10.0 us" in s


def test_the_report_does_not_score_at_another_k(tmp_path):
    _run(tmp_path / "o", 4, KINDS, RTTS)
    s = _report(tmp_path / "o")
    assert s.count("not scored (k=4") == 3 and "HELD" not in s


def test_a_failed_check_voids_what_rests_on_it(tmp_path):
    kinds = dict(KINDS, **{"2D2ms": "b1"})         # the two-vCPU pattern did not replicate: M2 fails
    _run(tmp_path / "o", 12, kinds, RTTS)
    s = _report(tmp_path / "o")
    assert "M2 2D2ms blocked halts in [I, TX]: 1.0 (want 3) -> FAILED" in s
    assert s.count("VOID (M2 failed)") == 2 and s.count("-> HELD") == 1      # P2 rests on M1 only


def test_the_harness_parses_and_states_its_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    h = open(HARNESS, encoding="utf-8").read()
    head = h.split("\nset -u\n")[0]
    for s in ("exactly 1 blocked halt inside", "REFUTED if it has 2 or more", "median <= -10 us",
              "REFUTED if >= -3 us", "median >= +8 us", "REFUTED if <= +2 us",
              "in >= 90% of", "in <= 10%", "-> P1, P2, P3", "-> P1, P3",
              "one boot with -smp 1 checked", "nothing was timed"):
        assert s in head, s
    assert 'SMP="${SMPC[$c]}"' in h
    assert "(cm, not c: c is this boot's configuration" in h
