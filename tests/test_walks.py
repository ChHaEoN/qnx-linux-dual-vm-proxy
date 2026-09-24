"""The walk test (Phase 3b / A6, 2026-09-24): the scoring run-walks.sh fixed before any run,
the report end to end on synthetic rounds, the injector's new kinds, and the harness's
header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import walks_report as wr  # noqa: E402

REPORT = os.path.join(GC, "walks_report.py")
HARNESS = os.path.join(GC, "run-walks.sh")
SRC = os.path.join(GC, "burst_inject.c")
BASH = shutil.which("bash")
ORDER = ["U", "N", "P", "F", "A"]


def test_the_kinds_and_their_classes():
    assert wr.KINDS == ("U", "N", "P", "F", "A") and wr.BURSTS == ("P", "F", "A")
    marks = {"P": [10_000.0], "F": [50_000.0]}
    assert wr.classify(17_900.0, [], marks, []) == "P" and wr.classify(50_100.0, [], marks, []) == "F"


def _run(out, k, slow=("U", "P", "A"), n=1000, warm=200, seed=10):
    out.mkdir()
    rng = random.Random(seed)
    for r in range(1, k + 1):
        base = 1e9 + r * 10e6
        kinds = ORDER[r % 5:] + ORDER[:r % 5]
        marks = [(kd, 800_000.0 + 350_000.0 * i) for i, kd in enumerate(kinds)]
        tj = [600_000.0, 1_624_000.0]
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in tj]
        lines += ["%.6f 005 M %s %d" % ((base + t) / 1e6, kd, i) for i, (kd, t) in enumerate(marks)]
        slow_at = [t for kd, t in marks if kd in slow] + tj
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
                "dur_us": 100.0 if kd == "U" else (0.3 if kd == "N" else 3040.0), "iters": 0 if kd == "N" else 60}
               for i, (kd, _) in enumerate(marks)]
        (out / ("inj-t2ms_r%d.jsonl" % r)).write_text("".join(json.dumps(x) + "\n" for x in inj))
    (out / "logins.txt").write_text("accepted=0\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_a_sysfs_specific_window_holds_everything(tmp_path):
    _run(tmp_path / "o", 24)
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_a_window_from_any_walk_refutes_p2_and_none_refutes_p1_p3(tmp_path):
    _run(tmp_path / "o", 24, slow=("U", "P", "F", "A"))
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P1"), s
    _run(tmp_path / "p", 24, slow=("U",))
    s = _report(tmp_path / "p")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P3") and "-> HELD" in _line(s, "P4"), s


def test_the_injector_source_has_the_walks_and_makes_the_tmpfs_tree_before_the_round():
    src = open(SRC, encoding="utf-8").read()
    assert '"sys", "devices", "virtual", "dmi", "id", "sys_vendor"' in src
    assert '"run", "tjinj-walk", "a", "b", "c", "d"' in src
    assert src.index('mkdir(d[i], 0755)') < src.index("clock_nanosleep")
    assert 'fstatat(nfd, "", &st, AT_EMPTY_PATH)' in src and 'strchr("UNCMTSPFA"' in src


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("P's excess is >= +20 us", "F's excess is below +10 us", "A's excess is >= +20 us",
              "U's excess is >= +20 us", "N's excess is within +-10 us", "not mistaken for a blind test",
              "It is not to be amended", "Scored only at k = 24"):
        assert s in head, s
