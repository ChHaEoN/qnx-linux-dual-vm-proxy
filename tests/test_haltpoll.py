"""The halt_poll_ns intervention (Phase 3b / A6, 2026-09-24): the scoring of its
predictions and manipulation checks at the thresholds run-haltpoll.sh fixed
before any run (haltpoll_report.py), end to end on a synthetic run, and the
harness's header."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import haltpoll_report as hr  # noqa: E402

REPORT = os.path.join(GC, "haltpoll_report.py")
HARNESS = os.path.join(GC, "run-haltpoll.sh")
BASH = shutil.which("bash")


@pytest.mark.parametrize("m,want", [(-15.0, "HELD"), (-5.0, "HELD"), (-15.1, "PARTIAL"), (-29.9, "PARTIAL"),
                                    (-30.0, "REFUTED"), (-45.0, "REFUTED")])
def test_p1(m, want):
    assert hr.score_p1([m] * 12) == want


@pytest.mark.parametrize("m,want", [(-30.0, "HELD"), (-45.0, "HELD"), (-29.9, "PARTIAL"), (-15.1, "PARTIAL"),
                                    (-15.0, "REFUTED"), (0.0, "REFUTED")])
def test_p2(m, want):
    assert hr.score_p2([m] * 12) == want


@pytest.mark.parametrize("d,want", [
    ([4.0] * 12, "HELD"),
    ([6.0] * 10 + [-1.0, -1.0], "HELD"),
    ([6.0] * 9 + [-1.0] * 3, "PARTIAL"),       # median 6 but only 9/12 above zero
    ([3.9] * 12, "PARTIAL"),
    ([1.0] * 12, "REFUTED"),
    ([0.0] * 12, "REFUTED"),
])
def test_p3a(d, want):
    assert hr.score_p3a(d) == want


@pytest.mark.parametrize("d,want", [
    ([-4.0] * 12, "HELD"),
    ([-6.0] * 10 + [1.0, 1.0], "HELD"),
    ([-6.0] * 9 + [1.0] * 3, "PARTIAL"),
    ([-3.9] * 12, "PARTIAL"),
    ([-1.0] * 12, "REFUTED"),
    ([2.0] * 12, "REFUTED"),
])
def test_p3b(d, want):
    assert hr.score_p3b(d) == want


@pytest.mark.parametrize("rtt,mon,want", [(5.0, 1.0, "HELD"), (-5.0, -1.0, "HELD"), (5.1, 0.0, "FAILED"),
                                          (0.0, 1.1, "FAILED")])
def test_c1(rtt, mon, want):
    assert hr.score_c1([rtt] * 12, [mon] * 12) == want


def test_manipulation_checks():
    assert hr.checks(0, 2.0, 4.0, 0.9, 0.2) == {"M1": True, "M2": True, "M3": True}
    assert hr.checks(1, 2.0, 4.0, 0.9, 0.2)["M1"] is False
    assert hr.checks(0, 2.1, 4.0, 0.9, 0.2)["M2"] is False
    assert hr.checks(0, 2.0, 4.0, 0.89, 0.2)["M3"] is False
    assert hr.checks(0, 2.0, 4.0, 0.9, 0.21)["M3"] is False


def test_each_prediction_rests_on_the_checks_the_header_names():
    assert hr.RESTS_ON == {"P1": ("M1",), "P3a": ("M1", "M3"), "P2": ("M2", "M3"),
                           "P3b": ("M2", "M3"), "C1": ("M2", "M3")}


# ---- end to end on a synthetic run

def _run(out, k, cells, n_attempts=0):
    """cells: {arm: (rtt_us, monitor_ticks, attempted/ex, successful/ex, wakes/ex)}."""
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"counter": "arch_timer: cp15 timer(s) running at 31.25MHz"}))
    ex = 1200
    for r in range(1, k + 1):
        for a, (rtt, tk, att, okp, wk) in cells.items():
            if a.startswith("N"):
                att, okp = n_attempts, 0
            summ = {"p50_ms": rtt / 1000.0, "server_us": {"p50": tk * 0.032}, "other_us": {"p50": rtt - 0.4},
                    "period_us": {"p50": rtt + (265.0 if a.endswith("200us") else 2066.0)}}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": summ}))
            snap = lambda base: {"t_ns": 0, "counters": {"halt_attempted_poll": base, "halt_successful_poll": base,
                                                         "halt_wakeup": base}}
            b, e = snap(1000), snap(1000)
            e["counters"] = {"halt_attempted_poll": 1000 + int(att * ex), "halt_successful_poll": 1000 + int(okp * ex),
                             "halt_wakeup": 1000 + int(wk * ex)}
            (out / ("kvm-%s_r%d.json" % (a, r))).write_text(json.dumps({"before": b, "after": e}))


# As hypothesis H would have it: everything follows the polling.
H_CELLS = {"N200us": (180.0, 12, 0, 0, 5.0), "N2ms": (184.0, 12, 0, 0, 5.2),
           "D200us": (137.0, 6, 4.1, 4.08, 0.05), "D2ms": (184.0, 12, 2.5, 0.12, 5.2),
           "B200us": (137.0, 6, 4.1, 4.08, 0.05), "B2ms": (140.0, 6, 4.0, 3.9, 0.3)}


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_the_report_scores_h_as_held_at_k_12(tmp_path):
    _run(tmp_path / "o", 12, H_CELLS)
    s = _report(tmp_path / "o")
    for line in ("M1 N arms' attempted polls, all rounds: 0 (want 0) -> ok", "-> ok"):
        assert line in s
    assert s.count("-> HELD") == 5, s


def test_the_report_does_not_score_at_another_k(tmp_path):
    _run(tmp_path / "o", 6, H_CELLS)
    s = _report(tmp_path / "o")
    assert s.count("not scored (k=6") == 5 and "HELD" not in s


def test_a_failed_check_voids_what_rests_on_it(tmp_path):
    _run(tmp_path / "o", 12, H_CELLS, n_attempts=1)       # the N VMs still polled: M1 fails
    s = _report(tmp_path / "o")
    assert "-> FAILED" in s.split("M2")[0]
    assert s.count("VOID (M1 failed)") == 2               # P1 and P3a
    assert s.count("-> HELD") == 3                        # P2, P3b, C1 do not rest on M1


def test_the_harness_parses_and_states_its_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("median >= -15 us", "REFUTED if <= -30 us", "median <= -30 us", "REFUTED if >= -15 us",
              "median >= +4 ticks and above zero in >= 10/12", "REFUTED if the median <= +1",
              "median <= -4 ticks and below zero in >= 10/12", "REFUTED if the median >= -1",
              "|round trip| <= 5 us and |monitor| <= 1 tick",
              "zero attempted polls", "<= half of D2ms's", ">= 0.9 and D2ms's <= 0.2",
              "-> P1, P3a", "-> P2, P3b, C1", "-> P2, P3a, P3b, C1"):
        assert s in head, s
