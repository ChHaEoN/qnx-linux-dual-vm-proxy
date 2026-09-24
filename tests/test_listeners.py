"""The listener test (Phase 3b / A6, 2026-09-24): listeners_trace.py's reduction and CPU
attribution, the scoring run-listeners.sh fixed before any run, the report end to end
on synthetic rounds, and the harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import listeners_report as lr  # noqa: E402
import listeners_trace as lt  # noqa: E402

REPORT = os.path.join(GC, "listeners_report.py")
HARNESS = os.path.join(GC, "run-listeners.sh")
BASH = shutil.which("bash")

RAW = """# tracer: nop
#
# entries-in-buffer/entries-written: 3/3   #P:6
#
          <idle>-0       [003] d..2.   900.000100: sched_switch: prev_comm=swapper/3 prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=systemd-udevd next_pid=268 next_prio=120
   systemd-udevd-268     [003] d..2.   900.001100: sched_switch: prev_comm=systemd-udevd prev_pid=268 prev_prio=120 prev_state=S ==> next_comm=swapper/3 next_pid=0 next_prio=120
       CPU 0/KVM-4101    [001] d..2.   900.001200: sched_switch: prev_comm=CPU 0/KVM prev_pid=4101 prev_prio=120 prev_state=R ==> next_comm=CPU 1/KVM next_pid=4102 next_prio=120
"""


def test_reduce_keeps_who_ran_where():
    out, err = lt.reduce(RAW.splitlines(True))
    assert err is None, err
    assert out == ["900.000100 003 S systemd-udevd 268", "900.001100 003 S idle 0", "900.001200 001 S CPU_1/KVM 4102"]
    assert "lost events" in lt.reduce(RAW.replace("3/3", "3/5").splitlines(True))[1]
    assert "unparsed line" in lt.reduce((RAW + "  x-1 [000] d..2. 900.2: sched_wakeup: comm=x pid=1\n").splitlines(True))[1]


def test_runs_charge_cpu_inside_a_window():
    ev = [(0.0, 3, "idle", 0), (100.0, 3, "systemd-udevd", 268), (1100.0, 3, "idle", 0),
          (50.0, 1, "CPU_0/KVM", 4101), (900.0, 1, "gnome-shell", 2211), (1000.0, 1, "idle", 0)]
    runs = lt.Runs(sorted(ev))
    c = runs.cpu(0.0, 2000.0)
    assert c[("systemd-udevd", 268, 3)] == 1000.0 and c[("gnome-shell", 2211, 1)] == 100.0
    assert c[("CPU_0/KVM", 4101, 1)] == 850.0 and ("idle", 0, 3) not in c
    assert runs.cpu(600.0, 700.0)[("systemd-udevd", 268, 3)] == 100.0              # clipped
    assert ("CPU_0/KVM", 4101, 1) not in runs.cpu(0.0, 2000.0, lambda comm, pid: comm == "idle" or pid == 4101)


def test_classes_and_scoring():
    assert lr.klass("systemd-udevd") == "udevd" and lr.klass("(udev-worker)") == "udevd"
    assert lr.klass("kworker/u12:5") == "kworker" and lr.klass("gnome-shell") == "gnome-shell"
    assert lr.score_p1(0.5) == "HELD" and lr.score_p1(0.49) == "REFUTED"
    assert lr.score_p2(40.0, 20.0) == "HELD" and lr.score_p2(24.0, 5.0) == "PARTIAL"
    assert lr.score_p2(40.0, 30.0) == "PARTIAL" and lr.score_p2(40.0, 33.0) == "REFUTED"
    assert lr.score_p3(25.0) == "HELD" and lr.score_p3(24.9) == "REFUTED"


ROT = ["free", "c3", "c5", "c3", "c5", "free", "c5", "free", "c3"]


def _run(out, k, slow_arms=("free", "c3"), udev_core=None, n=1000, warm=200, seed=4):
    """Requests every 2250 us. Per round: tj reads at 1.2 s and 2.224 s, markers U at 0.9,
    1.5, 1.9 s and R at 2.4 s. After each U marker udevd runs 4 ms (on core 3 in c3, 5 in
    c5 and free unless udev_core says otherwise) and gnome-shell 0.5 ms on core 4; after R
    nothing. Exchanges 0..5 ms after a U marker are slow in slow_arms, and after a tj read
    in every arm; the rest take 200 us plus noise."""
    out.mkdir()
    rng = random.Random(seed)
    (out / "qemu-tids.txt").write_text("4100\n4101\n4102\n")
    order = []
    for r in range(1, k + 1):
        arm = ROT[(r - 1) % len(ROT)]
        order.append("round %d arm: %s" % (r, arm))
        base = 1e9 + r * 10e6
        marks = [("U", 900_000.0), ("U", 1_500_000.0), ("U", 1_900_000.0), ("R", 2_400_000.0)]
        tj = [1_200_000.0, 2_224_000.0]
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in tj]
        lines += ["%.6f 005 M %s %d" % ((base + t) / 1e6, kd, i) for i, (kd, t) in enumerate(marks)]
        uc = (udev_core or {}).get(arm, {"c3": 3, "c5": 5, "free": 5}[arm])
        sw = []
        for core in range(6):
            sw.append((base, core, "idle", 0))
        for kd, t in marks:
            if kd == "U":
                sw += [(base + t + 100, uc, "systemd-udevd", 268), (base + t + 4100, uc, "idle", 0),
                       (base + t + 200, 4, "gnome-shell", 2211), (base + t + 700, 4, "idle", 0)]
        for core in range(6):
            sw.append((base + 3_000_000.0, core, "idle", 0))
        (out / ("sw-t2ms_r%d.log" % r)).write_text("".join("%.6f %03d S %s %d\n" % (t / 1e6, c, comm, pid)
                                                           for t, c, comm, pid in sorted(sw)))
        slow_at = [t for kd, t in marks if kd == "U" and arm in slow_arms] + tj
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
    (out / "order.log").write_text("\n".join(order) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_udevd_slowing_only_from_qemus_l3_holds_everything(tmp_path):
    _run(tmp_path / "o", 24)
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    assert "arms {'free': 8, 'c3': 8, 'c5': 8}" in s, s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s
    assert "udevd's share of the U windows' excess CPU: 88.9%" in s, s        # 4 ms of 4.5


def test_udevd_slowing_from_either_l3_refutes_p2(tmp_path):
    _run(tmp_path / "o", 24, slow_arms=("free", "c3", "c5"))
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P2") and "-> HELD" in _line(s, "P1"), s


def test_a_pin_that_did_not_hold_voids_p2_and_another_k_is_not_scored(tmp_path):
    _run(tmp_path / "o", 24, udev_core={"c3": 4})
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M3") and "VOID (M3 failed)" in _line(s, "P2"), s
    assert "-> HELD" in _line(s, "P1") and "-> HELD" in _line(s, "P3"), s
    _run(tmp_path / "p", 4)
    assert "not scored (k=4; the prediction is for k=24)" in _report(tmp_path / "p")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("udevd's excess is >= 50% of the free arm's excess total",
              "the U class's tail rate with udevd on core 3 is >= 25% and >= 2x the\n#      rate with udevd on core 5",
              "REFUTED if the core-3 rate is below 1.25x the\n#      core-5 rate", "It is not to be amended",
              "Scored only at k = 24", "Every udevd process gets its original affinity back at the end",
              "not mistaken for a blind test"):
        assert s in head, s
