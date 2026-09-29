"""The comparison of the two ways into the guest's notified shared memory (Phase 3b / A6,
2026-09-29): run-bell.sh's header, bell_report.py end to end on synthetic rounds, and ifs-bell.build as
ifs-its.build plus exactly the bell lines. Every number here is synthetic."""
import json
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "ci"))
import results_guard as rg  # noqa: E402

REPORT = os.path.join(GC, "bell_report.py")
HARNESS = os.path.join(GC, "run-bell.sh")
IFS_DIR = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor")
BASH = shutil.which("bash")
# The lines' shapes are the tools' own printf formats; every value is made up.
CONSOLE = ("its: msixcfg: ivshmem 00:01.0 BAR1 0x12340000 (4096 B), MSI-X entry 0 -> 0x12350040 data 0, "
           "DeviceID 0x8 EventID 0 -> LPI 8193 (ITT 0x12360000), MC 0x8000 cmd 0x0006\n"
           "monitor: safety monitor serving shm-kick on ivshmem 00:01.0 BAR2 0x10000000; slot @4096; peer 1; "
           "kick /dev/vcon2 (raw) (frame=64 bytes, conf_min=60%)\n"
           "monitor: safety monitor serving shm-kick on ivshmem 00:01.0 BAR2 0x10000000; slot @8192; peer 1; "
           "kick msix (LPI 8193) (frame=64 bytes, conf_min=60%)\n")


def _run(out, k=16, b_p50=60.0, k_p50=120.0, b_p99=90.0, k_p99=200.0, user=(0.1, 2.1), kern=(6.2, 2.2),
         bad_notify=False, no_console=False, no_kvm=False, n=1000, warm=200, seed=7):
    out.mkdir(parents=True)
    rng = random.Random(seed)
    ex = n + warm
    for r in range(1, k + 1):
        for a, p50, p99, u, kk in (("K", k_p50, k_p99, user[1], kern[1]), ("B", b_p50, b_p99, user[0], kern[0])):
            j = rng.uniform(-3, 3)
            nt = {"exchanges": ex, "wakeups": ex, "early_wakeups": 0, "notifications": ex, "stray": 0, "eagain": 0}
            if bad_notify and a == "B" and r == 3:
                nt["early_wakeups"] = 2
            s = {"n": n, "bad": 0, "rejected_by_monitor": 0, "proto": {"K": "shmdb", "B": "shmbell"}[a],
                 "cpu_affinity": [4], "p50_ms": (p50 + j) / 1000.0, "p90_ms": (p50 + j + 5) / 1000.0,
                 "p99_ms": (p99 + 2 * j) / 1000.0, "p999_ms": (p99 + 40 + j) / 1000.0, "notify": nt}
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
            if not no_kvm:
                before = {"mmio_exit_user": 1000, "mmio_exit_kernel": 5000, "exits": 9000,
                          "halt_attempted_poll": 10, "halt_successful_poll": 5, "halt_wakeup": 20}
                after = dict(before)
                after["mmio_exit_user"] += int(round(u * ex))
                after["mmio_exit_kernel"] += int(round(kk * ex))
                after["exits"] += int(round((u + kk + 3) * ex))
                (out / ("kvm-%s_r%d.json" % (a, r))).write_text(json.dumps(
                    {"before": {"counters": before}, "after": {"counters": after}}))
        (out / ("console-A_r%d.log" % r)).write_text("" if (no_console and r == 5) else CONSOLE)
    (out / "stamp.json").write_text(json.dumps({"n": n, "warmup": warm, "pin": {"qemu": "0-2", "probe": 4}}))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag)[1].split("\n")[0]


