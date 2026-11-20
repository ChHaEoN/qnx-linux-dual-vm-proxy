"""The C2b S3 contract test: the monitor's kind 6 judge and sdv/lane held to each other, on
tests/test_sdv_phase8_contract.py's pattern. The rules come from the project's local design notes, not in this tree.

monitor.c's kind 6 and sdv/lane (laneframe's codec, lanerules' judge) were written together, and laneclient.py
packs frames with laneframe alone and sends them to the monitor. This file holds the two together end to end, the way
that client meets the monitor:

- The native 0x50 build, made by build-monitor-native.sh itself (MONITOR_EXT_KINDS=0x50, its own OUT, the generated kind
  4 headers), serving `PORT svc 300`, is sent over one TCP connection a seeded corpus of frames packed by
  laneframe.encode (lanes and no lanes, with vehicle values and without, values inside and outside profile 1's limits,
  at their edges and one binary32 step past) and by laneframe.pack_bits (the injections a client could ask for: a
  non-finite value in each slot, profile 0, a confidence over 100). Every reply is a reply laneframe.decode_reply takes,
  echoes every byte but p[6] and p[7], and carries lanerules.judge's verdict and reason; none of the frames gets reason
  10 (a frame laneframe packs is a layout the monitor takes); the corpus reaches every reason 0, 8, 9 and 28-31.
- The console agrees with the replies: each REJECT line the harnesses' regex reads names the reply's seq and reason, no
  REJECT line names a frame that was accepted, and the client done: line counts what was sent.
- The liveness deadline still holds with kind 6: a silence over 300 ms prints one LIVENESS MISS, the next kind 6 claim
  one LIVENESS RESTORED.

Nothing here is a result: every value is profile 1's (2.4), a frame's or the specification's.

What this does NOT show: the guest build or its port pair 7170/7171; laneclient.py itself, a lane model
or a camera; any timing (the waits only bound when a line may come on a loaded host).

Needs gcc and bash on Linux and the generated kind 4 contract in sdv-out/gen (sdv/vss/generate.py); without them a test
skips, and under SDV_REQUIRE_GEN=1 it fails instead (tests/twin_gate.py).
"""
import os
import random
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
H = 16
HARNESS_REGEX = re.compile(r"REJECT seq=(\d+) .*?reason=([a-z-]+)")
REASONS = {0, 8, 9, 28, 29, 30, 31}
NONFINITE = (0x7F800000, 0xFF800000, 0x7FC00000, 0x7F800001, 0xFFFFFFFF)


