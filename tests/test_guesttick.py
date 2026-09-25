"""The guest-tick test (Phase 3b / A6, 2026-09-25): the classes, the scoring run-guesttick.sh
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
import guesttick_report as gr  # noqa: E402

REPORT = os.path.join(GC, "guesttick_report.py")
HARNESS = os.path.join(GC, "run-guesttick.sh")
BASH = shutil.which("bash")


def test_classes_by_the_first_event():
    ev = [1000.0, 1300.0]
    assert gr.klass(900.0, ev) == "DURING"          # first event 100 us after t0
    assert gr.klass(990.0, ev) is None              # 10 us after: no class
    assert gr.klass(800.0, ev) == "AFTER"           # 200 us after
    assert gr.klass(1010.0, ev) == "NONE"           # the next is 290 us away
    assert gr.klass(1400.0, ev) == "NONE"           # none left


def _run(out, k, during=40.0, after=40.0, bad_state=False, few_events=False, n=1000, warm=200, seed=9):
    """Requests every 2250 us from 137 us past the host grid (1 in 16 in the host tick bin,
    +10 us, 1 in 10 of those +60). One guest event in every 2000 us, at a random point of
    its first half. A first event 25..150 us after t0 adds `during` us with probability
    0.6; 175..250 us adds `after` likewise; 1 in 300 others +50 us."""
    out.mkdir(parents=True)
    rng = random.Random(seed)
    clog = []
    for r in range(1, k + 1):
        for w in ("before", "after"):
            want = "0-5" if (bad_state and r == 2) else "3,5"
            clog.append("round %d %s udevd=%s pid1=%s gnome-shell=%s qemu=0-2" % (r, w, want, want, want))
        base = 1e9 + r * 1e7
        gev = [j * 2000.0 + 1000.0 * rng.random() for j in range(int((warm + n) * 2250.0 / 2000.0) + 2)]
        gev = gev[::(20 if few_events else 1)]
        lines, samples = [], []
        for i in range(warm + n):
            t0 = 137.0 + i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i < warm:
                continue
            v = 180.0 + 8.0 * rng.random()
            if t0 % 4000.0 >= 3850.0:
                v += 10.0 + (60.0 if rng.random() < 0.1 else 0.0)
            else:
                nxt = [g for g in gev if g >= t0][:1]
                off = nxt[0] - t0 if nxt else 1e9
                if 25.0 <= off < 150.0 and rng.random() < 0.6:
                    v += during
                elif 175.0 <= off < 250.0 and rng.random() < 0.6:
                    v += after
                elif rng.random() < 1.0 / 300:
                    v += 50.0
            samples.append(v / 1000.0)
        tk = ["%.6f 001 I kvm" % ((base + g) / 1e6) for g in gev[::2]] + \
             ["%.6f 002 H kvm_bg_timer_expire" % ((base + g) / 1e6) for g in gev[1::2]]
        (out / ("tk-t2ms_r%d.log" % r)).write_text("\n".join(sorted(tk, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(lines) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_a_guest_tick_during_the_exchange_holds_everything(tmp_path):
    _run(tmp_path / "o", 40)
    s = _report(tmp_path / "o")
    assert "FAILED" not in _line(s, "M1") + _line(s, "M2") + _line(s, "M3") + _line(s, "M4"), s
    assert "-> HELD" in _line(s, "P1") and "-> HELD" in _line(s, "P2") and "-> HELD" in _line(s, "P4"), s
    assert "-> REFUTED" in _line(s, "P3"), s          # this synthetic host also slows AFTER exchanges


def test_no_effect_refutes_and_an_after_only_effect_is_seen(tmp_path):
    _run(tmp_path / "a", 40, during=0.0, after=0.0)
    s = _report(tmp_path / "a")
    assert "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P3"), s
    _run(tmp_path / "b", 40, during=40.0, after=0.0)
    s = _report(tmp_path / "b")
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_failed_checks_void(tmp_path):
    _run(tmp_path / "a", 40, after=0.0, bad_state=True)
    s = _report(tmp_path / "a")
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P1"), s
    _run(tmp_path / "b", 40, after=0.0, few_events=True)
    s = _report(tmp_path / "b")
    assert "-> FAILED" in _line(s, "M4") and "VOID" in _line(s, "P3"), s
    _run(tmp_path / "c", 4)
    assert "not scored (k=4; the prediction is for k=40)" in _report(tmp_path / "c")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("RATIO(DURING) >= 5", "SLOWDOWN >= +5 us", "RATIO(AFTER) <= 2", "COVER >= 0.4",
              "DURING  in [25, 150) us", "AFTER  in [175, 250) us", "chosen after looking at that record",
              "It is not to be amended", "Scored only at k = 40", "The owner asked for this test", "never recorded"):
        assert s in head, s
    assert "guesttick_report.py" in body and "kvm guest vtimer" in body and 'BG=""' in body
