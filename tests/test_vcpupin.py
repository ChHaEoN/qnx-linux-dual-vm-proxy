"""The vCPU-pinning experiment's pieces (Phase 3b / A6, 2026-09-24): the trace
reduction and its counts (switch_trace.py), the scoring of the three predictions
at the thresholds run-vcpupin.sh fixed before any run (vcpupin_report.py), and
the launcher's THREAD_NAMES opt-in."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import switch_trace  # noqa: E402
import vcpupin_report  # noqa: E402

SWT = os.path.join(GC, "switch_trace.py")
BASH = shutil.which("bash")

HEAD = """# tracer: nop
#
# entries-in-buffer/entries-written: {0}/{1}   #P:6
#
#                                _-------=> irqs-off
#           TASK-PID     CPU#  |||||||  TIMESTAMP  FUNCTION
#              | |         |   |||||||      |         |
"""
# Real shapes: a task name with a space and a slash, one with dashes, and a line
# with no flags column (irq-info off).
LINES = [
    "          <idle>-0       [001] d..2.  100.000100: sched_switch: prev_comm=swapper/1 prev_pid=0 "
    "prev_prio=120 prev_state=R ==> next_comm=CPU 0/KVM next_pid=4242 next_prio=120",
    "       CPU 0/KVM-4242    [001] d..2.  100.000200: sched_switch: prev_comm=CPU 0/KVM prev_pid=4242 "
    "prev_prio=120 prev_state=S ==> next_comm=CPU 1/KVM next_pid=4243 next_prio=120",
    " qemu-system-aar-4200    [002] dN.3.  100.000300: sched_switch: prev_comm=qemu-system-aar prev_pid=4200 "
    "prev_prio=120 prev_state=S ==> next_comm=CPU 0/KVM next_pid=4242 next_prio=120",
    "          <idle>-0       [000]   100.000400: sched_switch: prev_comm=swapper/0 prev_pid=0 "
    "prev_prio=120 prev_state=R ==> next_comm=CPU 1/KVM next_pid=4243 next_prio=120",
]
MAP = "4242:0,4243:1"


def run_reduce(text, tid_map=MAP):
    return subprocess.run([sys.executable, SWT, "reduce", "--map", tid_map], input=text,
                          capture_output=True, text=True, timeout=30)


def test_reduce_keeps_only_core_time_and_vcpu():
    r = run_reduce(HEAD.format(4, 4) + "\n".join(LINES) + "\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["100.000100 1 0", "100.000200 1 1", "100.000300 2 0", "100.000400 0 1"]
    # No process name or pid from the trace survives the reduction.
    assert "swapper" not in r.stdout and "qemu" not in r.stdout and "4242" not in r.stdout


@pytest.mark.parametrize("text,why", [
    (HEAD.format(3, 4) + LINES[0] + "\n", "lost events"),
    ("\n".join(LINES) + "\n", "no entries-in-buffer"),
    (HEAD.format(1, 1) + LINES[0].replace("next_pid=4242", "next_pid=999") + "\n", "not in the map"),
    (HEAD.format(1, 1) + "garbage-1 sched_switch: next_pid=4242\n", "unparsed"),
])
def test_reduce_refuses_a_trace_it_cannot_vouch_for(text, why):
    r = run_reduce(text)
    assert r.returncode == 2 and why in r.stderr, (r.returncode, r.stderr)


def test_reduce_refuses_a_bad_map():
    r = run_reduce(HEAD.format(0, 0), "4242:zero")
    assert r.returncode == 2 and "bad --map" in r.stderr


def test_count_follows_last_vcpu_ran_per_core():
    ev = [("1", 1, 0),   # core 1 first seen: flush unknown; vCPU 0 first: migration unknown
          ("2", 2, 1),   # core 2 first seen; vCPU 1 first
          ("3", 1, 0),   # core 1 last had vCPU 0: no flush; vCPU 0 stays
          ("4", 1, 1),   # core 1 last had vCPU 0: FLUSH; vCPU 1 was on 2: migration
          ("5", 2, 0),   # core 2 last had vCPU 1: FLUSH; vCPU 0 was on 1: migration
          ("6", 2, 0)]   # same vCPU again: no flush; stays
    c = switch_trace.count(ev)
    assert (c["switch_ins"], c["flush_cond"], c["same_vcpu"], c["flush_unknown"]) == (6, 2, 2, 2)
    assert (c["migrations"], c["stays"], c["migr_unknown"]) == (2, 2, 2)
    assert c["per_vcpu"] == {"0": 4, "1": 2} and c["per_core"] == {"1": 3, "2": 3}


def test_count_is_zero_when_each_vcpu_keeps_its_own_core():
    ev = [(str(i), 1 + i % 2, i % 2) for i in range(20)]
    c = switch_trace.count(ev)
    assert c["flush_cond"] == 0 and c["migrations"] == 0 and c["switch_ins"] == 20


def test_count_reads_a_reduced_file_in_time_order(tmp_path):
    f = tmp_path / "sw-x_r1.log"
    f.write_text("100.3 1 1\n100.1 1 0\n100.2 1 0\n")   # out of order on purpose
    c = json.loads(subprocess.check_output([sys.executable, SWT, "count", str(f)], text=True))
    assert c["flush_cond"] == 1 and c["same_vcpu"] == 1


# The thresholds are the header's, fixed before any run. These pin them.
@pytest.mark.parametrize("diffs,want", [
    ([-4.0] * 12, "HELD"),
    ([-6.0] * 10 + [1.0, 1.0], "HELD"),                 # median -6, 10/12 below zero
    ([-6.0] * 9 + [1.0, 1.0, 1.0], "PARTIAL"),          # median -6 but only 9/12
    ([-3.9] * 12, "PARTIAL"),
    ([-1.1] * 12, "PARTIAL"),
    ([-1.0] * 12, "REFUTED"),
    ([0.0] * 12, "REFUTED"),
    ([2.0] * 12, "REFUTED"),
])
def test_p1_is_scored_at_the_preregistered_thresholds(diffs, want):
    assert vcpupin_report.score_p1(diffs) == want


@pytest.mark.parametrize("diffs,want", [([1.0] * 12, "HELD"), ([-1.0] * 12, "HELD"), ([0.0] * 12, "HELD"),
                                        ([1.1] * 12, "FAILED"), ([-1.5] * 12, "FAILED")])
def test_p2_is_scored_at_the_preregistered_threshold(diffs, want):
    assert vcpupin_report.score_p2(diffs) == want


@pytest.mark.parametrize("f2,f02,fo,want", [
    (0.5, 0.099, 0, ("HELD", "ok")),
    (0.49, 0.0, 0, ("FAILED", "ok")),
    (2.0, 0.1, 0, ("FAILED", "ok")),
    (2.0, 0.0, 1, ("HELD", "PINNING BROKEN")),
])
def test_p3_is_scored_at_the_preregistered_thresholds(f2, f02, fo, want):
    assert vcpupin_report.score_p3(f2, f02, fo) == want


def test_the_harness_parses_and_states_its_prediction_before_any_code():
    h = os.path.join(GC, "run-vcpupin.sh")
    if BASH is not None:
        r = subprocess.run([BASH, "-n", h], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    head = open(h, encoding="utf-8").read().split("\nset -u\n")[0]
    for s in ("median <= -4 ticks", "at least 10 of 12 rounds", "median is >= -1 tick",
              "|median| <= 1 tick", "at\n#      least 0.5 times per exchange in S2ms", "fewer than 0.1 times"):
        assert s in head, s


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_the_launcher_refuses_a_thread_names_value_it_does_not_know(tmp_path):
    f = tmp_path / "x.bin"
    f.write_text("x")
    env = dict(os.environ, IFS_BIN=str(f).replace("\\", "/"), DISK=str(f).replace("\\", "/"), THREAD_NAMES="yes")
    r = subprocess.run([BASH, os.path.join(GC, "launch-qnx-kvm-bridged.sh")], capture_output=True, text=True,
                       env=env, timeout=30)
    assert r.returncode == 1 and "THREAD_NAMES='yes' is not 0 or 1" in r.stderr, r.stderr


# ---- the per-arm liveness check, and the report end to end on a synthetic run

def _kvm(path, t0_ns, t1_ns, wakes):
    snap = lambda t, w: {"t_ns": t, "qemu_pid": 1, "counters": {"halt_wakeup": w, "halt_attempted_poll": 0,
                                                                 "halt_successful_poll": 0}, "threads": {}}
    path.write_text(json.dumps({"before": snap(t0_ns, 100), "after": snap(t1_ns, 100 + wakes)}))


def _check(tmp_path, lines, wakes, mode):
    sw, kv = tmp_path / "sw-a_r1.log", tmp_path / "kvm-a_r1.json"
    sw.write_text("".join("%s %d %d\n" % l for l in lines))
    _kvm(kv, 10_000_000_000, 11_000_000_000, wakes)
    return subprocess.run([sys.executable, SWT, "check", "--sw", str(sw), "--kvm", str(kv), "--mode", mode],
                          capture_output=True, text=True, timeout=30)


def test_check_counts_only_inside_the_kvm_window(tmp_path):
    inside = [("10.%06d" % (i * 1000 + 1), 1 + i % 2, i % 2) for i in range(40)]
    outside = [("9.5", 1, 1), ("11.5", 2, 0)]
    r = _check(tmp_path, outside[:1] + inside + outside[1:], 40, "O")
    assert r.returncode == 0, r.stderr
    c = json.loads(r.stdout)
    assert c["switch_ins"] == 40 and c["kvm_halt_wakeup"] == 40 and c["cores_of"] == {"0": [1], "1": [2]}


def test_check_refuses_a_trace_that_missed_the_wake_ups(tmp_path):
    r = _check(tmp_path, [("10.1", 1, 0)] * 5, 100, "S")
    assert r.returncode == 2 and "missed vCPU switch-ins" in r.stderr


def test_check_lets_a_quiet_arm_through(tmp_path):
    assert _check(tmp_path, [], 10, "S").returncode == 0      # under 20 wake-ups there is nothing to demand


@pytest.mark.parametrize("lines,why", [
    ([("10.1", 1, 0), ("10.2", 2, 0)], "pinning did not hold"),        # vCPU 0 moved
    ([("10.1", 1, 0), ("10.2", 1, 1)], "pinning did not hold"),        # both on core 1: a flush condition
])
def test_check_refuses_an_o_arm_whose_pinning_did_not_hold(tmp_path, lines, why):
    r = _check(tmp_path, lines, 2, "O")
    assert r.returncode == 2 and why in r.stderr


def _synthetic_run(out, k, mon_ticks):
    """mon_ticks: {arm: ticks at p50}. Every arm: 40 switch-ins for 40 wake-ups."""
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"counter": "arch_timer: cp15 timer(s) running at 31.25MHz"}))
    for r in range(1, k + 1):
        for a, tk in mon_ticks.items():
            summ = {"p50_ms": 0.18, "server_us": {"p50": tk * 0.032}, "other_us": {"p50": 179.6},
                    "period_us": {"p50": 2249.0}}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": summ}))
            _kvm(out / ("kvm-%s_r%d.json" % (a, r)), 10_000_000_000, 11_000_000_000, 40)
            if a.startswith("O"):
                ev = [("10.%06d" % (i * 1000 + 1), 1 + i % 2, i % 2) for i in range(40)]
            elif a == "S2ms":
                ev = [("10.%06d" % (i * 1000 + 1), 1 + (i // 2) % 2, i % 2) for i in range(40)]
            else:
                ev = [("10.%06d" % (i * 1000 + 1), 1 + i % 2, i % 2) for i in range(40)]
            (out / ("sw-%s_r%d.log" % (a, r))).write_text("".join("%s %d %d\n" % e for e in ev))


def test_the_report_scores_only_at_k_12(tmp_path):
    ticks = {"S200us": 6, "S2ms": 12, "O200us": 6, "O2ms": 6}
    _synthetic_run(tmp_path / "k4", 4, ticks)
    r = subprocess.run([sys.executable, os.path.join(GC, "vcpupin_report.py"), str(tmp_path / "k4"), "1000", "200"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("not scored (k=4") == 3 and "HELD" not in r.stdout
    _synthetic_run(tmp_path / "k12", 12, ticks)
    r = subprocess.run([sys.executable, os.path.join(GC, "vcpupin_report.py"), str(tmp_path / "k12"), "1000", "200"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "O2ms - S2ms: median -6.0 ticks" in r.stdout and "12/12 -> HELD" in r.stdout
    assert "O200us - S200us: median +0.0 ticks" in r.stdout
    # The S2ms trace puts both vCPUs on one core, then both on the other: every
    # switch-in after the first on each core is a flush condition, 38 of 40, and
    # 38 in 1200 exchanges is 0.032 per exchange -- far under P3's 0.5, so P3
    # fails. The O arms' zero is still reported, as a pinning check.
    assert "P3 flush per exchange: S2ms 0.032" in r.stdout and "-> FAILED" in r.stdout and "(must be 0: ok)" in r.stdout
