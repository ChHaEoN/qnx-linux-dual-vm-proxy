"""The doorbell's robustness matrix (Phase 3b / A6, 2026-09-29): run-bellrobust.sh's header,
bellrobust_report.py end to end on synthetic runs, ifs-robust.build as ifs-bell.build plus exactly
the second msixcfg, and ivshmem_ring.py's observer and self-ring refusal. Every value here is
synthetic."""
import difflib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
MON = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor")
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "ci"))
import results_guard as rg  # noqa: E402

REPORT = os.path.join(GC, "bellrobust_report.py")
HARNESS = os.path.join(GC, "run-bellrobust.sh")
BASH = shutil.which("bash")
MSIX0 = "its: msixcfg: ivshmem 00:01.0 BAR1 0x12340000 (4096 B), MSI-X entry 0 -> 0x1 data 0, DeviceID 0x8 EventID 0 -> LPI 8193 (ITT 0x2)\n"
BK = "monitor: safety monitor serving shm-kick on x; slot @4096; peer 1; kick /dev/vcon2 (raw) (frame=64 bytes)\n"
BB = "monitor: safety monitor serving shm-kick on x; slot @8192; peer 1; kick msix (LPI 8193) (frame=64 bytes)\n"
BOOT = {"S1": ("ifs-bell.bin", 1), "S2": ("ifs-bell.bin", 1), "S3": ("ifs-bell.bin", 1), "S4": ("ifs-bell.bin", 1),
        "S5": ("ifs-bell.bin", 1), "S6": ("ifs-robust.bin", 1), "S7": ("ifs-unmask-a.bin", 2),
        "S8": ("ifs-unmask-a.bin", 2)}
RINGS = {"S1": 500, "S2": 2000, "S4": 4000, "S7": 500, "S8": 2000}


class Run:
    def __init__(self, out, repeats=3):
        self.out, self.repeats = out, repeats
        self.rc, self.boots, self.peer = [], [], 100
        out.mkdir(parents=True)

    def ex(self, tag, n, t0=1000, t1=2000, spoil=None, rc=0, peer=None):
        self.peer += 1
        s = {"n": n, "bad": 0, "rejected_by_monitor": 0, "ivshm_peer": self.peer if peer is None else peer,
             "notify": {"exchanges": n, "notifications": n, "wakeups": n, "early_wakeups": 0, "stray": 0, "eagain": 0}}
        if spoil:
            spoil(s)
        (self.out / ("ex-%s.json" % tag)).write_text(json.dumps({"summary": s}))
        self.rc.append("%s rc=%d t0=%d t1=%d" % (tag, rc, t0, t1))

    def ring(self, tag, count, window=(900, 2100), answered=None, rc=0):
        body = "ring: joined as peer 9\nring: window %d %d (time_ns)\n" % window
        if answered is not None:
            body += "ring: observer: %d doorbell(s) came back to this peer from slot 1\n" % answered
        body += "ring: %d rung; read the console\n" % count
        (self.out / ("ring-%s.log" % tag)).write_text(body)
        self.rc.append("ring-%s rc=%d" % (tag, rc))

    def kvm(self, tag, idle=500, rings=3500):
        """kernel MMIO rises over an idle window of 1 s and a ring window of 1.5 s"""
        for kind, r, t0, dt in (("idle", idle, 0, 10 ** 9), ("rings", rings, 2 * 10 ** 9, 15 * 10 ** 8)):
            (self.out / ("kvm-%s-%s.json" % (tag, kind))).write_text(json.dumps(
                {"before": {"t_ns": t0, "counters": {"mmio_exit_kernel": 7}},
                 "after": {"t_ns": t0 + dt, "counters": {"mmio_exit_kernel": 7 + r}}}))

    def boot(self, lab, sc, console=None, up=True):
        img, v = BOOT[sc]
        self.boots.append("%s image=%s vectors=%d qemu_pid=1" % (lab, img, v) if up else "%s FAILED to come up" % lab)
        cons = console if console is not None else (MSIX0 + (MSIX0 if sc == "S6" else "") + BK + BB)
        (self.out / ("console-%s.log" % lab)).write_text(cons)

    def write(self):
        (self.out / "scenarios.log").write_text("\n".join(self.rc) + "\n")
        (self.out / "boots.log").write_text("\n".join(self.boots) + "\n")
        (self.out / "stamp.json").write_text(json.dumps({"repeats": self.repeats}))


