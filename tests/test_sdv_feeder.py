"""The Phase 7 live path (sdv/feeder, and `stack.py live`): the live feeder in WSL, the live stack run and F2's check (SDV
plan Phase 7 WP3c, spec-2 2.4 and section 6).

No CARLA, bus, monitor, bridge, Docker, PowerShell or network is used. The feeder runs WP1's take against
tests/fixtures/carla/fake_carla.py with a fake clock, and its sender's thread is made punctual by that clock (PumpClock: every
instant the sender is due at is pumped as the clock passes it); SocketCAN is a recording stand-in for the send, slice.dbc is
read by tests/test_sdv_carla.py's exact stand-in for cantools' database, fwcheck's PowerShell read is a stand-in result, and the
default route and /sys/class/net are text and files under tmp_path. `stack.py live` runs its preparation against the tree's
generation with Docker answered by a stand-in, and its run with every outside call replaced. f2check reads synthetic run
records.

Every number asserted here is a design value, a value of the generated contract, a value of the fake simulator or of a
synthetic record, or computed from them; none is a measurement. The addresses are RFC 5737 documentation addresses; the fake
CLOCK_REALTIME is the fake clock plus a fixed offset.
"""
import ast
import collections
import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

import test_sdv_carla as tsc

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FEEDER_DIR = REPO / "sdv" / "feeder"
STACK_DIR = REPO / "sdv" / "stack"
BRIDGE_DIR = REPO / "sdv" / "bridge"
SIM_LOCK = REPO / "sdv" / "sim" / "requirements.lock"
MS = 1_000_000

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(STACK_DIR) not in sys.path:
    sys.path.insert(0, str(STACK_DIR))
import attribution as attr  # noqa: E402
import stack  # noqa: E402
live = tsc._by_path("sdv_feeder_live", FEEDER_DIR / "live.py")
f2check = tsc._by_path("sdv_feeder_f2check", FEEDER_DIR / "f2check.py")
sys.dont_write_bytecode = _saved

C = tsc.C
fake = tsc.fake
sendpolicy = tsc.sendpolicy
NEEDS_CONTRACT = tsc.NEEDS_CONTRACT
REAL_OFFSET_NS = 1_700_000_000 * 10 ** 9      # the fake CLOCK_REALTIME: the fake clock plus this
NAME = "20261020-carla-7"
GATEWAY = "192.0.2.1"                          # RFC 5737: a documentation address, never a real one
PASS = (0, ["fwcheck: PASS (wsl)"])
ROUTE_HEADER = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"


def le_hex(addr):
    """An IPv4 address as /proc/net/route prints it: the 32-bit value in host order (little-endian here), in hex."""
    return "%08X" % int.from_bytes(socket.inet_aton(addr), "little")


def route_line(iface, dest, gw, flags, metric, mask):
    return "%s\t%s\t%s\t%04X\t0\t0\t%d\t%s\t0\t0\t0\n" % (iface, dest, gw, flags, metric, mask)


# "00FFFFFF" is a /24 netmask as /proc/net/route prints it (le_hex of the dotted mask, which the identifier gate would refuse)
ROUTE_TEXT = (ROUTE_HEADER + route_line("eth0", "00000000", le_hex(GATEWAY), 0x3, 0, "00000000")
              + route_line("eth0", le_hex("192.0.2.0"), "00000000", 0x1, 0, "00FFFFFF"))


def make_net(tmp_path, present=True, up=True, kind=280):
    """A /sys/class/net with vcan0 (ARPHRD_CAN 280, IFF_UP set) or as the case asks."""
    net = tmp_path / "sysnet"
    net.mkdir(parents=True, exist_ok=True)
    if present:
        (net / "vcan0").mkdir(exist_ok=True)
        (net / "vcan0" / "type").write_text("%d\n" % kind, encoding="ascii")
        (net / "vcan0" / "flags").write_text("0x%x\n" % (0xC1 if up else 0xC0), encoding="ascii")
    return net


class PumpClock:
    """fake_carla's Clock (a fake monotonic clock in ns: a sleep advances it exactly, a tick by the tick's wall time) with the
    live sender's thread made punctual: each instant the sender is due at is pumped at that instant while the clock moves past
    it. One the clock stops exactly at waits for the clock's next move, so a step made current at that very instant is the one
    sent (sendpolicy.schedule's rule: at an instant the newer step is current)."""

    def __init__(self, start_ns=5_000 * MS):
        self.now = start_ns
        self.sleeps = []
        self.sender = None

    def __call__(self):
        return self.now

    def attach(self, sender):
        self.sender = sender

    def _move(self, target):
        while self.sender is not None:
            due = self.sender.next_due()
            if due is None or due >= target:
                break
            self.now = max(self.now, due)
            self.sender.pump(self.now)
        self.now = max(self.now, target)

    def advance(self, ns):
        self._move(self.now + int(ns))

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self._move(self.now + max(0, int(math.ceil(seconds * 1e9))))


class Bus:
    """The SocketCAN send replaced: every frame with the fake clock's reading."""

    def __init__(self, clock):
        self.clock = clock
        self.sent = []

    def send(self, can_id, data):
        self.sent.append((self.clock(), can_id, bytes(data)))


def run_live(tmp_path, name=NAME, seed=7, freeze_at=None, fw=None, route=ROUTE_TEXT, net=None, out=None, host=GATEWAY,
             contract=None, drv=None, rv=None, db=None, extra=(), **faults):
    """`live.py run` in this process against a fresh fake simulator, the punctual sender and the recording send."""
    clock = PumpClock()
    carla = fake.make(clock, **faults)
    bus = Bus(clock)
    out = out if out is not None else tmp_path / "live" / name
    argv = ["run", "--name", name, "--seed", str(seed), "--host", host, "--out", str(out)]
    argv += (["--freeze-at-s", str(freeze_at)] if freeze_at is not None else []) + list(extra)
    live.capture._LOADS.clear()
    rc = live.main(argv, carla=carla, send=bus.send, db=db if db is not None else tsc.FakeDb(),
                   contract=contract if contract is not None else C, fwcheck_run=fw or (lambda: PASS), route_text=route,
                   sys_net=net if net is not None else make_net(tmp_path), clock_ns=clock,
                   realtime_ns=lambda: clock() + REAL_OFFSET_NS, sleep=clock.sleep,
                   drive_values=drv if drv is not None else tsc.short_drive(),
                   route_values=rv if rv is not None else tsc.short_route(), attach_sender=clock.attach)
    return types.SimpleNamespace(rc=rc, carla=carla, out=out, bus=bus, clock=clock)


def read_live(out):
    return json.loads((out / "live.json").read_text(encoding="utf-8"))


def period_ms(pol, m):
    return pol.dyn_period_ms if m == 0 else pol.gear_period_ms


def inst_ns(x, pol):
    """A send's instant on the take's clock from step 0 (its message's period times its instant number)."""
    return x[1] * period_ms(pol, x[0]) * MS


def _as_schedule(sends, pol):
    """Sends ([message, instant, step, ...]) as sendpolicy.schedule's frames: (instant [ms], message, step)."""
    return [(x[1] * period_ms(pol, x[0]), [pol.dyn_msg, pol.gear_msg][x[0]], x[2]) for x in sends]


def origin_abs(r):
    """The fake clock's reading at which step 0 became current: the first frame is the dynamics message's instant 0."""
    t, cid, _d = r.bus.sent[0]
    assert cid == tsc.FakeDb().get_message_by_name(tsc.policy().dyn_msg).frame_id
    return t


# =================================================================================================================
# live.py: the take, the sends, live.json
# =================================================================================================================

