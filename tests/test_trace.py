"""The kernel-trace test (Phase 3b / A6, 2026-09-27): guesttrace.py's parser and cutter on synthetic
traceprinter text, trace_report.py's verdicts on synthetic runs, the trace client's reply check,
and the harness's header."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
import guesttrace as gt  # noqa: E402
import tracectl_client as tc  # noqa: E402

REPORT = os.path.join(GC, "trace_report.py")
HARNESS = os.path.join(GC, "run-trace.sh")
BASH = shutil.which("bash")
HZ = 31250000
IOSOCK, W, RX, IDLE = 100, 19, 26, 1
CLIENTS = {"N": (200, "proc/boot/qnx-echo-server-timed"), "L": (300, "proc/boot/qnx-ipcbench")}
N_WANT = 310


def cyc(us):
    return int(round(us * HZ / 1e6))


class Gen:
    """Synthetic traceprinter text: one CPU, cycles from start (low 32 bits printed)."""

    def __init__(self, start=0xFFFFF000, buffers=(1, 2)):
        self.t, self.lines, self.rcvid = start, [], 0x10
        self.ev("CONTROL", "TIME", "msb:0x%08x lsb(offset):0x%08x" % (start >> 32, start & 0xFFFFFFFF))
        for b in buffers:
            self.ev("CONTROL", "BUFFER", "sequence = %d, num_events = 10" % b)

    def ev(self, cls, name, args=""):
        self.lines.append("t:0x%08x CPU:00 %-15s :%-18s %s" % (self.t & 0xFFFFFFFF, cls, name, args))

    def name(self, pid, pname, threads):
        self.lines.append("t:0x%08x CPU:00 PROCESS         :PROCCREATE_NAME   " % (self.t & 0xFFFFFFFF))
        self.lines += ["                      ppid:0", "                       pid:%d" % pid,
                       "                      name:%s" % pname]
        for tid, tname in threads:
            self.lines.append("t:0x%08x CPU:00 PROCESS         :PROCTHREAD_NAME   " % (self.t & 0xFFFFFFFF))
            self.lines += ["                       pid:%d" % pid, "                       tid:%d" % tid,
                           "                      name:%s" % tname]

    def adv(self, us):
        self.t += cyc(us)

    def read(self, client, typ, A, B, R, Cw, Ck, idle_in_b=0.0):
        """One message from client (pid, 1) to io-sock thread W, cut as given (us)."""
        self.rcvid += 1
        rc = "0x%08x" % self.rcvid
        cl = "pid:%d tid:1" % client
        self.ev("KER_CALL", "MSG_SENDV/11", 'coid:0x40000003 msg[0]:"" (0x%08x)' % typ)
        self.ev("COMM", "SND_MESSAGE", "rcvid:%s pid:%d" % (rc, IOSOCK))
        self.ev("THREAD", "THREPLY", cl)
        self.adv(A / 2)
        self.ev("THREAD", "THRUNNING", "pid:%d tid:%d" % (IOSOCK, W))
        self.adv(A / 2)
        self.ev("COMM", "REC_MESSAGE", "rcvid:%s pid:%d" % (rc, IOSOCK))
        self.ev("KER_EXIT", "MSG_RECEIVEV/14", 'rcvid:%s rmsg[0]:"" (0x%08x)' % (rc, typ))
        b_rest = B - idle_in_b
        self.adv(b_rest / 4)
        self.ev("KER_CALL", "SYNC_RWLOCK/77", "")
        self.lines += ["                     syncp:0x0000002c0d1a2af0", "                        op:3"]
        self.adv(b_rest / 4)
        self.ev("KER_EXIT", "SYNC_RWLOCK/77", "ret_val:0 empty:0x00000000")
        if idle_in_b:
            self.ev("THREAD", "THRUNNING", "pid:%d tid:1" % IDLE)
            self.adv(idle_in_b)
            self.ev("THREAD", "THRUNNING", "pid:%d tid:%d" % (IOSOCK, W))
        self.adv(b_rest / 2)
        self.ev("KER_CALL", "MSG_REPLYV/15", "rcvid:%s status:0x00000020" % rc)
        self.ev("COMM", "REPLY_MESSAGE", "tid:1 pid:%d" % client)
        self.ev("THREAD", "THREADY", cl)
        self.adv(R)
        self.ev("KER_EXIT", "MSG_REPLYV/15", "ret_val:0 empty:0x00000000")
        self.adv(Cw)
        self.ev("KER_CALL", "MSG_RECEIVEV/14", "")
        self.lines += ["                      chid:0x00000001", "                    rparts:1"]
        self.ev("THREAD", "THRECEIVE", "pid:%d tid:%d" % (IOSOCK, W))
        self.adv(Ck / 2)
        self.ev("THREAD", "THRUNNING", cl)
        self.adv(Ck / 2)
        self.ev("KER_EXIT", "MSG_SENDV/11", "")
        self.lines += ["                   ret_val:0x0000000000000020"]

    def text(self):
        head = ["started pid 5", "logged rc 0 bytes 4096", "=== tracelogger", "=== tracelogger rc 0",
                "=== traceprinter", "TRACEPRINTER version 1.02", " -- HEADER FILE INFORMATION -- ",
                "  TRACE_CYCLES_PER_SEC:: %d" % HZ, "         TRACE_CPU_NUM:: 1", " -- KERNEL EVENTS -- "]
        tail = ["=== traceprinter rc 0", "=== pidin", "     pid tid name  prio STATE", "=== pidin rc 0", "end"]
        return "\n".join(head + self.lines + tail) + "\n"


BASE = {"A": 2.0, "B": 3.0, "R": 1.0, "Cw": 0.5, "Ck": 1.5}


def window(kind, seg, n=N_WANT, buffers=(1, 2)):
    g = Gen(buffers=buffers)
    pid, pname = CLIENTS[kind]
    g.name(IDLE, "/proc/boot/procnto-smp-instr", [(1, "idle_cpu_0")])
    g.name(IOSOCK, "system/bin/io-sock", [(W, "resmgr worker"), (RX, "vtnet0 rxq 0")])
    g.name(pid, pname, [(1, "main")])
    g.ev("THREAD", "THRUNNING", "pid:%d tid:1" % pid)
    q = dict(A=1.0, B=1.0, R=0.5, Cw=0.2, Ck=1.0)
    for _ in range(n):
        g.adv(300)
        if kind == "N":
            g.read(pid, 0x101, **dict(q, B=1700.0))       # r1: waits for the frame
            g.read(pid, 0x101, **seg)                      # r2
            g.read(pid, 0x102, **q)                        # the echo
        else:
            g.adv(1900)                                    # the 2 ms sleep
            g.read(pid, 0x102, **q)                        # the prime's write
            g.read(pid, 0x101, **q)                        # the prime's read
            g.read(pid, 0x101, **seg)                      # the timed read
    return g.text()


def _run(out, n_seg, l_seg=BASE, pairs=6, broken=None):
    out.mkdir()
    (out / "stamp.json").write_text(json.dumps({"n": 500, "warmup": 100}))
    order = []
    for r in range(1, pairs + 1):
        order.append("pair %d order: %s boot b%d" % (r, "N L" if r % 2 else "L N", (r - 1) // 3 + 1))
        for kind, seg in (("N", n_seg), ("L", l_seg)):
            buf = (1, 3) if broken == (kind, r) else (1, 2)
            (out / ("trace-%s_r%d.txt" % (kind, r))).write_text(window(kind, seg, buffers=buf))
        s = {"p50_ms": 0.18, "n": 500, "bad": 0, "rejected_by_monitor": 0, "frame_bytes": 64}
        (out / ("lat-N_r%d.json" % r)).write_text(json.dumps({"summary": s}))
        (out / ("bench-L_r%d.txt" % r)).write_text(
            "op sock regime tight n 500 p10_ns 1 p50_ns 1 p90_ns 1 mean_ns 1\n"
            "op sock regime spaced n 500 p10_ns 1 p50_ns 1 p90_ns 1 mean_ns 1\ndone\n")
    (out / "order.log").write_text("\n".join(order) + "\n")


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out)], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag + " ")[1].split("\n")[0]


# ---- the parser and the cutter

def test_the_parser_wraps_the_counter_joins_continuations_and_names_threads():
    tr = gt.Trace(gt.sections(window("N", BASE, n=3))["traceprinter"])
    ts = [e[0] for e in tr.events]
    assert ts == sorted(ts) and ts[-1] > 1 << 32
    assert tr.hz == HZ and tr.cpus() == [0] and tr.buffers_contiguous()
    assert tr.pid_of("io-sock") == [IOSOCK] and tr.threads[(IOSOCK, W)] == "resmgr worker"
    ker = [e for e in tr.events if e[2] == "KER_CALL" and e[3].startswith("SYNC_RWLOCK")]
    assert ker and "op:3" in ker[0][4]


def test_the_cutter_returns_each_segment_it_was_given():
    seg = {"A": 2.5, "B": 4.0, "R": 1.2, "Cw": 0.8, "Ck": 1.6}
    tr = gt.Trace(gt.sections(window("N", seg, n=5))["traceprinter"])
    msgs = gt.messages(tr, IOSOCK)
    assert len(msgs) == 15
    picked = gt.pick_second_reads(msgs, 0.001 * HZ)
    assert len(picked) == 5
    s, why = gt.segments(tr, picked[2], IOSOCK)
    assert why == ""
    for k, v in seg.items():
        assert abs(tr.us(s[k]) - v) < 0.1, (k, tr.us(s[k]), v)
    assert s["kc"]["B"]["SYNC_RWLOCK"][0] == 1 and s["kc"]["Cw"] == {}


def test_loopback_reads_are_the_timed_ones_after_a_sleep_write_and_read():
    tr = gt.Trace(gt.sections(window("L", BASE, n=4))["traceprinter"])
    msgs = gt.messages(tr, IOSOCK)
    picked = gt.pick_loopback_reads(msgs, 0.001 * HZ)
    # the first iteration has no message before its write, so it is not counted
    assert len(picked) == 3 and all(abs(tr.us(m["t5"] - m["t0"]) - 8.0) < 0.2 for m in picked)


def test_idle_inside_a_read_is_counted_as_other_threads():
    g = Gen()
    g.name(IDLE, "/proc/boot/procnto-smp-instr", [(1, "idle_cpu_0")])
    g.name(IOSOCK, "system/bin/io-sock", [(W, "resmgr worker")])
    g.ev("THREAD", "THRUNNING", "pid:200 tid:1")
    g.read(200, 0x101, idle_in_b=2.0, **dict(BASE, B=6.0))
    tr = gt.Trace(gt.sections(g.text())["traceprinter"])
    s, _ = gt.segments(tr, gt.messages(tr, IOSOCK)[0], IOSOCK)
    assert abs(tr.us(s["others"]["idle"]) - 2.0) < 0.1 and abs(tr.us(s["B"]) - 6.0) < 0.1


def test_the_client_accepts_only_a_whole_reply():
    good = window("L", BASE, n=1)
    assert tc.ok(good) == (True, "")
    assert not tc.ok(good.replace("=== pidin rc 0", "=== pidin rc 1"))[0]
    assert not tc.ok(good.replace("logged rc 0 bytes 4096", "logged rc 0 bytes 0"))[0]
    assert not tc.ok(good.rstrip("\n").rsplit("\n", 1)[0])[0]
    assert not tc.ok("error usage\n")[0]


# ---- the report on synthetic runs

def test_extra_io_sock_work_holds_both(tmp_path):
    _run(tmp_path / "o", dict(BASE, B=8.0))
    s = _report(tmp_path / "o")
    assert "FAILED" not in s, s
    assert "-> HELD" in _line(s, "P1") and "-> HELD" in _line(s, "P2"), s


def test_an_extra_kernel_pass_refutes_both(tmp_path):
    _run(tmp_path / "o", dict(BASE, R=6.0))
    s = _report(tmp_path / "o")
    assert "-> REFUTED" in _line(s, "P1") and "-> REFUTED" in _line(s, "P2"), s


def test_no_difference_under_tracing_voids(tmp_path):
    _run(tmp_path / "o", BASE)
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P1"), s


def test_a_lost_buffer_fails_m1(tmp_path):
    _run(tmp_path / "o", dict(BASE, B=8.0), broken=("L", 4))
    s = _report(tmp_path / "o")
    assert "-> FAILED" in _line(s, "M1") and "pair 4 L" in s and "VOID (M1 failed)" in _line(s, "P1"), s


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("It is not to be amended", "The owner asked for this run",
              "P1 io-sock's work per read, B + Cw, is >= 3 us longer for the network read.",
              "P2 the kernel's pass per read, A + R + Ck, differs by no more than 1.5 us either way.",
              "M2 the premise survives the tracing", "its durations were not analysed"):
        assert s in head, s
    assert 'PROBE_FRAME_BYTES=64 m_probe "$OUT" "N_r$2" "$GUEST" 7122' in body
    assert 'run "$N" 2000 5' in body