def clean_run(out, over=None):
    """A clean synthetic run; over: {(scenario, repeat): fn(run, lab)} replaces that scenario's content."""
    over = over or {}
    run = Run(out)
    for r in range(1, run.repeats + 1):
        for sc in sorted(BOOT):
            lab = "%s_r%d" % (sc, r)
            if (sc, r) in over:
                over[(sc, r)](run, lab)
                continue
            run.boot(lab, sc)
            if sc in ("S1", "S7"):
                run.ex(lab + "-pre", 100)
                run.kvm(lab)
                run.ring(lab, RINGS[sc], answered=0)
                run.ex(lab + "-check", 100)
            elif sc in ("S2", "S8"):
                run.ex(lab + "-pre", 100)
                run.ring(lab, RINGS[sc], window=(900, 2100))
                run.ex(lab, 400, t0=1000, t1=2000)
                run.ex(lab + "-check", 100)
            elif sc == "S3":
                run.ex(lab + "-pre", 100)
                for c in range(1, 21):
                    run.ex("%s-p%d" % (lab, c), 20)
                run.ex(lab + "-check", 100)
            elif sc == "S4":
                run.ring(lab, 4000, window=(100, 9000))
                run.rc.append("%s msixcfg_seen=3000 msix_monitor_seen=4000" % lab)
                run.ex(lab + "-check", 100)
            elif sc == "S5":
                run.ex(lab + "-pre", 100)
                run.ex(lab + "-vlm", 100)
                run.ex(lab + "-check", 100)
            elif sc == "S6":
                run.ex(lab + "-msix", 100)
                run.ex(lab + "-console", 100)
    run.write()
    return run


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _verdicts(s):
    return {"S" + ln.split()[0][1:]: ln.split("-> ")[1] for ln in s.splitlines() if ln.startswith("  P")}


def test_a_clean_run_holds_every_scenario(tmp_path):
    clean_run(tmp_path / "o")
    v = _verdicts(_report(tmp_path / "o"))
    assert len(v) == 8 and set(v.values()) == {"HELD"}, v


def test_the_observer_catches_an_answered_spurious_ring(tmp_path):
    def s1_answered(run, lab):
        run.boot(lab, "S1")
        run.ex(lab + "-pre", 100)
        run.kvm(lab)
        run.ring(lab, 500, answered=3)
        run.ex(lab + "-check", 100)
    clean_run(tmp_path / "o", {("S1", r): s1_answered for r in (1, 2, 3)})
    assert _verdicts(_report(tmp_path / "o"))["S1"] == "REFUTED"


def test_rings_not_shown_delivered_void_not_pass(tmp_path):
    def undelivered(run, lab):
        run.boot(lab, "S7")
        run.ex(lab + "-pre", 100)
        run.kvm(lab, idle=500, rings=900)            # 150 over the idle rate for 500 rings: under 2 per ring
        run.ring(lab, 500, answered=0)
        run.ex(lab + "-check", 100)
    clean_run(tmp_path / "o", {("S7", 2): undelivered})
    s = _report(tmp_path / "o")
    assert "S7 r2 VOID (M3" in s and _verdicts(s)["S7"].startswith("HELD (2 of 3"), s


def test_an_already_broken_doorbell_voids_the_next_scenario(tmp_path):
    def broken_pre(run, lab):
        run.boot(lab, "S2")
        run.ex(lab + "-pre", 100, spoil=lambda s: s["notify"].update(stray=1))
        run.ring(lab, 2000)
        run.ex(lab, 400, spoil=lambda s: s.update(bad=5))
        run.ex(lab + "-check", 100)
    clean_run(tmp_path / "o", {("S2", r): broken_pre for r in (1, 2, 3)})
    assert _verdicts(_report(tmp_path / "o"))["S2"].startswith("VOID")


