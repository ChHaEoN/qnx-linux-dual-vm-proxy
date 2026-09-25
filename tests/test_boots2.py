"""The boot-interaction test (Phase 3b / A6, 2026-09-25): the six-boot report on synthetic boots
with two arms, and the harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import boots2_report as b2  # noqa: E402

REPORT = os.path.join(GC, "boots2_report.py")
HARNESS = os.path.join(GC, "run-boots2.sh")
BASH = shutil.which("bash")
TAGS = ("b1", "b2", "b3", "b4", "b5", "b6")


def _boot(out, tag, shift, fast_shift, tick=12.0, k=8, uptime=900, n=1000, warm=200, seed=6):
    out.mkdir(parents=True)
    rng = random.Random(seed + int(tag[1]))
    (out / "stamp.json").write_text(json.dumps({"boot_tag": tag, "boot": "cmdline isolcpus/irqaffinity: 0 token(s);"
                                                " uptime at preflight %d s" % uptime}))
    clog = []
    for r in range(1, k + 1):
        for w in ("before", "after"):
            clog.append("round %d %s udevd=0-5 pid1=0-5 gnome-shell=0-5 qemu=0-2" % (r, w))
        base = 1e9 + r * 1e7
        lines, slow, fast = [], [], []
        rs = rng.gauss(0, 1.0)
        for i in range(warm + n):
            t0 = 137.0 + i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i < warm:
                continue
            v = 180.0 + shift + rs + 8.0 * rng.random()
            if t0 % 4000.0 >= 3850.0:
                v += tick
            slow.append(v / 1000.0)
            fast.append((140.0 + fast_shift + rs + 8.0 * rng.random()) / 1000.0)
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(lines) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": slow}))
        (out / ("lat-t200us_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": fast}))
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _six(tmp, shifts, fast_shifts, **kw):
    dirs = []
    for tag, s, f in zip(TAGS, shifts, fast_shifts):
        _boot(tmp / tag, tag, s, f, **kw)
        dirs.append(str(tmp / tag))
    return dirs


def _report(args):
    r = subprocess.run([sys.executable, REPORT] + args + ["1000", "200"], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


SHIFTS = [0, 8, 3, 12, 5, 1]


def test_a_boot_that_shifts_both_arms_alike_holds_everything(tmp_path):
    s = _report(_six(tmp_path, SHIFTS, SHIFTS))
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_a_boot_that_moves_one_arm_only_refutes_p2_and_p3(tmp_path):
    s = _report(_six(tmp_path, SHIFTS, [0] * 6))
    assert "-> HELD" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> REFUTED" in _line(s, "P3"), s


def test_an_unsettled_boot_voids_and_one_boot_reports(tmp_path):
    d = _six(tmp_path, SHIFTS, SHIFTS)
    shutil.rmtree(d[3])
    _boot(tmp_path / "b4", "b4", 12, 12, uptime=200)
    s = _report(d)
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P2"), s
    s = _report(["--one", d[0]])
    assert "b1  rounds 8 aligned 8" in s and "DIFF" in s, s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("ICC(p50 t2ms) >= 0.5", "SD_between(DIFF) <= 0.5 x SD_between(p50 t2ms)", "ICC(p50 t200us) >= 0.5",
              "max - min per-boot SLOWDOWN <= 4 us", ">= 200 out-class t2ms exchanges in the tick bin",
              "none of them counts an\n# outcome the prediction is about", "It is not to be amended",
              "Scored only with six boots at k = 8", "changing no setting"):
        assert s in head, s
    assert "boots2_report.py" in body and "INTERVAL_MS=0.2" in body and 'ARMS=(t2ms t200us)' in body