@NEEDS_CONTRACT
def test_a_live_take_writes_the_take_s_files_and_live_json_and_sends_what_sendpolicy_schedules(tmp_path):
    r = run_live(tmp_path)
    assert r.rc == 0
    assert sorted(p.name for p in r.out.iterdir()) == ["capture.json", "live.json", "script.jsonl", "steps.jsonl", "take.sha256"]
    listed = [ln.split("  ")[1] for ln in (r.out / "take.sha256").read_text(encoding="ascii").splitlines()]
    assert listed == ["steps.jsonl", "script.jsonl", "capture.json"]
    cap = tsc.read_capture(r.out)
    assert cap["completed"] is True and cap["cleanup"] == "ok" and cap["fwcheck"] == PASS[1][0] and cap["tm"] is None
    assert cap["name"] == NAME and cap["seed"] == 7
    steps = tsc.read_steps(r.out)
    pol = tsc.policy()
    sched = sendpolicy.schedule([(s["t_vals_ns"], s["t_cur_ns"]) for s in steps], pol)
    t0 = origin_abs(r)
    db = tsc.FakeDb()
    names = {db.get_message_by_name(m).frame_id: m for m in (pol.dyn_msg, pol.gear_msg)}
    sent = [((t - t0) // MS, names[cid]) for t, cid, _d in r.bus.sent]
    assert all((t - t0) % MS == 0 for t, _c, _d in r.bus.sent)
    assert sent == [(t, m) for t, m, _i in sched if t * MS < steps[-1]["t_cur_ns"]]
    doc = read_live(r.out)
    assert [(x[3] // MS, [pol.dyn_msg, pol.gear_msg][x[0]]) for x in doc["sends"]] == sent
    assert [x[2] for x in doc["sends"]] == [i for t, _m, i in sched if t * MS < steps[-1]["t_cur_ns"]]
    assert doc["steps_seen"] == len(steps) and doc["take_rc"] == 0 and doc["freeze"] is None


@NEEDS_CONTRACT
def test_the_live_frames_are_the_frames_the_encoder_writes_for_the_same_take(tmp_path, monkeypatch):
    """The live sender and WP1's encoder schedule and encode one way: every frame sent is the recording's frame at the same
    instant, byte for byte, and the recording holds no other frame before the take's last step (where the take's end cut
    the live sends)."""
    r = run_live(tmp_path)
    monkeypatch.setattr(tsc.encode, "load_dbc", lambda contract, path=None: tsc.FakeDb())
    monkeypatch.setattr(tsc.encode, "read_log", tsc.fake_read_log)
    rec = tmp_path / "rec" / NAME
    res = tsc.encode.record(r.out, rec, NAME, contract=tsc.synthetic_contract())
    assert res["verify"]["ok"] is True, res["verify"]["ok_terms"]
    logged = []
    for line in (rec / "carla.log").read_text(encoding="ascii").splitlines():
        m = re.fullmatch(r"\((\d{10})\.(\d{6})\) vcan0 ([0-9A-F]{3})#([0-9A-F]*)", line)
        assert m is not None
        logged.append((int(m.group(1)) * 1000 + int(m.group(2)) // 1000, int(m.group(3), 16), bytes.fromhex(m.group(4))))
    t0 = origin_abs(r)
    sent = [((t - t0) // MS, cid, data) for t, cid, data in r.bus.sent]
    last_cur_ms = tsc.read_steps(r.out)[-1]["t_cur_ns"] // MS
    assert sent and sent == [f for f in logged if f[0] < last_cur_ms]


# --- K4 16.4's F1 arms on the live sender ---------------------------------------------------------------------------

@NEEDS_CONTRACT
def test_f1_faster_than_real_time_is_held_to_the_pacing_and_every_step_reaches_two_dynamics_frames(tmp_path):
    r = run_live(tmp_path)                       # the fake's tick returns at once
    pol = tsc.policy()
    steps = tsc.read_steps(r.out)
    t_cur = [s["t_cur_ns"] for s in steps]
    assert all(b - a == pol.interval_ns for a, b in zip(t_cur, t_cur[1:]))
    doc = read_live(r.out)
    dyn = [x for x in doc["sends"] if x[0] == 0]
    gear = [x for x in doc["sends"] if x[0] == 1]
    per_step = collections.Counter(x[2] for x in dyn)
    assert all(per_step[i] >= 2 for i in range(len(steps) - 1))          # the last step's window is the take's end's
    assert all(b[2] - a[2] in (0, 1) for a, b in zip(dyn, dyn[1:]))      # no step skipped
    assert all(x[3] == x[1] * pol.dyn_period_ms * MS for x in dyn)
    assert gear and all(x[3] == x[1] * pol.gear_period_ms * MS for x in gear)   # the gear on its own timer
    assert tsc.read_capture(r.out)["rtf"]["max"] <= 1 and doc["gaps"] == [] and doc["capped"] == {pol.dyn_msg: 0, pol.gear_msg: 0}


@NEEDS_CONTRACT
def test_f1_no_catch_up_after_a_slow_step(tmp_path):
    """One slow step (its tick takes 120 ms), then fast ones: the next step becomes current a full step after it, the slow
    step's repeat window counts from when it became current, and no instant is sent twice or made up for later."""
    slow = 40
    r = run_live(tmp_path, tick_ns=lambda n: 120 * MS if n == slow + 1 + tsc.capture.SETTLE_TICKS else 0)
    pol = tsc.policy()
    steps = tsc.read_steps(r.out)
    t_cur = [s["t_cur_ns"] for s in steps]
    assert t_cur[slow] - t_cur[slow - 1] == 120 * MS
    assert t_cur[slow + 1] - t_cur[slow] == pol.interval_ns                  # no burst of two steps
    doc = read_live(r.out)
    sends = doc["sends"]
    mine = [x for x in sends if x[2] == slow]
    assert mine and all(t_cur[slow] <= inst_ns(x, pol) <= t_cur[slow] + pol.cap_ns for x in mine)
    before = [x for x in sends if x[2] == slow - 1]
    assert max(inst_ns(x, pol) for x in before) <= t_cur[slow - 1] + pol.cap_ns
    keys = [(x[0], x[1]) for x in sends]
    assert len(keys) == len(set(keys)) and all(0 <= x[3] - inst_ns(x, pol) <= live.LATE_HOOK_GUARD_MS * MS for x in sends)
    waited = [x for x in sends if x[3] != inst_ns(x, pol)]  # only at instants a newer step could have held: the slow step's
    assert waited and all(inst_ns(x, pol) >= t_cur[x[2]] + pol.interval_ns and x[2] == slow - 1 for x in waited)
    assert _as_schedule(sends, pol) == [f for f in sendpolicy.schedule([(s["t_vals_ns"], s["t_cur_ns"]) for s in steps], pol)
                                        if f[0] * MS < t_cur[-1]]
    assert slow in doc["gaps"] and slow in tsc.read_capture(r.out)["gaps"]


def test_a_late_sender_sends_only_the_latest_instant_of_each_message_and_counts_the_ones_it_missed():
    pol = tsc.policy()
    sent = []
    s = live.Sender(pol, lambda cid, data: sent.append((cid, bytes(data))), clock_ns=lambda: 0, realtime_ns=lambda: 0)
    frames = {pol.dyn_msg: (0x100, b"d" * 8), pol.gear_msg: (0x101, b"g" * 8)}
    assert s.next_due() is None and s.pump(5 * MS) is None and sent == []          # nothing before step 0
    s.current(0, 1000 * MS, frames, [])
    assert s.next_due() == 1000 * MS
    s.pump(1000 * MS)
    assert sent == [(0x100, b"d" * 8), (0x101, b"g" * 8)]
    late = 1000 * MS + 3 * pol.dyn_period_ms * MS + 5 * MS                          # three dynamics periods late, inside the cap
    s.pump(late)
    s.pump(late)                                                                    # pumped again at once: nothing more
    assert sent[2:] == [(0x101, b"g" * 8), (0x100, b"d" * 8)]                       # in their instants' order (50, then 60 ms)
    assert [(x[0], x[1]) for x in s.sends] == [(0, 0), (1, 0), (1, (late - 1000 * MS) // (pol.gear_period_ms * MS)), (0, 3)]
    assert s.record()["missed"] == {pol.dyn_msg: 2, pol.gear_msg: (late - 1000 * MS) // (pol.gear_period_ms * MS) - 1}


@NEEDS_CONTRACT
def test_f1_slower_than_real_time_each_step_is_repeated_for_the_cap_and_then_a_gap(tmp_path):
    r = run_live(tmp_path, tick_ns=lambda n: 100 * MS)
    pol = tsc.policy()
    steps = tsc.read_steps(r.out)
    t_cur = [s["t_cur_ns"] for s in steps]
    assert all(b - a == 100 * MS for a, b in zip(t_cur, t_cur[1:]))
    doc = read_live(r.out)
    sends = doc["sends"]
    for i in range(len(steps) - 1):
        mine = [x for x in sends if x[2] == i]
        assert mine and all(t_cur[i] <= inst_ns(x, pol) <= t_cur[i] + pol.cap_ns for x in mine), i
        assert not [x for x in sends if t_cur[i] + pol.cap_ns < inst_ns(x, pol) < t_cur[i + 1]], i
    assert all(0 <= x[3] - inst_ns(x, pol) <= live.LATE_HOOK_GUARD_MS * MS for x in sends)
    sched, got = sendpolicy.schedule([(s["t_vals_ns"], s["t_cur_ns"]) for s in steps], pol), _as_schedule(sends, pol)
    assert got == sched[:len(got)] and len(got) >= sum(1 for f in sched if f[0] * MS < t_cur[-1])   # the cleanup's ticks move on
    assert doc["gaps"] == list(range(1, len(steps))) == tsc.read_capture(r.out)["gaps"]
    assert doc["capped"][pol.dyn_msg] > 0          # the dynamics instants past the cap (the gear's 50 ms fall inside it)


@NEEDS_CONTRACT
@pytest.mark.parametrize("faults", [{"ignore_apply": True}, {"keep_async": True}, {"ignore_settings": ("fixed_delta_seconds",)}],
                         ids=["ignores-apply", "asynchronous", "another-step"])
def test_f1_another_fixed_delta_seconds_or_asynchronous_mode_is_refused_and_nothing_is_sent(tmp_path, faults):
    r = run_live(tmp_path, **faults)
    assert r.rc == 1 and r.bus.sent == []
    cap = tsc.read_capture(r.out)
    assert cap["completed"] is False and "world settings" in " ".join(cap["errors"])
    doc = read_live(r.out)
    assert doc["sends"] == [] and doc["steps_seen"] == 0 and doc["take_rc"] == 1


@NEEDS_CONTRACT
def test_f1_a_skipped_frame_shows_as_an_rtf_of_two_and_a_gap(tmp_path):
    r = run_live(tmp_path, frame_jump_at=30)
    steps = tsc.read_steps(r.out)
    cap, doc = tsc.read_capture(r.out), read_live(r.out)
    jumped = [k for k in range(1, len(steps)) if steps[k]["frame"] - steps[k - 1]["frame"] != 1]
    assert len(jumped) == 1 and jumped == cap["skipped_frames"]
    assert cap["rtf"]["max"] == pytest.approx(2.0) and cap["rtf"]["max"] > 1
    assert jumped[0] in cap["gaps"] and jumped[0] in doc["gaps"]


# --- the freeze ---------------------------------------------------------------------------------------------------

@NEEDS_CONTRACT
def test_the_freeze_stops_ticking_for_freeze_s_the_sends_stop_within_the_cap_and_live_json_records_the_last_frame(tmp_path):
    at = 3.0
    r = run_live(tmp_path, freeze_at=at)
    pol = tsc.policy()
    assert r.rc == 0
    steps, cap, doc = tsc.read_steps(r.out), tsc.read_capture(r.out), read_live(r.out)
    assert cap["completed"] is True and cap["cleanup"] == "ok"
    sim = [s["elapsed_s"] - steps[0]["elapsed_s"] for s in steps]
    assert sim[-1] > at >= sim[-2]                                    # the take ends at the first step past T
    fz = doc["freeze"]
    t_frozen = steps[-1]["t_cur_ns"]
    assert (fz["at_s"], fz["freeze_s"], fz["step"], fz["frame"]) == (at, live.FREEZE_S, steps[-1]["i"], steps[-1]["frame"])
    assert fz["start_ns"] == t_frozen and fz["end_ns"] - fz["start_ns"] >= live.FREEZE_S * 1e9
    assert fz["start_real_ns"] == fz["start_ns"] + origin_abs(r) + REAL_OFFSET_NS
    t0 = origin_abs(r)
    assert not [t for t in r.carla.sim.tick_clock if t0 + fz["start_ns"] <= t < t0 + fz["end_ns"]]     # no tick in the freeze
    last = doc["sends"][-1]                 # the instants stop within the cap; the last frame goes out at most the guard after its own
    g = live.LATE_HOOK_GUARD_MS * MS
    assert last[3] == max(x[3] for x in doc["sends"]) and inst_ns(last, pol) - t_frozen <= pol.cap_ns and last[3] - t_frozen <= pol.cap_ns + g
    assert max(inst_ns(x, pol) for x in doc["sends"]) - t_frozen <= pol.cap_ns
    assert fz["last_frame"] == {"message": [pol.dyn_msg, pol.gear_msg][last[0]], "instant": last[1], "step": last[2],
                                "t_ns": last[3], "t_real_ns": last[4]}
    assert max(t for t, _c, _d in r.bus.sent) - (t0 + t_frozen) <= pol.cap_ns + g
    assert _as_schedule(doc["sends"], pol) == sendpolicy.schedule([(s["t_vals_ns"], s["t_cur_ns"]) for s in steps], pol)
    assert doc["capped"][pol.dyn_msg] > 0 and doc["stale"] == {pol.dyn_msg: 0, pol.gear_msg: 0}


@NEEDS_CONTRACT
def test_freeze_s_covers_age_max_one_tick_and_the_repeat_cap_and_the_tick_is_the_bridge_s():
    assert live.FREEZE_S * 1000 >= C.AGE_MAX_MS + live.TICK_MS + C.FEEDER_REPEAT_CAP_MS + live.LATE_HOOK_GUARD_MS
    hz = re.search(r"^TICK_HZ = (\d+)$", (BRIDGE_DIR / "vss_claim_bridge.py").read_text(encoding="utf-8"), re.M)
    assert hz and live.TICK_MS == 1000 // int(hz.group(1))


@NEEDS_CONTRACT
def test_a_freeze_point_the_take_never_passes_freezes_nothing_and_says_so(tmp_path, capsys):
    r = run_live(tmp_path, freeze_at=100000.0)
    assert r.rc == 0 and read_live(r.out)["freeze"] is None and "no freeze" in capsys.readouterr().err


# --- out of range -------------------------------------------------------------------------------------------------

def _row(**over):
    row = {"i": 5, "frame": 105, "elapsed_s": 1.5, "t_vals_ns": 0, "t_cur_ns": 0, "seg": "route drive", "gear": 1, "v": [7.0, 0.0, 0.0],
           "a": [0.5, 0.0, 0.0], "fwd": [1.0, 0.0, 0.0], "w": [0.0, 0.0, 0.0], "steer": 0.0, "throttle": 0.3, "brake": 0.0,
           "reverse": False, "wheel_deg": [0.0, 0.0]}
    row.update(over)
    return row


@NEEDS_CONTRACT
def test_a_value_outside_the_dbc_range_sends_no_frame_and_is_logged_never_clamped():
    pol = tsc.policy()
    codec = live.Codec(tsc.FakeDb(), C, pol)
    front = [fake.FAKE_MAX_STEER_DEG, fake.FAKE_MAX_STEER_DEG]
    frames, problems = codec.frames(_row(v=[400.0, 0.0, 0.0]), front)
    assert frames is None and len(problems) == 1 and "LongVel" in problems[0] and "never clamped" in problems[0]
    sent = []
    s = live.Sender(pol, lambda cid, data: sent.append(cid), clock_ns=lambda: 0, realtime_ns=lambda: 0)
    s.current(5, 0, frames, problems)
    s.pump(0)
    s.pump(pol.dyn_period_ms * MS)
    assert sent == [] and s.record()["refused_steps"] == [{"i": 5, "problems": problems}]
    good, none = codec.frames(_row(), front)
    assert none == [] and set(good) == {pol.dyn_msg, pol.gear_msg}
    db = tsc.FakeDb()
    assert good[pol.dyn_msg] == (db.get_message_by_name(pol.dyn_msg).frame_id,
                                 db.get_message_by_name(pol.dyn_msg).encode({"LongVel": 7.0, "LongAccel": 0.5, "SteerAngleRow1": 0.0,
                                                                             "YawRate": 0.0}))
    bad_gear, why = codec.frames(_row(gear=-1), front)                # a gear its reverse flag denies: no frame either
    assert bad_gear is None and why


# --- the hook: step 0's dating on the realtime clock, and the freeze point ------------------------------------------------

class HookClock:
    """A fake monotonic clock in ns that only moves when a test moves it or the hook sleeps."""

    def __init__(self, start_ns=5_000 * MS):
        self.now = start_ns
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += int(round(seconds * 1e9))


def _hook(freeze_at=None):
    pol = tsc.policy()
    clock = HookClock()

    def real():
        return clock() + REAL_OFFSET_NS
    sender = live.Sender(pol, lambda cid, data: None, clock_ns=clock, realtime_ns=real)
    return live.Hook(sender, live.Codec(tsc.FakeDb(), C, pol), clock, real, clock.sleep, freeze_at), clock


def _ego():
    return {"front_max_steer_deg": [fake.FAKE_MAX_STEER_DEG, fake.FAKE_MAX_STEER_DEG]}


@NEEDS_CONTRACT
def test_the_hook_dates_step_0_on_the_realtime_clock_at_its_becoming_current_not_at_the_hook_s_call():
    """live.json's origin_real_ns is the CLOCK_REALTIME reading at step 0's becoming current, from the two clocks' offset at
    the call: the hook runs after the step became current, and the delay must not count."""
    hook, clock = _hook()
    t_cur = clock()
    clock.now += 7 * MS                                          # the hook follows the step's becoming current by 7 ms
    assert hook(_row(i=0, frame=100, elapsed_s=1.5), t_cur, _ego()) is None
    assert hook.origin_real_ns == t_cur + REAL_OFFSET_NS
    clock.now += 40 * MS
    hook(_row(i=1, frame=101, elapsed_s=1.55), clock() - 3 * MS, _ego())
    assert hook.origin_real_ns == t_cur + REAL_OFFSET_NS and hook.first_elapsed == 1.5      # step 0's, set once
    assert hook.frames_seen == [100, 101] and hook.t_cur_seen == [t_cur, clock() - 3 * MS]


@NEEDS_CONTRACT
def test_the_freeze_comes_at_the_first_step_whose_simulated_time_passes_t_not_at_the_one_that_reaches_it():
    t = 2.0
    hook, clock = _hook(t)
    hook(_row(i=0, frame=100, elapsed_s=1.5), clock(), _ego())
    clock.now += 50 * MS
    assert hook(_row(i=1, frame=101, elapsed_s=1.5 + t), clock(), _ego()) is None          # exactly T since step 0: not past it
    assert hook.freeze is None and clock.sleeps == []
    clock.now += 50 * MS
    start = clock()
    assert hook(_row(i=2, frame=102, elapsed_s=1.5 + t + 0.05), start, _ego()) is True      # the first step past T ends the take
    fz = hook.freeze
    assert (fz["step"], fz["frame"], fz["at_s"], fz["freeze_s"]) == (2, 102, t, live.FREEZE_S) and fz["sim_s"] == pytest.approx(t + 0.05)
    assert clock.sleeps == [live.FREEZE_S] and fz["end_ns"] - fz["start_ns"] == int(live.FREEZE_S * 1e9)
    assert hook(_row(i=3, frame=103, elapsed_s=1.5 + t + 0.1), clock(), _ego()) is None and clock.sleeps == [live.FREEZE_S]   # once


# --- refusals before connecting -------------------------------------------------------------------------------------

REFUSALS = ["fwcheck-fails", "fwcheck-unread", "host-not-the-route-s", "no-default-route", "host-not-an-address", "out-exists",
            "out-in-a-work-tree", "no-vcan0", "vcan0-down", "vcan0-not-can", "bad-name", "out-not-the-name", "freeze-zero",
            "freeze-nan", "negative-seed", "freeze-inf", "profile-3-not-compiled", "out-a-dangling-symlink"]


@NEEDS_CONTRACT
@pytest.mark.parametrize("case", REFUSALS)
def test_each_refusal_comes_before_connecting_and_writes_nothing(tmp_path, case):
    kw = {}
    if case == "fwcheck-fails":
        kw["fw"] = lambda: (1, ["fwcheck: FAIL (wsl): P3: (no WSL-scoped allow rule)"])
    elif case == "fwcheck-unread":
        kw["fw"] = lambda: (2, ["fwcheck: the firewall read failed (1): denied"])
    elif case == "host-not-the-route-s":
        kw["host"] = "192.0.2.2"
    elif case == "no-default-route":
        kw["route"] = ROUTE_HEADER + route_line("eth0", le_hex("192.0.2.0"), "00000000", 0x1, 0, "00FFFFFF")
    elif case == "host-not-an-address":
        kw["host"] = "localhost"
    elif case == "out-exists":
        (tmp_path / "live" / NAME).mkdir(parents=True)
        (tmp_path / "live" / NAME / "keep").write_text("x", encoding="ascii")
    elif case == "out-in-a-work-tree":
        (tmp_path / "wt" / ".git").mkdir(parents=True)
        kw["out"] = tmp_path / "wt" / "live" / NAME
    elif case == "no-vcan0":
        kw["net"] = make_net(tmp_path, present=False)
    elif case == "vcan0-down":
        kw["net"] = make_net(tmp_path, up=False)
    elif case == "vcan0-not-can":
        kw["net"] = make_net(tmp_path, kind=1)
    elif case == "bad-name":
        kw.update(name="20261020-carla-8", out=tmp_path / "live" / "20261020-carla-8")
    elif case == "out-not-the-name":
        kw["out"] = tmp_path / "live" / "elsewhere"
    elif case == "freeze-zero":
        kw["freeze_at"] = 0
    elif case == "freeze-nan":
        kw["freeze_at"] = "nan"
    elif case == "negative-seed":
        kw.update(seed=-7)
    elif case == "freeze-inf":
        kw["freeze_at"] = "inf"
    elif case == "profile-3-not-compiled":
        kw["contract"] = tsc.synthetic_contract(compiled=False)
    elif case == "out-a-dangling-symlink":
        (tmp_path / "live").mkdir()
        try:
            os.symlink(tmp_path / "nowhere", tmp_path / "live" / NAME)
        except (OSError, NotImplementedError):
            pytest.skip("symbolic links cannot be made here")
    r = run_live(tmp_path, **kw)
    assert r.rc == 2 and r.carla.sim.calls == [] and r.bus.sent == []
    if case == "out-exists":
        assert sorted(p.name for p in r.out.iterdir()) == ["keep"]
    elif case == "out-a-dangling-symlink":
        assert r.out.is_symlink() and not (tmp_path / "nowhere").exists()          # nothing was made through it
    else:
        assert not r.out.exists()


def test_the_default_gate_is_fwcheck_for_wsl_whole_with_p4_and_the_interpreters_read_through_wsl_s_mount(tmp_path, monkeypatch):
    seen = []

    def spy(for_, runner=None, tm=True, interpreters=None):
        seen.append((for_, tm, tuple(interpreters())))
        return 0, ["fwcheck: PASS (%s)" % for_]
    monkeypatch.setattr(live.fwcheck, "run", spy)
    venv = tmp_path / "mnt" / "e" / "CARLA" / "venv312"
    venv.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = C:\\Python312\nversion = 3.12.10\n", encoding="utf-8")
    monkeypatch.setattr(live, "MOUNT_ROOT", str(tmp_path / "mnt"))
    assert live.fwcheck_wsl() == (0, ["fwcheck: PASS (wsl)"])
    assert seen == [("wsl", True, ("C:\\Python312\\python.exe", "E:\\CARLA\\venv312\\Scripts\\python.exe"))]
    assert live.wsl_path(r"E:\CARLA\venv312\pyvenv.cfg") == str(tmp_path / "mnt") + "/e/CARLA/venv312/pyvenv.cfg"
    with pytest.raises(ValueError):
        live.wsl_path("/already/a/posix/path")


def test_the_gateway_is_the_default_route_s_and_no_refusal_prints_an_address():
    assert live.default_gateway(ROUTE_TEXT) == GATEWAY
    two = (ROUTE_HEADER + route_line("eth1", "00000000", le_hex("192.0.2.9"), 0x3, 100, "00000000")
           + route_line("eth0", "00000000", le_hex(GATEWAY), 0x3, 5, "00000000"))
    assert live.default_gateway(two) == GATEWAY                                    # the lowest metric
    assert live.default_gateway(ROUTE_HEADER) is None
    assert live.default_gateway(ROUTE_HEADER + route_line("eth0", "00000000", le_hex(GATEWAY), 0x2, 0, "00000000")) is None   # not up
    assert live.default_gateway(ROUTE_HEADER + route_line("eth0", "00000000", le_hex(GATEWAY), 0x3, 0, "000000FF")) is None   # not the default
    assert live.gateway_problem(GATEWAY, ROUTE_TEXT) is None
    for host, route in (("192.0.2.2", ROUTE_TEXT), (GATEWAY, ROUTE_HEADER), ("not-an-address", ROUTE_TEXT)):
        p = live.gateway_problem(host, route)
        assert p and GATEWAY not in p and "192.0.2.2" not in p


def test_vcan0_must_be_a_can_interface_that_is_up_and_every_other_type_is_refused(tmp_path):
    assert live.vcan_problem(make_net(tmp_path / "ok")) is None
    for kind in (1, 776):                                          # Ethernet, and another type that is not ARPHRD_CAN (280)
        why = live.vcan_problem(make_net(tmp_path / ("k%d" % kind), kind=kind))
        assert why and "not a CAN interface" in why and ("type %d" % kind) in why
    assert "is down" in live.vcan_problem(make_net(tmp_path / "down", up=False))
    assert "no vcan0" in live.vcan_problem(make_net(tmp_path / "none", present=False))


@NEEDS_CONTRACT
def test_the_live_run_starts_no_traffic_manager_and_opens_no_listener(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(socket.socket, "bind", lambda self, *a: opened.append(("bind", a)))
    monkeypatch.setattr(socket.socket, "listen", lambda self, *a: opened.append(("listen", a)))
    r = run_live(tmp_path, freeze_at=2.0)
    assert r.rc == 0 and opened == []
    assert not [c for c in r.carla.sim.calls if c.startswith(("get_trafficmanager", "set_autopilot"))]
    calls = {n.func.attr for n in ast.walk(ast.parse((FEEDER_DIR / "live.py").read_text(encoding="utf-8")))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {"get_trafficmanager", "set_autopilot", "listen", "bind", "accept"}


@NEEDS_CONTRACT
def test_the_gateway_address_is_written_to_no_file_and_printed_nowhere(tmp_path, capsys):
    r = run_live(tmp_path, freeze_at=2.0)
    assert r.rc == 0
    for p in r.out.iterdir():
        assert GATEWAY not in p.read_text(encoding="utf-8", errors="replace"), p.name
    out = capsys.readouterr()
    assert GATEWAY not in out.out and GATEWAY not in out.err


LIVE_KEYS = {"format", "name", "seed", "channel", "policy", "dbc_sha256", "contract_sha256", "live_sha256", "fwcheck", "clock",
             "origin_real_ns", "send_keys", "sends", "counts", "capped", "missed", "refused_steps", "send_errors", "gaps",
             "steps_seen", "freeze", "take_rc", "late_hook_guard_ms", "stale", "stale_sends"}


@NEEDS_CONTRACT
def test_live_json_holds_the_sends_the_gaps_and_the_freeze_and_names_what_made_them(tmp_path):
    r = run_live(tmp_path, freeze_at=2.0)
    pol = tsc.policy()
    doc = read_live(r.out)
    assert set(doc) == LIVE_KEYS and doc["format"] == 1 and (doc["name"], doc["seed"], doc["channel"]) == (NAME, 7, "vcan0")
    assert doc["send_keys"] == ["message", "instant", "step", "t_ns", "t_real_ns"]
    assert doc["policy"] == {"step_ms": pol.step_ms, "interval_ms": pol.interval_ms, "cap_ms": pol.cap_ms, "messages": [pol.dyn_msg, pol.gear_msg],
                             "periods_ms": [pol.dyn_period_ms, pol.gear_period_ms]}
    assert doc["origin_real_ns"] == origin_abs(r) + REAL_OFFSET_NS
    assert all(x[4] - x[3] == doc["origin_real_ns"] for x in doc["sends"])          # both clocks of every send
    assert doc["counts"] == {pol.dyn_msg: sum(1 for x in doc["sends"] if x[0] == 0), pol.gear_msg: sum(1 for x in doc["sends"] if x[0] == 1)}
    assert len(doc["sends"]) == len(r.bus.sent) and doc["send_errors"] == [] and doc["refused_steps"] == []
    assert doc["fwcheck"] == PASS[1][0] and doc["live_sha256"] == hashlib.sha256((FEEDER_DIR / "live.py").read_bytes()).hexdigest()
    assert doc["dbc_sha256"] == hashlib.sha256(tsc.SLICE_DBC.read_bytes()).hexdigest()
    assert doc["contract_sha256"] == hashlib.sha256(Path(C.__file__).read_bytes()).hexdigest()
    text = (r.out / "live.json").read_text(encoding="utf-8")
    assert text == json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n"


@NEEDS_CONTRACT
def test_live_json_calls_a_step_a_gap_only_when_it_became_current_more_than_the_repeat_cap_after_the_one_before(tmp_path):
    """A step slower than the pacing interval but within the repeat cap is not a gap (the frames still cover it); one past the
    cap is (K4 16.4's slower-than-real-time arm)."""
    pol = tsc.policy()
    within, past = 60, 120
    assert pol.interval_ms < within <= pol.cap_ms < past                       # the premise: the two durations' places
    a, b = 20, 40
    settle = tsc.capture.SETTLE_TICKS
    r = run_live(tmp_path, tick_ns=lambda n: {a + 1 + settle: within * MS, b + 1 + settle: past * MS}.get(n, 0))
    t_cur = [s["t_cur_ns"] for s in tsc.read_steps(r.out)]
    assert t_cur[a] - t_cur[a - 1] == within * MS and t_cur[b] - t_cur[b - 1] == past * MS
    assert read_live(r.out)["gaps"] == [b] == tsc.read_capture(r.out)["gaps"]


@NEEDS_CONTRACT
def test_a_send_that_fails_is_counted_and_fails_the_run_and_the_sender_goes_on(tmp_path, monkeypatch):
    calls = []

    def flaky(cid, data):
        calls.append(cid)
        if len(calls) == 3:
            raise OSError("fake: no buffer space")
    clock = PumpClock()
    carla = fake.make(clock)
    live.capture._LOADS.clear()
    out = tmp_path / "live" / NAME
    rc = live.main(["run", "--name", NAME, "--seed", "7", "--host", GATEWAY, "--out", str(out), "--freeze-at-s", "1.0"],
                   carla=carla, send=flaky, db=tsc.FakeDb(), contract=C, fwcheck_run=lambda: PASS, route_text=ROUTE_TEXT,
                   sys_net=make_net(tmp_path), clock_ns=clock, realtime_ns=lambda: clock() + REAL_OFFSET_NS, sleep=clock.sleep,
                   drive_values=tsc.short_drive(), route_values=tsc.short_route(), attach_sender=clock.attach)
    doc = read_live(out)
    assert rc == 1 and len(doc["send_errors"]) == 1 and "no buffer space" in doc["send_errors"][0]["error"]
    assert len(doc["sends"]) == len(calls) - 1 > 3


def test_the_sender_thread_paces_on_the_real_clock_and_stops():
    pol = tsc.policy()
    sent = []
    s = live.Sender(pol, lambda cid, data: sent.append((time.perf_counter_ns(), cid)), clock_ns=time.perf_counter_ns,
                    realtime_ns=time.time_ns)
    th = live.SenderThread(s, time.perf_counter_ns)
    th.start()
    t_cur = time.perf_counter_ns()
    s.current(0, t_cur, {pol.dyn_msg: (0x100, b"\0" * 8), pol.gear_msg: (0x101, b"\0" * 8)}, [])
    time.sleep(0.25)
    th.stop()
    assert not th.thread.is_alive()
    assert sent and all(t - t_cur <= pol.cap_ns + 50 * MS for t, _c in sent)     # nothing long after the cap (scheduling slack)
    assert all(inst_ns(x, pol) <= pol.cap_ns for x in s.sends)                  # no instant past the cap
    assert s.record()["stale"] == {pol.dyn_msg: 0, pol.gear_msg: 0}


# --- an instant a newer step may hold: the take's hook comes after the step became current ----------------------------

def _frames(i):
    pol = tsc.policy()
    return {pol.dyn_msg: (0x100, bytes([i]) * 8), pol.gear_msg: (0x101, bytes([i]) * 8)}


def test_at_an_instant_a_newer_step_may_hold_the_sender_waits_for_the_hook_and_sends_the_step_current_at_that_instant():
    """The take announces a step through its hook only after the step became current and was written, so at an instant one
    pacing interval or more after the latest step announced a newer one may already be current (no step becomes current
    sooner: sendpolicy.became_current). There the sender waits for the hook, up to LATE_HOOK_GUARD_MS, then sends the step
    that was current at the instant, as sendpolicy.schedule does: not the newest it knows, not the one it knew first."""
    pol = tsc.policy()
    sent = []
    s = live.Sender(pol, lambda cid, data: sent.append((cid, bytes(data))), clock_ns=lambda: 0, realtime_ns=lambda: 0)
    g, o = live.LATE_HOOK_GUARD_MS * MS, 1000 * MS
    assert 0 < g < min(pol.dyn_period_ms, pol.gear_period_ms) * MS
    s.current(0, o, _frames(0), [])
    for t in (0, 20, 40):
        s.pump(o + t * MS)
    nxt = o + pol.interval_ns                                   # the gear's instant 1: step 1 may be current there
    assert s.pump(nxt) == nxt + g and len(s.sends) == 4         # nothing sent at it yet: the hook has the guard
    s.current(1, nxt, _frames(1), [])                           # the hook, 2 ms late: step 1 became current at that instant
    assert s.next_due() == nxt
    s.pump(nxt + 2 * MS)
    assert s.sends[-1][:4] == [1, 1, 1, pol.interval_ns + 2 * MS] and sent[-1] == (0x101, bytes([1]) * 8)
    s.pump(o + 60 * MS)
    s.pump(o + 80 * MS)
    assert s.pump(o + 100 * MS) == o + 100 * MS + g             # the dynamics' instant 5 and the gear's 2: wait again
    s.current(2, o + 103 * MS, _frames(2), [])                  # step 2 became current after that instant (a slow tick)
    s.pump(o + 103 * MS)
    steps = [(0, 0), (pol.interval_ns, pol.interval_ns), (103 * MS, 103 * MS)]
    assert _as_schedule(s.sends, pol) == [f for f in sendpolicy.schedule(steps, pol) if f[0] <= 100]
    assert s.sends[-2][:3] == [0, 5, 1] and s.sends[-1][:3] == [1, 2, 1]      # step 1's, the step current at 100 ms
    assert s.record()["stale"] == {pol.dyn_msg: 0, pol.gear_msg: 0}


def test_a_hook_later_than_the_guard_leaves_its_instant_to_the_step_before_and_is_counted_stale():
    pol = tsc.policy()
    s = live.Sender(pol, lambda cid, data: None, clock_ns=lambda: 0, realtime_ns=lambda: 0)
    g, o = live.LATE_HOOK_GUARD_MS * MS, 1000 * MS
    s.current(0, o, _frames(0), [])
    for t in (0, 20, 40):
        s.pump(o + t * MS)
    nxt = o + pol.interval_ns
    s.pump(nxt)
    s.pump(nxt + g)                                             # the guard ran out: the gear's instant 1 from step 0
    assert s.sends[-1][:3] == [1, 1, 0]
    s.current(1, nxt, _frames(1), [])                           # step 1 had become current at that instant
    s.pump(o + 60 * MS)
    rec = s.record()
    assert rec["stale"] == {pol.dyn_msg: 0, pol.gear_msg: 1}
    assert rec["stale_sends"] == [{"message": pol.gear_msg, "instant": 1, "sent_step": 0, "current_step": 1}]
    assert s.sends[-1][:3] == [0, 3, 1]


def _timeline(s, steps_ms, end_ms):
    """Drive a Sender through an exact timeline: step i is announced at its t_cur (the hook right on time) and the sender is
    pumped at each moment next_due() gives, in time order, an announcement before a pump at the same moment (the PumpClock's
    rule), until end_ms from step 0."""
    pending = list(enumerate(steps_ms))
    while True:
        due = s.next_due()
        if pending and (due is None or pending[0][1] * MS <= due):
            i, t = pending.pop(0)
            s.current(i, t * MS, _frames(i), [])
            continue
        if due is None or due > end_ms * MS:
            return
        s.pump(due)


def test_a_frame_exactly_at_the_repeat_cap_is_sent_and_the_one_a_period_later_is_not():
    """sendpolicy.schedule sends a frame whose step has been current for exactly the repeat cap (it caps only past it). Step 1
    becomes current one pacing interval after step 0 and step 2 a pacing interval after the instant that lies exactly one cap
    after step 1: at that instant the sender cannot rule out a newer step, waits the guard, and sends step 1's frame."""
    pol = tsc.policy()
    t1 = pol.interval_ms
    edge = t1 + pol.cap_ms
    t2 = edge + pol.interval_ms
    assert edge % pol.dyn_period_ms == 0 and edge >= t1 + pol.interval_ms and t2 > edge + live.LATE_HOOK_GUARD_MS    # the premises
    sent = []
    s = live.Sender(pol, lambda cid, data: sent.append(cid), clock_ns=lambda: 0, realtime_ns=lambda: 0)
    _timeline(s, [0, t1, t2], t2 + pol.cap_ms + live.LATE_HOOK_GUARD_MS)
    steps = [(0, 0), (t1 * MS, t1 * MS), (t2 * MS, t2 * MS)]
    sched = sendpolicy.schedule(steps, pol)
    assert _as_schedule(s.sends, pol) == sched
    assert (edge, pol.dyn_msg, 1) in sched and (edge + pol.dyn_period_ms, pol.dyn_msg, 1) not in sched
    at_edge = [x for x in s.sends if x[0] == 0 and x[1] * pol.dyn_period_ms == edge]
    assert len(at_edge) == 1 and at_edge[0][2] == 1 and at_edge[0][3] == edge * MS + live.LATE_HOOK_GUARD_MS * MS
    assert s.record()["capped"][pol.dyn_msg] >= 1 and s.record()["stale"] == {pol.dyn_msg: 0, pol.gear_msg: 0}


def _sleep_until(t_ns):
    while True:
        d = t_ns - time.perf_counter_ns()
        if d <= 0:
            return
        time.sleep(d / 1e9)


def test_with_the_real_thread_a_hook_late_by_less_than_the_guard_still_gives_its_instant_the_step_current_at_it(monkeypatch):
    """The sender's own thread and the real clocks: steps 1 and 2 become current exactly at instants of the dynamics message
    (60 and 120 ms, slow ticks) and the take's hook announces each 2 ms later. The frames of those instants carry the new
    step, as sendpolicy.schedule's do, and every frame sent is schedule's. The guard is set wider for this test only (still
    below the 20 ms period), so that a loaded machine's late wake-ups cannot turn the order of the two threads."""
    monkeypatch.setattr(live, "LATE_HOOK_GUARD_MS", 15, raising=False)
    pol = tsc.policy()
    s = live.Sender(pol, lambda cid, data: None, clock_ns=time.perf_counter_ns, realtime_ns=time.time_ns)
    th = live.SenderThread(s, time.perf_counter_ns)
    th.start()
    t0 = time.perf_counter_ns()
    s.current(0, t0, _frames(0), [])
    for i, at in ((1, 60), (2, 120)):
        _sleep_until(t0 + (at + 2) * MS)
        s.current(i, t0 + at * MS, _frames(i), [])
    _sleep_until(t0 + 260 * MS)
    th.stop()
    assert not th.thread.is_alive() and th.error is None
    sched = {(t, m): i for t, m, i in sendpolicy.schedule([(0, 0), (60 * MS, 60 * MS), (120 * MS, 120 * MS)], pol)}
    got = {(t, m): i for t, m, i in _as_schedule(s.sends, pol)}
    assert got.get((60, pol.dyn_msg)) == 1 and got.get((120, pol.dyn_msg)) == 2, got
    assert all(sched.get(k) == v for k, v in got.items()), (got, sched)
    woke = [x for x in s.sends if x[0] == 0 and x[1] in (3, 6)]       # sent on the announcement, not at the guard's end
    assert len(woke) == 2 and all(x[3] - inst_ns(x, pol) < 15 * MS for x in woke), woke


CARLA_VENV_PY = Path(os.environ.get("SDV_CARLA_VENV", "~/sdv-carla-venv")).expanduser() / "bin" / "python"
NEEDS_CARLA_VENV = pytest.mark.skipif(not CARLA_VENV_PY.exists(),
                                      reason="needs the feeder's venv ~/sdv-carla-venv from requirements-live.lock (sdv/feeder/README.md)")
_VENV_CODEC = r"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("sdv_feeder_live", sys.argv[1])
live = importlib.util.module_from_spec(spec)
sys.modules["sdv_feeder_live"] = live
spec.loader.exec_module(live)
contract = live.vssframe.load_contract()
pol = live.sendpolicy.Policy.from_contract(contract)
codec = live.Codec(live.encode.load_dbc(contract), contract, pol)
out = []
for row in json.loads(sys.argv[2]):
    frames, problems = codec.frames(row, [70.0, 70.0])
    out.append([None if frames is None else {m: [c, d.hex()] for m, (c, d) in frames.items()}, problems])
print(json.dumps(out))
"""


@NEEDS_CONTRACT
@NEEDS_CARLA_VENV
def test_in_the_feeder_venv_cantools_encodes_as_the_stand_in_does_and_a_refusal_needs_nothing_else(tmp_path):
    """The feeder's own venv, its real cantools against the tree's slice.dbc: the frames the stand-in gives in this process,
    and the same refusal; then live.py itself refuses an existing --out there before anything else (no fwcheck, no bus)."""
    rows = [_row(), _row(i=6, v=[-1.5, 0.0, 0.0], a=[0.4, 0.0, 0.0], steer=0.0, wheel_deg=[-6.25, -6.25], w=[0.0, 0.0, 4.5], gear=-1,
                         reverse=True), _row(i=7, v=[400.0, 0.0, 0.0])]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([str(CARLA_VENV_PY), "-c", _VENV_CODEC, str(FEEDER_DIR / "live.py"), json.dumps(rows)], capture_output=True,
                       text=True, env=env, timeout=120, cwd=str(REPO))
    assert p.returncode == 0, p.stderr[-2000:]
    got = json.loads(p.stdout)
    codec = live.Codec(tsc.FakeDb(), C, tsc.policy())
    for (frames, problems), row in zip(got, rows):
        want, why = codec.frames(row, [70.0, 70.0])
        assert (frames is None) == (want is None) and len(problems) == len(why)
        if want is not None:
            assert frames == {m: [c, d.hex()] for m, (c, d) in want.items()}
    (tmp_path / NAME).mkdir()
    q = subprocess.run([str(CARLA_VENV_PY), str(FEEDER_DIR / "live.py"), "run", "--name", NAME, "--seed", "7", "--host", GATEWAY,
                        "--out", str(tmp_path / NAME)], capture_output=True, text=True, env=env, timeout=120, cwd=str(REPO))
    assert q.returncode == 2 and "refused" in q.stderr and "exists" in q.stderr


# --- the venv's lock and the README ---------------------------------------------------------------------------------

def _lock(path):
    pins = {}
    for m in re.finditer(r"^([A-Za-z0-9_.-]+)==(\S+) \\\n((?:\s+--hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", path.read_text(encoding="utf-8"), re.M):
        pins[m.group(1).lower()] = (m.group(2), re.findall(r"sha256:([0-9a-f]{64})", m.group(3)))
    return pins


def test_the_feeder_lock_is_the_carla_wheel_and_the_sim_lock_s_cantools_and_python_can_resolution_nothing_else():
    lock = FEEDER_DIR / "requirements-live.lock"
    pins, sim = _lock(lock), _lock(SIM_LOCK)
    assert sim and pins == dict(sim, carla=("0.9.16", ["c323a7b1f8ad3ac81cfac79f5d96c9cac8afa6d0a768fa2fffa46bb336945c4f"]))
    assert all(len(h) == 1 for _v, h in pins.values())
    text = lock.read_text(encoding="utf-8")
    assert "carla-0.9.16-cp312-cp312-manylinux_2_31_x86_64.whl" in text and "--require-hashes --no-deps" in text
    assert len(re.findall(r"^[A-Za-z0-9_.-]+==", text, re.M)) == len(pins)


def test_the_readme_gives_the_venv_the_two_commands_the_refusals_and_what_it_does_not_show():
    text = re.sub(r"\s+", " ", (FEEDER_DIR / "README.md").read_text(encoding="utf-8"))
    for s in ("~/sdv-carla-venv", "requirements-live.lock", "--require-hashes --no-deps", "live.py run --name", "--freeze-at-s",
              "stack.py live [--name N] --bridge", "--feeder-out", "f2check.py", "f2.json", "live.json", "fwcheck --for wsl", "default route",
              "vcan0", "carla-feeder", "not built", "no Traffic Manager", "no listener", "FREEZE_S", "does not demonstrate",
              "CAN timing", "arbitration", "any timing", "vehicle dynamics", "MISS", "lower bound"):
        assert s in text, s


# =================================================================================================================
# stack.py live: the live run's header, its record close, its run
# =================================================================================================================

def _live_ctx(tmp_path, monkeypatch, mode, prepare=True, man=None):
    """A LiveContext on the tree's generation, prepared without pulling, building, the bridge image or the native monitor:
    Docker, the time-sync read and the DBC sources replaced, the DBC staged from a cache under tmp_path."""
    if C is None:
        pytest.skip("needs the generated contract")
    monkeypatch.delenv(stack.HOST_ROLE_ENV, raising=False)
    monkeypatch.setenv(stack.TWIN_CONTROL_ENV, str(tmp_path / "no-marker"))
    gen_man = json.loads((stack.GEN / "manifest.json").read_text(encoding="utf-8"))
    sha = gen_man["inputs"]["slice.dbc"]
    cache = tmp_path / "cache"
    (cache / "dbc").mkdir(parents=True)
    (cache / "dbc" / ("%s.dbc" % sha)).write_bytes(tsc.SLICE_DBC.read_bytes())
    monkeypatch.setattr(stack, "CACHE", cache)
    monkeypatch.setattr(stack, "load_dbc_sources", lambda: {})
    monkeypatch.setattr(stack, "docker", lambda *a, **_kw: subprocess.CompletedProcess(a, 0, "27.0\n", ""))
    monkeypatch.setattr(stack, "run", lambda *a, **kw: pytest.fail("a live context ran a command: %r" % (a[:1],)))
    monkeypatch.setattr(stack, "time_sync", lambda: {"daemon": "none", "synchronised": False})
    if man is not None:
        monkeypatch.setattr(stack, "generation_manifest", lambda: man)
    feeder_out = tmp_path / "takes" / NAME
    ctx = stack.LiveContext(tmp_path / "runs" / "20261020-live", mode, feeder_out)
    got = ctx.prepare(pull=False, build=False, bridge_parts=False) if prepare else None
    return ctx, got


def _profile3():
    pid = int(C.LIVE_DEFAULT_PROFILE["carla"])
    return pid, {int(r["id"]): r for r in C.PROFILES}[pid]


@NEEDS_CONTRACT
@pytest.mark.parametrize("mode", ["broker", "can"])
def test_the_live_run_header_is_carla_live_profile_3_live_default_with_source_rtf_null_and_c12a_holds(tmp_path, monkeypatch, mode):
    ctx, man = _live_ctx(tmp_path, monkeypatch, mode)
    h = ctx.run_header(stack.LIVE_REPLAY, "vcan")
    pid, row = _profile3()
    assert (h["run_type"], h["feed"], h["bridge_mode"], h["profile_id"], h["profile_source"], h["source_rtf"]) == (
        "carla", "live", mode, pid, "live-default", None)
    assert h["source_vehicle"] == {"name": stack.LIVE_SOURCE_VEHICLE, "wheelbase_mm": int(row["l_mm"])}
    assert h["age_max_ms"] == C.AGE_MAX_MS and h["demo_odd_window"] is None and h["recordings"] == []
    assert h["time_sync"]["age_clock"] == stack.AGE_CLOCK[mode] and h["header_check"] is None
    assert h["catalogue"]["databroker_json_sha256"] == "sha256:" + stack.sha256_file(stack.GEN / "vss-databroker-carla.json")
    assert h["run_id"].endswith("-vss-live-%s" % stack.LIVE_REPLAY)
    c12a = ctx.check_header(h)
    assert c12a[1], c12a
    assert not ctx.check_header(dict(h, profile_id=1))[1]                       # the live default is carla's 3, not sigsim's 1
    staged = ctx.run_dir / "in"
    assert sorted(os.listdir(staged)) == ["can-provider.ini", "slice.dbc", "vss-can-mapping.json", "vss-databroker.json"]
    assert (staged / "vss-databroker.json").read_bytes() == (stack.GEN / "vss-databroker-carla.json").read_bytes()
    assert man["recording"] is None and man["live"]["feeder_out"] == str(ctx.feeder_out) and man["live"]["feed"] == "live"
    writers = [r for r in ctx.rows if r["writer"] == attr.CAN_PROVIDER]
    assert writers and all(r["upstream"] == stack.LIVE_UPSTREAM for r in writers)
    assert (mode == "broker") == bool(man["bridge"]["writes"]) and (man["bridge"]["wheelbase"] is not None) == (mode == "broker")
    assert json.loads((ctx.run_dir / "manifest.json").read_text(encoding="utf-8"))["live"] == man["live"]


def _close_files(rd, mode, profiles="1 2 3"):
    (rd / "bridge").mkdir(parents=True, exist_ok=True)
    (rd / "monitor.log").write_text("monitor: vss rules: kind 4, catalog 0x%08X (vss 6.0), age_max %d ms, profiles %s\n"
                                    % (C.CATALOG_DIGEST, C.AGE_MAX_MS, profiles), encoding="utf-8")
    recs = [{"event": "connect", "digest": "0x%08X" % C.CATALOG_DIGEST, "age_max_ms": C.AGE_MAX_MS, "profile_id": _profile3()[0],
             "mode": mode}]
    if mode == "broker":          # the bridge's own wheelbase record, as the carla catalogue serves profile 3's L
        l_mm = int(_profile3()[1]["l_mm"])
        recs.append({"event": "wheelbase", "path": attr.WHEELBASE, "served": True, "value_mm": l_mm, "l_mm": l_mm})
    (rd / "bridge" / "bridge.jsonl").write_text("".join(json.dumps(x) + "\n" for x in recs), encoding="utf-8")


def _take_dir(path, rtf, completed=True, ended=True, wheelbase=None, blueprint=None, cleanup=None):
    path.mkdir(parents=True, exist_ok=True)
    cleanup = cleanup if cleanup is not None else "ok" if completed else "not run"
    doc = {"format": 1, "name": NAME, "seed": 7, "completed": completed, "cleanup": cleanup,
           "errors": [] if completed else ["RuntimeError: fake"], "rtf": rtf, "steps": 3,
           "blueprint": blueprint or stack.LIVE_SOURCE_VEHICLE, "ego": {"wheelbase_mm": wheelbase or int(_profile3()[1]["l_mm"])}}
    (path / "capture.json").write_text(json.dumps(doc), encoding="utf-8")
    if ended:
        (path / "take.sha256").write_text("x  steps.jsonl\n", encoding="ascii")
    return path


@NEEDS_CONTRACT
def test_the_live_close_fills_source_rtf_from_the_take_s_capture_json_and_c12b_reads_it(tmp_path, monkeypatch):
    ctx, _man = _live_ctx(tmp_path, monkeypatch, "broker")
    rd = tmp_path / "rd"
    _close_files(rd, "broker")
    rtf = {"min": 0.97, "mean": 0.99, "max": 1.0}
    take = _take_dir(tmp_path / "take", rtf)
    h = ctx.run_header(stack.LIVE_REPLAY, "vcan")
    c = stack.live_close(h, rd, take)
    assert c[1], c
    assert h["source_rtf"] == rtf and h["header_check"] == "ok" and "source_rtf" in c[2]
    h2 = ctx.run_header(stack.LIVE_REPLAY, "vcan")
    c2 = stack.live_close(h2, rd, tmp_path / "no-take")
    assert not c2[1] and "source_rtf is not filled" in c2[2] and h2["source_rtf"] is None
    h3 = ctx.run_header(stack.LIVE_REPLAY, "vcan")
    c3 = stack.live_close(h3, rd, _take_dir(tmp_path / "take3", dict(rtf, max=1.5)))
    assert not c3[1] and "max 1.5 > 1" in c3[2]
    h4 = ctx.run_header(stack.LIVE_REPLAY, "vcan")
    _close_files(tmp_path / "rd4", "broker", profiles="1 2")
    c4 = stack.live_close(h4, tmp_path / "rd4", take)
    assert not c4[1] and "do not list the header's profile" in c4[2]


@NEEDS_CONTRACT
def test_live_refuses_a_generation_without_the_carla_layer_before_anything_is_written(tmp_path, monkeypatch):
    man = json.loads((stack.GEN / "manifest.json").read_text(encoding="utf-8"))
    for k in ("vehicle_layers", "databroker_catalogues"):
        man.pop(k)
    ctx, _ = _live_ctx(tmp_path, monkeypatch, "can", prepare=False, man=man)
    with pytest.raises(stack.StackError, match="no carla vehicle layer"):
        ctx.prepare(pull=False, build=False, bridge_parts=False)
    assert not ctx.run_dir.exists()


@NEEDS_CONTRACT
def test_live_refuses_a_generation_that_does_not_compile_the_carla_live_default_profile_before_anything_is_written(tmp_path, monkeypatch):
    ctx, _ = _live_ctx(tmp_path, monkeypatch, "can", prepare=False)
    ctx.contract = tsc.synthetic_contract(compiled=False)
    with pytest.raises(stack.StackError, match="not compiled in this generation"):
        ctx.prepare(pull=False, build=False, bridge_parts=False)
    assert not ctx.run_dir.exists()


@NEEDS_CONTRACT
def test_live_refuses_a_staged_dbc_that_is_not_the_generation_s_own_input(tmp_path, monkeypatch):
    """The feeder encodes with the generation's own slice.dbc input; the bridge and the guest decode with it. C10-dbc holds the
    staged copy to it by sha256."""
    ctx, _ = _live_ctx(tmp_path, monkeypatch, "can", prepare=False)
    other = tmp_path / "other.dbc"
    other.write_bytes(tsc.SLICE_DBC.read_bytes() + b"\n")                  # a DBC that is not the one the generation names
    real = stack.resolve_dbc
    monkeypatch.setattr(stack, "resolve_dbc", lambda sha, *a, **kw: dict(real(sha, *a, **kw), path=str(other)))
    with pytest.raises(stack.StackError, match="C10-dbc"):
        ctx.prepare(pull=False, build=False, bridge_parts=False)


@pytest.mark.parametrize("case", ["a1-metal", "c7g-metal", "orin", "feeder-out-exists", "feeder-out-in-the-repo", "twin-control",
                                  "feeder-out-a-dangling-symlink"])
def test_stack_live_refuses_before_anything_is_written(tmp_path, monkeypatch, case):
    def forbidden(*a, **kw):
        raise AssertionError("a refused run reached docker or a command: %r" % (a[:3],))
    monkeypatch.setattr(stack, "docker", forbidden)            # nothing outside this process, whatever the code does
    monkeypatch.setattr(stack, "run", forbidden)
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    monkeypatch.delenv(stack.HOST_ROLE_ENV, raising=False)
    monkeypatch.delenv(stack.CPUSET_ENV, raising=False)
    monkeypatch.delenv(stack.AFTER_START_ENV, raising=False)
    monkeypatch.setenv(stack.TWIN_CONTROL_ENV, str(tmp_path / "no-marker"))
    out = tmp_path / "takes" / NAME
    if case in ("a1-metal", "c7g-metal", "orin"):
        monkeypatch.setenv(stack.HOST_ROLE_ENV, case)
        why = "the PC"
    elif case == "feeder-out-exists":
        out.mkdir(parents=True)
        why = "exists"
    elif case == "feeder-out-in-the-repo":
        out = REPO / "sdv-out" / "not-made" / NAME
        why = "inside the repository"
    elif case == "feeder-out-a-dangling-symlink":
        out.parent.mkdir(parents=True)
        try:
            os.symlink(tmp_path / "nowhere", out)
        except (OSError, NotImplementedError):
            pytest.skip("symbolic links cannot be made here")
        why = "exists"
    else:
        (tmp_path / "no-marker").write_text("", encoding="ascii")
        why = "twin-control marker"
    with pytest.raises(stack.StackError, match=why):
        stack.main(["live", "--bridge", "can", "--feeder-out", str(out)])
    assert not (tmp_path / "runs").exists() and (case == "feeder-out-exists" or not out.exists())
    assert not (tmp_path / "nowhere").exists()                                       # nothing was made through a symbolic link


def test_stack_live_takes_broker_or_can_only():
    with pytest.raises(SystemExit):
        stack.main(["live", "--bridge", "replay", "--feeder-out", "/nowhere/x"])
    assert stack.LIVE_BRIDGE_MODES == ("broker", "can")


def test_the_usage_lines_of_stack_live_name_every_option_the_subcommand_takes(capsys):
    """A second live run on one day needs --name (new_run_dir refuses the default name twice): the usage line of stack.py's
    docstring and of the feeder's README lists every option the subcommand has."""
    with pytest.raises(SystemExit):
        stack.main(["live", "--help"])
    opts = set(re.findall(r"^\s+(--[a-z-]+)", capsys.readouterr().out, re.M))
    assert opts == {"--name", "--bridge", "--feeder-out", "--native"}
    for where, text in (("stack.py", stack.__doc__), ("sdv/feeder/README.md", (FEEDER_DIR / "README.md").read_text(encoding="utf-8"))):
        line = next(ln for ln in text.splitlines() if "stack.py live" in ln and "--bridge" in ln)
        assert opts <= set(re.findall(r"--[a-z-]+", line)), (where, line)


class _Capture:
    """VcanCapture replaced: two frames with their receive times."""

    def __init__(self):
        self.frames = [(0x100, b"\0" * 8), (0x101, b"\1" * 8)]
        self.times_ns = [REAL_OFFSET_NS + 5 * MS, REAL_OFFSET_NS + 6 * MS]
        self.closed = 0

    def close(self):
        self.closed += 1
        return self.frames


def _live_fakes(monkeypatch, events, mode, late_reply=False):
    """Every outside call of live_once replaced; the bridge's records written at `up`: one ACCEPT, and with late_reply a 22
    an hour from now (after the take's end, whenever the stack sees it)."""
    def fake_up(ctx, feed, rd, label, header=None):
        events.append(("up", feed, header["feed"], header["bridge_mode"]))
        rd.mkdir(parents=True, exist_ok=True)
        _close_files(rd, mode)
        rep = [{"event": "reply", "seq": 1, "verdict": 1, "reason": 0, "src_now_ns": REAL_OFFSET_NS + 10 * MS}]
        if late_reply:
            rep.append({"event": "reply", "seq": 2, "verdict": 2, "reason": 22, "src_now_ns": time.time_ns() + 3600 * 10 ** 9})
        (rd / "bridge" / "replies.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rep), encoding="utf-8")
        (rd / "bridge" / "summary.json").write_text(json.dumps({"counters": {}, "identity": {"holds": True},
                                                                "ticks_identity": {"holds": True}, "fatal": None}), encoding="utf-8")
        return {"feed": feed, "listeners_before": {}, "listeners": {"ok": True}}

    def fake_start(ctx, comp, feed, rd, label):
        events.append(("start", comp, feed))
        return stack.CONTAINERS[comp]

    def fake_run(cmd, check=True, timeout=None, input_text=None):
        events.append(("run", list(cmd)))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def listeners_now(info, feed, suffix, allowed=()):
        info["listeners" + suffix] = {"ok": True}
    cap = _Capture()
    for name, fn in (("up", fake_up), ("start", fake_start), ("run", fake_run), ("listeners_now", listeners_now),
                     ("wait_log", lambda *a, **kw: None), ("stop_containers", lambda ctx: events.append(("stop",))),
                     ("collect", lambda rd: {attr.BRIDGE: "exited 0"}), ("remove_stack", lambda: events.append(("remove",))),
                     ("docker", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", "")), ("VcanCapture", lambda: cap)):
        monkeypatch.setattr(stack, name, fn)
    for name in ("VCAN_READY_S", "LIVE_SETTLE_S"):
        monkeypatch.setattr(stack, name, 0.0)
    monkeypatch.setattr(stack, "LIVE_POLL_S", 0.001)
    monkeypatch.setattr(attr, "run_rows", lambda rows, ids: [])
    monkeypatch.setattr(attr, "check_images", lambda rows, running: ("C8", True, "synthetic"))
    return cap


@NEEDS_CONTRACT
@pytest.mark.parametrize("mode", ["broker", "can"])
def test_live_once_starts_the_stack_on_the_vcan_feed_plays_no_recording_waits_for_the_take_and_closes(tmp_path, monkeypatch, mode):
    ctx, _man = _live_ctx(tmp_path, monkeypatch, mode)
    events = []
    cap = _live_fakes(monkeypatch, events, mode)
    rtf = {"min": 0.98, "mean": 0.99, "max": 1.0}
    _take_dir(ctx.feeder_out, rtf)
    stack.live_once(ctx)
    assert ("up", "vcan", "live", mode) in events and ("start", attr.CAN_PROVIDER, "vcan") in events
    assert not [e for e in events if e[0] == "run" and any("player" in str(w) or str(w).endswith(".log") for w in e[1])]
    assert cap.closed >= 1 and events[-1] == ("remove",)
    rd = ctx.run_dir / stack.LIVE_REPLAY
    on_disk = json.loads((rd / "result.json").read_text(encoding="utf-8"))
    gates = stack.live_gates(on_disk)
    assert all(gates.values()) and set(gates) == set(GATES_OK), gates
    table = json.loads((rd / "attribution.json").read_text(encoding="utf-8"))
    assert table["header"]["source_rtf"] == rtf and table["header"]["header_check"] == "ok" and table["header"]["feed"] == "live"
    capd = json.loads((rd / stack.LIVE_CAPTURE).read_text(encoding="utf-8"))
    assert capd["frames"] == [[REAL_OFFSET_NS + 5 * MS, 0x100, "00" * 8], [REAL_OFFSET_NS + 6 * MS, 0x101, "01" * 8]]
    assert on_disk["feeder_out"] == str(ctx.feeder_out) and on_disk["bridge_mode"] == mode and on_disk["take"]["completed"] is True


@NEEDS_CONTRACT
def test_live_once_gives_up_on_a_take_that_never_ends_and_still_closes_the_run(tmp_path, monkeypatch):
    ctx, _man = _live_ctx(tmp_path, monkeypatch, "can")
    events = []
    _live_fakes(monkeypatch, events, "can")
    monkeypatch.setattr(stack, "LIVE_TAKE_WAIT_S", 0.01)
    ctx.feeder_out.mkdir(parents=True)               # a take that started and never wrote its capture.json
    r = stack.live_once(ctx)
    gates = stack.live_gates(r)
    assert r["take"]["timed_out"] is True and gates["take_completed"] is False and events[-1] == ("remove",)
    assert gates["c12b"] is False and "source_rtf is not filled" in r["c12b"][2]
    assert (ctx.run_dir / stack.LIVE_REPLAY / "result.json").is_file()
    half = _take_dir(tmp_path / "t1", {"min": 0.9, "mean": 0.95, "max": 1.0}, completed=True, ended=False)
    assert stack.wait_for_take(half, 0.01)["completed"] is True             # capture.json reads completed: the wait ends there
    failed = _take_dir(tmp_path / "t3", {"min": 0.9, "mean": 0.95, "max": 1.0}, completed=False, ended=True)
    t0 = time.monotonic()
    st = stack.wait_for_take(failed, 5.0)                                     # a take that ended without completing: no wait
    assert (st["timed_out"], st["completed"], st["ended"]) == (False, False, True) and time.monotonic() - t0 < 4
    take2 = _take_dir(tmp_path / "t2", {"min": 0.9, "mean": 0.95, "max": 1.0}, wheelbase=1234)
    want = {"name": stack.LIVE_SOURCE_VEHICLE, "wheelbase_mm": int(_profile3()[1]["l_mm"])}
    assert stack.take_state(take2, want)["vehicle_agrees"] is False and stack.take_state(take2)["vehicle_agrees"] is None


@NEEDS_CONTRACT
def test_the_wait_ends_once_the_take_reads_completed_and_its_cleanup_had_its_settle_time(tmp_path, monkeypatch):
    """spec-2 2.4: the stack waits for capture.json to read completed, not for the timeout. A completed take that has not
    ended (take.sha256, written after the cleanup) is waited for LIVE_SETTLE_S more and then taken as it is."""
    monkeypatch.setattr(stack, "LIVE_SETTLE_S", 0.01)
    monkeypatch.setattr(stack, "LIVE_POLL_S", 0.001)
    half = _take_dir(tmp_path / "half", {"min": 0.9, "mean": 0.95, "max": 1.0}, completed=True, ended=False)
    t0 = time.monotonic()
    st = stack.wait_for_take(half, 30.0)
    assert (st["timed_out"], st["completed"], st["ended"]) == (False, True, False) and time.monotonic() - t0 < 5


@NEEDS_CONTRACT
def test_take_state_reads_a_capture_json_again_while_the_take_rewrites_it_and_gives_up_after_live_torn_reads(tmp_path, monkeypatch):
    take = _take_dir(tmp_path / "take", {"min": 0.9, "mean": 0.95, "max": 1.0})
    real_read_text = Path.read_text
    reads = []

    def torn(torn_reads):
        def read_text(self, *a, **kw):
            if self.name == "capture.json":
                reads.append(1)
                if len(reads) <= torn_reads:
                    return '{"format": 1, "completed": tr'                      # half of the file the take is rewriting
            return real_read_text(self, *a, **kw)
        return read_text
    with monkeypatch.context() as m:
        m.setattr(stack, "LIVE_POLL_S", 0.001)
        m.setattr(Path, "read_text", torn(1))
        st = stack.take_state(take)
        assert (st["capture"], st["completed"], len(reads)) == (True, True, 2)       # torn once, read again
        reads.clear()
        m.setattr(Path, "read_text", torn(10 ** 6))
        st = stack.take_state(take)
        assert (st["capture"], st["completed"], len(reads)) == (False, False, stack.LIVE_TORN_READS)


@NEEDS_CONTRACT
def test_take_state_agrees_with_the_declared_vehicle_only_when_the_blueprint_and_the_wheelbase_are_both_its(tmp_path):
    want = {"name": stack.LIVE_SOURCE_VEHICLE, "wheelbase_mm": int(_profile3()[1]["l_mm"])}
    rtf = {"min": 0.9, "mean": 0.95, "max": 1.0}
    assert stack.take_state(_take_dir(tmp_path / "a", rtf), want)["vehicle_agrees"] is True
    assert stack.take_state(_take_dir(tmp_path / "b", rtf, blueprint="vehicle.other"), want)["vehicle_agrees"] is False
    assert stack.take_state(_take_dir(tmp_path / "c", rtf, wheelbase=1234), want)["vehicle_agrees"] is False


def test_the_live_constants_are_held_to_their_sources():
    assert stack.LIVE_SOURCE_VEHICLE == live.capture.BLUEPRINT == tsc.encode.BLUEPRINT
    assert stack.LIVE_TAKE_WAIT_S > tsc.drive.DRIVE.max_take_s
    assert stack.LIVE_RUN_TYPE in attr.CARLA_RUN_TYPES and live.CHANNEL == stack.VCAN
    assert (f2check.LIVE_REPLAY, f2check.CAPTURE) == (stack.LIVE_REPLAY, stack.LIVE_CAPTURE)


@NEEDS_CONTRACT
def test_live_once_splits_the_bridge_s_replies_at_the_take_s_end_as_the_stack_saw_it(tmp_path, monkeypatch):
    """bridge_result splits the replies at the end of what fed the bridge: in a live run the take's end as the wait saw it
    (a replay's player end), so a 22 after the take ended is counted after it, not while playing."""
    ctx, _man = _live_ctx(tmp_path, monkeypatch, "broker")
    _live_fakes(monkeypatch, [], "broker", late_reply=True)
    _take_dir(ctx.feeder_out, {"min": 0.98, "mean": 0.99, "max": 1.0})
    r = stack.live_once(ctx)
    assert r["bridge"]["clock"]["player_end_realtime_ns"] == r["take"]["seen_end_realtime_ns"] is not None
    assert r["bridge"]["replies"] == {"while_playing": {"ACCEPT": 1}, "after_player_end": {"REJECT 22": 1}}
    assert r["bridge"]["ok"] is True


def _gates_result(**take):
    t = {"completed": True, "timed_out": False, "vehicle_agrees": True, "cleanup": "ok", "errors": []}
    t.update(take)
    return {"c12a": ["C12a", True, ""], "c8": ["C8", True, ""], "listeners": {"ok": True}, "listeners_feed": {"ok": True},
            "listeners_end": {"ok": True}, "c12b": ["C12b", True, ""], "bridge": {"ok": True}, "take": t}


def test_the_live_gates_want_the_take_completed_within_the_wait_and_cleaned_up():
    """A take whose loop completed but whose cleanup failed exits 1 itself (carla_capture.take) and encode.check_take refuses
    it; the live run's gates say so too (take_clean), and a take that completed only after the wait gave up is not one the
    run waited for (take_completed)."""
    def failing(**take):
        return [k for k, v in stack.live_gates(_gates_result(**take)).items() if not v]
    assert failing() == [] and set(stack.live_gates(_gates_result())) == set(GATES_OK)
    assert failing(timed_out=True) == ["take_completed"]
    assert failing(timed_out=None) == ["take_completed"]
    assert failing(cleanup="RuntimeError: fake: the actor would not go") == ["take_clean"]
    assert failing(errors=["RuntimeError: fake"]) == ["take_clean"]
    assert failing(cleanup=None) == ["take_clean"]


@NEEDS_CONTRACT
def test_live_once_fails_its_take_clean_gate_on_a_take_whose_cleanup_failed(tmp_path, monkeypatch):
    ctx, _man = _live_ctx(tmp_path, monkeypatch, "can")
    _live_fakes(monkeypatch, [], "can")
    _take_dir(ctx.feeder_out, {"min": 0.98, "mean": 0.99, "max": 1.0}, cleanup="RuntimeError: fake: the actor would not go")
    r = stack.live_once(ctx)
    assert [k for k, v in r["gates"].items() if not v] == ["take_clean"] and r["take"]["completed"] is True


TIMEOUT_TEXT = ("time-out of 120000ms while waiting for the simulator, make sure the simulator is ready and connected to "
                "%s:2000")       # the shape of LibCarla's client TimeoutException: it names the endpoint it was connected to


@NEEDS_CONTRACT
def test_a_server_error_naming_the_gateway_reaches_no_file_of_the_take_or_of_the_stack_s_records(tmp_path, monkeypatch, capsys):
    """A server that stalls makes LibCarla raise with the endpoint in its text, at a tick and again in the take's cleanup; the
    take records both texts in capture.json and the stack copies them into its result. Every file the take, live.py and the
    stack write holds the gateway masked (spec-2 2.4: never written to any file), and nothing prints it."""
    fail_at = tsc.capture.SETTLE_TICKS + 12
    real_tick = fake.Sim.tick

    def tick(self):
        if self.ticks + 1 == fail_at:
            self.ticks += 1
            raise RuntimeError(TIMEOUT_TEXT % GATEWAY)
        return real_tick(self)

    def destroy(self):
        raise RuntimeError(TIMEOUT_TEXT % GATEWAY)
    monkeypatch.setattr(fake.Sim, "tick", tick)
    monkeypatch.setattr(fake.Actor, "destroy", destroy)
    ctx, _man = _live_ctx(tmp_path, monkeypatch, "can")
    r = run_live(tmp_path, out=ctx.feeder_out)
    assert r.rc == 1
    _live_fakes(monkeypatch, [], "can")
    res = stack.live_once(ctx)
    written = [p for root in (ctx.feeder_out, ctx.run_dir) for p in sorted(root.rglob("*")) if p.is_file()]
    assert ctx.feeder_out / "capture.json" in written and ctx.run_dir / stack.LIVE_REPLAY / "result.json" in written
    for p in written:
        assert GATEWAY not in p.read_text(encoding="utf-8", errors="replace"), p
    cap = tsc.read_capture(ctx.feeder_out)
    masked = TIMEOUT_TEXT % live.HOST_MASK
    assert cap["completed"] is False and any(masked in e for e in cap["errors"]) and masked in cap["cleanup"]
    assert any(masked in e for e in res["take"]["errors"]) and res["gates"]["take_completed"] is False
    out = capsys.readouterr()
    assert GATEWAY not in out.out + out.err


# =================================================================================================================
# f2check.py: F2's verdict over a live run's records
# =================================================================================================================

FREEZE_START = REAL_OFFSET_NS + 10_000 * MS
LAST_FRAME = FREEZE_START + 60 * MS


def _bound_ms():
    return C.AGE_MAX_MS + live.TICK_MS


FREEZE_END = FREEZE_START + int(live.FREEZE_S * 1e9)
DONE_LINE = "monitor: client done: seen=200 accepted=150 rejected=50\n"            # monitor.c's line at a session's end
MISS_LINE = "monitor: LIVENESS MISS: no claim for 512 ms since seq=200 (deadline 500 ms, miss 1)\n"
GATES_OK = {"c12a": True, "c8": True, "listeners": True, "take_completed": True, "take_clean": True, "take_vehicle": True,
            "c12b": True, "bridge": True}


def _f2_records(delay_ms=None, miss=0, reject_before=False, no22=False, tail="", stop_ms=None, take_rc=0, only_after_start=False,
                reject_at_start=False, at_last_frame_22=False):
    """Synthetic records: ACCEPT every 100 ms up to the freeze, the last frame 60 ms into it, ACCEPT until the first 22
    (delay_ms after the last frame; default 30 ms inside the bound), then 22 until 500 ms after the freeze's end (or until
    stop_ms after the freeze's start: a bridge stopped then), each with the age it would pack (from the last frame). The
    console: the monitor's banner, miss MISS lines, then tail (a session's end, a MISS, ...). only_after_start: no reply
    before the freeze's start (the one at the start itself stays); reject_at_start: the reply at the freeze's very start is a
    REJECT; at_last_frame_22: one more reply, a 22, at the last frame's own time."""
    delay = _bound_ms() - 30 if delay_ms is None else delay_ms
    replies, seq = [], 0
    t = REAL_OFFSET_NS
    first22 = LAST_FRAME + delay * MS
    end = FREEZE_END + 500 * MS if stop_ms is None else FREEZE_START + stop_ms * MS

    def age(at):
        return max(0, (at - LAST_FRAME) // MS) if at > LAST_FRAME else 20
    while t < end:
        seq += 1
        reason = 0 if (no22 or t < first22) else 22
        replies.append({"event": "reply", "seq": seq, "verdict": 1 if reason == 0 else 2, "reason": reason, "src_now_ns": t,
                        "age_ms": age(t)})
        t += 100 * MS
    if not no22:
        seq += 1
        replies.append({"event": "reply", "seq": seq, "verdict": 2, "reason": 22, "src_now_ns": first22, "age_ms": age(first22)})
        replies.sort(key=lambda x: x["src_now_ns"])
    if reject_before:
        replies[3] = dict(replies[3], verdict=2, reason=24)
    if only_after_start:
        replies = [r for r in replies if r["src_now_ns"] >= FREEZE_START]
    if reject_at_start:
        assert sum(1 for r in replies if r["src_now_ns"] == FREEZE_START) == 1        # the premise: one reply on the very instant
        replies = [dict(r, verdict=2, reason=24) if r["src_now_ns"] == FREEZE_START else r for r in replies]
    if at_last_frame_22:
        replies.append({"event": "reply", "seq": seq + 1000, "verdict": 2, "reason": 22, "src_now_ns": LAST_FRAME, "age_ms": 20})
        replies.sort(key=lambda x: x["src_now_ns"])
    frames = [[REAL_OFFSET_NS + k * 20 * MS, 0x100, "00" * 8] for k in range(int((LAST_FRAME - REAL_OFFSET_NS) // (20 * MS)))]
    frames.append([LAST_FRAME, 0x101, "01" * 8])
    console = "monitor: service monitor listening on :7160 \n" + "monitor: LIVENESS MISS: seq=9 after 500 ms\n" * miss + tail
    doc = {"freeze": {"freeze_s": live.FREEZE_S, "start_real_ns": FREEZE_START, "end_real_ns": FREEZE_END, "at_s": 9.0},
           "sends": [[0, 0, 0, 0, REAL_OFFSET_NS]], "take_rc": take_rc, "send_errors": []}
    return replies, frames, console, doc


@NEEDS_CONTRACT
@pytest.mark.parametrize("mode", ["can", "broker"])
@pytest.mark.parametrize("case, ok, failing", [
    ("ok", True, []),
    ("at-the-bound", True, []),
    ("late-22", False, ["first_22_within_bound"]),
    ("no-22", False, ["first_22_found", "first_22_within_bound"]),
    ("a-miss", False, ["no_miss"]),
    ("reject-before-the-freeze", False, ["every_frame_before_the_freeze_accepted"]),
    ("a-miss-after-the-last-session", True, []),
    ("a-miss-between-two-sessions", False, ["no_miss"]),
    ("the-bridge-stopped-in-the-freeze", False, ["bridge_answered_after_the_freeze"]),
    ("the-feeder-failed", False, ["feeder_ok"]),
    ("no-reply-before-the-freeze", False, ["every_frame_before_the_freeze_accepted"]),
    ("a-reject-exactly-at-the-freeze-start", True, []),
    ("a-22-exactly-at-the-last-frame", False, ["first_22_found", "first_22_within_bound"]),
])
def test_f2check_on_synthetic_run_records(case, ok, failing, mode):
    """The console's MISS lines count until the bridge's last session ended (its last `client done:`): the native monitor
    outlives the bridge at the run's end (stack.py live stops the bridge, then the other containers, then the monitor) and
    reports that silence, as step3.console_view reads the same monitor; a MISS between two sessions counts. That rule is safe
    only for a last session that lasted past the freeze, which the bridge's last reply shows."""
    kw = {"at-the-bound": {"delay_ms": _bound_ms()}, "late-22": {"delay_ms": _bound_ms() + 1}, "no-22": {"no22": True},
          "a-miss": {"miss": 1}, "reject-before-the-freeze": {"reject_before": True},
          "a-miss-after-the-last-session": {"tail": DONE_LINE + MISS_LINE},
          "a-miss-between-two-sessions": {"tail": DONE_LINE + MISS_LINE + DONE_LINE + MISS_LINE},
          "the-bridge-stopped-in-the-freeze": {"tail": DONE_LINE + MISS_LINE, "stop_ms": 1000},
          "the-feeder-failed": {"take_rc": 1}, "no-reply-before-the-freeze": {"only_after_start": True},
          "a-reject-exactly-at-the-freeze-start": {"reject_at_start": True},
          "a-22-exactly-at-the-last-frame": {"no22": True, "at_last_frame_22": True}}.get(case, {})
    replies, frames, console, doc = _f2_records(**kw)
    v = f2check.verdict(mode, replies, frames, console, doc, C.AGE_MAX_MS, live.TICK_MS, live.FREEZE_S)
    assert v["ok"] is ok and sorted(k for k, x in v["checks"].items() if not x) == sorted(failing), v["checks"]
    assert v["bound_ms"] == _bound_ms() and v["last_frame"]["t_ns"] == LAST_FRAME
    if case in ("ok", "at-the-bound", "late-22"):
        assert v["first_22"]["delay_ms"] == pytest.approx(kw.get("delay_ms", _bound_ms() - 30))


@NEEDS_CONTRACT
def test_f2check_without_a_freeze_or_with_another_freeze_s_does_not_pass():
    replies, frames, console, doc = _f2_records()
    v = f2check.verdict("can", replies, frames, console, dict(doc, freeze=None), C.AGE_MAX_MS, live.TICK_MS, live.FREEZE_S)
    assert v["ok"] is False and v["checks"]["froze"] is False
    other = dict(doc, freeze=dict(doc["freeze"], freeze_s=live.FREEZE_S / 2))
    assert f2check.verdict("can", replies, frames, console, other, C.AGE_MAX_MS, live.TICK_MS, live.FREEZE_S)["checks"]["froze"] is False


@NEEDS_CONTRACT
def test_f2check_names_its_age_source_per_mode_and_in_broker_mode_a_lower_bound():
    replies, frames, console, doc = _f2_records()
    can = f2check.verdict("can", replies, frames, console, doc, C.AGE_MAX_MS, live.TICK_MS, live.FREEZE_S)
    broker = f2check.verdict("broker", replies, frames, console, doc, C.AGE_MAX_MS, live.TICK_MS, live.FREEZE_S)
    assert "SocketCAN receive time" in can["age_source"] and "lower bound" not in can["age_source"]
    assert "datapoint timestamp" in broker["age_source"] and "lower bound" in broker["age_source"]
    assert can["checks"] == broker["checks"]


def _f2_run(tmp_path, mode="can", gates=GATES_OK, **kw):
    """A live run's records and its take's live.json under tmp_path; gates: result.json's (None: none written)."""
    replies, frames, console, doc = _f2_records(**kw)
    run = tmp_path / "runs" / "20261020-live"
    rd = run / stack.LIVE_REPLAY
    (rd / "bridge").mkdir(parents=True)
    take = tmp_path / "takes" / NAME
    take.mkdir(parents=True)
    (take / "live.json").write_text(json.dumps(doc), encoding="utf-8")
    (rd / "bridge" / "replies.jsonl").write_text("".join(json.dumps(x) + "\n" for x in replies), encoding="utf-8")
    (rd / stack.LIVE_CAPTURE).write_text(json.dumps({"frames": frames}), encoding="utf-8")
    (rd / "monitor.log").write_text(console, encoding="utf-8")
    result = {"bridge_mode": mode, "feeder_out": str(take)}
    if gates is not None:
        result["gates"] = dict(gates)
    (rd / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (rd / "attribution.json").write_text(json.dumps({"header": {"age_max_ms": C.AGE_MAX_MS, "bridge_mode": mode}}), encoding="utf-8")
    return run, take


@NEEDS_CONTRACT
def test_f2check_main_writes_f2_json_beside_the_run_and_exits_0_only_when_ok(tmp_path):
    run, _take = _f2_run(tmp_path)
    assert f2check.main([str(run)]) == 0
    v = json.loads((run / "f2.json").read_text(encoding="utf-8"))
    assert v["ok"] is True and v["mode"] == "can" and v["run"] == run.name
    assert f2check.main([str(run)]) == 2, "an existing f2.json is never rewritten"
    run2, _t = _f2_run(tmp_path / "late", delay_ms=_bound_ms() + 1)
    assert f2check.main([str(run2)]) == 1 and json.loads((run2 / "f2.json").read_text(encoding="utf-8"))["ok"] is False


@NEEDS_CONTRACT
def test_f2check_main_refuses_a_run_it_cannot_read_or_whose_age_max_is_not_the_contract_s(tmp_path):
    run, take = _f2_run(tmp_path)
    (take / "live.json").unlink()
    assert f2check.main([str(run)]) == 2 and not (run / "f2.json").exists()
    run2, _t = _f2_run(tmp_path / "b")
    hdr = run2 / stack.LIVE_REPLAY / "attribution.json"
    hdr.write_text(json.dumps({"header": {"age_max_ms": C.AGE_MAX_MS + 1}}), encoding="utf-8")
    assert f2check.main([str(run2)]) == 2 and not (run2 / "f2.json").exists()
    assert f2check.main([str(tmp_path / "nothing")]) == 2


@NEEDS_CONTRACT
def test_f2check_main_refuses_a_run_of_another_bridge_mode_naming_it_and_a_reply_it_cannot_read(tmp_path, capsys):
    """Only broker and can runs are judged (a replay has no live feeder); a reply record with no src_now_ns is a record
    f2check cannot judge: refused (exit 2, no f2.json), not an uncaught KeyError."""
    run, _t = _f2_run(tmp_path, mode="replay")
    assert f2check.main([str(run)]) == 2 and not (run / "f2.json").exists()
    assert "the run's bridge mode 'replay' is not one of broker, can" in capsys.readouterr().err
    run2, _t = _f2_run(tmp_path / "b")
    replies = run2 / stack.LIVE_REPLAY / "bridge" / "replies.jsonl"
    replies.write_text(replies.read_text(encoding="utf-8") + json.dumps({"event": "reply", "seq": 9999, "verdict": 2, "reason": 22}) + "\n",
                       encoding="utf-8")
    assert f2check.main([str(run2)]) == 2 and not (run2 / "f2.json").exists()
    assert "refused" in capsys.readouterr().err


@NEEDS_CONTRACT
def test_f2check_main_counts_a_miss_only_until_the_bridge_s_last_session_ended(tmp_path):
    """The native monitor's console of every live run ends with the bridge's `client done:` and then one MISS: the monitor
    outlives the bridge (stack.py live stops it last). That MISS is not the run's; one before the session's end is."""
    run, _t = _f2_run(tmp_path, tail=DONE_LINE + MISS_LINE)
    assert f2check.main([str(run)]) == 0
    v = json.loads((run / "f2.json").read_text(encoding="utf-8"))
    assert (v["ok"], v["miss"], v["miss_after_last_session"], v["sessions"]) == (True, 0, 1, 1)
    run2, _t = _f2_run(tmp_path / "b", tail=MISS_LINE + DONE_LINE + MISS_LINE)
    assert f2check.main([str(run2)]) == 1
    v2 = json.loads((run2 / "f2.json").read_text(encoding="utf-8"))
    assert (v2["ok"], v2["miss"], v2["miss_after_last_session"]) == (False, 1, 1) and v2["checks"]["no_miss"] is False


def test_f2check_reads_a_session_s_end_and_a_miss_as_step3_reads_the_same_monitor():
    import step3
    assert (f2check.DONE, f2check.MISS) == (step3.DONE, step3.MISS)
    assert DONE_LINE.startswith(step3.DONE) and MISS_LINE.startswith(step3.MISS)


@NEEDS_CONTRACT
def test_f2check_main_requires_the_run_s_own_gates_and_names_them_in_f2_json(tmp_path):
    """f2.json ok says the run passed: a run whose own gates failed (a listener beyond loopback, a take that did not clean up,
    the bridge's result) is not ok, and the gate is named; a result.json with no gates is no live run's and is refused."""
    bad = dict(GATES_OK, listeners=False)
    run, _t = _f2_run(tmp_path, gates=bad)
    assert f2check.main([str(run)]) == 1
    v = json.loads((run / "f2.json").read_text(encoding="utf-8"))
    assert v["ok"] is False and v["run_gates"] == bad and [k for k, x in v["checks"].items() if not x] == ["run_gates"]
    run2, _t = _f2_run(tmp_path / "b", gates=None)
    assert f2check.main([str(run2)]) == 2 and not (run2 / "f2.json").exists()
    run3, _t = _f2_run(tmp_path / "c", gates={})
    assert f2check.main([str(run3)]) == 1, "no gate at all is no pass"


@NEEDS_CONTRACT
def test_f2check_main_records_the_feeder_s_exit_and_fails_a_take_that_did_not_end_clean(tmp_path):
    run, _t = _f2_run(tmp_path, take_rc=1)
    assert f2check.main([str(run)]) == 1
    v = json.loads((run / "f2.json").read_text(encoding="utf-8"))
    assert v["feeder"] == {"take_rc": 1, "send_errors": 0} and [k for k, x in v["checks"].items() if not x] == ["feeder_ok"]


@NEEDS_CONTRACT
@pytest.mark.parametrize("mode", ["can", "broker"])
def test_f2check_records_the_bridge_s_own_age_at_the_first_22_and_the_age_source_time_it_implies(mode):
    """The first 22's own age (the bridge's age_ms: from the oldest slot's datapoint timestamp in broker mode, its receive
    time in can mode, truncated to ms) gives that slot's age-source time within 1 ms: information beside the verdict, which
    stands on the last frame's receive time."""
    replies, frames, console, doc = _f2_records()
    v = f2check.verdict(mode, replies, frames, console, doc, C.AGE_MAX_MS, live.TICK_MS, live.FREEZE_S)
    f = v["first_22"]
    assert f["age_ms"] == (f["src_now_ns"] - LAST_FRAME) // MS > C.AGE_MAX_MS
    assert f["oldest_slot_age_source_ns"] == f["src_now_ns"] - f["age_ms"] * MS == LAST_FRAME
    assert ("datapoint timestamp" in v["oldest_slot_age_source"]) == (mode == "broker")
    no_age = [dict(r) for r in replies]
    for r in no_age:
        r.pop("age_ms")
    g = f2check.verdict(mode, no_age, frames, console, doc, C.AGE_MAX_MS, live.TICK_MS, live.FREEZE_S)["first_22"]
    assert g["age_ms"] is None and g["oldest_slot_age_source_ns"] is None