def test_failures_count_and_boot_failures_void(tmp_path):
    def failed_boot(run, lab):
        run.boot(lab, "S3", up=False)
    def lost_doubled(run, lab):
        run.boot(lab, "S8")
        run.ex(lab + "-pre", 100)
        run.ring(lab, 2000)
        run.ex(lab, 400, rc=1)
        run.ex(lab + "-check", 100)
    def short_overlap(run, lab):
        run.boot(lab, "S2")
        run.ex(lab + "-pre", 100)
        run.ring(lab, 2000, window=(1900, 2100))
        run.ex(lab, 400, t0=1000, t1=2000)
        run.ex(lab + "-check", 100)
    def s4_no_monitor(run, lab):
        run.boot(lab, "S4", console=MSIX0 + BK)
        run.ring(lab, 4000, window=(100, 9000))
        run.rc.append("%s msixcfg_seen=3000 msix_monitor_seen=never" % lab)
        run.ex(lab + "-check", 100)
    def s4_missed(run, lab):
        run.boot(lab, "S4")
        run.ring(lab, 4000, window=(3500, 9000))
        run.rc.append("%s msixcfg_seen=3000 msix_monitor_seen=4000" % lab)
        run.ex(lab + "-check", 100)
    def s6_once(run, lab):
        run.boot(lab, "S6", console=MSIX0 + BK + BB)
        run.ex(lab + "-msix", 100)
        run.ex(lab + "-console", 100)
    def s5_rejected(run, lab):
        run.boot(lab, "S5")
        run.ex(lab + "-pre", 100)
        run.ex(lab + "-vlm", 100, spoil=lambda s: s.update(rejected_by_monitor=2))
        run.ex(lab + "-check", 100)
    clean_run(tmp_path / "o", {("S3", 1): failed_boot, ("S8", 2): lost_doubled, ("S2", 3): short_overlap,
                                 ("S4", 1): s4_no_monitor, ("S4", 2): s4_missed, ("S6", 1): s6_once,
                                 ("S6", 2): s6_once, ("S6", 3): s6_once, ("S5", 2): s5_rejected})
    s = _report(tmp_path / "o")
    v = _verdicts(s)
    assert v["S3"] == "HELD (2 of 3 repeats ran)" and v["S8"] == "PARTIAL" and v["S2"] == "HELD (2 of 3 repeats ran)", s
    assert "S4 r1 VOID (M6" in s and "S4 r2 VOID (M6" in s and v["S4"] == "HELD (1 of 3 repeats ran)", s
    assert v["S6"] == "VOID (in every repeat)" and "(M8" in s and v["S5"] == "PARTIAL", s
    assert v["S1"] == "HELD" and v["S7"] == "HELD", s


def test_the_idle_window_the_closing_check_the_image_and_the_ring_rc_each_count(tmp_path):
    def busy_idle(run, lab):
        run.boot(lab, "S1")
        run.ex(lab + "-pre", 100)
        run.kvm(lab, idle=3000, rings=3500)          # the rings alone clear 2 per ring; over idle they do not
        run.ring(lab, 500, answered=0)
        run.ex(lab + "-check", 100)
    def lost_after(run, lab):
        run.boot(lab, "S5")
        run.ex(lab + "-pre", 100)
        run.ex(lab + "-vlm", 100)
        run.ex(lab + "-check", 100, rc=1)
    def wrong_image(run, lab):
        run.boot(lab, "S3")
        run.boots[-1] = "%s image=ifs-bell.bin vectors=2 qemu_pid=1" % lab
        run.ex(lab + "-pre", 100)
        for c in range(1, 21):
            run.ex("%s-p%d" % (lab, c), 20)
        run.ex(lab + "-check", 100)
    def ring_failed(run, lab):
        run.boot(lab, "S7")
        run.ex(lab + "-pre", 100)
        run.kvm(lab)
        run.ring(lab, 500, answered=0, rc=1)
        run.ex(lab + "-check", 100)
    def idle_rate(run, lab):
        run.boot(lab, "S7")
        run.ex(lab + "-pre", 100)
        run.kvm(lab, idle=600, rings=1800)           # over the idle count, not over its rate for 1.5 s
        run.ring(lab, 500, answered=0)
        run.ex(lab + "-check", 100)
    clean_run(tmp_path / "o", {("S1", 1): busy_idle, ("S5", 3): lost_after, ("S3", 2): wrong_image,
                                 ("S7", 1): ring_failed, ("S7", 3): idle_rate})
    s = _report(tmp_path / "o")
    v = _verdicts(s)
    assert "S1 r1 VOID (M3" in s and v["S1"].startswith("HELD (2 of 3"), s
    assert "S5 r3 FAIL (the closing check)" in s and v["S5"] == "PARTIAL", s
    assert "S3 r2 VOID (M1" in s and v["S3"].startswith("HELD (2 of 3"), s
    assert "S7 r1 FAIL (ring set)" in s and "S7 r3 VOID (M3" in s and v["S7"] == "PARTIAL (2 of 3 repeats ran)", s


