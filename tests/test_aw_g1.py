"""Gate G1's harness and judge (SDV Phase 8 WP8 Step B; sdv/aw/prereg-g1g2.md, PR):
run-aw-g1.sh, aw_g1.py, the stamp's PLATFORM_POLICY=g1 and clock sampler (lib-measure.sh), the host's watchdog and 5 s sampler
(sdv/aw/g1_watchdog.py, g1_sampler.py) and the two rclpy recorders (sdv/aw/aw_g1_diag.py, aw_g1_count.py). No git runs here.

THE JUDGE'S RECORD (class Rec). A good main arm built from stand-in series on design values alone: four drives of 300 s of
Control at a 30 ms spacing, the 1 s series, the recorder's lines, the harness's own reads. Each case changes one thing. The parts
cut from the PC spike's real files (the form of scenario.jsonl, replies.jsonl and diag.jsonl) are the constants below, every
number in them rewritten: no test depends on any figure of any run.

THE HARNESS'S RIG (class Rig). The harness as the Orin's helper or remote-ladder.sh's detached runner runs it, against stubs first
on PATH (a Python docker that keeps containers as files, sudo, pgrep, pkill, ip, sysctl, taskset, sync, sleep, id), a fake /proc
and /sys (PROC_ROOT, SYS_ROOT), the real lib-measure.sh, lib-vss-deadline.sh, aw_setup.py, aw_suite.py and vss_setup.py, and
stand-ins for the launch script, latency_probe.py, ctlsynth.py and vss-repin.sh. The clock the harness reads is a file
(QNX_CLOCK_FILE) the docker stub moves on, so 1200 s pass in a few drives; the rig's stand-in watchdog follows that clock. The real
watchdog runs in its own cases and in one harness case, on the real clock. The driver is resident (PR's dated section, item 15): the docker
stub's `run` of aw-scenario leaves a detached process behind, which takes each word from the go file the harness writes, does that drive on
the rig's clock and answers in the drive's directory, as long as its container's file says it runs; `docker wait` blocks as docker's does.
The stub models inspect, wait and stop errors for a container that is gone.
The harness's look at a drive's exit file waits in a builtin, on the real clock, where no stub reaches it, so the rig's copy of the harness
says EXIT_POLL_S=0.01 in place of its design value and nothing else in it differs; one case runs the design value.

No container starts, no ROS runs, no AWS, no SSH, no board, no docker or QEMU of this machine.

Does not demonstrate: anything about the Orin, the image, ROS, DDS or a real guest; that the design values leave Autoware enough;
that the recorders see what the stand-ins here feed them on a real run. The startup that boots the guest under KVM is ours, not a
QNX-supported configuration, and no timing claim attaches to the boot.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
G = os.path.join(REPO, "orin-native", "gpu-concurrency")
AW = os.path.join(REPO, "sdv", "aw")
CTL = os.path.join(REPO, "sdv", "ctl")
HARNESS = os.path.join(G, "run-aw-g1.sh")
TOOL = os.path.join(G, "aw_g1.py")
LIB = os.path.join(G, "lib-measure.sh")
WATCHDOG = os.path.join(AW, "g1_watchdog.py")
SAMPLER = os.path.join(AW, "g1_sampler.py")
DIAG = os.path.join(AW, "aw_g1_diag.py")
COUNT = os.path.join(AW, "aw_g1_count.py")
PREREG = os.path.join(AW, "prereg-g1g2.md")
BASH = shutil.which("bash")
linux_only = pytest.mark.skipif(BASH is None or sys.platform == "win32",
                                reason="the harness, the library and their stubs need bash and coreutils")

S = 10 ** 9
DIGEST = "0x12345678"
REF_RE = re.compile(r"^ghcr\.io/.+@sha256:[0-9a-f]{64}$")
VALIDATOR = "control_validator: control_validation_latency"
T5_LIST = ("topic_state_monitor_control_command_control_cmd: control_topic_status",
           "topic_state_monitor_trajectory_follower_control_cmd: control_topic_status",
           "controller_node_exe: incoming_message_timeout")
RULES_LINE = ("monitor: ctl rules: kind 2, catalog %s (vss 6.0), dt_max 200 ms, overspeed margin 2 m/s, rollback margin 1 m/s, "
              "profiles 1 2")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def g1():
    return _load(TOOL, "aw_g1")


def _frame_hex(seq, t_ns):
    return (seq.to_bytes(8, "little") + t_ns.to_bytes(8, "little") + bytes(48)).hex()


# --- the judge's record -------------------------------------------------------------------------------------------------------

class Rec:
    """A good main arm, in memory until write(): each field is what the file of that name will hold."""

    def __init__(self, d, arm="main", drives=4):
        self.d = str(d)
        self.arm_name = arm
        self.t0 = 1000 * S
        self.drives = []
        b = self.t0
        for _ in range(drives):
            self.drives.append(self.drive(b))
            b += 303 * S
        self.frames = []
        for dr in self.drives:
            self.frames += self.frames_of(dr)
        self.first_container = self.t0 - 120 * S
        self.loop_end = (self.drives[-1]["end"] if self.drives else self.t0) + 1 * S
        self.last_stop = self.loop_end + 40 * S
        self.series = [(t, 3000000) for t in range(self.first_container - 30 * S, self.last_stop + 3 * S, S)]
        self.events = []        # the watchdog's event lines, beside its readings
        self.stop_file = None
        self.diag = self.diag_lines() if self.drives else None
        self.arm = {"plan": arm, "arm": arm, "stamp_exit": "0", "stamp_mono_ns": str(self.first_container - 200 * S),
                    "first_container_mono_ns": str(self.first_container), "loop_end": "reached",
                    "loop_end_mono_ns": str(self.loop_end), "last_stop_mono_ns": str(self.last_stop),
                    "harness_end": "status=DONE", "ctl_digest": DIGEST, "console_arm_from": "0",
                    "arm_pair_start": "%d %d" % (self.first_container, 1800000000 * S),
                    "arm_pair_end": "%d %d" % (self.last_stop, 1800000000 * S + self.last_stop - self.first_container)}
        self.stamp = {"platform": {"policy": "g1"}, "n": 0, "k": 0, "warmup": 0, "interval_ms": 0}
        self.placement = [("aw-sim", "3,5", "3,5", "running"), ("aw-claim-node", "3,5", "3,5", "running"),
                          ("aw-g1-diag", "3,5", "3,5", "running")]
        if arm != "main":
            self.placement[1] = ("aw-g1-count", "3,5", "3,5", "running")
        if drives:                  # PR's dated section, item 15: the driver's one start
            self.placement.append(("aw-scenario", "3,5", "3,5", "running"))
        self.vmstat_before, self.vmstat_end = 7, 7
        self.mem_events = [("aw-sim", 0), ("aw-claim-node" if arm == "main" else "aw-g1-count", 0), ("aw-g1-diag", 0)]
        self.pairs = {"host": (500 * S, 1800000000 * S), "container": (501 * S, 1800000001 * S)}
        self.hc_before = ("format=1\nlo.flags=LOOPBACK,UP,LOWER_UP\nnet.core.rmem_max=212992\nnet.ipv4.ipfrag_time=30\n"
                          "net.ipv4.ipfrag_high_thresh=4194304\n")
        self.hc_after = self.hc_before
        self.console = ("monitor: boot\n" + RULES_LINE % DIGEST + "\n") if arm == "main" else None
        self.summary = {"counters": {"controls": len(self.frames), "packed": len(self.frames), "replied": len(self.frames),
                                     "drop": 0, "lost_on_reconnect": 0, "reconnects": 0},
                        "identity": {"controls": len(self.frames), "packed": len(self.frames), "replied": len(self.frames),
                                     "drop": 0, "lost_on_reconnect": 0, "holds": True}, "demo": None, "fatal": None}
        self.sampler = [{"mono_ns": self.first_container, "wall_ns": 1, "what": "meminfo", "MemAvailable": 1}]

    @staticmethod
    def drive(b):
        lines = [{"step": "map", "outcome": "done", "mono_ns": b},
                 {"step": "localize", "outcome": "done", "state": 3, "mono_ns": b + S // 5},
                 {"step": "route", "outcome": "done", "state": 2, "mono_ns": b + S // 2},
                 {"step": "engage", "outcome": "done", "state": 2, "mono_ns": b + 2 * S},
                 {"step": "arrive", "outcome": "done", "state": 3, "mono_ns": b + 300 * S},
                 {"step": "clear", "outcome": "done", "state": None, "mono_ns": b + 300 * S + S // 100}]
        return {"begin": b, "end": b + 301 * S, "rc": 0, "lines": lines}

    @staticmethod
    def frames_of(dr, spacing=30 * 10 ** 6):
        route = next(x for x in dr["lines"] if x["step"] == "route")["mono_ns"]
        last = dr["lines"][-1]["mono_ns"]
        return [{"t": t, "outcome": "replied", "verdict": 0, "reason": 0} for t in range(route + S, last, spacing)]

    def diag_lines(self):
        out = []
        start = self.drives[0]["begin"] - 30 * S
        first_ok = self.drives[0]["lines"][3]["mono_ns"]
        for n in T5_LIST:
            out.append((start, {"mono_ns": start, "first": True, "name": n, "hardware_id": "x", "level": 2, "message": "Error"}))
            out.append((first_ok, {"mono_ns": first_ok, "first": False, "name": n, "hardware_id": "x", "level": 0, "message": "OK"}))
        out.append((start, {"mono_ns": start, "first": True, "name": VALIDATOR, "hardware_id": "control_validator", "level": 0,
                            "message": "OK"}))
        out.append((start, {"mono_ns": start, "first": True, "name": "vehicle_cmd_gate: heartbeat", "hardware_id": "g", "level": 0,
                            "message": "OK"}))
        end = self.drives[-1]["lines"][-1]["mono_ns"] + 2 * S
        for t in range(start, end + S, 5 * S):
            names = {n: t for n in T5_LIST}
            names[VALIDATOR] = t
            names["vehicle_cmd_gate: heartbeat"] = t
            out.append((t, {"mono_ns": t, "last_seen": names,
                            "values": {T5_LIST[0]: {"status": "OK", "timeout": "1.00 [s]", "measured_rate": "30.00 [Hz]"}}}))
        out.sort(key=lambda p: p[0])
        return [x for _t, x in out]

    def p(self, *names):
        return os.path.join(self.d, *names)

    def put(self, name, text):
        p = self.p(*name.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def write(self):
        os.makedirs(self.d, exist_ok=True)
        if self.arm is not None:
            self.put("arm.tsv", "".join("%s\t%s\n" % kv for kv in self.arm.items()))
        if self.stamp is not None:
            self.put("stamp.json", json.dumps(self.stamp))
        if self.series is not None or self.events:
            rows = ["R %d %d %s\n" % (t, 1800000000 * S + t, kb) for t, kb in (self.series or [])]
            self.put("watchdog.log", "".join(rows + ["E %d %d %s\n" % e for e in self.events]))
        if self.stop_file is not None:
            self.put("watchdog.stop", self.stop_file)
        self.put("placement.tsv", "".join("\t".join(r) + "\n" for r in self.placement))
        rows = []
        for k, dr in enumerate(self.drives, start=1):
            rows.append("begin\t%d\t%d\n" % (k, dr["begin"]))
            if dr.get("rc") is not None:
                rows.append("end\t%d\t%d\t%d\n" % (k, dr["rc"], dr["end"]))
            if dr.get("stopped"):
                rows.append("stopped\t%d\t%s\n" % (k, dr["stopped"]))
            if dr.get("lines") is not None:
                self.put("drives/d%03d/scenario.jsonl" % k, "".join(json.dumps(x) + "\n" for x in dr["lines"]))
        self.put("drives.tsv", "".join(rows))
        if self.vmstat_before is not None:
            self.put("vmstat-before.txt", "pgfault 1\noom_kill %d\n" % self.vmstat_before)
        if self.vmstat_end is not None:
            self.put("vmstat-end.txt", "pgfault 2\noom_kill %d\n" % self.vmstat_end)
        if self.mem_events is not None:
            self.put("memory-events-end.tsv", "".join("%s\t%s\n" % x for x in self.mem_events))
        if self.pairs is not None:
            self.put("clock-pairs.txt", "".join("%s %d %d\n" % (k, v[0], v[1]) for k, v in self.pairs.items()))
        if self.hc_before is not None:
            self.put("hc-before.txt", self.hc_before)
        if self.hc_after is not None:
            self.put("hc-after.txt", self.hc_after)
        if self.console is not None:
            self.put("guest-console.log", self.console)
        if self.diag is not None:
            self.put("diag/diag.jsonl", "".join(json.dumps(x) + "\n" for x in self.diag))
        if self.sampler is not None:
            self.put("sampler.jsonl", "".join(json.dumps(x) + "\n" for x in self.sampler))
        if self.arm_name == "main":
            self.write_replies()
        else:
            self.put("count/arrivals.jsonl", "".join(json.dumps({"seq": i + 1, "mono_ns": f["t"]}) + "\n"
                                                     for i, f in enumerate(self.frames)))
        return self

    def write_replies(self):
        if self.frames is None:
            return
        rows = ['{"header": {"format": 1, "kind": 2, "mode": "node"}}\n']
        for i, f in enumerate(self.frames, start=1):
            seq = f.get("seq", i)
            rows.append(json.dumps({"seq": seq, "frame": _frame_hex(seq, f["t"]), "outcome": f["outcome"], "verdict": f["verdict"],
                                    "reason": f["reason"], "mono_ns": f["t"] + 10 ** 6}) + "\n")
        if self.summary is not None:
            rows.append(json.dumps({"summary": self.summary}) + "\n")
        self.put("claim/run/replies.jsonl", "".join(rows))


GATE = ("T1", "T2", "T3", "T4", "T4w", "T5", "T6", "T7")
INSTRUMENTS = ("series", "stamp", "placement", "reply-log", "rules-digest", "positive-control", "settings", "one-clock")


def _judge(g1, rec, **kw):
    if isinstance(rec, Rec):
        rec.write()
        rec = rec.d
    return g1.judge_record(rec, **kw)


def _line(j, word):
    for ln in j.lines:
        if ln.startswith(word + " "):
            return ln
    raise AssertionError("no line for %s in %s" % (word, j.lines))


def _inst(j, name):
    return _line(j, "instrument " + name)


def _failed(j):
    return [w for w in GATE if _line(j, w).startswith(w + " FAIL")]


def _missing(j):
    return [n for n in INSTRUMENTS if " MISSING" in _inst(j, n)]


def test_a_good_record_passes_with_one_line_per_item_and_instrument_then_one_verdict(g1, tmp_path):
    j = _judge(g1, Rec(tmp_path / "r"))
    assert j.verdict == "PASS", j.lines
    for w in GATE:
        assert _line(j, w).startswith(w + " PASS"), j.lines
    for n in INSTRUMENTS:
        assert _inst(j, n).startswith("instrument %s OK" % n), j.lines
    verdicts = [x for x in j.lines if x.startswith("verdict:")]
    assert verdicts == ["verdict: PASS"]


def _t1_vmstat(r):
    r.vmstat_end = r.vmstat_before + 1


def _t1_events(r):
    r.mem_events[0] = ("aw-sim", 1)


def _t2_stop(r):
    r.events = [(r.t0 + 50 * S, 1800000050 * S, "stop floor_kb=716800 avail_kb=700000")]


def _t2_stop_file(r):
    r.stop_file = "stop\n"


def _t3(r):
    r.series[100] = (r.series[100][0], 1048575)


def _t4(r):
    # every other frame of two in three kept: a rate under 30 per second with no window under 150
    r.frames = [f for i, f in enumerate(r.frames) if i % 3 != 0]
    r.summary["identity"]["replied"] = r.summary["counters"]["replied"] = len(r.frames)
    r.summary["identity"]["controls"] = r.summary["counters"]["controls"] = len(r.frames)
    r.summary["identity"]["packed"] = r.summary["counters"]["packed"] = len(r.frames)


def _t4w(r):
    # a stall of 12 s covering one whole window of the first drive; the rate over 300 s stays over 30
    first = r.frames[0]["t"]
    r.frames = [f for f in r.frames if not first + 19 * S <= f["t"] < first + 31 * S]
    r.summary["counters"]["replied"] = len(r.frames)


def _t5_error(r):
    t = r.drives[1]["begin"]
    r.diag.append({"mono_ns": t, "first": False, "name": T5_LIST[2], "hardware_id": "x", "level": 2, "message": "timeout"})


def _t5_never_ok(r):
    r.diag = [x for x in r.diag if not (x.get("name") == T5_LIST[1] and x.get("level") == 0)]


def _t5_silent(r):
    limit = r.drives[1]["begin"]
    for x in r.diag:
        if "last_seen" in x and x["mono_ns"] > limit:
            x["last_seen"][VALIDATOR] = limit


def _t6_drop(r):
    r.summary["counters"]["drop"] = 1
    r.summary["identity"]["drop"] = 1


def _t6_lost(r):
    r.summary["counters"]["lost_on_reconnect"] = 1


def _t6_identity(r):
    r.summary["identity"]["holds"] = False


def _t6_no_summary(r):
    r.summary = None


def _t7_rc(r):
    r.drives[1]["rc"] = 3


def _t7_no_goal(r):
    r.drives[1]["lines"][4]["outcome"] = "timeout"
    r.drives[1]["lines"].pop()


def _t7_not_cleared(r):
    r.drives[1]["lines"][5]["outcome"] = "timeout"


def _t7_short(r):
    r.drives.pop()
    r.frames = [f for f in r.frames if f["t"] <= r.drives[-1]["lines"][-1]["mono_ns"]]
    r.summary["counters"]["replied"] = len(r.frames)
    r.loop_end = r.drives[-1]["end"] + S
    r.arm["loop_end"] = "sim-died"
    r.arm["loop_end_mono_ns"] = str(r.loop_end)


def _t7_reached_word_but_short(r):
    _t7_short(r)
    r.arm["loop_end"] = "reached"


@pytest.mark.parametrize("change, item", [
    (_t1_vmstat, "T1"), (_t1_events, "T1"), (_t2_stop, "T2"), (_t2_stop_file, "T2"), (_t3, "T3"), (_t4, "T4"), (_t4w, "T4w"),
    (_t5_error, "T5"), (_t5_never_ok, "T5"), (_t5_silent, "T5"), (_t6_drop, "T6"), (_t6_lost, "T6"), (_t6_identity, "T6"),
    (_t6_no_summary, "T6"), (_t7_rc, "T7"), (_t7_no_goal, "T7"), (_t7_not_cleared, "T7"), (_t7_short, "T7"),
    (_t7_reached_word_but_short, "T7"),
], ids=lambda x: x if isinstance(x, str) else x.__name__.lstrip("_"))
def test_each_item_failing_alone_is_a_fail_naming_it(g1, tmp_path, change, item):
    r = Rec(tmp_path / "r")
    change(r)
    j = _judge(g1, r)
    assert j.verdict == "FAIL", j.lines
    assert _failed(j) == [item], j.lines
    assert not _missing(j), j.lines
    assert any(item in x for x in j.reasons), j.reasons
    assert item in _line(j, "verdict:"), j.lines


def _no_series(r):
    r.series = None


def _series_gap(r):
    t = r.drives[1]["begin"]
    r.series = [x for x in r.series if not t < x[0] < t + 7 * S]


def _series_short(r):
    r.series = [x for x in r.series if x[0] < r.loop_end - 7 * S]


def _series_late(r):
    r.series = [x for x in r.series if x[0] > r.first_container + 7 * S]


def _no_stamp(r):
    r.stamp = None


def _stamp_policy(r):
    r.stamp["platform"]["policy"] = "record"


def _stamp_refused(r):
    r.arm["stamp_exit"] = "1"


def _stamp_after_container(r):
    r.arm["stamp_mono_ns"] = str(r.first_container + 1)


def _off_request(r):
    r.placement[0] = ("aw-sim", "0-5", "3,5", "running")


def _off_effective(r):
    r.placement[1] = ("aw-claim-node", "3,5", "0-5", "running")


def _no_request(r):
    r.placement[2] = ("aw-g1-diag", "", "3,5", "running")


def _no_row(r):
    r.placement.pop()


def _duplicate_seq(r):
    r.frames[5]["seq"] = 5


def _hole(r):
    r.frames[5]["seq"] = 10 ** 6


def _no_outcome(r):
    r.frames[5]["outcome"] = None


def _no_log(r):
    r.frames = None


def _digest_other(r):
    r.console = RULES_LINE % "0x87654321" + "\n"


def _no_rules_line(r):
    r.console = "monitor: boot\n"


def _no_validator_ok(r):
    r.diag = [x for x in r.diag if not (x.get("name") == VALIDATOR and x.get("level") == 0)]


def _recorder_gone(r):
    limit = r.drives[1]["begin"]
    r.diag = [x for x in r.diag if x["mono_ns"] < limit]


def _settings_differ(r):
    r.hc_after = r.hc_before.replace("212992", "4194304")


def _no_settings(r):
    r.hc_after = None


def _clock_off(r):
    r.pairs["container"] = (501 * S, 1800000001 * S + 2 * S)


def _no_clock(r):
    r.pairs = None


@pytest.mark.parametrize("change, name", [
    (_series_gap, "series"), (_series_short, "series"), (_series_late, "series"), (_no_stamp, "stamp"), (_stamp_policy, "stamp"),
    (_stamp_refused, "stamp"), (_stamp_after_container, "stamp"), (_off_request, "placement"), (_off_effective, "placement"),
    (_no_request, "placement"), (_no_row, "placement"), (_duplicate_seq, "reply-log"), (_hole, "reply-log"),
    (_no_outcome, "reply-log"), (_digest_other, "rules-digest"), (_no_rules_line, "rules-digest"),
    (_no_validator_ok, "positive-control"), (_recorder_gone, "positive-control"), (_settings_differ, "settings"),
    (_no_settings, "settings"), (_clock_off, "one-clock"), (_no_clock, "one-clock"),
], ids=lambda x: x if isinstance(x, str) else x.__name__.lstrip("_"))
def test_each_instrument_missing_alone_is_not_judged_naming_it(g1, tmp_path, change, name):
    r = Rec(tmp_path / "r")
    change(r)
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED", j.lines
    assert _missing(j) == [name], j.lines
    assert _failed(j) == [], j.lines
    assert name in _line(j, "verdict:"), j.lines


def test_the_series_absent_gives_t2_and_t3_no_reading_and_not_judged(g1, tmp_path):
    r = Rec(tmp_path / "r")
    _no_series(r)
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and "series" in _missing(j), j.lines
    assert _line(j, "T3").startswith("T3 no reading") and _line(j, "T2").startswith("T2 no reading"), j.lines


def test_the_reply_log_absent_is_not_judged_and_t4_has_no_reading(g1, tmp_path):
    r = Rec(tmp_path / "r")
    _no_log(r)
    j = _judge(g1, r)
    assert j.verdict == "FAIL" or j.verdict == "NOT JUDGED", j.lines
    assert "reply-log" in _missing(j), j.lines
    assert _line(j, "T4").startswith("T4 no reading") and _line(j, "T4w").startswith("T4w no reading"), j.lines


def test_a_gap_is_reported_with_the_lowest_value_on_each_side(g1, tmp_path):
    r = Rec(tmp_path / "r")
    t = r.drives[1]["begin"]
    r.series = [(a, 2000000 if a <= t else 1500000) for a, _b in r.series if not t < a < t + 7 * S]
    j = _judge(g1, r)
    text = _inst(j, "series")
    assert "2000000" in text and "1500000" in text, text


def test_a_gap_of_exactly_five_seconds_is_no_gap(g1, tmp_path):
    r = Rec(tmp_path / "r")
    t = r.drives[1]["begin"]
    r.series = [x for x in r.series if not t < x[0] < t + 5 * S]
    assert t in [x[0] for x in r.series] and t + 5 * S in [x[0] for x in r.series]
    j = _judge(g1, r)
    assert _inst(j, "series").startswith("instrument series OK"), j.lines


def test_the_series_instrument_ends_at_the_loops_end_and_not_at_the_last_stop(g1, tmp_path):
    """PR section 5: the instrument covers the span from the first container's start to the loop's end; T3 reads on to the last stop, as far
    as the series goes. A series that ends 1 s after the loop's end, well before the last stop, is a series that covers its span."""
    r = Rec(tmp_path / "r")
    r.series = [x for x in r.series if x[0] <= r.loop_end + 1 * S]
    assert r.series[-1][0] < r.last_stop - 30 * S, "the series ends well before the last stop"
    j = _judge(g1, r)
    assert not _missing(j) and j.verdict == "PASS", j.lines


def test_a_fail_beside_a_missing_instrument_is_a_fail_naming_both(g1, tmp_path):
    r = Rec(tmp_path / "r")
    _t3(r)
    _clock_off(r)
    j = _judge(g1, r)
    assert j.verdict == "FAIL", j.lines
    v = _line(j, "verdict:")
    assert "T3" in v and "one-clock" in v, v


@pytest.mark.parametrize("kb, verdict", [(1048576, "PASS"), (1048575, "FAIL")])
def test_t3_is_at_least_1048576_kb(g1, tmp_path, kb, verdict):
    r = Rec(tmp_path / "r")
    r.series[200] = (r.series[200][0], kb)
    assert _judge(g1, r).verdict == verdict


