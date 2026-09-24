"""The host's share of the tail (Phase 3b / A6, 2026-09-24): hostact_trace.py's
reduction and its charge of a window, the scoring run-tailhost.sh fixed before any
run, the report end to end on synthetic rounds, and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import hostact_trace as hat  # noqa: E402
import tailhost_report as th  # noqa: E402

REPORT = os.path.join(GC, "tailhost_report.py")
HARNESS = os.path.join(GC, "run-tailhost.sh")
BASH = shutil.which("bash")

RAW = """# tracer: nop
#
# entries-in-buffer/entries-written: 9/9   #P:6
#
#           TASK-PID     CPU#  |||||  TIMESTAMP  FUNCTION
#              | |         |   |||||     |         |
       CPU 0/KVM-4101    [001] d.h1.   700.000100: irq_handler_entry: irq=11 name=kvm guest vtimer
       CPU 0/KVM-4101    [001] d.h1.   700.000104: irq_handler_exit: irq=11 ret=handled
       CPU 0/KVM-4101    [001] ..s1.   700.000105: softirq_entry: vec=1 [action=TIMER]
       CPU 0/KVM-4101    [001] ..s1.   700.000130: timer_expire_entry: timer=00000000deadbeef function=delayed_work_timer_fn now=4295067296 baseclk=4295067296
       CPU 0/KVM-4101    [001] ..s1.   700.000140: softirq_exit: vec=1 [action=TIMER]
  qemu-system-aar-4100    [000] d..2.   700.000200: sched_switch: prev_comm=qemu-system-aar prev_pid=4100 prev_prio=120 prev_state=R+ ==> next_comm=kworker/0:1 next_pid=77 next_prio=120
     kworker/0:1-77      [000] d..2.   700.000240: sched_switch: prev_comm=kworker/0:1 prev_pid=77 prev_prio=120 prev_state=I ==> next_comm=qemu-system-aar next_pid=4100 next_prio=120
          <idle>-0       [002] d.h1.   700.000300: ipi_entry: (Function call interrupts)
          <idle>-0       [002] d.h1.   700.000302: ipi_exit: (Function call interrupts)
