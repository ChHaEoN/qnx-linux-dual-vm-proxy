"""C2b S4's contract test: the lane claim client (sdv/lane/laneclient.py) against the native 0x50 monitor, on
tests/test_sdv_lane_contract.py's pattern, and its live source against the native 0x50 and 0x54 monitors. The rules
come from the project's local design notes, not in this tree.

tests/test_sdv_lane_contract.py holds the monitor's kind 6 judge to lanerules with frames the test packs and sends itself.
This file runs the client as a run would (`python laneclient.py run`, a subprocess) and holds what it sends and what it
logs to the monitor's answers:

- The native 0x50 build, made by build-monitor-native.sh itself (MONITOR_EXT_KINDS=0x50, its own OUT in a scratch HOME,
  the generated kind 4 headers), serving `PORT svc 300`, is sent a made-up estimates file (ESTIMATES below, every value
  chosen by hand inside or outside profile 1's design limits) that reaches ACCEPT with a lane, ACCEPT with no lane (with
  and without vehicle values), and every reason 28-31, with rule 31 on both sides of the lane and its two ways out
  (moving away, under the speed bound). The file is checked first against lanerules (each row's intended verdict and
  reason), so a row that stopped reaching its rule fails here, not as a missing reason later.
- The client runs it with --expect-judge: every frame is replied, every reply equals lanerules.judge of the frame the log
  holds, no reply carries reason 10 (a frame laneframe packs is a layout the monitor takes), the summary counts no
  difference and the identity holds; each REJECT line the console prints (its limiter prints reason changes) names a
  logged rejection's seq and reason.
- A silence over the monitor's deadline in the file: the monitor closes the idle connection (one LIVENESS MISS), the
  client sees the close, reconnects only for the next estimate, loses nothing, and the next claim restores liveness.
- The live source (`run --estimates -`): a producer subprocess writes the same made-up
  rows to the client's stdin, 50 ms apart but for one silence of 800 ms, into the native 0x50 and 0x54 builds (0x54 is
  the guest's, `make lane`) serving `PORT svc 500`, the guest's mode (ifs-lane.build's :7170). Every frame is replied,
  every reply equals lanerules.judge of its frame, every reason 28-31, ACCEPT and "no lane" are reached, no reply
  carries reason 10, and the identity holds; the silence is one LIVENESS MISS and one RESTORED on the console and one
  reconnect, counted, with nothing lost; the summary's sha256 and count are the bytes and lines the producer wrote.

Nothing here is a result: every value is profile 1's (S3's 2.4), a hand case's, or the specification's.

What this does NOT show: the guest build (a native gcc build serves here, not the qcc one) or its port pair 7170/7171;
a lane model, a camera or CARLA (the estimates are made up); any timing (the waits only bound when a line may come on a
loaded host, and the producer's gaps are its own sleeps).

Needs gcc and bash on Linux and the generated kind 4 contract in sdv-out/gen (sdv/vss/generate.py); without them a test
skips, and under SDV_REQUIRE_GEN=1 it fails instead (tests/twin_gate.py).
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import monitor_corpus as mc
import twin_gate

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LANE_DIR = REPO / "sdv" / "lane"
CLIENT = LANE_DIR / "laneclient.py"
NATIVE = REPO / "orin-native" / "gpu-concurrency" / "build-monitor-native.sh"
GEN_FILES = ("vss_contract.h", "vss_profiles.h")

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(LANE_DIR) not in sys.path:
    sys.path.insert(0, str(LANE_DIR))
import laneframe as lf  # noqa: E402
import lanerules as lr  # noqa: E402

sys.dont_write_bytecode = _saved

SVC_MS = 300
GAP_MS = 50              # between estimates: well inside the deadline, so the connection stays open
SILENCE_MS = 450         # over the deadline: the monitor closes the idle connection
HARNESS_REGEX = re.compile(r"REJECT seq=(\d+) .*?reason=([a-z-]+)")
NO_LANE = dict(lane_found=False, offset_m=None, heading_rad=None, curvature_1pm=None, lane_width_m=None)

# (what it is, the row's fields over BASE, the verdict and reason lanerules gives it). Profile 1: conf_min 50; width 2.5 to
# 4.5; |curvature| up to 0.1; |heading| up to 0.5; half the vehicle 0.95, so with width 3.5 the room is 0.8; rule 31 over
# speed 1.0 with a least time to the line of 1.0.
BASE = dict(lane_found=True, conf=90, offset_m=0.1, heading_rad=0.0, curvature_1pm=0.001, lane_width_m=3.5, v_mps=10.0,
            yaw_rps=0.0, age_ms=20)
ESTIMATES = [
    ("a lane, accepted", dict(), (0, 0)),
    ("no lane, with vehicle values", dict(NO_LANE, conf=5), (0, 0)),
    ("no lane, no vehicle values", dict(NO_LANE, conf=0, v_mps=None, yaw_rps=None), (0, 0)),
    ("confidence under the minimum", dict(conf=30), (1, 28)),
    ("the width over the window", dict(lane_width_m=5.0), (1, 29)),
    ("the width under the window", dict(lane_width_m=2.0), (1, 29)),
    ("the curvature over its limit", dict(curvature_1pm=-0.2), (1, 29)),
    ("the heading over its limit", dict(heading_rad=0.7), (1, 29)),
    ("the offset past the room, left", dict(offset_m=0.9), (1, 30)),
    ("the offset past the room, right", dict(offset_m=-0.9), (1, 30)),
    ("toward the left line, too fast", dict(offset_m=0.5, heading_rad=0.1, v_mps=20.0), (1, 31)),
    ("toward the right line, too fast", dict(offset_m=-0.5, heading_rad=-0.1, v_mps=20.0), (1, 31)),
    ("on the centre, moving", dict(offset_m=0.0, heading_rad=0.2, v_mps=30.0, lane_width_m=2.5), (1, 31)),
    ("moving away from the nearer line", dict(offset_m=0.5, heading_rad=-0.1, v_mps=20.0), (0, 0)),
    ("toward the line under the speed bound", dict(offset_m=0.5, heading_rad=0.1, v_mps=0.5), (0, 0)),
    ("toward the line, no vehicle values", dict(offset_m=0.5, heading_rad=0.1, v_mps=None, yaw_rps=None), (0, 0)),
    ("an age past u16, saturated", dict(age_ms=70000), (0, 0)),
]


def rows(gaps):
    out, t = [], 0
    for (_what, over, _want), gap in zip(ESTIMATES, gaps):
        t += gap
        r = dict(BASE, t_ms=t)
        r.update(over)
        out.append(r)
    return out


def build_native(tmp_path_factory, kinds):
    """The native monitor MONITOR_EXT_KINDS=kinds (0x50 or 0x54), built by build-monitor-native.sh to its own OUT in a
    scratch HOME; 0x54, the ctl build, takes kind 2's generated header too."""
    if shutil.which("gcc") is None or shutil.which("bash") is None or not hasattr(os, "sched_getaffinity"):
        twin_gate.missing("needs gcc and bash on Linux: runs in WSL and in CI's tooling job")
    gen = twin_gate.gen_dir()
    absent = [n for n in GEN_FILES + (("vss_ctl.h",) if kinds == "0x54" else ()) if not (gen / n).is_file()]
    if absent:
        twin_gate.missing("needs the generated kind 4 contract in %s (sdv/vss/generate.py): no %s" % (gen, ", ".join(absent)))
    d = tmp_path_factory.mktemp("laneclient-native-%s" % kinds)
    home = d / "home"
    home.mkdir()
    out = d / "monitor-lane"
    env = {k: v for k, v in os.environ.items() if k not in ("MONITOR_EXT_KINDS", "MONITOR_VSS_GEN", "OUT", "FORCE", "CC")}
    env.update(HOME=str(home), OUT=str(out), MONITOR_EXT_KINDS=kinds, MONITOR_VSS_GEN=str(gen))
    r = subprocess.run(["bash", str(NATIVE)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "switch: MONITOR_EXT_KINDS=%s -ffp-contract=off" % kinds in r.stdout, r.stdout
    return str(out)


@pytest.fixture(scope="module")
def monitor(tmp_path_factory):
    """The native 0x50 monitor."""
    return build_native(tmp_path_factory, "0x50")


@pytest.fixture(scope="module", params=["0x50", "0x54"])
def lane_monitor(request, tmp_path_factory):
    """The native 0x50 and 0x54 monitors, the live source's targets: (MONITOR_EXT_KINDS, the binary)."""
    return request.param, build_native(tmp_path_factory, request.param)


def run_client(tmp_path, port, est_rows):
    """`python laneclient.py run --expect-judge` on these rows: (exit code, stdout, stderr, the log's lines)."""
    est = tmp_path / "estimates.jsonl"
    est.write_text("".join(json.dumps(r) + "\n" for r in est_rows), encoding="utf-8", newline="\n")
    out = tmp_path / "replies.jsonl"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-B", str(CLIENT), "run", "--estimates", str(est), "--port", str(port),
                        "--out", str(out), "--expect-judge"], env=env, capture_output=True, text=True, timeout=120)
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()] if out.exists() else []
    return r.returncode, r.stdout, r.stderr, lines


