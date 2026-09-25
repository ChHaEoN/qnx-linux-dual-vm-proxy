"""The confinement test (Phase 3b / A6, 2026-09-25): the arm and state checks, the scoring
run-confine.sh fixed before any run, the report end to end on synthetic rounds, and the
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
import confine_report as cr  # noqa: E402

REPORT = os.path.join(GC, "confine_report.py")
HARNESS = os.path.join(GC, "run-confine.sh")
BASH = shutil.which("bash")
PAT = ["open", "confined", "confined", "open"]


def test_scoring():
    assert cr.score_keep(20.0, 40.0) == "HELD" and cr.score_keep(19.9, 40.0) == "REFUTED"
    assert cr.score_lower(270.0, 300.0) == "HELD" and cr.score_lower(271.0, 300.0) == "REFUTED"
    assert cr.score_same(182.0, 180.0) == "HELD" and cr.score_same(182.1, 180.0) == "REFUTED"


def _run(out, k, u_conf=40.0, tail_conf=True, p50_shift=0.0, bad_state=False, qemu_moved=False,
         n=1000, warm=200, seed=12):
    """Requests every 2250 us; tj reads at 0.6 and 1.624 s; markers U at 0.8, 1.2, 2.0 s and
    N at 1.9 s. Exchanges 0..5 ms after a U marker or a tj read are 60 us slower when open
    and u_conf us slower when confined. The out class has a rare +600 us tail (1 in 300)
    open, and confined only if tail_conf."""
    out.mkdir()
    rng = random.Random(seed)
    order, clog = [], []
    for r in range(1, k + 1):
        arm = PAT[(r - 1) % 4]
        order.append("round %d arm: %s" % (r, arm))
        want = "3,5" if arm == "confined" else "0-5"
        if bad_state and r == 2:
            want = "0-5"
        q = "0-2" if not (qemu_moved and r == 3) else "0-2 3,5"
        for w in ("before", "after"):
            clog.append("round %d %s udevd=%s pid1=%s gnome-shell=%s qemu=%s" % (r, w, want, want, want, q))
        base = 1e9 + r * 10e6
        marks = [("U", 800_000.0), ("U", 1_200_000.0), ("N", 1_900_000.0), ("U", 2_000_000.0)]
        tj = [600_000.0, 1_624_000.0]
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in tj]
        lines += ["%.6f 005 M %s %d" % ((base + t) / 1e6, kd, i) for i, (kd, t) in enumerate(marks)]
        slow_at = [t for kd, t in marks if kd == "U"] + tj
        add = 60.0 if arm == "open" else u_conf
        samples = []
        for i in range(warm + n):
            t0 = i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i >= warm:
                v = 180.0 + (p50_shift if arm == "confined" else 0.0) + 8.0 * rng.random()
                if any(0 <= t0 - s <= 5000.0 for s in slow_at):
                    v += add
                elif (arm == "open" or tail_conf) and rng.random() < 1.0 / 300:
                    v += 600.0
                samples.append(v / 1000.0)
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(sorted(lines, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
        inj = [{"i": i, "kind": kd, "t_ns": 0, "seq_before": 10, "seq_after": 13 if kd == "U" else 10,
                "dur_us": 100.0, "iters": 3 if kd == "U" else 0} for i, (kd, _) in enumerate(marks)]
        (out / ("inj-t2ms_r%d.jsonl" % r)).write_text("".join(json.dumps(x) + "\n" for x in inj))
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_arms_and_state_checks(tmp_path):
    _run(tmp_path / "o", 4)
    arms = cr.arms_of(str(tmp_path / "o"))
    assert arms == {1: "open", 2: "confined", 3: "confined", 4: "open"}
    assert cr.conf_checks(str(tmp_path / "o"), arms) == (4, 4, 4)


def test_a_window_that_stays_and_a_tail_that_drops_hold_everything(tmp_path):
    _run(tmp_path / "o", 24, u_conf=40.0, tail_conf=False)
    s = _report(tmp_path / "o")
    assert "arms {'open': 12, 'confined': 12}" in s and "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_a_window_that_goes_refutes_p1_p2_and_a_shift_refutes_p4(tmp_path):
    _run(tmp_path / "o", 24, u_conf=10.0, tail_conf=True, p50_shift=5.0)
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2"), s
    assert "-> REFUTED" in _line(s, "P3") and "-> REFUTED" in _line(s, "P4"), s


def test_a_confinement_that_did_not_hold_or_a_moved_qemu_voids(tmp_path):
    _run(tmp_path / "o", 24, bad_state=True)
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M3") and all("VOID (M3 failed)" in _line(s, p) for p in ("P1", "P3")), s
    _run(tmp_path / "p", 24, qemu_moved=True)
    s = _report(tmp_path / "p")
    assert "-> FAILED" in _line(s, "M7") and "VOID (M7 failed)" in _line(s, "P4"), s
    _run(tmp_path / "q", 4)
    assert "not scored (k=4; the prediction is for k=24)" in _report(tmp_path / "q")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("confined U excess >= 0.5x open's", "confined tj excess >= 0.5x open's",
              "confined p99.9 <= 0.9x open's", "|confined p50 - open p50| <= 2 us",
              "an EMPTY AllowedCPUs= does NOT undo it on systemd 249", "The owner chose this test",
              "It is not to be amended", "Scored only at k = 24"):
        assert s in head, s
