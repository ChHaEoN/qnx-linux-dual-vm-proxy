"""The same-run ladder of every way across the partition (Phase 3b / A6, 2026-09-29): run-paths.sh's
header, paths_report.py end to end on synthetic rounds, and ifs-paths.build as ifs-bell.build plus
exactly the SOME/IP lines. Every number here is synthetic: round values chosen to clear or miss
each threshold by construction."""
import difflib
import json
import os
import random
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "ci"))
import results_guard as rg  # noqa: E402

REPORT = os.path.join(GC, "paths_report.py")
HARNESS = os.path.join(GC, "run-paths.sh")
IFS_DIR = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor")
BASH = shutil.which("bash")
PROTO = {"T": "tcp", "U": "udp", "S": "someip", "P": "shm", "K": "shmdb", "B": "shmbell"}
# The lines' shapes are the tools' own printf formats; every value is made up.
CONSOLE = ("its: msixcfg: ivshmem 00:01.0 BAR1 0x12340000 (4096 B), MSI-X entry 0 -> 0x12350040 data 0, "
           "DeviceID 0x8 EventID 0 -> LPI 8193 (ITT 0x12360000), MC 0x8000 cmd 0x0006\n"
           "monitor: safety monitor serving shm-kick on ivshmem 00:01.0 BAR2 0x12000000; slot @4096; peer 1; "
           "kick /dev/vcon2 (raw) (frame=64 bytes, conf_min=60%)\n"
           "monitor: safety monitor serving shm-kick on ivshmem 00:01.0 BAR2 0x12000000; slot @8192; peer 1; "
           "kick msix (LPI 8193) (frame=64 bytes, conf_min=60%)\n")
BASE = {"T": 500.0, "U": 450.0, "S": 500.0, "P": 100.0, "K": 400.0, "B": 200.0}
SPACING_NS = 2000000


def _run(out, k=18, rounds=None, p50=None, swing=None, lat_edit=None, notify_edit=None, console_drop=None,
         no_kvm=False, drop_vcpu=False, missing_arm=None, smoke=0, n=1000, warm=200, seed=5):
    """swing: {arm: s} adds +s in odd rounds and -s in even ones; lat_edit/notify_edit: {(arm, round):
    {field: value}}; console_drop: (round, substring) removes that line from that boot's console."""
    p50 = dict(BASE, **(p50 or {}))
    out.mkdir(parents=True)
    rng = random.Random(seed)
    ex = n + warm
    for r in range(1, (rounds or k) + 1):
        for a in PROTO:
            if a == missing_arm:
                continue
            j = rng.uniform(-2, 2) + ((swing or {}).get(a, 0.0) * (1 if r % 2 else -1))
            s = {"n": n, "warmup_discarded": warm, "bad": 0, "rejected_by_monitor": 0, "proto": PROTO[a],
                 "cpu_affinity": [4], "p50_ms": (p50[a] + j) / 1000.0, "p90_ms": (p50[a] + j + 6) / 1000.0,
                 "p99_ms": (p50[a] + j + 30) / 1000.0, "p999_ms": (p50[a] + j + 60) / 1000.0}
            if a in ("K", "B"):
                s["notify"] = {"exchanges": ex, "wakeups": ex, "early_wakeups": 0, "notifications": ex,
                               "stray": 0, "eagain": 0}
                s["notify"].update((notify_edit or {}).get((a, r), {}))
            s.update((lat_edit or {}).get((a, r), {}))
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
            if not no_kvm:
                spin = 2000.0 if a == "P" else 30.0
                before = {"t_ns": 0, "counters": {"exits": 1000}, "threads": {
                    "11": {"comm": "CPU 0/KVM", "run_ns": 1000}, "12": {"comm": "CPU 1/KVM", "run_ns": 2000},
                    "13": {"comm": "qemu-system-aar", "run_ns": 5}}}
                after = {"t_ns": ex * SPACING_NS, "counters": {"exits": 1000 + 10 * ex}, "threads": {
                    "11": {"comm": "CPU 0/KVM", "run_ns": 1000 + int(spin * 1000 * ex / 2)},
                    "12": {"comm": "CPU 1/KVM", "run_ns": 2000 + int(spin * 1000 * ex / 2)},
                    "13": {"comm": "qemu-system-aar", "run_ns": 999999}}}
                if drop_vcpu and a == "T" and r == 3:
                    del after["threads"]["12"]
                (out / ("kvm-%s_r%d.json" % (a, r))).write_text(json.dumps({"before": before, "after": after}))
        text = CONSOLE
        if console_drop and console_drop[0] == r:
            text = "".join(ln for ln in CONSOLE.splitlines(True) if console_drop[1] not in ln)
        (out / ("console-A_r%d.log" % r)).write_text(text)
    (out / "stamp.json").write_text(json.dumps({"n": n, "warmup": warm, "k": k, "smp": 2, "smoke": smoke,
                                                "pin": {"qemu": "0-2", "probe": 4}}))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag)[1].split("\n")[0]


