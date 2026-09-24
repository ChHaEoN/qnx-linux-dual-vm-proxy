"""The burst test (Phase 3b / A6, 2026-09-24): the classes and scoring run-bursts.sh fixed
before any run, the report end to end on synthetic rounds, the injector's source (built
and run if a compiler is here), and the harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import bursts_report as br  # noqa: E402

REPORT = os.path.join(GC, "bursts_report.py")
HARNESS = os.path.join(GC, "run-bursts.sh")
SRC = os.path.join(GC, "burst_inject.c")
BASH = shutil.which("bash")
CC = shutil.which("gcc") or shutil.which("cc")


def test_classes_and_scoring():
    marks = {"U": [10_000.0], "C": [50_000.0], "N": [90_000.0]}
    assert br.classify(17_900.0, [], marks, []) == "U" and br.classify(18_100.0, [], marks, []) == "out"
    assert br.classify(10_500.0, [10_000.0], marks, []) == "tj"
    assert br.classify(49_600.0, [], marks, []) == "C" and br.classify(95_000.0, [], marks, []) == "N"
    assert br.classify(200_000.0, [], marks, [199_000.0]) == "other"
    assert br.score_quiet(9.9) == "HELD" and br.score_quiet(10.0) == "REFUTED"
    assert br.score_slow(20.0) == "HELD" and br.score_slow(10.0) == "PARTIAL" and br.score_slow(9.9) == "REFUTED"


ORDER = ["U", "N", "C", "M", "T", "S"]


def _run(out, k, slow=("U", "M", "T"), null_slow=False, logins=0, short=None, n=1000, warm=200, seed=8):
    """Requests every 2250 us; tj reads at 0.6 and 1.624 s; markers U N C M T S at 0.8,
    1.1, 1.4, 1.7, 2.0, 2.3 s (rotated each round). Exchanges 0..5 ms after a marker of a
    kind in slow (and after a tj read) are 50 us slower; the rest 180 us plus noise."""
    out.mkdir()
    rng = random.Random(seed)
    for r in range(1, k + 1):
        base = 1e9 + r * 10e6
        kinds = ORDER[r % 6:] + ORDER[:r % 6]
        marks = [(kd, 800_000.0 + 300_000.0 * i) for i, kd in enumerate(kinds)]
        tj = [600_000.0, 1_624_000.0]
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in tj]
        lines += ["%.6f 005 M %s %d" % ((base + t) / 1e6, kd, i) for i, (kd, t) in enumerate(marks)]
        slow_kinds = set(slow) | ({"N"} if null_slow else set())
        slow_at = [t for kd, t in marks if kd in slow_kinds] + tj
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
                "dur_us": (short if (short and kd == "M") else (80.0 if kd == "U" else (0.2 if kd == "N" else 3050.0))),
                "iters": 0 if kd == "N" else 5}
               for i, (kd, _) in enumerate(marks)]
        (out / ("inj-t2ms_r%d.jsonl" % r)).write_text("".join(json.dumps(x) + "\n" for x in inj))
    (out / "logins.txt").write_text("accepted=%d\n" % logins)


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_memory_and_tlb_windows_hold_everything(tmp_path):
    _run(tmp_path / "o", 24)
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4", "P5"):
        assert "-> HELD" in _line(s, p), s


def test_compute_and_syscall_windows_refute_p1_p4_and_quiet_memory_refutes_p2_p3(tmp_path):
    _run(tmp_path / "o", 24, slow=("U", "C", "S"))
    s = _report(tmp_path / "o")
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> REFUTED" in _line(s, p), s
    assert "-> HELD" in _line(s, "P5"), s


def test_a_slow_null_window_a_short_burst_or_a_login_voids(tmp_path):
    _run(tmp_path / "a", 24, null_slow=True)
    s = _report(tmp_path / "a")
    assert "-> FAILED" in _line(s, "M7") and "VOID (M7 failed)" in _line(s, "P2") and "-> HELD" in _line(s, "P5"), s
    _run(tmp_path / "b", 24, short=900.0)
    s = _report(tmp_path / "b")
    assert "-> FAILED" in _line(s, "M5") and "VOID (M5 failed)" in _line(s, "P1"), s
    _run(tmp_path / "c", 24, logins=2)
    s = _report(tmp_path / "c")
    assert all("VOID (M6 failed)" in _line(s, p) for p in ("P1", "P5")), s
    _run(tmp_path / "d", 4)
    assert "not scored (k=4; the prediction is for k=24)" in _report(tmp_path / "d")


@pytest.mark.skipif(CC is None or sys.platform.startswith("win"), reason="needs a POSIX C compiler")
def test_the_injector_builds_and_logs_every_kind(tmp_path):
    exe = tmp_path / "bi"
    subprocess.run([CC, "-O2", "-o", str(exe), SRC], check=True)
    (tmp_path / "zone").mkdir()
    (tmp_path / "zone" / "uevent").write_text("")
    (tmp_path / "marker").write_text("")
    (tmp_path / "seq").write_text("5\n")
    subprocess.run([str(exe), "--zone", str(tmp_path / "zone"), "--marker", str(tmp_path / "marker"), "--log",
                    str(tmp_path / "log"), "--seed", "3", "--start", "0.01", "--step", "0.02", "--jitter", "0",
                    "--seqnum", str(tmp_path / "seq")], check=True, timeout=30)
    rows = [json.loads(l) for l in (tmp_path / "log").read_text().splitlines()]
    assert sorted(x["kind"] for x in rows) == sorted(ORDER)
    assert all(2500 <= x["dur_us"] <= 3600 and x["iters"] > 0 for x in rows if x["kind"] in "CMTS")


def test_the_injector_source_allocates_before_the_round_and_marks_each_action():
    src = open(SRC, encoding="utf-8").read()
    assert src.index("memset(buf, 1, BUF)") < src.index("clock_nanosleep")
    assert 'snprintf(m, sizeof m, "tjinj %c %zu\\n"' in src and "munmap" in src and "SYS_getppid" in src


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("C's excess is below +10 us", "M's excess is >= +20 us", "T's excess is >= +20 us",
              "S's excess is below +10 us", "U's excess is >= +20 us", "N's excess is within +-10 us",
              "It is not to be amended", "Scored only at k = 24", "Nothing on the board is changed"):
        assert s in head, s