def test_the_made_up_estimates_reach_every_reason_by_lanerules(tmp_path):
    """The file checked against the reference judge before the monitor sees it: each row packs to a well-formed
    request (by the client's own pack) that lanerules judges as the row says, and together they reach ACCEPT with and
    without a lane and every reason 28-31."""
    sys.dont_write_bytecode = True
    try:
        import laneclient as lc
    finally:
        sys.dont_write_bytecode = _saved
    es = lc.parse_estimates("".join(json.dumps(r) + "\n" for r in rows([GAP_MS] * len(ESTIMATES))).encode("utf-8"))
    got = []
    for k, (e, (what, _over, want)) in enumerate(zip(es, ESTIMATES), start=1):
        fr = lc.pack(e, k, 0, 1)
        assert lf.layout_errors(fr) == [], what
        got.append(lr.judge(fr))
        assert got[-1] == want, (what, got[-1], want)
    assert {r for _v, r in got} == {0, 28, 29, 30, 31}
    assert any(not e.lane_found for e in es) and any(e.lane_found and v == 0 for e, (v, _r) in zip(es, got))


def test_every_claim_the_client_sends_is_judged_by_the_monitor_as_lanerules_judges_it_and_never_gets_10(monitor, tmp_path):
    est_rows = rows([GAP_MS] * len(ESTIMATES))
    proc, port = mc._start_on_port(monitor, ["svc", str(SVC_MS)], socket.SOCK_STREAM, mc.BANNER["svc"])
    try:
        rc, stdout, stderr, lines = run_client(tmp_path, port, est_rows)
        proc.wait_for(b"monitor: client done:")
        mrc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0, (stdout, stderr)
    assert mrc == 0 and not proc.err, (mrc, b"".join(proc.err))
    recs, s = lines[1:-1], lines[-1]["summary"]
    assert lines[0]["header"]["kind"] == 6 and lines[0]["header"]["frames"] == len(ESTIMATES)
    assert [r["outcome"] for r in recs] == ["replied"] * len(ESTIMATES)
    bad = []
    for r, (what, _over, want) in zip(recs, ESTIMATES):
        fr = bytes.fromhex(r["frame"])
        if [r["verdict"], r["reason"]] != list(lr.judge(fr)) or (r["verdict"], r["reason"]) != want or r["reason"] == 10 \
                or r["layout"] != "ok" or r["expect"] != list(want):
            bad.append((what, r))
    assert not bad, bad
    assert s["judge"] == {"compared": len(ESTIMATES), "differ": 0, "differences": []}
    assert s["identity"] == {"packed": len(ESTIMATES), "replied": len(ESTIMATES), "drop": 0, "lost_on_reconnect": 0,
                             "holds": True}
    assert {b["reason"] for b in s["by_reason"]} == {0, 28, 29, 30, 31} and 10 not in {r["reason"] for r in recs}
    out = [ln.decode("ascii") for ln in proc.out]
    printed = [HARNESS_REGEX.search(ln).groups() for ln in out if ln.startswith("monitor: REJECT")]
    rejected = {(str(r["seq"]), r["name"]) for r in recs if r["verdict"] == 1}
    assert printed and all(p in rejected for p in printed), (printed, rejected)      # the limiter prints reason changes only
    accepted = sum(1 for r in recs if r["verdict"] == 0)
    assert "monitor: client done: seen=%d accepted=%d rejected=%d\n" % (len(recs), accepted, len(recs) - accepted) in out
    assert "differ=0" in stdout and "identity=holds" in stdout


