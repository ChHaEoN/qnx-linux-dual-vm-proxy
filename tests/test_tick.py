"""The tick test (Phase 3b / A6, 2026-09-25): tick_trace.py's reducer and contexts, the
scoring run-tick.sh fixed before any run, the report end to end on synthetic rounds, and the
harness's header."""
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
import tick_report as tr  # noqa: E402
import tick_trace as tkt  # noqa: E402

REPORT = os.path.join(GC, "tick_report.py")
HARNESS = os.path.join(GC, "run-tick.sh")
BASH = shutil.which("bash")
PAT = ["light", "heavy", "heavy", "light"]
HDR = ["# tracer: nop", "#", "# entries-in-buffer/entries-written: 9/9   #P:6", "#"]
# The tick's hrtimer handler was renamed twice in mainline: tick_sched_timer up to 6.6,
# tick_nohz_highres_handler in 6.7 and 6.8, tick_nohz_handler from 6.9. The trace lines below
# are synthetic, in ftrace's layout; every value in them is made up. TICK stands for the name.
HANDLERS = ("tick_sched_timer", "tick_nohz_highres_handler", "tick_nohz_handler")
BODY_T = [
    "          <idle>-0       [001] d...2.. 100.000001: sched_switch: prev_comm=swapper/1 prev_pid=0 prev_prio=120 "
    "prev_state=R ==> next_comm=CPU 0/KVM next_pid=5001 next_prio=120",
    "          <idle>-0       [001] d..h1.. 100.004003: irq_handler_entry: irq=13 name=arch_timer",
    "          <idle>-0       [001] d..h1.. 100.004004: hrtimer_expire_entry: hrtimer=000000002a152c30 "
    "function=TICK now=4003504",
    "          <idle>-0       [001] d..h1.. 100.004006: irq_handler_exit: irq=13 ret=handled",
    "          <idle>-0       [001] ..s1... 100.004007: softirq_entry: vec=1 [action=TIMER]",
    "          <idle>-0       [001] ..s1... 100.004008: timer_expire_entry: timer=0000000049d1e620 "
    "function=tcp_write_timer now=4311720608 baseclk=4311720608",
    "          <idle>-0       [001] ..s1... 100.004020: softirq_exit: vec=1 [action=TIMER]",
    "     kworker/1:1-77      [001] ....... 100.004030: workqueue_execute_start: work struct 00000000d2f54dc6: "
    "function vmstat_update",
    "     kworker/1:1-77      [001] ....... 100.004040: workqueue_execute_end: work struct 00000000d2f54dc6: "
    "function vmstat_update",
]


def _body(handler):
    return [x.replace("function=TICK ", "function=%s " % handler) for x in BODY_T]


@pytest.mark.parametrize("handler", HANDLERS)
def test_reduce_parses_every_event_and_refuses_what_it_cannot_trust(handler):
    body = _body(handler)
    out, err = tkt.reduce(HDR + body)
    assert err is None, err
    assert out[0] == "100.000001 001 S CPU_0/KVM 5001"
    assert out[1:4] == ["100.004003 001 I arch_timer", "100.004004 001 H %s" % handler, "100.004006 001 i -"]
    assert out[4:7] == ["100.004007 001 Q TIMER", "100.004008 001 E tcp_write_timer", "100.004020 001 q -"]
    assert out[7:] == ["100.004030 001 W vmstat_update", "100.004040 001 w -"]
    assert "lost" in tkt.reduce(HDR[:2] + ["# entries-in-buffer/entries-written: 8/9   #P:6"] + body)[1]
    assert "lost" in tkt.reduce(HDR + body[:2] + ["CPU:1 [LOST 3 EVENTS]"])[1]
    assert "unparsed" in tkt.reduce(HDR + ["  x-1 [001] ....... 1.0: kvm_exit: reason=1"])[1]
    assert "header" in tkt.reduce(body)[1]


def test_the_tick_is_any_of_its_three_names_and_nothing_else():
    """One list, in tick_trace.py, and both reports ask it. The reducer keeps whatever name
    the kernel printed, so a fourth rename shows as 0/0 in the grid check and not as a guess."""
    assert tkt.TICK_HANDLERS == HANDLERS
    for h in HANDLERS:
        assert tkt.is_tick(h), h
    for h in ("kvm_bg_timer_expire", "tick_sched_handle", "tick_nohz_handler2", "hrtimer_wakeup", "", "tick"):
        assert not tkt.is_tick(h), h
    for name in ("tick_report.py", "metal_report.py"):
        src = open(os.path.join(GC, name), encoding="utf-8").read()
        assert "tkt.is_tick(fn)" in src and '== "tick_sched_timer"' not in src, name


