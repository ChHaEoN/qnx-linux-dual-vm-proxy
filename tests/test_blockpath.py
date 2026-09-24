"""The block-path decomposition's pieces (Phase 3b / A6, 2026-09-24): the trace
reduction and the segments (blockpath_trace.py), the report end to end
(blockpath_report.py), and the harness's header and syntax.

TRACE below was drafted by the PC's local model (qwen3.8:27b under Ollama) from a
written specification of two exchanges, then checked here: every segment value
the tests assert was worked out by hand from that specification first. One slip
was corrected by hand (a prev_comm naming the wrong core's idle task)."""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import blockpath_trace as bpt  # noqa: E402

BPT = os.path.join(GC, "blockpath_trace.py")
REPORT = os.path.join(GC, "blockpath_report.py")
HARNESS = os.path.join(GC, "run-blockpath.sh")
BASH = shutil.which("bash")
MAP = "m:4200,v0:4201,v1:4202"

TRACE = """# tracer: nop
#
# entries-in-buffer/entries-written: 26/26   #P:6
#
         python3-4300    [004] ....1..  1000.000000: net_dev_xmit: dev=tap-qnx skbaddr=0000000049465e19 len=130 rc=0
          <idle>-0       [005] d...2..  1000.000004: sched_switch: prev_comm=swapper/5 prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=qemu-system-aar next_pid=4200 next_prio=120
 qemu-system-aar-4200    [005] .......  1000.000021: kvm_irq_line: Inject VGIC SPI interrupt (1), vcpu->idx: 0, num: 78, level: 1
 qemu-system-aar-4200    [005] d...2..  1000.000023: sched_waking: comm=CPU 0/KVM pid=4201 prio=120 target_cpu=001
          <idle>-0       [001] d...2..  1000.000032: sched_switch: prev_comm=swapper/1 prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=CPU 0/KVM next_pid=4201 next_prio=120
       CPU 0/KVM-4201    [001] .......  1000.000038: kvm_vcpu_wakeup: wait time 1900000 ns, polling valid
       CPU 0/KVM-4201    [001] .......  1000.000084: kvm_irq_line: Inject VGIC SPI interrupt (1), vcpu->idx: 0, num: 78, level: 0
       CPU 0/KVM-4201    [001] d...2..  1000.000125: sched_waking: comm=CPU 1/KVM pid=4202 prio=120 target_cpu=002
          <idle>-0       [002] d...2..  1000.000134: sched_switch: prev_comm=swapper/5 prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=CPU 1/KVM next_pid=4202 next_prio=120
       CPU 1/KVM-4202    [002] .......  1000.000141: kvm_vcpu_wakeup: wait time 2200000 ns, polling valid
       CPU 0/KVM-4201    [001] d...2..  1000.000200: sched_waking: comm=qemu-system-aar pid=4200 prio=120 target_cpu=005
          <idle>-0       [005] d...2..  1000.000207: sched_switch: prev_comm=swapper/5 prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=qemu-system-aar next_pid=4200 next_prio=120
 qemu-system-aar-4200    [005] ..s1...  1000.000230: netif_receive_skb: dev=tap-qnx skbaddr=ffff0000812b4000 len=116
         python3-4300    [004] ....1..  1000.002000: net_dev_xmit: dev=tap-qnx skbaddr=0000000049465e19 len=130 rc=0
          <idle>-0       [005] d...2..  1000.002004: sched_switch: prev_comm=swapper/5 prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=qemu-system-aar next_pid=4200 next_prio=120
 qemu-system-aar-4200    [005] .......  1000.002021: kvm_irq_line: Inject VGIC SPI interrupt (1), vcpu->idx: 0, num: 78, level: 1
       CPU 0/KVM-4201    [001] .......  1000.002024: kvm_vcpu_wakeup: poll time 150000 ns, polling valid
       CPU 0/KVM-4201    [001] .......  1000.002060: kvm_irq_line: Inject VGIC SPI interrupt (1), vcpu->idx: 0, num: 78, level: 0
       CPU 1/KVM-4202    [002] .......  1000.002062: kvm_vcpu_wakeup: poll time 90000 ns, polling valid
       CPU 0/KVM-4201    [001] d...2..  1000.002100: sched_waking: comm=qemu-system-aar pid=4200 prio=120 target_cpu=005
          <idle>-0       [005] d...2..  1000.002104: sched_switch: prev_comm=swapper/5 prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=qemu-system-aar next_pid=4200 next_prio=120
 qemu-system-aar-4200    [005] ..s1...  1000.002120: netif_receive_skb: dev=tap-qnx skbaddr=ffff0000812b4000 len=116
 qemu-system-aar-4200    [005] ..s1...  1000.002121: netif_receive_skb: dev=tap-qnx skbaddr=ffff0000812b4000 len=66
         python3-4300    [004] ....1..  1000.002300: net_dev_xmit: dev=tap-qnx skbaddr=0000000049465e19 len=66 rc=0
       CPU 1/KVM-4202    [002] .......  1000.002400: kvm_vcpu_wakeup: poll time 5000 ns, polling valid
       CPU 0/KVM-4201    [001] .......  1000.002500: kvm_vcpu_wakeup: poll time 7000 ns, polling valid
"""


def _reduce(text, m=MAP):
    return subprocess.run([sys.executable, BPT, "reduce", "--map", m], input=text, capture_output=True,
                          text=True, timeout=30)