def test_a_silence_over_the_deadline_is_closed_by_the_monitor_and_the_next_estimate_reconnects(monitor, tmp_path):
    n = 4
    est_rows = rows([0, GAP_MS, SILENCE_MS, GAP_MS][:n])
    proc, port = mc._start_on_port(monitor, ["svc", str(SVC_MS)], socket.SOCK_STREAM, mc.BANNER["svc"])
    try:
        rc, stdout, stderr, lines = run_client(tmp_path, port, est_rows)
        proc.wait_for(b"monitor: client done:", n=2)
        mrc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0, (stdout, stderr)
    assert mrc == 0 and not proc.err, (mrc, b"".join(proc.err))
    recs, s = lines[1:-1], lines[-1]["summary"]
    assert [r["outcome"] for r in recs] == ["replied"] * n
    assert s["counters"]["connects"] == 2 and s["counters"]["reconnects"] == 1
    assert s["identity"]["holds"] and s["identity"]["lost_on_reconnect"] == 0 and s["judge"]["differ"] == 0
    out = [ln.decode("ascii") for ln in proc.out]
    assert sum(1 for ln in out if ln.startswith("monitor: LIVENESS MISS:")) == 1
    assert sum(1 for ln in out if ln.startswith("monitor: LIVENESS RESTORED: seq=3 ")) == 1
    assert sum(1 for ln in out if ln.startswith("monitor: client closed: no complete frame for %d ms" % SVC_MS)) == 1