def test_contexts_label_innermost_first_and_split_own_from_foreign():
    ev = [(0.0, 1, "S", "CPU_0/KVM 5001"), (10.0, 1, "I", "arch_timer"), (13.0, 1, "i", "-"),
          (13.0, 1, "Q", "TIMER"), (25.0, 1, "q", "-"), (30.0, 1, "S", "kworker/1:1 77"),
          (31.0, 1, "W", "vmstat_update"), (41.0, 1, "S", "CPU_0/KVM 5001"), (45.0, 1, "S", "kworker/1:1 77"),
          (47.0, 1, "w", "-"), (50.0, 1, "S", "idle 0"), (60.0, 1, "I", "rtl"), (62.0, 1, "i", "-"),
          (70.0, 1, "S", "CPU_0/KVM 5001"), (80.0, 1, "q", "-")]
    c = tkt.Contexts(ev, lambda core, comm, pid: pid == 5001)
    t = c.time(0.0, 80.0, [1])
    assert t["hardirq:arch_timer"] == 3.0 and t["softirq:TIMER"] == 12.0 and t["hardirq:rtl"] == 2.0
    assert t["work:vmstat_update"] == 12.0      # 31..41 and, back from preemption, 45..47
    assert t["task:kworker/1:1"] == 1.0 + 3.0   # 30..31 and 47..50
    assert t["own"] == 10.0 + 5.0 + 4.0 + 10.0 and t["idle"] == 18.0
    f = tkt.foreign(t)
    assert set(f) == {"hardirq:arch_timer", "softirq:TIMER", "hardirq:rtl", "work:vmstat_update", "task:kworker/1:1"}
    assert c.time(5.0, 12.0, [1, 4]) == {"own": 5.0, "hardirq:arch_timer": 2.0}


