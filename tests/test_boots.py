"""The boot-variation test (Phase 3b / A6, 2026-09-25): the variance components, the six-boot
report on synthetic boots, and the harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import boots_report as bo  # noqa: E402

REPORT = os.path.join(GC, "boots_report.py")
HARNESS = os.path.join(GC, "run-boots.sh")
BASH = shutil.which("bash")


def test_components_find_a_boot_effect_and_its_absence():
    w, b, icc = bo.components([[10, 11, 10, 11], [20, 21, 20, 21], [30, 31, 30, 31]])
    assert b > 50 and icc > 0.95
    w, b, icc = bo.components([[10, 20, 10, 20], [10, 20, 10, 20], [10, 20, 10, 20]])
    assert b == 0.0 and icc == 0.0


def _boot(out, tag, shift, tick=11.0, k=8, uptime=900, tokens=0, qemu="0-2", n=1000, warm=200, seed=4):
    out.mkdir(parents=True)
    rng = random.Random(seed + int(tag[1]))
    (out / "stamp.json").write_text(json.dumps({"boot_tag": tag, "boot": "cmdline isolcpus/irqaffinity: %d token(s);"
                                                " uptime at preflight %d s" % (tokens, uptime)}))
    clog = []
    for r in range(1, k + 1):
        for w in ("before", "after"):
            clog.append("round %d %s udevd=0-5 pid1=0-5 gnome-shell=0-5 qemu=%s" % (r, w, qemu))
        base = 1e9 + r * 1e7
        lines, samples = [], []
        rshift = shift + rng.gauss(0, 1.0)
        for i in range(warm + n):
            t0 = 137.0 + i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i < warm:
                continue
            v = 180.0 + rshift + 8.0 * rng.random()
            if t0 % 4000.0 >= 3850.0:
                v += tick + (60.0 if rng.random() < 0.2 else 0.0)
            elif rng.random() < 1.0 / 200:
                v += 50.0
            samples.append(v / 1000.0)
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(lines) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _six(tmp, shifts, **kw):
    dirs = []
    for tag, s in zip(bo.TAGS, shifts):
        d = tmp / tag
        _boot(d, tag, s, **kw)
        dirs.append(str(d))
    return dirs


def _report(args):
    r = subprocess.run([sys.executable, REPORT] + args + ["1000", "200"], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_boots_that_differ_hold_everything(tmp_path):
    s = _report(_six(tmp_path, [0, 8, 3, 12, 5, 1]))
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_boots_alike_refute_and_a_moving_tick_refutes_p4(tmp_path):
    s = _report(_six(tmp_path / "a", [0, 0, 0, 0, 0, 0]))
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2") and "-> REFUTED" in _line(s, "P3"), s
    d = _six(tmp_path / "b", [0, 8, 3, 12, 5, 1])
    shutil.rmtree(d[2])
    _boot(tmp_path / "b" / "b3", "b3", 3, tick=25.0)
    s = _report(d)
    assert "-> REFUTED" in _line(s, "P4"), s


def test_an_unsettled_or_changed_boot_voids(tmp_path):
    d = _six(tmp_path / "a", [0, 8, 3, 12, 5, 1])
    shutil.rmtree(d[4])
    _boot(tmp_path / "a" / "b5", "b5", 5, uptime=300)
    s = _report(d)
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P1"), s
    s = _report(["--one", d[0]])
    assert "b1  rounds 8 aligned 8" in s, s
    s = _report([d[1], d[0]] + d[2:])
    assert "not scored" in _line(s, "P1"), s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("max BOOT P50 - min BOOT P50 >= 5 us", "ICC(p50) >= 0.5", "max BOOT P99 - min BOOT P99 >= 10 us",
              "max - min per-boot SLOWDOWN <= 4 us", "It is not to be amended", "Scored only with six boots at k = 8",
              "The owner asked for", "changing no setting"):
        assert s in head, s
    assert "boots_report.py" in body and 'set_units "$CONF' not in body and "SETTLE_S" in body
