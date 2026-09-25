"""The natural-state confinement test (Phase 3b / A6, 2026-09-25): the scoring run-natural.sh
fixed before any run, the report end to end on synthetic rounds, and the harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import natural_report as nr  # noqa: E402

REPORT = os.path.join(GC, "natural_report.py")
HARNESS = os.path.join(GC, "run-natural.sh")
BASH = shutil.which("bash")
PAT = ["open", "confined", "confined", "open"]


def test_scoring():
    assert nr.score_shrink(20.0, 40.0) == "HELD" and nr.score_shrink(20.1, 40.0) == "REFUTED"
    assert nr.score_shrink(-1.0, 0.0) == "REFUTED"
    assert nr.score_lower(190.0, 200.0, nr.LOWER99) == "HELD" and nr.score_lower(190.1, 200.0, nr.LOWER99) == "REFUTED"
    assert nr.score_lower(270.0, 300.0, nr.LOWER999) == "HELD" and nr.score_lower(271.0, 300.0, nr.LOWER999) == "REFUTED"


def _run(out, k, tj_conf=5.0, tail_conf=False, p50_shift=0.0, bad_state=False, qemu_moved=False, no_window=False,
         n=1000, warm=200, seed=12):
    """Requests every 2250 us; tj reads at 0.6 and 1.624 s, another zone's at 1.1 s.
    Exchanges 0..5 ms after a tj read are 60 us slower open and tj_conf us slower confined
    (0 in both when no_window). The out class has +40 us in 1 of 60 and +600 us in 1 of 300
    open, and confined only if tail_conf."""
    out.mkdir()
    rng = random.Random(seed)
    order, clog, sq = [], [], []
    for r in range(1, k + 1):
        arm = PAT[(r - 1) % 4]
        order.append("round %d arm: %s" % (r, arm))
        want = "3,5" if arm == "confined" else "0-5"
        if bad_state and r == 2:
            want = "0-5"
        q = "0-2" if not (qemu_moved and r == 3) else "0-2 3,5"
        for w in ("before", "after"):
            clog.append("round %d %s udevd=%s pid1=%s gnome-shell=%s qemu=%s" % (r, w, want, want, want, q))
        sq.append("round %d seqnum %d %d" % (r, 1000 * r, 1000 * r + 6))
        base = 1e9 + r * 10e6
        tj = [600_000.0, 1_624_000.0]
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in tj]
        lines.append("%.6f 003 T cpu-thermal" % ((base + 1_100_000.0) / 1e6))
        add = 0.0 if no_window else (60.0 if arm == "open" else tj_conf)
        samples = []
        for i in range(warm + n):
            t0 = i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i >= warm:
                v = 180.0 + (p50_shift if arm == "confined" else 0.0) + 8.0 * rng.random()
                if any(0 <= t0 - s <= 5000.0 for s in tj):
                    v += add
                elif arm == "open" or tail_conf:
                    x = rng.random()
                    v += 600.0 if x < 1.0 / 300 else (40.0 if x < 1.0 / 60 else 0.0)
                samples.append(v / 1000.0)
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(sorted(lines, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "seqnum.log").write_text("\n".join(sq) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_seqnums(tmp_path):
    _run(tmp_path / "o", 4)
    assert nr.seqnums(str(tmp_path / "o")) == {1: 6, 2: 6, 3: 6, 4: 6}


def test_a_window_and_a_tail_that_go_hold_everything(tmp_path):
    _run(tmp_path / "o", 40, tj_conf=5.0, tail_conf=False)
    s = _report(tmp_path / "o")
    assert "arms {'open': 20, 'confined': 20}" in s and "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s
    assert "[(6, 20)]" in s, s


def test_a_window_and_a_tail_that_stay_refute_and_a_shift_refutes_p4(tmp_path):
    _run(tmp_path / "o", 40, tj_conf=40.0, tail_conf=True, p50_shift=5.0)
    s = _report(tmp_path / "o")
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> REFUTED" in _line(s, p), s


def test_failed_checks_void(tmp_path):
    _run(tmp_path / "o", 40, bad_state=True)
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M2") and all("VOID (M2 failed)" in _line(s, p) for p in ("P1", "P3")), s
    _run(tmp_path / "p", 40, qemu_moved=True)
    s = _report(tmp_path / "p")
    assert "-> FAILED" in _line(s, "M5") and "VOID (M5 failed)" in _line(s, "P4"), s
    _run(tmp_path / "q", 40, no_window=True)
    s = _report(tmp_path / "q")
    assert "-> FAILED" in _line(s, "M3") and "VOID (M3 failed)" in _line(s, "P1") and "VOID" not in _line(s, "P2"), s
    _run(tmp_path / "r", 4)
    assert "not scored (k=4; the prediction is for k=40)" in _report(tmp_path / "r")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("confined tj excess <= 0.5x open's", "confined p99 <= 0.95x open's",
              "confined p99.9 <= 0.9x open's", "|confined p50 - open p50| <= 2 us",
              "NOTHING IS INJECTED", "The owner chose this test", "informed by earlier runs, not blind",
              "It is not to be amended", "Scored only at k = 40"):
        assert s in head, s
    assert 'K="${K:-40}"' in body and "natural_report.py" in body
    for s in ("burst_inject", "trace_marker", "INJ"):
        assert s not in body, s
