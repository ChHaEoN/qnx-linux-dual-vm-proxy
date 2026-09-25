"""The a1.metal test (Phase 3b / A6, 2026-09-25): the report on synthetic rounds from a
16-core host at HZ=250 and HZ=1000, and the harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import metal_report as mr  # noqa: E402

REPORT = os.path.join(GC, "metal_report.py")
HARNESS = os.path.join(GC, "run-metal.sh")
BASH = shutil.which("bash")
PAT = ["open", "confined", "confined", "open"]


def _run(out, k, hz=250, tick=8.0, conf_shift=0.0, conf_tail=1.0, bad_state=False, off_grid=False,
         n=1000, warm=200, seed=5):
    """Requests every 2250 us from 137 us past a base on every grid. Exchanges leaving
    150..0 us before a tick are +tick us; 1 in 8 of them +40 more. 1 in 120 others +40 us
    (confined: times conf_tail). Ticks every 1e6/hz us, on the grid unless off_grid."""
    out.mkdir(parents=True)
    rng = random.Random(seed)
    period = 1e6 / hz
    (out / "stamp.json").write_text(json.dumps({"host": {"all": "0-15", "conf": "3,5,6,7,8,9,10,11,12,13,14,15", "hz": hz},
                                                "pin": {"qemu": "0-2", "probe": 4}}))
    order, clog = [], []
    for r in range(1, k + 1):
        arm = PAT[(r - 1) % 4]
        order.append("round %d arm: %s" % (r, arm))
        want = "3,5-15" if arm == "confined" else "0-15"
        if bad_state and r == 2:
            want = "0-15"
        for w in ("before", "after"):
            clog.append("round %d %s udevd=%s pid1=%s gnome-shell=none qemu=0-2" % (r, w, want, want))
        base = 1e9 + r * 1e7
        lines, tk, samples = [], [], []
        for i in range(warm + n):
            t0 = 137.0 + i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i < warm:
                continue
            v = 150.0 + 8.0 * rng.random() + (conf_shift if arm == "confined" else 0.0)
            if period - 150.0 <= t0 % period < period:
                v += tick + (40.0 if rng.random() < 1.0 / 8 else 0.0)
            elif rng.random() < (conf_tail if arm == "confined" else 1.0) / 120:
                v += 40.0
            samples.append(v / 1000.0)
        j = 0
        while j * period < (warm + n) * 2250.0 + period:
            tk.append("%.6f 001 H tick_sched_timer" % ((base + j * period + (period / 2 if off_grid else 3.5)) / 1e6))
            j += 1
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(sorted(lines, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("tk-t2ms_r%d.log" % r)).write_text("\n".join(tk) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_cpu_lists_compare_as_sets():
    assert mr.cpus("3,5-15") == mr.cpus("3,5,6,7,8,9,10,11,12,13,14,15") and mr.cpus("0-2") == mr.cpus("0 1 2")


def test_a_tick_cost_and_no_confinement_gain_hold_everything(tmp_path):
    for hz in (250, 1000):
        s = _report_of(tmp_path / str(hz), hz=hz)
        assert "FAILED" not in s, s
        for p in ("P1", "P2", "P3", "P4"):
            assert "-> HELD" in _line(s, p), (hz, s)


def _report_of(d, **kw):
    _run(d, 40, **kw)
    return _report(d)


def test_no_tick_cost_or_a_confinement_gain_refutes(tmp_path):
    s = _report_of(tmp_path / "a", tick=0.0)
    assert "-> REFUTED" in _line(s, "P2"), s
    s = _report_of(tmp_path / "b", conf_tail=0.0, conf_shift=3.0)
    assert "-> REFUTED" in _line(s, "P3") and "-> REFUTED" in _line(s, "P4"), s


def test_a_wrong_state_or_an_off_grid_tick_voids(tmp_path):
    s = _report_of(tmp_path / "a", bad_state=True)
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P3"), s
    s = _report_of(tmp_path / "b", off_grid=True)
    assert "-> FAILED" in _line(s, "M5") and "VOID (M5 failed)" in _line(s, "P1") and "VOID" not in _line(s, "P4"), s
    _run(tmp_path / "c", 4)
    assert "not scored (k=4; the prediction is for k=40)" in _report(tmp_path / "c")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("RATIO >= 2", "SLOWDOWN >= +3 us", "|p99 confined - p99 open| <= 5% of open's",
              "|p50 confined - p50 open| <= 2 us", "[PERIOD - 150, PERIOD) us mod PERIOD", "It is not to be amended",
              "rehearsals and", "Scored only at k = 40", "The owner asked for this session"):
        assert s in head, s
    assert "0-5" not in body and "metal_report.py" in body and "hrtimer_expire_entry" in body