@pytest.fixture(scope="module")
def monitor(tmp_path_factory):
    """The native 0x50 monitor, built by build-monitor-native.sh to its own OUT in a scratch HOME."""
    if shutil.which("gcc") is None or shutil.which("bash") is None or not hasattr(os, "sched_getaffinity"):
        twin_gate.missing("needs gcc and bash on Linux: runs in WSL and in CI's tooling job")
    gen = twin_gate.gen_dir()
    absent = [n for n in GEN_FILES if not (gen / n).is_file()]
    if absent:
        twin_gate.missing("needs the generated kind 4 contract in %s (sdv/vss/generate.py): no %s" % (gen, ", ".join(absent)))
    d = tmp_path_factory.mktemp("lane-native")
    home = d / "home"
    home.mkdir()
    out = d / "monitor-lane"
    env = {k: v for k, v in os.environ.items() if k not in ("MONITOR_EXT_KINDS", "MONITOR_VSS_GEN", "OUT", "FORCE", "CC")}
    env.update(HOME=str(home), OUT=str(out), MONITOR_EXT_KINDS="0x50", MONITOR_VSS_GEN=str(gen))
    r = subprocess.run(["bash", str(NATIVE)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "switch: MONITOR_EXT_KINDS=0x50 -ffp-contract=off" in r.stdout, r.stdout
    return str(out)


def _edge(x, limit, above):
    """The binary32 at or just inside a limit, and the one just past it."""
    f = lf.f32(limit)
    inside = f if (f <= limit if above else f >= limit) else (lf.f32_next_down(f) if above else lf.f32_next_up(f))
    past = lf.f32_next_up(inside) if above else lf.f32_next_down(inside)
    return inside, past


def corpus(rng, n):
    """[(frame, how)]: laneframe's frames, honest ones (encode) and injections (pack_bits)."""
    pr = lf.PROFILES[1]
    out = []
    seq = 1

    def add(fr, how):
        nonlocal seq
        out.append((fr, how))
        seq += 1

    # each limit of profile 1 at, and one binary32 step past, it
    for c in (pr.conf_min - 1, pr.conf_min, 100):
        add(lf.encode(seq=seq, conf=c, offset=0.0, heading=0.0, curvature=0.0, width=3.5), "conf %d" % c)
    for lim, above in ((pr.width_min, False), (pr.width_max, True)):
        for w in _edge(None, lim, above):
            add(lf.encode(seq=seq, conf=90, offset=0.0, heading=0.0, curvature=0.0, width=w), "width %r" % w)
    for name, lim in (("curvature", pr.k_max), ("heading", pr.h_max)):
        for v in _edge(None, lim, True):
            for s in (1.0, -1.0):
                kw = dict(offset=0.0, heading=0.0, curvature=0.0, width=3.5)
                kw[name] = s * v
                add(lf.encode(seq=seq, conf=90, **kw), "%s %r" % (name, s * v))
    room = 3.5 / 2 - pr.veh_half_w
    for v in _edge(None, room, True):
        for s in (1.0, -1.0):
            add(lf.encode(seq=seq, conf=90, offset=s * v, heading=0.0, curvature=0.0, width=3.5), "offset %r" % (s * v))
    # the injections a client could ask for
    for i, name in enumerate(("offset", "heading", "curvature", "width", "speed", "yaw_rate")):
        vals = dict(offset=0, heading=0, curvature=0, width=lf.f32_bits(3.5), speed=0, yaw_rate=0)
        vals[name] = NONFINITE[i % len(NONFINITE)]
        add(lf.pack_bits(seq=seq, flags=lf.F_LANE | lf.F_VEH, profile=1, conf=90, **vals), "%s non-finite" % name)
    add(lf.pack_bits(seq=seq, flags=0, profile=0), "profile 0")
    add(lf.pack_bits(seq=seq, flags=lf.F_LANE, profile=1, conf=101, offset=0, heading=0, curvature=0,
                     width=lf.f32_bits(3.5)), "conf 101")
    # and a seeded mixture of honest claims
    while len(out) < n:
        kw = dict(seq=seq, tstamp_ns=rng.randrange(1 << 63), age_ms=rng.randrange(0x10000))
        if rng.random() < 0.85:
            kw.update(conf=rng.choice((rng.randrange(101), rng.randrange(50, 101), 90)),
                      offset=rng.uniform(-1.4, 1.4), heading=rng.uniform(-0.55, 0.55), curvature=rng.uniform(-0.11, 0.11),
                      width=rng.uniform(2.4, 4.6))
        if rng.random() < 0.7:
            kw.update(speed=rng.choice((rng.uniform(-3.0, 40.0), rng.uniform(0.0, 2.0))), yaw_rate=rng.uniform(-1.0, 1.0))
        if rng.random() < 0.05:
            kw.update(profile=rng.choice((2, 7, 255)))
        add(lf.encode(**kw), "random")
    return out


def test_every_frame_laneframe_packs_is_judged_by_the_monitor_as_lanerules_judges_it_and_never_gets_10(monitor):
    frames = corpus(random.Random(1313), 2500)
    assert all(lf.layout_errors(f) == [] for f, _how in frames), "laneframe packs only well-formed requests"
    want = [lr.judge(f) for f, _how in frames]
    assert {r for _v, r in want} == REASONS, sorted({r for _v, r in want})
    proc, port = mc._start_on_port(monitor, ["svc", str(SVC_MS)], socket.SOCK_STREAM, mc.BANNER["svc"])
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=mc.REPLY_TIMEOUT) as s:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            replies = []
            for fr, _how in frames:
                s.sendall(fr)
                replies.append(mc._recv_exact(s, 64))
        proc.wait_for(b"monitor: client done:")
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    bad = []
    for (fr, how), rep, w in zip(frames, replies, want):
        d = lf.decode_reply(rep)
        if (d.verdict, d.reason) != tuple(w) or rep[:H + 6] != fr[:H + 6] or rep[H + 8:] != fr[H + 8:] or d.reason == 10:
            bad.append("%s: reply %s, lanerules %s" % (how, (d.verdict, d.reason), w))
    assert not bad, bad[:10]
    out = [ln.decode("ascii") for ln in proc.out]
    by_seq = {lf.decode_request(fr).seq: w for (fr, _how), w in zip(frames, want)}
    printed = [HARNESS_REGEX.search(ln).groups() for ln in out if ln.startswith("monitor: REJECT")]
    assert printed and all(lf.REASON_NAMES[by_seq[int(seq)][1]] == name for seq, name in printed), printed[:10]
    assert all(" kind=lane " in ln for ln in out if ln.startswith("monitor: REJECT"))
    accepted = sum(1 for v, _r in want if v == 0)
    assert "monitor: client done: seen=%d accepted=%d rejected=%d\n" % (len(frames), accepted, len(frames) - accepted) in out


def test_a_silence_over_the_deadline_is_one_miss_and_the_next_kind_6_claim_restores(monitor):
    f1 = lf.encode(seq=1, conf=90, offset=0.1, heading=0.0, curvature=0.0, width=3.5, speed=10.0, yaw_rate=0.0)
    f2 = lf.encode(seq=2, conf=10, offset=0.1, heading=0.0, curvature=0.0, width=3.5)
    f3 = lf.encode(seq=3)
    proc, port = mc._start_on_port(monitor, ["svc", str(SVC_MS)], socket.SOCK_STREAM, mc.BANNER["svc"])
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=mc.REPLY_TIMEOUT) as s:
            s.sendall(f1)
            r1 = mc._recv_exact(s, 64)
            s.sendall(f2)
            r2 = mc._recv_exact(s, 64)
            proc.wait_for(b"monitor: LIVENESS MISS:")
            proc.wait_for(b"monitor: client closed: no complete frame for %d ms" % SVC_MS)
        with socket.create_connection(("127.0.0.1", port), timeout=mc.REPLY_TIMEOUT) as s:
            s.sendall(f3)
            r3 = mc._recv_exact(s, 64)
        proc.wait_for(b"monitor: LIVENESS RESTORED:")
        proc.wait_for(b"monitor: client done:", n=2)
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    assert [(lf.decode_reply(r).verdict, lf.decode_reply(r).reason) for r in (r1, r2, r3)] == [(0, 0), (1, 28), (0, 0)]
    out = [ln.decode("ascii") for ln in proc.out]
    assert sum(1 for ln in out if ln.startswith("monitor: LIVENESS MISS:")) == 1
    assert sum(1 for ln in out if ln.startswith("monitor: LIVENESS RESTORED: seq=3 ")) == 1
    assert [ln for ln in out if ln.startswith("monitor: REJECT")] == ["monitor: REJECT seq=2 kind=lane profile=1 reason=lane-conf-low\n"]