def test_t3_reads_the_1_s_series_from_the_first_containers_start_to_the_last_stop(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.series[0] = (r.series[0][0], 1000)          # before the first container: outside its span
    r.series[-1] = (r.series[-1][0], 1000)        # after the last stop: outside its span
    assert _judge(g1, r).verdict == "PASS"
    r2 = Rec(tmp_path / "r2")
    at = next(i for i, x in enumerate(r2.series) if x[0] > r2.loop_end + 5 * S)   # after the loop's end, before the last stop
    r2.series[at] = (r2.series[at][0], 1000)
    j = _judge(g1, r2)
    assert _failed(j) == ["T3"], j.lines


def test_t3_never_reads_the_5_s_sampler(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.sampler = [{"mono_ns": r.t0, "wall_ns": 1, "what": "meminfo", "MemAvailable": 1, "text": "MemAvailable: 1 kB"}]
    r.series = [(a, 2000000) for a, _b in r.series]
    j = _judge(g1, r)
    assert j.verdict == "PASS" and "2000000" in _line(j, "T3"), j.lines
    r2 = Rec(tmp_path / "r2")
    r2.series[300] = (r2.series[300][0], 1000)
    r2.sampler = [{"mono_ns": r2.t0, "wall_ns": 1, "what": "meminfo", "text": "MemAvailable: 9000000 kB"}]
    assert _failed(_judge(g1, r2)) == ["T3"]


def test_a_dead_5_s_sampler_has_no_effect_on_the_verdict(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.sampler = None
    assert _judge(g1, r).verdict == "PASS"


def test_a_frame_between_drives_enters_no_interval_and_t6_still_reads_it(g1, tmp_path):
    r = Rec(tmp_path / "r")
    base = _judge(g1, r)
    rate = float(re.search(r"([0-9.]+) per second", _line(base, "T4")).group(1))
    r2 = Rec(tmp_path / "r2")
    end = r2.drives[0]["lines"][-1]["mono_ns"]
    extra = [{"t": end + S // 2 + i * 10 ** 7, "outcome": "replied", "verdict": 0, "reason": 0} for i in range(100)]
    k = next(i for i, f in enumerate(r2.frames) if f["t"] > end)
    r2.frames[k:k] = extra
    j = _judge(g1, r2)
    assert j.verdict == "PASS", j.lines
    assert float(re.search(r"([0-9.]+) per second", _line(j, "T4")).group(1)) == rate
    assert any(x.startswith("info frames outside every drive: 100") for x in j.lines), j.lines
    r2.frames[k]["outcome"] = "drop"
    r2.summary["counters"]["drop"] = 1
    assert "T6" in _failed(_judge(g1, r2))


def test_a_frame_is_placed_by_its_tstamp_never_by_its_outcomes_mono_ns(g1, tmp_path):
    # a reply that comes back late: its outcome's mono_ns falls after the drive's last line, its tstamp inside
    r = Rec(tmp_path / "r").write()
    p = r.p("claim", "run", "replies.jsonl")
    out = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            doc = json.loads(ln)
            if "seq" in doc:
                doc["mono_ns"] = doc["mono_ns"] + 10 * S
            out.append(json.dumps(doc) + "\n")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)
    j = _judge(g1, r.d)
    assert j.verdict == "PASS", j.lines
    assert any(x.startswith("info frames outside every drive: 0") for x in j.lines), j.lines


def test_a_timed_out_drives_frames_still_count_and_t7_fails(g1, tmp_path):
    r = Rec(tmp_path / "r")
    dr = r.drives[1]
    dr["rc"] = 3
    dr["lines"][4] = {"step": "arrive", "outcome": "timeout", "state": 2, "mono_ns": dr["lines"][4]["mono_ns"]}
    dr["lines"].pop()
    j = _judge(g1, r)
    assert _failed(j) == ["T7"], j.lines
    n = len([f for f in r.frames if r.drives[0]["lines"][2]["mono_ns"] < f["t"] <= r.drives[0]["lines"][-1]["mono_ns"]
             or dr["lines"][2]["mono_ns"] < f["t"] <= dr["lines"][-1]["mono_ns"]
             or r.drives[2]["lines"][2]["mono_ns"] < f["t"] <= r.drives[2]["lines"][-1]["mono_ns"]
             or r.drives[3]["lines"][2]["mono_ns"] < f["t"] <= r.drives[3]["lines"][-1]["mono_ns"]])
    assert any(x.startswith("info frames inside drive intervals: %d" % n) for x in j.lines), j.lines


def test_a_drive_with_no_route_line_has_no_interval_and_t7_fails(g1, tmp_path):
    r = Rec(tmp_path / "r")
    dr = r.drives[2]
    route = dr["lines"][2]["mono_ns"]
    dr["lines"] = dr["lines"][:2] + [{"step": "route", "outcome": "timeout", "mono_ns": route}]
    dr["rc"] = 3
    last = route
    r.frames = [f for f in r.frames if not last < f["t"] <= route + 310 * S]
    r.summary["counters"]["replied"] = len(r.frames)
    j = _judge(g1, r)
    assert _failed(j) == ["T7"], j.lines
    assert any(x.startswith("info drive d003: no interval") for x in j.lines), j.lines


def test_a_drive_with_its_route_set_and_no_frame_has_no_interval_and_t7_has_failed(g1, tmp_path):
    r = Rec(tmp_path / "r")
    dr = r.drives[2]
    a, b = dr["lines"][2]["mono_ns"], dr["lines"][-1]["mono_ns"]
    r.frames = [f for f in r.frames if not a < f["t"] <= b]
    j = _judge(g1, r)
    assert "T7" in _failed(j), j.lines


def test_t4_with_no_interval_says_no_reading(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=1)
    r.drives[0]["lines"] = r.drives[0]["lines"][:2] + [{"step": "route", "outcome": "timeout", "mono_ns": r.t0 + 60 * S}]
    r.drives[0]["rc"] = 3
    r.frames = []
    r.summary["counters"]["replied"] = 0
    r.arm["loop_end"] = "first-no-route"
    j = _judge(g1, r)
    assert _line(j, "T4").startswith("T4 no reading"), j.lines
    assert _line(j, "T4w").startswith("T4w no reading"), j.lines
    assert j.verdict == "FAIL" and "T7" in _failed(j), j.lines


def test_a_window_that_would_end_after_the_drive_is_dropped(g1, tmp_path):
    r = Rec(tmp_path / "r")
    # the last 9 s of the first drive hold no frame: no whole window can cover them, so T4w sees none under 150 there
    last = r.drives[0]["lines"][-1]["mono_ns"]
    first = next(f["t"] for f in r.frames if f["t"] > r.drives[0]["lines"][2]["mono_ns"])
    whole = first + ((last - first) // (10 * S)) * 10 * S
    r.frames = [f for f in r.frames if not whole <= f["t"] <= last]
    r.summary["counters"]["replied"] = len(r.frames)
    assert _line(_judge(g1, r), "T4w").startswith("T4w PASS")


@pytest.mark.parametrize("count, ok", [(150, True), (149, False)])
def test_t4w_is_no_10_s_window_under_150(g1, tmp_path, count, ok):
    r = Rec(tmp_path / "r")
    first = next(f["t"] for f in r.frames if f["t"] > r.drives[0]["lines"][2]["mono_ns"])
    a, b = first + 20 * S, first + 30 * S
    inside = [f for f in r.frames if a <= f["t"] < b]
    keep = {id(f) for f in inside[:count]}
    r.frames = [f for f in r.frames if not (a <= f["t"] < b) or id(f) in keep]
    r.summary["counters"]["replied"] = len(r.frames)
    assert _line(_judge(g1, r), "T4w").startswith("T4w PASS" if ok else "T4w FAIL")


def test_t4_rate_at_exactly_30_per_second_holds_and_just_under_does_not(g1):
    assert g1.rate_holds(300, 10 * S) is True
    assert g1.rate_holds(299, 10 * S) is False
    assert g1.rate_holds(1, 0) is None


def test_t4_is_one_number_over_the_driven_time_the_silence_counts_in_neither_direction(g1, tmp_path):
    r = Rec(tmp_path / "r")
    j = _judge(g1, r)
    frames = len(r.frames)
    total = sum(dr["lines"][-1]["mono_ns"] - next(f["t"] for f in r.frames if f["t"] > dr["lines"][2]["mono_ns"])
                for dr in r.drives)
    got = float(re.search(r"([0-9.]+) per second", _line(j, "T4")).group(1))
    assert abs(got - frames * S / total) < 0.01, _line(j, "T4")


def test_t5_ignores_the_wait_before_the_first_route_and_warn_and_another_status(g1, tmp_path):
    r = Rec(tmp_path / "r")
    t = r.drives[1]["begin"]
    r.diag += [{"mono_ns": t, "first": False, "name": T5_LIST[0], "hardware_id": "x", "level": 1, "message": "Warn"},
               {"mono_ns": t, "first": False, "name": VALIDATOR, "hardware_id": "c", "level": 2, "message": "latency"},
               {"mono_ns": t, "first": False, "name": "vehicle_cmd_gate: heartbeat", "hardware_id": "g", "level": 2, "message": "x"}]
    j = _judge(g1, r)
    assert j.verdict == "PASS", j.lines
    assert any(x.startswith("info status not on the list reached") and VALIDATOR in x for x in j.lines), j.lines


def test_the_latency_status_entries_and_time_away_are_recorded_and_gate_nothing(g1, tmp_path):
    r = Rec(tmp_path / "r")
    t = r.drives[1]["begin"]
    r.diag += [{"mono_ns": t, "first": False, "name": VALIDATOR, "hardware_id": "c", "level": 2, "message": "x"},
               {"mono_ns": t + 3 * S, "first": False, "name": VALIDATOR, "hardware_id": "c", "level": 0, "message": "OK"}]
    j = _judge(g1, r)
    assert j.verdict == "PASS", j.lines
    assert any("control_validation_latency, recorded, no gate item: 1 entries away from OK, 3.000 s away" in x for x in j.lines), j.lines


def test_oomkilled_is_information_only(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.arm["oomkilled_aw-sim"] = "true"
    j = _judge(g1, r)
    assert j.verdict == "PASS" and "info OOMKilled, information only: aw-sim true" in j.lines, j.lines


@pytest.mark.parametrize("facts, said", [
    ({"driver_ended_between_drives": "d003", "driver_inspect_unanswered": "exit 1"}, ["d003", "exit 1"]),
    ({"driver_ended_between_drives": "d003"}, ["d003"]),
    ({"driver_inspect_unanswered": "exit 1"}, ["exit 1"]),
    ({}, [])], ids=["both", "ended", "unanswered", "neither"])
def test_a_driver_found_ended_between_drives_and_an_inspect_with_no_answer_are_recorded_and_gate_nothing(g1, tmp_path, facts, said):
    """A second container start is a second join: the verdict says so beside its lines, and reads PASS all the same."""
    r = Rec(tmp_path / "r")
    r.arm.update(facts)
    j = _judge(g1, r)
    mine = [x for x in j.lines if x.startswith("info the resident driver")]
    assert j.verdict == "PASS", j.lines
    assert len(mine) == (1 if facts else 0), j.lines
    if facts:
        assert all(w in mine[0] for w in said) and "no gate item" in mine[0], mine
        assert ("d003" in mine[0]) == ("driver_ended_between_drives" in facts), mine
        assert ("exit 1" in mine[0]) == ("driver_inspect_unanswered" in facts), mine


def _t5_no_ok_on_the_list(r):
    r.diag = [x for x in r.diag if not (x.get("name") in T5_LIST and x.get("level") == 0)]


def test_a_status_never_ok_with_the_recorder_unseeing_at_the_first_end_is_no_reading_and_no_pass_line(g1, tmp_path):
    r = Rec(tmp_path / "r")
    _t5_no_ok_on_the_list(r)
    r.diag = [x for x in r.diag if "last_seen" not in x]
    j = _judge(g1, r)
    line = _line(j, "T5")
    assert line.startswith("T5 no reading") and "whether" in line and "not read" in line and T5_LIST[0] in line, line
    assert j.verdict == "NOT JUDGED" and "T5: no reading" in j.lines[-2] and _missing(j) == ["positive-control"], j.lines


def test_a_status_never_ok_with_the_recorder_seeing_at_the_first_end_is_still_a_fail(g1, tmp_path):
    r = Rec(tmp_path / "r")
    _t5_no_ok_on_the_list(r)
    j = _judge(g1, r)
    assert _line(j, "T5").startswith("T5 FAIL") and "had not been OK by the end of the first drive" in _line(j, "T5"), j.lines
    assert j.verdict == "FAIL"


def test_a_status_ok_in_time_with_the_recorder_unseeing_at_the_first_end_holds_t5(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.diag = [x for x in r.diag if "last_seen" not in x]
    j = _judge(g1, r)
    assert _line(j, "T5").startswith("T5 PASS"), j.lines


def test_a_reading_of_error_beside_a_status_not_read_is_a_fail(g1, tmp_path):
    r = Rec(tmp_path / "r")
    t = r.drives[1]["begin"]
    r.diag = [x for x in r.diag if "last_seen" not in x and not (x.get("name") == T5_LIST[1] and x.get("level") == 0)]
    r.diag.append({"mono_ns": t, "first": False, "name": T5_LIST[2], "hardware_id": "x", "level": 2, "message": "timeout"})
    j = _judge(g1, r)
    assert _line(j, "T5").startswith("T5 FAIL") and "reached ERROR" in _line(j, "T5"), j.lines
    assert j.verdict == "FAIL", j.lines


def test_a_first_drive_with_no_line_says_t5_has_no_reading(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.drives[0]["lines"] = None
    r.drives[0]["rc"] = 1
    j = _judge(g1, r)
    line = _line(j, "T5")
    assert line.startswith("T5 no reading") and "the first drive wrote no line" in line, line


def test_a_silent_validator_at_a_line_outside_any_drive_does_not_fail(g1, tmp_path):
    r = Rec(tmp_path / "r")
    for x in r.diag:
        if "last_seen" in x and x["mono_ns"] < r.drives[0]["lines"][3]["mono_ns"]:
            x["last_seen"][VALIDATOR] = x["mono_ns"] - 60 * S
    assert _judge(g1, r).verdict == "PASS"


def test_a_validator_silent_with_the_recorder_also_silent_is_no_t5_fail(g1, tmp_path):
    r = Rec(tmp_path / "r")
    limit = r.drives[1]["begin"]
    for x in r.diag:
        if "last_seen" in x and x["mono_ns"] > limit:
            for n in x["last_seen"]:
                x["last_seen"][n] = limit
    j = _judge(g1, r)
    assert "T5" not in _failed(j) and "positive-control" in _missing(j) and j.verdict == "NOT JUDGED", j.lines


def test_the_validator_gone_silent_with_the_recorder_alive_is_a_fail_and_the_recorder_gone_is_not_judged(g1, tmp_path):
    a = Rec(tmp_path / "a")
    _t5_silent(a)
    j = _judge(g1, a)
    assert j.verdict == "FAIL" and _failed(j) == ["T5"], j.lines
    b = Rec(tmp_path / "b")
    _recorder_gone(b)
    j = _judge(g1, b)
    assert j.verdict == "NOT JUDGED" and "positive-control" in _missing(j), j.lines


def test_every_reject_and_every_miss_is_a_finding_with_its_seq_and_place_and_no_gate_item(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.frames[10].update(verdict=1, reason=11)
    seq2 = 1 + next(i for i, f in enumerate(r.frames) if f["t"] > r.drives[1]["lines"][2]["mono_ns"])
    r.console += "monitor: LIVENESS MISS: no claim for 512 ms since seq=%d (deadline 500 ms, miss 1)\n" % seq2
    j = _judge(g1, r)
    assert j.verdict == "PASS", j.lines
    assert "finding REJECT seq=11 reason=11 in d001" in j.lines, j.lines
    assert any(x.startswith("finding MISS seq=%d in d002" % seq2) for x in j.lines), j.lines


def test_a_miss_before_the_arm_is_not_read(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.console = "monitor: LIVENESS MISS: no claim for 512 ms since seq=3 (deadline 500 ms, miss 1)\n"
    r.arm["console_arm_from"] = str(len(r.console))
    r.console += RULES_LINE % DIGEST + "\n"
    j = _judge(g1, r)
    assert not any(x.startswith("finding MISS") for x in j.lines), j.lines


def test_a_miss_of_a_frame_after_the_last_drive_is_a_finding_named_by_that_place_and_gates_nothing(g1, tmp_path):
    """PR's dated section, item 10: the one MISS when the claim node stops after the last drive, with the guest still running, is a finding
    under section 6 named in the record by its place. The last frame of the reply log comes 2 s after the last drive's last line."""
    r = Rec(tmp_path / "r")
    r.frames.append({"t": r.drives[-1]["lines"][-1]["mono_ns"] + 2 * S, "outcome": "replied", "verdict": 0, "reason": 0})
    seq = len(r.frames)
    r.console += "monitor: LIVENESS MISS: no claim for 512 ms since seq=%d (deadline 500 ms, miss 1)\n" % seq
    j = _judge(g1, r)
    assert j.verdict == "PASS", j.lines
    assert "finding MISS seq=%d after the last drive" % seq in j.lines, j.lines


def test_a_loop_ended_by_the_watchdog_is_a_fail_with_the_summary_and_the_last_line_absent(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=2)
    r.events = [(r.drives[1]["begin"] + 100 * S, 1800000000 * S, "stop floor_kb=716800 avail_kb=700000")]
    r.stop_file = "stop\n"
    dr = r.drives[1]
    dr["rc"] = 137
    dr["lines"] = dr["lines"][:4]
    r.frames = [f for f in r.frames if f["t"] <= r.events[0][0]]
    r.summary = None
    r.mem_events = [("aw-sim", "gone"), ("aw-claim-node", "gone"), ("aw-g1-diag", "gone")]
    r.arm["loop_end"] = "watchdog-stop"
    r.arm["loop_end_mono_ns"] = str(dr["end"])
    r.loop_end = dr["end"]
    r.diag = [x for x in r.diag if x["mono_ns"] < r.events[0][0]]
    j = _judge(g1, r)
    assert j.verdict == "FAIL", j.lines
    assert "T2" in _failed(j) and "T7" in _failed(j), j.lines
    assert not _line(j, "T6").startswith("T6 FAIL") and "T1" not in _failed(j), j.lines
    assert "re-run: none for a verdict" in " ".join(j.lines)


@pytest.mark.parametrize("stop_exit", ["124", "1"])
def test_a_missing_summary_after_a_docker_stop_that_got_no_answer_is_t6_with_no_reading_not_judged_and_a_rerun_is_allowed(g1, tmp_path, stop_exit):
    """PR's dated section, item 13: the harness's own `docker stop` of the claim node exited non-zero, so the node was never signalled and
    its missing summary reads nothing about the node or about Autoware."""
    r = Rec(tmp_path / "r")
    r.summary = None
    r.arm["claim_stop_exit"] = stop_exit
    j = _judge(g1, r)
    line = _line(j, "T6")
    assert line.startswith("T6 no reading") and "docker stop" in line and "exited %s" % stop_exit in line, line
    assert j.verdict == "NOT JUDGED" and _failed(j) == [] and not _missing(j), j.lines
    assert "T6: no reading" in _line(j, "verdict:"), j.lines
    assert "re-run: allowed on the owner's word" in " ".join(j.lines), j.lines


def test_a_missing_summary_after_a_docker_stop_that_answered_stays_a_t6_fail(g1, tmp_path):
    """PR's dated section, item 13: only a stop that got no answer excuses the missing summary; one that exited 0 signalled the node."""
    r = Rec(tmp_path / "r")
    r.summary = None
    r.arm["claim_stop_exit"] = "0"
    j = _judge(g1, r)
    assert j.verdict == "FAIL" and _failed(j) == ["T6"], j.lines
    assert "the claim node did not end its run" in _line(j, "T6"), j.lines
    assert "re-run: none for a verdict" in " ".join(j.lines), j.lines


@pytest.mark.parametrize("stop_exit", ["124", "1"])
def test_a_summary_that_is_there_is_t6s_reading_whatever_the_docker_stops_exit(g1, tmp_path, stop_exit):
    """PR's dated section, item 13 reads a MISSING summary; PR section 5: an item failed by a reading is never re-run. The summary is there and
    holds a drop, and the harness's docker stop of the claim node got no answer: the drop is still T6's reading."""
    r = Rec(tmp_path / "r")
    r.summary["counters"]["drop"] = 1
    r.arm["claim_stop_exit"] = stop_exit
    j = _judge(g1, r)
    assert j.verdict == "FAIL" and _failed(j) == ["T6"] and "drop 1" in _line(j, "T6"), j.lines
    assert "re-run: none for a verdict" in " ".join(j.lines), j.lines


ITEM_14_WORDS = ("deadline", "watchdog-dead", "misplaced", "docker-run-failed", "docker-wait-failed")


@pytest.mark.parametrize("word", ITEM_14_WORDS)
def test_a_missing_summary_after_a_loop_ended_by_the_harness_is_t6_with_no_reading_whatever_the_docker_stop_answered(g1, tmp_path, word):
    """PR's dated section, item 14: where the loop ended by a word of the harness's own, a missing summary is T6 with no reading even when the
    harness's docker stop of the claim node answered (exit 0): the stop's answer does not show the node was still alive to be signalled."""
    r = Rec(tmp_path / "r")
    r.summary = None
    r.arm["loop_end"] = word
    r.arm["claim_stop_exit"] = "0"
    if word == "deadline":
        r.arm["harness_end"] = "status=TIMEOUT at=arm reason=deadline"
    j = _judge(g1, r)
    assert _line(j, "T6").startswith("T6 no reading"), j.lines
    assert j.verdict == "NOT JUDGED" and _failed(j) == [], j.lines
    assert "T6: no reading" in _line(j, "verdict:") and g1.HARNESS_ENDS[word] in _line(j, "verdict:"), j.lines
    assert "re-run: allowed on the owner's word" in " ".join(j.lines), j.lines


def test_the_words_of_pr_s_item_14_are_the_judge_s_own_harness_ends(g1):
    with open(PREREG, encoding="utf-8") as f:
        pr = f.read()
    item = pr[pr.index("14. **Item 13's last sentence"):].partition("a missing summary")[0]
    assert set(re.findall(r"`([a-z-]+)`", item)) == set(ITEM_14_WORDS) == set(g1.HARNESS_ENDS), item


def test_a_stop_between_drives_fails_t7_for_the_loops_1200_s_and_t2(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=2)
    r.stop_file = "stop\n"
    r.events = [(r.drives[1]["end"], 1800000000 * S, "stop floor_kb=716800 avail_kb=700000")]
    r.arm["loop_end"] = "watchdog-stop"
    j = _judge(g1, r)
    assert _failed(j) == ["T2", "T7"] and "did not reach 1200 s" in _line(j, "T7"), j.lines


def test_a_dead_watchdog_stops_the_loop_and_is_not_judged(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=2)
    r.loop_end = r.drives[1]["end"]
    r.arm["loop_end"] = "watchdog-dead"
    r.arm["loop_end_mono_ns"] = str(r.loop_end)
    r.series = [x for x in r.series if x[0] < r.drives[1]["begin"]]
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED", j.lines
    assert _failed(j) == [], j.lines
    assert _line(j, "T7").startswith("T7 no reading"), j.lines
    v = _line(j, "verdict:")
    assert "watchdog" in v and "series" in v, v
    assert "re-run: allowed" in " ".join(j.lines)


def test_a_drive_the_harness_could_not_start_is_unread_and_not_judged(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=3)
    r.drives[2] = {"begin": r.drives[2]["begin"], "rc": None, "end": None, "stopped": "docker-run-exit-125", "lines": None}
    r.frames = r.frames_of(r.drives[0]) + r.frames_of(r.drives[1])
    r.arm["loop_end"] = "docker-run-failed"
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and not _failed(j), j.lines
    assert _line(j, "T7").startswith("T7 no reading") and "docker-run-exit-125" in _line(j, "T7"), j.lines
    assert "could not start a drive" in j.lines[-2], j.lines
    assert j.lines[-1].startswith("re-run: allowed"), j.lines


def test_a_drive_the_harness_could_not_start_leaves_an_earlier_drives_reading_a_fail(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=3)
    r.drives[0]["rc"] = 3
    r.drives[2] = {"begin": r.drives[2]["begin"], "rc": None, "end": None, "stopped": "docker-run-exit-125", "lines": None}
    r.frames = r.frames_of(r.drives[0]) + r.frames_of(r.drives[1])
    r.arm["loop_end"] = "docker-run-failed"
    j = _judge(g1, r)
    assert j.verdict == "FAIL" and _failed(j) == ["T7"] and "d001 exited 3" in _line(j, "T7"), j.lines
    assert "could not start a drive" in j.lines[-2], j.lines
    assert j.lines[-1].startswith("re-run: none"), j.lines


def _drive_with_no_exit_read(r, word):
    r.drives[2].update(rc=None, end=None, stopped=word)         # PR's dated section, item 12: its driver ran, so its lines stand
    r.arm["loop_end"] = "docker-wait-failed"


def test_a_drive_whose_exit_was_not_read_is_unread_and_not_judged(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=3)
    _drive_with_no_exit_read(r, "docker-wait-bound-no-answer")
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and not _failed(j), j.lines
    assert _line(j, "T7").startswith("T7 no reading") and "docker-wait-bound-no-answer" in _line(j, "T7"), j.lines
    assert "read no exit from a drive" in j.lines[-2] and "could not start a drive" not in j.lines[-2], j.lines
    assert j.lines[-1].startswith("re-run: allowed"), j.lines


def test_a_drive_whose_exit_was_not_read_leaves_an_earlier_drives_reading_a_fail(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=3)
    r.drives[0]["rc"] = 3
    _drive_with_no_exit_read(r, "docker-wait-exit-1")
    j = _judge(g1, r)
    assert j.verdict == "FAIL" and _failed(j) == ["T7"] and "d001 exited 3" in _line(j, "T7"), j.lines
    assert "read no exit from a drive" in j.lines[-2], j.lines
    assert j.lines[-1].startswith("re-run: none"), j.lines


def test_the_harness_own_exit_names_why_it_gave(g1, tmp_path):
    r = Rec(tmp_path / "r")
    del r.arm["loop_end"]
    r.arm["harness_end"] = "status=FAILED at=arm"
    r.arm["harness_why"] = "docker run of aw-sim exited 125: the stand-in refuses"
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and "status=FAILED at=arm: docker run of aw-sim exited 125" in j.lines[-2], j.lines


def test_a_container_off_its_cores_stops_before_the_loop_and_is_not_judged(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=0)
    r.frames = []
    r.summary["counters"]["replied"] = 0
    r.placement = [("aw-sim", "3,5", "0-5", "running")]
    r.diag = None
    r.arm["loop_end"] = "misplaced"
    r.arm["loop_end_mono_ns"] = str(r.first_container + 5 * S)
    r.arm["last_stop_mono_ns"] = str(r.first_container + 10 * S)
    r.series = [x for x in r.series if x[0] < r.first_container + 20 * S]
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED", j.lines
    assert _failed(j) == [], j.lines
    assert "placement" in _line(j, "verdict:"), j.lines
    assert _line(j, "T4").startswith("T4 no reading") and _line(j, "T7").startswith("T7 no reading"), j.lines


@pytest.mark.parametrize("end, word", [(None, "exited"), ("status=TIMEOUT at=arm reason=step-timeout", "TIMEOUT"),
                                       ("status=FAILED at=arm", "FAILED at=arm")])
def test_the_harness_own_exit_is_not_judged_naming_it(g1, tmp_path, end, word):
    r = Rec(tmp_path / "r", drives=2)
    r.drives[1]["rc"] = None
    r.drives[1]["lines"] = r.drives[1]["lines"][:4]
    r.frames = [f for f in r.frames if f["t"] <= r.drives[1]["lines"][-1]["mono_ns"] + 50 * S]
    r.summary = None
    r.vmstat_end = None
    r.mem_events = None
    r.hc_after = None
    for k in ("loop_end", "loop_end_mono_ns", "last_stop_mono_ns", "harness_end"):
        r.arm.pop(k)
    if end is not None:
        r.arm["harness_end"] = end
    r.series = [x for x in r.series if x[0] < r.drives[1]["begin"] + 50 * S]
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED", j.lines
    assert _failed(j) == [], j.lines
    assert word in _line(j, "verdict:"), j.lines
    for w in ("T1", "T6", "T7"):
        assert _line(j, w).startswith(w + " no reading"), j.lines


def test_a_host_check_failed_stem_is_the_settings_instrument_and_no_early_exit(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.arm["harness_end"] = "status=FAILED at=host-check"
    _settings_differ(r)
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and _missing(j) == ["settings"], j.lines
    assert "FAILED" not in _line(j, "verdict:").replace("settings", ""), j.lines


def _reset_record(r):
    r.drives[1]["rc"] = None
    r.drives[1]["lines"] = r.drives[1]["lines"][:4]
    r.frames = [f for f in r.frames if f["t"] <= r.drives[1]["lines"][-1]["mono_ns"]]
    r.summary = None
    r.vmstat_end = None
    r.mem_events = None
    r.hc_after = None
    r.diag = [x for x in r.diag if x["mono_ns"] <= r.drives[1]["lines"][-1]["mono_ns"]]
    r.series = [x for x in r.series if x[0] <= r.drives[1]["lines"][-1]["mono_ns"]]
    for k in ("loop_end", "loop_end_mono_ns", "last_stop_mono_ns", "harness_end"):
        r.arm.pop(k)


def test_a_reset_is_a_fail_its_prevented_readings_not_counted_and_a_rerun_allowed(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=2)
    _reset_record(r)
    j = _judge(g1, r, reset="watchdog reset, reset_reason read by the owner")
    assert j.verdict == "FAIL", j.lines
    assert _failed(j) == [], j.lines
    assert j.reasons == ["a reset, a hang or an oops during the arm, cause not assigned: watchdog reset, reset_reason read by the owner"], j.reasons
    for w in ("T1", "T6", "T7"):
        assert _line(j, w).startswith(w + " no reading"), j.lines
    assert "re-run: allowed" in " ".join(j.lines), j.lines


def test_a_reset_beside_an_item_failed_by_a_reading_is_never_re_run(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=2)
    _reset_record(r)
    r.series[50] = (r.series[50][0], 1000)
    j = _judge(g1, r, reset="a hang")
    assert j.verdict == "FAIL" and _failed(j) == ["T3"], j.lines
    assert "re-run: none for a verdict" in " ".join(j.lines), j.lines


def test_a_pass_after_a_reset_is_never_a_plain_pass(g1, tmp_path):
    r = Rec(tmp_path / "r")
    j = _judge(g1, r, rerun_of="20261201T-a6-orin-aw-g1", rerun_after="reset")
    assert j.verdict == "PASS"
    v = _line(j, "verdict:")
    assert v != "verdict: PASS" and "passed on a later boot after a reset of unassigned cause" in v, v
    assert "20261201T-a6-orin-aw-g1" in " ".join(j.lines), j.lines


def test_a_rerun_of_a_not_judged_arm_names_it(g1, tmp_path):
    r = Rec(tmp_path / "r")
    j = _judge(g1, r, rerun_of="20261201T-a6-orin-aw-g1", rerun_after="not-judged")
    assert j.verdict == "PASS"
    assert "a re-run of 20261201T-a6-orin-aw-g1" in _line(j, "verdict:"), j.lines
    assert "reset" not in _line(j, "verdict:"), j.lines


def test_a_failing_rerun_says_it_is_a_rerun(g1, tmp_path):
    r = Rec(tmp_path / "r")
    _t3(r)
    j = _judge(g1, r, rerun_of="X", rerun_after="reset")
    assert j.verdict == "FAIL" and any("a re-run of X" in x for x in j.lines), j.lines


def test_the_guest_stopped_arm_reads_the_count_recorder_and_drop_and_lost_do_not_apply(g1, tmp_path):
    r = Rec(tmp_path / "r", arm="guest-stopped")
    j = _judge(g1, r)
    assert j.verdict == "PASS", j.lines
    assert _line(j, "T6").startswith("T6 does not apply"), j.lines
    for name in ("reply-log", "rules-digest"):
        assert "does not apply" in _inst(j, name), j.lines
    assert any("never subtracted" in x for x in j.lines), j.lines


def test_the_guest_stopped_arm_fails_on_its_own_rate(g1, tmp_path):
    r = Rec(tmp_path / "r", arm="guest-stopped")
    r.frames = [f for i, f in enumerate(r.frames) if i % 3 != 0]
    assert "T4" in _failed(_judge(g1, r))


def test_a_torn_last_line_is_no_frame_and_the_parsers_keep_what_is_whole(g1, tmp_path):
    r = Rec(tmp_path / "r").write()
    with open(r.p("claim", "run", "replies.jsonl"), "a", encoding="utf-8") as f:
        f.write('{"seq": 99999, "frame": "0100')
    with open(r.p("drives", "d001", "scenario.jsonl"), "a", encoding="utf-8") as f:
        f.write('{"step": "cl')
    replies = g1.read_replies(r.p("claim", "run", "replies.jsonl"))
    assert replies.torn == 1 and replies.frames and replies.summary is not None
    assert [x["step"] for x in g1.read_scenario(r.p("drives", "d001", "scenario.jsonl"))][-1] == "clear"


# The form of the spike's real files, every number rewritten (no figure of a run): one drive's scenario.jsonl, the reply log's
# header, frames and summary, and /diagnostics lines as the spike's recorder wrote them.
CUT_SCENARIO = (
    '{"step":"map","outcome":"done","success":null,"code":null,"message":null,"state":null,"detail":"4 files, each with the '
    'scenario\'s sha256","mono_ns":1000000000,"ros_ns":null,"scenario":"sample-lanelet-102","scenario_sha256":"' + "ab" * 32
    + '","files":{"lanelet2_map.osm":"' + "cd" * 32 + '"}}\n'
    '{"step":"localize","outcome":"done","success":true,"code":0,"message":"","state":3,"detail":"","mono_ns":1100000000,"ros_ns":2000}\n'
    '{"step":"route","outcome":"done","success":true,"code":0,"message":"","state":2,"detail":"","mono_ns":1200000000,"ros_ns":2100}\n'
    '{"step":"engage","outcome":"done","success":true,"code":0,"message":"","state":2,"detail":"","mono_ns":1300000000,"ros_ns":2200}\n'
    '{"step":"arrive","outcome":"done","success":null,"code":null,"message":null,"state":3,"detail":"","mono_ns":1400000000,"ros_ns":2300}\n'
    '{"step":"clear","outcome":"done","success":true,"code":0,"message":"","state":null,"detail":"","mono_ns":1500000000,"ros_ns":2400}\n')
_F_TAIL = "0801000000000000000000000000000000000000000000000200000000000000" + "00" * 16
CUT_REPLIES = (
    '{"header":{"format":1,"kind":2,"mode":"node","target":"127.0.0.1:7150","stamp":false,"profile":1,"demo":null,"injections":[],'
    '"pause":null,"contract_sha256":"' + "ef" * 32 + '","digest":305419896,"design":{"reply_timeout_ms":500,"connect_timeout_ms":500,'
    '"backoff_first_ms":100,"backoff_cap_ms":2000,"odom_fresh_ms":100}}}\n'
    + "".join('{"seq":%d,"frame":"%s","outcome":"replied","verdict":0,"reason":0,"mono_ns":%d}\n'
              % (i, _frame_hex(i, 1200000000 + i * 1000)[:32] + _F_TAIL, 1300000000 + i) for i in (1, 2, 3))
    + '{"summary":{"counters":{"controls":3,"packed":3,"controls_paused":0,"replied":3,"accepted":3,"rejected":0,"drop":0,'
      '"lost_on_reconnect":0,"connects":1,"reconnects":0,"connect_failures":0,"peer_checks":3,"sends":3,"reply_timeouts":0,'
      '"reply_invalid":0,"stray_bytes":0,"r17_skip":0,"odom_absent":0,"odom_stale":0,"interval_negative":0,"nonfinite_in":0,'
      '"injected":0,"demo_frames":0,"sink_errors":1},"identity":{"controls":3,"packed":3,"replied":3,"drop":0,'
      '"lost_on_reconnect":0,"holds":true},"demo":null,"last_reply":[0,0,3],"fatal":null}}\n')
CUT_DIAG = (
    '{"mono_ns": 1000, "first": true, "name": "topic_state_monitor_trajectory_follower_control_cmd: control_topic_status", '
    '"hardware_id": "topic_state_monitor", "level": 2, "message": "Error"}\n'
    '{"mono_ns": 2000, "values": "topic_state_monitor_control_command_control_cmd: control_topic_status", "kv": {"topic": '
    '"/control/command/control_cmd", "status": "Timeout", "warn_rate": "5.00 [Hz]", "error_rate": "1.00 [Hz]", "timeout": "1.00 [s]", '
    '"measured_rate": "1.00 [Hz]", "now": "3.00 [s]", "last_message_time": "1.00 [s]"}}\n'
    '{"summary": "vehicle_cmd_gate: heartbeat", "level": 0, "count": 3, "last_ns": 4000, "first_ns": 3000, "hardware_id": "vehicle_cmd_gate"}\n')


def test_the_parsers_take_the_real_files_form(g1, tmp_path):
    (tmp_path / "scenario.jsonl").write_text(CUT_SCENARIO, encoding="utf-8")
    (tmp_path / "replies.jsonl").write_text(CUT_REPLIES, encoding="utf-8")
    (tmp_path / "diag.jsonl").write_text(CUT_DIAG, encoding="utf-8")
    lines = g1.read_scenario(str(tmp_path / "scenario.jsonl"))
    assert [x["step"] for x in lines] == ["map", "localize", "route", "engage", "arrive", "clear"]
    assert g1.route_mono(lines) == 1200000000
    rep = g1.read_replies(str(tmp_path / "replies.jsonl"))
    assert [f.seq for f in rep.frames] == [1, 2, 3] and rep.summary["identity"]["holds"] is True
    assert [f.t_ns for f in rep.frames] == [1200001000, 1200002000, 1200003000]
    assert all(f.outcome == "replied" and f.verdict == 0 for f in rep.frames)
    d = g1.read_diag(str(tmp_path / "diag.jsonl"))
    assert [e["level"] for e in d.events] == [2] and d.fifth == []


def test_the_judges_cli_prints_the_lines_and_writes_verdict_and_windows(g1, tmp_path, capsys):
    r = Rec(tmp_path / "r").write()
    out = tmp_path / "o"
    rc = g1.main(["judge", "--rec", r.d, "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "verdict: PASS" in printed
    assert (out / "verdict.txt").read_text(encoding="utf-8") == printed
    rows = (out / "windows.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0].split("\t") == ["drive", "start_mono_ns", "frames", "emc_bpmp_hz"] and len(rows) > 100


def test_a_fail_is_still_exit_0_of_the_judge(g1, tmp_path, capsys):
    r = Rec(tmp_path / "r")
    _t3(r)
    r.write()
    assert g1.main(["judge", "--rec", r.d]) == 0
    assert "verdict: FAIL" in capsys.readouterr().out


def test_a_rerun_after_needs_what_it_is_a_rerun_of(g1, tmp_path):
    r = Rec(tmp_path / "r").write()
    with pytest.raises(SystemExit):
        g1.main(["judge", "--rec", r.d, "--rerun-after", "reset"])


def test_each_windows_clock_comes_from_the_clock_sampler(g1, tmp_path):
    r = Rec(tmp_path / "r").write()
    mono0, wall0 = (int(x) for x in r.arm["arm_pair_start"].split())
    first = next(f["t"] for f in r.frames if f["t"] > r.drives[0]["lines"][2]["mono_ns"])
    wall = wall0 + first - mono0
    r.put("clk-g1.log", "%.6f emc_bpmp_hz=2133000000 emc_ccf_hz=2133000000 gpu_hz=0\n" % ((wall - S) / S))
    out = tmp_path / "o"
    assert g1.main(["judge", "--rec", r.d, "--out", str(out)]) == 0
    rows = (out / "windows.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[1].split("\t")[3] == "2133000000"


def test_the_design_values_are_the_prereg_s(g1):
    with open(PREREG, encoding="utf-8") as f:
        pr = f.read()
    assert g1.LOOP_NS == 1200 * S and "1200 s" in pr
    assert g1.T3_KB == 1048576 and "1048576 kB" in pr
    assert g1.RATE_MIN == 30 and "at least 30.0 per second" in pr
    assert g1.WINDOW_NS == 10 * S and g1.WINDOW_MIN == 150 and "under 150 frames" in pr
    assert g1.GAP_NS == 5 * S and "no gap over 5 s" in pr
    assert g1.SILENT_NS == 10 * S and "over 10 s" in pr
    assert g1.CLOCK_TOLERANCE_NS == 1 * S and "within 1 s" in pr
    assert tuple(g1.T5_LIST) == T5_LIST
    for n in T5_LIST:
        assert "`%s`" % n in pr.replace("\n", " ").replace("`, `", "`, `") or n in pr.replace("\n", " ")
    assert "control_validation_latency" not in " ".join(g1.T5_LIST)


# --- boundaries and findings of the judge, each at the exact word of PR --------------------------------------------------------------

def _cut_in_the_first_drive(r):
    """A record cut inside d001, after its engage line: the drive has no end and no last line of its own, the statuses are still at ERROR
    (they stay there until Control has begun) and the recorder is seeing. A reset in Autoware's start-up looks like this."""
    dr = r.drives[0]
    dr["rc"] = None
    dr["lines"] = dr["lines"][:4]
    cut = dr["lines"][-1]["mono_ns"]
    r.frames = [f for f in r.frames if f["t"] <= cut]
    r.summary = None
    r.vmstat_end = None
    r.mem_events = None
    r.hc_after = None
    _t5_no_ok_on_the_list(r)
    r.diag = [x for x in r.diag if x["mono_ns"] <= cut + 3 * S]
    r.series = [x for x in r.series if x[0] <= cut]
    for k in ("loop_end", "loop_end_mono_ns", "last_stop_mono_ns", "harness_end"):
        r.arm.pop(k)


def test_a_reset_in_the_first_drive_before_it_ends_names_only_the_reset_and_t5_is_not_read(g1, tmp_path):
    """PR section 5: the readings a reset prevented are not readings, so its one failing reason is the reset. "Not OK by the end of the
    first drive" needs a first drive that ended."""
    r = Rec(tmp_path / "r", drives=1)
    _cut_in_the_first_drive(r)
    j = _judge(g1, r, reset="watchdog reset, reset_reason read by the owner")
    assert j.verdict == "FAIL" and _failed(j) == [], j.lines
    assert j.reasons == ["a reset, a hang or an oops during the arm, cause not assigned: watchdog reset, reset_reason read by the owner"], j.reasons
    line = _line(j, "T5")
    assert line.startswith("T5 no reading") and "the first drive did not end" in line, line
    assert j.lines[-1].startswith("re-run: allowed"), j.lines


def test_a_first_drive_that_never_ended_is_not_judged_never_failed_by_t5(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=1)
    _cut_in_the_first_drive(r)
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and _failed(j) == [], j.lines
    assert _line(j, "T5").startswith("T5 no reading") and "the first drive did not end" in _line(j, "T5"), j.lines
    assert j.lines[-1].startswith("re-run: allowed"), j.lines


def test_a_first_drive_that_never_ended_reads_no_pass_for_t5_even_with_every_status_ok(g1, tmp_path):
    """Nothing fails and nothing is wrong with the statuses, but "OK by the end of the first drive" is a statement about an end."""
    r = Rec(tmp_path / "r", drives=1)
    _cut_in_the_first_drive(r)
    for n in T5_LIST:
        r.diag.append({"mono_ns": r.drives[0]["lines"][-1]["mono_ns"], "first": False, "name": n, "hardware_id": "x", "level": 0, "message": "OK"})
    line = _line(_judge(g1, r), "T5")
    assert line.startswith("T5 no reading") and "the first drive did not end" in line and "PASS" not in line, line


def test_a_first_drive_that_ended_with_its_statuses_not_ok_and_the_recorder_seeing_is_still_a_fail(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=1)
    _t5_no_ok_on_the_list(r)
    j = _judge(g1, r)
    assert _line(j, "T5").startswith("T5 FAIL") and "had not been OK by the end of the first drive" in _line(j, "T5"), j.lines


def test_a_drop_written_before_the_older_frames_reply_is_a_t6_fail_and_no_missing_reply_log(g1, tmp_path):
    """PR section 5: every frame line has its outcome, one per seq, in no order asked for. ctlclient.offer writes a replaced queued
    frame's drop line while an older frame's reply is outstanding, so the file can hold seq 12 before seq 11."""
    r = Rec(tmp_path / "r")
    for i, f in enumerate(r.frames, start=1):
        f["seq"] = i
    r.frames[10], r.frames[11] = r.frames[11], r.frames[10]
    r.frames[10]["outcome"] = "drop"
    r.summary["counters"]["drop"] = r.summary["identity"]["drop"] = 1
    j = _judge(g1, r)
    assert j.verdict == "FAIL" and _failed(j) == ["T6"], j.lines
    assert _inst(j, "reply-log").startswith("instrument reply-log OK") and not _missing(j), j.lines
    assert "reply-log" not in _line(j, "verdict:"), j.lines


def test_the_5_s_sampler_is_reported_with_its_rounds_and_its_largest_gap_and_gates_nothing(g1, tmp_path):
    """PR section 4: information only, and a gap in it is reported and is no instrument's failure."""
    r = Rec(tmp_path / "r")
    rounds = [r.first_container + k * 5 * S for k in range(4)] + [r.first_container + 27 * S]     # a gap of 12 s, then it stopped
    r.sampler = ([{"mono_ns": m, "wall_ns": 1, "what": "meminfo", "text": "MemAvailable: 1 kB"} for m in rounds]
                 + [{"mono_ns": m + 1, "wall_ns": 1, "what": "vmstat", "text": "oom_kill 0"} for m in rounds])
    j = _judge(g1, r)
    assert j.verdict == "PASS" and not _missing(j) and not _failed(j), j.lines
    line = next(x for x in j.lines if x.startswith("info the 5 s sampler"))
    assert "read by no item: 5 round(s), the largest gap between two 12.000 s" in line, line
    assert "the last round %.3f s before the loop's end" % ((r.loop_end - rounds[-1]) / S) in line, line
    r2 = Rec(tmp_path / "r2")
    r2.sampler = None
    j2 = _judge(g1, r2)
    assert j2.verdict == "PASS" and any(x == "info the 5 s sampler, read by no item: no round in the record" for x in j2.lines), j2.lines
    r3 = Rec(tmp_path / "r3")
    r3.sampler = [{"mono_ns": r3.first_container, "wall_ns": 1, "what": "meminfo"}, {"mono_ns": r3.loop_end + 3 * S, "wall_ns": 1, "what": "meminfo"}]
    j3 = _judge(g1, r3)
    assert j3.verdict == "PASS" and any(x.endswith(", the last round after the loop's end") for x in j3.lines), j3.lines


def test_a_frame_at_the_route_lines_own_time_is_outside_the_drive_and_one_at_its_last_line_is_inside(g1, tmp_path):
    """PR section 6: "after its `route` line ... and at or before its last line"."""
    base = _judge(g1, Rec(tmp_path / "a"))
    inside = int(re.search(r"info frames inside drive intervals: (\d+)", " ".join(base.lines)).group(1))
    r = Rec(tmp_path / "b")
    route, last = r.drives[1]["lines"][2]["mono_ns"], r.drives[1]["lines"][-1]["mono_ns"]
    for t in (route, last):
        k = next(i for i, f in enumerate(r.frames) if f["t"] > t)
        r.frames.insert(k, {"t": t, "outcome": "replied", "verdict": 0, "reason": 0})
    j = _judge(g1, r)
    assert "info frames outside every drive: 1" in j.lines and "info frames inside drive intervals: %d" % (inside + 1) in j.lines, j.lines


@pytest.mark.parametrize("late_ns, verdict", [(0, "PASS"), (1, "FAIL")])
def test_t5_a_status_ok_at_exactly_the_first_drives_last_line_holds_and_a_nanosecond_later_does_not(g1, tmp_path, late_ns, verdict):
    r = Rec(tmp_path / "r")
    end = r.drives[0]["lines"][-1]["mono_ns"]
    for x in r.diag:
        if x.get("name") in T5_LIST and x.get("level") == 0:
            x["mono_ns"] = end + late_ns
    j = _judge(g1, r)
    assert _line(j, "T5").startswith("T5 " + verdict), j.lines


@pytest.mark.parametrize("extra_ns, fails", [(0, False), (1, True)])
def test_t5_a_validator_unseen_for_exactly_10_s_is_no_fail_and_a_nanosecond_more_is(g1, tmp_path, extra_ns, fails):
    """PR section 7: "over 10 s"."""
    r = Rec(tmp_path / "r")
    for x in r.diag:
        if "last_seen" in x:
            x["last_seen"][VALIDATOR] = x["mono_ns"] - 10 * S - extra_ns
    j = _judge(g1, r)
    assert ("T5" in _failed(j)) is fails, j.lines
    assert fails or j.verdict == "PASS", j.lines


@pytest.mark.parametrize("extra_ns, ok", [(0, True), (1, False)])
def test_one_clock_offsets_exactly_1_s_apart_hold_and_a_nanosecond_more_do_not(g1, tmp_path, extra_ns, ok):
    """PR section 6: "their offsets within 1 s"."""
    r = Rec(tmp_path / "r")
    r.pairs["container"] = (501 * S, 1800000001 * S + S + extra_ns)
    j = _judge(g1, r)
    assert _inst(j, "one-clock").startswith("instrument one-clock OK") is ok, j.lines


@pytest.mark.parametrize("short_ns, verdict", [(0, "PASS"), (1, "FAIL")])
def test_t7_a_drive_ending_exactly_1200_s_after_the_first_route_reaches_it_and_a_nanosecond_short_does_not(g1, tmp_path, short_ns, verdict):
    """PR section 5: "the loop reached 1200 s"."""
    r = Rec(tmp_path / "r")
    r.drives[-1]["end"] = r.drives[0]["lines"][2]["mono_ns"] + 1200 * S - short_ns
    j = _judge(g1, r)
    assert _line(j, "T7").startswith("T7 " + verdict), j.lines


def test_a_series_gap_wholly_before_the_first_containers_start_is_no_gap(g1, tmp_path):
    """PR section 5: the series covers the span from the first container's start; a stretch before it is no part of the span."""
    r = Rec(tmp_path / "r")
    r.series = [x for x in r.series if not r.first_container - 20 * S < x[0] < r.first_container - 12 * S]
    j = _judge(g1, r)
    assert _inst(j, "series").startswith("instrument series OK"), j.lines


def test_a_console_holding_the_right_catalog_and_another_is_missing_the_rules_digest(g1, tmp_path):
    r = Rec(tmp_path / "r")
    r.console = "monitor: boot\n" + RULES_LINE % DIGEST + "\n" + RULES_LINE % "0x87654321" + "\n"
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and _missing(j) == ["rules-digest"], j.lines


# --- the watchdog ----------------------------------------------------------------------------------------------------------------

# --- PR's dated section of 2026-11-01: a reset's unequal tails (item 6), a status at STALE (item 7) -------------------------------------

def _reset_with_a_skewed_last_drive(r):
    """A reset whose tails came out unequal: the last drive's scenario.jsonl holds its arrive line, its replies stop 30 s after the route,
    and it has no `end` row. Its interval would hold far too few frames."""
    dr = r.drives[-1]
    dr["rc"] = None
    dr["lines"] = dr["lines"][:5]
    cut = dr["lines"][2]["mono_ns"] + 30 * S
    r.frames = [f for f in r.frames if f["t"] <= cut]
    r.summary = None
    r.vmstat_end = None
    r.mem_events = None
    r.hc_after = None
    r.series = [x for x in r.series if x[0] <= dr["lines"][-1]["mono_ns"]]
    for k in ("loop_end", "loop_end_mono_ns", "last_stop_mono_ns", "harness_end"):
        r.arm.pop(k)


RESET_WORD = "a hang, the owner's word"


def test_a_reset_with_a_skewed_last_drive_names_the_reset_alone_and_t4_reads_the_ended_drives(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=3)
    ended = len(r.frames_of(r.drives[0])) + len(r.frames_of(r.drives[1]))
    _reset_with_a_skewed_last_drive(r)
    j = _judge(g1, r, reset=RESET_WORD)
    assert j.verdict == "FAIL" and _failed(j) == [], j.lines
    assert j.reasons == ["a reset, a hang or an oops during the arm, cause not assigned: " + RESET_WORD], j.reasons
    assert _line(j, "T4").startswith("T4 PASS") and "%d frames" % ended in _line(j, "T4"), j.lines
    assert _line(j, "T4w").startswith("T4w PASS"), j.lines
    assert " also " not in _line(j, "verdict:"), j.lines
    assert j.lines[-1].startswith("re-run: allowed"), j.lines


def test_the_same_skewed_files_without_the_resets_word_read_as_before(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=3)
    _reset_with_a_skewed_last_drive(r)
    j = _judge(g1, r)
    assert {"T4", "T4w"} <= set(_failed(j)) and j.verdict == "FAIL", j.lines
    assert j.lines[-1].startswith("re-run: none"), j.lines
    assert not any("no end row" in x for x in j.lines), j.lines


def test_a_drive_with_no_end_row_under_a_reset_keeps_its_frames_in_the_information_lines_and_gives_no_window(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=3)
    a, b = r.drives[2]["lines"][2]["mono_ns"], r.drives[2]["lines"][2]["mono_ns"] + 30 * S
    n = len([f for f in r.frames if a < f["t"] <= b])
    _reset_with_a_skewed_last_drive(r)
    j = _judge(g1, r, reset=RESET_WORD)
    line = next(x for x in j.lines if x.startswith("info drive d003:"))
    assert "no end row" in line and "%d frames" % n in line, j.lines
    assert not any(w[0] == "d003" for w in j.windows), j.windows
    assert any(w[0] == "d002" for w in j.windows), j.windows
    assert any(x.startswith("info frames of drives with no end row under the reset: %d" % n) for x in j.lines), j.lines


def _validator_unseen_from(r, limit):
    for x in r.diag:
        if "last_seen" in x and x["mono_ns"] > limit:
            x["last_seen"][VALIDATOR] = limit


def test_a_validator_unseen_in_a_drive_with_no_end_row_is_no_t5_fail_under_a_reset_and_is_one_without_it(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=3)
    _validator_unseen_from(r, r.drives[2]["begin"])
    _reset_with_a_skewed_last_drive(r)
    j = _judge(g1, r, reset=RESET_WORD)
    assert _line(j, "T5").startswith("T5 PASS") and _failed(j) == [], j.lines
    assert "a silent validator" in _line(_judge(g1, r.d), "T5"), j.lines


def test_a_validator_unseen_in_a_drive_that_ended_still_fails_t5_under_a_reset_and_forbids_the_re_run(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=3)
    _validator_unseen_from(r, r.drives[1]["begin"])
    _reset_with_a_skewed_last_drive(r)
    j = _judge(g1, r, reset=RESET_WORD)
    assert _failed(j) == ["T5"] and "a silent validator in d002" in _line(j, "T5"), j.lines
    assert j.lines[-1].startswith("re-run: none"), j.lines


def _stale(r, name, t):
    r.diag.append({"mono_ns": t, "first": False, "name": name, "hardware_id": "x", "level": 3, "message": "Stale"})


def test_a_listed_status_at_stale_after_ok_is_no_t5_fail_and_t5s_line_names_it(g1, tmp_path):
    r = Rec(tmp_path / "r")
    _stale(r, T5_LIST[2], r.drives[1]["begin"])
    j = _judge(g1, r)
    assert j.verdict == "PASS" and _line(j, "T5").startswith("T5 PASS"), j.lines
    line = _line(j, "T5")
    assert "STALE" in line and T5_LIST[2] in line and T5_LIST[0] not in line, line


def test_a_listed_status_at_error_beside_one_at_stale_fails_t5_naming_both(g1, tmp_path):
    r = Rec(tmp_path / "r")
    _t5_error(r)                                    # T5_LIST[2] at ERROR
    _stale(r, T5_LIST[0], r.drives[1]["begin"])
    j = _judge(g1, r)
    assert _failed(j) == ["T5"], j.lines
    line = _line(j, "T5")
    assert "%s reached ERROR" % T5_LIST[2] in line and "STALE" in line and T5_LIST[0] in line, line


def test_two_listed_statuses_at_stale_are_both_named_on_t5s_line(g1, tmp_path):
    """PR's dated section, item 7: every listed status that reached STALE is named on T5's line, not the first of them alone."""
    r = Rec(tmp_path / "r")
    _stale(r, T5_LIST[0], r.drives[1]["begin"])
    _stale(r, T5_LIST[2], r.drives[1]["begin"])
    j = _judge(g1, r)
    line = _line(j, "T5")
    assert j.verdict == "PASS" and line.startswith("T5 PASS"), j.lines
    assert T5_LIST[0] in line and T5_LIST[2] in line and T5_LIST[1] not in line, line


def test_a_status_off_the_list_at_stale_is_not_named_on_t5s_line(g1, tmp_path):
    r = Rec(tmp_path / "r")
    _stale(r, "vehicle_cmd_gate: heartbeat", r.drives[1]["begin"])
    j = _judge(g1, r)
    assert "STALE" not in _line(j, "T5") and j.verdict == "PASS", j.lines


def test_the_judge_and_the_harness_cite_prs_dated_section_where_a_finding_stood():
    with open(TOOL, encoding="utf-8") as f:
        tool = f.read()
    with open(HARNESS, encoding="utf-8") as f:
        harness = f.read()
    assert "FINDING" not in tool and "FINDING" not in harness
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 13):
        assert "PR's dated section, item %d" % n in tool, n
    assert harness.count("PR's dated section, item 2") >= 3


# --- readings of PR held by name: the route's outcome, the silent validator's span and names, T7's arrive,
# --- a reset's one reason, a harness that died after the loop's end ---------------------------------------------------------------------

def _route_line(dr):
    return next(x for x in dr["lines"] if x["step"] == "route")


def _extra_line(r, m, ago):
    """A 5 s line of the recorder at m: every status of the good record seen now, and the names in AGO (name -> seconds before m) seen that
    long ago instead. A line is added and the others stay."""
    seen = {n: m for n in T5_LIST}
    seen["vehicle_cmd_gate: heartbeat"] = m
    seen.update({n: m - s * S for n, s in ago.items()})
    r.diag.append({"mono_ns": m, "last_seen": seen, "values": {}})


def test_a_route_line_of_outcome_timeout_is_no_route_so_its_drive_has_no_interval_and_t7_fails(g1, tmp_path):
    """PR sections 4 and 6: the route is the `route` line of outcome done. This drive ran on to its arrive and its clear and exited 0, and its
    frames are kept; the outcome of its route line alone is not done, so no frame is after a route and it has no interval."""
    r = Rec(tmp_path / "r")
    dr = r.drives[2]
    _route_line(dr)["outcome"] = "timeout"
    assert dr["rc"] == 0 and any(f["t"] > _route_line(dr)["mono_ns"] and f["t"] <= dr["lines"][-1]["mono_ns"] for f in r.frames)
    j = _judge(g1, r)
    assert _failed(j) == ["T7"], j.lines
    assert "d003 has no route line of outcome done" in _line(j, "T7"), j.lines
    assert any(x.startswith("info drive d003: no interval") for x in j.lines), j.lines


def test_first_route_exits_1_on_a_route_line_of_outcome_timeout_and_prints_the_done_ones_time(g1, tmp_path, capsys):
    lines = Rec.drive(1000 * S)["lines"]
    p = tmp_path / "scenario.jsonl"
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    assert g1.main(["first-route", "--file", str(p)]) == 0
    assert capsys.readouterr().out == "%d\n" % (1000 * S + S // 2)
    _route_line({"lines": lines})["outcome"] = "timeout"
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    assert g1.main(["first-route", "--file", str(p)]) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("offset_ns, fails", [(S, False), (S + S // 2, True)], ids=["between-the-route-and-the-first-frame", "at-the-first-frame"])
def test_t5_s_silent_validator_span_begins_at_the_drives_first_frame_and_not_at_its_route_line(g1, tmp_path, offset_ns, fails):
    """PR's dated section, item 3: the span is the drive's interval (section 6), so the wait from SET to the first Control is outside it. In
    the good record d002's route line is 0.5 s after its begin and its first frame 1 s after the route line. A validator unseen over
    10 s with the recorder seeing other names, at a 5 s line between the two, is no T5 fail; the same line at the first frame's own time is."""
    r = Rec(tmp_path / "r")
    dr = r.drives[1]
    m = dr["begin"] + offset_ns
    first = min(f["t"] for f in r.frames if f["t"] > _route_line(dr)["mono_ns"])
    assert _route_line(dr)["mono_ns"] < m <= first and (m == first) is fails, (m, first)
    _extra_line(r, m, {VALIDATOR: 60})
    j = _judge(g1, r)
    assert ("T5" in _failed(j)) is fails, j.lines
    if fails:
        assert "a silent validator in d002: %s unseen for over 10 s" % VALIDATOR in _line(j, "T5"), j.lines
    else:
        assert j.verdict == "PASS", j.lines


OTHER_VALIDATOR = "control_validator: another_status"


@pytest.mark.parametrize("ago_s, fails", [(0, False), (60, True)], ids=["both-seen-now", "one-unseen-over-10-s"])
def test_t5_reads_each_name_of_the_validator_and_not_the_newest_of_them(g1, tmp_path, ago_s, fails):
    """PR's dated section, item 3: "any `control_validator` status" is each of the validator's names. Two names at a 5 s line inside d002,
    one seen now, the other seen ago_s before it, the recorder seeing other names."""
    r = Rec(tmp_path / "r")
    _extra_line(r, r.drives[1]["begin"] + 100 * S + 7, {VALIDATOR: 0, OTHER_VALIDATOR: ago_s})
    j = _judge(g1, r)
    assert ("T5" in _failed(j)) is fails, j.lines
    if fails:
        assert "a silent validator in d002: %s unseen for over 10 s" % OTHER_VALIDATOR in _line(j, "T5"), j.lines
        assert _failed(j) == ["T5"], j.lines
    else:
        assert j.verdict == "PASS", j.lines


@pytest.mark.parametrize("others_ago_s, fails", [(60, False), (0, True), (10, True), (11, False)],
                         ids=["no-name-but-the-validators-seen", "another-name-seen-now", "another-name-seen-exactly-10-s-before",
                              "another-name-seen-11-s-before"])
def test_t5_s_silent_validator_needs_a_name_not_of_the_validators_seen_within_10_s(g1, tmp_path, others_ago_s, fails):
    """PR's dated section, item 3: "still seeing other names" is some name not of the validator's seen within 10 s of the line. At a 5 s line
    inside d002 one validator name is unseen for 60 s and another is seen now; every name not of the validator's was last seen others_ago_s
    before the line, and one seen exactly 10 s before it is seen within 10 s. The validator's own second name is no other name, so with none
    else seen within 10 s the recorder is not read as seeing and the line is no T5 fail."""
    r = Rec(tmp_path / "r")
    ago = {n: others_ago_s for n in T5_LIST}
    ago.update({"vehicle_cmd_gate: heartbeat": others_ago_s, VALIDATOR: 60, OTHER_VALIDATOR: 0})
    _extra_line(r, r.drives[1]["begin"] + 100 * S + 7, ago)
    j = _judge(g1, r)
    assert ("T5" in _failed(j)) is fails, j.lines
    if fails:
        assert "a silent validator in d002: %s unseen for over 10 s" % VALIDATOR in _line(j, "T5"), j.lines
    else:
        assert j.verdict == "PASS" and _line(j, "T5").startswith("T5 PASS"), j.lines


def _only_5s_line_near_the_last_drives_end(r, offset_ns, ago=None):
    """Every 5 s line within 30 s of the last drive's last line is taken out and one put back OFFSET_NS from it (negative: before it), every
    status seen now but those in AGO (name -> seconds before the line). The other drives' lines stay."""
    end = r.drives[-1]["lines"][-1]["mono_ns"]
    r.diag = [x for x in r.diag if "last_seen" not in x or abs(x["mono_ns"] - end) > 30 * S]
    _extra_line(r, end + offset_ns, {VALIDATOR: 0} if ago is None else ago)


@pytest.mark.parametrize("side", [1, -1], ids=["after-the-end", "before-the-end"])
def test_the_positive_control_counts_a_5_s_line_10_s_from_a_drives_end_on_either_side(g1, tmp_path, side):
    """PR's dated section, item 4: "at the end of every drive" is a 5 s line within 10 s of the drive's end, on either side, some name of it
    seen within 10 s of that line. The only such line of the last drive is exactly 10 s from its end."""
    r = Rec(tmp_path / "r")
    _only_5s_line_near_the_last_drives_end(r, side * 10 * S)
    j = _judge(g1, r)
    assert _inst(j, "positive-control").startswith("instrument positive-control OK"), j.lines
    assert j.verdict == "PASS" and _missing(j) == [], j.lines


@pytest.mark.parametrize("side", [1, -1], ids=["after-the-end", "before-the-end"])
def test_the_positive_control_does_not_count_a_5_s_line_11_s_from_a_drives_end(g1, tmp_path, side):
    """PR's dated section, item 4: the only 5 s line of the last drive is 11 s from its end, one second past the bound, so the recorder is
    not read as seeing at that drive's end and the positive control is missing."""
    r = Rec(tmp_path / "r")
    _only_5s_line_near_the_last_drives_end(r, side * 11 * S)
    j = _judge(g1, r)
    assert _missing(j) == ["positive-control"] and j.verdict == "NOT JUDGED", j.lines
    assert "the recorder saw no name at the end of d004" in _inst(j, "positive-control"), j.lines


@pytest.mark.parametrize("ago_s, seeing", [(10, True), (11, False)],
                         ids=["every-name-seen-exactly-10-s-before-the-line", "every-name-seen-11-s-before-the-line"])
def test_the_positive_control_counts_a_name_seen_within_10_s_of_the_5_s_line_and_10_s_is_within(g1, tmp_path, ago_s, seeing):
    """PR's dated section, item 4: "some name of it seen within 10 s of that line". The only 5 s line of the last drive is 2 s after its end,
    and every status in it was last seen ago_s before it."""
    r = Rec(tmp_path / "r")
    names = list(T5_LIST) + ["vehicle_cmd_gate: heartbeat", VALIDATOR]
    _only_5s_line_near_the_last_drives_end(r, 2 * S, {n: ago_s for n in names})
    j = _judge(g1, r)
    if seeing:
        assert _inst(j, "positive-control").startswith("instrument positive-control OK"), j.lines
        assert j.verdict == "PASS" and _missing(j) == [], j.lines
    else:
        assert _missing(j) == ["positive-control"] and j.verdict == "NOT JUDGED", j.lines
        assert "the recorder saw no name at the end of d004" in _inst(j, "positive-control"), j.lines


def test_t7_reads_the_arrive_lines_outcome_and_not_that_the_line_is_there(g1, tmp_path):
    """PR section 5, T7: each drive exits 0, is at the goal and has cleared its route. This one exited 0 and cleared its route, and its arrive
    line is there, of outcome timeout."""
    r = Rec(tmp_path / "r")
    dr = r.drives[1]
    dr["lines"][4]["outcome"] = "timeout"
    assert dr["rc"] == 0 and dr["lines"][4]["step"] == "arrive"
    assert dr["lines"][5]["step"] == "clear" and dr["lines"][5]["outcome"] == "done"
    j = _judge(g1, r)
    assert _failed(j) == ["T7"], j.lines
    assert "d002 did not arrive at the goal" in _line(j, "T7"), j.lines


def test_a_reset_beside_a_missing_instrument_gives_the_verdict_line_the_reset_alone(g1, tmp_path):
    """PR section 5: the readings a reset prevented are not readings, and its one failing reason is the reset; an instrument that is missing
    in such a record is not a second reason."""
    r = Rec(tmp_path / "r", drives=2)
    _reset_record(r)
    _no_stamp(r)
    j = _judge(g1, r, reset="a hang, the owner's word")
    assert j.verdict == "FAIL" and _failed(j) == [] and "stamp" in _missing(j), j.lines
    assert _line(j, "verdict:") == "verdict: FAIL: a reset, a hang or an oops during the arm, cause not assigned: a hang, the owner's word", j.lines
    assert " also " not in _line(j, "verdict:") and len(j.reasons) == 1, j.lines


def test_a_harness_that_died_after_the_loops_end_with_no_status_line_is_not_judged_and_under_a_reset_names_the_reset_alone(g1, tmp_path):
    """The loop reached its end and the arm.tsv has no harness_end: the harness died between the two. A PASS there would be a verdict
    on a record whose tail is unknown."""
    r = Rec(tmp_path / "r")
    del r.arm["harness_end"]
    assert r.arm["loop_end"] == "reached"
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and _failed(j) == [], j.lines
    assert "the harness exited after the loop's end with no status line" in _line(j, "verdict:"), j.lines
    assert j.lines[-1].startswith("re-run: allowed"), j.lines
    j = _judge(g1, r.d, reset="a hang, the owner's word")
    assert j.verdict == "FAIL" and _failed(j) == [], j.lines
    assert j.reasons == ["a reset, a hang or an oops during the arm, cause not assigned: a hang, the owner's word"], j.reasons
    assert " also " not in _line(j, "verdict:") and "no status line" not in _line(j, "verdict:"), j.lines


_WD_DOCKER = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WD/docker.log"
[ ! -e "$WD/docker-dead" ] || exit 1
[ ! -e "$WD/docker-hangs" ] || exec sleep 60
case "$1" in
	ps) [ ! -s "$WD/running" ] || cat "$WD/running" ;;
	kill) shift; for i in "$@"; do sed -i "/^$i\$/d" "$WD/running"; done ;;
esac
'''
_WD_SUDO = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WD/sudo.log"
[ "$1" = -n ] || exit 1
shift
exec "$@"
'''


class Dog:
    def __init__(self, base, avail=2000000, **env):
        self.d = base
        self.bin = base / "bin"
        self.bin.mkdir(parents=True)
        for n, b in (("docker", _WD_DOCKER), ("sudo", _WD_SUDO)):
            p = self.bin / n
            p.write_text(b, newline="\n")
            p.chmod(0o755)
        self.meminfo = base / "meminfo"
        self.set_avail(avail)
        self.series, self.stop, self.scopes = base / "series", base / "stop", base / "scopes"
        self.scopes.write_text("")
        (base / "running").write_text("")
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"], WD=str(base),
                        QNX_MEMINFO_FILE=str(self.meminfo), PYTHONDONTWRITEBYTECODE="1")
        self.env.pop("VSS_HOST", None)
        self.env.pop("G1_REHEARSAL_FLOOR_KB", None)
        self.env.update(env)
        self.p = None

    def set_avail(self, kb):
        tmp = self.meminfo.parent / "meminfo.tmp"
        tmp.write_text("MemTotal:  8000000 kB\nMemAvailable:  %d kB\n" % kb)
        with open(str(self.meminfo), "w") as f:
            f.write(tmp.read_text())

    def args(self, *extra, max_s="30"):
        return [sys.executable, "-B", WATCHDOG, "--series", str(self.series), "--stop-file", str(self.stop), "--scopes",
                str(self.scopes), "--max-s", max_s, "--spacing-s", "0.05", "--cgroup-kill-after-s", "0.3", *extra]

    def start(self, *extra):
        self.p = subprocess.Popen(self.args(*extra), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return self

    def end(self):
        if self.p is not None:
            self.p.terminate()
            self.p.communicate(timeout=10)

    def wait_for(self, what, s=15):
        end = time.time() + s
        while time.time() < end:
            if what():
                return True
            time.sleep(0.02)
        return False

    def lines(self):
        return self.series.read_text().splitlines() if self.series.exists() else []

    def docker(self):
        p = self.d / "docker.log"
        return p.read_text().splitlines() if p.exists() else []


@linux_only
def test_the_watchdog_writes_one_line_per_read_with_both_clocks_and_memavailable(tmp_path):
    dog = Dog(tmp_path).start()
    try:
        assert dog.wait_for(lambda: len(dog.lines()) >= 5)
    finally:
        dog.end()
    rows = [x.split() for x in dog.lines() if x.startswith("R ")]
    assert rows and all(len(r) == 4 and r[3] == "2000000" and int(r[1]) > 0 and int(r[2]) > 10 ** 18 for r in rows)
    assert int(rows[1][1]) > int(rows[0][1])
    assert not dog.stop.exists() and not dog.docker()


@linux_only
def test_the_watchdog_fires_on_a_stand_in_series_and_kills_by_label(tmp_path):
    dog = Dog(tmp_path)
    (tmp_path / "running").write_text("id1\nid2\n")
    dog.start()
    try:
        assert dog.wait_for(lambda: len(dog.lines()) >= 3)
        assert not dog.stop.exists()
        dog.set_avail(716799)
        assert dog.wait_for(lambda: "kill id1 id2" in dog.docker() or ("kill id1" in dog.docker() and "kill id2" in dog.docker()))
        assert dog.stop.exists()
    finally:
        dog.end()
    assert any(x.startswith("ps ") and "label=sdv.aw.run=g1" in x for x in dog.docker()), dog.docker()
    assert any(x.startswith("E ") and " stop " in x and "floor_kb=716800" in x and "avail_kb=716799" in x for x in dog.lines())


@linux_only
def test_the_watchdog_does_not_fire_at_the_floor_itself(tmp_path):
    dog = Dog(tmp_path, avail=716800).start()
    try:
        assert dog.wait_for(lambda: len(dog.lines()) >= 5)
    finally:
        dog.end()
    assert not dog.stop.exists()


@linux_only
def test_the_watchdog_keeps_killing_a_container_started_after_its_first_kill(tmp_path):
    dog = Dog(tmp_path)
    (tmp_path / "running").write_text("id1\n")
    dog.start()
    try:
        assert dog.wait_for(lambda: len(dog.lines()) >= 2)
        dog.set_avail(1000)
        assert dog.wait_for(lambda: "kill id1" in dog.docker())
        assert dog.wait_for(lambda: not (tmp_path / "running").read_text())
        time.sleep(0.2)
        (tmp_path / "running").write_text("id9\n")
        assert dog.wait_for(lambda: "kill id9" in dog.docker()), dog.docker()
    finally:
        dog.end()


@linux_only
def test_the_watchdog_writes_cgroup_kill_through_sudo_only_after_its_wait_and_only_where_a_scope_exists(tmp_path):
    dog = Dog(tmp_path)
    scope = tmp_path / "cg" / "system.slice" / "docker-a.scope"
    scope.mkdir(parents=True)
    (scope / "cgroup.kill").write_text("")
    gone = tmp_path / "cg" / "gone.scope"
    dog.scopes.write_text("aw-sim\t%s\naw-gone\t%s\n" % (scope, gone))
    (tmp_path / "docker-dead").write_text("")      # dockerd sits on the same saturated cores and does not answer
    dog.start()
    try:
        assert dog.wait_for(lambda: len(dog.lines()) >= 2)
        dog.set_avail(1000)
        assert dog.wait_for(lambda: (scope / "cgroup.kill").read_text().strip() == "1")
    finally:
        dog.end()
    sudo_log = (tmp_path / "sudo.log").read_text().splitlines()
    assert any("tee %s" % (scope / "cgroup.kill") in x for x in sudo_log)
    ev = [x.split() for x in dog.lines() if x.startswith("E ")]
    stop = next(int(x[1]) for x in ev if x[3] == "stop")
    kill = next(int(x[1]) for x in ev if x[3] == "cgroup-kill")
    assert kill - stop >= 3 * 10 ** 8
    assert not gone.exists()
    assert not any(str(gone) in x for x in sudo_log), "a scope that no longer exists is never written (its tee could only fail)"


@linux_only
def test_a_docker_that_hangs_delays_no_cgroup_kill(tmp_path):
    """Design values: the cgroup path exists for the dockerd that does not answer, so its first write comes CGROUP_KILL_AFTER_S after the
    stop, whatever a `docker ps` under its 10 s bound is doing."""
    dog = Dog(tmp_path)
    scope = tmp_path / "cg" / "docker-a.scope"
    scope.mkdir(parents=True)
    (scope / "cgroup.kill").write_text("")
    dog.scopes.write_text("aw-sim\t%s\n" % scope)
    (tmp_path / "docker-hangs").write_text("")
    dog.start("--cgroup-kill-after-s", "5", "--spacing-s", "1")
    try:
        assert dog.wait_for(lambda: len(dog.lines()) >= 2)
        dog.set_avail(1000)
        assert dog.wait_for(lambda: (scope / "cgroup.kill").read_text().strip() == "1", s=25)
        assert dog.wait_for(lambda: any(" cgroup-kill " in x for x in dog.lines()), s=5)
    finally:
        dog.end()
    ev = [x.split() for x in dog.lines() if x.startswith("E ")]
    stop = next(int(x[1]) for x in ev if x[3] == "stop")
    kill = next(int(x[1]) for x in ev if x[3] == "cgroup-kill")
    assert 5 * S <= kill - stop <= 7 * S, (kill - stop) / S


@linux_only
def test_a_docker_that_hangs_leaves_the_series_going_and_the_end_bounded(tmp_path):
    dog = Dog(tmp_path)
    (tmp_path / "docker-hangs").write_text("")
    dog.start()
    try:
        assert dog.wait_for(lambda: len(dog.lines()) >= 2)
        dog.set_avail(1000)
        assert dog.wait_for(lambda: dog.stop.exists())
        n = len([x for x in dog.lines() if x.startswith("R ")])
        assert dog.wait_for(lambda: len([x for x in dog.lines() if x.startswith("R ")]) > n + 3)
        t0 = time.time()
    finally:
        dog.end()
    assert time.time() - t0 < 6 and dog.p.returncode == 0
    assert dog.lines()[-1].split()[3] == "end"


@linux_only
def test_the_watchdogs_series_keeps_its_spacing_after_a_fire_as_before_it(tmp_path):
    """PR section 4: one line per spacing (here 0.1 s) for as long as the watchdog runs. The kill threads take nothing from the series and the
    stop does not change its pace. The watchdog keeps an absolute schedule, so the k-th line cannot come before the start + k spacings
    whatever a stall did, and a stall is followed by a burst: the mean gap from the start over both stretches is read, and a series that
    sped up after the fire is the one that would fall under the spacing."""
    dog = Dog(tmp_path)
    (tmp_path / "running").write_text("id1\n")
    t0 = time.monotonic_ns()
    dog.start("--spacing-s", "0.1")

    def stamps(kb):
        return [int(c[1]) for c in (x.split() for x in dog.lines() if x.startswith("R ")) if len(c) == 4 and c[3] == kb]

    try:
        assert dog.wait_for(lambda: len(stamps("2000000")) >= 15)
        dog.set_avail(1000)
        assert dog.wait_for(lambda: len(stamps("1000")) >= 15)
    finally:
        dog.end()
    t = stamps("2000000") + stamps("1000")
    assert (t[-1] - t0) / (len(t) - 1) >= 0.08 * S, (t[-1] - t0) / (len(t) - 1) / S


@linux_only
def test_the_watchdog_holds_meminfo_open(tmp_path):
    dog = Dog(tmp_path).start()
    try:
        assert dog.wait_for(lambda: len(dog.lines()) >= 2)
        dog.meminfo.unlink()
        n = len(dog.lines())
        assert dog.wait_for(lambda: len(dog.lines()) >= n + 5)
    finally:
        dog.end()
    assert all(x.split()[3] == "2000000" for x in dog.lines() if x.startswith("R "))


@linux_only
@pytest.mark.parametrize("floor", ["1048576", "1048577", "2000000"])
def test_the_watchdog_refuses_a_floor_at_or_above_t3s_threshold(tmp_path, floor):
    dog = Dog(tmp_path)
    # --max-s 2: a watchdog that does not refuse runs its 2 s and exits 0, so the returncode below fails at once (it was a 30 s timeout)
    r = subprocess.run(dog.args("--floor-kb", floor, max_s="2"), env=dog.env, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "floor" in r.stderr, r.stderr
    assert not dog.series.exists() and not dog.stop.exists()


@linux_only
def test_the_watchdog_takes_a_floor_just_under_the_threshold(tmp_path):
    dog = Dog(tmp_path).start("--floor-kb", "1048575")
    try:
        assert dog.wait_for(lambda: len(dog.lines()) >= 2)
    finally:
        dog.end()


@linux_only
def test_the_rehearsal_override_lifts_the_refusal_except_under_the_orin(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    dog = Dog(a, avail=3000000, G1_REHEARSAL_FLOOR_KB="4000000", VSS_HOST="c7g-metal").start()
    try:
        assert dog.wait_for(lambda: dog.stop.exists())
    finally:
        dog.end()
    assert any("floor_kb=4000000" in x for x in dog.lines())
    b = tmp_path / "b"
    b.mkdir()
    dog = Dog(b, G1_REHEARSAL_FLOOR_KB="4000000", VSS_HOST="orin")
    r = subprocess.run(dog.args(max_s="2"), env=dog.env, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "orin" in r.stderr, r.stderr
    assert not dog.series.exists()
    c = tmp_path / "c"
    c.mkdir()
    dog = Dog(c, G1_REHEARSAL_FLOOR_KB="not-a-number", VSS_HOST="c7g-metal")
    r = subprocess.run(dog.args(max_s="2"), env=dog.env, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "G1_REHEARSAL_FLOOR_KB" in r.stderr, r.stderr


def test_the_watchdog_floor_and_threshold_are_the_design_values():
    wd = _load(WATCHDOG, "g1_watchdog")
    assert wd.FLOOR_KB == 716800 and wd.T3_THRESHOLD_KB == 1048576 and wd.SPACING_S == 1.0 and wd.CGROUP_KILL_AFTER_S == 5.0
    assert wd.FSYNC_EVERY == 10 and wd.LABEL == "sdv.aw.run=g1"


def test_the_watchdog_flushes_each_line_and_fsyncs_every_10(tmp_path, monkeypatch):
    wd = _load(WATCHDOG, "g1_watchdog")
    calls = []
    monkeypatch.setattr(wd.os, "fsync", lambda fd: calls.append(fd))
    s = wd.Series(str(tmp_path / "s"))
    for i in range(25):
        s.reading(i, i, 5)
        assert (tmp_path / "s").read_text().count("\n") == i + 1
    assert len(calls) == 2
    s.event(1, 1, "stop", "x")
    assert len(calls) == 3
    s.close()


def test_the_watchdog_imports_the_standard_library_only():
    assert _stdlib_only(WATCHDOG) and _stdlib_only(SAMPLER)


def _stdlib_only(path):
    import ast
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names.add((n.module or "").split(".")[0])
    return names <= {"__future__", "argparse", "json", "os", "signal", "subprocess", "sys", "threading", "time", "typing"}


# --- the 5 s sampler -------------------------------------------------------------------------------------------------------------

@linux_only
def test_the_sampler_writes_each_read_with_its_own_time_and_survives_a_dead_docker(tmp_path):
    b = tmp_path / "bin"
    b.mkdir()
    dk = b / "docker"
    dk.write_text('#!/usr/bin/env bash\n[ ! -e "$WD/docker-dead" ] || exit 1\necho "aw-sim\t12.5%%\t1GiB / 3GiB"\n', newline="\n")
    dk.chmod(0o755)
    for n, text in (("meminfo", "MemAvailable: 5 kB\nCached: 6 kB\n"), ("vmstat", "oom_kill 0\n"), ("stat", "cpu0 1 2 3\ncpu1 4 5 6\n")):
        (tmp_path / n).write_text(text)
    scope = tmp_path / "scope"
    scope.mkdir()
    (scope / "memory.events").write_text("low 0\noom_kill 0\n")
    scopes = tmp_path / "scopes"
    scopes.write_text("aw-sim\t%s\naw-gone\t%s\n" % (scope, tmp_path / "gone"))
    out = tmp_path / "out.jsonl"
    env = dict(os.environ, PATH=str(b) + os.pathsep + os.environ["PATH"], WD=str(tmp_path), QNX_MEMINFO_FILE=str(tmp_path / "meminfo"),
               QNX_VMSTAT_FILE=str(tmp_path / "vmstat"), QNX_STAT_FILE=str(tmp_path / "stat"), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.Popen([sys.executable, "-B", SAMPLER, "--out", str(out), "--scopes", str(scopes), "--max-s", "20", "--spacing-s", "0.05"],
                         env=env)
    try:
        deadline = time.time() + 15
        while time.time() < deadline and (not out.exists() or out.read_text().count("docker_stats") < 2):
            time.sleep(0.02)
        (tmp_path / "docker-dead").write_text("")
        n = out.read_text().count("\n")
        while time.time() < deadline and out.read_text().count("\n") < n + 8:
            time.sleep(0.02)
    finally:
        p.terminate()
        p.wait(timeout=10)
    docs = [json.loads(x) for x in out.read_text().splitlines()]
    whats = {d["what"] for d in docs}
    assert whats >= {"meminfo", "vmstat", "stat", "docker_stats", "memory_events"}, whats
    assert all(d["mono_ns"] > 0 and d["wall_ns"] > 0 for d in docs)
    ev = [d for d in docs if d["what"] == "memory_events"]
    assert {d["name"] for d in ev} == {"aw-sim"} and "oom_kill" in ev[0]["text"]
    assert any(d["what"] == "docker_stats" and d.get("exit") not in (0, None) for d in docs), "a dead docker is recorded"


def test_the_sampler_spacing_is_the_design_value():
    s = _load(SAMPLER, "g1_sampler")
    assert s.SPACING_S == 5.0


def test_the_sampler_bounds_its_docker_stats_call(monkeypatch):
    """A wedged dockerd delays the next read and stops nothing: `docker stats` runs under DOCKER_BOUND_S, and a timeout is recorded."""
    s = _load(SAMPLER, "g1_sampler")
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))

    monkeypatch.setattr(s.subprocess, "run", fake_run)
    got = s.docker_stats()
    assert "timeout" in seen and seen["timeout"] == s.DOCKER_BOUND_S and 0 < s.DOCKER_BOUND_S <= 30, seen
    assert got == {"exit": None, "error": "TimeoutExpired"}


# --- the two recorders, against a stand-in rclpy ----------------------------------------------------------------------------------

class _Status:
    def __init__(self, name, level, values=(), hardware_id="hw", message="m"):
        self.name, self.level, self.hardware_id, self.message = name, level, hardware_id, message
        self.values = [types.SimpleNamespace(key=k, value=v) for k, v in values]


def _fake_ros(monkeypatch, feed, qos_seen):
    """A stand-in rclpy and message packages: spin_once runs feed(callback) once, then SIGTERMs this process."""
    state = {"cb": None, "done": False}

    class Node:
        def __init__(self, name):
            state["name"] = name

        def create_subscription(self, typ, topic, cb, qos):
            state["cb"], state["topic"] = cb, topic
            qos_seen.append((typ, topic, qos))

        def destroy_node(self):
            pass

    def spin_once(node, timeout_sec=None):
        if not state["done"]:
            state["done"] = True
            feed(state["cb"])
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(0)

    rclpy = types.ModuleType("rclpy")
    rclpy.init = lambda *a, **k: None
    rclpy.ok = lambda: True
    rclpy.spin_once = spin_once
    rclpy.try_shutdown = lambda: None
    node_mod = types.ModuleType("rclpy.node")
    node_mod.Node = Node
    qos_mod = types.ModuleType("rclpy.qos")

    class QoSProfile:
        def __init__(self, depth=None, history=None, reliability=None, durability=None):
            self.depth, self.history, self.reliability, self.durability = depth, history, reliability, durability

    qos_mod.QoSProfile = QoSProfile
    qos_mod.ReliabilityPolicy = types.SimpleNamespace(RELIABLE="RELIABLE")
    qos_mod.HistoryPolicy = types.SimpleNamespace(KEEP_LAST="KEEP_LAST")
    qos_mod.DurabilityPolicy = types.SimpleNamespace(VOLATILE="VOLATILE")
    diag_msg = types.ModuleType("diagnostic_msgs.msg")
    diag_msg.DiagnosticArray = "DiagnosticArray"
    ctl_msg = types.ModuleType("autoware_control_msgs.msg")
    ctl_msg.Control = "Control"
    for n, m in (("rclpy", rclpy), ("rclpy.node", node_mod), ("rclpy.qos", qos_mod), ("diagnostic_msgs", types.ModuleType("diagnostic_msgs")),
                 ("diagnostic_msgs.msg", diag_msg), ("autoware_control_msgs", types.ModuleType("autoware_control_msgs")),
                 ("autoware_control_msgs.msg", ctl_msg)):
        monkeypatch.setitem(sys.modules, n, m)
    return state


def test_the_diag_recorder_writes_first_observations_changes_and_the_5_s_line(tmp_path):
    d = _load(DIAG, "aw_g1_diag")
    p = tmp_path / "diag.jsonl"
    with open(str(p), "w", encoding="utf-8") as f:
        rec = d.Recorder(f.write)
        rec.seen(1000, [_Status("a: x", 2), _Status(T5_LIST[0], 2, values=[("status", "Timeout"), ("measured_rate", "1.00 [Hz]")])])
        rec.seen(2000, [_Status("a: x", 2)])                      # no change of level: no line
        rec.seen(3000, [_Status("a: x", b"\x00")])                # a level as a byte, as the message carries it
        assert rec.tick(4000) is False                            # not yet 5 s
        assert rec.tick(1000 + 5 * S) is True
        rec.close(1000 + 6 * S)
    docs = [json.loads(x) for x in p.read_text().splitlines()]
    ev = [x for x in docs if "name" in x]
    assert [(e["name"], e["level"], e["first"]) for e in ev] == [("a: x", 2, True), (T5_LIST[0], 2, True), ("a: x", 0, False)]
    fifth = [x for x in docs if "last_seen" in x]
    assert fifth[0]["last_seen"] == {"a: x": 3000, T5_LIST[0]: 1000} and fifth[0]["mono_ns"] == 1000 + 5 * S
    assert fifth[0]["values"][T5_LIST[0]]["measured_rate"] == "1.00 [Hz]"
    assert set(fifth[0]["values"]) == {T5_LIST[0]}, "only control_topic_status keeps its key values (PR section 6's measured_rate)"
    assert [x["summary"] for x in docs if "summary" in x] == sorted(["a: x", T5_LIST[0]])


def test_the_diag_recorder_forces_a_last_line_at_the_time_it_was_written_and_never_before_a_status_was_seen(tmp_path):
    d = _load(DIAG, "aw_g1_diag")
    p = tmp_path / "diag.jsonl"
    with open(str(p), "w", encoding="utf-8") as f:
        rec = d.Recorder(f.write)
        assert rec.tick(500, force=True) is False                 # nothing seen yet: no line, due or not
        rec.seen(1000, [_Status("a: x", 0)])
        assert rec.tick(2000) is False                            # not due
        assert rec.tick(2000, force=True) is True                 # forced, with the time it was written
    docs = [json.loads(x) for x in p.read_text().splitlines()]
    fifth = [x for x in docs if "last_seen" in x]
    assert [x["mono_ns"] for x in fifth] == [2000] and fifth[0]["last_seen"] == {"a: x": 1000}, docs


def test_the_diag_recorder_main_ends_with_a_5_s_line_that_carries_the_clock_it_read(tmp_path, monkeypatch):
    """PR section 7: the close's last line carries the CLOCK_MONOTONIC read at the close."""
    d = _load(DIAG, "aw_g1_diag")
    _fake_ros(monkeypatch, lambda cb: cb(types.SimpleNamespace(status=[_Status(VALIDATOR, 0)])), [])
    p = tmp_path / "x" / "diag.jsonl"
    old = signal.getsignal(signal.SIGTERM)
    before = time.monotonic_ns()
    try:
        assert d.main(["--out", str(p)]) == 0
    finally:
        signal.signal(signal.SIGTERM, old)
    after = time.monotonic_ns()
    docs = [json.loads(x) for x in p.read_text().splitlines()]
    fifth = [x for x in docs if "last_seen" in x]
    assert len(fifth) == 1 and before <= fifth[0]["mono_ns"] <= after, (before, after, fifth)
    assert all(before <= x["mono_ns"] <= after for x in docs if "mono_ns" in x), docs


def test_the_diag_recorders_summary_lines_carry_the_clock_they_were_written_at(tmp_path):
    """PR section 7: every line has the node's CLOCK_MONOTONIC; the summary lines at the end are lines too."""
    d = _load(DIAG, "aw_g1_diag")
    p = tmp_path / "diag.jsonl"
    with open(str(p), "w", encoding="utf-8") as f:
        rec = d.Recorder(f.write)
        rec.seen(1000, [_Status("a: x", 2), _Status(T5_LIST[0], 0)])
        rec.close(7000)
    docs = [json.loads(x) for x in p.read_text().splitlines()]
    summaries = [x for x in docs if "summary" in x]
    assert [x["summary"] for x in summaries] == sorted(["a: x", T5_LIST[0]]), docs
    assert all(x["mono_ns"] == 7000 for x in summaries), summaries
    assert all(isinstance(x.get("mono_ns"), int) for x in docs), docs


def test_the_diag_recorder_main_writes_its_summary_lines_with_the_clock_it_read_after_its_last_5_s_line(tmp_path, monkeypatch):
    d = _load(DIAG, "aw_g1_diag")
    _fake_ros(monkeypatch, lambda cb: cb(types.SimpleNamespace(status=[_Status(VALIDATOR, 0), _Status("a: x", 1)])), [])
    p = tmp_path / "x" / "diag.jsonl"
    old = signal.getsignal(signal.SIGTERM)
    before = time.monotonic_ns()
    try:
        assert d.main(["--out", str(p)]) == 0
    finally:
        signal.signal(signal.SIGTERM, old)
    after = time.monotonic_ns()
    docs = [json.loads(x) for x in p.read_text().splitlines()]
    summaries = [x for x in docs if "summary" in x]
    fifth = [x for x in docs if "last_seen" in x]
    assert len(summaries) == 2 and len(fifth) == 1, docs
    assert all(before <= x["mono_ns"] <= after for x in summaries), (before, after, summaries)
    assert fifth[0]["mono_ns"] <= min(x["mono_ns"] for x in summaries), docs


def test_the_diag_recorder_runs_against_a_stand_in_rclpy(tmp_path, monkeypatch):
    d = _load(DIAG, "aw_g1_diag")
    qos = []
    _fake_ros(monkeypatch, lambda cb: cb(types.SimpleNamespace(status=[_Status(VALIDATOR, 0)])), qos)
    p = tmp_path / "x" / "diag.jsonl"
    old = signal.getsignal(signal.SIGTERM)
    try:
        assert d.main(["--out", str(p)]) == 0
    finally:
        signal.signal(signal.SIGTERM, old)
    assert qos[0][1] == "/diagnostics" and qos[0][2].reliability == "RELIABLE"
    docs = [json.loads(x) for x in p.read_text().splitlines()]
    assert any(x.get("name") == VALIDATOR and x["level"] == 0 for x in docs)


def test_the_count_recorder_keeps_only_arrival_times_with_the_claim_nodes_qos(tmp_path, monkeypatch):
    c = _load(COUNT, "aw_g1_count")
    qos = []
    _fake_ros(monkeypatch, lambda cb: [cb(object()) for _ in range(3)], qos)
    p = tmp_path / "x" / "arrivals.jsonl"
    old = signal.getsignal(signal.SIGTERM)
    try:
        assert c.main(["--out", str(p)]) == 0
    finally:
        signal.signal(signal.SIGTERM, old)
    typ, topic, q = qos[0]
    assert typ == "Control" and topic == "/control/command/control_cmd"
    assert q.depth == 1 and q.history == "KEEP_LAST" and q.reliability == "RELIABLE" and q.durability == "VOLATILE"
    docs = [json.loads(x) for x in p.read_text().splitlines()]
    assert [x["seq"] for x in docs if "seq" in x] == [1, 2, 3]
    assert all(set(x) == {"seq", "mono_ns"} for x in docs if "seq" in x)
    assert docs[-1] == {"summary": {"arrivals": 3}}


def test_each_recorder_imports_ros_inside_main_only():
    for p, name in ((DIAG, "aw_g1_diag"), (COUNT, "aw_g1_count")):
        for k in ("rclpy", "rclpy.node", "rclpy.qos"):
            sys.modules.pop(k, None)
        _load(p, name)
        assert "rclpy" not in sys.modules


# --- the stamp's g1 policy -------------------------------------------------------------------------------------------------------

def _lib_rig(tmp_path, procs=((812, "dockerd", "3,5"), (700, "containerd", "3,5")), containers=(), socket="active", docker_fails=False,
             inspect_fails=False):
    """A fake host: procs (pid, argv0, cores); containers (id, request, effective). inspect_fails: `docker ps` answers, `docker inspect` does not."""
    proc, sysr, b = tmp_path / "proc", tmp_path / "sys", tmp_path / "bin"
    b.mkdir(parents=True)
    sysr.mkdir()
    for pid, a0, cores in procs:
        d = proc / str(pid)
        d.mkdir(parents=True)
        (d / "cmdline").write_bytes(("/usr/bin/%s\0" % a0).encode())
        (d / "status").write_text("Name:\t%s\nCpus_allowed_list:\t%s\n" % (a0, cores))
    rows, pid = {}, 3000
    for cid, req, eff in containers:
        pid += 1
        d = proc / str(pid)
        d.mkdir(parents=True)
        (d / "cgroup").write_text("0::/system.slice/docker-%s.scope\n" % cid)
        scope = sysr / "fs" / "cgroup" / "system.slice" / ("docker-%s.scope" % cid)
        scope.mkdir(parents=True)
        (scope / "cpuset.cpus.effective").write_text(eff + "\n")
        rows[cid] = "%s|%d" % (req, pid)
    (tmp_path / "containers.json").write_text(json.dumps(rows))
    dk = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a[:2] == ["-H", "unix:///run/docker.sock"]:
    a = a[2:]
with open(os.environ["RIG"] + "/docker.log", "a") as f:
    f.write(" ".join(a) + "\n")
if os.environ.get("RIG_DOCKER_FAILS") or (a[0] == "inspect" and os.environ.get("RIG_INSPECT_FAILS")):
    sys.exit(1)
rows = json.load(open(os.environ["RIG"] + "/containers.json"))
if a[0] == "ps":
    print("\n".join(rows))
elif a[0] == "inspect":
    print(rows[a[-1]])
'''
    (b / "docker").write_text(dk, newline="\n")
    (b / "sudo").write_text('#!/usr/bin/env bash\n[ "$1" = -n ] || exit 1\nshift\nexec "$@"\n', newline="\n")
    (b / "taskset").write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$RIG/taskset.log"\nshift 2\nexec "$@"\n', newline="\n")
    (b / "systemctl").write_text('#!/usr/bin/env bash\ncase "$2" in docker.socket) [ "$1" = is-active ] && echo %s || echo enabled ;; '
                                 '*) [ "$1" = is-active ] && echo active || echo enabled ;; esac\n' % socket, newline="\n")
    for n in ("docker", "sudo", "taskset", "systemctl"):
        (b / n).chmod(0o755)
    py = b / "python3"
    py.write_text('#!/usr/bin/env bash\nexec "%s" "$@"\n' % sys.executable, newline="\n")
    py.chmod(0o755)
    env = dict(os.environ, PATH=str(b) + os.pathsep + os.environ["PATH"], RIG=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    if docker_fails:
        env["RIG_DOCKER_FAILS"] = "1"
    if inspect_fails:
        env["RIG_INSPECT_FAILS"] = "1"
    return env


def _g1_stamp(tmp_path, policy="g1", then="", env=None, **kw):
    e = _lib_rig(tmp_path, **kw)
    if env:
        e.update(env)
    out = tmp_path / "out"
    out.mkdir()
    script = "\n".join([
        "set -u",
        'PLATFORM_POLICY=%s' % policy,
        '. "%s"' % LIB,
        'PROC_ROOT="%s/proc"; SYS_ROOT="%s/sys"; SYSFS_CPU="%s/nocpu"' % (tmp_path, tmp_path, tmp_path),
        'OUT="%s"; N=0; K=0; WARMUP=0; INTERVAL_MS=0' % out,
        'm_write_stamp "$OUT/stamp.json" \'"ladder": "none"\'',
        then,
        "echo REACHED"])
    r = subprocess.run([BASH, "-c", script], env=e, capture_output=True, text=True, timeout=60)
    r.stamp = json.loads((out / "stamp.json").read_text()) if (out / "stamp.json").exists() else None
    return r


@linux_only
def test_a_g1_stamp_with_every_daemon_and_container_on_3_5_is_written_with_no_ladder(tmp_path):
    r = _g1_stamp(tmp_path, containers=[("aaa", "3,5", "3,5")])
    assert r.returncode == 0 and "REACHED" in r.stdout, r.stderr
    assert r.stamp["platform"]["policy"] == "g1"
    assert (r.stamp["n"], r.stamp["k"], r.stamp["warmup"], r.stamp["interval_ms"]) == (0, 0, 0, 0)
    assert r.stamp["ladder"] == "none"
    assert r.stamp["platform"]["containers_running"] == "1"


@linux_only
def test_a_g1_stamp_allows_the_socket_active(tmp_path):
    r = _g1_stamp(tmp_path, socket="active")
    assert r.returncode == 0, r.stderr
    assert r.stamp["platform"]["docker_socket"]["active"] == "active"


@linux_only
@pytest.mark.parametrize("procs, word", [
    (((812, "dockerd", "0-5"), (700, "containerd", "3,5")), "dockerd is running on cores '0-5'"),
    (((812, "dockerd", "3,5"), (700, "containerd", "0-5")), "containerd is running on cores '0-5'"),
    (((812, "dockerd", "3,5"),), "containerd is not running"),
    (((700, "containerd", "3,5"),), "dockerd is not running"),
    # a list that cannot be read is "unknown": not one that can be shown to be confined (an empty Cpus_allowed_list here)
    (((812, "dockerd", ""), (700, "containerd", "3,5")), "dockerd is running on cores 'unknown'"),
    (((812, "dockerd", "3,5"), (700, "containerd", "")), "containerd is running on cores 'unknown'"),
    (((812, "dockerd", "3,5"), (813, "dockerd", ""), (700, "containerd", "3,5")), "dockerd is running on cores '3,5;unknown'"),
])
def test_a_g1_stamp_refuses_a_daemon_off_3_5_or_absent(tmp_path, procs, word):
    r = _g1_stamp(tmp_path, procs=procs)
    assert r.returncode != 0 and "REACHED" not in r.stdout, r.stderr
    assert word in r.stderr and "g1" in r.stderr and r.stamp is None, r.stderr


@linux_only
@pytest.mark.parametrize("row, word", [
    (("aaa", "0-5", "3,5"), "request"), (("aaa", "", "3,5"), "request"), (("aaa", "3,5", "0-5"), "effective"),
    (("aaa", "3,5", ""), "effective"), (("aaa", "3,4", "3,5"), "request"), (("aaa", "3,5", "4"), "effective"),
])
def test_a_g1_stamp_refuses_a_container_outside_3_5_by_either_read(tmp_path, row, word):
    r = _g1_stamp(tmp_path, containers=[("bbb", "3,5", "3,5"), row])
    assert r.returncode != 0 and "REACHED" not in r.stdout, r.stderr
    assert "aaa" in r.stderr and word in r.stderr and r.stamp is None, r.stderr


@linux_only
def test_a_g1_stamp_refuses_when_the_containers_cannot_be_listed(tmp_path):
    r = _g1_stamp(tmp_path, docker_fails=True)
    assert r.returncode != 0 and "could not be listed" in r.stderr and r.stamp is None, r.stderr


@linux_only
def test_a_g1_stamp_refuses_a_container_that_cannot_be_inspected(tmp_path):
    """`docker ps` names it and `docker inspect` does not answer: its cores are unknown, which is not on {3,5}."""
    r = _g1_stamp(tmp_path, containers=[("aaa", "3,5", "3,5")], inspect_fails=True)
    assert r.returncode != 0 and "REACHED" not in r.stdout, r.stderr
    assert "container aaa could not be inspected" in r.stderr and r.stamp is None, r.stderr


@linux_only
def test_refuse_and_record_do_not_read_a_containers_cores(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    r = _g1_stamp(a, policy="record", containers=[("aaa", "0-5", "0-5")])
    assert r.returncode == 0 and r.stamp["platform"]["policy"] == "record", r.stderr
    assert not any(x.startswith("inspect") for x in (a / "docker.log").read_text().splitlines())
    b = tmp_path / "b"
    b.mkdir()
    r = _g1_stamp(b, policy="refuse", containers=[("aaa", "0-5", "0-5")], socket="inactive")
    assert r.returncode == 0 and r.stamp["platform"]["policy"] == "refuse", r.stderr


@linux_only
def test_an_unknown_policy_names_g1_among_the_policies(tmp_path):
    r = _g1_stamp(tmp_path, policy="bogus")
    assert r.returncode != 0 and "PLATFORM_POLICY='bogus' is not a policy" in r.stderr and "'g1'" in r.stderr, r.stderr


@linux_only
def test_the_after_state_of_a_g1_stamp_is_recorded_only(tmp_path):
    r = _g1_stamp(tmp_path, then='rm -rf "$PROC_ROOT/812"; m_stamp_after "$OUT/stamp.json"')
    assert r.returncode == 0, r.stderr
    d = json.loads((tmp_path / "out" / "stamp.json").read_text())
    assert d["platform_after"]["policy"] == "record" and d["platform_after"]["dockerd_cpus"] == "not running"


@linux_only
def test_the_clock_sampler_runs_the_loop_on_core_4_under_the_given_ceiling_in_the_clk_form(tmp_path):
    emc = tmp_path / "emc"
    emc.write_text("2133000000\n")
    script = "\n".join([
        "set -u",
        '. "%s"' % LIB,
        'OUT="%s"; EMC_BPMP="%s"; EMC_CCF="%s"; DEVFREQ_ROOT="%s/none"' % (tmp_path, emc, emc, tmp_path),
        "m_clock_sampler_start g1 30",
        "for i in 1 2 3 4 5 6 7 8 9 10; do [ -s \"$OUT/clk-g1.log\" ] && break; sleep 0.2; done",
        "m_sampler_stop || echo STOPFAILED",
        "echo REACHED"])
    e = _lib_rig(tmp_path / "rig") if (tmp_path / "rig").mkdir() is None else None
    real = shutil.which("timeout")
    with open(str(tmp_path / "rig" / "bin" / "timeout"), "w", newline="\n") as f:     # logs its bound, then the real one
        f.write('#!/usr/bin/env bash\nprintf "timeout %%s\\n" "$*" >> "$RIG/timeout.log"\nexec %s "$@"\n' % real)
    os.chmod(str(tmp_path / "rig" / "bin" / "timeout"), 0o755)
    r = subprocess.run([BASH, "-c", script], env=e, capture_output=True, text=True, timeout=60)
    assert "REACHED" in r.stdout and "STOPFAILED" not in r.stdout, r.stdout + r.stderr
    rows = (tmp_path / "clk-g1.log").read_text().splitlines()
    assert rows and re.match(r"^[0-9.]+ emc_bpmp_hz=2133000000 emc_ccf_hz=2133000000 gpu_hz=$", rows[0]), rows
    assert "-c 4" in (tmp_path / "rig" / "taskset.log").read_text()
    assert any(x.startswith("timeout 30 taskset -c 4 ") for x in (tmp_path / "rig" / "timeout.log").read_text().splitlines()), \
        "the arm's bound is the sampler's ceiling (PR section 4)"


# --- the harness's rig ------------------------------------------------------------------------------------------------------------

_RIG_DOCKER = r'''#!/usr/bin/env python3
import json, os, re, signal, sys, time
E = os.environ.get
STUB = E("STUB_DIR")
CDIR = os.path.join(STUB, "state", "docker")
os.makedirs(CDIR, exist_ok=True)
argv = sys.argv[1:]
if argv[:2] == ["-H", "unix:///run/docker.sock"]:
    argv = argv[2:]
with open(os.path.join(STUB, "docker-calls.jsonl"), "a") as f:
    f.write(json.dumps(argv) + "\n")
with open(os.path.join(STUB, "calls.log"), "a") as f:
    f.write("docker " + " ".join(argv) + "\n")
S = 10 ** 9


def clock():
    with open(E("QNX_CLOCK_FILE")) as f:
        m, w = f.read().split()
    return int(m), int(w)


def advance(ns):
    m, w = clock()
    tmp = "%s.tmp%d" % (E("QNX_CLOCK_FILE"), os.getpid())
    with open(tmp, "w") as f:                   # whole, for the rig's watchdog and the harness reading it at any moment
        f.write("%d %d\n" % (m + ns, w + ns))
    os.replace(tmp, E("QNX_CLOCK_FILE"))
    return m + ns


def path(n):
    return os.path.join(CDIR, n + ".json")


def load(n):
    try:
        with open(path(n)) as f:
            return json.load(f)
    except OSError:
        return None


def save(c):
    tmp = "%s.tmp%d" % (path(c["name"]), os.getpid())
    with open(tmp, "w") as f:                   # whole: the resident driver, a held `docker wait` and the harness read it side by side
        json.dump(c, f)
    os.replace(tmp, path(c["name"]))


def every():
    return [load(n[:-5]) for n in sorted(os.listdir(CDIR)) if n.endswith(".json")]


def host_of(mounts, p):
    best = ""
    for cont in mounts:
        if (p == cont or p.startswith(cont.rstrip("/") + "/")) and len(cont) > len(best):
            best = cont
    return mounts[best] + p[len(best):]


def append(p, docs):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        for d in docs:
            f.write(json.dumps(d) + "\n")


def scope_of(name):
    return os.path.join(E("SYS_ROOT"), "fs", "cgroup", "system.slice", "docker-%s.scope" % name)


def next_pid():
    p = os.path.join(STUB, "state", "pid")
    n = int(open(p).read()) if os.path.exists(p) else 5000
    with open(p, "w") as f:
        f.write(str(n + 1))
    return n


def frame(seq, t):
    return (seq.to_bytes(8, "little") + t.to_bytes(8, "little") + bytes(48)).hex()


def drive_count():
    p = os.path.join(STUB, "state", "drives")
    n = int(open(p).read()) + 1 if os.path.exists(p) else 1
    with open(p, "w") as f:
        f.write(str(n))
    return n


def csv(name):
    return (E(name) or "").split(",")


# docker's words for a container that is not there, in the wordings of the clients that say so (the first is docker 29's, read from the real CLI)
ABSENT = {None: "error: no such object: %s\n", "no-such-object": "Error: No such object: %s\n",
          "no-such-container": "Error response from daemon: No such container: %s\n"}


def no_answer():
    """An inspect the daemon did not answer: the container is not known to be gone. STUB_NO_ANSWER_WORDS=socket-gone is the client's words for a
    socket file that is not there, which hold `no such file or directory` and no word of a container's absence."""
    if E("STUB_NO_ANSWER_WORDS") == "socket-gone":
        sys.stderr.write("failed to connect to the docker API at unix:///var/run/docker.sock; check if the path is correct and if the daemon is "
                         "running: dial unix /var/run/docker.sock: connect: no such file or directory\n")
    else:
        sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?\n")
    sys.exit(1)


def ancestors():
    """This call's ancestors, nearest first, each (pid, argv): read at the driver's `docker run`, since the driver lives on detached."""
    pid, out = os.getppid(), []
    while pid > 1:
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as h:
                words = h.read().split(b"\0")
            with open("/proc/%d/stat" % pid) as h:
                parent = int(h.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        out.append((pid, words))
        pid = parent
    return out


def kill_arm_child(above):
    """SIGKILL the harness's arm child: the nearest ancestor whose command line has `_arm`."""
    for pid, words in above:
        if b"_arm" in words:
            os.kill(pid, 9)
            return


def kill_harness(above):
    """SIGKILL every ancestor that runs the harness, its parent first: killed outright, with no time for a trap."""
    mine = [pid for pid, words in above if any(w.endswith(b"run-aw-g1.sh") for w in words)]
    for p in reversed(mine):
        os.kill(p, 9)


def die(name, code):
    c = load(name)
    if c:
        c["running"] = False
        c["exit"] = code
        save(c)


def one_drive(name, word, root, require, above):
    """One drive of the resident driver: its lines on the rig's clock, its Control into the claim node's log, the diagnostics, and last what
    the driver's answer is. STUB_DRIVE_* its outcome; STUB_DRIVER_HANGS_AT_DRIVE, and a `docker wait` made to fail or hang at it, no number;
    STUB_DRIVER_DIES_AT_DRIVE no number and an ended container; STUB_EXIT_TORN_AT_DRIVE an exit file seen before its line ended;
    STUB_EXIT_GARBLED_AT_DRIVE one whose line has ended and is no number."""
    k = drive_count()
    wpath = os.path.join(STUB, "state", "waits")
    until = time.time() + 5
    while time.time() < until and not (os.path.exists(wpath) and int(open(wpath).read() or 0) >= k):
        time.sleep(0.002)                               # a real drive takes minutes: this one must not outrun the `docker wait` held for it
    now = advance(1 * S)
    if str(k) in csv("STUB_WATCHDOG_FREEZES_AT_DRIVE"):
        with open(os.path.join(STUB, "state", "dog-freeze"), "w") as f:   # alive, and its series stops growing from here
            f.write("x")
    out = os.path.join(root, word)
    os.makedirs(out)
    rows = [{"step": "map", "outcome": "done", "mono_ns": now, "require_claim_node": require}]
    rc = 0
    step_ns = int(E("STUB_DRIVE_S", "240")) * S
    if str(k) in csv("STUB_DRIVE_NO_ROUTE"):
        rows.append({"step": "localize", "outcome": "timeout", "mono_ns": now + 60 * S})
        rc = 3
        advance(61 * S)
    else:
        route = now + S
        route_out = "timeout" if str(k) in csv("STUB_DRIVE_ROUTE_TIMEOUT") else "done"    # the route line is there, of another outcome
        rows += [{"step": "localize", "outcome": "done", "state": 3, "mono_ns": now + S // 2},
                 {"step": "route", "outcome": route_out, "state": 2, "mono_ns": route},
                 {"step": "engage", "outcome": "done", "state": 2, "mono_ns": route + S}]
        end = route + step_ns
        claim = load("aw-claim-node")
        count = load("aw-g1-count")
        if claim:
            p = os.path.join(claim["out"], "replies.jsonl")
            n = claim.get("seq", 0)
            docs = []
            for t in range(route + 2 * S, end, 30 * 10 ** 6):
                n += 1
                docs.append({"seq": n, "frame": frame(n, t), "outcome": "replied", "verdict": 0, "reason": 0, "mono_ns": t + 1000})
            append(p, docs)
            claim["seq"] = n
            save(claim)
        if count:
            n = count.get("seq", 0)
            docs = []
            for t in range(route + 2 * S, end, 30 * 10 ** 6):
                n += 1
                docs.append({"seq": n, "mono_ns": t})
            append(count["out"], docs)
            count["seq"] = n
            save(count)
        diag = load("aw-g1-diag")
        if diag:
            docs = []
            if k == 1:
                docs += [{"mono_ns": route + S, "first": False, "name": n, "hardware_id": "x", "level": 0, "message": "OK"} for n in (
                    "topic_state_monitor_control_command_control_cmd: control_topic_status",
                    "topic_state_monitor_trajectory_follower_control_cmd: control_topic_status",
                    "controller_node_exe: incoming_message_timeout")]
            names = ["control_validator: control_validation_latency", "vehicle_cmd_gate: heartbeat"]
            for t in range(now, end + 6 * S, 5 * S):
                docs.append({"mono_ns": t, "last_seen": {n: t for n in names}, "values": {}})
            append(diag["out"], docs)
        if str(k) in csv("STUB_DRIVE_TIMEOUT") or route_out == "timeout":
            rows.append({"step": "arrive", "outcome": "timeout", "state": 2, "mono_ns": end})
            rc = 3
        else:
            rows += [{"step": "arrive", "outcome": "done", "state": 3, "mono_ns": end},
                     {"step": "clear", "outcome": "done", "mono_ns": end + S // 100}]
        advance(step_ns + S)
    append(os.path.join(out, "scenario.jsonl"), rows)
    append(os.path.join(out, "odometry.jsonl"), [{"at": "route", "x": 1.0, "y": 2.0, "z": 3.0, "to_start_m": 0.0, "to_goal_m": 60.0}])
    if rc != 0:
        append(os.path.join(out, "after-failure.jsonl"), [{"step": "stop", "outcome": "done"}, {"step": "clear", "outcome": "done"}])
    if str(k) in csv("STUB_KILL_PARENT_AFTER_DRIVE"):
        kill_arm_child(above)
    if str(k) in csv("STUB_KILL_HARNESS_AFTER_DRIVE"):
        kill_harness(above)
    if str(k) in csv("STUB_DEADLINE_PASSES_AFTER_DRIVE"):
        with open(os.path.join(STUB, "state", "deadline-passed"), "w") as f:   # the date stub then reads past the deadline
            f.write("x")
    if str(k) in csv("STUB_SIM_DIES_AFTER_DRIVE"):
        sim = load("aw-sim")
        sim["running"] = False
        sim["exit"] = 137
        save(sim)
    if str(k) in csv("STUB_SIM_GONE_AFTER_DRIVE"):      # removed: docker's own answer is then `no such object`
        os.remove(path("aw-sim"))
    if str(k) in csv("STUB_WATCHDOG_STOP_AFTER_DRIVE"):
        with open(E("STUB_STOP_FILE"), "w") as f:
            f.write("stop\n")
        with open(os.path.join(STUB, "state", "dog-stop"), "w") as f:
            f.write("x")
    if str(k) in csv("STUB_WATCHDOG_DIES_AFTER_DRIVE"):
        with open(os.path.join(STUB, "state", "dog-die"), "w") as f:
            f.write("x")
    holds = ("STUB_DRIVER_HANGS_AT_DRIVE", "STUB_WAIT_FAILS_AT_DRIVE", "STUB_WAIT_HANGS_AT_DRIVE", "STUB_DRIVER_REMOVED_AT_DRIVE")
    if any(str(k) in csv(x) for x in holds):
        with open(os.path.join(STUB, "state", "holding-%d" % k), "w") as f:
            f.write("x")
        while (load(name) or {}).get("running"):        # no number, ever: only docker's stop or the harness's removal ends this one
            time.sleep(0.005)
        return False
    if str(k) in csv("STUB_DRIVER_DIES_AT_DRIVE"):
        die(name, int(E("STUB_DRIVER_EXIT", "137")))
        return False
    if str(k) in csv("STUB_EXIT_GARBLED_AT_DRIVE"):     # a whole line that is no number (STUB_EXIT_GARBLED_LINE), and then the number
        with open(os.path.join(out, "exit"), "w") as f:
            f.write(E("STUB_EXIT_GARBLED_LINE", "oops") + "\n")
        time.sleep(0.3)
        with open(os.path.join(out, "exit"), "w") as f:
            f.write("13\n")
    elif str(k) in csv("STUB_EXIT_TORN_AT_DRIVE"):      # a first byte visible before the rest, as a writer with no rename would show it
        with open(os.path.join(out, "exit"), "w") as f:
            f.write("1")
        time.sleep(0.3)
        with open(os.path.join(out, "exit"), "w") as f:
            f.write("13\n")
    else:
        with open(os.path.join(out, "exit.tmp"), "w") as f:
            f.write("%d\n" % rc)
        os.replace(os.path.join(out, "exit.tmp"), os.path.join(out, "exit"))
    if str(k) in csv("STUB_DRIVER_DIES_AFTER_DRIVE"):   # its number written, and then gone, between two drives
        die(name, 1)
        return False
    return True


def resident(name, go, root, require, above):
    """The resident driver, detached from the `docker run` that started it: one word, one drive, until its container ends."""
    end = time.time() + 200
    while time.time() < end:
        if not (load(name) or {}).get("running"):
            return
        dpath = os.path.join(STUB, "state", "drives")
        begun = int(open(dpath).read()) if os.path.exists(dpath) else 0
        once = os.path.join(STUB, "state", "died-before-word")
        if str(begun + 1) in csv("STUB_DRIVER_DIES_BEFORE_WORD_AT_DRIVE") and os.path.exists(go) and not os.path.exists(once):
            with open(once, "w") as f:
                f.write("x")
            advance(1 * S)
            die(name, int(E("STUB_DRIVER_EXIT", "137")))
            return
        try:
            with open(go) as f:
                text = f.read()
        except OSError:
            time.sleep(0.002)
            continue
        if not text.endswith("\n"):
            time.sleep(0.002)
            continue
        os.remove(go)
        if not one_drive(name, text[:-1], root, require, above):
            return


cmd = argv[0] if argv else ""
if cmd == "ps":
    ps_after = E("STUB_PS_FAILS_AFTER_DRIVES")
    if ps_after:                    # the daemon stops answering `ps` once this many drives have started
        dpath = os.path.join(STUB, "state", "drives")
        started = int(open(dpath).read()) if os.path.exists(dpath) else 0
        if started >= int(ps_after):
            sys.stderr.write("Cannot connect to the Docker daemon\n")
            sys.exit(1)
    filt = [argv[i + 1] for i, a in enumerate(argv) if a == "--filter"]
    allc = "-aq" in argv or "-a" in argv
    for c in every():
        if not allc and not c["running"]:
            continue
        keep = True
        for f in filt:
            key, _eq, val = f.split("=", 1)[1].partition("=")
            keep = keep and key in c["labels"] and (not val or c["labels"][key] == val)
        if keep:
            print(c["name"])
elif argv[:2] == ["image", "inspect"]:
    if E("STUB_NO_IMAGE"):
        sys.stderr.write("No such image\n")
        sys.exit(1)
    print(json.dumps([{"Id": "sha256:" + "ab" * 32, "RepoDigests": [argv[2]], "RepoTags": [], "Os": "linux", "Architecture": "arm64",
                       "Config": {"Labels": {}, "Entrypoint": ["/docker-entrypoint.sh"]}}]))
elif cmd == "run":
    i, vals, flags = 1, {}, set()
    VALUE = ("--name", "--label", "--network", "--user", "--group-add", "--cap-drop", "--security-opt", "--entrypoint", "-v", "-e",
             "--cpuset-cpus", "--memory", "--memory-swap")
    while i < len(argv) and argv[i].startswith("-"):
        a = argv[i]
        if a in ("--rm", "-d"):
            flags.add(a)
            i += 1
        elif a in VALUE and i + 1 < len(argv):
            vals.setdefault(a, []).append(argv[i + 1])
            i += 2
        else:
            sys.stderr.write("docker stub: unknown run flag %s\n" % a)
            sys.exit(125)
    image, words = argv[i], argv[i + 1:]
    name = vals["--name"][0]
    dpath = os.path.join(STUB, "state", "drives")
    begun = int(open(dpath).read()) if os.path.exists(dpath) else 0
    if name in csv("STUB_RUN_HANGS") or (name == "aw-scenario" and str(begun + 1) in csv("STUB_RUN_HANGS_AT_DRIVE")):
        time.sleep(float(E("STUB_HANG_S", "20")))   # a dockerd that does not answer: only the harness's `timeout` ends this
        sys.stderr.write("docker: the stand-in gave up hanging\n")
        sys.exit(125)
    if name in csv("STUB_RUN_FAILS") or (name == "aw-scenario" and str(begun + 1) in csv("STUB_RUN_FAILS_AT_DRIVE")):
        if E("STUB_RUN_FAIL_STOPS"):    # the watchdog fired while dockerd was failing
            with open(E("STUB_STOP_FILE"), "w") as f:
                f.write("stop\n")
        sys.stderr.write("docker: Error response from daemon: the stand-in refuses\n")
        sys.exit(125)                   # dockerd's own: no container was created
    if load(name) is not None:
        sys.stderr.write("Conflict: the name %s is in use\n" % name)
        sys.exit(125)
    mounts = {}
    for v in vals.get("-v", []):
        parts = v.split(":")
        mounts[parts[1]] = parts[0]
    pid = next_pid()
    procdir = os.path.join(E("PROC_ROOT"), str(pid))
    os.makedirs(procdir, exist_ok=True)
    with open(os.path.join(procdir, "cgroup"), "w") as f:
        f.write("0::/system.slice/docker-%s.scope\n" % name)
    sc = scope_of(name)
    os.makedirs(sc, exist_ok=True)
    req = (vals.get("--cpuset-cpus") or [""])[0]
    eff = req
    for spec in csv("STUB_EFFECTIVE"):
        if spec.startswith(name + "="):
            eff = spec.split("=", 1)[1]
    with open(os.path.join(sc, "cpuset.cpus.effective"), "w") as f:
        f.write(eff + "\n")
    with open(os.path.join(sc, "memory.events"), "w") as f:
        f.write("low 0\nhigh 0\nmax 0\noom 0\noom_kill %s\n" % ("1" if name in csv("STUB_OOM_KILL") else "0"))
    with open(os.path.join(sc, "cgroup.kill"), "w") as f:
        f.write("")
    labels = dict(x.split("=", 1) if "=" in x else (x, "") for x in vals.get("--label", []))
    c = {"name": name, "labels": labels, "running": True, "exit": 0, "mounts": mounts, "pid": pid, "request": req, "log": "", "image": image}
    now = advance(1 * S)
    if name == "aw-sim" and E("STUB_SIM_RUN_ADVANCE_S"):    # a `docker run` that takes this long on saturated cores
        now = advance(int(E("STUB_SIM_RUN_ADVANCE_S")) * S)
    if name == "aw-sim" and E("STUB_SIM_NOT_UP"):
        c["not_up"] = True
    if name == "aw-claim-node":
        c["out"] = host_of(mounts, words[words.index("--out") + 1])
        append(os.path.join(c["out"], "replies.jsonl"), [{"header": {"format": 1, "kind": 2, "mode": "node"}}])
    if name == "aw-g1-diag":
        c["out"] = host_of(mounts, words[words.index("--out") + 1])
        append(c["out"], [{"mono_ns": now, "first": True, "name": n, "hardware_id": "x", "level": 2, "message": "Error"} for n in (
            "topic_state_monitor_control_command_control_cmd: control_topic_status",
            "topic_state_monitor_trajectory_follower_control_cmd: control_topic_status",
            "controller_node_exe: incoming_message_timeout")]
            + [{"mono_ns": now, "first": True, "name": "control_validator: control_validation_latency", "hardware_id": "c",
                "level": 0, "message": "OK"}])
    if name == "aw-g1-count":
        c["out"] = host_of(mounts, words[words.index("--out") + 1])
    if name == "aw-scenario":
        c["log"] = "aw_scenario: the driver's own line"
        c["root"] = host_of(mounts, words[words.index("--out") + 1])
        c["go"] = host_of(mounts, words[words.index("--serve") + 1])
    save(c)
    print("%064x" % pid)
    sys.stdout.flush()
    if name == "aw-scenario":
        above = ancestors()
        if os.fork() == 0:
            os.setsid()
            nul = os.open(os.devnull, os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(nul, fd)
            try:
                resident(name, c["go"], c["root"], "--require-claim-node" in words, above)
            finally:
                os._exit(0)
elif cmd == "exec":
    words = argv[1:]
    while words and words[0].startswith("-"):
        words = words[1:]
    name = words[0]
    c = load(name)
    if not c or not c["running"]:
        sys.stderr.write("not running\n")
        sys.exit(1)
    if "service" in words and "list" in words:
        if c.get("not_up"):
            if E("STUB_SIM_WAIT_STOPS"):            # the watchdog fired while the harness waited for the simulator
                with open(E("STUB_STOP_FILE"), "w") as f:
                    f.write("stop\n")
            advance(70 * S)
            sys.exit(0)
        print("/api/localization/initialize\n/api/routing/set_route_points\n/api/operation_mode/change_to_autonomous\n/other")
    elif "python3" in words:
        off = int(E("STUB_CONTAINER_CLOCK_OFF_NS", "0"))
        m, w = clock()
        print("%d %d" % (m + 7, w + 7 + off))
elif cmd == "stop":
    name = argv[-1]
    if name == E("STUB_STOP_FAILS", ""):    # dockerd gave no answer: the container is never signalled, and the claim node writes no summary
        sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?\n")
        sys.exit(int(E("STUB_STOP_FAIL_RC", "1")))
    c = load(name)
    if not c:
        sys.stderr.write("Error response from daemon: No such container: %s\n" % name)
        sys.exit(1)
    if c:
        c["running"] = False
        c["exit"] = 0
        if name == "aw-claim-node":
            n = c.get("seq", 0)
            append(os.path.join(c["out"], "replies.jsonl"), [{"summary": {
                "counters": {"controls": n, "packed": n, "replied": n, "drop": 0, "lost_on_reconnect": 0, "reconnects": 0},
                "identity": {"holds": True}}}])
            c["log"] = "ctl_claim_node: controls=%d identity=holds" % n
        if name == "aw-g1-count":
            append(c["out"], [{"summary": {"arrivals": c.get("seq", 0)}}])
        save(c)
        sc = scope_of(name)
        events = os.path.join(sc, "memory.events")
        if os.path.exists(events):              # a stopped container's scope is gone
            os.remove(events)
        advance(1 * S)
elif cmd == "logs":
    c = load(argv[-1])
    print(c["log"] if c else "")
elif cmd == "wait":
    name = argv[-1]

    def ended_by(word):                             # how each wait held for a drive ended: the harness's TERM, or the container's end
        with open(os.path.join(STUB, "state", "wait-ends"), "a") as h:
            h.write(word + "\n")
    signal.signal(signal.SIGTERM, lambda *_: (ended_by("killed"), os._exit(143)))     # before the count below, which the driver stand-in waits for
    c = load(name)
    wpath = os.path.join(STUB, "state", "waits")
    at = str(int(open(wpath).read()) + 1) if os.path.exists(wpath) else "1"      # the drive's: the harness holds one `docker wait` per drive
    with open(wpath, "w") as f:
        f.write(at)
    if at in csv("STUB_DRIVER_REMOVED_AT_DRIVE"):   # gone under the harness: docker's own words for it
        os.remove(path(name))
        c = None
    if at in csv("STUB_WAIT_FAILS_AT_DRIVE"):
        if E("STUB_WAIT_FAIL_STOPS"):   # the watchdog fired while dockerd was failing
            with open(E("STUB_STOP_FILE"), "w") as f:
                f.write("stop\n")
        if E("STUB_WAIT_SAYS"):
            print(E("STUB_WAIT_SAYS"))
        sys.exit(int(E("STUB_WAIT_FAIL_RC", "1")))   # the drive's container is there; `docker wait` gives no exit
    if at in csv("STUB_WAIT_HANGS_AT_DRIVE"):      # only the harness's `timeout` ends this; STUB_WAIT_INSPECT is what docker answers then
        if c and E("STUB_WAIT_INSPECT", "").startswith("ended"):   # it ended under the bound, with its lines and no number written
            until = time.time() + 10
            while time.time() < until and not os.path.exists(os.path.join(STUB, "state", "holding-" + at)):
                time.sleep(0.002)
            c = load(name)
            c["running"] = False
            c["exit"] = 3 if at in csv("STUB_DRIVE_TIMEOUT") else 0
            save(c)
        with open(os.path.join(STUB, "state", "wait-hung"), "w") as f:
            f.write("x")
        time.sleep(float(E("STUB_HANG_S", "20")))
        sys.exit(125)
    if c is None:
        sys.stderr.write("Error response from daemon: No such container: %s\n" % name)
        sys.exit(1)
    if E("STUB_WAIT_WARNS"):                        # docker's own number on stdout, a warning beside it on stderr
        sys.stderr.write("WARNING: Error loading config file: the stand-in's warning\n")
    end = time.time() + 200
    while time.time() < end:                        # as docker's: it answers when the container has ended
        c = load(name)
        if c is None or not c["running"]:
            break
        time.sleep(0.005)
    ended_by("done")
    print(c["exit"] if c else 1)
elif cmd == "inspect":
    fmt = argv[argv.index("-f") + 1]
    name = argv[-1]
    if name == "aw-scenario" and os.path.exists(os.path.join(STUB, "state", "wait-hung")):
        mode = E("STUB_WAIT_INSPECT")
        asks = "running" if fmt == "{{.State.Running}}" else "code" if fmt == "{{.State.ExitCode}}" else ""
        if asks and E("STUB_WAIT_INSPECT_WARNS"):           # docker's own answer on stdout, a warning beside it on stderr
            sys.stderr.write("WARNING: Error loading config file: the stand-in's warning\n")
        if asks and mode == "hang":
            time.sleep(float(E("STUB_HANG_S", "20")))
            sys.exit(125)
        if asks and (mode == "no-answer" or (mode == "ended-code-no-answer" and asks == "code")):
            sys.stderr.write("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?\n")
            sys.exit(1)
        if mode == "ended-code-garbled" and asks == "code":
            print("no number")
            sys.exit(0)
    if name == "aw-scenario" and fmt == "{{.State.Running}}" and E("STUB_DRIVER_INSPECT_NO_ANSWER"):
        no_answer()
    if name == "aw-sim" and fmt == "{{.State.Running}}":
        dpath = os.path.join(STUB, "state", "drives")
        begun = int(open(dpath).read()) if os.path.exists(dpath) else 0
        if E("STUB_SIM_INSPECT_NO_ANSWER") and begun >= int(E("STUB_SIM_INSPECT_NO_ANSWER")):   # the daemon's error, aw-sim still alive
            no_answer()
        if E("STUB_SIM_INSPECT_WARNS"):                     # docker's own answer on stdout, a warning beside it
            sys.stderr.write("WARNING: Error loading config file: the stand-in's warning\n")
    c = load(name)
    if c is None:                                   # docker's own: an empty line on stdout beside the words on stderr
        print()
        sys.stderr.write(ABSENT.get(E("STUB_ABSENT_WORDS"), ABSENT[None]) % name)
        sys.exit(1)
    if E("STUB_REQUEST_EMPTY") == name:
        c["request"] = ""
    out = fmt.replace("{{.HostConfig.CpusetCpus}}", c["request"]).replace("{{.State.Pid}}", str(c["pid"] if c["running"] else 0))
    out = out.replace("{{.State.Running}}", "true" if c["running"] else "false").replace("{{.State.OOMKilled}}", "false")
    out = out.replace("{{.State.ExitCode}}", str(c["exit"]))
    print(out)
elif cmd == "rm":
    for n in argv[1:]:
        if n.startswith("-"):
            continue
        try:
            os.remove(path(n))
        except OSError:
            pass
elif cmd == "kill":
    for n in argv[1:]:
        c = load(n)
        if c:
            c["running"] = False
            c["exit"] = 137
            save(c)
elif cmd == "stats":
    print("aw-sim\t1%\t1GiB / 3GiB")
'''

_RIG_STUBS = {
    "sudo": r'''printf 'sudo %s\n' "$*" >> "$STUB_DIR/calls.log"
[ "${1:-}" = -n ] || { echo "sudo: a terminal is required" >&2; exit 1; }
shift
exec "$@"
''',
    "id": r'''if [ "$*" = -nG ]; then printf '%s\n' "${STUB_GROUPS-}"; exit 0; fi
exec "$(PATH="$STUB_REAL_PATH" command -v id)" "$@"
''',
    "pgrep": r'''printf 'pgrep %s\n' "$*" >> "$STUB_DIR/calls.log"
[ "$*" = "-x qemu-system-aar" ] || exit 1
[ -e "$STUB_DIR/state/qemu" ] && { echo 4242; exit 0; }
exit 1
''',
    "pkill": r'''printf 'pkill %s\n' "$*" >> "$STUB_DIR/calls.log"
[ -e "$STUB_DIR/state/qemu" ] || exit 1
rm -f "$STUB_DIR/state/qemu"
''',
    # a second line when g1.json is already written: the sync that follows the record is one a test can see. And a copy of the drive log as
    # this call found it, numbered by the call's place among the `sync` lines: which rows a sync had still to flush.
    "sync": r'''printf 'sync\n' >> "$STUB_DIR/calls.log"
[ ! -e "$OUT/g1.json" ] || printf 'sync after g1.json\n' >> "$STUB_DIR/calls.log"
[ ! -e "$OUT/drives.tsv" ] || cp "$OUT/drives.tsv" "$STUB_DIR/sync-drives-$(grep -c '^sync$' "$STUB_DIR/calls.log")"
''',
    "sleep": 'printf "%s\\n" "$*" >> "$STUB_DIR/sleeps.log"\nexec "$(PATH="$STUB_REAL_PATH" command -v sleep)" 0.01\n',
    # the date a deadline check reads: far past the deadline once a drive has written the marker; every other call is the real date's
    "date": r'''if [ "${1:-}" = +%s ] && [ -e "$STUB_DIR/state/deadline-passed" ]; then echo 99999999999; exit 0; fi
exec "$(PATH="$STUB_REAL_PATH" command -v date)" "$@"
''',
    # set-property moves the stand-in daemon's cores, as the real property moves a unit's cgroup; everything else as without this stub
    "systemctl": r'''printf 'systemctl %s\n' "$*" >> "$STUB_DIR/calls.log"
if [ "${1:-}" = set-property ]; then
	[ -z "${STUB_SET_PROPERTY_FAILS:-}" ] || exit 1
	[ "${2:-}" = --runtime ] || exit 1
	case "${3:-}" in docker.service) pid=812 ;; containerd.service) pid=700 ;; *) exit 1 ;; esac
	case "${4:-}" in AllowedCPUs=?*) ;; *) exit 1 ;; esac
	sed -i "s/^Cpus_allowed_list:.*/Cpus_allowed_list:\t${4#AllowedCPUs=}/" "$PROC_ROOT/$pid/status"
	exit 0
fi
real="$(PATH="$STUB_REAL_PATH" command -v systemctl)" || { echo inactive; exit 3; }
exec "$real" "$@"
''',
    "ip": r'''printf 'ip %s\n' "$*" >> "$STUB_DIR/calls.log"
[ "$*" = "-br link show lo" ] || exit 1
echo "lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP> "
''',
    "sysctl": r'''printf 'sysctl %s\n' "$*" >> "$STUB_DIR/calls.log"
[ "${1:-}" = -n ] || exit 255
case "${2:-}" in
	net.core.rmem_max) if [ -n "${STUB_RMEM_AFTER:-}" ] && [ -e "$STUB_DIR/state/drives" ]; then echo "$STUB_RMEM_AFTER"; else echo 212992; fi ;;
	net.ipv4.ipfrag_time) echo 30 ;;
	net.ipv4.ipfrag_high_thresh) echo 4194304 ;;
	*) exit 255 ;;
esac
''',
    "taskset": r'''printf 'taskset %s\n' "$*" >> "$STUB_DIR/calls.log"
[ "$1" = -c ] || exit 1
shift 2
exec "$@"
''',
    "nvpmodel": 'echo "NV Power Mode: 25W"\n',
    # the :7150 readiness connect answered here; everything else the real timeout
    # every other call logged with its bound, so that a test reads which commands run under which bound; STUB_RUN_TIMEOUT_S shortens
    # the 120 s of a `docker run` for the cases where dockerd hangs, STUB_WAIT_TIMEOUT_S a drive's `docker wait` and STUB_INSPECT_TIMEOUT_S
    # the inspect after its bound
    "timeout": r'''case "$*" in
	*/dev/tcp/*) exit 0 ;;
	"120 docker run "*) [ -z "${STUB_RUN_TIMEOUT_S:-}" ] || set -- "$STUB_RUN_TIMEOUT_S" "${@:2}" ;;
	"600 docker wait "*) [ -z "${STUB_WAIT_TIMEOUT_S:-}" ] || set -- "$STUB_WAIT_TIMEOUT_S" "${@:2}" ;;
	"60 docker inspect -f {{.State.Running}} aw-scenario") [ -z "${STUB_INSPECT_TIMEOUT_S:-}" ] || set -- "$STUB_INSPECT_TIMEOUT_S" "${@:2}" ;;
esac
printf 'timeout %s\n' "$*" >> "$STUB_DIR/calls.log"
exec "$(PATH="$STUB_REAL_PATH" command -v timeout)" "$@"
''',
}

_RIG_LAUNCH = r'''#!/usr/bin/env bash
printf 'launch %s\n' "$IFS_BIN" >> "$STUB_DIR/calls.log"
mkdir -p "$(dirname "$LOG")"
[ -z "${STUB_BOOT_FAILS:-}" ] || exit 1
touch "$STUB_DIR/state/qemu"
mkdir -p "$PROC_ROOT/4242"
echo 0 > "$PROC_ROOT/4242/oom_score_adj"
printf 'monitor: boot\n%s\n' "$STUB_RULES_LINE" > "$LOG"
'''
_RIG_REPIN = r'''#!/usr/bin/env bash
printf 'repin %s\n' "$*" >> "$STUB_DIR/calls.log"
echo "repin tag=$1 cores=0-2 qemu=4242 threads=9 off_before=0 pin_failed=0 gone=0 threads_after=9 off_after=0 on_cores=yes"
'''
_RIG_PROBE = r'''#!/usr/bin/env python3
import os
print('RESULT {"bad": 0, "rejected_by_monitor": %s}' % os.environ.get("STUB_PROBE_REJECTED", "0"))
'''
_RIG_SYNTH = r'''#!/usr/bin/env python3
import os, sys
with open(os.environ["STUB_DIR"] + "/calls.log", "a") as f:
    f.write("ctlsynth " + " ".join(sys.argv[1:]) + "\n")
if os.environ.get("STUB_EXCHANGE_FAILS"):
    sys.exit(1)
if os.environ.get("STUB_EXCHANGE_MISS"):    # the monitor's liveness miss that the exchange's own close gives, on the console
    console = sys.argv[sys.argv.index("--console") + 1]
    with open(console, "a") as f:
        f.write("monitor: LIVENESS MISS: no claim for 512 ms since seq=1 (deadline 500 ms, miss 1)\n")
'''
# The rig's watchdog: the real one's series and stop file, on the rig's clock file.
_RIG_WATCHDOG = r'''#!/usr/bin/env python3
import argparse, os, signal, sys, time
ap = argparse.ArgumentParser()
ap.add_argument("--series")
ap.add_argument("--stop-file")
ap.add_argument("--scopes")
ap.add_argument("--max-s")
a = ap.parse_args()
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
STUB = os.environ["STUB_DIR"]
with open(STUB + "/calls.log", "a") as f:
    f.write("watchdog %s\n" % " ".join(sys.argv[1:]))
last = None
series = open(a.series, "a", buffering=1)
end = time.time() + 120
while time.time() < end:
    with open(os.environ["QNX_CLOCK_FILE"]) as f:
        m, w = (int(x) for x in f.read().split())
    if os.path.exists(STUB + "/state/dog-die"):
        sys.exit(0)
    if os.path.exists(STUB + "/state/dog-freeze"):      # alive, and no more lines: a series that has stopped growing
        time.sleep(0.005)
        continue
    t = m if last is None else last + 10 ** 9
    while t <= m:
        series.write("R %d %d %s\n" % (t, w, os.environ.get("STUB_SERIES_KB", "3000000")))
        last = t
        t += 10 ** 9
    if os.path.exists(STUB + "/state/dog-stop"):
        os.remove(STUB + "/state/dog-stop")
        series.write("E %d %d stop floor_kb=716800 avail_kb=700000\n" % (m, w))
        for n in os.listdir(STUB + "/state/docker"):
            os.system("docker kill %s >/dev/null 2>&1" % n[:-5])
    time.sleep(0.005)
'''


RIG_EXIT_POLL_S = "0.01"     # the one line of the harness the rig changes (THE HARNESS'S RIG above)


class Rig:
    """The harness's world (THE HARNESS'S RIG above)."""

    def __init__(self, base, real_watchdog=False, vss_host="c7g-metal", plan="main", exit_poll=RIG_EXIT_POLL_S):
        self.base = base
        self.plan = plan
        self.vss_host = vss_host
        self.repo = base / "w" / "repo"
        self.g = self.repo / "orin-native" / "gpu-concurrency"
        self.stem = base / "w" / "rec" / "aw-g1"
        self.out = self.stem / "raw"
        self.status = self.stem / "status"
        self.runlog = self.stem / "run.log"
        self.vss_home = base / "w" / "sdv"
        self.stub = base / "stub"
        self.proc = base / "proc"
        self.sys = base / "sys"
        for d in (self.g, self.stem, self.vss_home, self.stub / "state", self.proc, self.sys, base / "w" / "img", base / "home", base / "tmp"):
            os.makedirs(str(d), exist_ok=True)
        for f in ("run-aw-g1.sh", "aw_g1.py", "aw_suite.py", "aw_setup.py", "vss_setup.py", "lib-vss-deadline.sh", "lib-measure.sh"):
            shutil.copy(os.path.join(G, f), str(self.g / f))
        if exit_poll is not None:
            with open(HARNESS, encoding="utf-8", newline="") as f:
                text = f.read()
            assert text.count("\nEXIT_POLL_S=1\n") == 1
            with open(str(self.g / "run-aw-g1.sh"), "w", encoding="utf-8", newline="") as f:
                f.write(text.replace("\nEXIT_POLL_S=1\n", "\nEXIT_POLL_S=%s\n" % exit_poll))
        for name, body in (("launch-qnx-kvm-bridged.sh", _RIG_LAUNCH), ("vss-repin.sh", _RIG_REPIN), ("latency_probe.py", _RIG_PROBE)):
            self._w(self.g / name, body, 0o755)
        shutil.copytree(AW, str(self.repo / "sdv" / "aw"))
        os.chmod(str(self.repo / "sdv" / "aw" / "aw-entrypoint.sh"), 0o755)
        if not real_watchdog:
            self._w(self.repo / "sdv" / "aw" / "g1_watchdog.py", _RIG_WATCHDOG)
        os.makedirs(str(self.repo / "sdv" / "ctl" / "scenarios"))
        for n in ("ctl_claim_node.py", "aw_scenario.py"):
            shutil.copy(os.path.join(CTL, n), str(self.repo / "sdv" / "ctl" / n))
        self._w(self.repo / "sdv" / "ctl" / "ctlsynth.py", _RIG_SYNTH)
        files = {"lanelet2_map.osm": b"<osm/>\n", "map_config.yaml": b"a: 1\n", "map_projector_info.yaml": b"p: M\n",
                 "pointcloud_map.pcd": b"# pcd\n"}
        with open(os.path.join(CTL, "scenarios", "sample-lanelet-102.json"), encoding="utf-8") as f:
            sc = json.load(f)
        sc["map"]["files"] = {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
        self._w(self.repo / "sdv" / "ctl" / "scenarios" / "sample-lanelet-102.json", json.dumps(sc))
        for n, b in files.items():
            p = self.vss_home / "aw" / "map" / sc["map"]["name"] / n
            os.makedirs(str(p.parent), exist_ok=True)
            p.write_bytes(b)
        os.makedirs(str(self.repo / "sdv" / "stack"))
        shutil.copy(os.path.join(REPO, "sdv", "stack", "images.json"), str(self.repo / "sdv" / "stack" / "images.json"))
        self._w(self.vss_home / "gen" / "vss_ctl.py", "DIGEST = %s\nCOMPILED_PROFILE_IDS = (1, 2)\n" % DIGEST)
        (base / "w" / "img" / "ifs-ctl.bin").write_bytes(b"ifs")
        (base / "w" / "img" / "disk-qemu").write_bytes(b"disk")
        for name, body in _RIG_STUBS.items():
            self._w(self.stub / name, "#!/usr/bin/env bash\n" + body, 0o755)
        self._w(self.stub / "docker", _RIG_DOCKER, 0o755)
        self.clock = base / "clock"
        self.clock.write_text("%d %d\n" % (900 * S, 1800000000 * S))
        self.deadline = base / "deadline"
        self.deadline.write_text(str(int(time.time()) + 3 * 3600))
        self.meminfo = base / "meminfo"
        self.meminfo.write_text("MemTotal: 8000000 kB\nMemAvailable: 3000000 kB\nCached: 100 kB\n")
        self.vmstat = base / "vmstat"
        self.vmstat.write_text("pgfault 1\noom_kill 5\n")
        self.daemons()

    @staticmethod
    def _w(p, body, mode=None):
        os.makedirs(str(p.parent), exist_ok=True)
        with open(str(p), "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        if mode:
            os.chmod(str(p), mode)

    def daemons(self, dockerd="3,5", containerd="3,5"):
        for pid, a0, cores in ((812, "dockerd", dockerd), (700, "containerd", containerd)):
            d = self.proc / str(pid)
            os.makedirs(str(d), exist_ok=True)
            (d / "cmdline").write_bytes(("/usr/bin/%s\0" % a0).encode())
            (d / "status").write_text("Name:\t%s\nCpus_allowed_list:\t%s\n" % (a0, cores))

    def env(self, **cfg):
        drop = {k for k in os.environ if k.startswith(("STUB_", "VSS_", "SDV_", "QNX_", "AW_", "G1_"))} | {
            "PLAN", "STATUS", "OUT", "IFS_BIN", "DISK", "W"}
        e = {k: v for k, v in os.environ.items() if k not in drop}
        e.update(W=str(self.base / "w"), IFS_BIN=str(self.base / "w" / "img" / "ifs-ctl.bin"), DISK=str(self.base / "w" / "img" / "disk-qemu"),
                 OUT=str(self.out), VSS_HOME=str(self.vss_home), STATUS=str(self.status), PLAN=self.plan, VSS_HOST=self.vss_host,
                 QNX_METAL_DEADLINE_FILE=str(self.deadline), QNX_MEMINFO_FILE=str(self.meminfo), QNX_VMSTAT_FILE=str(self.vmstat),
                 QNX_STAT_FILE=str(self.meminfo), QNX_CLOCK_FILE=str(self.clock), QNX_L4T_RELEASE_FILE=str(self.base / "nv_tegra_release"),
                 QNX_DT_COMPATIBLE_FILE=str(self.base / "dt-compatible"), PROC_ROOT=str(self.proc), SYS_ROOT=str(self.sys),
                 SYSFS_CPU=str(self.base / "nocpu"), EMC_BPMP=str(self.base / "noemc"), EMC_CCF=str(self.base / "noemc"),
                 DEVFREQ_ROOT=str(self.base / "nodev"), PATH=str(self.stub) + os.pathsep + os.environ["PATH"], STUB_DIR=str(self.stub),
                 STUB_REAL_PATH=os.environ["PATH"], STUB_GROUPS="ubuntu docker", HOME=str(self.base / "home"), TMPDIR=str(self.base / "tmp"),
                 STUB_RULES_LINE=RULES_LINE % DIGEST, PYTHONDONTWRITEBYTECODE="1", STUB_STOP_FILE=str(self.out / "watchdog.stop"))
        for k, v in cfg.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = str(v)
        return e

    def run(self, timeout=240, **cfg):
        with open(str(self.runlog), "ab") as log:
            p = subprocess.run([BASH, str(self.g / "run-aw-g1.sh")], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                               cwd=str(self.g), env=self.env(**cfg), timeout=timeout)
        return Done(self, p.returncode)


class Done:
    def __init__(self, rig, rc):
        self.rig, self.rc = rig, rc
        self.log = rig.runlog.read_text(encoding="utf-8", errors="replace")
        self.status = rig.status.read_text(encoding="utf-8").splitlines() if rig.status.exists() else []
        p = rig.stub / "calls.log"
        self.calls = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        p = rig.stub / "docker-calls.jsonl"
        self.docker = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
        p = rig.out / "verdict.txt"
        self.verdict = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        self.arm = {}
        p = rig.out / "arm.tsv"
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                k, _t, v = ln.partition("\t")
                self.arm[k] = v
        p = rig.out / "g1.json"
        self.doc = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def why(self):
        return "rc %s status %s\n%s\n%s" % (self.rc, self.status, "\n".join(self.verdict), self.log[-4000:])

    def v(self):
        for x in self.verdict:
            if x.startswith("verdict:"):
                return x
        return ""

    def idx(self, pattern):
        for i, c in enumerate(self.calls):
            if re.search(pattern, c):
                return i
        return -1

    def runs(self, name=None):
        out = [a for a in self.docker if a and a[0] == "run"]
        return [a for a in out if name is None or _opt(a, "--name") == name]

    def rows(self):
        p = self.rig.out / "drives.tsv"
        return p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    def begun(self):
        """The drives that began: the driver is resident, so its `docker run`s do not count them."""
        return sum(1 for x in self.rows() if x.startswith("begin\t"))


def _opt(argv, k):
    return argv[argv.index(k) + 1] if k in argv else None


def _opts(argv, k):
    return [argv[i + 1] for i, a in enumerate(argv) if a == k]


@pytest.fixture(scope="module")
def whole(tmp_path_factory):
    return Rig(tmp_path_factory.mktemp("g1-whole")).run()


@linux_only
def test_a_whole_arm_ends_done_with_a_pass_on_stand_ins(whole):
    assert whole.rc == 0 and whole.status[-1] == "status=DONE", whole.why()
    assert whole.v() == "verdict: PASS", whole.why()
    assert whole.doc["status"] == "DONE" and whole.doc["harness"] == "run-aw-g1.sh"
    assert whole.arm["harness_end"] == "status=DONE" and whole.arm["loop_end"] == "reached"


@linux_only
def test_the_order_of_a_whole_arm(whole):
    idx = whole.idx
    assert 0 <= idx(r"^watchdog ") < idx(r"^launch "), whole.calls
    assert idx(r"^docker image inspect") < idx(r"^watchdog ")
    assert idx(r"^launch ") < idx(r"^repin boot") < idx(r"^sudo -n tee .*oom_score_adj") < idx(r"^ctlsynth ") < idx(r"^docker run .*--name aw-sim")
    run = r"^docker run .*--name %s"
    assert idx(run % "aw-sim") < idx(run % "aw-claim-node") < idx(run % "aw-g1-diag") < idx(run % "aw-scenario")
    stop = r"^docker stop .*%s"
    assert idx(run % "aw-scenario") < idx(stop % "aw-claim-node") < idx(stop % "aw-g1-diag") < idx(stop % "aw-sim") < idx(stop % "aw-scenario")
    assert idx(stop % "aw-scenario") < idx(r"^docker rm -f aw-sim"), whole.calls


@linux_only
def test_the_host_recorders_run_on_core_4_by_this_script_never_by_a_login(whole):
    for pat in ("g1_watchdog.py", "g1_sampler.py"):
        assert any(c.startswith("taskset -c 4 ") and pat in c for c in whole.calls), (pat, whole.calls)
    assert not any(c.startswith(("ssh", "scp")) for c in whole.calls)


@linux_only
def test_the_stamp_is_written_under_g1_before_any_container_with_no_ladder(whole):
    stamp = json.loads((whole.rig.out / "stamp.json").read_text())
    assert stamp["platform"]["policy"] == "g1"
    assert (stamp["n"], stamp["k"], stamp["warmup"], stamp["interval_ms"]) == (0, 0, 0, 0)
    assert stamp["sample_window"] == 1 and "platform_after" in stamp
    assert int(whole.arm["stamp_mono_ns"]) <= int(whole.arm["first_container_mono_ns"])
    assert "0 means no ladder" in stamp["ladder"]


@linux_only
def test_every_container_is_under_2_12_with_its_limits_label_and_cores(whole):
    names = {_opt(a, "--name") for a in whole.runs()}
    assert names == {"aw-sim", "aw-claim-node", "aw-g1-diag", "aw-scenario"}
    aw = str(whole.rig.repo / "sdv" / "aw")
    for a in whole.runs():
        name = _opt(a, "--name")
        assert _opt(a, "--entrypoint") == "/sdv-aw/aw-entrypoint.sh" and "%s:/sdv-aw:ro" % aw in _opts(a, "-v"), a
        assert _opt(a, "--user") == "aw" and _opt(a, "--cap-drop") == "ALL" and _opt(a, "--security-opt") == "no-new-privileges", a
        assert "--privileged" not in a and "--cap-add" not in a, a
        assert not any(":/proc" in v or ":/sys" in v for v in _opts(a, "-v")), a
        assert _opt(a, "--cpuset-cpus") == "3,5", a
        want = "3200m" if name == "aw-sim" else "256m"
        assert _opt(a, "--memory") == want and _opt(a, "--memory-swap") == want, a
        assert "sdv.aw.run=g1" in _opts(a, "--label"), a
        assert _opt(a, "--network") == "host", a


@linux_only
def test_the_harness_never_sets_a_sysctl_or_lo_multicast(whole):
    bad = [c for c in whole.calls if (c.startswith("sysctl ") and not c.startswith("sysctl -n ")) or re.search(r"^ip .*(set|multicast)", c)]
    assert not bad, bad


@linux_only
def test_the_guests_oom_score_adj_is_set_through_sudo_tee_and_read_back(whole):
    assert any(re.match(r"^sudo -n tee .*/4242/oom_score_adj", c) for c in whole.calls), whole.calls
    assert whole.arm["oom_score_adj"] == "-1000"


@linux_only
def test_each_container_is_placed_and_its_scope_listed_for_the_watchdog(whole):
    rows = [x.split("\t") for x in (whole.rig.out / "placement.tsv").read_text().splitlines()]
    assert [r[0] for r in rows[:3]] == ["aw-sim", "aw-claim-node", "aw-g1-diag"]
    assert all(r[1] == "3,5" and r[2] == "3,5" for r in rows)
    assert [r[0] for r in rows[3:]] == ["aw-scenario"], rows       # PR's dated section, item 15: its one start
    scopes = (whole.rig.out / "scopes.txt").read_text().splitlines()
    assert any(x.startswith("aw-sim\t") and x.endswith("docker-aw-sim.scope") for x in scopes), scopes


@linux_only
def test_each_container_start_is_followed_by_a_repin_with_its_name(whole):
    for n in ("aw-sim", "aw-claim-node", "aw-g1-diag"):
        assert whole.idx(r"^docker run .*--name %s" % n) < whole.idx(r"^repin %s$" % n), whole.calls
    assert (whole.rig.out / "repin.txt").read_text().count("repin tag=") >= 4
    # Repin after every container start, including the resident driver's start.
    assert whole.idx(r"^docker run .*--name aw-scenario") < whole.idx(r"^repin aw-scenario$"), whole.calls
    assert whole.calls.count("repin aw-scenario") == 1, whole.calls


@linux_only
def test_memory_events_and_vmstat_are_read_at_the_loops_end_before_any_stop(whole):
    rows = dict(x.split("\t") for x in (whole.rig.out / "memory-events-end.tsv").read_text().splitlines())
    assert rows["aw-sim"] == "0" and rows["aw-claim-node"] == "0" and rows["aw-g1-diag"] == "0"
    assert "oom_kill" in (whole.rig.out / "vmstat-end.txt").read_text()
    assert "oom_kill" in (whole.rig.out / "vmstat-before.txt").read_text()


@linux_only
def test_oomkilled_is_recorded_for_each_container_at_the_loops_end_as_information(whole):
    """PR section 5, T1: `OOMKilled` is recorded as information only. The stand-in says false for each container that is there, and the
    count recorder's name is not a container of the main arm: `none`."""
    for n in ("aw-sim", "aw-claim-node", "aw-g1-diag"):
        assert whole.arm["oomkilled_%s" % n] == "false", whole.arm
    assert whole.arm["oomkilled_aw-g1-count"] == "none", whole.arm


@linux_only
def test_the_guest_idle_read_is_in_the_record_before_the_first_container(whole):
    assert "MemAvailable" in (whole.rig.out / "guest-idle.txt").read_text()


@linux_only
def test_the_clock_pair_is_read_in_one_action_on_each_side(whole):
    text = (whole.rig.out / "clock-pairs.txt").read_text().splitlines()
    assert [x.split()[0] for x in text] == ["host", "container"]


@linux_only
def test_the_sweep_leaves_nothing_and_the_host_check_is_kept(whole):
    d = whole.rig.stub / "state" / "docker"
    assert not os.listdir(str(d))
    assert (whole.rig.out / "hc-before.txt").read_text() == (whole.rig.out / "hc-after.txt").read_text()
    assert not (whole.rig.stub / "state" / "qemu").exists()


@linux_only
@pytest.mark.parametrize("rc", ["1", "125"])
def test_a_docker_stop_of_the_claim_node_with_no_answer_reaches_the_judge_from_the_harness(tmp_path, rc):
    """PR's dated section, item 13, through the harness: the stop of the claim node gets no answer (the container is not signalled and writes
    no summary), and the exit the harness recorded in arm.tsv is all the judge's branch reads."""
    rig = Rig(tmp_path)
    d = rig.run(STUB_STOP_FAILS="aw-claim-node", STUB_STOP_FAIL_RC=rc)
    assert d.status[-1] == "status=DONE" and d.arm["loop_end"] == "reached" and d.arm["claim_stop_exit"] == rc, d.why()
    assert d.v().startswith("verdict: NOT JUDGED") and "T6: no reading" in d.v() and "exited %s" % rc in d.v(), d.why()
    assert d.verdict[-1].startswith("re-run: allowed"), d.why()


@linux_only
def test_a_stop_the_sweep_could_not_verify_is_recorded_and_leaves_the_status_line_alone(tmp_path):
    d = Rig(tmp_path).run(STUB_PS_FAILS_AFTER_DRIVES="1", STUB_DRIVE_NO_ROUTE="1")
    assert "could not be listed" in d.arm.get("stop_unverified", ""), d.why()
    assert d.status[-1] == "status=DONE", d.why()


@linux_only
def test_no_recorder_is_left_behind(whole):
    for name in ("watchdog.pid", "sampler.pid"):
        p = whole.rig.vss_home / "aw-g1-work" / name
        pid = int(p.read_text())
        assert not os.path.exists("/proc/%d" % pid) or "Z" in open("/proc/%d/stat" % pid).read().split()[2], name


@linux_only
def test_every_file_of_the_record_is_on_captures_whitelist_and_a_ros_log_never_is(whole):
    import ast
    import fnmatch
    path = os.path.join(REPO, "scripts", "aws", "capture.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] in (["VSS_WHITELIST"], ["NEVER_DIRS"], ["NEVER_FILES"]):
            exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), {}, ns)
        if isinstance(node, ast.FunctionDef) and node.name == "vss_excluded":
            exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), {"fnmatch": fnmatch}, ns)
    excluded = ns["vss_excluded"]
    excluded.__globals__.update(VSS_WHITELIST=ns["VSS_WHITELIST"], NEVER_DIRS=ns["NEVER_DIRS"], NEVER_FILES=ns["NEVER_FILES"])
    stem = whole.rig.stem
    n = 0
    for root, _d, files in os.walk(str(stem)):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), str(stem.parent)).replace(os.sep, "/")
            assert excluded(rel) == "", rel
            n += 1
    assert n > 15
    assert not any(d == "ros-log" for _r, ds, _f in os.walk(str(stem)) for d in ds)


@linux_only
@pytest.mark.parametrize("governor, state", [("performance", "pinned"), ("schedutil", "not-pinned")])
def test_the_stamp_reads_the_helpers_governor_pin_and_changes_nothing(tmp_path, governor, state):
    rig = Rig(tmp_path)
    for c in range(2):
        d = tmp_path / "cpu" / ("cpu%d" % c) / "cpufreq"
        d.mkdir(parents=True)
        (d / "scaling_governor").write_text(governor + "\n")
        (d / "scaling_cur_freq").write_text("1344000\n")
    d = rig.run(SYSFS_CPU=tmp_path / "cpu", STUB_DRIVE_NO_ROUTE="1")
    stamp = json.loads((rig.out / "stamp.json").read_text())
    assert stamp["governor_state"] == state and stamp["governor_before"] == governor and stamp["governor_after"] == governor, d.why()
    assert (tmp_path / "cpu" / "cpu0" / "cpufreq" / "scaling_governor").read_text().strip() == governor


@linux_only
def test_the_stamp_marks_the_orin_only_reads_absent_off_the_orin(whole):
    stamp = json.loads((whole.rig.out / "stamp.json").read_text())
    assert stamp["governor_state"] == "absent" and stamp["emc_bpmp"] == "absent" and stamp["vss_host"] == "c7g-metal"
    assert stamp["platform"]["nvpmodel"]
    lines = (whole.rig.out / "clk-g1.log").read_text().splitlines()
    assert all(re.match(r"^[0-9.]+ emc_bpmp_hz= emc_ccf_hz= gpu_hz=$", x) for x in lines)


@linux_only
def test_the_harness_ends_done_on_a_fail_and_a_timed_out_drive_does_not_end_the_loop(tmp_path):
    d = Rig(tmp_path).run(STUB_DRIVE_TIMEOUT="2")
    assert d.rc == 0 and d.status[-1] == "status=DONE", d.why()
    assert d.v().startswith("verdict: FAIL") and "T7" in d.v(), d.why()
    assert d.begun() > 2 and len(d.runs("aw-scenario")) == 1, "the next drive begins, on the same driver\n" + d.why()


@linux_only
def test_a_first_drive_with_no_route_ends_the_loop(tmp_path):
    d = Rig(tmp_path).run(STUB_DRIVE_NO_ROUTE="1")
    assert d.rc == 0 and d.status[-1] == "status=DONE", d.why()
    assert d.begun() == 1 and d.arm["loop_end"] == "first-no-route", d.why()
    assert d.v().startswith("verdict: FAIL"), d.why()


@linux_only
def test_a_later_drive_with_no_route_does_not_end_the_loop(tmp_path):
    d = Rig(tmp_path).run(STUB_DRIVE_NO_ROUTE="2")
    assert d.begun() > 2 and d.arm["loop_end"] == "reached", d.why()
    assert "T7" in d.v(), d.why()


@linux_only
def test_a_first_drive_whose_route_line_timed_out_ends_the_loop_as_first_no_route_with_its_frames_kept(tmp_path):
    """The route line is there, of outcome timeout, and the claim node's frames go on: it is no route, so `first-route` finds none."""
    rig = Rig(tmp_path)
    d = rig.run(STUB_DRIVE_ROUTE_TIMEOUT="1")
    assert d.rc == 0 and d.status[-1] == "status=DONE", d.why()
    assert d.begun() == 1 and d.arm["loop_end"] == "first-no-route" and "first_route_mono_ns" not in d.arm, d.why()
    route = [json.loads(x) for x in (rig.out / "drives" / "d001" / "scenario.jsonl").read_text().splitlines() if '"route"' in x]
    assert [x["outcome"] for x in route] == ["timeout"], route
    assert sum('"seq"' in x for x in (rig.out / "claim" / "run" / "replies.jsonl").read_text().splitlines()) > 100, d.why()
    assert d.v().startswith("verdict: FAIL") and "T7" in d.v(), d.why()


@linux_only
def test_a_smoke_of_7100_that_the_monitor_rejected_ends_failed_at_the_guest_and_starts_no_container(tmp_path):
    d = Rig(tmp_path).run(STUB_PROBE_REJECTED="1")
    assert not d.runs() and d.status[-1] == "status=FAILED at=guest" and d.rc == 1, d.why()
    assert d.arm["smoke_7100"] == "exit=0 result_line=yes bad=0 rej=1", d.why()
    assert ":7100's smoke failed" in d.doc["reason"] and "rej 1" in d.doc["reason"], d.doc
    assert d.v().startswith("verdict: NOT JUDGED"), d.why()


@linux_only
def test_a_stop_file_written_during_the_simulators_wait_ends_the_polls(tmp_path):
    """The simulator never lists its services, and the watchdog fires during the first poll: the wait ends there, not at its 1200 s, and the
    loop is over before its first drive."""
    d = Rig(tmp_path).run(STUB_SIM_NOT_UP="1", STUB_SIM_WAIT_STOPS="1")
    assert d.arm["sim_up"] == "false" and d.arm["sim_polls"] == "1" and int(d.arm["sim_up_s"]) < 300, d.why()
    assert d.arm["loop_end"] == "watchdog-stop" and not d.runs("aw-scenario"), d.why()
    assert d.status[-1] == "status=DONE", d.why()


@linux_only
def test_a_dead_aw_sim_ends_the_loop_and_fails_t7(tmp_path):
    d = Rig(tmp_path).run(STUB_SIM_DIES_AFTER_DRIVE="2")
    assert d.arm["loop_end"] == "sim-died" and d.begun() == 2, d.why()
    assert d.status[-1] == "status=DONE" and "T7" in d.v(), d.why()


@linux_only
def test_an_inspect_of_aw_sim_with_no_answer_is_recorded_and_is_no_death(tmp_path):
    """PR's dated section, item 2: the container is alive, the daemon gave an error."""
    d = Rig(tmp_path).run(STUB_SIM_INSPECT_NO_ANSWER="1")
    assert d.arm["loop_end"] == "reached", d.why()
    assert d.arm["sim_inspect_unanswered"] == "exit 1", d.why()
    assert d.status[-1] == "status=DONE" and d.v() == "verdict: PASS", d.why()


@linux_only
def test_aw_sim_gone_by_dockers_own_answer_is_sim_died(tmp_path):
    d = Rig(tmp_path).run(STUB_SIM_GONE_AFTER_DRIVE="2")
    assert d.arm["loop_end"] == "sim-died" and d.begun() == 2, d.why()
    assert "sim_inspect_unanswered" not in d.arm, "docker's own lower-case `no such object` is its answer\n" + d.why()
    assert d.status[-1] == "status=DONE" and "T7" in d.v(), d.why()


@linux_only
def test_a_warning_beside_dockers_answer_is_not_read_as_a_death(tmp_path):
    d = Rig(tmp_path).run(STUB_SIM_INSPECT_WARNS="1")
    assert d.arm["loop_end"] == "reached" and "sim_inspect_unanswered" not in d.arm, d.why()


@linux_only
def test_a_daemon_whose_socket_file_is_gone_is_no_answer_and_no_death_of_aw_sim(tmp_path):
    """The client's words for a socket file that is not there hold `no such file or directory` and say nothing of a container: dockerd gave no
    answer, which PR's dated section, item 2, reads as no death. A match on `no such` alone reads aw-sim gone: a FAIL by a reading, never re-run."""
    d = Rig(tmp_path).run(STUB_SIM_INSPECT_NO_ANSWER="1", STUB_NO_ANSWER_WORDS="socket-gone")
    assert d.arm["loop_end"] == "reached" and d.arm["sim_inspect_unanswered"] == "exit 1", d.why()
    assert d.status[-1] == "status=DONE" and d.v() == "verdict: PASS", d.why()


@linux_only
def test_a_daemon_whose_socket_file_is_gone_is_not_judged_when_the_next_docker_call_fails_too(tmp_path):
    d = Rig(tmp_path).run(STUB_SIM_INSPECT_NO_ANSWER="1", STUB_NO_ANSWER_WORDS="socket-gone", STUB_WAIT_FAILS_AT_DRIVE="3")
    assert d.arm["loop_end"] == "docker-wait-failed" and d.arm["sim_inspect_unanswered"] == "exit 1", d.why()
    assert d.status[-1] == "status=DONE" and d.v().startswith("verdict: NOT JUDGED"), d.why()
    assert d.verdict[-1].startswith("re-run: allowed"), d.why()


@linux_only
@pytest.mark.parametrize("words", ["no-such-object", "no-such-container"])
def test_each_older_wording_of_a_container_that_is_not_there_is_the_death_of_aw_sim_too(tmp_path, words):
    """docker 29's `error: no such object` is read by test_aw_sim_gone_by_dockers_own_answer_is_sim_died; the clients before it said `Error: No such
    object` and `Error response from daemon: No such container`, and the harness reads aw-sim gone on either."""
    d = Rig(tmp_path).run(STUB_SIM_GONE_AFTER_DRIVE="2", STUB_ABSENT_WORDS=words)
    assert d.arm["loop_end"] == "sim-died" and d.begun() == 2 and "sim_inspect_unanswered" not in d.arm, d.why()
    assert d.status[-1] == "status=DONE" and "T7" in d.v(), d.why()


@linux_only
def test_a_dockerd_really_gone_reaches_the_next_docker_wait_and_is_not_judged(tmp_path):
    """PR's dated section, item 2 says the next `docker run`; with the driver resident (item 15) the next docker call a drive needs is its wait."""
    d = Rig(tmp_path).run(STUB_SIM_INSPECT_NO_ANSWER="1", STUB_WAIT_FAILS_AT_DRIVE="3")
    assert d.arm["loop_end"] == "docker-wait-failed" and d.arm["sim_inspect_unanswered"] == "exit 1", d.why()
    assert d.status[-1] == "status=DONE" and d.v().startswith("verdict: NOT JUDGED"), d.why()
    assert d.verdict[-1].startswith("re-run: allowed"), d.why()


@linux_only
def test_no_answer_during_the_simulators_wait_does_not_end_the_wait(tmp_path):
    d = Rig(tmp_path).run(STUB_SIM_NOT_UP="1", STUB_SIM_INSPECT_NO_ANSWER="0", STUB_DRIVE_NO_ROUTE="1")
    assert d.arm["sim_up"] == "false" and int(d.arm["sim_polls"]) > 1, d.why()
    assert d.arm["sim_inspect_unanswered"] == "exit 1" and d.arm["loop_end"] == "first-no-route", d.why()


@linux_only
def test_the_simulators_wait_records_its_elapsed_time_when_it_comes_up(whole):
    assert whole.arm["sim_up"] == "true" and whole.arm["sim_up_s"] == "1", whole.why()      # the stand-in's `docker run` takes 1 s


@linux_only
def test_a_simulator_that_never_lists_its_services_is_waited_for_1200_s(tmp_path):
    d = Rig(tmp_path).run(STUB_SIM_NOT_UP="1", STUB_DRIVE_NO_ROUTE="1")             # each poll takes 70 s on the rig's clock
    assert d.arm["sim_up"] == "false" and 1200 <= int(d.arm["sim_up_s"]) < 1300, d.why()
    assert d.arm["loop_end"] == "first-no-route", d.why()


@linux_only
def test_the_simulators_wait_counts_from_its_docker_run(tmp_path):
    d = Rig(tmp_path).run(STUB_SIM_NOT_UP="1", STUB_DRIVE_NO_ROUTE="1", STUB_SIM_RUN_ADVANCE_S="1150")
    assert d.arm["sim_polls"] == "1" and int(d.arm["sim_up_s"]) >= 1200, d.why()    # 1151 s of run, then one poll of 70 s


def test_the_harness_holds_prs_simulators_wait():
    with open(HARNESS, encoding="utf-8") as f:
        text = f.read()
    with open(PREREG, encoding="utf-8") as f:
        pr = f.read()
    assert "is 1200 s from its `docker run`" in pr
    assert re.search(r"^SIM_UP_S=1200; ", text, re.M)
    head = text.partition("\nset -u\n")[0]
    assert "SIM_UP_S 1200 s from its docker run" in head and "docker's own answer" in head, head


def _kill_rig_processes(rig):
    """What a harness killed outright leaves behind (its recorders): every process with this rig's STUB_DIR in its environment."""
    mark = ("STUB_DIR=%s" % rig.stub).encode()
    for p in os.listdir("/proc"):
        if not p.isdigit() or int(p) == os.getpid():
            continue
        try:
            with open("/proc/%s/environ" % p, "rb") as f:
                if mark in f.read().split(b"\0"):
                    os.kill(int(p), signal.SIGKILL)
        except OSError:
            continue


@linux_only
def test_a_harness_killed_outright_leaves_the_console_and_the_scopes_in_the_record_through_a_re_run(g1, tmp_path):
    """PR section 5: every arm's partial readings stay in the record; a re-run's rm -rf of its working directory takes none of them."""
    rig = Rig(tmp_path)
    try:
        d = rig.run(STUB_KILL_HARNESS_AFTER_DRIVE="2")
    finally:
        _kill_rig_processes(rig)
    assert d.rc != 0 and not d.status and "harness_end" not in d.arm, d.why()
    first = rig.out
    console, scopes = (first / "guest-console.log").read_bytes(), (first / "scopes.txt").read_bytes()
    assert (RULES_LINE % DIGEST).encode() in console and b"aw-sim\t" in scopes and b"aw-scenario\t" in scopes, d.why()
    j = _judge(g1, str(first))
    assert j.verdict == "NOT JUDGED" and "the harness exited before the loop's end" in _line(j, "verdict:"), j.lines
    assert _inst(j, "rules-digest").startswith("instrument rules-digest OK"), j.lines
    shutil.rmtree(str(rig.stub / "state"))
    os.makedirs(str(rig.stub / "state"))
    rig.stem = tmp_path / "w" / "rec" / "aw-g1-again"
    rig.out, rig.status, rig.runlog = rig.stem / "raw", rig.stem / "status", rig.stem / "run.log"
    os.makedirs(str(rig.stem))
    again = rig.run()
    assert again.status[-1] == "status=DONE", again.why()
    assert (first / "guest-console.log").read_bytes() == console and (first / "scopes.txt").read_bytes() == scopes


@linux_only
def test_a_work_that_cannot_be_removed_is_a_status_line_and_acts_on_no_old_marker(tmp_path):
    """A second arm whose first left files of another uid under its working directory: what is left may hold that arm's markers and pids."""
    rig = Rig(tmp_path)
    work = rig.vss_home / "aw-g1-work"
    os.makedirs(str(work / "state"))
    for marker in ("launched", "began", "confined", "hc-before", "clock-sampler"):
        (work / "state" / marker).write_text("")
    sleeper = subprocess.Popen(["sleep", "300"])
    try:
        (work / "watchdog.pid").write_text(str(sleeper.pid))
        (work / "sampler.pid").write_text(str(sleeper.pid))
        (rig.stub / "state" / "qemu").write_text("")
        Rig._w(rig.stub / "rm", """#!/usr/bin/env bash
if [ "$*" = "-rf %s" ]; then echo "rm: cannot remove: Permission denied" >&2; exit 1; fi
exec "$(PATH="$STUB_REAL_PATH" command -v rm)" "$@"
""" % work, 0o755)
        d = rig.run()
        assert d.rc == 1 and d.status[-1] == "status=FAILED at=preflight", d.why()
        assert "aw-g1-work" in d.v() and d.v().startswith("verdict: NOT JUDGED"), d.why()
        assert "cannot remove" in d.arm["harness_why"], d.why()
        assert not any(a[0] in ("run", "rm") for a in d.docker), d.docker
        assert sleeper.poll() is None, "an old pid file was acted on"
        assert d.idx(r"^pkill ") < 0 and d.idx(r"set-property") < 0, d.calls
        assert not os.listdir(str(tmp_path / "tmp")), "the fresh directory is gone"
    finally:
        sleeper.kill()
        sleeper.wait()


@linux_only
def test_the_stop_file_ends_the_loop_and_is_a_fail_never_not_judged(tmp_path):
    d = Rig(tmp_path).run(STUB_WATCHDOG_STOP_AFTER_DRIVE="2")
    assert d.arm["loop_end"] == "watchdog-stop" and d.begun() == 2, d.why()
    assert d.status[-1] == "status=DONE" and d.v().startswith("verdict: FAIL") and "T2" in d.v(), d.why()


@linux_only
def test_a_dead_watchdog_stops_the_loop_before_the_next_drive(tmp_path):
    d = Rig(tmp_path).run(STUB_WATCHDOG_DIES_AFTER_DRIVE="2")
    assert d.arm["loop_end"] == "watchdog-dead" and d.begun() == 2, d.why()
    assert d.status[-1] == "status=DONE" and d.v().startswith("verdict: NOT JUDGED"), d.why()


@linux_only
def test_a_watchdog_that_lives_and_whose_series_stops_growing_stops_the_loop_before_the_next_drive(tmp_path):
    """PR section 5: before each drive the harness checks that the watchdog lives AND that its series grows."""
    d = Rig(tmp_path).run(STUB_WATCHDOG_FREEZES_AT_DRIVE="2")
    assert d.arm["loop_end"] == "watchdog-dead" and 2 <= d.begun() <= 3, d.why()
    assert d.status[-1] == "status=DONE" and d.v().startswith("verdict: NOT JUDGED"), d.why()


@linux_only
def test_a_deadline_that_passes_in_the_loop_ends_it_as_the_deadline_and_the_status_is_a_timeout(tmp_path):
    """lib-vss-deadline.sh's check point, before each drive: stop cleanly, status=TIMEOUT, exit 0."""
    d = Rig(tmp_path).run(STUB_DEADLINE_PASSES_AFTER_DRIVE="2")
    assert d.arm["loop_end"] == "deadline" and d.begun() == 2, d.why()
    assert d.rc == 0 and d.status[-1] == "status=TIMEOUT at=arm reason=deadline", d.why()
    assert d.v().startswith("verdict: NOT JUDGED") and "the deadline stopped the loop" in d.v(), d.why()


@linux_only
def test_every_docker_run_and_each_drives_wait_runs_under_a_bound(whole):
    runs = [c.split() for c in whole.calls if c.startswith("timeout 120 docker run -d --name ")]
    plain = [c for c in whole.calls if c.startswith("docker run ")]
    assert len(runs) == len(plain) and {r[6] for r in runs} == {"aw-sim", "aw-claim-node", "aw-g1-diag", "aw-scenario"}, whole.calls
    drives = whole.begun()
    waits = [c for c in whole.calls if c == "timeout 600 docker wait aw-scenario"]     # DRIVE_BOUND_S: a driver that never answers
    assert drives > 2 and len(waits) == drives, whole.calls


@linux_only
@pytest.mark.parametrize("plan, name, row", [("main", "aw-sim", "sim_run_exit"), ("main", "aw-claim-node", "claim_run_exit"),
                                             ("main", "aw-g1-diag", "diag_run_exit"), ("guest-stopped", "aw-g1-count", "count_run_exit")])
def test_a_docker_run_that_never_returns_ends_under_its_bound_as_the_harness_own_exit(tmp_path, plan, name, row):
    """A dockerd that stops answering, on the cores the watchdog's cgroup.kill path exists for: the loop must not sit in `docker run`."""
    rig = Rig(tmp_path, plan=plan)
    d = rig.run(STUB_RUN_HANGS=name, STUB_RUN_TIMEOUT_S=3)
    assert d.rc == 1 and d.status[-1] == "status=FAILED at=arm", d.why()
    assert d.arm[row] == "124" and not d.runs("aw-scenario"), d.why()
    assert d.v().startswith("verdict: NOT JUDGED") and "docker run of %s exited 124" % name in d.v(), d.why()
    assert not os.listdir(str(rig.stub / "state" / "docker")), "the sweep removes what did start"


@linux_only
def test_a_drives_docker_run_that_never_returns_ends_the_loop_as_a_run_that_failed(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_RUN_HANGS_AT_DRIVE="1", STUB_RUN_TIMEOUT_S=3)
    assert d.rc == 0 and d.status[-1] == "status=DONE" and d.arm["loop_end"] == "docker-run-failed", d.why()
    assert (rig.out / "drives.tsv").read_text().splitlines()[-1] == "stopped\t1\tdocker-run-exit-124", d.why()
    assert d.v().startswith("verdict: NOT JUDGED") and "could not start a drive" in d.v(), d.why()


@linux_only
def test_a_sync_follows_every_drive_the_last_docker_stop_and_the_record(whole):
    """Board rule: sync after every run, before stopping QEMU. The record (g1.json, the verdict) gets one after it."""
    calls = whole.calls
    start = whole.idx(r"^docker run .*--name aw-scenario")
    first_stop = whole.idx(r"^docker stop ")
    assert whole.begun() > 2 and calls[start:first_stop].count("sync") == whole.begun(), "one sync per drive\n" + "\n".join(calls[start:first_stop])
    last_stop = max(i for i, c in enumerate(calls) if c.startswith("docker stop "))
    pkill = whole.idx(r"^pkill ")
    assert pkill > last_stop and "sync" in calls[last_stop:pkill], "a sync after the last docker stop and before QEMU's stop\n" + "\n".join(calls)
    assert "sync after g1.json" in calls, "a sync after the record is written"


@linux_only
def test_a_drives_end_row_is_written_after_the_sync_that_follows_its_container_not_before_it(whole):
    """PR's dated section, item 6 reads an `end` row as the drive's files having been synced (scenario.jsonl and replies.jsonl are not
    fsynced, and the row is what says the sync ran). The sync stand-in kept the drive log as each call found it: the first sync after a
    drive's answer is read finds that drive's `begin` row and not yet its `end` row, and the row is there once the drive is done."""
    calls = whole.calls
    start = whole.idx(r"^docker run .*--name aw-scenario")
    before = sum(1 for c in calls[:start] if c == "sync")
    final = whole.rows()
    assert whole.begun() > 2
    for k in range(1, whole.begun() + 1):
        nth = before + k                # the loop's only syncs are the drives', one each
        seen = (whole.rig.stub / ("sync-drives-%d" % nth)).read_text().splitlines()
        assert any(x.startswith("begin\t%d\t" % k) for x in seen), (k, seen)
        assert not any(x.startswith("end\t%d\t" % k) for x in seen), "the end row was written before the sync that follows the drive: %s" % seen
        assert any(x.startswith("end\t%d\t" % k) for x in final), (k, final)


@linux_only
def test_the_arm_is_bracketed_by_a_clock_pair_at_its_start_and_one_at_its_end(whole):
    start, end = whole.arm["arm_pair_start"].split(), whole.arm["arm_pair_end"].split()
    assert len(start) == len(end) == 2 and all(x.isdigit() for x in start + end), whole.arm
    assert int(end[0]) >= int(whole.arm["last_stop_mono_ns"]) > int(start[0]), whole.arm


@linux_only
def test_a_miss_the_exchange_gave_is_before_the_arms_part_of_the_console_and_no_finding(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_EXCHANGE_MISS="1")
    console = (rig.out / "guest-console.log").read_bytes()
    assert b"LIVENESS MISS" in console, d.why()
    assert int(d.arm["console_arm_from"]) == len(console) > 0, d.why()
    assert not any(x.startswith("finding MISS") for x in d.verdict) and d.v() == "verdict: PASS", d.why()


@linux_only
@pytest.mark.parametrize("cfg, word", [({"STUB_EFFECTIVE": "aw-sim=0-5"}, "effective"), ({"STUB_REQUEST_EMPTY": "aw-claim-node"}, "request")])
def test_a_container_off_3_5_stops_before_the_loop_and_is_not_judged(tmp_path, cfg, word):
    d = Rig(tmp_path).run(**cfg)
    assert d.arm["loop_end"] == "misplaced" and not d.runs("aw-scenario"), d.why()
    assert d.status[-1] == "status=DONE" and d.v().startswith("verdict: NOT JUDGED") and "placement" in d.v(), d.why()


@linux_only
def test_a_drive_container_off_3_5_stops_the_loop(tmp_path):
    d = Rig(tmp_path).run(STUB_EFFECTIVE="aw-scenario=4")
    assert d.arm["loop_end"] == "misplaced" and len(d.runs("aw-scenario")) == 1, d.why()
    assert d.v().startswith("verdict: NOT JUDGED"), d.why()


@linux_only
def test_a_stamp_that_refuses_stops_everything_and_is_not_judged(tmp_path):
    rig = Rig(tmp_path)
    rig.daemons(dockerd="0-5")
    d = rig.run()
    assert not d.runs() and d.idx(r"^launch ") < 0 and d.idx(r"^watchdog ") < 0, d.why()
    assert d.status[-1] == "status=FAILED at=stamp" and d.rc == 1, d.why()
    assert d.v().startswith("verdict: NOT JUDGED") and "stamp" in d.v(), d.why()
    assert "dockerd is running on cores" in (rig.out / "stamp.out").read_text()


@linux_only
def test_a_guest_that_does_not_boot_ends_failed_and_starts_no_container(tmp_path):
    d = Rig(tmp_path).run(STUB_BOOT_FAILS="1")
    assert not d.runs() and d.status[-1] == "status=FAILED at=guest" and d.rc == 1, d.why()
    assert d.v().startswith("verdict: NOT JUDGED"), d.why()


@linux_only
def test_a_failed_7150_exchange_ends_failed(tmp_path):
    d = Rig(tmp_path).run(STUB_EXCHANGE_FAILS="1")
    assert not d.runs() and d.status[-1] == "status=FAILED at=guest", d.why()


@linux_only
def test_a_rules_line_of_another_contract_is_refused_before_any_container(tmp_path):
    d = Rig(tmp_path).run(STUB_RULES_LINE=RULES_LINE % "0x87654321")
    assert not d.runs() and d.status[-1] == "status=FAILED at=guest", d.why()


@linux_only
def test_an_oom_score_adj_that_does_not_read_back_stops_before_any_container(tmp_path):
    rig = Rig(tmp_path)
    Rig._w(rig.stub / "tee", '#!/usr/bin/env bash\ncat > /dev/null\n', 0o755)
    d = rig.run()
    assert not d.runs() and d.status[-1] == "status=FAILED at=guest", d.why()


@linux_only
def test_a_harness_killed_child_is_not_judged_naming_its_exit(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_KILL_PARENT_AFTER_DRIVE="2")
    assert d.status[-1] == "status=FAILED at=arm" and d.rc == 1, d.why()
    assert d.v().startswith("verdict: NOT JUDGED") and "FAILED at=arm" in d.v(), d.why()
    assert not os.listdir(str(rig.stub / "state" / "docker"))


@linux_only
def test_a_host_setting_changed_is_failed_at_host_check_and_the_settings_instrument(tmp_path):
    d = Rig(tmp_path).run(STUB_RMEM_AFTER="9999")
    assert d.status[-1] == "status=FAILED at=host-check" and d.rc == 1, d.why()
    assert d.v().startswith("verdict: NOT JUDGED") and "settings" in d.v(), d.why()


@linux_only
def test_a_rerun_goes_to_the_judge_from_the_environment(tmp_path):
    d = Rig(tmp_path).run(G1_RERUN_OF="20261201T-a6-orin-aw-g1", G1_RERUN_AFTER="reset")
    assert "passed on a later boot after a reset of unassigned cause" in d.v() and "20261201T-a6-orin-aw-g1" in d.v(), d.why()
    assert d.arm["rerun_of"] == "20261201T-a6-orin-aw-g1"


@linux_only
def test_the_graphical_session_is_recorded_as_booted(whole):
    assert "graphical_target" in whole.arm


@linux_only
def test_a_kill_seen_by_the_end_read_is_t1(tmp_path):
    d = Rig(tmp_path).run(STUB_OOM_KILL="aw-g1-diag")
    assert "T1" in d.v() and d.v().startswith("verdict: FAIL"), d.why()


@linux_only
def test_the_guest_stopped_arm_has_no_guest_and_no_claim_node(tmp_path):
    rig = Rig(tmp_path, plan="guest-stopped")
    d = rig.run()
    assert d.status[-1] == "status=DONE", d.why()
    assert d.idx(r"^launch ") < 0 and d.idx(r"^ctlsynth ") < 0 and d.idx(r"oom_score_adj") < 0, d.why()
    assert d.idx(r"^repin ") < 0 and "repin_exit_aw-sim" not in d.arm, "no QEMU runs here, so nothing is re-pinned\n" + d.why()
    names = {_opt(a, "--name") for a in d.runs()}
    assert names == {"aw-sim", "aw-g1-count", "aw-g1-diag", "aw-scenario"}
    assert not any("--require-claim-node" in a for a in d.runs("aw-scenario"))
    assert d.v() == "verdict: PASS", d.why()
    assert any(x.startswith("T6 does not apply") for x in d.verdict)


@linux_only
def test_the_main_arm_drives_with_the_claim_node_required(whole):
    assert all("--require-claim-node" in a for a in whole.runs("aw-scenario"))
    a = whole.runs("aw-claim-node")[0]
    assert a[a.index("--port") + 1] == "7150" and a[a.index("--host") + 1] == "192.168.100.10"


@linux_only
@pytest.mark.parametrize("host, jetson, ok", [
    ("orin", True, True), ("c7g-metal", True, False), ("c7g-metal", False, True), ("orin", False, False), ("a1-metal", False, False),
    (None, False, False), (None, True, False), ("a1-metal", True, False)])
def test_the_host_rule(tmp_path, host, jetson, ok):
    rig = Rig(tmp_path, vss_host=host or "x")
    if jetson:
        (rig.base / "nv_tegra_release").write_text("# R39\n")
    d = rig.run(VSS_HOST=host, STUB_NO_IMAGE="1")
    if ok:
        assert "VSS_HOST" not in " ".join(x for x in d.log.splitlines() if "FATAL" in x or "FAILED at" in x), d.why()
        assert "the image" in d.log, d.why()
    else:
        assert d.status[-1] == "status=FAILED at=preflight" and "VSS_HOST" in d.log, d.why()
    assert not d.runs()


@linux_only
def test_the_host_rule_reads_an_nvidia_device_tree_too(tmp_path):
    rig = Rig(tmp_path)
    (rig.base / "dt-compatible").write_bytes(b"nvidia,p3768-0000+p3767-0005\0nvidia,tegra234\0")
    d = rig.run()
    assert d.status[-1] == "status=FAILED at=preflight" and "Jetson" in d.log, d.why()


@linux_only
def test_the_floor_override_is_refused_under_the_orin(tmp_path):
    rig = Rig(tmp_path, vss_host="orin")
    (rig.base / "nv_tegra_release").write_text("# R39\n")
    d = rig.run(G1_REHEARSAL_FLOOR_KB="4000000")
    assert d.status[-1] == "status=FAILED at=preflight" and "G1_REHEARSAL_FLOOR_KB" in d.log, d.why()
    assert not d.runs()


@linux_only
def test_the_rehearsal_plan_is_refused_under_the_orin(tmp_path):
    rig = Rig(tmp_path, vss_host="orin", plan="rehearsal")
    (rig.base / "nv_tegra_release").write_text("# R39\n")
    d = rig.run()
    assert d.status[-1] == "status=FAILED at=preflight" and "rehearsal" in d.log, d.why()


@linux_only
@pytest.mark.parametrize("plan", ["", "other", "MAIN"])
def test_another_plan_is_refused(tmp_path, plan):
    d = Rig(tmp_path, plan=plan).run()
    assert d.status[-1] == "status=FAILED at=preflight" and not d.runs(), d.why()


def _pf_nothing(rig):
    pass


def _pf_other_ifs(rig):
    (rig.base / "w" / "img" / "ifs-vss.bin").write_bytes(b"ifs")


def _pf_no_watchdog(rig):
    os.remove(str(rig.repo / "sdv" / "aw" / "g1_watchdog.py"))


def _pf_entrypoint_not_executable(rig):
    os.chmod(str(rig.repo / "sdv" / "aw" / "aw-entrypoint.sh"), 0o644)


def _pf_no_digest(rig):
    Rig._w(rig.vss_home / "gen" / "vss_ctl.py", "x = 1")


def _pf_other_map_bytes(rig):
    maps = rig.vss_home / "aw" / "map"
    (maps / sorted(os.listdir(str(maps)))[0] / "lanelet2_map.osm").write_bytes(b"<osm other=\"1\"/>\n")


def _pf_no_deadline(rig):
    os.remove(str(rig.deadline))


@linux_only
@pytest.mark.parametrize("change, cfg, word", [
    (_pf_nothing, {"STUB_GROUPS": "ubuntu adm"}, "docker group"),
    (_pf_other_ifs, lambda rig: {"IFS_BIN": str(rig.base / "w" / "img" / "ifs-vss.bin")}, "not ifs-ctl.bin"),
    (_pf_no_watchdog, {}, "the tree lacks sdv/aw/g1_watchdog.py"),
    (_pf_entrypoint_not_executable, {}, "not executable"),
    (_pf_no_digest, {}, "DIGEST"),
    (_pf_other_map_bytes, {}, "the staged map"),
    (_pf_nothing, {"STUB_NO_IMAGE": "1"}, "not in the image store"),
    (_pf_no_deadline, {}, "deadline file"),
], ids=["no-docker-group", "not-ifs-ctl", "no-watchdog", "entrypoint-not-executable", "no-digest", "map-other-bytes", "no-image",
        "no-deadline-file"])
def test_each_preflight_refusal_names_its_cause_and_starts_nothing(tmp_path, change, cfg, word):
    rig = Rig(tmp_path)
    change(rig)
    d = rig.run(**(cfg(rig) if callable(cfg) else cfg))
    assert d.status[-1] == "status=FAILED at=preflight" and d.rc == 1 and not d.runs() and word in d.log, d.why()
    assert not (rig.stub / "state" / "qemu").exists(), d.why()


@linux_only
def test_a_leftover_container_is_refused_and_not_removed(tmp_path):
    rig = Rig(tmp_path)
    Rig._w(rig.stub / "state" / "docker" / "old.json", json.dumps({"name": "old", "labels": {"sdv.aw.run": "x"}, "running": True, "exit": 0}))
    d = rig.run()
    assert d.status[-1] == "status=FAILED at=preflight" and not d.runs(), d.why()
    assert (rig.stub / "state" / "docker" / "old.json").exists()


@linux_only
def test_a_qemu_already_running_is_refused_and_not_stopped(tmp_path):
    rig = Rig(tmp_path)
    (rig.stub / "state" / "qemu").write_text("")
    d = rig.run()
    assert d.status[-1] == "status=FAILED at=preflight" and (rig.stub / "state" / "qemu").exists(), d.why()


@linux_only
def test_an_old_record_is_never_mixed(tmp_path):
    rig = Rig(tmp_path)
    Rig._w(rig.out / "arm.tsv", "plan\tmain\n")
    d = rig.run()
    assert "refusing to mix" in d.log and not d.runs(), d.why()


@linux_only
def test_a_simulator_that_does_not_come_up_goes_on_to_the_first_drive(tmp_path):
    d = Rig(tmp_path).run(STUB_SIM_NOT_UP="1", STUB_DRIVE_NO_ROUTE="1")
    assert d.arm["sim_up"] == "false" and d.begun() == 1 and d.arm["loop_end"] == "first-no-route", d.why()


@linux_only
def test_the_rehearsal_plan_runs_the_arm_then_the_kill_unit_with_the_floor_above_memavailable(tmp_path):
    rig = Rig(tmp_path, plan="rehearsal", real_watchdog=False)
    d = rig.run()
    assert d.status[-1] == "status=DONE", d.why()
    kill = rig.out / "kill"
    assert (kill / "verdict.txt").exists(), d.why()
    assert (kill / "arm.tsv").read_text().count("rehearsal_floor_kb\t") == 1
    floor = dict(x.split("\t", 1) for x in (kill / "arm.tsv").read_text().splitlines())["rehearsal_floor_kb"]
    assert int(floor) > 3000000


def _sets(d, what="set-property"):
    return [c for c in d.calls if c.startswith("systemctl %s " % what)]


@linux_only
def test_the_rehearsal_plan_sets_allowedcpus_itself_so_the_g1_stamp_passes_and_restores_it_after_the_kill_unit(tmp_path):
    rig = Rig(tmp_path, plan="rehearsal")
    rig.daemons(dockerd="0-63", containerd="0-63")   # as run-aw-setup.sh leaves c7g.metal
    d = rig.run()
    assert d.rc == 0 and d.status[-1] == "status=DONE", d.why()
    assert d.v() == "verdict: PASS", d.why()
    stamp = json.loads((rig.out / "stamp.json").read_text())
    assert stamp["platform"]["policy"] == "g1", stamp["platform"]
    sets = _sets(d)
    assert sets[:2] == ["systemctl set-property --runtime docker.service AllowedCPUs=3,5",
                        "systemctl set-property --runtime containerd.service AllowedCPUs=3,5"], sets
    assert d.calls.index(sets[1]) < d.idx(r"^docker run ")
    assert (rig.out / "kill" / "verdict.txt").exists(), d.why()
    kill = dict(x.split("\t", 1) for x in (rig.out / "kill" / "arm.tsv").read_text().splitlines())
    assert d.arm["kill_unit_exit"] == "0" and kill["stamp_exit"] == "0", "the kill unit's own stamp needs the property still set\n" + d.why()
    assert len(sets) == 4 and all(re.search(r" AllowedCPUs=0-[0-9]+$", x) for x in sets[2:]), sets
    last_run = max(i for i, c in enumerate(d.calls) if c.startswith("docker run "))
    assert d.calls.index(sets[2]) > last_run, "restored only after the kill unit"
    assert sets[2].split()[3] == "docker.service" and sets[3].split()[3] == "containerd.service"
    assert "Cpus_allowed_list:\t0-" in (rig.proc / "812" / "status").read_text()


@linux_only
def test_a_rehearsal_whose_allowedcpus_cannot_be_set_ends_at_the_stamp_and_starts_nothing(tmp_path):
    rig = Rig(tmp_path, plan="rehearsal")
    rig.daemons(dockerd="0-63", containerd="0-63")
    d = rig.run(STUB_SET_PROPERTY_FAILS="1")
    assert d.rc == 1 and d.status[-1] == "status=FAILED at=stamp" and not d.runs(), d.why()
    assert d.idx(r"^watchdog ") < 0 and d.idx(r"^launch ") < 0, d.why()
    assert "AllowedCPUs" in d.v() and d.v().startswith("verdict: NOT JUDGED"), d.why()


@linux_only
def test_no_arm_but_the_rehearsal_touches_allowedcpus(tmp_path, whole):
    assert not _sets(whole), whole.calls
    rig = Rig(tmp_path, plan="main")
    rig.daemons(dockerd="0-63", containerd="0-63")
    d = rig.run()
    assert not _sets(d) and d.status[-1] == "status=FAILED at=stamp", d.why()


@linux_only
def test_the_harness_header_says_who_sets_allowedcpus():
    with open(HARNESS, encoding="utf-8") as f:
        head = f.read().partition("\nset -u\n")[0]
    assert "AllowedCPUs" in head and "g1-setup" in head and "PLAN=rehearsal" in head


@linux_only
def test_the_drivers_log_is_kept_in_a_directory_the_login_owns(whole):
    p = whole.rig.out / "drives" / "driver-d001.log"
    assert p.exists() and "the driver's own line" in p.read_text(), sorted(os.listdir(str(whole.rig.out / "drives")))
    assert not (whole.rig.out / "drives" / "d001" / "driver.log").exists()


@linux_only
def test_the_stamp_names_the_gpu_node_the_clock_sampler_will_read(tmp_path):
    rig = Rig(tmp_path)
    node = tmp_path / "devfreq" / "17000000.gpu"
    node.mkdir(parents=True)
    (node / "name").write_text("17000000.gpu\n")
    (node / "cur_freq").write_text("204000000\n")
    d = rig.run(DEVFREQ_ROOT=tmp_path / "devfreq", STUB_DRIVE_NO_ROUTE="1")
    stamp = json.loads((rig.out / "stamp.json").read_text())
    assert stamp["sampler_paths"]["gpu_devfreq"] == str(node / "cur_freq"), d.why()
    assert "gpu_hz=204000000" in (rig.out / "clk-g1.log").read_text(), d.why()


@linux_only
def test_a_stamp_with_no_gpu_node_says_none_and_runs_on(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_DRIVE_NO_ROUTE="1")
    assert json.loads((rig.out / "stamp.json").read_text())["sampler_paths"]["gpu_devfreq"] == "", d.why()


@linux_only
@pytest.mark.parametrize("plan, name, row", [("main", "aw-sim", "sim_run_exit"), ("main", "aw-claim-node", "claim_run_exit"),
                                             ("main", "aw-g1-diag", "diag_run_exit"), ("guest-stopped", "aw-g1-count", "count_run_exit")])
def test_a_docker_run_that_fails_for_a_standing_container_is_the_harness_own_exit(tmp_path, plan, name, row):
    rig = Rig(tmp_path, plan=plan)
    d = rig.run(STUB_RUN_FAILS=name)
    assert d.rc == 1 and d.status[-1] == "status=FAILED at=arm", d.why()
    assert d.arm[row] == "125" and not d.runs("aw-scenario"), d.why()
    v = d.v()
    assert v.startswith("verdict: NOT JUDGED") and "docker run of %s exited 125" % name in v, d.why()
    assert "T7: the loop" not in v and d.verdict[-1].startswith("re-run: allowed"), d.why()
    assert not os.listdir(str(rig.stub / "state" / "docker")), "the sweep removes what did start"
    assert not (rig.stub / "state" / "qemu").exists()
    assert d.doc["status"] == "FAILED" and "docker run of %s" % name in d.doc["reason"], d.doc


@linux_only
def test_a_docker_run_that_fails_for_the_first_drive_is_not_a_drives_reading(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_RUN_FAILS_AT_DRIVE="1")
    assert d.rc == 0 and d.status[-1] == "status=DONE" and d.arm["loop_end"] == "docker-run-failed", d.why()
    rows = (rig.out / "drives.tsv").read_text().splitlines()
    assert rows[-1] == "stopped\t1\tdocker-run-exit-125" and not any(x.startswith("end\t") for x in rows), rows
    assert d.v().startswith("verdict: NOT JUDGED") and "could not start a drive" in d.v(), d.why()
    assert "T7: the loop" not in d.v() and d.verdict[-1].startswith("re-run: allowed"), d.why()
    assert "the stand-in refuses" in d.arm["drive_run_err"], d.arm
    assert not os.listdir(str(rig.stub / "state" / "docker")), d.why()


@linux_only
def test_a_driver_restart_that_fails_for_a_later_drive_ends_the_loop_and_keeps_the_earlier_readings(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_RUN_FAILS_AT_DRIVE="3", STUB_DRIVER_DIES_AT_DRIVE="2", STUB_DRIVER_EXIT="3")
    assert d.arm["loop_end"] == "docker-run-failed" and len(d.runs("aw-scenario")) == 2 and d.begun() == 3, d.why()
    assert d.status[-1] == "status=DONE" and d.v().startswith("verdict: FAIL") and "d002 exited 3" in d.v(), d.why()
    assert "could not start a drive" in d.v() and d.verdict[-1].startswith("re-run: none"), d.why()


@linux_only
def test_a_stop_file_beside_a_failed_docker_run_is_the_watchdogs_end(tmp_path):
    d = Rig(tmp_path).run(STUB_DRIVER_DIES_AT_DRIVE="1", STUB_RUN_FAILS_AT_DRIVE="2", STUB_RUN_FAIL_STOPS="1")
    assert d.arm["loop_end"] == "watchdog-stop", d.why()
    assert d.v().startswith("verdict: FAIL") and "T2" in d.v(), d.why()


# --- a `docker wait` on a drive (PR's dated section, item 12): a number is the driver's exit; a bound that expires is the drive's reading
# --- only while docker answers that the container runs; anything else read no exit, and is the harness's own -------------------------

def _no_exit_was_read(rig, d, word, k="2"):
    rows = (rig.out / "drives.tsv").read_text().splitlines()
    assert rows[-1] == "stopped\t%s\t%s" % (k, word) and not any(x.startswith("end\t%s\t" % k) for x in rows), d.why()
    assert d.rc == 0 and d.status[-1] == "status=DONE" and d.arm["loop_end"] == "docker-wait-failed", d.why()
    assert d.begun() == int(k), "the loop ends there\n" + d.why()
    assert d.v().startswith("verdict: NOT JUDGED") and "read no exit from a drive" in d.v(), d.why()
    assert "could not start a drive" not in d.v() and "exited 124" not in d.v(), d.why()
    assert d.verdict[-1].startswith("re-run: allowed"), d.why()
    assert (rig.out / "vmstat-end.txt").exists(), "the end reads are taken\n" + d.why()
    assert not os.listdir(str(rig.stub / "state" / "docker")), d.why()
    # a drive with no exit read has its files synced as a drive that ended has: a sync follows its container's removal, before the first stop
    rm = max(i for i, c in enumerate(d.calls) if c == "docker rm -f aw-scenario")
    stop = next(i for i, c in enumerate(d.calls) if i > rm and c.startswith("docker stop "))
    assert "sync" in d.calls[rm:stop], "no sync after the drive with no exit read\n" + "\n".join(d.calls[rm:stop])


@linux_only
@pytest.mark.parametrize("cfg, word", [
    ({}, "docker-wait-exit-1"),
    ({"STUB_WAIT_FAIL_RC": "125"}, "docker-wait-exit-125"),
    ({"STUB_WAIT_SAYS": "0"}, "docker-wait-exit-1"),                                # a number beside a non-zero exit is not read as an exit
    ({"STUB_WAIT_FAIL_RC": "0", "STUB_WAIT_SAYS": "no number"}, "docker-wait-exit-0"),
    ({"STUB_WAIT_FAIL_RC": "0"}, "docker-wait-exit-0"),
], ids=["exit-1", "exit-125", "a-number-beside-exit-1", "no-number-beside-exit-0", "nothing-beside-exit-0"])
def test_a_docker_wait_that_gets_no_number_reads_no_exit_and_ends_the_loop_not_judged(tmp_path, cfg, word):
    rig = Rig(tmp_path)
    d = rig.run(STUB_WAIT_FAILS_AT_DRIVE="2", **cfg)
    _no_exit_was_read(rig, d, word)
    waits = [i for i, c in enumerate(d.calls) if c == "timeout 600 docker wait aw-scenario"]
    assert "timeout 120 docker rm -f aw-scenario" in d.calls[waits[-1]:], "bounded as a drive's always is\n" + d.why()
    assert "the driver's own line" in (rig.out / "drives" / "driver-d001.log").read_text(), "its partial readings stay in the record\n" + d.why()


@linux_only
def test_a_drives_look_at_its_exit_file_starts_no_process(tmp_path):
    """Polling the drive's exit file uses shell builtins, so each poll starts no child process."""
    rig = Rig(tmp_path)
    d = rig.run()
    assert d.v() == "verdict: PASS", d.why()
    log = rig.stub / "sleeps.log"
    asked = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    assert asked and RIG_EXIT_POLL_S not in asked, asked


def _exit_poll_shell(body):
    """The harness's own text of the wait, in a bash with no PATH: anything but a builtin there is an error, and `sleep` a function that says so."""
    with open(HARNESS, encoding="utf-8") as f:
        text = f.read()
    func = re.search(r"^exit_poll_wait\(\) \{.*?^\}$", text, re.M | re.S).group(0)
    opener = re.search(r"^\s*(exec \{IDLE_FD\}<> <\(:\).*)$", text, re.M).group(1)
    script = "set -u\nset -eo pipefail\nEXIT_POLL_S=0.2\nsleep() { echo SLEPT; }\n%s\n%s\n" % (func, body.replace("OPEN", opener))
    t0 = time.monotonic()
    p = subprocess.run([BASH, "-c", script], env={"PATH": "/nonexistent"}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True, timeout=60)
    return p, time.monotonic() - t0


@linux_only
def test_the_exit_polls_wait_is_a_builtin_that_waits_its_time():
    p, took = _exit_poll_shell("OPEN\nexit_poll_wait\nexit_poll_wait\necho end")
    assert p.returncode == 0 and p.stdout.strip() == "end", p.stdout
    assert 0.35 <= took < 5, took


@linux_only
def test_the_exit_polls_wait_is_a_sleep_where_its_pipe_is_not_there_and_never_a_spin():
    p, _took = _exit_poll_shell("IDLE_FD=\"\"\nexit_poll_wait\necho end")
    assert p.returncode == 0 and p.stdout.split() == ["SLEPT", "end"], p.stdout


@linux_only
def test_a_whole_arm_passes_on_the_exit_polls_design_value(tmp_path):
    """The rig's one changed line left as the harness has it: EXIT_POLL_S 1 s, in the builtin, on the real clock."""
    with open(HARNESS, encoding="utf-8") as f:
        assert "\nEXIT_POLL_S=1\n" in f.read()
    rig = Rig(tmp_path, exit_poll=None)
    d = rig.run()
    assert d.v() == "verdict: PASS" and d.arm["loop_end"] == "reached", d.why()
    assert "\nEXIT_POLL_S=1\n" in (rig.g / "run-aw-g1.sh").read_text(encoding="utf-8")


@linux_only
def test_a_wait_s_bound_with_docker_answering_running_is_the_drives_reading_and_t7_fails(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_WAIT_HANGS_AT_DRIVE="2", STUB_WAIT_TIMEOUT_S=2)
    assert any(x.startswith("end\t2\t124\t") for x in (rig.out / "drives.tsv").read_text().splitlines()), d.why()
    assert d.arm["loop_end"] == "reached" and d.v().startswith("verdict: FAIL") and "d002 exited 124" in d.v(), d.why()
    assert d.verdict[-1].startswith("re-run: none"), d.why()
    assert "timeout 60 docker inspect -f {{.State.Running}} aw-scenario" in d.calls, d.why()
    look = "docker inspect -f {{.State.Running}} aw-scenario"       # the check before a drive logs the same line as the look after the bound
    assert d.calls.count(look) == d.calls.count("timeout 60 " + look), "each look at the driver has its own bound\n" + d.why()
    assert len(d.runs("aw-scenario")) == 2, "a driver past its bound holds its drive, so the next drive gets a new one\n" + d.why()
    assert not (rig.out / "drives" / "d002" / "exit").exists() and (rig.out / "drives" / "d003" / "exit").exists(), d.why()


@linux_only
@pytest.mark.parametrize("cfg, rc, verdict", [({}, 0, "verdict: PASS"), ({"STUB_DRIVE_TIMEOUT": "2"}, 3, "verdict: FAIL: T7: d002 exited 3")],
                         ids=["exit-0", "exit-3"])
def test_a_wait_s_bound_with_docker_answering_not_running_reads_docker_s_exit_code(tmp_path, cfg, rc, verdict):
    """PR's dated section, item 15: no number written, and docker's code is the drive's, with its lines read by T7 as ever."""
    rig = Rig(tmp_path)
    d = rig.run(STUB_WAIT_HANGS_AT_DRIVE="2", STUB_WAIT_TIMEOUT_S=2, STUB_WAIT_INSPECT="ended", **cfg)
    assert any(x.startswith("end\t2\t%d\t" % rc) for x in (rig.out / "drives.tsv").read_text().splitlines()), d.why()
    assert d.arm["loop_end"] == "reached" and d.v().startswith(verdict), d.why()
    code = d.calls.index("timeout 60 docker inspect -f {{.State.ExitCode}} aw-scenario")
    assert "timeout 120 docker rm -f aw-scenario" in d.calls[code:], d.why()
    assert "driver_ended_between_drives" not in d.arm, "a death inside a drive is no fact of between drives\n" + d.why()
    assert len(d.runs("aw-scenario")) == 2, "the next drive gets another\n" + d.why()


@linux_only
@pytest.mark.parametrize("mode", ["no-answer", "hang", "ended-code-no-answer", "ended-code-garbled"])
def test_a_wait_s_bound_with_no_answer_from_docker_reads_no_exit_and_ends_the_loop_not_judged(tmp_path, mode):
    rig = Rig(tmp_path)
    d = rig.run(STUB_WAIT_HANGS_AT_DRIVE="2", STUB_WAIT_TIMEOUT_S=2, STUB_INSPECT_TIMEOUT_S=2, STUB_WAIT_INSPECT=mode)
    _no_exit_was_read(rig, d, "docker-wait-bound-no-answer")


@linux_only
def test_a_warning_beside_dockers_exit_number_is_not_read_as_no_exit(tmp_path):
    """A `docker wait` that prints its number and, on stderr, a warning: the number is the container's exit and no drive reads as having none."""
    rig = Rig(tmp_path)
    d = rig.run(STUB_DRIVER_DIES_AT_DRIVE="2", STUB_WAIT_WARNS="1")
    assert d.arm["loop_end"] == "reached" and not any(x.startswith("stopped\t") for x in d.rows()), d.why()
    assert any(x.startswith("end\t2\t137\t") for x in d.rows()) and d.status[-1] == "status=DONE", d.why()


@linux_only
@pytest.mark.parametrize("inspect, row, verdict", [("", "end\t2\t124\t", "verdict: FAIL: T7: d002 exited 124"),
                                                   ("ended", "end\t2\t0\t", "verdict: PASS")], ids=["running", "ended"])
def test_a_warning_beside_dockers_answer_after_a_wait_s_bound_is_not_read_as_no_answer(tmp_path, inspect, row, verdict):
    """After the wait's bound, docker's answer (`true`, or `false` and the exit code) with a warning beside it on stderr is still docker's
    answer: the drive's 124 while it runs, its exit code once it ended."""
    rig = Rig(tmp_path)
    d = rig.run(STUB_WAIT_HANGS_AT_DRIVE="2", STUB_WAIT_TIMEOUT_S=2, STUB_WAIT_INSPECT=inspect, STUB_WAIT_INSPECT_WARNS="1")
    assert any(x.startswith(row) for x in d.rows()) and not any(x.startswith("stopped\t") for x in d.rows()), d.why()
    assert d.arm["loop_end"] == "reached" and d.v().startswith(verdict), d.why()


@linux_only
def test_a_stop_file_beside_a_docker_wait_with_no_exit_is_the_watchdogs_end(tmp_path):
    d = Rig(tmp_path).run(STUB_WAIT_FAILS_AT_DRIVE="2", STUB_WAIT_FAIL_STOPS="1")
    assert d.arm["loop_end"] == "watchdog-stop", d.why()
    assert d.v().startswith("verdict: FAIL") and "T2" in d.v(), d.why()


@linux_only
def test_a_first_drive_whose_exit_was_not_read_is_no_first_no_route(tmp_path):
    """A first drive with no route line and an exit read is first-no-route, a FAIL never re-run. With no exit read it is the harness's."""
    rig = Rig(tmp_path)
    d = rig.run(STUB_WAIT_FAILS_AT_DRIVE="1", STUB_DRIVE_NO_ROUTE="1")
    _no_exit_was_read(rig, d, "docker-wait-exit-1", k="1")


@linux_only
def test_the_wait_s_reading_cites_pr_s_item():
    for p in (HARNESS, os.path.join(G, "aw_g1.py")):
        with open(p, encoding="utf-8") as f:
            text = f.read()
        assert "item 12" in text and "PR's dated section, item 15" in text, p


@linux_only
@pytest.mark.parametrize("cfg, word", [
    ({"G1_RERUN_OF": "20261201T-a6-orin-aw-g1", "G1_RERUN_AFTER": "bogus"}, "G1_RERUN_AFTER='bogus'"),
    ({"G1_RERUN_AFTER": "reset"}, "without G1_RERUN_OF"),
], ids=["a-word-the-judge-does-not-take", "no-rerun-of"])
def test_a_rerun_word_the_judge_cannot_take_is_refused_before_anything_starts(tmp_path, cfg, word):
    rig = Rig(tmp_path)
    d = rig.run(**cfg)
    assert d.rc == 1 and d.status[-1] == "status=FAILED at=preflight" and word in d.log, d.why()
    assert not d.runs() and d.idx(r"^watchdog ") < 0 and d.idx(r"^launch ") < 0, d.why()
    assert d.v().startswith("verdict: NOT JUDGED"), "a refusal still leaves a verdict\n" + d.why()


@linux_only
def test_a_rerun_after_a_not_judged_arm_is_taken(tmp_path):
    d = Rig(tmp_path).run(G1_RERUN_OF="20261201T-a6-orin-aw-g1", G1_RERUN_AFTER="not-judged", STUB_DRIVE_NO_ROUTE="1")
    assert d.status[-1] == "status=DONE" and "a re-run of 20261201T-a6-orin-aw-g1" in d.v(), d.why()


def _break_tool(rig, command):
    p = rig.g / "aw_g1.py"
    text = p.read_text(encoding="utf-8")
    head = "def cmd_%s(a: argparse.Namespace) -> int:\n" % command
    assert text.count(head) == 1
    Rig._w(p, text.replace(head, head + "    raise SystemExit(2)\n"))


@linux_only
def test_a_judge_that_cannot_run_is_never_a_done_record(tmp_path):
    rig = Rig(tmp_path)
    _break_tool(rig, "judge")
    d = rig.run(STUB_DRIVE_NO_ROUTE="1")
    assert d.rc == 1 and d.status[-1] == "status=FAILED at=record", d.why()
    assert d.arm["outcome_before_record"] == "status=DONE" and d.arm["harness_end"] == "status=FAILED at=record", d.arm
    assert d.doc["status"] == "FAILED" and d.doc["status_line"] == "status=FAILED at=record" and d.doc["verdict"] == [], d.doc


@linux_only
def test_a_g1_json_that_cannot_be_written_is_never_a_done_record(tmp_path):
    rig = Rig(tmp_path)
    _break_tool(rig, "record")
    d = rig.run(STUB_DRIVE_NO_ROUTE="1")
    assert d.rc == 1 and d.status[-1] == "status=FAILED at=record", d.why()
    assert d.v().startswith("verdict:"), d.why()


@linux_only
def test_the_real_watchdog_kills_a_rehearsal_unit_on_the_real_clock(tmp_path):
    rig = Rig(tmp_path, real_watchdog=True)
    d = rig.run(G1_REHEARSAL_FLOOR_KB="4000000")
    assert d.status[-1] == "status=DONE", d.why()
    assert (rig.out / "watchdog.stop").exists(), d.why()
    assert any(x.startswith("E ") and " stop " in x for x in (rig.out / "watchdog.log").read_text().splitlines()), d.why()
    assert d.v().startswith("verdict: FAIL") and "T2" in d.v(), d.why()
    assert any(a[0] == "kill" for a in d.docker), d.why()


@linux_only
def test_the_harness_header_holds_what_the_form_asks():
    with open(HARNESS, encoding="utf-8") as f:
        text = f.read()
    head = text.partition("\nset -u\n")[0]
    assert "WHAT IT DOES NOT SHOW" in head and "ours, not a QNX-supported configuration" in head
    assert "no timing claim attaches to the boot" in head
    assert not re.search(r"-enable-kvm", head)


@linux_only
def test_every_file_of_the_package_has_lf_endings_only():
    for p in (HARNESS, TOOL, WATCHDOG, SAMPLER, DIAG, COUNT, PREREG):
        with open(p, "rb") as f:
            assert b"\r" not in f.read(), p


def test_the_prereg_copy_is_in_the_tree_and_names_its_own_path():
    with open(PREREG, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("# Pre-registration: gates G1 and G2 (SDV Phase 8)") and "`sdv/aw/prereg-g1g2.md`" in text
    assert "## Dated sections" in text and "### 2026-11-01: readings where the sections above give no rule, or two" in text


def test_the_sdv_aw_readme_names_the_new_files():
    with open(os.path.join(AW, "README.md"), encoding="utf-8") as f:
        text = f.read()
    for n in ("g1_watchdog.py", "g1_sampler.py", "aw_g1_diag.py", "aw_g1_count.py", "prereg-g1g2.md", "run-aw-g1.sh"):
        assert n in text, n


# --- the driver is resident (PR's dated section, item 15), and the smaller findings of the rehearsal's record ---------------------------------

def test_the_prereg_copy_is_prs_byte_for_byte():
    """Its sha256, as the orchestrator's private copy has it: a change to PR is a new dated section there and a new pin here."""
    with open(PREREG, "rb") as f:
        raw = f.read()
    assert hashlib.sha256(raw).hexdigest() == "8af4e977b70a19f62ff882caaeb5e49945e529925c2e95e7992a45ba365f4c00"
    assert b"### 2026-11-02: the driver is resident" in raw and b"\r" not in raw


def test_placement_wants_the_drivers_one_start_and_no_row_per_drive(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=4)
    assert [x[0] for x in r.placement if x[0].startswith("aw-scenario")] == ["aw-scenario"]
    j = _judge(g1, r)
    assert j.verdict == "PASS" and _inst(j, "placement").startswith("instrument placement OK"), j.lines


def test_placement_with_no_read_of_the_driver_is_missing_naming_it(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=4)
    r.placement = [x for x in r.placement if x[0] != "aw-scenario"]
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and "no read of aw-scenario" in _inst(j, "placement"), j.lines


def test_a_restarted_driver_off_its_cores_is_placement_missing(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=4)
    r.placement.append(("aw-scenario", "3,5", "4", "running"))
    j = _judge(g1, r)
    assert j.verdict == "NOT JUDGED" and "aw-scenario request" in _inst(j, "placement"), j.lines


def test_placement_wants_no_driver_where_no_drive_began(g1, tmp_path):
    r = Rec(tmp_path / "r", drives=0)
    r.arm["loop_end"] = "sim-died"
    j = _judge(g1, r)
    assert "no read of aw-scenario" not in _inst(j, "placement"), j.lines


def test_the_record_s_doc_lines_say_the_driver_is_resident():
    with open(TOOL, encoding="utf-8") as f:
        text = f.read()
    assert "aw-scenario:" not in text and "the driver's one start" in text


@linux_only
def test_one_driver_container_runs_every_drive_of_an_arm(whole):
    assert whole.begun() > 2 and len(whole.runs("aw-scenario")) == 1, whole.why()
    for k in range(1, whole.begun() + 1):
        d = whole.rig.out / "drives" / ("d%03d" % k)
        assert (d / "exit").read_text() == "0\n" and (d / "scenario.jsonl").exists() and (d / "odometry.jsonl").exists()


@linux_only
def test_the_driver_is_started_in_serve_mode_from_a_go_file_outside_the_record(whole):
    a = whole.runs("aw-scenario")[0]
    assert a[a.index("--serve") + 1] == "/sdv-serve/go" and a[a.index("--out") + 1] == "/sdv-scn", a
    mounts = _opts(a, "-v")
    assert any(v.endswith(":/sdv-serve") and "aw-g1-work" in v for v in mounts) and any(v.endswith("/drives:/sdv-scn") for v in mounts), mounts
    assert not (whole.rig.out / "drives" / "go").exists() and not (whole.rig.vss_home / "aw-g1-work" / "serve" / "go").exists()
    for made in (whole.rig.out / "drives", whole.rig.vss_home / "aw-g1-work" / "serve"):
        # the container's user is in the login's group: it makes a drive's directory in the one and removes the word from the other
        assert made.stat().st_mode & 0o070 == 0o070, (made, oct(made.stat().st_mode))


@linux_only
def test_the_driver_starts_after_the_standing_containers_and_before_the_first_route(whole):
    idx = whole.idx
    assert idx(r"^docker run .*--name aw-g1-diag") < idx(r"^docker run .*--name aw-scenario"), whole.calls
    begin = next(x for x in whole.rows() if x.startswith("begin\t1\t"))
    first_route = int(whole.arm["first_route_mono_ns"])
    assert int(begin.split("\t")[2]) < first_route, whole.rows()


@linux_only
def test_the_drivers_memory_events_and_its_oomkilled_are_read_at_the_loops_end(whole):
    rows = dict(x.split("\t") for x in (whole.rig.out / "memory-events-end.tsv").read_text().splitlines())
    assert rows["aw-scenario"] == "0", rows
    assert whole.arm["oomkilled_aw-scenario"] == "false", whole.arm


@linux_only
def test_the_driver_stops_last_so_no_participant_leaves_while_a_frame_can_be_counted(whole):
    assert whole.arm["driver_stop_exit"] == "0", whole.arm
    last = max(i for i, c in enumerate(whole.calls) if c.startswith("docker stop "))
    assert whole.calls[last].endswith(" aw-scenario"), whole.calls
    assert "the driver's own line" in (whole.rig.out / "drives" / "driver-d001.log").read_text()


@linux_only
def test_a_number_in_the_drivers_file_is_its_exit_and_the_next_drive_begins_on_the_same_driver(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_DRIVE_TIMEOUT="2")
    assert any(x.startswith("end\t2\t3\t") for x in d.rows()) and d.arm["loop_end"] == "reached" and d.begun() > 2, d.why()
    assert len(d.runs("aw-scenario")) == 1, d.why()
    assert d.v().startswith("verdict: FAIL: T7: d002 exited 3") and d.verdict[-1].startswith("re-run: none"), d.why()
    assert (rig.out / "drives" / "d002" / "after-failure.jsonl").exists(), "T7 has failed, and the next drive begins on a clear route"
    last = json.loads((rig.out / "drives" / "d002" / "scenario.jsonl").read_text().splitlines()[-1])
    assert last["step"] == "arrive", "the drive's last line is still the drive's: section 6 reads it"


@linux_only
def test_an_exit_file_not_yet_whole_is_no_read(tmp_path):
    """A first byte seen before the rest (the driver writes by a rename, so this is a stand-in for a torn read): only the whole line counts."""
    d = Rig(tmp_path).run(STUB_EXIT_TORN_AT_DRIVE="2")
    assert any(x.startswith("end\t2\t13\t") for x in d.rows()), d.rows()


@linux_only
@pytest.mark.parametrize("line", ["oops", "1 2", "-1", ""], ids=["word", "two-numbers", "negative", "empty"])
def test_a_whole_line_in_the_exit_file_that_is_no_number_is_no_read(tmp_path, line):
    """The line has ended and is not a number: the driver's answer is not there yet (or is not an answer), and the number that follows is the exit."""
    d = Rig(tmp_path).run(STUB_EXIT_GARBLED_AT_DRIVE="2", STUB_EXIT_GARBLED_LINE=line)
    assert any(x.startswith("end\t2\t13\t") for x in d.rows()) and not any(x.startswith("end\t2\t0\t") for x in d.rows()), d.rows()


@linux_only
def test_the_wait_held_for_a_drive_is_ended_once_its_number_is_read(whole):
    """Nothing polls docker inside a drive; the one `docker wait` held for it must not outlive the drive, or every drive adds a process to the arm."""
    ends = (whole.rig.stub / "state" / "wait-ends").read_text(encoding="utf-8").split()
    assert whole.begun() > 2 and ends == ["killed"] * whole.begun(), (ends, whole.begun())


@linux_only
def test_a_stale_exit_file_of_the_last_drive_is_never_read_as_this_ones(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_DRIVER_HANGS_AT_DRIVE="2", STUB_WAIT_TIMEOUT_S=2)
    assert (rig.out / "drives" / "d001" / "exit").read_text() == "0\n"
    assert any(x.startswith("end\t2\t124\t") for x in d.rows()) and not any(x.startswith("end\t2\t0\t") for x in d.rows()), d.rows()
    assert d.v().startswith("verdict: FAIL: T7: d002 exited 124"), d.why()


@linux_only
def test_a_container_that_ended_with_no_number_is_that_drives_reading_with_dockers_code_and_starts_again(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_DRIVER_DIES_AT_DRIVE="2")
    assert any(x.startswith("end\t2\t137\t") for x in d.rows()), d.rows()
    assert not any(x.startswith("end\t2\t0\t") for x in d.rows()), "a container ended with no number is no exit 0"
    assert not any(x.startswith("stopped\t") for x in d.rows()) and d.arm["loop_end"] == "reached", d.why()
    assert len(d.runs("aw-scenario")) == 2 and d.begun() > 2, "the harness starts it again for the next drive\n" + d.why()
    rows = [x.split("\t")[0] for x in (rig.out / "placement.tsv").read_text().splitlines()]
    assert rows.count("aw-scenario") == 2, rows
    assert d.v().startswith("verdict: FAIL: T7: d002 exited 137") and d.verdict[-1].startswith("re-run: none"), d.why()
    assert "instrument placement OK" in "\n".join(d.verdict), d.why()
    assert (rig.out / "drives" / "driver-d001.log").exists() and (rig.out / "drives" / "driver-d003.log").exists(), d.why()
    assert "driver_ended_between_drives" not in d.arm, "a death inside a drive is no fact of between drives\n" + d.why()


@linux_only
def test_a_dying_driver_in_the_guest_stopped_arm_is_read_as_in_the_main_arm(tmp_path):
    rig = Rig(tmp_path, plan="guest-stopped")
    d = rig.run(STUB_DRIVER_DIES_AT_DRIVE="2")
    assert any(x.startswith("end\t2\t137\t") for x in d.rows()), d.rows()
    assert len(d.runs("aw-scenario")) == 2, d.why()
    assert not any("--require-claim-node" in a for a in d.runs("aw-scenario")), d.runs("aw-scenario")
    assert d.v().startswith("verdict: FAIL: T7: d002 exited 137"), d.why()


@linux_only
def test_a_container_that_ended_with_code_0_and_no_number_is_read_by_its_lines_so_a_localize_timeout_is_did_not_arrive(tmp_path):
    d = Rig(tmp_path).run(STUB_DRIVER_DIES_AT_DRIVE="2", STUB_DRIVER_EXIT="0", STUB_DRIVE_NO_ROUTE="2")
    assert any(x.startswith("end\t2\t0\t") for x in d.rows()), d.rows()
    assert d.v().startswith("verdict: FAIL: T7: d002 did not arrive"), d.why()


@linux_only
def test_a_driver_gone_between_two_drives_costs_no_drive_and_is_recorded(tmp_path):
    """No drive was under way, so no drive's reading: the harness finds it before the word, starts it again, and says so."""
    rig = Rig(tmp_path)
    d = rig.run(STUB_DRIVER_DIES_AFTER_DRIVE="2")
    assert d.arm["driver_ended_between_drives"] == "d003" and len(d.runs("aw-scenario")) == 2, d.why()
    assert all("\t0\t" in x for x in d.rows() if x.startswith("end\t")), d.rows()
    assert d.v() == "verdict: PASS", d.why()
    assert any(x.startswith("info the resident driver") and "d003" in x for x in d.verdict), "a second join is in the verdict\n" + d.why()


@linux_only
def test_an_inspect_of_the_driver_with_no_answer_is_recorded_and_the_drive_goes_on(tmp_path):
    d = Rig(tmp_path).run(STUB_DRIVER_INSPECT_NO_ANSWER="1")
    assert d.arm["driver_inspect_unanswered"] == "exit 1" and len(d.runs("aw-scenario")) == 1, d.why()
    assert d.v() == "verdict: PASS", d.why()
    assert any(x.startswith("info the resident driver") and "exit 1" in x for x in d.verdict), d.why()


@linux_only
def test_a_daemon_whose_socket_file_is_gone_is_no_end_of_the_driver_between_drives(tmp_path):
    """The same words for the driver's inspect: a healthy driver is not removed, and no drive loses it."""
    d = Rig(tmp_path).run(STUB_DRIVER_INSPECT_NO_ANSWER="1", STUB_NO_ANSWER_WORDS="socket-gone")
    assert d.arm["driver_inspect_unanswered"] == "exit 1" and "driver_ended_between_drives" not in d.arm, d.why()
    assert len(d.runs("aw-scenario")) == 1 and d.v() == "verdict: PASS", d.why()


@linux_only
def test_a_word_a_dead_driver_never_took_does_not_start_its_successor(tmp_path):
    rig = Rig(tmp_path)
    d = rig.run(STUB_DRIVER_DIES_BEFORE_WORD_AT_DRIVE="2")
    assert any(x.startswith("end\t2\t137\t") for x in d.rows()), d.rows()
    assert not (rig.out / "drives" / "d002").exists() and (rig.out / "drives" / "d003" / "exit").exists(), d.why()
    assert d.v().startswith("verdict: FAIL: T7: d002 exited 137"), d.why()


@linux_only
def test_docker_s_own_words_for_a_container_that_is_gone_read_no_exit(tmp_path):
    d = Rig(tmp_path).run(STUB_DRIVER_REMOVED_AT_DRIVE="2")
    assert d.arm["loop_end"] == "docker-wait-failed" and d.rows()[-1] == "stopped\t2\tdocker-wait-exit-1", d.why()
    assert d.v().startswith("verdict: NOT JUDGED") and d.verdict[-1].startswith("re-run: allowed"), d.why()


@linux_only
def test_every_row_of_arm_tsv_is_one_key_and_one_value_with_docker_s_empty_line_for_an_oomkilled_read(whole):
    """`docker inspect` of a name that is not there prints an empty line beside its error: the row names `none`, and stays one row."""
    text = (whole.rig.out / "arm.tsv").read_text()
    assert "oomkilled_aw-g1-count\tnone\n" in text
    bad = [x for x in text.splitlines() if "\t" not in x]
    assert not bad, bad


def _bad_meminfo(rig, body):
    p = rig.g / "aw_setup.py"
    text = p.read_text(encoding="utf-8")
    head = "def cmd_meminfo(a: argparse.Namespace) -> int:\n"
    assert text.count(head) == 1
    Rig._w(p, text.replace(head, head + body))


@linux_only
@pytest.mark.parametrize("body", ["    return 1\n", "    print('no number')\n    return 0\n", "    return 0\n"], ids=["exit-1", "garbled", "empty"])
def test_a_meminfo_that_cannot_be_read_refuses_the_kill_unit_and_the_main_arms_verdict_stands(tmp_path, body):
    rig = Rig(tmp_path, plan="rehearsal")
    rig.daemons(dockerd="0-63", containerd="0-63")
    _bad_meminfo(rig, body)
    d = rig.run()
    assert d.rc == 0 and d.status[-1] == "status=DONE" and d.v() == "verdict: PASS", d.why()
    assert "MemAvailable" in d.arm["kill_unit_refused"] and "kill_unit_exit" not in d.arm, d.why()
    assert not (rig.out / "kill").exists(), "no floor of 0 + 1 GiB"
    assert "kill unit is refused" in d.log, d.why()
    sets = _sets(d)
    assert sets[-1].endswith(" containerd.service AllowedCPUs=0-%d" % (os.cpu_count() - 1)) or " AllowedCPUs=0-" in sets[-1], sets


@linux_only
def test_the_harness_header_says_the_driver_is_resident():
    with open(HARNESS, encoding="utf-8") as f:
        head = f.read().partition("\nset -u\n")[0]
    flat = " ".join(x.lstrip("# ") for x in head.splitlines())
    assert "resident" in flat and "go file" in flat and "PR's dated section, item 15" in flat
    assert "a fresh --out each" not in flat


def test_the_sdv_aw_readme_says_the_driver_is_resident():
    with open(os.path.join(AW, "README.md"), encoding="utf-8") as f:
        flat = " ".join(f.read().split())
    for words in ("--serve", "/localization/kinematic_state", "change_to_stop", "resident", "odometry.jsonl", "after-failure.jsonl"):
        assert words in flat, words