def _run(out, k, variant="soft", heavy_shift=0.0, n=1000, warm=200, seed=7, handler="tick_sched_timer", stamp=None):
    """Requests every 2250 us from 137 us past a base on the 4 ms grid, so 1 in 16 lands in
    the tick bin (at 3887). Tick-bin exchanges are +10 us; 1 in 10 of them +60 us more. 1 in 200 others are
    +300 us. Heavy rounds trace cores 0-2 and 4: QEMU's threads 5001-5003 on 0-2, the probe's
    core idle, a 3 us arch_timer at every tick on every core. For the +60 exchanges the tick
    on core 1 also sets off a 30 us TIMER softirq ("soft") or lasts 30 us longer ("hard");
    with "rest", the +300 exchanges get a 20 us kworker on core 1. `handler` is the name the
    tick's hrtimer expiries carry; `stamp` adds keys to stamp.json."""
    out.mkdir()
    rng = random.Random(seed)
    order, clog = [], []
    (out / "stamp.json").write_text(json.dumps(dict({"pin": {"qemu": "0-2", "probe": 4}}, **(stamp or {}))))
    for r in range(1, k + 1):
        kd = PAT[(r - 1) % 4]
        order.append("round %d arm: %s" % (r, kd))
        for w in ("before", "after"):
            clog.append("round %d %s udevd=3,5 pid1=3,5 gnome-shell=3,5 qemu=0-2" % (r, w))
        base = 1e9 + r * 1e7
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in (600_000.0, 1_624_000.0)]
        samples, tk = [], []
        slow_ticks, busy = [], []
        for i in range(warm + n):
            t0 = 137.0 + i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i < warm:
                continue
            v = 180.0 + 8.0 * rng.random() + (heavy_shift if kd == "heavy" else 0.0)
            if t0 % 4000.0 >= 3850.0:
                v += 10.0
                if rng.random() < 0.1:
                    v += 60.0
                    slow_ticks.append(t0 - t0 % 4000.0 + 4000.0)
            elif rng.random() < 1.0 / 200:
                v += 300.0
                busy.append(t0)
            samples.append(v / 1000.0)
        if kd == "heavy":
            for c, pid in ((0, 5001), (1, 5002), (2, 5003)):
                tk.append((0.0, c, "S", "CPU_%d/KVM %d" % (c, pid)))
            tk.append((0.0, 4, "S", "idle 0"))
            slow = set(slow_ticks)
            for j in range(int((warm + n) * 2250.0 / 4000.0) + 3):
                tt = j * 4000.0
                for c in (0, 1, 2, 4):
                    extra = 30.0 if (variant == "hard" and c == 1 and tt in slow) else 0.0
                    tk += [(tt + 3.5, c, "I", "arch_timer"), (tt + 3.5, c, "H", handler),
                           (tt + 6.5 + extra, c, "i", "-")]
                    if variant != "hard" and c == 1 and tt in slow:
                        tk += [(tt + 7.0, c, "Q", "TIMER"), (tt + 8.0, c, "E", "tcp_write_timer"), (tt + 37.0, c, "q", "-")]
            if variant == "rest":
                for t0 in busy:
                    tk += [(t0 + 20.0, 1, "S", "kworker/1:1 77"), (t0 + 40.0, 1, "S", "CPU_1/KVM 5002")]
            tk.sort(key=lambda x: x[0])
            (out / ("tk-t2ms_r%d.log" % r)).write_text(
                "".join("%.6f %03d %s %s\n" % ((base + t) / 1e6, c, kk, f) for t, c, kk, f in tk))
            (out / ("qtids-t2ms_r%d.txt" % r)).write_text("5000\n5001\n5002\n5003\n")
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(sorted(lines, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


@pytest.mark.parametrize("handler", HANDLERS)
def test_a_tick_that_sets_off_softirq_work_holds_everything(tmp_path, handler):
    _run(tmp_path / "o", 40, handler=handler)
    s = _report(tmp_path / "o")
    assert "kinds {'light': 20, 'heavy': 20}" in s and "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4", "P5"):
        assert "-> HELD" in _line(s, p), s
    assert "softirq:TIMER" in s and "tcp_write_timer" in s, s
    m4 = _line(s, "M4")
    assert "tick handler (%s) expiries" % handler in m4 and "-> ok" in m4, m4


def test_a_handler_the_report_does_not_know_scores_nothing(tmp_path):
    """A fourth rename, or another timer: no expiry counts as a tick, the grid check FAILS at
    0/0, and at the scored k every prediction prints VOID (they all rest on M4)."""
    _run(tmp_path / "o", 40, handler="tick_renamed_again")
    s = _report(tmp_path / "o")
    m4 = _line(s, "M4")
    assert ": 0/0 " in m4 and "-> FAILED" in m4 and "tick handler (none seen; looked for" in m4, m4
    for h in HANDLERS:
        assert h in m4, "the failed check says which names it looked for: " + m4
    assert "tick_renamed_again" not in m4
    for p in ("P1", "P2", "P3", "P4", "P5"):
        assert "VOID (M4 failed)" in _line(s, p), s
    assert "HELD" not in s and "REFUTED" not in s, s


def test_a_stamp_that_names_another_hz_is_not_scored_and_one_without_the_key_is(tmp_path):
    """The rule is fixed at a 4 ms grid (HZ 250). A stamp says which HZ the host had only
    since the library writes its system object; every earlier record has no such key and
    reads as before."""
    _run(tmp_path / "a", 40, stamp={"system": {"config_hz": 1000, "config_hz_source": "/proc/config.gz"}})
    s = _report(tmp_path / "a")
    assert "the stamp says CONFIG_HZ 1000" in s and "fixed at a 4 ms grid" in s, s
    for p in ("P1", "P2", "P3", "P4", "P5"):
        assert "not scored (CONFIG_HZ 1000; the rule is fixed at HZ 250)" in _line(s, p), s
    assert "HELD" not in s and "REFUTED" not in s and "VOID" not in s, s
    for name, system in (("b", {"config_hz": 250, "config_hz_source": "/proc/config.gz"}),
                         ("c", {"config_hz": None, "config_hz_source": "unread"}),     # unread is not another HZ
                         ("d", {"l4t_release": "absent"}),                              # a system object without the key
                         ("e", None)):                                                  # every record before the key
        _run(tmp_path / name, 40, stamp=None if system is None else {"system": system})
        s = _report(tmp_path / name)
        assert "CONFIG_HZ" not in s and "FAILED" not in s, (name, s)
        for p in ("P1", "P2", "P3", "P4", "P5"):
            assert "-> HELD" in _line(s, p), (name, s)
    assert tr.stamp_hz(str(tmp_path / "a")) == 1000 and tr.stamp_hz(str(tmp_path / "b")) == 250
    for name in ("c", "d", "e", "no-such-dir"):
        assert tr.stamp_hz(str(tmp_path / name)) is None, name


def test_a_longer_interrupt_refutes_p4_and_host_work_elsewhere_refutes_p5(tmp_path):
    _run(tmp_path / "o", 40, variant="hard")
    s = _report(tmp_path / "o")
    assert "-> HELD" in _line(s, "P3") and "-> REFUTED" in _line(s, "P4"), s
    _run(tmp_path / "p", 40, variant="rest")
    s = _report(tmp_path / "p")
    assert "-> REFUTED" in _line(s, "P5") and "-> HELD" in _line(s, "P1"), s


def test_a_distorting_trace_or_too_few_rounds_voids(tmp_path):
    _run(tmp_path / "o", 40, heavy_shift=20.0)
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M6") and "VOID (M6 failed)" in _line(s, "P3") and "VOID" not in _line(s, "P1"), s
    _run(tmp_path / "p", 4)
    assert "not scored (k=4; the prediction is for k=40)" in _report(tmp_path / "p")


def test_the_bin_and_the_cores():
    assert tr.in_bin(1e9 + 3850.0) and not tr.in_bin(1e9 + 3849.9) and not tr.in_bin(1e9 + 4000.0)
    assert tr.cores("no-such-dir") == ([0, 1, 2], 4)


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("RATIO >= 3", "SLOWDOWN >= +5 us", "DIFF >= +10 us (heavy)", "SHARE >= 0.5", "DIFF <= +5 us",
              "[3850, 4000) mod 4000", "[t0, t0 + 250 us]", "The bin and its edges were chosen",
              "looking at that record: this run tests it on new data",
              "It is not to be amended", "Scored only at k = 40", "The owner asked for this"):
        assert s in head, s
    assert "CPAT=(light heavy heavy light)" in body and "tick_report.py" in body and "tracing_cpumask" in body
    assert 'set_units "$CONF_CORES" || die' in body and "set_units 0-5; fi" not in body
