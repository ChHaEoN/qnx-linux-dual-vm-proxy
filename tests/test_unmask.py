"""Where the doorbell's LPI is unmasked (Phase 3b / A6, 2026-09-29): run-unmask.sh's header and
unmask_report.py end to end on synthetic rounds. Every number here is synthetic: round values chosen
to clear or miss each threshold by construction, matching no record."""
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

REPORT = os.path.join(GC, "unmask_report.py")
HARNESS = os.path.join(GC, "run-unmask.sh")
BASH = shutil.which("bash")
VECTOR = {"a": {"U": 0, "D": 1}, "b": {"U": 1, "D": 0}}
SLOT = {0: 8192, 1: 12288}
MSIX = ("its: msixcfg: ivshmem 00:01.0 BAR1 0x12340000 (4096 B), MSI-X entry 0 -> 0x12350040 data 0, DeviceID 0x8 "
        "EventID 0 -> LPI 8193 (ITT 0x12360000), MC 0x1234 cmd 0x0abc\n"
        "its: msixcfg: MSI-X entry 1 -> 0x12350040 data 1, DeviceID 0x8 EventID 1 -> LPI 8194\n")
BANNER = "monitor: safety monitor serving shm-kick on ivshmem 00:01.0 BAR2 0x12000000; slot @%d; peer 1; kick %s (frame=64 bytes)\n"
WAITS = {"a": ((8192, "msix (LPI 8193)"), (12288, "msix1:defer (LPI 8194, unmask deferred)")),
         "b": ((8192, "msix:defer (LPI 8193, unmask deferred)"), (12288, "msix1 (LPI 8194)"))}


def image_of(r):
    return "a" if ((r - 1) // 2) % 2 == 0 else "b"


def _run(out, k=16, u=300.0, dd=290.0, mk=(3.0, 3.0), hw=(2.0, 2.0), jitter=0.2, wrong_vector=False,
         wrong_slot=False, stray=False, drop_banner=False, swap_banner=False, drop_kvm=False, n=1000, warm=200, seed=3):
    out.mkdir(parents=True)
    rng = random.Random(seed)
    ex = n + warm
    order = []
    for r in range(1, k + 1):
        im = image_of(r)
        arms = ["U", "D"] if r % 2 else ["D", "U"]
        order.append("round %d image %s order: %s" % (r, im, " ".join(arms)))
        for a, p50, kern, wake in (("U", u, mk[0], hw[0]), ("D", dd, mk[1], hw[1])):
            j = rng.uniform(-jitter, jitter)
            v = VECTOR[im][a]
            slot = SLOT[1 - v] if (wrong_slot and r == 6 and a == "D") else SLOT[v]
            if wrong_vector and r == 3 and a == "U":
                v = 1 - v                                    # the vector wrong, the slot right
            s = {"n": n, "warmup_discarded": warm, "bad": 0, "rejected_by_monitor": 0, "proto": "shmbell",
                 "cpu_affinity": [4], "p50_ms": (p50 + j) / 1000.0, "p90_ms": (p50 + j + 5) / 1000.0,
                 "p99_ms": (p50 + j + 20) / 1000.0, "p999_ms": (p50 + j + 40) / 1000.0,
                 "shm_region": "file /dev/shm/unmask-test, 4096 bytes, slot @%d" % slot,   # the probe's own format
                 "notify": {"exchanges": ex, "wakeups": ex, "early_wakeups": 0, "notifications": ex,
                            "stray": 1 if (stray and a == "D" and r == 5) else 0, "eagain": 0}}
            if v:
                s["bell_vector"] = v
            (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
            if not (drop_kvm and r == 2):
                kv = {"before": {"counters": {"mmio_exit_kernel": 100, "exits": 100, "halt_wakeup": 10}},
                      "after": {"counters": {"mmio_exit_kernel": 100 + int(kern * ex), "exits": 100 + 5 * ex,
                                             "halt_wakeup": 10 + int(wake * ex)}}}
                (out / ("kvm-%s_r%d.json" % (a, r))).write_text(json.dumps(kv))
        waits = WAITS[im]
        if swap_banner and r == 9:
            waits = WAITS["b" if im == "a" else "a"]
        text = MSIX + "".join(BANNER % w for w in waits)
        if drop_banner and r == 7:
            text = MSIX + BANNER % waits[0]
        (out / ("console-A_r%d.log" % r)).write_text(text)
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "stamp.json").write_text(json.dumps({"n": n, "warmup": warm, "k": k, "pin": {"probe": 4}}))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag)[1].split("\n")[0]


