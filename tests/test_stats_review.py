"""stats_review.py (Phase 3b / A6, 2026-09-24): the distribution-free interval,
the bootstrap, the two-level variance components and equation 3 of Kalibera &
Jones (ISMM 2013), and the rank autocorrelation, each against known answers."""
import json
import math
import os
import random
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import stats_review as sr  # noqa: E402


def test_the_exact_interval_for_twelve_rounds_is_the_third_and_tenth():
    j, cov = sr.exact_ci_ranks(12)
    assert j == 3 and abs(cov - (1 - 2 * (1 + 12 + 66) / 4096)) < 1e-12     # 96.14%
    assert sr.exact_median_ci(list(range(1, 13)))[:2] == (3, 10)


@pytest.mark.parametrize("k,j", [(6, 1), (8, 1), (10, 2), (16, 4), (24, 7)])
def test_the_exact_interval_ranks_follow_the_sign_test(k, j):
    got, cov = sr.exact_ci_ranks(k)
    assert got == j and cov >= 0.95
    tail_next = sum(math.comb(k, i) for i in range(j + 1)) / 2 ** k
    assert 1 - 2 * tail_next < 0.95          # one rank further in would not reach 95%


def test_too_few_rounds_report_their_real_coverage():
    j, cov = sr.exact_ci_ranks(4)
    assert j == 1 and abs(cov - 0.875) < 1e-12


def test_the_bootstrap_is_repeatable_and_brackets_the_median():
    d = [random.Random(3).gauss(-40, 3) for _ in range(12)]
    a, b = sr.bootstrap_median_ci(d, 2000), sr.bootstrap_median_ci(d, 2000)
    assert a == b and a[0] <= st_median(d) <= a[1]


def st_median(x):
    import statistics
    return statistics.median(x)


def test_variance_components_recover_a_known_between_round_spread():
    rng = random.Random(7)
    offsets = [rng.gauss(0, 5.0) for _ in range(40)]
    rounds = [[180 + o + rng.gauss(0, 20.0) for _ in range(800)] for o in offsets]
    vc = sr.variance_components(rounds, reps=100)
    import statistics
    assert abs(vc["sd_between"] - statistics.pstdev(offsets)) < 1.5
    # The sampling sd of a normal sample's median: 1.2533 * sigma / sqrt(n).
    assert abs(vc["sd_median_within"] - 1.2533 * 20 / math.sqrt(800)) < 0.25


def test_no_round_level_leaves_t2_near_zero():
    rng = random.Random(9)
    rounds = [[180 + rng.gauss(0, 20.0) for _ in range(800)] for _ in range(40)]
    vc = sr.variance_components(rounds, reps=100)
    assert vc["T2"] < 0.5                    # sampling alone explains the spread


def test_equation_three():
    assert sr.optimal_r1(0.002, 4.0, 400.0, 25.0) == math.ceil(math.sqrt(2000 * 16))   # 179
    assert sr.optimal_r1(0.002, 4.0, 400.0, 0.0) is None
    assert sr.optimal_r1(0.002, 4.0, 400.0, -1.0) is None


def test_rank_autocorrelation():
    rng = random.Random(11)
    x, prev = [], 0.0
    for _ in range(5000):
        prev = 0.6 * prev + rng.gauss(0, 1)
        x.append(prev)
    assert abs(sr.rank_autocorr(x, 1) - 0.6) < 0.05
    iid = [rng.gauss(0, 1) for _ in range(5000)]
    assert abs(sr.rank_autocorr(iid, 1)) < 0.05
    x[100] = 1e9                              # one huge sample barely moves a rank correlation
    assert abs(sr.rank_autocorr(x, 1) - 0.6) < 0.05


def test_round_seconds(tmp_path):
    f = tmp_path / "run.log"
    f.write_text("[10:00:00] round 1/3 done\nnoise\n[10:01:30] round 2/3 done\n[10:02:50] round 3/3 done\n")
    assert sr.round_seconds(str(f)) == 85.0
    g = tmp_path / "midnight.log"
    g.write_text("[23:59:30] round 1/2 done\n[00:00:40] round 2/2 done\n")
    assert sr.round_seconds(str(g)) == 70.0


def test_the_cli_on_a_synthetic_record(tmp_path):
    rng = random.Random(5)
    for r in range(1, 13):
        for arm, base in (("X", 140.0), ("Y", 180.0)):
            s = [(base + rng.gauss(0, 10)) / 1000.0 for _ in range(300)]
            summ = {"p50_ms": sorted(s)[150], "n": 300, "warmup_discarded": 50, "period_us": {"p50": 2200.0}}
            (tmp_path / ("lat-%s_r%d.json" % (arm, r))).write_text(json.dumps({"summary": summ,
                                                                                "samples_in_order": s}))
    (tmp_path / "run.log").write_text("".join("[10:%02d:00] round %d/12 done\n" % (r, r) for r in range(1, 13)))
    out = subprocess.run([sys.executable, os.path.join(GC, "stats_review.py"), str(tmp_path), "--pairs", "X:Y",
                          "--reps", "500"], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "12 rounds in every arm used" in out.stdout and "[d(3), d(10)] (coverage 96.1%)" in out.stdout
    assert "excludes 0" in out.stdout
