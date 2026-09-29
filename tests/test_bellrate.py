"""The doorbell against the console kick at three spacings (Phase 3b / A6, 2026-09-29): run-bellrate.sh's
header and bellrate_report.py end to end on synthetic rounds. Every number here is synthetic: round
values chosen to clear or miss each threshold by construction, matching no record."""
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

REPORT = os.path.join(GC, "bellrate_report.py")
HARNESS = os.path.join(GC, "run-bellrate.sh")
BASH = shutil.which("bash")
ARMS = ("K2", "B2", "Kf", "Bf", "Ke", "Be")
SPACING = {"2": 2.0, "f": 0.2, "e": 2.0}
CONSOLE = ("its: msixcfg: ivshmem 00:01.0 BAR1 0x12340000 (4096 B), MSI-X entry 0 -> 0x12350040 data 0, DeviceID 0x8 "
           "EventID 0 -> LPI 8193 (ITT 0x12360000), MC 0x1234 cmd 0x0abc\n"
           "monitor: safety monitor serving shm-kick on ivshmem 00:01.0 BAR2 0x12000000; slot @4096; peer 1; "
           "kick /dev/vcon2 (raw) (frame=64 bytes)\n"
           "monitor: safety monitor serving shm-kick on ivshmem 00:01.0 BAR2 0x12000000; slot @8192; peer 1; "
           "kick msix (LPI 8193) (frame=64 bytes)\n")
# p50 per arm: S = B - K is -300 at 2 ms and for exp, -290 at 0.2 ms, so S(0.2) - S(2) = Bf - 350
BASE = {"K2": 700.0, "B2": 400.0, "Kf": 650.0, "Bf": 360.0, "Ke": 710.0, "Be": 410.0}
# halt wake-ups per exchange: K wakes more at 2 ms; polling ends most halts at 0.2 ms for both
WAKE = {"K2": 5.0, "B2": 3.0, "Kf": 1.5, "Bf": 1.2, "Ke": 4.8, "Be": 2.9}
POLLS = {"K2": 0.05, "B2": 0.05, "Kf": 2.0, "Bf": 1.5, "Ke": 0.3, "Be": 0.3}


def _run(out, k=12, p50=None, wake=None, polls=None, jitter=0.3, gap=250.0, edit=None, drop=None, n=1000,
         warm=200, seed=7, wake_jitter=0.02):
    """edit: {(arm, round): fn(summary)}; drop: (arm, round) whose lat file is left out."""
    out.mkdir(parents=True)
    p50, wake, polls = dict(BASE, **(p50 or {})), dict(WAKE, **(wake or {})), dict(POLLS, **(polls or {}))
    rng = random.Random(seed)
    ex = n + warm
    for r in range(1, k + 1):
        for a in ARMS:
            j = rng.uniform(-jitter, jitter)
            v = p50[a] + j
            s = {"n": n, "warmup_discarded": warm, "bad": 0, "rejected_by_monitor": 0,
                 "proto": "shmdb" if a[0] == "K" else "shmbell", "cpu_affinity": [4], "interval_ms": SPACING[a[1]],
                 "p50_ms": v / 1000.0, "p90_ms": (v + 5) / 1000.0, "p99_ms": (v + 30) / 1000.0,
                 "p999_ms": (v + 60) / 1000.0,
                 "period_us": {"p50": v + (gap if a[1] == "f" else 2000.0), "mean": v + 2000.0},
                 "notify": {"exchanges": ex, "wakeups": ex, "early_wakeups": 0, "notifications": ex,
                            "stray": 0, "eagain": 0}}
            if a[1] == "e":
                s["arrival"] = {"kind": "exp", "seed": r * 10, "draws": ex,
                                "sleep_ms": {"mean": 2.03, "p50": 1.4, "sd": 2.0, "max": 15.0}}
            for fn in [f for (ea, er), f in (edit or {}).items() if (ea, er) == (a, r)]:
                fn(s)
            if drop != (a, r):
                (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
            kv = {"before": {"counters": {"halt_successful_poll": 10, "halt_wakeup": 10, "exits": 10}},
                  "after": {"counters": {"halt_successful_poll": 10 + int(polls[a] * ex),
                                         "halt_wakeup": 10 + int((wake[a] + rng.uniform(-wake_jitter, wake_jitter)) * ex),
                                         "exits": 10 + 7 * ex}}}
            (out / ("kvm-%s_r%d.json" % (a, r))).write_text(json.dumps(kv))
        (out / ("console-A_r%d.log" % r)).write_text(CONSOLE)
    (out / "stamp.json").write_text(json.dumps({"n": n, "warmup": warm, "k": k, "pin": {"probe": 4},
                                                "kvm_halt_poll": {"halt_poll_ns": "500000"}}))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag)[1].split("\n")[0]