def test_the_image_schedule_balances_image_and_order():
    combos = {}
    for r in range(1, 17):
        key = (image_of(r), r % 2)
        combos[key] = combos.get(key, 0) + 1
    assert combos == {("a", 1): 4, ("a", 0): 4, ("b", 1): 4, ("b", 0): 4}
    text = open(HARNESS, encoding="utf-8").read()
    assert "if [ $(( (($1 - 1) / 2) % 2 )) = 0 ]; then echo a; else echo b; fi" in text
    assert 'case "$1$2" in aU|bD) echo 0 ;; *) echo 1 ;; esac' in text


def test_the_expected_saving_holds_both(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    for m in ("M1", "M2", "M3", "M4"):
        assert "FAILED" not in _line(s, m), s
    assert "-> ok" in _line(s, "M5")
    assert _line(s, "P1").endswith("-> HELD") and _line(s, "P2").endswith("-> HELD"), s
    assert "vector effect, (a - b) / 2, unscored" in s


def test_each_prediction_can_fail(tmp_path):
    cases = [({"dd": 299.0}, "P1", "PARTIAL"), ({"dd": 301.0}, "P1", "REFUTED"), ({"dd": 298.0}, "P1", "HELD"),
             ({"dd": 297.5, "jitter": 15.0}, "P1", "REFUTED"),                   # interval over 0
             ({"mk": (3.0, 3.5)}, "P2", "HELD"), ({"mk": (3.0, 3.6)}, "P2", "REFUTED"),
             ({"mk": (3.0, 2.4)}, "P2", "REFUTED")]
    for n_, (kw, p, want) in enumerate(cases):
        _run(tmp_path / str(n_), **kw)
        s = _report(tmp_path / str(n_))
        assert _line(s, p).endswith("-> " + want), (kw, s)


def test_differing_wake_ups_qualify_but_do_not_void(tmp_path):
    _run(tmp_path / "o", hw=(2.0, 2.5))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M5")
    for p in ("P1", "P2"):
        assert "HELD -- H1 not supported: the ways differ in wake-ups" in _line(s, p), s


def test_failed_checks_void_what_rests_on_them(tmp_path):
    cases = [({"wrong_vector": True}, "M1", ("P1", "P2")), ({"wrong_slot": True}, "M1", ("P1", "P2")),
             ({"stray": True}, "M2", ("P1", "P2")), ({"drop_banner": True}, "M3", ("P1", "P2")),
             ({"swap_banner": True}, "M3", ("P1", "P2")), ({"drop_kvm": True}, "M4", ("P2",))]
    for n_, (kw, check, voided) in enumerate(cases):
        _run(tmp_path / str(n_), **kw)
        s = _report(tmp_path / str(n_))
        assert "-> FAILED" in _line(s, check), (kw, s)
        for p in ("P1", "P2"):
            assert ("VOID" in _line(s, p)) == (p in voided), (kw, p, s)


def test_an_image_with_no_rounds_prints_no_data(tmp_path):
    _run(tmp_path / "o", k=2)
    s = _report(tmp_path / "o")
    assert "p50 in image b (way +- vector), unscored" in s and "(no data)" in _line(s, "  p50 in image b"), s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    flat = " ".join(ln.lstrip("#").strip() for ln in head.splitlines())
    for s in ("median DIFF(p50) D - U <= -2.0 us with the interval's upper end below 0: HELD",
              "|median DIFF(mmio_exit_kernel per exchange) D - U| <= 0.5", "It is not to be amended",
              "d(4)..d(13), 97.9%, at K = 16", "P1 rests on M1-M3; P2 on M1-M4",
              "|median DIFF(halt_wakeup per exchange) D - U| <= 0.3", "What this does NOT test",
              "SDP 8.0 has no ISR", "no lightweight block", "the probe's output went to files that were not read",
              "The preflight boots both images"):
        assert s in flat, s
    assert "VECTORS=2" in body and 'PROBE_BELL_VECTOR="$v" m_probe' in body and "unmask_report.py" in body
    assert "ivshmem-doorbell,chardev=ivsh0,vectors=2" in body
    boot = body.split("boot_vm() {")[1].split("\n}\n")[0]
    assert 'up_check 0 "$lab-v0"' in boot and 'up_check 1 "$lab-v1"' in boot, "each vector's first wait is untimed"
    assert "boot_vm preflight-b b" in body and "boot_vm preflight-a a" in body


def test_what_is_known_names_records_and_quotes_no_figure():
    text = open(HARNESS, encoding="utf-8").read()
    known = rg.known_sections(text)
    joined = " ".join(line for _n, line in known)
    for rec in ("20260929T-a6-orin-bell", "20260929T-a6-orin-mmio", "20260929T-a6-orin-paths"):
        assert rec in joined, rec
    assert [f for _n, line in known for f in rg.figures(line)] == []
