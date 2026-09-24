"""The tail decomposition (Phase 3b / A6, 2026-09-24): the alignment of trace and
probe, the tail rule run-tailpath.sh fixed before any run, the scoring of P1,
the report end to end on synthetic rounds, and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import tailpath_report as tp  # noqa: E402

REPORT = os.path.join(GC, "tailpath_report.py")
HARNESS = os.path.join(GC, "run-tailpath.sh")
BASH = shutil.which("bash")


def test_p1():
    base = {"A": 0.0, "B": 1.0, "D": 0.0, "rest": 2.0}
    assert tp.score_p1(dict(base, C=30.0), {"C": 0.6}) == "HELD"
    assert tp.score_p1(dict(base, C=30.0), {"C": 0.4}) == "PARTIAL"
    assert tp.score_p1(dict(base, C=1.5, rest=2.0), {"C": 0.9}) == "REFUTED"


def test_checks():
    assert tp.checks(22, 24, 950, 1000) == {"M1": True, "M2": True}
    assert tp.checks(21, 24, 950, 1000)["M1"] is False
    assert tp.checks(22, 24, 949, 1000)["M2"] is False


def test_alignment_needs_exactly_warmup_plus_n_requests():
    lat = {"samples_in_order": [0.18, 0.19]}
    rows = [{"k": 2, "total": 150.0}, {"k": 3, "total": 160.0}]
    assert tp.round_rows(lat, rows, 3, 2, 2) is None
    got = tp.round_rows(lat, rows, 4, 2, 2)
    assert [round(g[0], 3) for g in got] == [180.0, 190.0] and got[1][1]["total"] == 160.0


def _exchange(t0, a, b, c, d):
    """Reduced-trace lines of one exchange with segment lengths a, b, c, d (us)."""
    ev = [(0, "X 130"), (a, "I 78 1 m"), (a + b, "K wait 1000 v0"), (a + b + c, "W m v0"), (a + b + c + d, "R 116")]
    return ["%.6f 001 %s" % ((t0 + t) / 1e6, e) for t, e in ev]


def _run(out, k, n=200, warm=20, slow_seg="C"):
    out.mkdir()
    for r in range(1, k + 1):
        lines, samples = [], []
        for i in range(warm + n):
            segs = {"A": 18.0, "B": 10.0, "C": 97.0, "D": 21.0}
            slow = i >= warm and (i - warm) % 50 == 49          # 4 slow exchanges of 200: the top 2%
            if slow:
                segs[slow_seg] += 100.0
            lines += _exchange(1_000_000 + r * 1_000_000 + i * 2000, segs["A"], segs["B"], segs["C"], segs["D"])
            if i >= warm:
                samples.append((sum(segs.values()) + 40.0) / 1000.0)       # rest 40 us
        (out / ("bp-t2ms_r%d.log" % r)).write_text("\n".join(lines) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "200", "20"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_a_tail_in_c_is_found_and_scored_at_k_24(tmp_path):
    _run(tmp_path / "o", 24)
    s = _report(tmp_path / "o")
    assert "rounds 24, aligned 24" in s and "M1 aligned rounds 24/24" in s and "-> ok" in s
    assert "P1  the largest median excess is C's; C's share 100.0% -> HELD" in s, s


def test_a_tail_on_the_probe_side_refutes(tmp_path):
    out = tmp_path / "o"
    _run(out, 24, slow_seg="C")
    # Re-write the samples so the slow exchanges' extra time is outside A..D: "rest".
    for r in range(1, 25):
        p = out / ("lat-t2ms_r%d.json" % r)
        d = json.loads(p.read_text())
        d["samples_in_order"] = [v + (0.1 if (j % 50 == 49) else 0.0) for j, v in enumerate(d["samples_in_order"])]
        p.write_text(json.dumps(d))
    bp = out / "bp-t2ms_r1.log"
    for r in range(1, 25):                                   # and take C's extra out of the trace
        f = out / ("bp-t2ms_r%d.log" % r)
        lines = []
        for i in range(20 + 200):
            lines += _exchange(1_000_000 + r * 1_000_000 + i * 2000, 18.0, 10.0, 97.0, 21.0)
        f.write_text("\n".join(lines) + "\n")
    assert bp.exists()
    s = _report(out)
    assert "the largest median excess is rest's" in s and "-> REFUTED" in s, s


def test_not_scored_at_another_k(tmp_path):
    _run(tmp_path / "o", 4)
    s = _report(tmp_path / "o")
    assert "not scored (k=4; the prediction is for k=24)" in s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("at or above its\n# round's p99 round trip", "minus the\n# round's median of that segment",
              "C has the largest median excess of the five, and C's share of the summed\n#      excess is >= 50%",
              "REFUTED if another segment's median excess is larger", "in >= 90% of", ">= 95% of"):
        assert s in head, s


def test_a_stray_frame_into_the_tap_is_not_a_request(tmp_path):
    # FOUND BY THE SMOKE RUN: a 101-byte frame that was not the probe's counted as a
    # request, and its round could not be aligned with the probe's samples.
    out = tmp_path / "o"
    _run(out, 24)
    f = out / "bp-t2ms_r3.log"
    lines = f.read_text().splitlines()
    lines.insert(50, "%.6f 004 X 101" % (float(lines[49].split()[0]) + 1e-6))
    f.write_text("\n".join(lines) + "\n")
    s = _report(out)
    assert "rounds 24, aligned 24" in s and "not aligned" not in s, s