def test_the_expected_pattern_holds_all_three(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    for m in ("M1", "M2", "M3", "M4"):
        assert "FAILED" not in _line(s, m), s
    assert "-> ok" in _line(s, "M5") and "-> ok" in _line(s, "M6")
    for p in ("P1", "P2", "P3"):
        assert _line(s, p).endswith("-> HELD"), s


def test_each_prediction_can_fail(tmp_path):
    cases = [({"p50": {"Bf": 352.0}}, "P1", "PARTIAL"),                        # +2: above 0, under +3
             ({"p50": {"Bf": 348.0}}, "P1", "REFUTED"),                        # the difference grows
             ({"p50": {"Bf": 354.0}}, "P1", "HELD"),
             ({"p50": {"Bf": 354.0}, "jitter": 10.0}, "P1", "UNRESOLVED"),     # past +3, interval over 0
             ({"p50": {"Be": 413.0}}, "P2", "HELD"),
             ({"p50": {"Be": 414.0}, "jitter": 6.0}, "P2", "PARTIAL"),        # median within, interval not
             ({"p50": {"Be": 416.0}}, "P2", "REFUTED"), ({"p50": {"Be": 404.0}}, "P2", "REFUTED"),
             ({"wake": {"Kf": 3.3, "Bf": 1.2}}, "P3", "REFUTED"),              # W(0.2) as large as W(2)
             ({"wake": {"Kf": 3.15}, "wake_jitter": 0.4}, "P3", "REFUTED")]   # median above 0, interval not
    for n_, (kw, p, want) in enumerate(cases):
        _run(tmp_path / str(n_), **kw)
        s = _report(tmp_path / str(n_))
        assert _line(s, p).split("-> ")[1].startswith(want), (kw, s)


def test_the_qualifiers_note_but_do_not_void(tmp_path):
    cases = [({"polls": {"Kf": 0.3}}, "M5", "H1's premise not met"),           # K's polls do not rise
             ({"polls": {"B2": 1.4}}, "M5", "H1's premise not met"),           # B's rise is too small
             ({"gap": 480.0}, "M5", "H1's premise not met"),                   # idle gap near the window
             ({"p50": {"B2": 710.0, "Be": 720.0, "Bf": 670.0}}, "M6", "S(2 ms) not below 0")]
    for n_, (kw, check, note) in enumerate(cases):
        _run(tmp_path / str(n_), **kw)
        s = _report(tmp_path / str(n_))
        assert "-> FAILED" in _line(s, check), (kw, s)
        assert note in _line(s, "P1") and "VOID" not in _line(s, "P1"), (kw, s)
        assert note not in _line(s, "P2"), (kw, s)


def test_failed_checks_void(tmp_path):
    def no_arrival(s):
        s.pop("arrival")

    def exp_on_const(s):
        s["arrival"] = {"kind": "exp", "seed": 1, "draws": 1200, "sleep_ms": {"mean": 2.0, "sd": 2.0}}

    def few_draws(s):
        s["arrival"]["sleep_ms"]["mean"] = 2.5

    def wrong_spacing(s):
        s["interval_ms"] = 0.5

    def no_p999(s):
        s.pop("p999_ms")

    def eagain(s):
        s["notify"]["eagain"] = 1

    cases = [({"edit": {("Ke", 2): no_arrival}}, "M1"), ({"edit": {("Kf", 2): exp_on_const}}, "M1"),
             ({"edit": {("Be", 3): few_draws}}, "M1"), ({"edit": {("Bf", 4): wrong_spacing}}, "M1"),
             ({"edit": {("K2", 5): no_p999}}, "M1"), ({"drop": ("Kf", 6)}, "M1"),
             ({"edit": {("B2", 7): eagain}}, "M2")]
    for n_, (kw, check) in enumerate(cases):
        _run(tmp_path / str(n_), **kw)
        s = _report(tmp_path / str(n_))
        assert "-> FAILED" in _line(s, check), (kw, s)
        for p in ("P1", "P2", "P3"):
            assert "VOID" in _line(s, p), (kw, p, s)
    _run(tmp_path / "k")
    os.remove(tmp_path / "k" / "kvm-Bf_r3.json")
    s = _report(tmp_path / "k")
    assert "-> FAILED" in _line(s, "M4") and "not evaluated" in _line(s, "M5")
    assert "VOID" in _line(s, "P3") and "VOID" not in _line(s, "P1") and "premise not evaluated" in _line(s, "P1")


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    flat = " ".join(ln.lstrip("#").strip() for ln in head.splitlines())
    for s in ("median of S(0.2 ms) - S(2 ms) >= +3.0 us with the interval's lower end above 0: HELD",
              "UNRESOLVED", "median of W(2 ms) - W(0.2 ms) > 0 with the interval's lower end above 0: HELD",
              "median of S(exp) - S(2 ms) within +-5.0 us with the whole interval within it: HELD",
              "It is not to be amended", "d(3)..d(10), 96.1%, at K = 12", "Williams order over the six (period 6)",
              "P1 and P2 rest on M1-M3; P3 on M1-M4", "What this does NOT test", "vgic_mmio_write_its_cwriter",
              "kvm_vcpu_wake_up", "halt_poll_ns must read 500000", "co-variation"):
        assert s in flat, s
    for leak in ("wakes a halted vCPU more often", "the rate record's mechanism", "saving"):
        assert leak not in head, leak
    assert 'MODES=(K2 B2 Kf Bf Ke Be)' in body and "bellrate_report.py" in body
    arm = body.split("run_arm() {")[1].split("\n}\n")[0]
    assert "?f) iv=0.2 ;;" in arm and '?e) arr=exp; seed="$((r * 10))" ;;' in arm
    assert arm.count('PROBE_SEED="$seed"') == 2 and '*) die "no way in for $a" ;;' in arm
    assert 'IMG_B="${IMG_B:-$HOME/output/ifs-bell.bin}"' in body
    assert "halt_poll_ns is not 500000" in body and '"\\"kvm_halt_poll\\": $HALT_POLL"' in body
    assert "INTERVAL_MS='\"per arm: see spacings\"' m_write_stamp" in body


def test_what_is_known_names_records_and_quotes_no_figure():
    text = open(HARNESS, encoding="utf-8").read()
    known = rg.known_sections(text)
    joined = " ".join(line for _n, line in known)
    for rec in ("20260929T-a6-orin-bell", "20260929T-a6-a1metal-bell", "20260929T-a6-orin-mmio",
                "20260929T-a6-orin-paths", "20260929T-a6-orin-unmask", "20260924T-a6-orin-rate",
                "20260924T-a6-orin-haltpoll", "20260924T-a6-orin-arrival", "20260924T-a6-orin-blockpath"):
        assert rec in joined, rec
    assert [f for _n, line in known for f in rg.figures(line)] == []