def test_reduce_keeps_only_times_cores_roles_and_fields():
    r = _reduce(TRACE)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert len(lines) == 26
    assert lines[0] == "1000.000000 004 X 130"
    assert lines[2] == "1000.000021 005 I 78 1 m"
    assert lines[3] == "1000.000023 005 W v0 m"
    assert lines[4] == "1000.000032 001 S v0"
    assert lines[5] == "1000.000038 001 K wait 1900000 v0"
    for leak in ("python3", "swapper", "qemu", "4300", "skbaddr", "0000000049465e19"):
        assert leak not in r.stdout, leak


def test_segments_of_a_blocked_and_a_polled_exchange(tmp_path):
    f = tmp_path / "bp-x_r1.log"
    f.write_text(_reduce(TRACE).stdout)
    rows, summ = bpt.segments(bpt.read(str(f)))
    assert summ["requests"] == 2 and summ["segmented"] == 2 and summ["irq"] == "78"
    blocked, polled = rows
    want_b = {"A": 21, "B": 17, "C": 162, "D": 30, "total": 230, "blocked": 2, "polled": 0,
              "wake_us": 18, "load_us": 13, "m_wakes": 1, "v_first": "wait"}
    want_p = {"A": 21, "B": 3, "C": 76, "D": 20, "total": 120, "blocked": 0, "polled": 2,
              "wake_us": 0, "load_us": 0, "m_wakes": 1, "v_first": "poll"}
    for row, want in ((blocked, want_b), (polled, want_p)):
        for k, v in want.items():
            got = row[k]
            assert (round(got, 3) if isinstance(got, float) else got) == v, (k, got, v)


def test_an_exchange_missing_a_mark_is_skipped_not_guessed(tmp_path):
    f = tmp_path / "bp-x_r1.log"
    kept = [l for l in _reduce(TRACE).stdout.splitlines() if not l.startswith("1000.000230 ")]  # blocked reply gone
    f.write_text("\n".join(kept) + "\n")
    rows, summ = bpt.segments(bpt.read(str(f)))
    # Without its reply, the first exchange's OUT would be the second exchange's --
    # except that the window ends at the next request, so it is skipped.
    assert summ["segmented"] == 1 and summ["skipped"] == {"no reply": 1}


@pytest.mark.parametrize("mutate,why", [
    (lambda t: t.replace("26/26", "25/26"), "lost events"),
    (lambda t: t + "CPU:3 [LOST 12 EVENTS]\n", "LOST line"),
    (lambda t: t.replace("dev=tap-qnx skbaddr=0000000049465e19", "dev=eth0 skbaddr=0000000049465e19"),
     "device other than tap-qnx"),
    (lambda t: t.replace("comm=CPU 0/KVM pid=4201", "comm=CPU 0/KVM pid=9999", 1), "not in the map"),
    (lambda t: t.replace("# entries-in-buffer/entries-written: 26/26   #P:6\n", ""), "no entries-in-buffer"),
    (lambda t: t + "garbage without a prefix\n", "unparsed line"),
])
def test_reduce_refuses_a_trace_it_cannot_vouch_for(mutate, why):
    r = _reduce(mutate(TRACE))
    assert r.returncode == 2 and why in r.stderr, (r.returncode, r.stderr)
    assert "python3" not in r.stderr and "swapper" not in r.stderr


def test_reduce_refuses_a_bad_map():
    r = _reduce(TRACE, "main:4200")
    assert r.returncode == 2 and "bad --map" in r.stderr


def test_the_report_decomposes_blocked_against_polled(tmp_path):
    """Six arms, three rounds: the blocked arms (N200us, N2ms, D2ms) carry the
    fixture's blocked exchange, the polled ones its polled exchange, and every
    blocked round trip is 110 us longer -- the traced total's difference."""
    blocked_log = [l for l in _reduce(TRACE).stdout.splitlines() if float(l.split()[0]) < 1000.002]
    polled_log = [l for l in _reduce(TRACE).stdout.splitlines() if float(l.split()[0]) >= 1000.002]
    for r in (1, 2, 3):
        for a in ("N200us", "N2ms", "D200us", "D2ms", "B200us", "B2ms"):
            blocked = a in ("N200us", "N2ms", "D2ms")
            (tmp_path / ("lat-%s_r%d.json" % (a, r))).write_text(
                json.dumps({"summary": {"p50_ms": (300.0 if blocked else 190.0) / 1000.0}}))
            (tmp_path / ("bp-%s_r%d.log" % (a, r))).write_text(
                "\n".join(blocked_log if blocked else polled_log) + "\n")
    out = subprocess.run([sys.executable, REPORT, str(tmp_path), "500", "100"], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    s = out.stdout
    assert "blocked - polled at 2 ms (D2ms - B2ms)" in s and "blocked - polled at 0.2 ms (N200us - D200us)" in s
    assert s.count("A..D    +110.0 [+110.0, +110.0]") == 2
    assert s.count("rtt     +110.0 [+110.0, +110.0]") == 2
    assert s.count("B        +14.0 [+14.0, +14.0]") == 2
    assert s.count("account for 100% of the round trip's difference") == 2


def test_the_harness_parses_and_says_what_it_is():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    h = open(HARNESS, encoding="utf-8").read()
    head = h.split("\nset -u\n")[0]
    assert "THIS IS A DECOMPOSITION, NOT A TEST. No prediction is registered." in head
    assert "one calibration trace" in head and "nothing here is blind" in head
    assert "THREAD_NAMES=1 SMP=2" in h and "trace_start" in h and "trace_take" in h
