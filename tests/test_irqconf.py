"""The interrupt-placement test (Phase 3b / A6, 2026-09-29): the pieces of the rule
run-irqconf.sh fixed before any run, the report end to end on synthetic rounds, and the
harness's header. Every number here is synthetic."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "ci"))
import irqconf_report as ir  # noqa: E402
import results_guard as rg  # noqa: E402

REPORT = os.path.join(GC, "irqconf_report.py")
HARNESS = os.path.join(GC, "run-irqconf.sh")
BASH = shutil.which("bash")


def test_device_near_uses_the_lead_and_the_round_trip():
    dev = [10000.0]
    assert ir.device_near(10400.0, 200.0, dev)        # 400 us before t0: inside the lead
    assert not ir.device_near(10600.0, 200.0, dev)    # 600 us before: outside
    assert ir.device_near(9900.0, 200.0, dev)         # during the exchange
    assert not ir.device_near(9700.0, 200.0, dev)     # after it
    assert not ir.device_near(5000.0, 200.0, [])


def test_lift_is_the_tail_share_over_the_rest():
    res = [(True, True)] * 3 + [(False, True)] * 7 + [(True, False)] * 10 + [(False, False)] * 90
    assert abs(ir.lift(res) - 3.0) < 1e-9
    assert ir.lift([(False, True), (False, False)]) != ir.lift([(False, True), (False, False)])   # nan


def _run(out, k, dev_cost=80.0, bad_state=False, move_fails=False, n=1000, warm=200, seed=11):
    """Requests every 2250 us from 137 us past the host grid. Guest timer events one in every
    2000 us. In dflt a device interrupt about every 20 ms on core 0; an exchange with one in
    [t0 - 500, t0 + rtt] adds `dev_cost` us with probability 0.6. In moved the interrupts go
    to core 3 (or, with move_fails, stay on 0 and cost the same). 1 in 300 exchanges +50 us."""
    out.mkdir(parents=True)
    rng = random.Random(seed)
    clog, order = [], []
    for r in range(1, k + 1):
        for w in ("before", "after"):
            want = "0-5" if (bad_state and r == 2) else "3,5"
            clog.append("round %d %s udevd=%s pid1=%s gnome-shell=%s qemu=0-2" % (r, w, want, want, want))
        arms = ("dflt", "moved") if r % 2 else ("moved", "dflt")
        order.append("round %d order: %s" % (r, " ".join(arms)))
        for j, arm in enumerate(arms):
            tag = "%s_r%d" % (arm, r)
            base = 1e9 + r * 1e7 + j * 4e6
            span = (warm + n) * 2250.0
            gev = [g * 2000.0 + 1000.0 * rng.random() for g in range(int(span / 2000.0) + 2)]
            dev = sorted(rng.uniform(0, span) for _ in range(int(span / 20000.0)))
            on_measured = arm == "dflt" or move_fails
            lines, samples = [], []
            for i in range(warm + n):
                t0 = 137.0 + i * 2250.0
                lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
                if i < warm:
                    continue
                v = 180.0 + 8.0 * rng.random()
                if on_measured and ir.device_near(t0, v, dev) and rng.random() < 0.6:
                    v += dev_cost
                elif rng.random() < 1.0 / 300:
                    v += 50.0
                samples.append(v / 1000.0)
            tk = ["%.6f 001 I kvm" % ((base + g) / 1e6) for g in gev[::2]]
            tk += ["%.6f 002 H kvm_bg_timer_expire" % ((base + g) / 1e6) for g in gev[1::2]]
            tk += ["%.6f 000 I IPI" % ((base + g + 7.0) / 1e6) for g in gev]
            if on_measured:
                tk += ["%.6f 000 I rtl88x2ce" % ((base + d) / 1e6) for d in dev]
            (out / ("tk-%s.log" % tag)).write_text("\n".join(sorted(tk, key=lambda x: float(x.split()[0]))) + "\n")
            (out / ("tp-%s.log" % tag)).write_text("\n".join(lines) + "\n")
            (out / ("lat-%s.json" % tag)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
            c0, c3 = (len(dev), 0) if on_measured else (0, len(dev))
            (out / ("irq-%s.before" % tag)).write_text("277: 1000 0 0 500 0 0\n")
            (out / ("irq-%s.after" % tag)).write_text("277: %d 0 0 %d 0 0\n" % (1000 + c0, 500 + c3))
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag)[1].split("\n")[0]


def test_interrupts_that_cost_the_tail_hold_everything(tmp_path):
    _run(tmp_path / "o", 40)
    s = _report(tmp_path / "o")
    for m in ("M1", "M2", "M3", "M4", "M5"):
        assert "FAILED" not in _line(s, m), s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_harmless_interrupts_refute_the_mechanism(tmp_path):
    _run(tmp_path / "a", 40, dev_cost=0.0)
    s = _report(tmp_path / "a")
    assert "-> REFUTED" in _line(s, "P4") and "-> HELD" in _line(s, "P3"), s
    assert "-> HELD" not in _line(s, "P1"), s


def test_failed_checks_void(tmp_path):
    _run(tmp_path / "a", 40, bad_state=True)
    s = _report(tmp_path / "a")
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P1"), s
    _run(tmp_path / "b", 40, move_fails=True)
    s = _report(tmp_path / "b")
    assert "-> FAILED" in _line(s, "M4") and "VOID (M4 failed)" in _line(s, "P2"), s
    _run(tmp_path / "c", 4)
    assert "not scored (k=4; the prediction is for k=40)" in _report(tmp_path / "c")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("median DIFF(p99) <= -3 us", "EXCESS <= 0.8%", "|median DIFF(p50)| <= 2 us", "LIFT >= 3",
              "[t0 - 500 us, t0 + its", "It is not to be amended", "Scored only at k = 40",
              "an exploration, not a test", "never recorded", "odd rounds dflt then moved"):
        assert s in head, s
    assert "irqconf_report.py" in body and 'BG=""' in body and "irq_set restore" in body


def test_what_is_known_names_records_and_quotes_no_figure():
    """The pre-registration's WHAT IS KNOWN passes the results guard with nothing allowlisted."""
    text = open(HARNESS, encoding="utf-8").read()
    known = rg.known_sections(text)
    assert len(known) >= 5 and "20260929T-a6-orin-residual" in " ".join(line for _n, line in known)
    assert [f for _n, line in known for f in rg.figures(line)] == []
