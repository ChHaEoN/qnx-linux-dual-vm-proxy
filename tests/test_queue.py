"""The queue test (Phase 3b / A6, 2026-09-24): the arms and queue checks, the scoring
run-queue.sh fixed before any run, the report end to end on synthetic rounds, and the
harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import queue_report as qr  # noqa: E402

REPORT = os.path.join(GC, "queue_report.py")
HARNESS = os.path.join(GC, "run-queue.sh")
BASH = shutil.which("bash")
PAT = ["run", "hold", "hold", "run"]


def _run(out, k, slow_in=("run",), bad_queue=False, n=1000, warm=200, seed=9):
    """Requests every 2250 us; tj reads at 0.6 and 1.624 s; markers U at 0.8, 1.2, 2.0 s and
    N at 1.9 s. Exchanges 0..5 ms after a U marker or a tj read are 50 us slower in the
    arms listed in slow_in."""
    out.mkdir()
    rng = random.Random(seed)
    order, qlog = [], []
    for r in range(1, k + 1):
        arm = PAT[(r - 1) % 4]
        order.append("round %d arm: %s" % (r, arm))
        held = arm == "hold"
        if bad_queue and r == 2:
            held = False
        qlog.append("round %d end: queue %s" % (r, "held" if held else "empty"))
        base = 1e9 + r * 10e6
        marks = [("U", 800_000.0), ("U", 1_200_000.0), ("N", 1_900_000.0), ("U", 2_000_000.0)]
        tj = [600_000.0, 1_624_000.0]
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in tj]
        lines += ["%.6f 005 M %s %d" % ((base + t) / 1e6, kd, i) for i, (kd, t) in enumerate(marks)]
        slow_at = ([t for kd, t in marks if kd == "U"] + tj) if arm in slow_in else []
        samples = []
        for i in range(warm + n):
            t0 = i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i >= warm:
                v = 180.0 + 8.0 * rng.random()
                if any(0 <= t0 - s <= 5000.0 for s in slow_at):
                    v += 50.0
                samples.append(v / 1000.0)
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(sorted(lines, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
        inj = [{"i": i, "kind": kd, "t_ns": 0, "seq_before": 10, "seq_after": 13 if kd == "U" else 10,
                "dur_us": 100.0, "iters": 3 if kd == "U" else 0} for i, (kd, _) in enumerate(marks)]
        (out / ("inj-t2ms_r%d.jsonl" % r)).write_text("".join(json.dumps(x) + "\n" for x in inj))
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "queue.log").write_text("\n".join(qlog) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_arms_and_queue_checks(tmp_path):
    _run(tmp_path / "o", 4)
    arms = qr.arms_of(str(tmp_path / "o"))
    assert arms == {1: "run", 2: "hold", 3: "hold", 4: "run"}
    assert qr.queue_ok(str(tmp_path / "o"), arms) == (4, 4)


def test_a_window_that_needs_processing_holds_everything(tmp_path):
    _run(tmp_path / "o", 24)
    s = _report(tmp_path / "o")
    assert "arms {'run': 12, 'hold': 12}" in s and "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_a_window_the_kernel_alone_makes_refutes_p1_p2(tmp_path):
    _run(tmp_path / "o", 24, slow_in=("run", "hold"))
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P3"), s


def test_a_queue_not_held_voids_and_another_k_is_not_scored(tmp_path):
    _run(tmp_path / "o", 24, bad_queue=True)
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M3") and all("VOID (M3 failed)" in _line(s, p) for p in ("P1", "P2", "P3")), s
    _run(tmp_path / "p", 4)
    assert "not scored (k=4; the prediction is for k=24)" in _report(tmp_path / "p")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("hold's U excess is below +10 us", "hold's tj excess is below +10 us", "run's U excess is\n#      >= +20 us",
              "The queue is released on any exit", "It is not to be amended", "Scored only at k = 24"):
        assert s in head, s
