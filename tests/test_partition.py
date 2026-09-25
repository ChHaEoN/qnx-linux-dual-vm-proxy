"""The partition test (Phase 3b / A6, 2026-09-25): the four-boot report on synthetic boots,
the counters it reads, and the harness's header."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import partition_report as pr  # noqa: E402

REPORT = os.path.join(GC, "partition_report.py")
HARNESS = os.path.join(GC, "run-partition.sh")
BASH = shutil.which("bash")
SOFT = ("HI", "TIMER", "NET_TX", "NET_RX", "BLOCK", "IRQ_POLL", "TASKLET", "SCHED", "HRTIMER", "RCU")


def _irq(sched, dev0):
    out = []
    for when, add in (("before", 0), ("after", 1)):
        out.append("== round 1 %s softirqs" % when)
        out.append("                    CPU0       CPU1       CPU2       CPU3       CPU4       CPU5")
        for row in SOFT:
            v = [100 + add * (sched if row == "SCHED" and c in (0, 1, 2, 4) else 7) for c in range(6)]
            out.append("%12s: %s" % (row, " ".join("%10d" % x for x in v)))
        out.append("== round 1 %s interrupts" % when)
        out.append("           CPU0       CPU1       CPU2       CPU3       CPU4       CPU5")
        out.append(" 13: %s     GICv3  30 Level     arch_timer" % " ".join("%10d" % (500 + add * 250) for _ in range(6)))
        out.append("276: %s     GICv3 104 Level     rtl88x2ce" % " ".join(
            "%10d" % (40 + add * (dev0 if c == 0 else 0)) for c in range(6)))
        out.append("IPI0: %s       Rescheduling interrupts" % " ".join("%10d" % (9 + add) for _ in range(6)))
    return "\n".join(out) + "\n"


def _boot(out, tag, k=16, tick=11.0, tail_every=10, sched=None, iso=None, uptime=900, seed=3, n=1000, warm=200):
    arm = pr.ARM_OF[tag]
    out.mkdir(parents=True)
    rng = random.Random(seed + ord(tag[0]) * 7 + int(tag[1]))
    part = arm == "partition"
    iso = ("0-2,4" if part else "") if iso is None else iso
    info = "cmdline isolcpus/irqaffinity: %s; isolated '%s'; default_smp_affinity %s; uptime at preflight %d s" % (
        " ".join(pr.PARAMS) if part else "", iso, "28" if part else "3f", uptime)
    (out / "stamp.json").write_text(json.dumps({"arm": arm, "boot_tag": tag, "boot": info,
                                                "pin": {"qemu": "0-2", "probe": 4}}))
    order, clog, plog = [], [], []
    for r in range(1, k + 1):
        order.append("round %d arm: %s" % (r, arm))
        for w in ("before", "after"):
            clog.append("round %d %s udevd=3,5 pid1=3,5 gnome-shell=3,5 qemu=0 1 2" % (r, w))
            plog += ["round %d %s 5001 1 1" % (r, w), "round %d %s 5002 2 2" % (r, w), "round %d %s 5000 0 0" % (r, w)]
        base = 1e9 + r * 1e7
        lines = ["%.6f 003 T tj-thermal" % ((base + t) / 1e6) for t in (600_000.0, 1_624_000.0)]
        samples = []
        for i in range(warm + n):
            t0 = 137.0 + i * 2250.0
            lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
            if i < warm:
                continue
            v = 180.0 + 8.0 * rng.random()
            if t0 % 4000.0 >= 3850.0:
                v += tick + (60.0 if rng.random() < 1.0 / tail_every else 0.0)
            elif rng.random() < 1.0 / 100:
                v += 50.0
            samples.append(v / 1000.0)
        (out / ("tp-t2ms_r%d.log" % r)).write_text("\n".join(sorted(lines, key=lambda l: float(l.split()[0]))) + "\n")
        (out / ("lat-t2ms_r%d.json" % r)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
        (out / ("irq-t2ms_r%d.txt" % r)).write_text(_irq((10 if part else 1000) if sched is None else sched, 0 if part else 50))
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "pin.log").write_text("\n".join(plog) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")


def _four(tmp, **part):
    dirs = []
    for tag in pr.TAGS:
        d = tmp / tag
        kw = part if pr.ARM_OF[tag] == "partition" else {}
        _boot(d, tag, **kw)
        dirs.append(str(d))
    return dirs


def _report(args):
    r = subprocess.run([sys.executable, REPORT] + args + ["1000", "200"], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split(tag)[1].split("\n")[0]


def test_irq_counts_read_softirqs_and_device_interrupts(tmp_path):
    p = tmp_path / "irq.txt"
    p.write_text(_irq(1000, 50))
    c = pr.irq_counts(str(p))
    assert pr.delta(c, "SCHED", (0, 1, 2, 4)) == 4000 and pr.delta(c, "SCHED", (3,)) == 7
    assert pr.delta(c, "DEV", (0,)) == 50 and pr.delta(c, "DEV", (1,)) == 0   # the timer and IPIs are not devices


def test_a_partition_that_halves_the_tick_holds_everything(tmp_path):
    s = _report(_four(tmp_path, tick=5.0, tail_every=200))
    assert "FAILED" not in s, s
    for p in ("P1", "P2", "P3", "P4", "P5"):
        assert "-> HELD" in _line(s, p), s


def test_a_partition_that_changes_nothing_refutes(tmp_path):
    s = _report(_four(tmp_path))
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P3") and "-> REFUTED" in _line(s, "P4"), s
    assert "-> HELD" in _line(s, "P5"), s


def test_a_partition_that_did_not_take_or_boots_out_of_order_void(tmp_path):
    s = _report(_four(tmp_path / "x", tick=5.0, tail_every=200, sched=900))
    assert "-> FAILED" in _line(s, "M4") and "VOID (M4 failed)" in _line(s, "P1"), s
    s = _report(_four(tmp_path / "y", tick=5.0, tail_every=200, iso=""))
    assert "-> FAILED" in _line(s, "M4"), s
    d = _four(tmp_path / "z", tick=5.0, tail_every=200)
    s = _report([d[1], d[0], d[2], d[3]])
    assert "not scored" in _line(s, "P1"), s
    s = _report(["--one", d[1]])
    assert "B1  partition rounds 16 aligned 16" in s and "isolated '0-2,4'" in s, s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("partition SLOWDOWN <= 0.75x default's", "partition SLOWDOWN >= +3 us", "partition RATIO <= 0.75x default's",
              "both partition boots' SLOWDOWN below both default boots'", "|p50 partition - p50 default| <= 3 us",
              "A1 B1 B2 A2", "It is not to be amended", "The owner asked for", "ONE PER CORE"):
        assert s in head, s
    assert 'HK=3,5' in body and 'irq_snap "$r" before' in body and "partition_report.py" in body