def _verdicts(s):
    return {p: _line(s, p).split("-> ")[1] for p in ("P1", "P2", "P3", "P4")}


def _row(s, arm):
    return re.search(r"^    %s +%s +(.*)$" % (arm, PROTO[arm]), s, re.M).group(1).split()


def test_the_expected_ordering_holds_everything_and_shows_the_spinning_vcpu(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    for m in ("M1", "M2", "M3", "M4"):
        assert "FAILED" not in _line(s, m), s
    assert set(_verdicts(s).values()) == {"HELD"}, s
    # columns: p50 p90 p99 p99.9, vCPU us/ex, exits/ex, vCPU busy %
    assert _row(s, "P")[4:] == ["2000.0", "10.00", "50.0"], s
    assert _row(s, "B")[4:] == ["30.0", "10.00", "0.8"], s


def test_each_prediction_can_fail_on_its_own(tmp_path):
    cases = [
        ({"B": 440.0}, None, {"P1": "PARTIAL", "P4": "REFUTED"}),   # B - T -60, B - U -10, B - K +40
        ({"U": 240.0}, None, {"P1": "PARTIAL"}),                    # B - T meets its bound, B - U does not
        ({"B": 520.0}, None, {"P1": "REFUTED", "P4": "REFUTED"}),
        ({"B": 370.0}, None, {"P4": "PARTIAL"}),                   # B - K -30: below 0, not -40
        ({"P": 190.0}, None, {"P2": "PARTIAL"}),
        ({"P": 250.0}, None, {"P2": "REFUTED"}),
        ({"P": 195.0}, {"P": 30.0}, {"P2": "REFUTED"}),              # median below 0, interval over it
        ({"S": 515.0}, None, {"P3": "REFUTED"}),
        ({"S": 485.0}, None, {"P3": "REFUTED"}),                    # S faster than T by more than the band
        ({}, {"S": 10.0}, {"P3": "PARTIAL"}),                       # median inside, interval not
    ]
    for i, (p50, swing, want) in enumerate(cases):
        _run(tmp_path / str(i), p50=p50, swing=swing)
        got = _verdicts(_report(tmp_path / str(i)))
        assert got == dict({p: "HELD" for p in got}, **want), (p50, swing, got)


def test_a_failed_check_voids_only_the_predictions_resting_on_it(tmp_path):
    cases = [
        ({"notify_edit": {("K", 2): {"stray": 1}}}, "M2", {"P4"}),
        ({"notify_edit": {("B", 5): {"eagain": 1}}}, "M2", {"P1", "P2", "P4"}),
        ({"notify_edit": {("B", 5): {"wakeups": 1201}}}, "M2", {"P1", "P2", "P4"}),
        ({"lat_edit": {("S", r): {"proto": "tcp"} for r in range(1, 19)}}, "M1", {"P3"}),
        ({"lat_edit": {("K", 7): {"cpu_affinity": [5]}}}, "M1", {"P4"}),
        ({"lat_edit": {("T", 7): {"warmup_discarded": 0}}}, "M1", {"P1", "P3"}),
        ({"missing_arm": "S"}, "M1", {"P3"}),
        ({"console_drop": (4, "kick msix")}, "M3", {"P1", "P2", "P4"}),
        ({"console_drop": (4, "kick /dev/vcon2")}, "M3", {"P4"}),
        ({"console_drop": (4, "msixcfg")}, "M3", {"P1", "P2", "P4"}),
        ({"rounds": 6}, "M1", {"P1", "P2", "P3", "P4"}),            # the stamp says k=18
    ]
    for i, (kw, check, voided) in enumerate(cases):
        _run(tmp_path / str(i), **kw)
        s = _report(tmp_path / str(i))
        assert "-> FAILED" in _line(s, check), (kw, s)
        got = _verdicts(s)
        assert {p for p, v in got.items() if v.startswith("VOID")} == voided, (kw, got)
        assert all(v == "HELD" for p, v in got.items() if p not in voided), (kw, got)


def test_m4_rests_nothing_and_fails_on_a_partial_snapshot(tmp_path):
    for i, kw in enumerate(({"no_kvm": True}, {"drop_vcpu": True})):
        _run(tmp_path / str(i), **kw)
        s = _report(tmp_path / str(i))
        assert "-> FAILED" in _line(s, "M4"), s
        assert set(_verdicts(s).values()) == {"HELD"}, s


def test_off_rule_k_and_smoke_runs_are_unscored(tmp_path):
    _run(tmp_path / "a", k=6)
    _run(tmp_path / "b", smoke=1)
    for d in ("a", "b"):
        s = _report(tmp_path / d)
        assert "FAILED" not in _line(s, "M1"), s
        assert all(v.startswith("UNSCORED") for v in _verdicts(s).values()), s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    flat = " ".join(ln.lstrip("#").strip() for ln in head.splitlines())
    for s in ("B - T <= -80 us AND B - U <= -60 us", "P - B <= -15 us",
              "|median DIFF(p50) S - T| <= 3 us with the interval inside [-3, +3] us", "B - K <= -40 us",
              "It is not to be amended", "Williams order over the six (period 6)", "d(5)..d(14), 96.9%, at K = 18",
              "P3 on M1 (S, T)", "NOT one client", "What this does NOT test", "ON AWS a1.metal"):
        assert s in flat, s
    for gone in ("Autoware", "third run", "item 4", "follow-ups"):
        assert gone not in head, gone
    assert 'ARM_PROTOS="T=tcp U=udp S=someip P=shm K=shmdb B=shmbell"' in body and "paths_report.py" in body
    assert 'IMG_P="${IMG_P:-${IFS_BIN:-' in body, "scripts/aws passes the image as IFS_BIN"
    assert '[ "$K" = 18 ] || [ "$SMOKE" = 1 ]' in body and '"\\"smp\\": $SMP"' in body


def test_what_is_known_names_records_and_quotes_no_figure():
    text = open(HARNESS, encoding="utf-8").read()
    known = rg.known_sections(text)
    joined = " ".join(line for _n, line in known)
    for rec in ("20260922T-a6-orin-kick", "20260922T-a6-orin-shm", "20260922T-a6-orin-shift",
                "20260927T-a6-orin-someip", "20260929T-a6-orin-its", "20260929T-a6-orin-bell",
                "20260929T-a6-a1metal-bell"):
        assert rec in joined, rec
    assert [f for _n, line in known for f in rg.figures(line)] == []


def test_ifs_paths_is_ifs_bell_plus_exactly_the_someip_lines_in_place():
    def lines(name):
        with open(os.path.join(IFS_DIR, name), encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    bell, paths = lines("ifs-bell.build"), lines("ifs-paths.build")
    root = "E:/Project/qnx-linux-dual-vm-proxy/ipc-test/"
    ops = [(tag, bell[i1:i2], paths[j1:j2])
           for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, bell, paths, autojunk=False).get_opcodes()
           if tag != "equal"]
    assert ops == [
        ("insert", [], ["/proc/boot/qnx-someip-monitor 30509 &"]),
        ("replace", ["[perms=0444] build/ifs.build=" + root + "qnx-safety-monitor/ifs-bell.build"],
         ["[perms=0444] build/ifs.build=" + root + "qnx-safety-monitor/ifs-paths.build"]),
        ("replace", ["[perms=0444] build.date = output/build/ifs-bell.build.date"],
         ["[perms=0444] build.date = output/build/ifs-paths.build.date"]),
        ("insert", [], ["[perms=555] qnx-someip-monitor=" + root + "qnx-someip/qnx-someip-monitor"]),
    ], ops
    at = {ln: i for i, ln in enumerate(paths)}
    assert at["/proc/boot/startup.sh"] < at["/proc/boot/qnx-someip-monitor 30509 &"], "after io-sock is up"
    assert at["/proc/boot/qnx-someip-monitor 30509 &"] == at["/proc/boot/qnx-echo-server-net 7001 udp &"] + 1
    assert at["/proc/boot/qnx-its-probe msixcfg"] < at["/proc/boot/qnx-safety-monitor shm ivshmem &"]
