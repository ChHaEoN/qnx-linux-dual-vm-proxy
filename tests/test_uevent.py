"""The uevent test (Phase 3b / A6, 2026-09-24): the injector, the reducer's markers,
the classes and scoring run-uevent.sh fixed before any run, the report end to end on
synthetic rounds, and the harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import tjphase_trace as tt  # noqa: E402
import uevent_report as ur  # noqa: E402

REPORT = os.path.join(GC, "uevent_report.py")
INJ = os.path.join(GC, "uevent_inject.py")
HARNESS = os.path.join(GC, "run-uevent.sh")
BASH = shutil.which("bash")

RAW = """# tracer: nop
#
# entries-in-buffer/entries-written: 2/2   #P:6
#
         python3-7000    [005] .....   900.000100: tracing_mark_write: tjinj U 2
     python3-5000    [004] ..s1.   900.000200: net_dev_xmit: dev=tap-qnx skbaddr=00000000abcdef01 len=130 rc=0
"""


def test_the_reducer_keeps_injection_markers_and_refuses_others():
    out, err = tt.reduce(RAW.splitlines(True))
    assert err is None, err
    assert out == ["900.000100 005 M U 2", "900.000200 004 X 130"]
    other = RAW.replace("tjinj U 2", "hello there")
    assert "not an injection's" in tt.reduce(other.splitlines(True))[1]


def test_the_injector_does_what_its_kinds_say(tmp_path):
    zone = tmp_path / "zone"
    zone.mkdir()
    (zone / "uevent").write_text("")
    (zone / "temp").write_text("48000\n")
    marker = tmp_path / "marker"
    marker.write_text("")
    seq = tmp_path / "seqnum"
    seq.write_text("100\n")
    log = tmp_path / "inj.jsonl"
    r = subprocess.run([sys.executable, INJ, "--zone", str(zone), "--marker", str(marker), "--log", str(log),
                        "--seed", "7", "--start", "0.01", "--step", "0.02", "--jitter", "0.0", "--seqnum", str(seq)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert sorted(x["kind"] for x in rows) == ["R", "R", "U", "U"] and [x["i"] for x in rows] == [0, 1, 2, 3]
    assert all(x["seq_before"] == 100 and x["seq_after"] == 100 for x in rows)
    marks = marker.read_text().splitlines()
    assert marks == ["tjinj %s %d" % (x["kind"], x["i"]) for x in rows]
    assert (zone / "uevent").read_text() == "change"        # a U wrote it
    assert (zone / "temp").read_text() == "48000\n"         # an R only read it


def test_classes_manipulation_and_scoring():
    inj = {"U": [10_000.0], "R": [50_000.0]}
    assert ur.classify(10_000.0 + 7_900.0, [], inj, []) == "U"
    assert ur.classify(10_000.0 + 8_100.0, [], inj, []) == "out"
    assert ur.classify(50_000.0 - 400.0, [], inj, []) == "R"
    assert ur.classify(10_500.0, [10_000.0], inj, []) == "tj"                 # the poll first
    assert ur.classify(90_000.0, [], inj, [89_000.0]) == "other"
    rows = [{"kind": "U", "seq_before": 1, "seq_after": 4}, {"kind": "U", "seq_before": 1, "seq_after": 3},
            {"kind": "R", "seq_before": 5, "seq_after": 5}, {"kind": "R", "seq_before": 5, "seq_after": 8}]
    assert ur.manip_ok(rows) == (1, 2, 1, 2)
    assert ur.score_hot(25.0) == "HELD" and ur.score_hot(10.0) == "PARTIAL" and ur.score_hot(9.99) == "REFUTED"
    assert ur.score_quiet(9.99) == "HELD" and ur.score_quiet(10.0) == "REFUTED"


def _run(out, k, slow_after=("U", "tj"), n=1000, warm=200, seed=3):
    """Requests every 2250 us. Per round: a tj read at 1.2 s and 2.224 s into the round,
    another zone's at 0.7 s, and four markers at 0.9, 1.5, 1.9, 2.4 s (U, R, U, R).
    Exchanges starting 0..5 ms after a mark of a kind in slow_after take 600 us; the
    rest 200 us plus up to 50 us of noise."""
    out.mkdir()
    rng = random.Random(seed)
    for r in range(1, k + 1):
        base = 1e9 + r * 10e6
        marks = [("U", 900_000.0), ("R", 1_500_000.0), ("U", 1_900_000.0), ("R", 2_400_000.0)]
        tj = [1_200_000.0, 2_224_000.0]
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in tj]
        lines.append("%.6f 003 T cpu-thermal" % ((base + 700_000.0) / 1e6))
        lines += ["%.6f 005 M %s %d" % ((base + t) / 1e6, kd, i) for i, (kd, t) in enumerate(marks)]
        slow_at = [t for kd, t in marks if kd in slow_after] + (tj if "tj" in slow_after else [])
        samples = []
        for i in range(warm + n):
            t0 = i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i >= warm:
                slow = any(0 <= t0 - s <= 5000.0 for s in slow_at)
                samples.append(0.6 if slow else 0.2 + 0.05 * rng.random())
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(sorted(lines, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
        inj = [{"i": i, "kind": kd, "t_ns": 0, "seq_before": 10, "seq_after": 13 if kd == "U" else 10, "dur_us": 50.0}
               for i, (kd, _) in enumerate(marks)]
        (out / ("inj-t2ms_r%d.jsonl" % r)).write_text("".join(json.dumps(x) + "\n" for x in inj))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_uevents_that_slow_and_reads_that_do_not_hold_everything(tmp_path):
    _run(tmp_path / "o", 24)
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_reads_that_slow_and_uevents_that_do_not_refute_p1_and_p2(tmp_path):
    _run(tmp_path / "o", 24, slow_after=("R", "tj"))
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P3"), s


def test_a_failed_manipulation_voids_p1_p2_and_another_k_is_not_scored(tmp_path):
    out = tmp_path / "o"
    _run(out, 24)
    for r in range(1, 25):                        # no U raised the seqnum
        p = out / ("inj-t2ms_r%d.jsonl" % r)
        rows = [json.loads(l) for l in p.read_text().splitlines()]
        p.write_text("".join(json.dumps(dict(x, seq_after=x["seq_before"])) + "\n" for x in rows))
    s = _report(out)
    assert "M2" in s and "-> FAILED" in _line(s, "M2"), s
    assert "VOID (M2 failed)" in _line(s, "P1") and "VOID (M2 failed)" in _line(s, "P2"), s
    assert "-> HELD" in _line(s, "P3"), s
    _run(tmp_path / "p", 4)
    assert "not scored (k=4; the prediction is for k=24)" in _report(tmp_path / "p")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("at or above its round's p99 round trip", "U class's tail rate is >= 25%",
              "R class's tail rate is below 10%", "tj class's tail\n#      rate is >= 25%",
              "raised the uevent\n#      seqnum by >= 3", "It is not to be amended", "Scored only at k = 24",
              "no mode, policy, trip or cooling state is written"):
        assert s in head, s
