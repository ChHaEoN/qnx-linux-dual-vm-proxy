"""The desktop test (Phase 3b / A6, 2026-09-24): the state and login checks, the scoring
run-headless.sh fixed before any run, the report end to end on synthetic rounds, and the
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
import headless_report as hr  # noqa: E402

REPORT = os.path.join(GC, "headless_report.py")
HARNESS = os.path.join(GC, "run-headless.sh")
BASH = shutil.which("bash")


def test_scoring():
    assert hr.score_keep(30.0, 60.0) == "HELD" and hr.score_keep(29.9, 60.0) == "REFUTED"
    assert hr.score_keep(5.0, -1.0) == "REFUTED"
    assert hr.score_lower(270.0, 300.0) == "HELD" and hr.score_lower(271.0, 300.0) == "REFUTED"


def _state(r, k):
    return "G" if (r - 1) * 4 // k in (0, 3) else "H"


def _run(out, k, h_window=60.0, h_tail=True, desktop_bad=False, logins=0, n=1000, warm=200, seed=6):
    """Requests every 2250 us; tj reads at 1.2 and 2.224 s; U markers at 0.9, 1.5, 1.9 s and
    R at 2.4 s. Exchanges 0..5 ms after a U marker or a tj read are slower by 60 us (G) or
    h_window us (H). The out class gets a heavy tail (1 in 50 at +150 us) in G, and in H
    too unless h_tail is False."""
    out.mkdir()
    rng = random.Random(seed)
    order, states = [], []
    for r in range(1, k + 1):
        s = _state(r, k)
        order.append("round %d state: %s" % (r, s))
        on = (s == "G") != desktop_bad
        for w in ("before", "after"):
            states.append("round %d %s gnome-shell=%d xorg=%d" % (r, w, 1 if on else 0, 1 if on else 0))
        base = 1e9 + r * 10e6
        marks = [("U", 900_000.0), ("U", 1_500_000.0), ("U", 1_900_000.0), ("R", 2_400_000.0)]
        tj = [1_200_000.0, 2_224_000.0]
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in tj]
        lines += ["%.6f 005 M %s %d" % ((base + t) / 1e6, kd, i) for i, (kd, t) in enumerate(marks)]
        slow_at = [t for kd, t in marks if kd == "U"] + tj
        add = 60.0 if s == "G" else h_window
        samples = []
        for i in range(warm + n):
            t0 = i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i >= warm:
                v = 185.0 + 10.0 * rng.random()
                if any(0 <= t0 - x <= 5000.0 for x in slow_at):
                    v += add
                elif (s == "G" or h_tail) and rng.random() < 0.02:
                    v += 150.0
                samples.append(v / 1000.0)
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(sorted(lines, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
        inj = [{"i": i, "kind": kd, "t_ns": 0, "seq_before": 10, "seq_after": 13 if kd == "U" else 10, "dur_us": 50.0}
               for i, (kd, _) in enumerate(marks)]
        (out / ("inj-t2ms_r%d.jsonl" % r)).write_text("".join(json.dumps(x) + "\n" for x in inj))
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "states.log").write_text("\n".join(states) + "\n")
    (out / "logins.txt").write_text("accepted=%d\n" % logins)


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_a_window_that_survives_and_a_tail_that_drops_hold_everything(tmp_path):
    _run(tmp_path / "o", 24, h_tail=False)
    s = _report(tmp_path / "o")
    assert "states {'G': 12, 'H': 12}" in s and "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_a_window_that_needs_the_desktop_refutes_p1_and_p3(tmp_path):
    _run(tmp_path / "o", 24, h_window=10.0)
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P3") and "-> REFUTED" in _line(s, "P2"), s


def test_a_login_or_a_desktop_in_the_wrong_state_voids_and_another_k_is_not_scored(tmp_path):
    _run(tmp_path / "o", 24, logins=1)
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M6") and all("VOID (M6 failed)" in _line(s, p) for p in ("P1", "P2", "P3")), s
    _run(tmp_path / "p", 24, desktop_bad=True)
    s = _report(tmp_path / "p")
    assert "-> FAILED" in _line(s, "M3") and "VOID (M3 failed)" in _line(s, "P2"), s
    _run(tmp_path / "q", 4)
    assert "not scored (k=4; the prediction is for k=24)" in _report(tmp_path / "q")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("H's U excess is >= 0.5x G's", "H's out p99 is <= 0.9x G's", "H's tj excess is >= 0.5x G's",
              "no SSH login was accepted during the rounds", "It is not to be amended", "Scored only at k = 24",
              "The owner agreed to this knowing it closes the board's graphical session"):
        assert s in head, s
