"""Where the two ways into the guest trap (Phase 3b / A6, 2026-09-29): mmio_trace.py on synthetic
ftrace text, mmio_report.py end to end on synthetic windows reduced by it, and run-mmio.sh's header.
Every number here is synthetic: addresses are QEMU virt's map and made-up BARs, counts are round
values chosen to clear or miss each threshold by construction."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "ci"))
import mmio_trace  # noqa: E402
import results_guard as rg  # noqa: E402

REPORT = os.path.join(GC, "mmio_report.py")
HARNESS = os.path.join(GC, "run-mmio.sh")
BASH = shutil.which("bash")
BAR0, BAR1 = 0x12300000, 0x12301000
CONSOLE = ("GICv3: 8192 LPI interrupts\nSetting up ITS based LPIs\n"
           "monitor: shm configured: ivshmem 00:01.0 BAR2 0x12000000 (1048576 bytes, prefetchable) "
           "BAR0 %#x (256 bytes), addresses assigned here, cmd=0x0002\n"
           "its: msixcfg: ivshmem 00:01.0 BAR1 %#x (4096 B), MSI-X entry 0 -> 0x8090040 data 0, "
           "DeviceID 0x8 EventID 0 -> LPI 8193 (ITT 0x12360000), MC 0x8000 cmd 0x0006\n" % (BAR0, BAR1))
GICD_ICEN, GICD_ISEN, GICD_CTLR = 0x08000184, 0x08000104, 0x08000000
GITS_CWRITER = 0x08080088
CON = 0x0A003800
CON_STATUS, CON_ACK, CON_NOTIFY = CON + 0x60, CON + 0x64, CON + 0x50
DB = BAR0 + 0xC
UART = 0x09000000
SPACING = 2000000
# Per exchange: (gpa, 'r'|'w', handled in userspace, share of exchanges it happens in)
K_EX = [(CON_STATUS, "r", True, 1.0), (CON_ACK, "w", True, 1.0), (CON_NOTIFY, "w", False, 1.0),
        (GICD_ICEN, "w", False, 1.0), (GICD_CTLR, "r", False, 1.0), (GICD_ISEN, "w", False, 1.0),
        (DB, "w", False, 1.0)]
B_EX = [(GITS_CWRITER, "r", False, 1.0), (GITS_CWRITER, "w", False, 1.0),
        (GITS_CWRITER, "r", False, 1.0), (GITS_CWRITER, "w", False, 1.0), (DB, "w", False, 1.0)]


def line(task, ts, body):
    return "  %s [001] d..1. %.6f: %s" % (task, ts, body)


def trace_text(items, lost=None, bad_header=False, extra_lines=()):
    """items: (gpa, rw, user, count) -- count accesses of each, in round-robin order."""
    lines, ts, left = [], 100.0, [list(it) for it in items]
    while any(it[3] > 0 for it in left):
        for it in left:
            if it[3] <= 0:
                continue
            it[3] -= 1
            gpa, rw, user = it[0], it[1], it[2]
            ts += 0.000001
            task = "CPU 1/KVM-1235" if gpa == DB else "CPU 0/KVM-1234"
            lines.append(line(task, ts, "kvm_mmio: mmio %s len 4 gpa %#x val 0x0"
                              % ("unsatisfied-read" if rw == "r" else "write", gpa)))
            if user:
                lines.append(line(task, ts, "kvm_userspace_exit: reason KVM_EXIT_MMIO (6)"))
            if rw == "r":
                lines.append(line(task, ts, "kvm_mmio: mmio read len 4 gpa %#x val 0x0" % gpa))
    lines += list(extra_lines)
    n = len(lines)
    head = ["# tracer: nop", "#", "# entries-in-buffer/entries-written: %d/%d   #P:6" % (n, n + bad_header), "#"]
    if lost:
        lines.insert(len(lines) // 2, lost)
    return "\n".join(head + lines) + "\n"


def reduce(text):
    doc, err = mmio_trace.reduce(text.splitlines(True))
    assert err is None, err
    return doc


def _run(out, k=6, n=100, warm=20, k_ex=None, b_ex=None, bg=(), counter_skew=(0, 0), notify=None,
         drop=None, extra_lines=None, stamp_k=None):
    """bg: (gpa, rw, user, per-2-ms rate) in every window; counter_skew: added to KVM's (kernel, user)
    counts in B_r2; notify: {(arm, round): {field: value}}; drop: (round, 'window'|'bars')."""
    out.mkdir(parents=True)
    ex = n + warm
    durs = {"K": int(ex * SPACING * 1.3), "B": int(ex * SPACING * 1.25), "I": int(ex * SPACING * 1.1)}
    for r in range(1, k + 1):
        (out / ("console-A_r%d.log" % r)).write_text("" if drop == (r, "bars") else CONSOLE)
        for a, per in (("K", k_ex or K_EX), ("B", b_ex or B_EX), ("I", [])):
            items = [(g, w, u, int(round(share * ex))) for g, w, u, share in per]
            items += [(g, w, u, int(round(rate * durs[a] / SPACING))) for g, w, u, rate in bg]
            text = trace_text(items, extra_lines=(extra_lines or {}).get((a, r), ()))
            (out / ("mmio-%s_r%d.json" % (a, r))).write_text(json.dumps(reduce(text)))
            if drop != (r, "window") or a != "K":
                (out / ("window-%s_r%d.json" % (a, r))).write_text(json.dumps({"t0_ns": 5, "t1_ns": 5 + durs[a]}))
            kern = sum(c for _g, _w, u, c in items if not u)
            user = sum(c for _g, _w, u, c in items if u)
            dk, du = counter_skew if (a, r) == ("B", 2) else (0, 0)
            kvm = {"before": {"counters": {"mmio_exit_kernel": 50, "mmio_exit_user": 7}},
                   "after": {"counters": {"mmio_exit_kernel": 50 + kern + dk, "mmio_exit_user": 7 + user + du}}}
            (out / ("kvm-%s_r%d.json" % (a, r))).write_text(json.dumps(kvm))
            if a != "I":
                s = {"n": n, "warmup_discarded": warm, "bad": 0, "rejected_by_monitor": 0,
                     "proto": {"K": "shmdb", "B": "shmbell"}[a], "cpu_affinity": [4], "p50_ms": 0.5,
                     "notify": {"exchanges": ex, "wakeups": ex, "early_wakeups": 0, "notifications": ex,
                                "stray": 0, "eagain": 0}}
                s["notify"].update((notify or {}).get((a, r), {}))
                (out / ("lat-%s_r%d.json" % (a, r))).write_text(json.dumps({"summary": s}))
    stamp = {"n": n, "warmup": warm, "k": k if stamp_k is None else stamp_k, "smp": 2, "pin": {"probe": 4}}
    (out / "stamp.json").write_text(json.dumps(stamp))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag)[1].split("\n")[0]


def _verdicts(s):
    return {p: _line(s, p).split("-> ")[1] for p in ("P1", "P2")}


# ---------------------------------------------------------------- the reducer

def test_the_reducer_counts_accesses_and_marks_userspace_ones():
    doc = reduce(trace_text([(g, w, u, 3) for g, w, u, _s in K_EX]))
    assert doc["accesses"]["%#x|r" % CON_STATUS] == 3 and doc["to_userspace"]["%#x|r" % CON_STATUS] == 3
    assert doc["accesses"]["%#x|w" % GICD_ICEN] == 3 and "%#x|w" % GICD_ICEN not in doc["to_userspace"]
    assert sum(doc["reads_completed"].values()) == 6 and doc["userspace_exits"] == {"KVM_EXIT_MMIO": 6}
    assert sum(doc["accesses"].values()) == 21 and doc["unpaired_mmio_exits"] == 0
    assert doc["lines_matched"] == doc["entries"] == doc["events"]


def test_only_a_kvm_exit_mmio_next_on_the_same_thread_marks_an_access_userspace():
    a, b = "CPU 0/KVM-11", "CPU 1/KVM-12"
    body = [line(a, 1.0, "kvm_mmio: mmio write len 4 gpa 0x8000184 val 0x1"),
            line(a, 1.1, "kvm_userspace_exit: reason restart (-4)"),          # a signal: the write stays kernel
            line(b, 1.2, "kvm_mmio: mmio unsatisfied-read len 4 gpa 0xa003860 val 0x0"),
            line(a, 1.3, "kvm_mmio: mmio write len 4 gpa 0x8000104 val 0x1"),  # A's write, between B's two
            line(b, 1.4, "kvm_userspace_exit: reason KVM_EXIT_MMIO (6)"),      # B's read went out
            line(b, 1.5, "kvm_mmio: mmio read len 4 gpa 0xa003860 val 0x1"),
            line(a, 1.6, "kvm_userspace_exit: reason KVM_EXIT_MMIO (6)")]     # A's second write went out
    text = "# entries-in-buffer/entries-written: 7/7   #P:6\n" + "\n".join(body) + "\n"
    doc = reduce(text)
    assert doc["to_userspace"] == {"0xa003860|r": 1, "0x8000104|w": 1}, doc["to_userspace"]
    assert doc["unpaired_mmio_exits"] == 0


def test_an_exit_with_no_access_before_it_is_counted_unpaired():
    text = ("# entries-in-buffer/entries-written: 1/1   #P:6\n"
            + line("CPU 0/KVM-11", 1.0, "kvm_userspace_exit: reason KVM_EXIT_MMIO (6)") + "\n")
    assert reduce(text)["unpaired_mmio_exits"] == 1


def test_the_reducer_refuses_a_trace_that_may_have_lost_events_or_does_not_parse():
    good = trace_text([(DB, "w", False, 3)])
    cases = [trace_text([(DB, "w", False, 3)], lost="CPU:1 [LOST 12 EVENTS]"),
             trace_text([(DB, "w", False, 3)], lost="CPU:1 [LOST EVENTS]"),
             trace_text([(DB, "w", False, 3)], bad_header=True),
             "\n".join(ln for ln in good.splitlines() if "entries-in-buffer" not in ln),
             good + "a line that is no trace event\n",
             good.replace("mmio write len 4", "mmio write length 4", 1),
             good + line("CPU 0/KVM-11", 9.0, "kvm_userspace_exit: why") + "\n"]
    for i, text in enumerate(cases):
        doc, err = mmio_trace.reduce(text.splitlines(True))
        assert doc is None and err, text[-200:]
        if i < 3:
            assert err.startswith("lost events"), err


def test_a_foreign_event_is_counted_in_the_lines_but_not_the_events():
    text = trace_text([(DB, "w", False, 2)], extra_lines=[line("bash-99", 5.0, "print: tracing_mark_write: hi")])
    doc = reduce(text)
    assert doc["lines_matched"] == doc["entries"] == doc["events"] + 1


# ---------------------------------------------------------------- the report

def test_the_expected_split_holds_both_predictions_and_prints_intervals(tmp_path):
    _run(tmp_path / "o")
    s = _report(tmp_path / "o")
    for m in ("M1", "M2", "M3", "M4"):
        assert "FAILED" not in _line(s, m), s
    assert _verdicts(s) == {"P1": "HELD", "P2": "HELD"}, s
    assert "LPI setup, from the boots' consoles (unscored): Setting up ITS based LPIs" in s
    assert _line(s, "  K GICD").split()[:2] == ["3.000", "[3.000,"], s   # median [interval]


def test_the_background_is_taken_out_within_the_round(tmp_path):
    # B's GICD raw would be 0.3 per 2 ms over its window (> 0.2 per exchange); net of I it is about 0
    _run(tmp_path / "o", bg=[(GICD_ICEN, "w", False, 0.3), (UART, "w", True, 0.5)])
    s = _report(tmp_path / "o")
    assert _verdicts(s) == {"P1": "HELD", "P2": "HELD"}, s
    assert "I  GICD" in s and "I  UART" in s


def test_each_leg_can_fail(tmp_path):
    no_gicd = [x for x in K_EX if not (0x08000000 <= x[0] < 0x08010000)]
    cases = [
        ({"k_ex": no_gicd}, {"P1": "PARTIAL"}),                                           # K's GICD leg
        ({"b_ex": B_EX + [(GICD_ICEN, "w", False, 0.5)]}, {"P1": "PARTIAL"}),             # B's GICD leg
        ({"k_ex": K_EX + [(GITS_CWRITER, "r", False, 0.5)]}, {"P1": "PARTIAL"}),          # K's GITS leg
        ({"b_ex": [x for x in B_EX if x[0] == DB]}, {"P1": "PARTIAL"}),                   # B's GITS leg
        ({"k_ex": no_gicd, "b_ex": [x for x in B_EX if x[0] == DB]}, {"P1": "REFUTED"}),
        ({"k_ex": K_EX + [(0x0A003E50, "w", True, 1.0), (0x0A003E60, "r", True, 1.0)]}, {"P2": "REFUTED"}),
        ({"k_ex": [x for x in K_EX if x[0] != CON_ACK]}, {"P2": "REFUTED"}),               # no ACK write
        ({"k_ex": [x if x[0] != CON_STATUS else (CON_STATUS, "r", False, 1.0) for x in K_EX]},
         {"P2": "REFUTED"}),                                                               # status read in kernel
        ({"b_ex": B_EX + [(CON_STATUS, "r", True, 0.5)]}, {"P2": "REFUTED"}),              # B touches the console
    ]
    for i, (kw, want) in enumerate(cases):
        _run(tmp_path / str(i), **kw)
        got = _verdicts(_report(tmp_path / str(i)))
        assert got == dict({"P1": "HELD", "P2": "HELD"}, **want), (kw, got)


def test_the_thresholds_are_inclusive(tmp_path):
    two = [x for x in K_EX if x[0] != GICD_CTLR]                                          # K's GICD exactly 2.0
    cases = [
        ({"k_ex": two}, "P1", "HELD"),
        ({"k_ex": [x if x[0] != GICD_ISEN else (GICD_ISEN, "w", False, 0.9) for x in two]}, "P1", "PARTIAL"),
        ({"b_ex": B_EX + [(GICD_ICEN, "w", False, 0.2)]}, "P1", "HELD"),                   # B's GICD exactly 0.2
        ({"b_ex": B_EX + [(GICD_ICEN, "w", False, 0.3)]}, "P1", "PARTIAL"),
        ({"k_ex": [x if x[0] != CON_ACK else (CON_ACK, "w", True, 0.9) for x in K_EX]}, "P2", "HELD"),
        ({"k_ex": [x if x[0] != CON_ACK else (CON_ACK, "w", True, 0.85) for x in K_EX]}, "P2", "REFUTED"),
        ({"k_ex": K_EX + [(0x0A003E50, "w", True, 26 / 120.0)]}, "P2", "HELD"),            # share 240/266 > 0.9
        ({"k_ex": K_EX + [(0x0A003E50, "w", True, 27 / 120.0)]}, "P2", "REFUTED"),         # share 240/267 < 0.9
    ]
    for i, (kw, p, want) in enumerate(cases):
        _run(tmp_path / str(i), **kw)
        s = _report(tmp_path / str(i))
        assert _verdicts(s)[p] == want, (kw, s)


def test_failed_checks_void(tmp_path):
    exit6 = line("CPU 0/KVM-11", 9.0, "kvm_userspace_exit: reason KVM_EXIT_MMIO (6)")
    cases = [
        ({"notify": {("K", 3): {"stray": 1}}}, "M1"),
        ({"notify": {("B", 3): {"notifications": 119}}}, "M1"),
        ({"drop": (2, "window")}, "M1"),
        ({"stamp_k": 7}, "M1"),                                                              # a round missing
        ({"extra_lines": {("B", 2): [line("bash-99", 5.0, "print: tracing_mark_write: hi")]}}, "M2"),
        ({"extra_lines": {("K", 4): [exit6] * 3}}, "M2"),                                    # unpaired beyond smp
        ({"k_ex": [x for x in K_EX if x[0] != DB]}, "M3"),                                   # the positive control
        ({"b_ex": [x for x in B_EX if x[0] != DB] + [(DB, "w", True, 1.0)]}, "M3"),
        ({"b_ex": B_EX + [(DB, "w", False, 0.1)]}, "M3"),                                    # 1.1 per exchange
        ({"drop": (2, "bars")}, "M3"),
        ({"counter_skew": (400, 0)}, "M4"),                                                  # KVM counted more
        ({"counter_skew": (-400, 0)}, "M4"),                                                 # the trace saw more
        ({"counter_skew": (30, -30)}, "M4"),                                                 # only the user row off
    ]
    for i, (kw, check) in enumerate(cases):
        _run(tmp_path / str(i), **kw)
        s = _report(tmp_path / str(i))
        assert "-> FAILED" in _line(s, check), (kw, s)
        for p in ("P1", "P2"):
            assert "VOID" in _line(s, p), (kw, s)
    os.remove(tmp_path / "0" / "mmio-K_r1.json")
    s = _report(tmp_path / "0")
    assert "-> FAILED" in _line(s, "M2") and "VOID" in _line(s, "P1")
    f = tmp_path / "1" / "mmio-B_r2.json"                     # fewer lines than the buffer held
    doc = json.loads(f.read_text())
    doc["entries"] += 1
    f.write_text(json.dumps(doc))
    s = _report(tmp_path / "1")
    assert "-> FAILED" in _line(s, "M2") and "entries in the buffer" in s


def test_no_data_still_prints_void_predictions(tmp_path):
    (tmp_path / "o").mkdir()
    s = _report(tmp_path / "o")
    assert "VOID" in _line(s, "P1") and "VOID" in _line(s, "P2"), s


# ---------------------------------------------------------------- the harness

def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    flat = " ".join(ln.lstrip("#").strip() for ln in head.splitlines())
    for s in ("K's GICD accesses >= 2.0 and B's <= 0.2; B's GITS accesses >= 2.0 and K's <= 0.2",
              "InterruptStatus (+0x60) and writes of its InterruptACK (+0x64) each >= 0.9",
              "at least 90% of K's userspace-handled accesses (the median of the per-round shares)",
              "It is not to be amended", "d(1)..d(6), 96.9%, at K = 6", "and is not scored",
              "0.98-1.05 per exchange", "<= 2% + 20", "The background is taken out within the round",
              "Williams order over the three (period 6)", "What this does NOT test", "no latency here is a figure",
              "every prediction rests on all of M1-M4"):
        assert s in flat, s
    known = " ".join(ln for _n, ln in rg.known_sections(text))
    for leak in ("kept B from adding", "trades the console", "the trace held accesses"):
        assert leak not in head, leak
    assert "format trace" not in known, "the format trace is disclosed under THE INSTRUMENTS, not WHAT IS KNOWN"
    assert 'TEVENTS="kvm/kvm_mmio kvm/kvm_userspace_exit"' in body and "mmio_report.py" in body
    assert 'IMG_B="${IMG_B:-${IFS_BIN:-' in body and "trace_restore" in body.split("cleanup() {")[1][:200]
    assert "gzip" not in body and "echo mono > trace_clock" in body and "expanded:" in body
    assert "set_event'" in body and "tracing_cpumask" in body and "window-$1.json" in body
    assert '"\\"kernel\\"' not in body, "m_write_stamp already writes the kernel"
    import mmio_report
    assert mmio_report.CONSOLE_VIRTIO == 0x0A003800 and "0x0a003800" in head


def test_what_is_known_names_records_and_quotes_no_figure():
    text = open(HARNESS, encoding="utf-8").read()
    known = rg.known_sections(text)
    joined = " ".join(line for _n, line in known)
    for rec in ("20260929T-a6-orin-bell", "20260929T-a6-a1metal-bell", "20260929T-a6-orin-paths"):
        assert rec in joined, rec
    assert [f for _n, line in known for f in rg.figures(line)] == []