def test_a_set_that_never_ran_voids_a_pass_but_not_a_failure(tmp_path):
    def stopped_before_check(run, lab):
        run.boot(lab, "S1")
        run.ex(lab + "-pre", 100)
        run.kvm(lab)
        run.ring(lab, 500, answered=0)
    def rings_never_started(run, lab):
        run.boot(lab, "S4")
        run.rc.append("%s no 'peer 1 connected' in the server's log within 60 s" % lab)
        run.ex(lab + "-check", 100)
    def failed_then_stopped(run, lab):
        run.boot(lab, "S2")
        run.ex(lab + "-pre", 100)
        run.ring(lab, 2000)
        run.ex(lab, 400, spoil=lambda s: s.update(bad=5))
    def console_way_failed(run, lab):
        run.boot(lab, "S6")
        run.ex(lab + "-msix", 100)
        run.ex(lab + "-console", 100, rc=1)
    def no_opening_check(run, lab):
        run.boot(lab, "S5")
        run.ex(lab + "-vlm", 100)
        run.ex(lab + "-check", 100)
    def same_peer(run, lab):
        run.boot(lab, "S3")
        run.ex(lab + "-pre", 100)
        for c in range(1, 21):
            run.ex("%s-p%d" % (lab, c), 20, peer=7)
        run.ex(lab + "-check", 100)
    def probe_lost(run, lab):
        run.boot(lab, "S3")
        run.ex(lab + "-pre", 100)
        for c in range(1, 21):
            run.ex("%s-p%d" % (lab, c), 20, rc=3 if c == 7 else 0)
        run.ex(lab + "-check", 100)
    clean_run(tmp_path / "o", {("S1", 2): stopped_before_check, ("S4", 3): rings_never_started,
                                 ("S2", 1): failed_then_stopped, ("S6", 2): console_way_failed,
                                 ("S5", 1): no_opening_check, ("S3", 3): same_peer, ("S3", 1): probe_lost})
    s = _report(tmp_path / "o")
    v = _verdicts(s)
    assert "S1 r2 VOID (M7 (the closing check never ran)" in s and v["S1"] == "HELD (2 of 3 repeats ran)", s
    assert "S4 r3 VOID (M7 (ring set never ran)" in s and v["S4"] == "HELD (2 of 3 repeats ran)", s
    assert "S2 r1 FAIL (the doubled exchanges)" in s and v["S2"] == "PARTIAL", s
    assert "S6 r2 FAIL (the console exchanges)" in s and v["S6"] == "PARTIAL", s
    assert "S5 r1 VOID (M2 (the opening check never ran)" in s and v["S5"] == "HELD (2 of 3 repeats ran)", s
    assert "S3 r3 VOID (M4" in s and "S3 r1 FAIL (probe 7)" in s and v["S3"] == "PARTIAL (2 of 3 repeats ran)", s


def test_a_wedge_that_also_stops_the_evidence_is_a_failure_not_void(tmp_path):
    def wedged_at_first_ring(run, lab):
        run.boot(lab, "S7")
        run.ex(lab + "-pre", 100)
        run.kvm(lab, idle=500, rings=520)            # the first ring wedged: no rise from the rest
        run.ring(lab, 500, answered=0)
        run.ex(lab + "-check", 100, rc=1)
    def wedged_and_outlasted(run, lab):
        run.boot(lab, "S8")
        run.ex(lab + "-pre", 100)
        run.ring(lab, 2000, window=(900, 2100))
        run.ex(lab, 400, t0=1000, t1=9000, spoil=lambda s: s.update(bad=300))   # timed out past the rings
        run.ex(lab + "-check", 100, rc=1)
    def s4_missed_and_broken(run, lab):
        run.boot(lab, "S4")
        run.ring(lab, 4000, window=(3500, 9000))
        run.rc.append("%s msixcfg_seen=3000 msix_monitor_seen=4000" % lab)
        run.ex(lab + "-check", 100, rc=1)
    clean_run(tmp_path / "o", {("S7", r): wedged_at_first_ring for r in (1, 2, 3)}
              | {("S8", r): wedged_and_outlasted for r in (1, 2, 3)}
              | {("S4", r): s4_missed_and_broken for r in (1, 2, 3)})
    s = _report(tmp_path / "o")
    v = _verdicts(s)
    assert v["S7"] == "REFUTED" and v["S8"] == "REFUTED" and v["S4"] == "REFUTED", s
    assert "S7 r1 FAIL (the closing check)" in s and "M3" not in s.split("S7 r1 ")[1].splitlines()[0], s