# The live source: the guest's mode, and the producer's gaps (its own sleeps, none a measurement).
LIVE_SVC_MS = 500        # ifs-lane.build's :7170 svc 500
LIVE_SILENCE_MS = 800    # over the deadline: one LIVENESS MISS and RESTORED pair, one reconnect
LIVE_SILENCE_AT = 8      # the 0-based row the silence comes before
PRODUCER = (
    "import json, os, sys, time\n"
    "plan, ready = sys.argv[1], sys.argv[2]\n"
    "end = time.monotonic() + 60\n"
    "while not os.path.exists(ready) and time.monotonic() < end:\n"
    "    time.sleep(0.01)\n"
    "for gap_ms, line in json.load(open(plan, encoding='utf-8')):\n"
    "    time.sleep(gap_ms / 1000.0)\n"
    "    sys.stdout.buffer.write(line.encode('utf-8'))\n"
    "    sys.stdout.buffer.flush()\n"
)


def test_live_claims_from_stdin_are_judged_by_the_monitor_as_lanerules_judges_them_and_a_silence_reconnects(lane_monitor,
                                                                                                          tmp_path):
    """The producer waits for the client's reply log (the client is then about to read stdin), then writes the rows
    with its gaps; `laneclient.py run --estimates - --expect-judge` sends each as its line comes."""
    kinds, binary = lane_monitor
    gaps = [0] + [GAP_MS] * (len(ESTIMATES) - 1)
    gaps[LIVE_SILENCE_AT] = LIVE_SILENCE_MS
    lines = [json.dumps(r) + "\n" for r in rows(gaps)]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([[g, ln] for g, ln in zip(gaps, lines)]), encoding="utf-8", newline="\n")
    script = tmp_path / "producer.py"
    script.write_text(PRODUCER, encoding="utf-8", newline="\n")
    out = tmp_path / "replies.jsonl"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc, port = mc._start_on_port(binary, ["svc", str(LIVE_SVC_MS)], socket.SOCK_STREAM, mc.BANNER["svc"])
    try:
        prod = subprocess.Popen([sys.executable, "-B", str(script), str(plan), str(out)], stdout=subprocess.PIPE, env=env)
        try:
            r = subprocess.run([sys.executable, "-B", str(CLIENT), "run", "--estimates", "-", "--port", str(port), "--out",
                                str(out), "--expect-judge"], stdin=prod.stdout, env=env, capture_output=True, text=True,
                               timeout=120)
        finally:
            assert prod.stdout is not None
            prod.stdout.close()
            prod.wait(timeout=60)
        proc.wait_for(b"monitor: client done:", n=2)
        mrc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert r.returncode == 0, (kinds, r.stdout, r.stderr)
    assert prod.returncode == 0 and mrc == 0 and not proc.err, (prod.returncode, mrc, b"".join(proc.err))
    logged = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    h, recs, s = logged[0]["header"], logged[1:-1], logged[-1]["summary"]
    assert h["source"] == "stdin" and "estimates_sha256" not in h and "frames" not in h and h["port"] == port
    assert [r["outcome"] for r in recs] == ["replied"] * len(ESTIMATES)
    bad = []
    for rec, (what, _over, want) in zip(recs, ESTIMATES):
        fr = bytes.fromhex(rec["frame"])
        if [rec["verdict"], rec["reason"]] != list(lr.judge(fr)) or (rec["verdict"], rec["reason"]) != want \
                or rec["reason"] == 10 or rec["layout"] != "ok" or rec["expect"] != list(want):
            bad.append((what, rec))
    assert not bad, (kinds, bad)
    assert {b["reason"] for b in s["by_reason"]} == {0, 28, 29, 30, 31} and any(not e["lane_found"] for e in rows(gaps))
    assert s["judge"] == {"compared": len(ESTIMATES), "differ": 0, "differences": []}
    assert s["identity"] == {"packed": len(ESTIMATES), "replied": len(ESTIMATES), "drop": 0, "lost_on_reconnect": 0,
                             "holds": True}
    assert (s["counters"]["connects"], s["counters"]["reconnects"]) == (2, 1)
    sha = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    assert s["source"] == {"name": "stdin", "estimates_sha256": sha, "estimates": len(ESTIMATES), "refused": None}
    console = [ln.decode("ascii") for ln in proc.out]
    assert sum(1 for ln in console if ln.startswith("monitor: LIVENESS MISS:")) == 1
    assert sum(1 for ln in console if ln.startswith("monitor: LIVENESS RESTORED: seq=%d " % (LIVE_SILENCE_AT + 1))) == 1
    assert sum(1 for ln in console if ln.startswith("monitor: client closed: no complete frame for %d ms" % LIVE_SVC_MS)) == 1
    printed = [HARNESS_REGEX.search(ln).groups() for ln in console if ln.startswith("monitor: REJECT")]
    rejected = {(str(rec["seq"]), rec["name"]) for rec in recs if rec["verdict"] == 1}
    assert printed and all(p in rejected for p in printed), (printed, rejected)
    assert "differ=0" in r.stdout and "identity=holds" in r.stdout and "source=stdin" in r.stdout