"""
MAP = "m:4100,v0:4101,v1:4102,q:4103"


def test_reduce_keeps_roles_classes_and_keys_and_no_names():
    out, err = hat.reduce(RAW.splitlines(True), hat.parse_map(MAP))
    assert err is None, err
    assert out == [
        "700.000100 001 HE 11 kvm_guest_vtimer",
        "700.000104 001 HX 11",
        "700.000105 001 SE 1 TIMER",
        "700.000130 001 TE delayed_work_timer_fn 4295067296",
        "700.000140 001 SX 1 TIMER",
        "700.000200 000 SW m R+ kw",
        "700.000240 000 SW kw I m",
        "700.000300 002 PE Function_call_interrupts",
        "700.000302 002 PX Function_call_interrupts",
    ]
    assert not any("kworker" in l or "4100" in l or "deadbeef" in l for l in out)


def test_reduce_refuses_lost_events_and_unparsed_lines():
    lost = RAW.replace("9/9", "9/12")
    assert "lost events" in hat.reduce(lost.splitlines(True), hat.parse_map(MAP))[1]
    bad = RAW + "  foo-1 [000] d..2. 700.1: sched_wakeup: comm=foo pid=1\n"
    assert "unparsed line" in hat.reduce(bad.splitlines(True), hat.parse_map(MAP))[1]
    nohead = "\n".join(l for l in RAW.splitlines() if "entries-in-buffer" not in l)
    assert "no entries-in-buffer" in hat.reduce(nohead.splitlines(True), hat.parse_map(MAP))[1]


def test_map_allows_many_q_but_one_of_each_other_role():
    assert hat.parse_map("m:1,v0:2,v1:3,q:4,q:5") == {1: "m", 2: "v0", 3: "v1", 4: "q", 5: "q"}
    with pytest.raises(ValueError):
        hat.parse_map("m:1,m:2")
    with pytest.raises(ValueError):
        hat.parse_map("x:1")


def _ev(lines):
    ev = []
    for l in lines:
        f = l.split()
        ev.append((float(f[0]), int(f[1]), f[2], f[3:]))
    return sorted(ev, key=lambda e: e[0])


def test_charge_counts_own_handlers_once_and_preemption():
    act = hat.Activity(_ev([
        "0 1 SW idle S v0",
        "0 2 SW v1 S idle",
        "0 0 SW idle S m",
        "100 1 SE 1 TIMER", "110 1 HE 11 x", "115 1 HX 11", "130 1 SX 1 TIMER",   # softirq 25 + irq 5
        "150 2 PE Function_call_interrupts", "152 2 PX Function_call_interrupts",   # core 2 idle: not charged
        "200 0 SW m R kw", "240 0 SW kw S m",                                    # m preempted 40
        "300 0 SW m S idle",
        "400 0 SE 3 NET_RX", "410 0 SX 3 NET_RX",                                  # outside the window
    ]))
    c = act.charge(90, 250)
    assert (c["irq"], c["softirq"], c["ipi"], c["preempted"], c["unknown"]) == (5, 25, 0, 40, 0)
    assert c["keys"] == {"irq:x": 5, "softirq:TIMER": 25, "preempted:m": 40}
    assert act.charge(120, 125)["softirq"] == 5          # clipped to the window
    assert act.known_from([0, 1, 2]) == 0


def test_an_ipi_inside_its_ipi_interrupt_is_counted_once_as_the_ipi():
    # FOUND ON THE BOARD before any run: arm64 delivers an IPI as an interrupt named
    # IPI, so ipi_entry..ipi_exit sits inside irq_handler_entry..exit, and inside a
    # softirq when it lands in one.
    act = hat.Activity(_ev(["0 1 SW idle S v1", "100 1 SE 1 TIMER", "110 1 HE 1 IPI",
                            "111 1 PE Rescheduling_interrupts", "116 1 PX Rescheduling_interrupts",
                            "118 1 HX 1", "140 1 SX 1 TIMER"]))
    c = act.charge(0, 200)
    assert (c["ipi"], c["irq"], c["softirq"]) == (5, 3, 32)
    assert c["ipi"] + c["irq"] + c["softirq"] == 40


def test_a_sleeping_thread_switched_out_is_not_preempted_and_an_unknown_core_is_not_charged():
    act = hat.Activity(_ev(["10 0 SW m S kw", "50 0 SW kw S m", "60 3 SE 1 TIMER", "70 3 SX 1 TIMER"]))
    c = act.charge(0, 100)
    assert c["preempted"] == 0 and c["softirq"] == 0 and c["unknown"] == 10
    assert act.known_from([0, 3]) is None


def test_scoring():
    assert th.score_p1(0.4, 0.12, 0.5) == "HELD"
    assert th.score_p1(0.4, 0.12, -2.5) == "PARTIAL"
    assert th.score_p1(0.1, 0.12, 0.0) == "REFUTED"
    assert th.score_p2(0.5) == "HELD" and th.score_p2(0.2) == "PARTIAL" and th.score_p2(0.19) == "REFUTED"
    assert th.score_p3({"irq": 1, "softirq": 5, "ipi": 2, "preempted": 3}) == "HELD"
    assert th.score_p3({"irq": 1, "softirq": 5, "ipi": 2, "preempted": 6}) == "REFUTED"
    assert th.checks(22, 24, 950, 1000, 22, 941, 0.1) == {"M1": True, "M2": True, "M3": True, "M4": True, "M5": True}
    ok = th.checks(22, 24, 950, 1000, 21, 940, 0.09)
    assert not ok["M3"] and not ok["M4"] and not ok["M5"]
    assert th.wrap(31.5, 32) == -0.5 and th.wrap(16.0, 32) == 16.0


def _exchange(t0, a, b, c, d):
    ev = [(0, "X 130"), (a, "I 78 1 m"), (a + b, "K wait 1000 v0"), (a + b + c, "W m v0"), (a + b + c + d, "R 116")]
    return ["%.6f 001 %s" % ((t0 + t) / 1e6, e) for t, e in ev]


def _run(out, k, n=200, warm=20, inside=True):
    """Slow exchanges are the ones starting within 2 ms of the 32 ms grid; each has a
    100 us TIMER softirq on the vCPU's core (inside its window, or after it), and a
    timer callback 50 us after its start."""
    out.mkdir()
    for r in range(1, k + 1):
        bp, ha, samples = [], [], []
        base = 1_000_000 + r * 3_200_000
        ha.append("%.6f 001 SW idle S v0" % ((base - 1000) / 1e6))
        for i in range(warm + n):
            t0 = base + i * 2000
            segs = {"A": 18.0, "B": 10.0, "C": 97.0, "D": 21.0}
            slow = i >= warm and t0 % 32000 < 2000
            if slow:
                segs["C"] += 100.0
                s0 = t0 + (30 if inside else 400)
                ha += ["%.6f 001 SE 1 TIMER" % (s0 / 1e6), "%.6f 001 SX 1 TIMER" % ((s0 + 100) / 1e6)]
                ha.append("%.6f 001 TE delayed_work_timer_fn %d" % ((t0 + 50) / 1e6, t0 // 4000))
            bp += _exchange(t0, segs["A"], segs["B"], segs["C"], segs["D"])
            if i >= warm:
                samples.append((sum(segs.values()) + 40.0) / 1000.0)
        (out / ("bp-t2ms_r%d.log" % r)).write_text("\n".join(bp) + "\n")
        (out / ("ha-t2ms_r%d.log" % r)).write_text("\n".join(ha) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "200", "20"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_a_tail_made_of_softirqs_on_the_grid_holds_everything_at_k_24(tmp_path):
    _run(tmp_path / "o", 24)
    s = _report(tmp_path / "o")
    assert "rounds 24, aligned 24, with host activity 24" in s, s
    for m in ("M1", "M2", "M3", "M4", "M5"):
        assert "  %s " % m in s and "FAILED" not in s, s
    assert "P1  the tail's R at 32 ms 1.000" in s and "-0.05 ms from the timers' -> HELD" in s, s
    assert "P2  H's share of the summed excess 100.0% -> HELD" in s, s
    assert "P3  the largest class is softirq -> HELD" in s, s


def test_host_work_outside_the_windows_refutes_p2_and_leaves_p3_unscored(tmp_path):
    _run(tmp_path / "o", 24, inside=False)
    s = _report(tmp_path / "o")
    assert "P2  H's share of the summed excess 0.0% -> REFUTED" in s, s
    assert "P3  the largest class is" in s and "not scored (P2 REFUTED" in s, s


def test_a_missing_host_trace_voids_everything_and_another_k_is_not_scored(tmp_path):
    out = tmp_path / "o"
    _run(out, 24)
    os.remove(out / "ha-t2ms_r5.log")
    s = _report(out)
    assert "M3 host-activity trace for 23 of 24 aligned rounds (want all) -> FAILED" in s, s
    assert s.count("-> VOID (M3") == 3, s          # M4 fails with it: round 5's windows have no known task
    _run(tmp_path / "p", 4)
    assert "not scored (k=4; the prediction is for k=24)" in _report(tmp_path / "p")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(HARNESS, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("at or above its round's p99 round trip", "the p99 of 1000 random subsets",
              "within\n#      2 ms of the traced timer callbacks' mean phase",
              "is >= 50% of their summed traced-span excess", "REFUTED if < 20%",
              "softirq time is the largest of the four classes", "Not scored if\n#      P2 is REFUTED",
              "Exploratory, and stated so it is not mistaken for\n# a blind test", ">= 99% of segmented windows"):
        assert s in head, s
