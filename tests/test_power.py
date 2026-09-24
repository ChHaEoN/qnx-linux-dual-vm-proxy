"""The power test (Phase 3b / A6, 2026-09-24): the rail sampler against a fake
hwmon directory, the scoring at the thresholds run-power.sh fixed before any run,
the checks, the report end to end on a synthetic run, and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import power_report as pr  # noqa: E402

PW = os.path.join(GC, "power_window.py")
REPORT = os.path.join(GC, "power_report.py")
HARNESS = os.path.join(GC, "run-power.sh")
BASH = shutil.which("bash")


def test_the_sampler_reads_every_labelled_rail_until_told_to_stop(tmp_path):
    hw = tmp_path / "hwmon0"
    hw.mkdir()
    for i, (lab, mv, ma) in enumerate((("VDD_IN", 5000, 900), ("VDD_CPU_GPU_CV", 5000, 100),
                                       ("VDD_SOC", 5000, 270)), 1):
        (hw / ("in%d_label" % i)).write_text(lab + "\n")
        (hw / ("in%d_input" % i)).write_text("%d\n" % mv)
        (hw / ("curr%d_input" % i)).write_text("%d\n" % ma)
    (hw / "in4_input").write_text("1\n")          # an unlabelled channel is skipped
    stop, out = tmp_path / "stop", tmp_path / "pw.json"
    p = subprocess.Popen([sys.executable, PW, "--out", str(out), "--stop-file", str(stop), "--hwmon", str(hw),
                          "--interval-ms", "5", "--max-s", "30"])
    import time
    time.sleep(0.5)
    stop.write_text("")
    assert p.wait(timeout=20) == 0
    d = json.loads(out.read_text())
    assert d["rails"] == ["VDD_IN", "VDD_CPU_GPU_CV", "VDD_SOC"]
    assert len(d["samples"]) > 10
    t, a, b, c = d["samples"][0]
    assert (a, b, c) == (4500.0, 500.0, 1350.0)     # mV x mA / 1000
    ts = [s[0] for s in d["samples"]]
    assert ts == sorted(ts)


def test_the_sampler_stops_by_itself(tmp_path):
    hw = tmp_path / "hw"
    hw.mkdir()
    (hw / "in1_label").write_text("VDD_IN")
    (hw / "in1_input").write_text("5000")
    (hw / "curr1_input").write_text("1000")
    r = subprocess.run([sys.executable, PW, "--out", str(tmp_path / "o.json"), "--stop-file", str(tmp_path / "s"),
                        "--hwmon", str(hw), "--interval-ms", "10", "--max-s", "0.3"], timeout=20)
    assert r.returncode == 0 and json.loads((tmp_path / "o.json").read_text())["samples"]


@pytest.mark.parametrize("d,want", [([150.0] * 6, "HELD"), ([400.0] * 5 + [-1.0], "PARTIAL"),
                                    ([149.0] * 6, "PARTIAL"), ([30.0] * 6, "REFUTED")])
def test_p1(d, want):
    assert pr.score_p1(d) == want


@pytest.mark.parametrize("m,want", [(30.0, "HELD"), (-30.0, "HELD"), (31.0, "FAILED")])
def test_p2(m, want):
    assert pr.score_p2([m] * 6) == want


@pytest.mark.parametrize("m,want", [(100.0, "HELD"), (99.0, "PARTIAL"), (21.0, "PARTIAL"), (20.0, "REFUTED")])
def test_p3(m, want):
    assert pr.score_p3([m] * 6) == want


def test_checks():
    share = {"B2ms": 0.8, "D2ms": 0.2, "D200us": 0.5, "N200us": 0.3}
    assert pr.checks(share, [200, 500]) == {"M1a": True, "M1b": True, "M2": True}
    assert pr.checks(dict(share, B2ms=0.79), [500])["M1a"] is False
    assert pr.checks(dict(share, N200us=0.31), [500])["M1b"] is False
    assert pr.checks(share, [199])["M2"] is False
    assert pr.RESTS_ON == {"P1": ("M1a", "M2"), "P2": ("M2",), "P3": ("M1b", "M2")}


def test_the_window_is_cut_on_the_snapshots_clock():
    pw = {"rails": ["VDD_IN", "VDD_CPU_GPU_CV"], "samples": [[5, 9999, 9999], [10, 4000, 500], [20, 4200, 700],
                                                             [30, 9999, 9999]]}
    kv = {"before": {"t_ns": 10}, "after": {"t_ns": 20}}
    p, n = pr.window_power(pw, kv)
    assert n == 2 and p == {"VDD_IN": 4100, "VDD_CPU_GPU_CV": 600}


CELLS = {  # arm: (VDD_IN, CPU, SOC, busiest share, p50)
    "Nidle": (4500, 500, 1370, 0.02, None), "N200us": (4700, 600, 1380, 0.2, 173.0),
    "N2ms": (4600, 550, 1375, 0.06, 179.0), "Didle": (4500, 505, 1370, 0.02, None),
    "D200us": (5100, 850, 1400, 0.67, 132.0), "D2ms": (4610, 552, 1375, 0.06, 178.0),
    "Bidle": (4510, 510, 1370, 0.02, None), "B200us": (5120, 860, 1400, 0.68, 132.0),
    "B2ms": (5300, 1000, 1400, 0.92, 144.0)}


def _run(out, k):
    out.mkdir()
    for r in range(1, k + 1):
        for a, (vin, cpu, soc, sh, p50) in CELLS.items():
            samples = [[1000 + i * 20, vin, cpu, soc] for i in range(500)]
            (out / ("pw-%s_r%d.json" % (a, r))).write_text(json.dumps(
                {"rails": ["VDD_IN", "VDD_CPU_GPU_CV", "VDD_SOC"], "samples": samples}))
            th = lambda run: {"1": {"run_ns": run}, "2": {"run_ns": 0}}
            kv = {"before": {"t_ns": 1000, "threads": th(0)}, "after": {"t_ns": 1000 + 499 * 20,
                                                                       "threads": th(int(sh * 499 * 20))}}
            (out / ("kvm-%s_r%d.json" % (a, r))).write_text(json.dumps(kv))
            if p50 is not None:
                (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": {"p50_ms": p50 / 1000}}))


def test_the_report_scores_h_at_k_6(tmp_path):
    _run(tmp_path / "o", 6)
    r = subprocess.run([sys.executable, REPORT, str(tmp_path / "o")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    s = r.stdout
    assert s.count("-> HELD") == 3 and s.count("-> ok") == 3, s
    assert "P1  B2ms   - D2ms   VDD_CPU_GPU_CV: median    +448 mW" in s
    assert "B saves 34.0 us at p50 for +0.69 W at VDD_IN" in s


def test_the_report_does_not_score_at_another_k(tmp_path):
    _run(tmp_path / "o", 3)
    r = subprocess.run([sys.executable, REPORT, str(tmp_path / "o")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.count("not scored (k=3") == 3


def test_the_harness_parses_and_states_its_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    h = open(HARNESS, encoding="utf-8").read()
    head = h.split("\nset -u\n")[0]
    for s in ("median >= +150 mW and above zero in all 6 rounds", "REFUTED if <= +30 mW", "|median| <= 30 mW",
              "median >= +100 mW", "REFUTED if <= +20 mW", "B2ms >= 0.8 and D2ms <= 0.2",
              "D200us >= 0.5 and N200us <= 0.3", ">= 200 power samples", "No power was\n# compared"):
        assert s in head, s
    assert 'N="$N200" m_require_complete' in h and 'N="$N2" m_require_complete' in h