def test_console_errors_are_listed_without_its_probes_information(tmp_path):
    info = ("its: GITS 0x8080000, lock 0x1\nits: CTLR 0x0 IIDR 0x1 TYPER 0x1 (Devbits 8)\n"
            "its: BASER0 0x1 (type 1)\nits: CBASER 0x1 -> queue\nits: CWRITER 0x0 CREADR 0x0, lock word 0\n")
    def noisy(run, lab):
        run.boot(lab, "S5", console=info + MSIX0 + "its: msixcfg maps 1..2 vectors, not 3\n" + BK + BB)
        run.ex(lab + "-pre", 100)
        run.ex(lab + "-vlm", 100)
        run.ex(lab + "-check", 100)
    clean_run(tmp_path / "o", {("S5", 1): noisy})
    s = _report(tmp_path / "o")
    assert "(unscored): 1\n" in s and "msixcfg maps" in s, s
    assert _verdicts(s)["S5"] == "HELD", s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    flat = " ".join(ln.lstrip("#").strip() for ln in head.splitlines())
    for s in ("each scenario S1..S8 passes in every repeat that is not VOID: HELD", "It is not to be amended",
              "A functional test: nothing here is timed", "in S1 and S7, the observer counted 0 doorbells",
              "the idle window's rate, taken over the rings' own duration, by at least 2 per ring",
              "the startup library's LPI mask and unmask callouts each issue ITS commands",
              "otherwise the doorbell was already broken", "No banner is scored",
              "So rings before msixcfg can leave at most one interrupt at set-up", "What this does NOT test",
              "a ring lost and then covered by the next spurious ring",
              "a failure stands whether or not they held", "the probe starting 0.5 s into them"):
        assert s in flat, s
    boot = body.split("boot_vm() {")[1].split("\nend_boot()")[0]
    assert boot.index("grep -q 'peer 1 connected'") < boot.index('rings "$4" 4000 5 0 &'), "rings after QEMU joined"
    assert "trap cleanup EXIT" in body and "report\n" in body.split("cleanup() {")[1].split("\n}\n")[0] + "\n"


def test_what_is_known_is_record_names_only():
    text = open(HARNESS, encoding="utf-8").read()
    known = " ".join(ln for _n, ln in rg.known_sections(text))
    rest = " ".join(known.replace("#", " ").split())
    for rec in ("20260929T-a6-orin-its", "20260929T-a6-orin-bell", "20260929T-a6-orin-mmio",
                "20260929T-a6-orin-unmask"):
        assert rec in rest, rec
        rest = rest.replace(rec, "")
    for fixed in ("WHAT IS KNOWN.", "(held locally)", ",", "."):
        rest = rest.replace(fixed, "")
    assert rest.split() == [], rest


def test_ifs_robust_is_ifs_bell_plus_the_second_msixcfg():
    def lines(name):
        with open(os.path.join(MON, name), encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    bell, rob = lines("ifs-bell.build"), lines("ifs-robust.build")
    root = "E:/Project/qnx-linux-dual-vm-proxy/ipc-test/qnx-safety-monitor/"
    ops = [(t, bell[i1:i2], rob[j1:j2]) for t, i1, i2, j1, j2
           in difflib.SequenceMatcher(None, bell, rob, autojunk=False).get_opcodes() if t != "equal"]
    assert ops == [("insert", [], ["/proc/boot/qnx-its-probe msixcfg"]),
                   ("replace", ["[perms=0444] build/ifs.build=%sifs-bell.build" % root],
                    ["[perms=0444] build/ifs.build=%sifs-robust.build" % root]),
                   ("replace", ["[perms=0444] build.date = output/build/ifs-bell.build.date"],
                    ["[perms=0444] build.date = output/build/ifs-robust.build.date"])], ops


def test_the_ring_tool_observes_without_touching_the_request_and_refuses_to_ring_itself():
    src = open(os.path.join(GC, "ivshmem_ring.py"), encoding="utf-8").read()
    assert "if own == guest_peer:" in src and "refusing to ring" in src
    assert "OFF_REPLY_VIA, OFF_CLIENT_PEER, VIA_DOORBELL = 72, 76, 1" in src
    hdr = open(os.path.join(HERE, "..", "ipc-test", "common", "shm_chan.h"), encoding="utf-8").read()
    for name, v in (("SHM_CHAN_OFF_REPLY_VIA", "72u"), ("SHM_CHAN_OFF_CLIENT_PEER", "76u"), ("SHM_VIA_DOORBELL", "1u")):
        assert "#define %s" % name in hdr and v in hdr.split("#define %s" % name)[1].split("\n")[0], name
    body = src.split("def main():")[1]
    assert "OFF_REQ" not in body and "req_seq" not in body.lower().replace("never touches req_seq", "")
    assert "struct.pack_into(\"<II\", shm, a.slot + OFF_REPLY_VIA, *saved)" in body, "the slot is put back"
    assert body.index("time.sleep(OBSERVER_SETTLE_S)") < body.index("for i in range(a.count):"), "QEMU learns the peer first"
    assert "OBSERVER_SETTLE_S = 0.5" in src