def test_a_doorbell_that_is_much_faster_holds_everything(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    for m in ("M1", "M2", "M3", "M4"):
        assert "FAILED" not in _line(s, m), s
    for p in ("P1", "P2", "P3"):
        assert "-> HELD" in _line(s, p), s


def test_a_small_gain_is_partial_and_a_loss_is_refuted(tmp_path):
    _run(tmp_path / "a", b_p50=100.0, k_p50=120.0)
    assert "-> PARTIAL" in _line(_report(tmp_path / "a"), "P1")
    _run(tmp_path / "b", b_p50=130.0, k_p50=120.0, b_p99=260.0)
    s = _report(tmp_path / "b")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2"), s


def test_the_mechanism_is_graded_on_both_counters(tmp_path):
    _run(tmp_path / "a", user=(2.1, 2.1))
    assert "-> PARTIAL" in _line(_report(tmp_path / "a"), "P3")
    _run(tmp_path / "b", user=(2.1, 2.1), kern=(2.2, 2.2))
    assert "-> REFUTED" in _line(_report(tmp_path / "b"), "P3")


def test_failed_checks_void(tmp_path):
    _run(tmp_path / "a", bad_notify=True)
    s = _report(tmp_path / "a")
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P1"), s
    _run(tmp_path / "b", no_console=True)
    s = _report(tmp_path / "b")
    assert "-> FAILED" in _line(s, "M3") and "VOID (M3 failed)" in _line(s, "P2"), s
    _run(tmp_path / "c", no_kvm=True)
    s = _report(tmp_path / "c")
    assert "-> FAILED" in _line(s, "M4") and "VOID (M4 failed)" in _line(s, "P3"), s
    assert "VOID" not in _line(s, "P1"), "P1 does not rest on the KVM counters"


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("median DIFF(p50) <= -40 us: HELD", "median DIFF(mmio_exit_user per exchange) <= -1.0",
              "median DIFF(mmio_exit_kernel per\n#      exchange) >= +2.0", "It is\n# not to be amended",
              "paired within the round", "d(4)..d(13)", "What this does NOT test", "M4 KVM's counters"):
        assert s in head, s
    assert "bell_report.py" in body and "shmbell" in body and "KVM_STATS=1" in body
    assert 'ARM_PROTOS="K=shmdb B=shmbell"' in body


def test_what_is_known_names_records_and_quotes_no_figure():
    text = open(HARNESS, encoding="utf-8").read()
    known = rg.known_sections(text)
    joined = " ".join(line for _n, line in known)
    for rec in ("20260922T-a6-orin-kick", "20260922T-a6-orin-shift", "20260929T-a6-orin-its"):
        assert rec in joined, rec
    assert [f for _n, line in known for f in rg.figures(line)] == []


def test_ifs_bell_is_ifs_its_with_exactly_the_bell_lines():
    def lines(name):
        with open(os.path.join(IFS_DIR, name), encoding="utf-8") as f:
            return [ln.rstrip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    its, bell = lines("ifs-its.build"), lines("ifs-bell.build")
    removed = [ln for ln in its if ln not in bell]
    added = [ln for ln in bell if ln not in its]
    root = "E:/Project/qnx-linux-dual-vm-proxy/ipc-test/qnx-safety-monitor/"
    assert removed == ["/proc/boot/qnx-its-probe selftest 20", "/proc/boot/qnx-its-probe msixwait &",
                       "[perms=0444] build/ifs.build=" + root + "ifs-its.build",
                       "[perms=0444] build.date = output/build/ifs-its.build.date",
                       "[perms=555] qnx-safety-monitor=" + root + "qnx-safety-monitor"], removed
    assert added == ["/proc/boot/qnx-safety-monitor shmkick ivshmem@8192 msix &",
                     "[perms=0444] build/ifs.build=" + root + "ifs-bell.build",
                     "[perms=0444] build.date = output/build/ifs-bell.build.date",
                     "[perms=555] qnx-safety-monitor=" + root + "qnx-safety-monitor-bell"], added
    at = {ln: i for i, ln in enumerate(bell)}
    assert at["/proc/boot/qnx-its-probe msixcfg"] < at["/proc/boot/qnx-safety-monitor shmkick ivshmem@8192 msix &"]
