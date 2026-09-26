"""The guest-clock intervention (Phase 3b / A6, 2026-09-26): the report on synthetic guest boots
at 1 kHz and 100 Hz, and the harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import clock_report as ck  # noqa: E402

REPORT = os.path.join(GC, "clock_report.py")
HARNESS = os.path.join(GC, "run-clock.sh")
BASH = shutil.which("bash")
PAT = ["A", "B", "B", "A", "A", "B", "B", "A"]


def _kvm(att, ok):
    c = lambda a, o: {"halt_attempted_poll": a, "halt_successful_poll": o}
    return {"before": {"counters": c(1000, 500)}, "after": {"counters": c(1000 + att, 500 + ok)}}


def _run(out, k_per=5, b_events=0.05, b_slower=70.0, b_poll=0.2, bad_period=False, n=1000, warm=200, seed=8):
    """A: a guest event every ~2 ms at a random phase, and an exchange whose first event falls
    0..150 us after t0 is +40 us; B: the same with events thinned to b_events and every
    exchange b_slower us slower. Poll success 0.6 in A, b_poll in B."""
    out.mkdir(parents=True)
    rng = random.Random(seed)
    order, clog, glog = [], [], []
    r = 0
    for g, arm in enumerate(PAT, 1):
        want = "1000000" if arm == "A" else "10000000"
        got = "1000000" if (bad_period and g == 2) else want
        glog.append("guest %d arm %s image ifs-clock.bin sha256 x clockctl period %s want %s" % (g, arm, got, want))
        for _ in range(k_per):
            r += 1
            order.append("round %d arm: %s guest %d" % (r, arm, g))
            for w in ("before", "after"):
                clog.append("round %d %s udevd=3,5 pid1=3,5 gnome-shell=3,5 qemu=0-2" % (r, w))
            base = 1e9 + r * 1e7
            gev = [j * 2000.0 + 1000.0 * rng.random() for j in range(int((warm + n) * 2250.0 / 2000.0) + 2)]
            if arm == "B":
                gev = [x for x in gev if rng.random() < b_events]
            lines, samples = [], []
            for i in range(warm + n):
                t0 = 137.0 + i * 2250.0
                lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
                if i < warm:
                    continue
                v = 180.0 + 8.0 * rng.random() + (b_slower if arm == "B" else 0.0)
                nxt = [x for x in gev if x >= t0][:1]
                if nxt and nxt[0] - t0 < 150.0 and rng.random() < 0.5:
                    v += 40.0
                elif rng.random() < 1.0 / 150:
                    v += 30.0
                samples.append(v / 1000.0)
            (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(lines) + "\n")
            (out / ("tk-t2ms_r%d.log" % r)).write_text("".join("%.6f 001 I kvm\n" % ((base + x) / 1e6) for x in gev))
            (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
            (out / ("kvm-t2ms_r%d.json" % r)).write_text(json.dumps(_kvm(1000, 600 if arm == "A" else int(1000 * b_poll))))
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "guests.log").write_text("\n".join(glog) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_a_thinned_slower_polling_less_guest_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_a_guest_the_clock_did_not_change_refutes(tmp_path):
    _run(tmp_path / "o", b_slower=0.0, b_poll=0.6)
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P2") and "-> REFUTED" in _line(s, "P3") and "-> HELD" in _line(s, "P1"), s


def test_a_wrong_period_or_an_untouched_timer_voids(tmp_path):
    _run(tmp_path / "a", bad_period=True)
    s = _report(tmp_path / "a")
    assert "-> FAILED" in _line(s, "M4") and "VOID (M4 failed)" in _line(s, "P1"), s
    _run(tmp_path / "b", b_events=1.0)
    s = _report(tmp_path / "b")
    assert "-> FAILED" in _line(s, "M4"), s
    _run(tmp_path / "c", k_per=1)
    assert "not scored (k=8; the prediction is for k=40)" in _report(tmp_path / "c")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("GUESTSHARE(B) <= 0.5 x GUESTSHARE(A)", "P50(B) - P50(A) >= +30 us", "POLL(B) <= 0.5 x POLL(A)",
              "EVENTS(B) <= EVENTS(A) / 3", "A B B A A B B A", "they are not blind", "ENOTSUP",
              "It is not to be amended", "Scored only at k = 40", "The owner asked for this test"):
        assert s in head, s
    assert "clock_report.py" in body and "guest_stop" in body and "sync" in body
