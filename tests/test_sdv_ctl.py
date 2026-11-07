"""Phase 8 WP2 (the Phase 8 specification, section 4): the claim side of kind 2, sdv/ctl, tested without ROS.

sdv/ctl/ctlframe.py packs and decodes the kind 2 frame and loads the kind 2 contract; ctlrules.py is the reference
judge of the specification's 2.3 (CI only); ctlclient.py is the connection core, with 2.1's design values and the
claim bridge's connection rules applied to kind 2; ctl_claim_node.py is the rclpy shim; ctlreplay.py replays a 2.7
export through the same core; ctl_export.py writes that export from a bag. What is tested, and how:

- The codec and the loader, standard library only, against the fixture contract tests/fixtures/ctl-py/vss_ctl.py and
  its bad-digest twin: every layout fault of 2.2 refused, every non-finite value refused by encode and packed bit for
  bit by pack_bits, the interval truncated to ms, saturated and 0 for the first.
- The reference judge at every rule's edge (each limit at and one binary32 step above, rule 17 in double with
  rules.vss_tan, 18 and 19 at their thresholds and skipped with b3 clear), each adjacent pair of 2.3's order, and the
  reason each injection mode is meant to give.
- The core with every instant passed in: the seq from 1, the flags and the odometry freshness window, the 1-deep
  queue, the intake pause, profile 2's window, the refusals (a stamp target above all), the reply log's header and
  records, and 2.6's message from its one pure function.
- The connection rules against a Python peer on loopback that records each connection (accepted, the frames read, how
  it ended): no connect before the first Control, the lazy reconnect after an idle close, the peer-closed check before
  a send, one request outstanding, a frame in flight at a close, the reply timeout, the backoff (a port nothing
  listens on), the connect timeout (a full accept queue), an invalid reply and stray bytes, the stop's drain, and the
  client on its own thread. Every run that ends is held to controls = packed = replied + drop + lost_on_reconnect.
- The node with stand-ins for rclpy and the message packages in sys.modules (what it subscribes to and publishes),
  its import graph (no KUKSA client, no gRPC, nothing of sdv/frame, no ctlrules), the replay against the fixture export
  (tests/fixtures/ctl-py/export.jsonl), the export's pure conversions (tests/fixtures/ctl-py/messages.json), its path
  refusals before rosbag2_py is imported, its main against a stand-in rosbag2_py, and the README's facts.

What this does NOT show: that the monitor judges kind 2 as ctlrules does (the integration stage's contract test, with
WP1a's native build); anything about ROS, rclpy, Autoware's messages or a real bag beyond the stand-ins; any timing
(the waits below only bound when an event may come on a loaded host).

The tests of ctlrules need the kind 4 generated contract (sdv-out/gen) for M_PER_MM; they skip without it, and fail
instead under SDV_REQUIRE_GEN=1 (tests/twin_gate.py).
"""
import ast
import errno
import hashlib
import importlib
import json
import math
import select
import socket
import struct
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import twin_gate

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CTL_DIR = REPO / "sdv" / "ctl"
FIX = HERE / "fixtures" / "ctl-py"
CONTRACT_FILE = FIX / "vss_ctl.py"
BAD_DIGEST_FILE = FIX / "vss_ctl_bad_digest.py"
EXPORT_FILE = FIX / "export.jsonl"
MESSAGES_FILE = FIX / "messages.json"

MS = 1_000_000
H = 16
T0 = 10 ** 12
NAN_BITS = 0x7FC00000
CONTROL_TOPIC = "/control/command/control_cmd"
ODOM_TOPIC = "/localization/kinematic_state"
VERDICT_TOPIC = "/qnx_monitor/verdict"
MESSAGE_KEYS = ["v", "seq", "profile", "v_cmd", "acc", "jerk", "steer", "steer_rate", "interval_ms", "verdict", "reason",
                "packed", "replied", "accepted", "rejected", "dropped", "lost_on_reconnect", "reconnects", "connected"]
EXPECTED_SLOT_PATHS = ("Vehicle.DualVm.ControlCommand.Velocity", "Vehicle.DualVm.ControlCommand.Acceleration",
                       "Vehicle.DualVm.ControlCommand.Jerk", "Vehicle.DualVm.ControlCommand.SteeringTireAngle",
                       "Vehicle.DualVm.ControlCommand.SteeringTireRotationRate", "Vehicle.DualVm.Motion.LongitudinalVelocity",
                       "Vehicle.DualVm.ControlCommand.StampInterval")
INJECTION_REASONS = {"nan": 9, "undef": 10, "reserved": 10, "profile0": 8, "kind9": 5, "interval": 11, "speed": 12, "accel": 13,
                     "jerk": 14, "steer": 15, "steer-rate": 16, "lat-accel": 17, "overspeed": 18, "rolling-back": 19}
SPEC_ORDER = (10, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19)
SPEC_NAMES = {8: "profile-unbound", 9: "field-not-finite", 10: "flags-invalid", 11: "ctl-interval", 12: "ctl-speed",
              13: "ctl-accel", 14: "ctl-jerk", 15: "ctl-steer", 16: "ctl-steer-rate", 17: "ctl-lat-accel",
              18: "ctl-overspeed", 19: "ctl-rolling-back"}
SLACK_S = 5.0          # how long a wait may run on a loaded host before the test gives up


# ============================================================ loading the package

def _import(name):
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        if str(CTL_DIR) not in sys.path:
            sys.path.insert(0, str(CTL_DIR))
        return importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved


@pytest.fixture(scope="module")
def cf():
    return _import("ctlframe")


@pytest.fixture(scope="module")
def cc():
    return _import("ctlclient")


@pytest.fixture(scope="module")
def cr():
    return _import("ctlrules")


@pytest.fixture(scope="module")
def node():
    return _import("ctl_claim_node")


@pytest.fixture(scope="module")
def rp():
    return _import("ctlreplay")


@pytest.fixture(scope="module")
def ex():
    return _import("ctl_export")


@pytest.fixture(scope="module")
def K(cf):
    return cf.load_contract(CONTRACT_FILE)


@pytest.fixture(scope="module")
def mpm(cr):
    """The kind 4 contract's M_PER_MM, which rule 17 multiplies L by (it reaches the C monitor as VSS_M_PER_MM)."""
    try:
        return cr.default_m_per_mm()
    except Exception as err:  # noqa: BLE001 -- the gate decides between skip and fail
        twin_gate.missing("the kind 4 generated contract for M_PER_MM (%s)" % err)


# ============================================================ helpers

class Bits(int):
    """A slot given as its exact binary32 bits, not as a value."""


class Clock:
    """A clock the test moves by hand, in ns."""

    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, ms=0, ns=0):
        self.t += ms * MS + ns


def up(cf, x):
    return cf.f32_next_up(x)


def strict_json(s):
    def refuse(const):
        raise ValueError("not JSON: %s" % const)
    return json.loads(s, parse_constant=refuse)


def ctl(cc, stamp_ms=0, recv_ns=None, v=2.0, a=None, j=None, d=0.1, r=None):
    """A Control as the node hands it over: None for a field leaves its is_defined flag clear."""
    return cc.Control(stamp_ns=T0 + int(stamp_ms * MS), recv_ns=T0 if recv_ns is None else recv_ns, velocity=v,
                      acceleration=0.0 if a is None else a, is_defined_acceleration=a is not None,
                      jerk=0.0 if j is None else j, is_defined_jerk=j is not None, steering_tire_angle=d,
                      steering_tire_rotation_rate=0.0 if r is None else r, is_defined_steering_tire_rotation_rate=r is not None)


def honest(cc, clk, stamp_ms=0):
    """A Control with every optional field defined, and an odometry received at the same instant."""
    return ctl(cc, stamp_ms=stamp_ms, recv_ns=clk(), v=2.0, a=0.5, j=1.0, d=0.1, r=0.1), cc.Odometry(v=2.0, recv_ns=clk())


def client(cc, K, port=1, clock=None, sink=None, reply_log=None, **kw):
    cfg = cc.Config(host="127.0.0.1", port=port, **kw)
    return cc.CtlClient(cfg, K, clock=clock or Clock(), sink=sink, reply_log=reply_log)


def settle(c, cond, timeout=SLACK_S):
    """Let the client process its socket (wait() pumps too) until cond() holds or the time runs out."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        c.wait(0.02)
    return cond()


def wait_for(cond, timeout=SLACK_S):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def closed_out(cc, c, drain=True):
    """Stop the client and hold the run to the identity: every counted Control packed one frame, and every packed frame
    is replied, dropped or lost, nothing left in flight."""
    s = c.stop(drain=drain)
    n = c.n
    assert n["controls"] == n["packed"] == n["replied"] + n["drop"] + n["lost_on_reconnect"], n
    assert s["identity"]["holds"] and cc.identity(n)["holds"]
    assert c.queued is None and c.outstanding is None and not c.connected
    return s


def message_objs(msgs):
    return [strict_json(m) for m in msgs]


BASE = dict(profile=1, v_cmd=2.0, accel=0.5, jerk=1.0, delta=0.1, rate=0.1, v_meas=2.0, interval_ms=30)
SLOT_FLAGS = {"accel": 0x01, "jerk": 0x02, "rate": 0x04, "v_meas": 0x08}
SLOT_OFFSETS = {"v_cmd": 2, "accel": 25, "jerk": 29, "delta": 33, "rate": 37, "v_meas": 41}


def frame(cf, patch=None, **over):
    """A kind 2 request from BASE with `over` applied: a value None leaves its slot undefined (flag clear, zero
    bytes), a Bits value is packed as its bits; `patch` writes payload bytes afterwards {offset: byte}."""
    v = dict(BASE)
    v.update(over)
    flags = 0
    bits = {}
    for k in SLOT_OFFSETS:
        x = v[k]
        if x is None:
            bits[k] = None
            continue
        bits[k] = int(x) if isinstance(x, Bits) else cf.f32_bits(x)
        flags |= SLOT_FLAGS.get(k, 0)
    f = cf.pack_bits(seq=1, tstamp_ns=0, flags=flags, profile=v["profile"], interval_ms=v["interval_ms"], **bits)
    if patch:
        b = bytearray(f)
        for off, val in patch.items():
            b[H + off] = val
        f = bytes(b)
    return f


# ============================================================ the fake monitor

class FakeMonitor:
    """A loopback peer in place of the monitor's svc mode: one connection at a time, each recorded (the frames it read
    and how it ended). `script(conn_index, frame_index, frame)` says what to do with each complete frame: "reply" (the
    frame with p[6], p[7] written by `answer`), "close", "none", or ("raw", bytes) sent as they are; a list of those is
    done in order. idle_close_s closes a connection that has no complete frame for that long (from its accept or its
    last frame), as svc's deadline does."""

    def __init__(self, script=None, idle_close_s=None, backlog=8):
        self.script = script or (lambda ci, fi, f: "reply")
        self.idle_close_s = idle_close_s
        self.conns = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lsock.bind(("127.0.0.1", 0))
        self.lsock.listen(backlog)
        self.port = self.lsock.getsockname()[1]
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    @staticmethod
    def answer(f):
        b = bytearray(f)
        b[H + 6], b[H + 7] = (0, 0) if b[H + 24] == 2 else (1, 5)
        return bytes(b)

    @property
    def accepts(self):
        with self._lock:
            return len(self.conns)

    def frames(self):
        with self._lock:
            return [f for c in self.conns for f in c["frames"]]

    def seqs(self):
        return [struct.unpack_from("<Q", f, 0)[0] for f in self.frames()]

    def ended(self, ci):
        with self._lock:
            return self.conns[ci]["ended"] if ci < len(self.conns) else None

    def _serve(self):
        self.lsock.settimeout(0.05)
        while not self._stop.is_set():
            try:
                s, _addr = self.lsock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn = {"frames": [], "ended": None}
            with self._lock:
                self.conns.append(conn)
                ci = len(self.conns) - 1
            self._serve_conn(ci, conn, s)

    def _serve_conn(self, ci, conn, s):
        buf = b""
        idle = self.idle_close_s
        due = time.monotonic() + idle if idle else None
        why = "stopped"
        try:
            while not self._stop.is_set():
                r, _w, _x = select.select([s], [], [], 0.01)
                if due is not None and time.monotonic() >= due:
                    why = "idle-closed"
                    return
                if not r:
                    continue
                data = s.recv(64 - len(buf))
                if not data:
                    why = "eof"
                    return
                buf += data
                if len(buf) < 64:
                    continue
                f, buf = buf, b""
                with self._lock:
                    conn["frames"].append(f)
                    fi = len(conn["frames"]) - 1
                acts = self.script(ci, fi, f)
                for a in acts if isinstance(acts, list) else [acts]:
                    if a == "reply":
                        s.sendall(self.answer(f))
                    elif a == "close":
                        why = "closed"
                        return
                    elif a != "none":
                        s.sendall(a[1])
                if due is not None:
                    due = time.monotonic() + idle
        except OSError as err:
            why = "error: %s" % err
        finally:
            with self._lock:
                conn["ended"] = why
            s.close()

    def close(self):
        self._stop.set()
        try:
            self.lsock.close()
        except OSError:
            pass
        self._t.join(2)


@pytest.fixture
def monitor():
    made = []

    def make(**kw):
        m = FakeMonitor(**kw)
        made.append(m)
        return m
    yield make
    for m in made:
        m.close()


def free_port():
    """A loopback port nothing listens on (bound, then released)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ============================================================ 2.1 and 2.2: the constants

def test_the_frame_constants_are_the_specifications(cf):
    assert (cf.FRAME_HEADER_BYTES, cf.FRAME_PAYLOAD_BYTES, cf.FRAME_TOTAL_BYTES) == (16, 48, 64)
    assert cf.SENTINEL_SEQ == (1 << 64) - 1 and cf.KIND_CTL == 2
    assert (cf.P_FLAGS, cf.P_PROFILE, cf.P_V_CMD, cf.P_VERDICT, cf.P_REASON, cf.P_KIND) == (0, 1, 2, 6, 7, 24)
    assert (cf.P_ACCEL, cf.P_JERK, cf.P_DELTA, cf.P_RATE, cf.P_V_MEAS, cf.P_INTERVAL, cf.P_RESERVED) == (25, 29, 33, 37, 41, 45, 47)
    assert cf.STAMP_SPAN == (8, 24)
    assert (cf.F_ACCEL, cf.F_JERK, cf.F_RATE, cf.F_ODOM, cf.F_RESERVED) == (0x01, 0x02, 0x04, 0x08, 0xF0)
    assert cf.INTERVAL_MAX == 0xFFFF
    assert cf.ORDER == SPEC_ORDER
    assert {r: cf.REASON_NAMES[r] for r in SPEC_NAMES} == SPEC_NAMES
    assert cf.CONTRACT_SLOT_PATHS == EXPECTED_SLOT_PATHS


def test_the_shared_reason_names_are_kind_4s(cf, cr):
    for r in (8, 9, 10):
        assert cf.REASON_NAMES[r] == cr.rules.REASON_NAMES[r]


def test_the_design_values_are_the_specifications(cc, node):
    """2.1's client design values, each in one place: reply and connect timeouts 500 ms, the backoff from 100 ms
    doubling to a 2 s cap, the odometry freshness window 100 ms; :7150 the claim port, :7151 the stamp port."""
    assert cc.REPLY_TIMEOUT_NS == 500 * MS and cc.CONNECT_TIMEOUT_NS == 500 * MS
    assert cc.BACKOFF_FIRST_NS == 100 * MS and cc.BACKOFF_CAP_NS == 2000 * MS
    assert cc.ODOM_FRESH_NS == 100 * MS
    assert (cc.CLAIM_PORT, cc.STAMP_PORT, cc.DEMO_PROFILE) == (7150, 7151, 2)
    assert cc.MESSAGE_KEYS == tuple(MESSAGE_KEYS) and cc.MESSAGE_MAX_BYTES == 1024
    assert (node.CONTROL_TOPIC, node.ODOM_TOPIC, node.VERDICT_TOPIC) == (CONTROL_TOPIC, ODOM_TOPIC, VERDICT_TOPIC)
    assert (node.SUBSCRIPTION_DEPTH, node.VERDICT_DEPTH) == (1, 10)
    assert dict(cc.INJECTION_REASONS) == INJECTION_REASONS and tuple(cc.INJECTIONS) == tuple(INJECTION_REASONS)


# ============================================================ ctlframe: encode, pack_bits, decode

def test_encode_writes_each_field_at_its_offset(cf):
    f = cf.encode(seq=7, tstamp_ns=123456789, flags=0x0F, profile=1, v_cmd=2.5, delta=-0.125, accel=0.5, jerk=-1.0,
                  rate=0.25, v_meas=2.25, interval_ms=0x1234)
    assert len(f) == 64
    assert struct.unpack_from("<QQ", f, 0) == (7, 123456789)
    p = f[H:]
    assert (p[0], p[1], p[6], p[7], p[24], p[47]) == (0x0F, 1, 0, 0, 2, 0)
    assert not any(p[8:24])
    assert struct.unpack_from("<f", p, 2)[0] == 2.5
    assert [struct.unpack_from("<f", p, off)[0] for off in (25, 29, 33, 37, 41)] == [0.5, -1.0, -0.125, 0.25, 2.25]
    assert struct.unpack_from("<H", p, 45)[0] == 0x1234 and (p[45], p[46]) == (0x34, 0x12)


@pytest.mark.parametrize("slot", ["accel", "jerk", "rate", "v_meas"])
def test_an_undefined_slot_is_four_zero_bytes(cf, slot):
    kw = dict(accel=0.5, jerk=1.0, rate=0.25, v_meas=2.0)
    kw[slot] = None
    flags = 0x0F & ~SLOT_FLAGS[slot]
    f = cf.encode(seq=1, tstamp_ns=0, flags=flags, profile=1, v_cmd=-0.0, delta=0.0, **kw)
    off = SLOT_OFFSETS[slot]
    assert f[H + off:H + off + 4] == b"\x00\x00\x00\x00"
    assert f[H + 2:H + 6] == struct.pack("<I", 0x80000000)          # a defined -0.0 is a value, sent as it is
    assert cf.decode_request(f).value(slot) is None


@pytest.mark.parametrize("slot", ["v_cmd", "delta", "accel", "jerk", "rate", "v_meas"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 1e39])
def test_encode_refuses_a_non_finite_value(cf, slot, bad):
    kw = dict(v_cmd=1.0, delta=0.0, accel=0.5, jerk=1.0, rate=0.25, v_meas=2.0)
    kw[slot] = bad
    with pytest.raises(cf.FrameError):
        cf.encode(seq=1, tstamp_ns=0, flags=0x0F, profile=1, **kw)


@pytest.mark.parametrize("slot", ["accel", "jerk", "rate", "v_meas"])
def test_encode_and_pack_bits_refuse_a_defined_undefined_mismatch(cf, slot):
    full = dict(v_cmd=1.0, delta=0.0, accel=0.5, jerk=1.0, rate=0.25, v_meas=2.0)
    missing = dict(full)
    missing[slot] = None
    with pytest.raises(cf.FrameError):           # the flag set, the value missing
        cf.encode(seq=1, tstamp_ns=0, flags=0x0F, profile=1, **missing)
    with pytest.raises(cf.FrameError):           # the value given, the flag clear
        cf.encode(seq=1, tstamp_ns=0, flags=0x0F & ~SLOT_FLAGS[slot], profile=1, **full)
    bits = {k: cf.f32_bits(x) for k, x in full.items()}
    with pytest.raises(cf.FrameError):
        cf.pack_bits(seq=1, tstamp_ns=0, flags=0x0F & ~SLOT_FLAGS[slot], profile=1, **bits)


@pytest.mark.parametrize("flags", [0x10, 0x20, 0x40, 0x80])
def test_encode_and_pack_bits_refuse_a_reserved_flag_bit(cf, flags):
    with pytest.raises(cf.FrameError):
        cf.encode(seq=1, tstamp_ns=0, flags=flags, profile=1, v_cmd=1.0, delta=0.0)
    with pytest.raises(cf.FrameError):
        cf.pack_bits(seq=1, tstamp_ns=0, flags=flags, profile=1, v_cmd=0, delta=0)


@pytest.mark.parametrize("profile", [0, 256, -1, True, 1.0])
def test_encode_refuses_a_profile_outside_1_to_255(cf, profile):
    with pytest.raises(cf.FrameError):
        cf.encode(seq=1, tstamp_ns=0, flags=0, profile=profile, v_cmd=1.0, delta=0.0)


def test_pack_bits_takes_profile_0_and_encode_takes_1_and_255(cf):
    assert cf.pack_bits(seq=1, tstamp_ns=0, flags=0, profile=0, v_cmd=0, delta=0)[H + 1] == 0
    for pid in (1, 255):
        assert cf.encode(seq=1, tstamp_ns=0, flags=0, profile=pid, v_cmd=1.0, delta=0.0)[H + 1] == pid


@pytest.mark.parametrize("seq", [0, (1 << 64) - 1, -1, 1 << 64])
def test_encode_and_pack_bits_refuse_seq_0_and_the_sentinel(cf, seq):
    with pytest.raises(cf.FrameError):
        cf.encode(seq=seq, tstamp_ns=0, flags=0, profile=1, v_cmd=1.0, delta=0.0)
    with pytest.raises(cf.FrameError):
        cf.pack_bits(seq=seq, tstamp_ns=0, flags=0, profile=1, v_cmd=0, delta=0)


@pytest.mark.parametrize("interval", [-1, 0x10000, 1.5, True])
def test_encode_refuses_an_interval_outside_u16(cf, interval):
    with pytest.raises(cf.FrameError):
        cf.encode(seq=1, tstamp_ns=0, flags=0, profile=1, v_cmd=1.0, delta=0.0, interval_ms=interval)


@pytest.mark.parametrize("bits", [0x7FC00000, 0x7F800001, 0xFFC00001, 0x7F800000, 0xFF800000, 0x80000000, 0x00000001])
def test_pack_bits_packs_the_exact_bits_of_every_slot(cf, bits):
    f = cf.pack_bits(seq=1, tstamp_ns=0, flags=0x0F, profile=1, v_cmd=bits, delta=bits, accel=bits, jerk=bits, rate=bits,
                     v_meas=bits)
    for off in SLOT_OFFSETS.values():
        assert struct.unpack_from("<I", f, H + off)[0] == bits


def test_interval_ms_is_0_first_truncated_and_saturated(cf):
    assert cf.interval_ms(None, 5 * 10 ** 12) == 0
    assert cf.interval_ms(T0, T0 + 30 * MS) == 30
    assert cf.interval_ms(T0, T0 + 30 * MS + 999_999) == 30
    assert cf.interval_ms(T0, T0 + 65_535 * MS) == 0xFFFF
    assert cf.interval_ms(T0, T0 + 65_536 * MS) == 0xFFFF
    assert cf.interval_ms(T0, T0 + 3600 * 1000 * MS) == 0xFFFF
    assert cf.interval_ms(T0, T0) == 0
    assert cf.interval_ms(T0, T0 - MS) == 0            # a stamp that went back: 0, and the client counts it


def test_decode_request_reads_back_what_encode_wrote(cf):
    f = cf.encode(seq=9, tstamp_ns=77, flags=0x05, profile=2, v_cmd=-1.5, delta=0.25, accel=0.75, rate=-0.5,
                  interval_ms=31)
    d = cf.decode_request(f)
    assert (d.seq, d.tstamp_ns, d.flags, d.profile, d.interval_ms, d.verdict, d.reason) == (9, 77, 0x05, 2, 31, 0, 0)
    assert (d.v_cmd, d.accel, d.jerk, d.delta, d.rate, d.v_meas) == (-1.5, 0.75, None, 0.25, -0.5, None)
    assert d.bits["v_cmd"] == cf.f32_bits(-1.5) and d.bits["jerk"] is None


def _layout_faults():
    out = [("length 63", lambda b: b[:63]), ("length 65", lambda b: b + b"\x00"),
           ("seq 0", lambda b: b"\x00" * 8 + b[8:]), ("sentinel", lambda b: b"\xff" * 8 + b[8:]),
           ("kind 3", lambda b: b[:H + 24] + b"\x03" + b[H + 25:]), ("p47", lambda b: b[:63] + b"\x01"),
           ("verdict in request", lambda b: b[:H + 6] + b"\x01" + b[H + 7:]),
           ("reason in request", lambda b: b[:H + 7] + b"\x05" + b[H + 8:])]
    for bit in (0x10, 0x20, 0x40, 0x80):
        out.append(("flag 0x%02X" % bit, lambda b, bit=bit: b[:H] + bytes([b[H] | bit]) + b[H + 1:]))
    for i in range(8, 24):
        out.append(("p[%d]" % i, lambda b, i=i: b[:H + i] + b"\x01" + b[H + i + 1:]))
    return out


@pytest.mark.parametrize("name,mutate", _layout_faults(), ids=[n for n, _m in _layout_faults()])
def test_decode_request_refuses_every_layout_fault(cf, name, mutate):
    f = cf.encode(seq=1, tstamp_ns=0, flags=0, profile=1, v_cmd=1.0, delta=0.0)
    cf.decode_request(f)
    with pytest.raises(cf.FrameError):
        cf.decode_request(mutate(f))


@pytest.mark.parametrize("slot", ["accel", "jerk", "rate", "v_meas"])
@pytest.mark.parametrize("bits", [0x80000000, NAN_BITS, 0x00000001])
def test_decode_request_refuses_an_undefined_slot_not_all_zero(cf, slot, bits):
    f = bytearray(cf.encode(seq=1, tstamp_ns=0, flags=0, profile=1, v_cmd=1.0, delta=0.0))
    struct.pack_into("<I", f, H + SLOT_OFFSETS[slot], bits)
    with pytest.raises(cf.FrameError):
        cf.decode_request(bytes(f))


def test_decode_reply_takes_a_consistent_verdict_and_reason_only(cf):
    req = cf.encode(seq=3, tstamp_ns=0, flags=0, profile=1, v_cmd=1.0, delta=0.0)

    def rep(v, r, stamp=b""):
        b = bytearray(req)
        b[H + 6], b[H + 7] = v, r
        if stamp:
            b[H + 8:H + 24] = stamp
        return bytes(b)
    assert (cf.decode_reply(rep(0, 0)).verdict, cf.decode_reply(rep(1, 12)).reason) == (0, 12)
    for v, r in ((2, 0), (2, 5), (0, 3), (1, 0)):
        with pytest.raises(cf.FrameError):
            cf.decode_reply(rep(v, r))
    stamps = struct.pack("<QQ", 11, 22)
    with pytest.raises(cf.FrameError):
        cf.decode_reply(rep(1, 12, stamps))
    d = cf.decode_reply(rep(1, 12, stamps), stamp=True)
    assert (d.t_in_ns, d.t_out_ns) == (11, 22)
    with pytest.raises(cf.FrameError):
        cf.decode_reply(rep(1, 12)[:H + 47] + b"\x01")


@pytest.mark.parametrize("reason", [5, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
def test_decode_reply_takes_every_kind_2_reason(cf, reason):
    req = cf.encode(seq=3, tstamp_ns=0, flags=0, profile=1, v_cmd=1.0, delta=0.0)
    b = bytearray(req)
    b[H + 6] = 1
    b[H + 7] = reason
    d = cf.decode_reply(bytes(b))
    assert (d.verdict, d.reason) == (1, reason)


@pytest.mark.parametrize("i", range(8, 24))
def test_a_stamp_reply_takes_any_byte_in_the_stamp_span(cf, i):
    req = cf.encode(seq=3, tstamp_ns=0, flags=0, profile=1, v_cmd=1.0, delta=0.0)
    b = bytearray(req)
    b[H + 6] = 0
    b[H + 7] = 0
    b[H + i] = 0xFF
    assert cf.decode_reply(bytes(b), stamp=True).verdict == 0
    with pytest.raises(cf.FrameError):
        cf.decode_reply(bytes(b))


def test_digest_of_is_fnv1_32_over_little_endian_uids(cf):
    assert cf.fnv1_32(b"") == 0x811C9DC5 and cf.fnv1_32(b"a") == 0x050C5D7E
    uids = tuple(0xC7100001 + i for i in range(7))
    assert cf.digest_of(uids) == 0x682F2F02
    assert cf.fnv1_32(b"".join(struct.pack(">I", u) for u in uids)) != 0x682F2F02


# ============================================================ ctlframe: the contract loader

def test_the_fixture_contract_loads(cf, K):
    assert K.FORMAT == 1 and tuple(K.SLOT_PATHS) == EXPECTED_SLOT_PATHS
    assert cf.digest_of(K.SLOT_UIDS) == K.DIGEST
    assert tuple(K.COMPILED_PROFILE_IDS) == (1, 2)
    assert cf.contract_sha256(K) == hashlib.sha256(CONTRACT_FILE.read_bytes()).hexdigest()


def test_the_loader_imports_by_path_only_and_leaves_no_bytecode(cf):
    before = set(sys.modules)
    cf.load_contract(CONTRACT_FILE)
    assert "vss_ctl" not in sys.modules and not any(m == "vss_ctl" for m in set(sys.modules) - before)
    assert not (FIX / "__pycache__").exists()


def test_the_bad_digest_twin_is_refused(cf):
    with pytest.raises(cf.ContractError, match="DIGEST"):
        cf.load_contract(BAD_DIGEST_FILE)


def _variant(tmp_path, old, new):
    src = CONTRACT_FILE.read_text(encoding="utf-8")
    assert src.count(old) == 1, old
    p = tmp_path / "vss_ctl.py"
    p.write_text(src.replace(old, new), encoding="utf-8")
    return p


def _contract_with(cf, tmp_path, *pairs):
    """The fixture contract with each (old, new) applied, written into a directory of its own under tmp_path (a client
    reads the file again for its header's sha256) and loaded."""
    src = CONTRACT_FILE.read_text(encoding="utf-8")
    for old, new in pairs:
        assert src.count(old) == 1, old
        src = src.replace(old, new)
    d = tmp_path / ("contract-%d" % len(list(tmp_path.iterdir())))
    d.mkdir()
    (d / "vss_ctl.py").write_text(src, encoding="utf-8")
    return cf.load_contract(d / "vss_ctl.py")


P1_STEER_MAX = '"steer_max": 1.0, "steer_rate_max": 1.0,\n        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": True}'


@pytest.mark.parametrize("old,new", [
    ("FORMAT = 1", "FORMAT = 2"),
    ("FORMAT = 1", "FORMAT = True"),
    ("FORMAT = 1", "FORMAT = 1.0"),                     # the generated module writes the int 1 (C: VSS_CTL_FORMAT 1u)
    ("FORMAT = 1", "FORMAT_ = 1"),
    ('"Vehicle.DualVm.Motion.LongitudinalVelocity",', '"Vehicle.DualVm.Motion.LateralVelocity",'),
    ("DT_MAX_MS = 200", "DT_MAX_MS = None"),
    ('    3: {"l_mm": 2790,', '    0: {"l_mm": 2790,'),   # profile 3 is not compiled: only its id breaks a rule
    ('    1: {"l_mm": 2790,', '    1: {"l_mm": 0,'),
    ('"steer_max": 1.0, "steer_rate_max": 1.0,\n        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": True}',
     '"steer_max": 1.0000000000000002, "steer_rate_max": 1.0,\n        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": True}'),
    ('"steer_max": 1.0, "steer_rate_max": 1.0,\n        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": True}',
     '"steer_max": 0.0, "steer_rate_max": 1.0,\n        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": True}'),
    ('"steer_max": 1.0, "steer_rate_max": 1.0,\n        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": True}',
     '"steer_max": float("nan"), "steer_rate_max": 1.0,\n        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": True}'),
    ("COMPILED_PROFILE_IDS = (1, 2)", "COMPILED_PROFILE_IDS = (1, 2, 3)"),
    ("0xC7100006, 0xC7100007)", "0xC7100007, 0xC7100006)"),
])
def test_the_loader_refuses_a_contract_that_breaks_its_rules(cf, tmp_path, old, new):
    """2.4's three rules (FORMAT the int 1, the digest, a compiled steer_max in (0, 1.0]) and the generated module's
    shape: the seven slot paths, the five constants, profile ids in 1..255, a compiled row's l_mm a positive int."""
    with pytest.raises(cf.ContractError):
        cf.load_contract(_variant(tmp_path, old, new))


def test_the_loader_judges_only_compiled_profiles_steer_max(cf, tmp_path):
    p = _variant(tmp_path, '"steer_max": 0.5,', '"steer_max": 2.0,')         # profile 3, not compiled
    assert cf.load_contract(p).PROFILES[3]["steer_max"] == 2.0
    with pytest.raises(cf.ContractError):
        cf.load_contract(tmp_path / "absent.py")


# the fixture's profile 2 row, its start and its end: the loader refuses a row's shape beyond 2.4's three rules
# (run_window_max_ms None or a positive int, compiled a bool, a compiled row's limits positive numbers)
P2_ROW_END = '"run_window_max_ms": 30000, "compiled": True}'
P2_ROW_START = '    2: {"l_mm": 2790, "v_max": 3.0,'


@pytest.mark.parametrize("pairs", [
    [(P2_ROW_END, '"run_window_max_ms": 0, "compiled": True}')],
    [(P2_ROW_END, '"run_window_max_ms": 1.5, "compiled": True}')],
    [(P2_ROW_END, '"run_window_max_ms": 30000, "compiled": 1}'), ("COMPILED_PROFILE_IDS = (1, 2)", "COMPILED_PROFILE_IDS = (1,)")],
    [(P2_ROW_START, '    2: {"l_mm": 2790, "v_max": 0.0,')],
    [(P2_ROW_START, '    2: {"l_mm": 2790, "v_max": float("nan"),')],
], ids=["window 0", "window 1.5", "compiled 1", "v_max 0", "v_max nan"])
def test_x_the_loader_refuses_a_profile_row_of_another_shape(cf, tmp_path, pairs):
    src = CONTRACT_FILE.read_text(encoding="utf-8")
    for old, new in pairs:
        assert src.count(old) == 1, old
        src = src.replace(old, new)
    p = tmp_path / "vss_ctl.py"
    p.write_text(src, encoding="utf-8")
    with pytest.raises(cf.ContractError):
        cf.load_contract(p)


def test_x_a_contract_that_fails_to_execute_is_a_contract_error(cf, tmp_path):
    p = _variant(tmp_path, "FORMAT = 1", "FORMAT = 1\nraise RuntimeError('half written')")
    with pytest.raises(cf.ContractError, match="does not load"):
        cf.load_contract(p)


def test_x_the_loader_refuses_compiled_profile_ids_out_of_order(cf, tmp_path):
    with pytest.raises(cf.ContractError, match="COMPILED_PROFILE_IDS"):
        cf.load_contract(_variant(tmp_path, "COMPILED_PROFILE_IDS = (1, 2)", "COMPILED_PROFILE_IDS = (2, 1)"))


# ============================================================ ctlrules: the reference judge

def test_an_honest_frame_is_accepted(cr, cf, K, mpm):
    assert cr.judge(frame(cf), K, m_per_mm=mpm) == (0, 0)
    assert cr.judge(frame(cf), K) == (0, 0)                 # the default M_PER_MM is the kind 4 contract's


@pytest.mark.parametrize("field,limit,reason", [("v_cmd", "v_max", 12), ("accel", "a_max", 13), ("jerk", "jerk_max", 14),
                                                ("delta", "steer_max", 15), ("rate", "steer_rate_max", 16)])
@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_each_limit_at_and_one_binary32_step_above(cr, cf, K, mpm, field, limit, reason, sign):
    lim = K.PROFILES[1][limit]
    assert cf.f32(lim) == lim
    assert cr.judge(frame(cf, **{field: sign * lim}), K, m_per_mm=mpm) == (0, 0)
    assert cr.judge(frame(cf, **{field: sign * up(cf, lim)}), K, m_per_mm=mpm) == (1, reason)


@pytest.mark.parametrize("field", ["accel", "jerk", "rate"])
def test_an_undefined_slot_skips_its_rule(cr, cf, K, mpm, field):
    assert cr.judge(frame(cf, **{field: None}), K, m_per_mm=mpm) == (0, 0)


def test_the_interval_at_dt_max_and_above(cr, cf, K, mpm):
    dt = K.DT_MAX_MS
    assert cr.judge(frame(cf, interval_ms=dt), K, m_per_mm=mpm) == (0, 0)
    assert cr.judge(frame(cf, interval_ms=dt + 1), K, m_per_mm=mpm) == (1, 11)
    assert cr.judge(frame(cf, interval_ms=0xFFFF), K, m_per_mm=mpm) == (1, 11)
    assert cr.judge(frame(cf, interval_ms=0), K, m_per_mm=mpm) == (0, 0)


def _rule17_edge(cf, rules_mod, K, mpm, delta):
    """The largest binary32 v_meas whose v*v*tan(|delta|)/L_m (double, that order, rules.vss_tan, L_m = l_mm * M_PER_MM)
    is not above lat_acc_max + TOL17, found by stepping binary32 values."""
    pr = K.PROFILES[1]
    l_m = float(pr["l_mm"]) * mpm
    t = rules_mod.vss_tan(abs(delta))
    bound = pr["lat_acc_max"] + K.TOL17

    def over(v):
        return v * v * t / l_m > bound
    v = cf.f32(math.sqrt(bound * l_m / t))
    while over(v):
        v = cf.f32_next_down(v)
    while not over(cf.f32_next_up(v)):
        v = cf.f32_next_up(v)
    return v


@pytest.mark.parametrize("delta", [0.5, -0.5, 1.0, 0.0625])
@pytest.mark.parametrize("vsign", [1.0, -1.0])
def test_rule_17_at_its_edge_against_rules_vss_tan(cr, cf, K, mpm, delta, vsign):
    rules_mod = cr.rules
    v = _rule17_edge(cf, rules_mod, K, mpm, delta)
    vc = 25.0 * vsign        # rule 18 stays quiet (1.2 x 25 + 2 is above every v_meas here), and 19 with v_cmd < 0
    assert cr.judge(frame(cf, delta=delta, v_meas=vsign * v, v_cmd=vc), K, m_per_mm=mpm) == (0, 0)
    assert cr.judge(frame(cf, delta=delta, v_meas=vsign * up(cf, v), v_cmd=vc), K, m_per_mm=mpm) == (1, 17)
    assert cr.judge(frame(cf, delta=delta, v_meas=None, v_cmd=vc), K, m_per_mm=mpm) == (0, 0)     # b3 clear: skipped


def test_rule_17_uses_tol17_and_the_wheelbase_in_metres(cr, cf, K, mpm):
    """At v_meas with v*v*tan/L_m between lat_acc_max and lat_acc_max + TOL17 the frame is accepted, and at a v_meas
    whose lateral acceleration is over the bound only when L is taken in metres it is rejected."""
    pr = K.PROFILES[1]
    l_m = float(pr["l_mm"]) * mpm
    t = cr.rules.vss_tan(0.5)
    v_mid = cf.f32(math.sqrt((pr["lat_acc_max"] + K.TOL17 / 2) * l_m / t))
    assert cr.judge(frame(cf, delta=0.5, v_meas=v_mid, v_cmd=25.0), K, m_per_mm=mpm) == (0, 0)
    assert cr.lat_accel(v_mid, 0.5, pr["l_mm"], mpm) == v_mid * v_mid * t / l_m
    # twice the bound: rejected with L in metres, while with L in mm the left side would be a thousandth of it and pass
    # (rules 12 and 18 stay quiet at v_cmd 25.0)
    v_over = cf.f32(math.sqrt(2 * (pr["lat_acc_max"] + K.TOL17) * l_m / t))
    assert cr.judge(frame(cf, delta=0.5, v_meas=v_over, v_cmd=25.0), K, m_per_mm=mpm) == (1, 17)


def _rule18_edge(cf, K, v_cmd):
    thr = K.OVERSPEED_FACTOR * abs(v_cmd) + K.OVERSPEED_MARGIN
    v = cf.f32(thr)
    while v > thr:
        v = -cf.f32_next_up(-v)
    while cf.f32_next_up(v) <= thr:
        v = cf.f32_next_up(v)
    return v


@pytest.mark.parametrize("v_cmd", [2.0, -2.0, 0.0, 12.5])
def test_rule_18_at_its_threshold_with_absolute_values(cr, cf, K, mpm, v_cmd):
    v = _rule18_edge(cf, K, v_cmd)
    assert cr.judge(frame(cf, delta=0.0, v_cmd=v_cmd, v_meas=v), K, m_per_mm=mpm) == (0, 0)
    assert cr.judge(frame(cf, delta=0.0, v_cmd=v_cmd, v_meas=up(cf, v)), K, m_per_mm=mpm) == (1, 18)
    assert cr.judge(frame(cf, delta=0.0, v_cmd=v_cmd, v_meas=-up(cf, v)), K, m_per_mm=mpm) == (1, 18)
    assert cr.judge(frame(cf, delta=0.0, v_cmd=v_cmd, v_meas=None), K, m_per_mm=mpm) == (0, 0)


def test_rule_19_at_its_threshold(cr, cf, K, mpm):
    rb = K.ROLLBACK_V
    assert cf.f32(rb) == rb
    for v_cmd in (0.0, -0.0, 1.0):
        assert cr.judge(frame(cf, delta=0.0, v_cmd=v_cmd, v_meas=-rb), K, m_per_mm=mpm) == (0, 0)
        assert cr.judge(frame(cf, delta=0.0, v_cmd=v_cmd, v_meas=-up(cf, rb)), K, m_per_mm=mpm) == (1, 19)
    assert cr.judge(frame(cf, delta=0.0, v_cmd=-0.25, v_meas=-1.0), K, m_per_mm=mpm) == (0, 0)
    assert cr.judge(frame(cf, delta=0.0, v_cmd=0.0, v_meas=None), K, m_per_mm=mpm) == (0, 0)


def _faults(cf, K):
    pr = K.PROFILES[1]
    return {
        10: dict(patch={47: 1}),
        8: dict(profile=0),
        9: dict(v_cmd=Bits(NAN_BITS)),
        11: dict(interval_ms=K.DT_MAX_MS + 1),
        12: dict(v_cmd=up(cf, pr["v_max"])),
        13: dict(accel=up(cf, pr["a_max"])),
        14: dict(jerk=up(cf, pr["jerk_max"])),
        15: dict(delta=up(cf, pr["steer_max"])),
        16: dict(rate=up(cf, pr["steer_rate_max"])),
        17: dict(delta=0.5, v_meas=20.0, v_cmd=25.0),
        18: dict(delta=0.0, v_meas=20.0, v_cmd=2.0),
        19: dict(delta=0.0, v_meas=-1.0, v_cmd=0.0),
    }


@pytest.mark.parametrize("reason", SPEC_ORDER)
def test_each_fault_alone_gives_its_reason(cr, cf, K, mpm, reason):
    assert cr.judge(frame(cf, **_faults(cf, K)[reason]), K, m_per_mm=mpm) == (1, reason)


@pytest.mark.parametrize("pair", list(zip(SPEC_ORDER, SPEC_ORDER[1:])), ids=lambda p: "%d-%d" % p)
def test_of_two_adjacent_failures_the_earlier_wins(cr, cf, K, mpm, pair):
    a, b = pair
    fa, fb = _faults(cf, K)[a], _faults(cf, K)[b]
    if pair == (17, 18):
        kw = dict(delta=0.5, v_meas=20.0, v_cmd=2.0)
    elif pair == (18, 19):
        kw = dict(delta=0.0, v_meas=-20.0, v_cmd=2.0)
    else:
        kw = dict(fb)
        kw.update(fa)
        patch = dict(fb.get("patch", {}))
        patch.update(fa.get("patch", {}))
        kw["patch"] = patch or None
    f = frame(cf, **kw)
    assert cr.judge(f, K, m_per_mm=mpm) == (1, a)


@pytest.mark.parametrize("bit", [0x10, 0x20, 0x40, 0x80])
def test_rule_10_a_reserved_flag_bit(cr, cf, K, mpm, bit):
    assert cr.judge(frame(cf, patch={0: 0x0F | bit}), K, m_per_mm=mpm) == (1, 10)


@pytest.mark.parametrize("off", list(range(8, 24)) + [47])
def test_rule_10_a_reserved_byte(cr, cf, K, mpm, off):
    assert cr.judge(frame(cf, patch={off: 0x01}), K, m_per_mm=mpm) == (1, 10)


@pytest.mark.parametrize("slot", ["accel", "jerk", "rate", "v_meas"])
@pytest.mark.parametrize("bits", [0x80000000, NAN_BITS, 0x7F800000])
def test_rule_10_an_undefined_slot_not_all_zero_comes_before_9(cr, cf, K, mpm, slot, bits):
    f = bytearray(frame(cf, **{slot: None}))
    struct.pack_into("<I", f, H + SLOT_OFFSETS[slot], bits)
    assert cr.judge(bytes(f), K, m_per_mm=mpm) == (1, 10)


def test_rule_10_ignores_the_verdict_and_reason_bytes(cr, cf, K, mpm):
    assert cr.judge(frame(cf, patch={6: 1, 7: 12}), K, m_per_mm=mpm) == (0, 0)


@pytest.mark.parametrize("pid", [0, 3, 4, 255])
def test_rule_8_an_uncompiled_or_absent_profile(cr, cf, K, mpm, pid):
    assert cr.judge(frame(cf, profile=pid), K, m_per_mm=mpm) == (1, 8)


@pytest.mark.parametrize("slot", ["v_cmd", "delta", "accel", "jerk", "rate", "v_meas"])
@pytest.mark.parametrize("bits", [0x7FC00000, 0x7F800001, 0xFFC00000, 0x7F800000, 0xFF800000])
def test_rule_9_a_non_finite_defined_slot(cr, cf, K, mpm, slot, bits):
    assert cr.judge(frame(cf, **{slot: Bits(bits)}), K, m_per_mm=mpm) == (1, 9)


def test_the_judge_refuses_other_kinds_and_lengths_and_passes_the_sentinel(cr, cf, K, mpm):
    with pytest.raises(ValueError):
        cr.judge(frame(cf, patch={24: 4}), K, m_per_mm=mpm)
    with pytest.raises(ValueError):
        cr.judge(frame(cf)[:63], K, m_per_mm=mpm)
    assert cr.judge(b"\xff" * 8 + frame(cf)[8:], K, m_per_mm=mpm) is None


# ============================================================ ctlclient: packing and accounting, no socket

def test_the_client_packs_one_frame_per_control_from_seq_1(cc, cf, K):
    clk = Clock()
    c = client(cc, K, clock=clk)
    assert c.offer(*honest(cc, clk)) == 1
    d = cf.decode_request(c.queued.frame)
    assert (d.seq, d.tstamp_ns, d.profile, d.flags, d.interval_ms) == (1, T0, 1, 0x0F, 0)
    assert (d.v_cmd, d.accel, d.jerk, d.delta, d.rate, d.v_meas) == (2.0, 0.5, 1.0, cf.f32(0.1), cf.f32(0.1), 2.0)
    clk.advance(ms=30)
    assert c.offer(*honest(cc, clk, stamp_ms=30.5)) == 2
    d = cf.decode_request(c.queued.frame)
    assert (d.seq, d.tstamp_ns, d.interval_ms) == (2, T0 + 30 * MS, 30)
    assert c.n["interval_negative"] == 0
    clk.advance(ms=30)
    assert c.offer(*honest(cc, clk, stamp_ms=10)) == 3          # a stamp that went back: interval 0, and counted
    assert (cf.decode_request(c.queued.frame).interval_ms, c.n["interval_negative"]) == (0, 1)
    closed_out(cc, c)


def test_the_client_packs_undefined_fields_as_zero_bytes_with_their_flags_clear(cc, cf, K):
    clk = Clock()
    c = client(cc, K, clock=clk)
    c.offer(ctl(cc, v=-1.0, a=None, j=None, d=-0.25, r=None), None)
    f = c.queued.frame
    assert f[H] == 0 and f[H + 25:H + 45] == bytes(4) + bytes(4) + struct.pack("<f", -0.25) + bytes(4) + bytes(4)
    assert cf.decode_request(f).v_cmd == -1.0
    closed_out(cc, c)


def test_b3_only_for_an_odometry_inside_the_freshness_window(cc, cf, K):
    clk = Clock()
    c = client(cc, K, clock=clk)
    for age, b3 in ((0, True), (100 * MS, True), (100 * MS + 1, False), (-1, False)):
        c.offer(ctl(cc, recv_ns=clk()), cc.Odometry(v=1.5, recv_ns=clk() - age))
        d = cf.decode_request(c.queued.frame)
        assert bool(d.flags & 0x08) is b3, age
        assert d.v_meas == (1.5 if b3 else None)
    c.offer(ctl(cc, recv_ns=clk()), None)
    assert not c.queued.frame[H] & 0x08
    assert (c.n["r17_skip"], c.n["odom_absent"], c.n["odom_stale"]) == (3, 1, 2)     # stale: too old, or after the Control
    closed_out(cc, c)


@pytest.mark.parametrize("odom", ["absent", "stale"])
@pytest.mark.parametrize("mode", ["lat-accel", "overspeed", "rolling-back"])
def test_r17_skip_counts_the_frames_packed_with_b3_clear(cc, cf, K, mode, odom):
    """2.3: the node counts r17_skip when b3 is clear. An injection that sets b3 packs a frame rule 17 is judged on, so it
    is no r17_skip whatever the odometry was; the odometry's own state is still counted (odom_absent, odom_stale)."""
    clk = Clock()
    c = client(cc, K, clock=clk, injections=((1, mode),))
    o = None if odom == "absent" else cc.Odometry(v=2.0, recv_ns=clk() - 101 * MS)
    c.offer(ctl(cc, recv_ns=clk()), o)
    assert c.queued.frame[H] & 0x08
    assert (c.n["r17_skip"], c.n["odom_absent"], c.n["odom_stale"]) == (0, int(odom == "absent"), int(odom == "stale"))
    clk.advance(ms=30)
    c.offer(ctl(cc, stamp_ms=30, recv_ns=clk()), o)             # seq 2, not injected: b3 clear, an r17_skip
    assert not c.queued.frame[H] & 0x08
    assert (c.n["r17_skip"], c.n["odom_absent"], c.n["odom_stale"]) == (1, 2 * (odom == "absent"), 2 * (odom == "stale"))
    closed_out(cc, c)


def test_a_non_finite_honest_value_is_packed_as_it_came(cc, cf, K):
    """No Control goes uncounted: a non-finite value the gate sent is packed bit for bit (the monitor answers 9)."""
    clk = Clock()
    c = client(cc, K, clock=clk)
    c.offer(ctl(cc, v=math.inf, a=math.nan), None)
    f = c.queued.frame
    assert struct.unpack_from("<I", f, H + 2)[0] == 0x7F800000
    assert not cf.is_finite_bits(struct.unpack_from("<I", f, H + 25)[0])
    assert c.n["nonfinite_in"] == 1
    c.offer(ctl(cc, v=-1e39, d=1e39), None)                 # beyond binary32: the infinity of its sign, as C converts it
    f = c.queued.frame
    assert struct.unpack_from("<I", f, H + 2)[0] == 0xFF800000 and struct.unpack_from("<I", f, H + 33)[0] == 0x7F800000
    assert c.n["nonfinite_in"] == 2
    closed_out(cc, c)


def test_a_sink_that_raises_is_counted_and_breaks_nothing(cc, K, tmp_path):
    def sink(_s):
        raise RuntimeError("the publisher's context is shut down")
    log = tmp_path / "replies.jsonl"
    c = client(cc, K, sink=sink, reply_log=log)
    c.offer(ctl(cc), None)
    c.offer(ctl(cc, stamp_ms=30), None)
    closed_out(cc, c)
    assert c.n["sink_errors"] == 2
    assert [json.loads(x).get("outcome") for x in log.read_text(encoding="utf-8").splitlines()[1:-1]] == ["drop", "drop"]


def test_the_sentinel_is_never_packed(cc, K):
    c = client(cc, K)
    c.next_seq = (1 << 64) - 1
    with pytest.raises(cc.ClientError):
        c.offer(ctl(cc), None)
    assert c.n["controls"] == c.n["packed"] == 0
    closed_out(cc, c)


def test_the_one_deep_queue_counts_each_replaced_frame_as_a_drop(cc, cf, K, tmp_path):
    msgs = []
    log = tmp_path / "replies.jsonl"
    c = client(cc, K, sink=msgs.append, reply_log=log)
    for i in range(3):
        c.offer(ctl(cc, stamp_ms=30 * i), None)
    assert (c.n["drop"], c.queued.seq) == (2, 3)
    closed_out(cc, c)                     # nothing ever connected: the queued frame is a drop at the stop
    assert c.n["drop"] == 3 and c.n["connects"] == 0
    objs = message_objs(msgs)
    assert [(o["seq"], o["verdict"], o["dropped"]) for o in objs] == [(1, None, 1), (2, None, 2), (3, None, 3)]
    recs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [r["outcome"] for r in recs[1:-1]] == ["drop"] * 3


def test_the_intake_pause_counts_no_control_and_the_next_carries_the_interval(cc, cf, K):
    clk = Clock()
    c = client(cc, K, clock=clk, pause=(2, 1000))
    assert c.offer(ctl(cc, stamp_ms=0), None) == 1
    clk.advance(ms=30)
    assert c.offer(ctl(cc, stamp_ms=30), None) == 2          # the pause starts once seq 2 is packed
    for dt, stamp in ((30, 60), (969, 90)):
        clk.advance(ms=dt)
        assert c.offer(ctl(cc, stamp_ms=stamp), None) is None
    assert (c.n["controls"], c.n["packed"], c.n["controls_paused"]) == (2, 2, 2)
    clk.advance(ms=1)                                        # 1000 ms after the pause started: it is over
    assert c.offer(ctl(cc, stamp_ms=1030), None) == 3
    assert cf.decode_request(c.queued.frame).interval_ms == 1000
    closed_out(cc, c)


def test_profile_2_only_inside_its_window_from_the_first_packed_frame(cc, cf, K):
    clk = Clock()
    c = client(cc, K, clock=clk, demo=(100, 200))
    profiles = []
    for dt in (0, 99, 1, 199, 1, 500):
        clk.advance(ms=dt)
        c.offer(ctl(cc, v=1.0), None)
        profiles.append(cf.decode_request(c.queued.frame).profile)
    assert profiles == [1, 1, 2, 2, 1, 1]
    s = closed_out(cc, c)
    assert s["demo"] == {"profile": 2, "first_seq": 3, "last_seq": 4, "frames": 2}


@pytest.mark.parametrize("kw", [
    dict(port=7151, injections=((5, "nan"),)), dict(port=7151, pause=(5, 100)), dict(stamp=True, injections=((5, "speed"),)),
    dict(stamp=True, pause=(5, 100)), dict(profile=2), dict(profile=0), dict(profile=3), dict(profile=9), dict(profile=True),
    dict(demo=(0, 30001)), dict(demo=(0, 0)), dict(demo=(-1, 100)), dict(injections=((5, "bogus"),)),
    dict(injections=((0, "nan"),)), dict(injections=((5, "nan"), (5, "speed"))), dict(pause=(0, 100)), dict(pause=(5, 0)),
    dict(port=0), dict(port=65536), dict(port=7151, stamp=False, demo=(0, 100)), dict(host=""),
], ids=lambda kw: ",".join("%s=%s" % i for i in sorted(kw.items())))
def test_the_config_refusals(cc, K, kw):
    cfg = cc.Config(**{"host": "127.0.0.1", **kw})
    assert cc.check_config(cfg, K)
    with pytest.raises(cc.ClientError):
        cc.CtlClient(cfg, K)


def test_a_demo_window_is_refused_when_profile_2_is_not_compiled(cc, cf, K, tmp_path):
    """The demo profile is the one a --demo window sends; a contract that does not compile it into the guest would
    have every demo frame answered 8, so the window is refused at start (the base profile alone still starts)."""
    k = _contract_with(cf, tmp_path, ('"run_window_max_ms": 30000, "compiled": True}', '"run_window_max_ms": 30000, "compiled": False}'),
                       ("COMPILED_PROFILE_IDS = (1, 2)", "COMPILED_PROFILE_IDS = (1,)"))
    demo = cc.Config(host="127.0.0.1", demo=(0, 100))
    assert cc.check_config(demo, K) == []
    assert [p for p in cc.check_config(demo, k) if "not compiled" in p]
    with pytest.raises(cc.ClientError):
        cc.CtlClient(demo, k)
    assert cc.check_config(cc.Config(host="127.0.0.1"), k) == []


def test_x_a_demo_window_is_refused_when_profile_2_has_no_run_window(cc, cf, tmp_path):
    k = _contract_with(cf, tmp_path, (P2_ROW_END, '"run_window_max_ms": None, "compiled": True}'))
    assert [p for p in cc.check_config(cc.Config(host="127.0.0.1", demo=(0, 100)), k) if "run_window_max_ms" in p]


@pytest.mark.parametrize("kw", [dict(port=7151), dict(stamp=True), dict(injections=((5, "nan"), (9, "speed"))),
                                dict(pause=(3, 1500)), dict(demo=(0, 30000)), dict(port=7150, profile=1)])
def test_the_configs_accepted(cc, K, kw):
    assert cc.check_config(cc.Config(host="127.0.0.1", **kw), K) == []


def test_a_stamp_target_is_the_stamp_port_or_one_marked_stamp(cc):
    assert cc.Config(host="h", port=7151).is_stamp() and cc.Config(host="h", port=7150, stamp=True).is_stamp()
    assert not cc.Config(host="h", port=7150).is_stamp()


@pytest.mark.parametrize("mode", list(INJECTION_REASONS))
def test_each_injection_gives_its_designed_reason(cc, cr, cf, K, mpm, mode):
    clk = Clock()
    c = client(cc, K, clock=clk, injections=((1, mode),))
    c.offer(*honest(cc, clk))
    f = c.queued.frame
    ref = client(cc, K, clock=Clock())
    ref.offer(*honest(cc, Clock()))
    clean = ref.queued.frame
    assert cr.judge(clean, K, m_per_mm=mpm) == (0, 0)
    if mode == "kind9":
        assert f[H + 24] == 9 and f[:H + 24] + f[H + 25:] == clean[:H + 24] + clean[H + 25:]
    else:
        assert cr.judge(f, K, m_per_mm=mpm) == (1, INJECTION_REASONS[mode])
    assert c.n["injected"] == 1
    closed_out(cc, c)
    closed_out(cc, ref)


def test_an_injection_at_a_later_seq_leaves_the_others_honest(cc, cr, cf, K, mpm):
    clk = Clock()
    c = client(cc, K, clock=clk, injections=((2, "speed"),))
    got = []
    for i in range(3):
        clk.advance(ms=30)
        c.offer(*honest(cc, clk, stamp_ms=30 * i))
        got.append(cr.judge(c.queued.frame, K, m_per_mm=mpm))
    assert got == [(0, 0), (1, 12), (0, 0)]
    closed_out(cc, c)


def _aw_ctl(cc, clk, v=2.0):
    """A Control as Autoware's gate sends it: every is_defined flag false, numbers in the fields (spec-2 W4 G9)."""
    return cc.Control(stamp_ns=T0, recv_ns=clk(), velocity=v, acceleration=-1.5, is_defined_acceleration=False, jerk=0.3,
                      is_defined_jerk=False, steering_tire_angle=0.05, steering_tire_rotation_rate=0.01,
                      is_defined_steering_tire_rotation_rate=False)


@pytest.mark.parametrize("odom", ["fresh", "absent"])
@pytest.mark.parametrize("v", [2.0, 0.0, -1.0])
@pytest.mark.parametrize("mode", list(INJECTION_REASONS))
def test_x_each_injection_gives_its_reason_on_autowares_honest_traffic(cc, cr, K, mpm, mode, v, odom):
    """The value injections for 13, 14 and 16 must set their own is_defined flag, and 17, 18 and 19 the odometry flag
    (b3), whatever the Control and the odometry were: honest traffic with every flag clear, no odometry at all, and a
    command that reverses give each injection its designed reason."""
    clk = Clock()
    c = client(cc, K, clock=clk, injections=((1, mode),))
    c.offer(_aw_ctl(cc, clk, v=v), cc.Odometry(v=v, recv_ns=clk()) if odom == "fresh" else None)
    f = c.queued.frame
    if mode == "kind9":
        assert f[H + 24] == 9
    else:
        assert cr.judge(f, K, m_per_mm=mpm) == (1, INJECTION_REASONS[mode])
    closed_out(cc, c)


@pytest.mark.parametrize("steer_max", ["0.6", "0.8", "0.3", "0.55", "0.7", "0.45"])
def test_the_lat_accel_injection_gives_17_for_a_steer_max_not_exact_in_binary32(cc, cr, cf, tmp_path, mpm, steer_max):
    """The loader takes a compiled steer_max that binary32 cannot carry (generate.py will refuse one; spec-2 2.3). The
    injection's delta is the largest binary32 not above steer_max, so rule 15 stays quiet whichever way steer_max
    rounds (0.6, 0.8, 0.3 and 0.55 round up, 0.7 and 0.45 down) and the frame gets 17."""
    sm = float(steer_max)
    assert cf.f32(sm) != sm
    k = _contract_with(cf, tmp_path, (P1_STEER_MAX, P1_STEER_MAX.replace('"steer_max": 1.0', '"steer_max": ' + steer_max)))
    clk = Clock()
    c = cc.CtlClient(cc.Config(host="127.0.0.1", port=1, injections=((1, "lat-accel"),)), k, clock=clk)
    c.offer(*honest(cc, clk))
    assert cr.judge(c.queued.frame, k, m_per_mm=mpm) == (1, 17)
    d = cf.decode_request(c.queued.frame).delta
    assert d <= sm < cf.f32_next_up(d)
    closed_out(cc, c)


def test_a_rolling_back_injection_is_refused_when_rule_18_would_come_first(cc, cr, cf, tmp_path, mpm):
    """The rolling-back injection packs v_meas = -(ROLLBACK_V + INJECT_MARGIN_MPS) as binary32 with v_cmd >= 0. At v_cmd 0
    rule 18's threshold is OVERSPEED_MARGIN, so a contract whose margin is under that |v_meas| as packed would give 18,
    not 19: the client refuses the injection at start (the other injections stay accepted). The comparison is with the
    binary32 packed (ROLLBACK_V 0.1 and margin 1.1: 0.1 + 1.0 == 1.1 in double, but binary32 1.1 is above 1.1). At a
    margin equal to it the injection gives 19, whatever v_cmd."""
    inj = cc.Config(host="127.0.0.1", port=1, injections=((1, "rolling-back"),))
    edge = 0.5 + cc.INJECT_MARGIN_MPS                            # the fixture's ROLLBACK_V is 0.5
    for pairs in ([("OVERSPEED_MARGIN = 2.0", "OVERSPEED_MARGIN = 1.0")],
                  [("OVERSPEED_MARGIN = 2.0", "OVERSPEED_MARGIN = 1.1"), ("ROLLBACK_V = 0.5", "ROLLBACK_V = 0.1")]):
        k = _contract_with(cf, tmp_path, *pairs)
        assert [p for p in cc.check_config(inj, k) if "rolling-back" in p], pairs
        with pytest.raises(cc.ClientError):
            cc.CtlClient(inj, k)
        for mode in INJECTION_REASONS:
            if mode != "rolling-back":
                assert cc.check_config(cc.Config(host="127.0.0.1", port=1, injections=((1, mode),)), k) == [], mode
        # what the refusal keeps out: at v_cmd 0 the packed v_meas trips 18
        v_meas = -cf.f32(k.ROLLBACK_V + cc.INJECT_MARGIN_MPS)
        assert cr.judge(frame(cf, delta=0.0, v_cmd=0.0, v_meas=v_meas), k, m_per_mm=mpm) == (1, 18)
    k = _contract_with(cf, tmp_path, ("OVERSPEED_MARGIN = 2.0", "OVERSPEED_MARGIN = %r" % edge))
    assert k.OVERSPEED_MARGIN == edge and cc.check_config(inj, k) == []
    for v in (0.0, -0.0, 0.3, 2.0, -2.0):
        clk = Clock()
        c = cc.CtlClient(inj, k, clock=clk)
        c.offer(ctl(cc, recv_ns=clk(), v=v), None)
        assert cr.judge(c.queued.frame, k, m_per_mm=mpm) == (1, 19), v
        closed_out(cc, c)


F32_MAX = 3.4028234663852886e38       # the largest finite binary32
F32_TINY = 2.0 ** -149                # the smallest binary32 above 0
INJ_ROW1 = ('    1: {"l_mm": 2790, "v_max": 25.0, "a_max": 5.0, "jerk_max": 80.0, "steer_max": 1.0, "steer_rate_max": 1.0,\n'
            '        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": True},')
INJ_ROW2 = ('    2: {"l_mm": 2790, "v_max": 3.0, "a_max": 5.0, "jerk_max": 80.0, "steer_max": 1.0, "steer_rate_max": 1.0,\n'
            '        "lat_acc_max": 5.0, "run_window_max_ms": 30000, "compiled": True},')


def _row1(old, new):
    """Profile 1's row of the fixture contract with one of its values replaced, as an (old, new) pair for _contract_with."""
    assert INJ_ROW1.count(old) == 1, old
    return INJ_ROW1, INJ_ROW1.replace(old, new)


NO_DELTA = "leaves no binary32 delta above 0"
NO_ABOVE = "leaves no binary32 above the limit"
NO_V18 = "not beyond rule 18's threshold"
NO_V19 = "not below rule 19's threshold"
# (name, the fixture's edits, {each injection the contract then leaves no frame for: what its refusal says})
INJ_VARIANTS = [
    ("steer_max 1e-46", [_row1('"steer_max": 1.0', '"steer_max": 1e-46')], {"steer": NO_ABOVE, "lat-accel": NO_DELTA}),
    ("steer_max 1e-45", [_row1('"steer_max": 1.0', '"steer_max": 1e-45')], {"lat-accel": NO_DELTA}),
    ("steer_max 2**-149", [_row1('"steer_max": 1.0', '"steer_max": %r' % F32_TINY)], {}),
    ("lat_acc_max 1e300", [_row1('"lat_acc_max": 5.0', '"lat_acc_max": 1e300')], {"lat-accel": "beyond binary32"}),
    ("TOL17 the negative of lat_acc_max", [("TOL17 = 0.5", "TOL17 = -5.0")], {"lat-accel": "lat_acc_max + TOL17 = 0.0"}),
    ("v_max 3e38", [_row1('"v_max": 25.0', '"v_max": 3e38')], {"speed": NO_ABOVE}),
    ("a_max 1e-46", [_row1('"a_max": 5.0', '"a_max": 1e-46')], {"accel": NO_ABOVE}),
    ("a_max 2**-149", [_row1('"a_max": 5.0', '"a_max": %r' % F32_TINY)], {}),
    ("jerk_max the largest binary32", [_row1('"jerk_max": 80.0', '"jerk_max": %r' % F32_MAX)], {"jerk": NO_ABOVE}),
    ("steer_rate_max 1e-46", [_row1('"steer_rate_max": 1.0', '"steer_rate_max": 1e-46')], {"steer-rate": NO_ABOVE}),
    ("OVERSPEED_MARGIN 1e39", [("OVERSPEED_MARGIN = 2.0", "OVERSPEED_MARGIN = 1e39")], {"overspeed": NO_V18}),
    ("OVERSPEED_FACTOR infinite", [("OVERSPEED_FACTOR = 1.2", 'OVERSPEED_FACTOR = float("inf")')], {"overspeed": NO_V18}),
    ("ROLLBACK_V 1e9 + 0.1 under a margin of 1e10", [("ROLLBACK_V = 0.5", "ROLLBACK_V = 1000000000.1"),
                                                    ("OVERSPEED_MARGIN = 2.0", "OVERSPEED_MARGIN = 1e10")],
     {"rolling-back": NO_V19, "overspeed": NO_V18}),
    ("ROLLBACK_V 1e39 under an infinite margin", [("ROLLBACK_V = 0.5", "ROLLBACK_V = 1e39"),
                                                 ("OVERSPEED_MARGIN = 2.0", 'OVERSPEED_MARGIN = float("inf")')],
     {"rolling-back": NO_V19, "overspeed": NO_V18}),
]


@pytest.mark.parametrize("pairs,refused", [v[1:] for v in INJ_VARIANTS], ids=[v[0] for v in INJ_VARIANTS])
def test_x_an_injection_is_refused_at_start_unless_the_contract_leaves_a_frame_with_its_reason(cc, cr, cf, tmp_path, mpm, pairs,
                                                                                               refused):
    """The loader takes any positive limit and any number as a constant, so a contract can leave an injection no frame
    that carries its designed reason: a steer_max below the smallest binary32 above 0 packs delta 0 and the lat-accel
    injection divides by tan(0); 1.5 times a limit can leave binary32 at either end; a constant can put rule 18's or
    19's threshold out of reach. check_config refuses such an injection at start, for a Control at rest (v_cmd 0,
    delta 0, no optional field, no odometry); every injection it accepts packs a frame that gets its reason, and offer()
    never raises for one (in the node it would raise inside the ROS callback). The smallest binary32 as a limit still
    leaves a frame: refusing it would be a refusal too many. Each refusal says why (what an operator reads at start)."""
    k = _contract_with(cf, tmp_path, *pairs)
    for mode in INJECTION_REASONS:
        cfg = cc.Config(host="127.0.0.1", port=1, injections=((1, mode),))
        problems = cc.check_config(cfg, k)
        if mode in refused:
            mine = [p for p in problems if p.startswith("the %s injection with profile 1:" % mode)]
            assert len(mine) == 1 and refused[mode] in mine[0], (mode, problems)
            with pytest.raises(cc.ClientError):
                cc.CtlClient(cfg, k)
            continue
        assert problems == [], (mode, problems)
        clk = Clock()
        c = cc.CtlClient(cfg, k, clock=clk)
        assert c.offer(ctl(cc, recv_ns=clk(), v=0.0, d=0.0), None) == 1
        f = c.queued.frame
        if mode == "kind9":
            assert f[H + 24] == 9
        else:
            assert cr.judge(f, k, m_per_mm=mpm) == (1, INJECTION_REASONS[mode]), mode
        closed_out(cc, c)


def test_x_an_injection_is_held_to_profile_2_only_when_a_demo_window_may_send_it(cc, cf, tmp_path):
    """An injection takes the profile of the frame it lands in, profile 2 inside the demo window: with a window set,
    check_config holds it to profile 2's row too, and without one it does not."""
    k = _contract_with(cf, tmp_path, (INJ_ROW2, INJ_ROW2.replace('"steer_max": 1.0', '"steer_max": 1e-46')))
    for mode, why in (("steer", NO_ABOVE), ("lat-accel", NO_DELTA)):
        assert cc.check_config(cc.Config(host="127.0.0.1", port=1, injections=((1, mode),)), k) == [], mode
        demo = cc.Config(host="127.0.0.1", port=1, demo=(0, 100), injections=((1, mode),))
        assert [p for p in cc.check_config(demo, k) if p.startswith("the %s injection with profile 2:" % mode) and why in p], mode
        with pytest.raises(cc.ClientError):
            cc.CtlClient(demo, k)


@pytest.mark.parametrize("dt,refused", [("200.5", True), ("-5", True), ("65535", True), ("65534", False)])
def test_x_an_interval_injection_is_refused_unless_dt_max_ms_is_an_int_below_0xffff(cc, cr, cf, tmp_path, mpm, dt, refused):
    """The interval injection packs DT_MAX_MS + 1 into the u16 at p[45..46]. A DT_MAX_MS that is not an int (the C header
    writes it %du), is negative, or is 0xFFFF leaves no such interval, and offer() would raise: check_config refuses
    it at start. 0xFFFE leaves 0xFFFF, which gets 11."""
    k = _contract_with(cf, tmp_path, ("DT_MAX_MS = 200", "DT_MAX_MS = " + dt))
    cfg = cc.Config(host="127.0.0.1", port=1, injections=((1, "interval"),))
    if refused:
        assert [p for p in cc.check_config(cfg, k) if p.startswith("the interval injection with profile 1: DT_MAX_MS %s " % dt)]
        with pytest.raises(cc.ClientError):
            cc.CtlClient(cfg, k)
        return
    assert cc.check_config(cfg, k) == []
    clk = Clock()
    c = cc.CtlClient(cfg, k, clock=clk)
    c.offer(ctl(cc, recv_ns=clk(), v=0.0, d=0.0), None)
    assert cf.decode_request(c.queued.frame).interval_ms == 0xFFFF and cr.judge(c.queued.frame, k, m_per_mm=mpm) == (1, 11)
    closed_out(cc, c)


def test_x_an_overspeed_injection_packs_a_v_meas_beyond_binary32_as_an_infinity(cc, cr, cf, K, mpm):
    """overspeed's v_meas is OVERSPEED_FACTOR x |v_cmd| + OVERSPEED_MARGIN + INJECT_MARGIN_MPS, so a Control whose v_cmd is
    the largest binary32 puts it beyond binary32: a value only the Control decides, which no start-up check can refuse.
    The frame packs an infinity there, as an honest value beyond binary32 is packed (the monitor answers 9), and
    offer() does not raise."""
    clk = Clock()
    c = client(cc, K, clock=clk, injections=((1, "overspeed"),))
    assert c.offer(ctl(cc, recv_ns=clk(), v=F32_MAX, d=0.0), None) == 1
    f = c.queued.frame
    assert cf.fields_of(f)["v_meas"] == math.inf and cr.judge(f, K, m_per_mm=mpm) == (1, 9)
    closed_out(cc, c)


def test_x_a_rolling_back_injection_is_refused_when_its_v_meas_rounds_to_the_threshold(cc, cf, tmp_path):
    """ROLLBACK_V 2**25 is exact in binary32 and -(ROLLBACK_V + 1.0) rounds to -ROLLBACK_V, which rule 19 (strict) does
    not reject: the injection is refused at start (OVERSPEED_MARGIN 1e8 keeps the rule-18 refusal out of it)."""
    k = _contract_with(cf, tmp_path, ("ROLLBACK_V = 0.5", "ROLLBACK_V = 33554432.0"), ("OVERSPEED_MARGIN = 2.0", "OVERSPEED_MARGIN = 1e8"))
    problems = cc.check_config(cc.Config(host="127.0.0.1", port=1, injections=((1, "rolling-back"),)), k)
    assert [p for p in problems if p.startswith("the rolling-back injection with profile 1:") and NO_V19 in p], problems


def test_x_a_limit_too_large_for_a_float_is_a_refusal_not_an_exception(cc, cf, tmp_path):
    """The loader takes any positive int as l_mm; one no float can hold leaves the lat-accel injection no frame, and
    check_config says so (an ArithmeticError caught) instead of raising."""
    k = _contract_with(cf, tmp_path, _row1('"l_mm": 2790', '"l_mm": 10 ** 400'))
    problems = cc.check_config(cc.Config(host="127.0.0.1", port=1, injections=((1, "lat-accel"),)), k)
    assert [p for p in problems if p.startswith("the lat-accel injection with profile 1:")], problems


# ============================================================ 2.6: the verdict message

def _counters(**kw):
    n = dict(packed=5, replied=3, accepted=2, rejected=1, drop=1, lost_on_reconnect=1, reconnects=0)
    n.update(kw)
    return n


def test_the_verdict_message_of_a_replied_frame(cc, cf):
    f = cf.encode(seq=7, tstamp_ns=0, flags=0x05, profile=1, v_cmd=2.5, delta=-0.1, accel=0.5, rate=0.25, interval_ms=31)
    s = cc.verdict_message(seq=7, frame=f, verdict=1, reason=12, counters=_counters(), connected=True)
    assert s.isascii() and len(s.encode()) <= 1024 and ", " not in s and ": " not in s
    o = strict_json(s)
    assert list(o) == MESSAGE_KEYS
    assert o == {"v": 1, "seq": 7, "profile": 1, "v_cmd": 2.5, "acc": 0.5, "jerk": None, "steer": cf.f32(-0.1),
                 "steer_rate": 0.25, "interval_ms": 31, "verdict": 1, "reason": 12, "packed": 5, "replied": 3,
                 "accepted": 2, "rejected": 1, "dropped": 1, "lost_on_reconnect": 1, "reconnects": 0, "connected": True}
    assert s == json.dumps(o, separators=(",", ":"))


def test_the_verdict_message_of_a_drop_a_loss_and_a_connection_change(cc, cf):
    f = cf.encode(seq=4, tstamp_ns=0, flags=0, profile=2, v_cmd=1.0, delta=0.0)
    o = strict_json(cc.verdict_message(seq=4, frame=f, verdict=None, reason=None, counters=_counters(), connected=False))
    assert (o["seq"], o["verdict"], o["reason"], o["acc"], o["jerk"], o["steer_rate"], o["profile"]) == (4, None, None, None, None, None, 2)
    o = strict_json(cc.verdict_message(seq=0, frame=None, verdict=None, reason=None, counters=_counters(reconnects=2),
                                       connected=True))
    assert list(o) == MESSAGE_KEYS
    assert {k: o[k] for k in MESSAGE_KEYS[1:11]} == {"seq": 0, "profile": 0, "v_cmd": None, "acc": None, "jerk": None,
                                                     "steer": None, "steer_rate": None, "interval_ms": 0,
                                                     "verdict": None, "reason": None}
    assert (o["reconnects"], o["connected"]) == (2, True)


@pytest.mark.parametrize("bits", [NAN_BITS, 0x7F800000, 0xFF800000, 0x7F800001])
def test_a_non_finite_value_reaches_the_message_as_null(cc, cf, bits):
    f = cf.pack_bits(seq=2, tstamp_ns=0, flags=0x0F, profile=1, v_cmd=bits, delta=bits, accel=bits, jerk=bits, rate=bits,
                     v_meas=cf.f32_bits(1.0))
    s = cc.verdict_message(seq=2, frame=f, verdict=1, reason=9, counters=_counters(), connected=True)
    o = strict_json(s)
    assert (o["v_cmd"], o["acc"], o["jerk"], o["steer"], o["steer_rate"]) == (None,) * 5
    assert "NaN" not in s and "Infinity" not in s


def test_an_injected_layout_fault_reaches_the_message_by_its_flags(cc, cf):
    f = bytearray(cf.encode(seq=2, tstamp_ns=0, flags=0, profile=1, v_cmd=1.0, delta=0.0))
    struct.pack_into("<f", f, H + 25, 1.0)                     # acceleration bytes with b0 clear
    f[H + 24] = 9
    o = strict_json(cc.verdict_message(seq=2, frame=bytes(f), verdict=1, reason=5, counters=_counters(), connected=True))
    assert (o["acc"], o["v_cmd"], o["reason"]) == (None, 1.0, 5)


def test_the_verdict_message_refuses_a_connection_change_with_a_seq(cc):
    with pytest.raises(ValueError):
        cc.verdict_message(seq=3, frame=None, verdict=None, reason=None, counters=_counters(), connected=True)


# ============================================================ the reply log and its header

def test_the_reply_log_header_and_records(cc, cf, K, tmp_path):
    log = tmp_path / "replies.jsonl"
    clk = Clock()
    c = client(cc, K, clock=clk, reply_log=log, injections=((3, "nan"),), pause=(5, 100), demo=(1000, 2000))
    c.offer(ctl(cc), None)
    clk.advance(ms=30)
    c.offer(ctl(cc, stamp_ms=30), None)
    clk.advance(ms=5)
    closed_out(cc, c)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "\r" not in log.read_text(encoding="utf-8")
    objs = [strict_json(x) for x in lines]
    h = objs[0]["header"]
    want = {"format": 1, "kind": 2, "mode": "node", "target": "127.0.0.1:1", "stamp": False, "profile": 1,
            "demo": {"profile": 2, "start_ms": 1000, "duration_ms": 2000}, "injections": [{"seq": 3, "mode": "nan"}],
            "pause": {"after_seq": 5, "duration_ms": 100}, "contract_sha256": hashlib.sha256(CONTRACT_FILE.read_bytes()).hexdigest(),
            "digest": K.DIGEST}
    assert {k: h[k] for k in want} == want
    recs = objs[1:-1]
    assert [set(r) for r in recs] == [{"seq", "frame", "outcome", "verdict", "reason", "mono_ns"}] * 2
    assert [(r["seq"], r["outcome"], r["verdict"], r["reason"]) for r in recs] == [(1, "drop", None, None), (2, "drop", None, None)]
    assert bytes.fromhex(recs[1]["frame"])[:8] == struct.pack("<Q", 2) and len(recs[1]["frame"]) == 128
    # the client's clock at each outcome, not at the pack: seq 1 (packed at T0) dropped when seq 2 replaced it, and
    # seq 2 (packed at T0 + 30 ms) dropped at the stop
    assert [r["mono_ns"] for r in recs] == [T0 + 30 * MS, T0 + 35 * MS]
    assert objs[-1]["summary"]["identity"]["holds"] is True


def test_the_reply_log_is_never_overwritten(cc, K, tmp_path):
    log = tmp_path / "replies.jsonl"
    log.write_text("x\n", encoding="utf-8")
    with pytest.raises(cc.ClientError):
        client(cc, K, reply_log=log)
    assert log.read_text(encoding="utf-8") == "x\n"


def test_x_the_header_says_stamp_for_the_stamp_port(cc, K, tmp_path):
    log = tmp_path / "replies.jsonl"
    c = cc.CtlClient(cc.Config(host="127.0.0.1", port=7151), K, clock=Clock(), reply_log=log)
    closed_out(cc, c)
    h = json.loads(log.read_text(encoding="utf-8").splitlines()[0])["header"]
    assert (h["stamp"], h["target"]) == (True, "127.0.0.1:7151")


# ============================================================ the connection rules, against a peer on loopback

def test_no_connect_before_the_first_control(cc, K, monitor):
    mon = monitor()
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        c.wait(0.02)
    assert mon.accepts == 0 and c.n["connects"] == 0
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["replied"] == 1)
    assert mon.accepts == 1 and c.n["connects"] == 1 and c.n["reconnects"] == 0
    closed_out(cc, c)


def test_the_reconnect_is_lazy_after_the_monitor_closes_an_idle_connection(cc, K, monitor):
    msgs = []
    mon = monitor(idle_close_s=0.15)
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns, sink=msgs.append)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["replied"] == 1)
    assert settle(c, lambda: not c.connected)               # the client sees the close while it waits
    end = time.monotonic() + 0.6
    while time.monotonic() < end:
        c.wait(0.02)
    assert mon.accepts == 1                                 # a silence: no reconnect
    c.offer(ctl(cc, stamp_ms=900), None)
    assert settle(c, lambda: c.n["replied"] == 2)
    assert mon.accepts == 2 and c.n["reconnects"] == 1 and c.n["lost_on_reconnect"] == 0
    closed_out(cc, c)
    conn = [o["connected"] for o in message_objs(msgs) if o["seq"] == 0]
    assert conn == [True, False, True, False]


def test_a_close_seen_only_by_the_peer_check_reconnects_before_the_send(cc, K, monitor):
    """The monitor replies and closes; the client has read the reply but not yet the close when the next Control comes.
    The non-blocking MSG_PEEK before the send finds the close, so the frame goes out on a new connection and is replied,
    never written into the dead one and lost."""
    mon = monitor(script=lambda ci, fi, f: ["reply", "close"])
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["replied"] == 1)
    assert wait_for(lambda: mon.ended(0) == "closed")
    time.sleep(0.05)
    assert c.connected                                      # not yet noticed
    checks = c.n["peer_checks"]
    c.offer(ctl(cc, stamp_ms=30), None)
    c.pump()
    assert settle(c, lambda: c.n["replied"] == 2)
    assert c.n["lost_on_reconnect"] == 0 and mon.accepts == 2 and c.n["peer_checks"] > checks
    closed_out(cc, c)


def test_one_request_outstanding_and_the_replaced_frame_is_a_drop(cc, K, monitor):
    release = threading.Event()

    def script(ci, fi, f):
        if fi == 0:
            release.wait(SLACK_S)
        return "reply"
    mon = monitor(script=script)
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: len(mon.frames()) == 1)
    c.offer(ctl(cc, stamp_ms=30), None)
    for _ in range(10):
        c.wait(0.01)
    assert len(mon.frames()) == 1 and c.n["sends"] == 1 and c.queued.seq == 2
    c.offer(ctl(cc, stamp_ms=60), None)
    assert c.n["drop"] == 1 and c.queued.seq == 3
    release.set()
    assert settle(c, lambda: c.n["replied"] == 2)
    assert mon.seqs() == [1, 3]
    closed_out(cc, c)
    assert (c.n["replied"], c.n["drop"], c.n["lost_on_reconnect"]) == (2, 1, 0)


def test_a_frame_in_flight_when_the_monitor_closes_is_lost(cc, K, monitor, tmp_path):
    msgs = []
    log = tmp_path / "replies.jsonl"
    mon = monitor(script=lambda ci, fi, f: "close")
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns, sink=msgs.append, reply_log=log)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["lost_on_reconnect"] == 1)
    assert c.n["replied"] == 0 and not c.connected and len(mon.frames()) == 1
    closed_out(cc, c)
    objs = message_objs(msgs)
    assert [(o["seq"], o["verdict"], o["connected"], o["lost_on_reconnect"]) for o in objs] == \
        [(0, None, True, 0), (1, None, False, 1), (0, None, False, 1)]
    recs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()[1:-1]]
    assert [(r["seq"], r["outcome"]) for r in recs] == [(1, "lost")]


def test_the_reply_timeout_closes_and_counts_the_frame_lost(cc, K, monitor):
    clk = Clock()
    mon = monitor(script=lambda ci, fi, f: "none")
    c = client(cc, K, port=mon.port, clock=clk)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["sends"] == 1)
    clk.advance(ms=499)
    c.pump()
    assert c.connected and c.n["lost_on_reconnect"] == 0 and c.outstanding is not None
    clk.advance(ms=1)
    c.pump()
    assert not c.connected and c.n["lost_on_reconnect"] == 1 and c.n["reply_timeouts"] == 1
    assert wait_for(lambda: mon.ended(0) == "eof")           # the monitor sees the client close it
    for _ in range(5):
        c.wait(0.01)
    assert mon.accepts == 1                                 # and nothing reconnects until a frame is queued
    closed_out(cc, c)


def test_x_the_reply_timeout_runs_from_the_send(cc, K, monitor):
    """A frame packed while no connection is open waits in the queue; its 500 ms run from the send, not from the pack."""
    clk = Clock()
    mon = monitor(script=lambda ci, fi, f: "none")
    c = client(cc, K, port=mon.port, clock=clk)
    c.offer(ctl(cc), None)
    clk.advance(ms=400)                                         # packed at T0, sent at T0 + 400 ms
    assert settle(c, lambda: c.n["sends"] == 1)
    clk.advance(ms=499)
    c.pump()
    assert c.outstanding is not None and c.n["lost_on_reconnect"] == 0
    clk.advance(ms=1)
    c.pump()
    assert c.n["lost_on_reconnect"] == 1 and c.n["reply_timeouts"] == 1
    closed_out(cc, c)


def test_the_backoff_doubles_from_100_ms_to_a_2_s_cap(cc):
    b = cc.Backoff()
    assert [b.next_ns() // MS for _ in range(8)] == [100, 200, 400, 800, 1600, 2000, 2000, 2000]
    b.reset()
    assert b.next_ns() == 100 * MS


def test_a_failed_connect_backs_off_before_the_next_attempt(cc, K):
    clk = Clock()
    c = client(cc, K, port=free_port(), clock=clk)
    c.offer(ctl(cc), None)
    c.pump()
    assert settle(c, lambda: c.n["connect_failures"] == 1)
    for k, wait_ms in enumerate((100, 200, 400, 800, 1600, 2000, 2000), start=1):
        assert c.next_connect_ns == clk() + wait_ms * MS
        clk.advance(ms=wait_ms - 1)
        for _ in range(3):
            c.wait(0.01)
        assert c.n["connect_failures"] == k                 # not before the backoff is over
        clk.advance(ms=1)
        c.pump()
        assert settle(c, lambda k=k: c.n["connect_failures"] == k + 1)
    assert c.n["connects"] == 0
    closed_out(cc, c)
    assert c.n["drop"] == 1


def test_x_a_connect_resets_the_backoff(cc, K):
    """2.1's backoff starts again from 100 ms after a connect (the bridge's Backoff, reset by a connect): a guest that
    goes away again after a long outage is retried within 100 ms of the next failure, not 2 s."""
    c = client(cc, K)
    for _ in range(6):
        c.backoff.next_ns()
    s1, s2 = socket.socketpair()
    try:
        c._connected(s1)
        assert c.backoff.next_ns() == 100 * MS
    finally:
        c._close("test")
        s2.close()
    closed_out(cc, c)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="a full accept queue keeps a connect pending on Linux")
def test_a_connect_that_does_not_complete_is_abandoned_at_the_connect_timeout(cc, K):
    lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lst.bind(("127.0.0.1", 0))
    lst.listen(0)
    port = lst.getsockname()[1]
    fill = []
    try:
        for _ in range(4):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setblocking(False)
            s.connect_ex(("127.0.0.1", port))
            fill.append(s)
        time.sleep(0.1)
        clk = Clock()
        c = client(cc, K, port=port, clock=clk)
        c.offer(ctl(cc), None)
        c.pump()
        for _ in range(5):
            c.wait(0.02)
        if c.n["connects"]:
            pytest.skip("this kernel completed the connect despite the full accept queue")
        assert c.n["connect_failures"] == 0
        clk.advance(ms=499)
        c.pump()
        assert c.n["connect_failures"] == 0
        clk.advance(ms=1)
        c.pump()
        assert c.n["connect_failures"] == 1 and c.next_connect_ns == clk() + 100 * MS
        closed_out(cc, c)
    finally:
        for s in fill:
            s.close()
        lst.close()


def test_an_invalid_reply_loses_the_frame_and_closes(cc, K, monitor):
    def script(ci, fi, f):
        b = bytearray(FakeMonitor.answer(f))
        b[H + 30] ^= 0x01                                   # a byte the monitor never writes
        return [("raw", bytes(b))]
    mon = monitor(script=script)
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc, j=1.0), None)
    assert settle(c, lambda: c.n["lost_on_reconnect"] == 1)
    assert c.n["reply_invalid"] == 1 and c.n["replied"] == 0 and not c.connected
    closed_out(cc, c)


@pytest.mark.parametrize("vr", [(1, 0), (0, 12), (2, 5)], ids=["reject-ok", "accept-ctl-speed", "verdict-2"])
def test_x_a_reply_with_an_inconsistent_verdict_and_reason_is_invalid(cc, K, monitor, vr):
    """Every other byte of the reply is the request's; only a verdict and a reason that do not belong together (a
    reject with 0, an accept with a reason, a verdict that is neither) make it invalid: the frame is lost, not counted
    as replied, and the connection closed."""
    def script(ci, fi, f):
        b = bytearray(f)
        b[H + 6], b[H + 7] = vr
        return [("raw", bytes(b))]
    mon = monitor(script=script)
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["lost_on_reconnect"] + c.n["replied"] == 1)
    assert (c.n["reply_invalid"], c.n["replied"], c.n["lost_on_reconnect"]) == (1, 0, 1)
    assert not c.connected
    closed_out(cc, c)


@pytest.mark.parametrize("off", [0, 8], ids=["seq", "tstamp"])
def test_x_a_reply_whose_header_is_not_the_requests_is_invalid(cc, K, monitor, off):
    """seq and tstamp bind a reply to its request (ipc-test/common/frame.h): a reply carrying another seq or tstamp is
    reply_invalid, the outstanding frame lost and the connection closed, never counted as that frame's reply."""
    def script(ci, fi, f):
        b = bytearray(FakeMonitor.answer(f))
        b[off] ^= 0x01
        return [("raw", bytes(b))]
    mon = monitor(script=script)
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["lost_on_reconnect"] + c.n["replied"] == 1)
    assert (c.n["reply_invalid"], c.n["replied"], c.n["lost_on_reconnect"]) == (1, 0, 1)
    assert not c.connected
    closed_out(cc, c)


def test_x_a_reply_in_two_segments_is_one_reply(cc, K):
    """A reply that arrives in two reads (TCP may split it) is put together, not taken as invalid."""
    ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ls.bind(("127.0.0.1", 0))
    ls.listen(1)
    done = threading.Event()

    def peer():
        s, _a = ls.accept()
        f = b""
        while len(f) < 64:
            f += s.recv(64 - len(f))
        r = FakeMonitor.answer(f)
        s.sendall(r[:30])
        time.sleep(0.1)
        s.sendall(r[30:])
        done.wait(SLACK_S)
        s.close()
    t = threading.Thread(target=peer, daemon=True)
    t.start()
    try:
        c = client(cc, K, port=ls.getsockname()[1], clock=time.monotonic_ns)
        c.offer(ctl(cc), None)
        assert settle(c, lambda: c.n["replied"] + c.n["lost_on_reconnect"] == 1)
        assert (c.n["replied"], c.n["reply_invalid"]) == (1, 0)
        closed_out(cc, c)
    finally:
        done.set()
        t.join(SLACK_S)
        ls.close()


class _FailingSend:
    """The client's connected socket with its send failing (EPIPE) or short (10 bytes); the peer check and close pass."""

    def __init__(self, s, short):
        self._s, self._short = s, short

    def send(self, data):
        if self._short:
            return 10
        raise OSError(errno.EPIPE, "broken pipe")

    def recv(self, n, flags=0):
        raise BlockingIOError()

    def close(self):
        self._s.close()

    def fileno(self):
        return self._s.fileno()


@pytest.mark.parametrize("short", [False, True], ids=["epipe", "short-send"])
def test_x_a_send_that_fails_loses_its_frame_and_keeps_the_identity(cc, K, monitor, short):
    mon = monitor()
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["replied"] == 1)
    c._sock = _FailingSend(c._sock, short)
    c.offer(ctl(cc, stamp_ms=30), None)
    c.pump()
    assert (c.n["lost_on_reconnect"], c.connected) == (1, False)
    assert c.outstanding is None and c.queued is None
    closed_out(cc, c)


def test_stray_bytes_with_nothing_outstanding_close_the_connection(cc, K, monitor):
    mon = monitor(script=lambda ci, fi, f: ["reply", "reply"])
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["replied"] == 1)
    assert settle(c, lambda: not c.connected)
    assert c.n["stray_bytes"] > 0 and c.n["lost_on_reconnect"] == 0
    closed_out(cc, c)


def _stamped(f):
    b = bytearray(FakeMonitor.answer(f))
    b[H + 8:H + 24] = struct.pack("<QQ", 1111, 2222)
    return [("raw", bytes(b))]


def test_a_stamp_target_takes_the_stamps_and_logs_them(cc, K, monitor, tmp_path):
    mon = monitor(script=lambda ci, fi, f: _stamped(f))
    log = tmp_path / "replies.jsonl"
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns, stamp=True, reply_log=log)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["replied"] == 1)
    closed_out(cc, c)
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[1])
    assert (rec["outcome"], rec["t_in_ns"], rec["t_out_ns"]) == ("replied", 1111, 2222)


def test_x_a_stamp_target_takes_stamps_with_every_byte_set(cc, K, monitor, tmp_path):
    """t_in and t_out fill p[8..23] whole: stamps whose top bytes are set (p[15], p[23]) are taken as they are."""
    t_in, t_out = 0x01FFFFFFFFFFFFFF, 0xFF00000000000001

    def script(ci, fi, f):
        b = bytearray(FakeMonitor.answer(f))
        b[H + 8:H + 24] = struct.pack("<QQ", t_in, t_out)
        return [("raw", bytes(b))]
    mon = monitor(script=script)
    log = tmp_path / "replies.jsonl"
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns, stamp=True, reply_log=log)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["replied"] + c.n["lost_on_reconnect"] == 1)
    closed_out(cc, c)
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[1])
    assert (rec["outcome"], rec["t_in_ns"], rec["t_out_ns"]) == ("replied", t_in, t_out)


def test_an_unmarked_target_takes_a_stamped_reply_for_an_invalid_one(cc, K, monitor):
    mon = monitor(script=lambda ci, fi, f: _stamped(f))
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["lost_on_reconnect"] == 1)
    assert c.n["reply_invalid"] == 1 and c.n["replied"] == 0
    closed_out(cc, c)


def test_the_reply_carries_the_monitors_verdict(cc, K, monitor):
    mon = monitor()
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns, injections=((2, "kind9"),))
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["replied"] == 1)
    c.offer(ctl(cc, stamp_ms=30), None)
    assert settle(c, lambda: c.n["replied"] == 2)
    assert (c.n["accepted"], c.n["rejected"], c.last_reply) == (1, 1, (1, 5, 2))
    closed_out(cc, c)


def test_the_stop_drains_the_outstanding_and_the_queued_frame(cc, K, monitor):
    release = threading.Event()

    def script(ci, fi, f):
        if fi == 0:
            release.wait(SLACK_S)
        return "reply"
    mon = monitor(script=script)
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: len(mon.frames()) == 1)
    c.offer(ctl(cc, stamp_ms=30), None)
    threading.Timer(0.1, release.set).start()
    closed_out(cc, c)
    assert (c.n["replied"], c.n["drop"], c.n["lost_on_reconnect"]) == (2, 0, 0) and mon.seqs() == [1, 2]


def test_the_stop_makes_no_new_connection_to_drain(cc, K, monitor):
    """At a stop no new connect: a frame queued while no connection is open (nothing has pumped yet) is a drop, and the
    monitor, listening all along, is never connected to."""
    mon = monitor()
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.offer(ctl(cc), None)
    closed_out(cc, c)
    assert (c.n["connects"], c.n["sends"], c.n["drop"], c.n["replied"]) == (0, 0, 1, 0)
    time.sleep(0.3)                                         # the monitor's accept loop polls every 50 ms
    assert mon.accepts == 0


@pytest.mark.parametrize("drain", [False, True], ids=["no-drain", "drain-on-a-clock-that-stands-still"])
def test_x_a_frame_outstanding_at_the_stop_is_lost(cc, K, monitor, tmp_path, drain):
    """The identity at a stop with a frame still outstanding: without the drain, or when the drain ends on its real-time
    bound before the reply timeout (a clock that stands still), the frame is counted lost and logged so."""
    mon = monitor(script=lambda ci, fi, f: "none")
    log = tmp_path / "replies.jsonl"
    c = client(cc, K, port=mon.port, clock=Clock(), reply_log=log)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["sends"] == 1)
    assert c.outstanding is not None
    closed_out(cc, c, drain=drain)
    assert (c.n["lost_on_reconnect"], c.n["replied"], c.n["drop"]) == (1, 0, 0)
    recs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()[1:-1]]
    assert [(r["seq"], r["outcome"]) for r in recs] == [(1, "lost")]


def test_the_client_on_its_own_thread(cc, K, monitor):
    mon = monitor()
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns)
    c.start()
    try:
        for i in range(10):
            c.offer(ctl(cc, stamp_ms=30 * i), None)
            time.sleep(0.03)
        assert wait_for(lambda: c.n["replied"] + c.n["drop"] == 10)
    finally:
        closed_out(cc, c)
    assert c.n["replied"] >= 1 and mon.accepts == 1


def test_x_the_client_threads_wait_ends_at_the_reply_deadline(cc, K):
    """On its own thread (the node's mode) the loop waits only until the next instant something is due: with a frame
    outstanding, no later than its reply deadline, so the reply timeout fires at 500 ms, not at the loop's longest wait."""
    clk = Clock()
    c = client(cc, K, clock=clk)
    c.outstanding = cc.Packed(seq=1, frame=bytes(64), profile=1, inject=None, demo=False, mono_ns=clk())
    c._reply_due = clk() + 100 * MS
    try:
        assert c._next_due_s() == pytest.approx(0.1)
    finally:
        c.outstanding = None
    closed_out(cc, c)


def test_x_a_fatal_in_the_client_thread_closes_the_connection(cc, K, monitor, capsys):
    """A fault raised inside the thread's loop is recorded (the summary's fatal, exit code 1) and the connection is
    closed with it: nothing pumps the socket after that, so a verdict message must not go on saying connected."""
    mon = monitor()
    msgs = []
    c = client(cc, K, port=mon.port, clock=time.monotonic_ns, sink=msgs.append)
    c.offer(ctl(cc), None)
    assert settle(c, lambda: c.n["replied"] == 1 and c.connected)

    def boom(_timeout_s):
        raise RuntimeError("a fault in the loop")
    c.wait = boom
    c.start()
    assert wait_for(lambda: c.fatal is not None)
    c._thread.join(SLACK_S)
    assert not c._thread.is_alive() and not c.connected
    assert "a fault in the loop" in capsys.readouterr().err
    c.offer(ctl(cc, stamp_ms=30), None)
    c.offer(ctl(cc, stamp_ms=60), None)                         # the first is replaced: a drop message
    assert [(o["seq"], o["verdict"], o["connected"]) for o in message_objs(msgs)] == \
        [(0, None, True), (1, 0, True), (0, None, False), (2, None, False)]
    s = closed_out(cc, c)
    assert s["fatal"] == "RuntimeError: a fault in the loop" and cc.exit_code(s) == 1


class _ResetPeer:
    """A loopback peer that answers the first frame, waits, then resets the connection (SO_LINGER 0: an RST, not a FIN).
    Every later connection is answered normally."""

    def __init__(self):
        self.ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ls.bind(("127.0.0.1", 0))
        self.ls.listen(4)
        self.port = self.ls.getsockname()[1]
        self.accepts, self.reset_done = 0, threading.Event()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        self.ls.settimeout(0.05)
        while not self._stop.is_set():
            try:
                s, _a = self.ls.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.accepts += 1
            first = self.accepts == 1
            try:
                while not self._stop.is_set():
                    f = b""
                    while len(f) < 64:
                        r, _w, _x = select.select([s], [], [], 0.05)
                        if self._stop.is_set():
                            return
                        if r:
                            d = s.recv(64 - len(f))
                            if not d:
                                raise OSError("eof")
                            f += d
                    s.sendall(FakeMonitor.answer(f))
                    if first:
                        time.sleep(0.2)
                        break
            except OSError:
                pass
            finally:
                if first:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    self.reset_done.set()
                s.close()

    def close(self):
        self._stop.set()
        self.ls.close()
        self._t.join(2)


def test_x_a_reset_seen_only_by_the_peer_check_reconnects_before_the_send(cc, K):
    """The monitor answers, then resets the connection: the non-blocking recv(MSG_PEEK) before the next send fails
    (ECONNRESET), which the peer check takes as closed, so the frame goes out on a new connection and is replied."""
    peer = _ResetPeer()
    try:
        c = client(cc, K, port=peer.port, clock=time.monotonic_ns)
        c.offer(ctl(cc), None)
        assert settle(c, lambda: c.n["replied"] == 1)
        assert peer.reset_done.wait(SLACK_S)
        time.sleep(0.05)
        assert c.connected                                      # not yet noticed
        c.offer(ctl(cc, stamp_ms=30), None)
        c.pump()
        assert settle(c, lambda: c.n["replied"] == 2)
        assert c.n["lost_on_reconnect"] == 0 and peer.accepts == 2
        closed_out(cc, c)
    finally:
        peer.close()


def test_x_a_host_that_does_not_resolve_backs_off(cc, K, monkeypatch):
    """A name the resolver refuses (socket.gaierror, an OSError, raised here without any lookup) is a failed connect: the
    backoff, never an exception out of pump()."""
    clk = Clock()
    c = client(cc, K, clock=clk)

    class _Unresolvable(socket.socket):
        def connect_ex(self, address):
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    monkeypatch.setattr(cc.socket, "socket", _Unresolvable)
    c.offer(ctl(cc), None)
    c.pump()
    monkeypatch.undo()
    assert c.n["connect_failures"] == 1 and c.next_connect_ns == clk() + 100 * MS and not c.connected
    closed_out(cc, c)


# ============================================================ the node, with stand-ins for ROS

def ns(obj):
    if isinstance(obj, dict):
        return types.SimpleNamespace(**{k: ns(v) for k, v in obj.items()})
    return obj


def messages():
    return json.loads(MESSAGES_FILE.read_text(encoding="utf-8"))


def control_msg(stamp_ns, v=2.0, a=0.5, a_def=True, d=0.1, r=0.0, r_def=False):
    t = types.SimpleNamespace(sec=stamp_ns // 10 ** 9, nanosec=stamp_ns % 10 ** 9)
    return types.SimpleNamespace(stamp=t, lateral=types.SimpleNamespace(steering_tire_angle=d, steering_tire_rotation_rate=r,
                                                                        is_defined_steering_tire_rotation_rate=r_def),
                                 longitudinal=types.SimpleNamespace(velocity=v, acceleration=a, jerk=0.0,
                                                                    is_defined_acceleration=a_def, is_defined_jerk=False))


def odom_msg(v):
    return ns({"header": {"stamp": {"sec": 1, "nanosec": 0}}, "twist": {"twist": {"linear": {"x": v}}}})


def test_the_node_converts_its_messages_with_pure_functions(node, cc):
    m = messages()["messages"]
    c = node.control_from_msg(ns(m[CONTROL_TOPIC]), 42)
    assert c == cc.Control(stamp_ns=1700 * 10 ** 9 + 34_000_000, recv_ns=42, velocity=2.75, acceleration=0.5,
                           is_defined_acceleration=True, jerk=0.0, is_defined_jerk=False, steering_tire_angle=0.125,
                           steering_tire_rotation_rate=0.25, is_defined_steering_tire_rotation_rate=True)
    assert node.odometry_from_msg(ns(m[ODOM_TOPIC]), 43) == cc.Odometry(v=2.25, recv_ns=43)
    assert node.stamp_ns(types.SimpleNamespace(sec=2, nanosec=5)) == 2_000_000_005


def fake_ros(monkeypatch, script):
    """Stand-ins for rclpy and the three message packages, put into sys.modules: each Node records what it creates,
    spin() runs `script(record)`, and a publisher appends what it publishes."""
    rec = types.SimpleNamespace(publishers=[], subscriptions=[], published=[], inits=0, shutdowns=0, spun=False)

    class Node:
        def __init__(self, name):
            rec.node_name = name

        def create_publisher(self, msg_type, topic, qos):
            pub = types.SimpleNamespace(msg_type=msg_type, topic=topic, qos=qos)
            pub.publish = lambda m: rec.published.append((topic, m))
            rec.publishers.append(pub)
            return pub

        def create_subscription(self, msg_type, topic, cb, qos):
            rec.subscriptions.append(types.SimpleNamespace(msg_type=msg_type, topic=topic, cb=cb, qos=qos))
            return object()

        def destroy_node(self):
            rec.destroyed = True

    class QoSProfile:
        def __init__(self, depth=None, history=None, reliability=None, durability=None):
            self.depth, self.history, self.reliability, self.durability = depth, history, reliability, durability

    class HistoryPolicy:
        KEEP_LAST, KEEP_ALL = "keep_last", "keep_all"

    class ReliabilityPolicy:
        RELIABLE, BEST_EFFORT = "reliable", "best_effort"

    class DurabilityPolicy:
        VOLATILE, TRANSIENT_LOCAL = "volatile", "transient_local"

    class ExternalShutdownException(Exception):
        pass

    def spin(n):
        rec.spun = True
        script(rec)

    def init(args=None):
        rec.inits += 1

    def try_shutdown():
        rec.shutdowns += 1

    rclpy = types.ModuleType("rclpy")
    rclpy.init, rclpy.spin, rclpy.try_shutdown, rclpy.shutdown = init, spin, try_shutdown, try_shutdown
    mods = {"rclpy": rclpy, "rclpy.node": types.ModuleType("rclpy.node"), "rclpy.qos": types.ModuleType("rclpy.qos"),
            "rclpy.executors": types.ModuleType("rclpy.executors")}
    mods["rclpy.node"].Node = Node
    q = mods["rclpy.qos"]
    q.QoSProfile, q.HistoryPolicy, q.ReliabilityPolicy, q.DurabilityPolicy = QoSProfile, HistoryPolicy, ReliabilityPolicy, DurabilityPolicy
    mods["rclpy.executors"].ExternalShutdownException = ExternalShutdownException
    rclpy.node, rclpy.qos, rclpy.executors = mods["rclpy.node"], q, mods["rclpy.executors"]

    class String:
        def __init__(self, data=""):
            self.data = data

    msg_types = {"autoware_control_msgs": "Control", "nav_msgs": "Odometry", "std_msgs": "String"}
    for pkg, cls_name in msg_types.items():
        top, sub = types.ModuleType(pkg), types.ModuleType(pkg + ".msg")
        setattr(sub, cls_name, String if cls_name == "String" else type(cls_name, (), {}))
        top.msg = sub
        mods[pkg], mods[pkg + ".msg"] = top, sub
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    rec.types = {k: getattr(mods[k + ".msg"], v) for k, v in msg_types.items()}
    return rec


def test_the_node_subscribes_to_the_two_claim_topics_and_publishes_only_the_verdict(node, cc, K, monitor, monkeypatch, tmp_path):
    mon = monitor()

    def frames_published(rec):
        return sum(1 for _t, m in list(rec.published) if strict_json(m.data)["seq"] != 0)

    def script(rec):
        subs = {s.topic: s.cb for s in rec.subscriptions}
        subs[ODOM_TOPIC](odom_msg(2.0))
        for i in range(5):
            subs[CONTROL_TOPIC](control_msg(T0 + 30 * i * MS))
            assert wait_for(lambda i=i: frames_published(rec) == i + 1)       # one outcome before the next Control

    rec = fake_ros(monkeypatch, script)
    rc = node.main(["--host", "127.0.0.1", "--port", str(mon.port), "--contract", str(CONTRACT_FILE),
                    "--out", str(tmp_path / "run")])
    assert rc == 0 and rec.spun and rec.inits == 1 and rec.shutdowns >= 1
    assert len(rec.publishers) == 1
    pub = rec.publishers[0]
    assert (pub.topic, pub.msg_type, pub.qos.depth, pub.qos.history, pub.qos.reliability) == \
        (VERDICT_TOPIC, rec.types["std_msgs"], 10, "keep_last", "reliable")
    assert sorted(s.topic for s in rec.subscriptions) == sorted([CONTROL_TOPIC, ODOM_TOPIC])
    for s in rec.subscriptions:
        assert (s.qos.depth, s.qos.history) == (1, "keep_last")
        assert (s.qos.reliability, s.qos.durability) == ("reliable", "volatile")       # a latched message must never become a frame
        assert s.msg_type is rec.types["autoware_control_msgs" if s.topic == CONTROL_TOPIC else "nav_msgs"]
    assert {t for t, _m in rec.published} == {VERDICT_TOPIC}
    objs = [strict_json(m.data) for _t, m in rec.published]
    assert all(list(o) == MESSAGE_KEYS for o in objs)
    frames = [o for o in objs if o["seq"]]
    assert [o["seq"] for o in frames] == [1, 2, 3, 4, 5] and all(o["verdict"] == 0 for o in frames)
    assert [o["connected"] for o in objs if o["seq"] == 0] == [True, False]
    recs = [json.loads(x) for x in (tmp_path / "run" / "replies.jsonl").read_text(encoding="utf-8").splitlines()]
    assert recs[0]["header"]["mode"] == "node" and recs[-1]["summary"]["identity"]["holds"]
    assert all(bytes.fromhex(r["frame"])[H] & 0x08 for r in recs[1:-1])          # the odometry was fresh: b3


def test_x_the_node_drains_the_last_frame_at_its_stop(node, cc, monitor, monkeypatch, tmp_path):
    """The spin ends right after the last Control while its reply is still on the way: the node's stop drains it, so it
    is counted replied, not lost."""
    def script_mon(ci, fi, f):
        if fi == 1:
            time.sleep(0.2)
        return "reply"
    mon = monitor(script=script_mon)

    def script(rec):
        subs = {s.topic: s.cb for s in rec.subscriptions}
        subs[CONTROL_TOPIC](control_msg(T0))
        assert wait_for(lambda: any(strict_json(m.data)["seq"] == 1 for _t, m in list(rec.published)))
        subs[CONTROL_TOPIC](control_msg(T0 + 30 * MS))
        assert wait_for(lambda: len(mon.frames()) == 2)           # sent; its reply comes 200 ms later
    fake_ros(monkeypatch, script)
    rc = node.main(["--host", "127.0.0.1", "--port", str(mon.port), "--contract", str(CONTRACT_FILE), "--out", str(tmp_path / "run")])
    recs = [json.loads(x) for x in (tmp_path / "run" / "replies.jsonl").read_text(encoding="utf-8").splitlines()[1:-1]]
    assert rc == 0 and [(r["seq"], r["outcome"]) for r in recs] == [(1, "replied"), (2, "replied")]


def test_the_node_refuses_a_bad_config_before_it_imports_rclpy(node, monkeypatch, tmp_path, capsys):
    for name in ("rclpy", "rclpy.node"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    rc = node.main(["--host", "127.0.0.1", "--port", "7151", "--inject", "5:nan", "--contract", str(CONTRACT_FILE),
                    "--out", str(tmp_path / "run")])
    assert rc == 2 and "rclpy" not in sys.modules
    assert "stamp" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


def test_the_node_and_the_replay_take_the_same_arguments(node, rp, cc):
    common = ["--host", "127.0.0.1", "--port", "7150", "--profile", "1", "--demo", "0:30000", "--inject", "5:nan",
              "--inject", "9:speed", "--pause", "3:1500", "--contract", str(CONTRACT_FILE), "--out", "/x"]
    a = node.argument_parser().parse_args(common)
    b = rp.argument_parser().parse_args(common + ["--export", str(EXPORT_FILE)])
    assert cc.config_from_args(a) == cc.config_from_args(b) == cc.Config(
        host="127.0.0.1", port=7150, profile=1, stamp=False, demo=(0, 30000), injections=((5, "nan"), (9, "speed")),
        pause=(3, 1500))


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module)
        elif isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("import_module", "__import__"):
            names.add("<dynamic import>")
    return names


FORBIDDEN_IN_NODE = ("kuksa_client", "kuksa", "grpc", "grpcio", "rules", "vssframe", "kind4_client", "ctlrules")


def test_the_node_imports_no_kuksa_grpc_frame_or_rules(node):
    """Statically over the node and every sdv/ctl module it imports (inside functions too), and at run time in a fresh
    interpreter: no KUKSA client, no gRPC, nothing of sdv/frame, no ctlrules, and no ROS until main runs."""
    seen, todo, names = set(), ["ctl_claim_node"], set()
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        found = _imports(CTL_DIR / (mod + ".py"))
        names |= found
        todo.extend(m for m in found if (CTL_DIR / (m + ".py")).is_file())
    assert seen == {"ctl_claim_node", "ctlclient", "ctlframe"}
    assert not [m for m in names if m.split(".")[0] in FORBIDDEN_IN_NODE or m == "<dynamic import>"]
    for m in seen:                               # no path to sdv/frame built (REPO / "sdv" / "frame", "sdv/frame")
        tree = ast.parse((CTL_DIR / (m + ".py")).read_text(encoding="utf-8"))
        joins = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
                 and isinstance(n.right, ast.Constant) and n.right.value == "frame"]
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and any(isinstance(a, ast.Constant) and isinstance(a.value, str) and "sdv/frame" in a.value for a in n.args)]
        assert not joins and not calls, m
    code =("import sys; sys.dont_write_bytecode = True; sys.path.insert(0, %r); import ctl_claim_node; "
            "print(' '.join(sorted(sys.modules)))" % str(CTL_DIR))
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    loaded = set(out.stdout.split())
    bad = FORBIDDEN_IN_NODE + ("rclpy", "autoware_control_msgs", "nav_msgs", "std_msgs")
    assert not [m for m in loaded if m.split(".")[0] in bad]


def test_ctlrules_is_imported_by_nothing_in_the_package_but_the_tests():
    for p in CTL_DIR.glob("*.py"):
        if p.name != "ctlrules.py":
            assert "ctlrules" not in {m.split(".")[0] for m in _imports(p)}, p.name


# ============================================================ the replay

def test_the_replay_reads_the_export(rp):
    records, summary = rp.read_export(EXPORT_FILE)
    assert len(records) == 11 and summary["export_format"] == 1
    assert [r["topic"] for r in records].count(CONTROL_TOPIC) == 4


def test_the_replay_pairs_each_control_with_the_latest_odometry_before_it(rp):
    records, _s = rp.read_export(EXPORT_FILE)
    pairs = rp.controls_with_odometry(records)
    assert [(o.v, o.recv_ns) if o else None for _c, o in pairs] == [(2.0, 1700000000000), (2.25, 1700020000000),
                                                                   (9.0, 1700056000000), (9.0, 1700056000000)]
    assert [c.recv_ns for c, _o in pairs] == [1700005000000, 1700055000000, 1700085000000, 1700300000000]


def test_the_replay_schedules_each_control_at_its_receive_time_after_the_first(rp):
    records, _s = rp.read_export(EXPORT_FILE)
    assert rp.schedule_ns(rp.controls_with_odometry(records)) == [0, 50 * MS, 80 * MS, 295 * MS]


def test_x_only_the_last_control_of_the_fixture_export_has_a_stale_odometry(rp, cc):
    """The fixture export's odometry ages (each Control's receive time minus that of the latest odometry before it) are
    5, 35, 29 and 244 ms: only the last is outside the 100 ms freshness window, which is why the replay packs it with b3
    clear (test_the_replay_sends_the_export_through_the_core says so in a comment; this holds the comment's claim)."""
    records, _s = rp.read_export(EXPORT_FILE)
    ages = [c.recv_ns - o.recv_ns for c, o in rp.controls_with_odometry(records)]
    assert ages == [5 * MS, 35 * MS, 29 * MS, 244 * MS]
    assert [a <= cc.ODOM_FRESH_NS for a in ages] == [True, True, True, False]


def test_the_replay_sends_the_export_through_the_core(rp, cc, cf, K, monitor, tmp_path):
    mon = monitor()
    log = tmp_path / "replies.jsonl"
    cfg = cc.Config(host="127.0.0.1", port=mon.port)
    s = rp.replay(EXPORT_FILE, cfg, K, reply_log=log)
    assert s["identity"]["holds"] and s["counters"]["replied"] == 4
    objs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    h = objs[0]["header"]
    assert h["mode"] == "replay" and h["export_sha256"] == hashlib.sha256(EXPORT_FILE.read_bytes()).hexdigest()
    frames = [cf.decode_request(bytes.fromhex(r["frame"])) for r in objs[1:-1]]
    assert [d.interval_ms for d in frames] == [0, 30, 30, 30]               # from the recorded stamps, not the receive times
    assert [d.v_meas for d in frames] == [2.0, 2.25, 9.0, None]  # the last odometry is 244 ms older than its Control: outside the 100 ms window
    assert [d.v_cmd for d in frames] == [2.5, 2.75, 3.0, 3.0]
    assert [(d.accel, d.jerk, d.rate) for d in frames] == [(0.5, None, None), (0.5, 0.25, None), (None, None, 0.25),
                                                           (None, None, None)]
    assert mon.seqs() == [1, 2, 3, 4]


@pytest.mark.parametrize("edit", [
    ("topic", lambda o: o.update(topic="/diagnostics")), ("extra key", lambda o: o.update(extra=1)),
    ("no fields", lambda o: o.pop("fields")), ("recv_ns str", lambda o: o.update(recv_ns="1")),
    ("field missing", lambda o: o["fields"].pop("velocity")), ("field extra", lambda o: o["fields"].update(v_meas=1.0)),
    ("flag not bool", lambda o: o["fields"].update(is_defined_jerk=1)), ("value str", lambda o: o["fields"].update(velocity="2")),
], ids=lambda e: e[0])
def test_the_replay_refuses_a_malformed_export_line(rp, tmp_path, edit):
    lines = EXPORT_FILE.read_text(encoding="utf-8").splitlines()
    o = json.loads(lines[2])
    edit[1](o)
    lines[2] = json.dumps(o, separators=(",", ":"))
    p = tmp_path / "e.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(rp.ReplayError):
        rp.read_export(p)


@pytest.mark.parametrize("edit", [
    ("topic", lambda o: o.update(topic="/diagnostics")), ("extra key", lambda o: o.update(extra=1)),
    ("no fields", lambda o: o.pop("fields")), ("recv_ns str", lambda o: o.update(recv_ns="1")),
], ids=lambda e: e[0])
@pytest.mark.parametrize("line", range(11))
def test_the_replay_refuses_a_generic_fault_on_any_line(rp, tmp_path, line, edit):
    lines = EXPORT_FILE.read_text(encoding="utf-8").splitlines()
    o = json.loads(lines[line])
    edit[1](o)
    lines[line] = json.dumps(o, separators=(",", ":"))
    p = tmp_path / "e.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(rp.ReplayError):
        rp.read_export(p)


@pytest.mark.parametrize("edit", ["no summary", "count", "format", "after summary"])
def test_the_replay_refuses_an_export_whose_summary_does_not_close_it(rp, tmp_path, edit):
    lines = EXPORT_FILE.read_text(encoding="utf-8").splitlines()
    if edit == "no summary":
        lines = lines[:-1]
    elif edit == "after summary":
        lines.append(lines[0])
    else:
        s = json.loads(lines[-1])
        if edit == "count":
            s["summary"]["messages"][CONTROL_TOPIC] = 5
        else:
            s["summary"]["export_format"] = 2
        lines[-1] = json.dumps(s, separators=(",", ":"))
    p = tmp_path / "e.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(rp.ReplayError):
        rp.read_export(p)


def _x_export(tmp_path, edit):
    lines = EXPORT_FILE.read_text(encoding="utf-8").splitlines()
    edit(lines)
    p = tmp_path / "e.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _x_set(i, **kw):
    def edit(lines):
        o = json.loads(lines[i])
        o.update(kw)
        lines[i] = json.dumps(o, separators=(",", ":"))
    return edit


def _x_velocity_to_infinity(lines):
    assert lines[2].count('"velocity":2.5') == 1
    lines[2] = lines[2].replace('"velocity":2.5', '"velocity":1e400')           # JSON reads a number this large as infinity


@pytest.mark.parametrize("edit", [_x_set(3, recv_ns=1), _x_set(2, stamp_ns=None), _x_velocity_to_infinity],
                         ids=["recv_ns goes back", "a Control without a stamp", "a number JSON reads as infinity"])
def test_x_the_replay_refuses(rp, tmp_path, edit):
    with pytest.raises(rp.ReplayError):
        rp.read_export(_x_export(tmp_path, edit))


def test_x_the_replay_takes_the_zero_count_ctl_export_writes_for_an_absent_topic(rp, tmp_path):
    """ctl_export writes a count of 0 for a topic the bag does not hold; the replay reads such an export."""
    def edit(lines):
        del lines[6]                                       # the /localization/acceleration line
        s = json.loads(lines[-1])
        s["summary"]["messages"]["/localization/acceleration"] = 0
        lines[-1] = json.dumps(s, separators=(",", ":"))
    records, _s = rp.read_export(_x_export(tmp_path, edit))
    assert len(records) == 10


@pytest.mark.parametrize("topic,count,absent_line", [(CONTROL_TOPIC, 4.0, None), (CONTROL_TOPIC, "4", None),
                                                     ("/localization/acceleration", 0.0, 6)],
                         ids=["4.0", "'4'", "0.0 for an absent topic"])
def test_x_the_replay_refuses_a_summary_count_that_is_not_an_int(rp, tmp_path, topic, count, absent_line):
    def edit(lines):
        if absent_line is not None:
            del lines[absent_line]
        s = json.loads(lines[-1])
        s["summary"]["messages"][topic] = count
        lines[-1] = json.dumps(s, separators=(",", ":"))
    with pytest.raises(rp.ReplayError):
        rp.read_export(_x_export(tmp_path, edit))


def test_x_the_replay_refuses_a_negative_receive_time(rp, tmp_path):
    with pytest.raises(rp.ReplayError):
        rp.read_export(_x_export(tmp_path, _x_set(0, recv_ns=-1)))


def test_x_the_replay_refuses_a_gear_report_that_is_not_an_int(rp, tmp_path):
    def edit(lines):
        o = json.loads(lines[4])
        o["fields"]["report"] = 2.0
        lines[4] = json.dumps(o, separators=(",", ":"))
    with pytest.raises(rp.ReplayError):
        rp.read_export(_x_export(tmp_path, edit))


def test_x_the_replay_refuses_an_export_format_that_is_not_the_int_1(rp, tmp_path):
    def edit(lines):
        s = json.loads(lines[-1])
        s["summary"]["export_format"] = True
        lines[-1] = json.dumps(s, separators=(",", ":"))
    with pytest.raises(rp.ReplayError):
        rp.read_export(_x_export(tmp_path, edit))


def test_x_the_replay_packs_a_null_as_a_non_finite_value(rp, cc, cf, K):
    """A value the export holds as null is packed as a quiet NaN (the monitor answers it with 9), never as 0.0."""
    records, _s = rp.read_export(EXPORT_FILE)
    records[2]["fields"]["velocity"] = None
    records[2]["fields"]["steering_tire_angle"] = None
    c = client(cc, K)
    c.offer(*rp.controls_with_odometry(records)[0])
    f = c.queued.frame
    assert not cf.is_finite_bits(struct.unpack_from("<I", f, H + 2)[0])
    assert not cf.is_finite_bits(struct.unpack_from("<I", f, H + 33)[0])
    closed_out(cc, c)


def test_the_replay_main_runs_against_a_peer_and_writes_its_run_directory(rp, monitor, tmp_path):
    mon = monitor()
    out = tmp_path / "run"
    rc = rp.main(["--host", "127.0.0.1", "--port", str(mon.port), "--contract", str(CONTRACT_FILE), "--out", str(out),
                  "--export", str(EXPORT_FILE)])
    assert rc == 0 and mon.seqs() == [1, 2, 3, 4]
    assert (out / "replies.jsonl").is_file()


@pytest.mark.parametrize("where", ["repo", "nonempty"])
def test_a_run_directory_inside_the_repo_or_not_empty_is_refused(rp, tmp_path, where):
    if where == "repo":
        out = REPO / "sdv-out" / "ctl-run-refused"
    else:
        out = tmp_path / "run"
        out.mkdir()
        (out / "x").write_text("x", encoding="utf-8")
    rc = rp.main(["--host", "127.0.0.1", "--port", str(free_port()), "--contract", str(CONTRACT_FILE), "--out", str(out),
                  "--export", str(EXPORT_FILE)])
    assert rc == 2
    if where == "repo":
        assert not out.exists()


def test_x_the_replay_main_refuses_a_bad_export_before_the_run_directory(rp, tmp_path, capsys):
    bad = _x_export(tmp_path, lambda lines: lines.pop())            # no summary line
    out = tmp_path / "run"
    rc = rp.main(["--host", "127.0.0.1", "--port", str(free_port()), "--contract", str(CONTRACT_FILE), "--out", str(out),
                  "--export", str(bad)])
    assert rc == 2 and not out.exists() and "refused" in capsys.readouterr().err


def test_x_the_replay_main_refuses_a_missing_export_before_the_run_directory(rp, tmp_path, capsys):
    out = tmp_path / "run"
    rc = rp.main(["--host", "127.0.0.1", "--port", str(free_port()), "--contract", str(CONTRACT_FILE), "--out", str(out),
                  "--export", str(tmp_path / "absent.jsonl")])
    assert rc == 2 and not out.exists() and "refused" in capsys.readouterr().err


def test_x_the_replay_takes_two_messages_with_one_receive_time(rp, tmp_path):
    """Receive order is never decreasing, not strictly increasing: two messages a bag received in the same ns are taken."""
    records, _s = rp.read_export(_x_export(tmp_path, _x_set(1, recv_ns=1700000000000)))
    assert records[0]["recv_ns"] == records[1]["recv_ns"]


def test_x_the_replay_refuses_an_export_format_of_1_0(rp, tmp_path):
    """The summary's export_format is the int 1 (ctl_export writes it so); 1.0 is not that, as FORMAT 1.0 is not the
    contract's."""
    def edit(lines):
        s = json.loads(lines[-1])
        s["summary"]["export_format"] = 1.0
        lines[-1] = json.dumps(s, separators=(",", ":"))
    with pytest.raises(rp.ReplayError):
        rp.read_export(_x_export(tmp_path, edit))


def _linked_work_tree(tmp_path):
    """A scratch directory that holds a .git entry (a work tree as far as the package can tell), and a symbolic link to a
    directory inside it: the link's own ancestors hold no .git, so only following the link finds the work tree."""
    tree = tmp_path / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(tree / "sub", target_is_directory=True)
    except (OSError, NotImplementedError) as err:
        pytest.skip("no symbolic link can be made here: %s" % err)
    return tree, link


def test_a_run_directory_reached_through_a_symbolic_link_into_a_work_tree_is_inside_it(cc, tmp_path):
    tree, link = _linked_work_tree(tmp_path)
    assert cc.work_tree_of(link / "run") == tree.resolve()
    assert cc.work_tree_of(tmp_path / "elsewhere" / "run") is None
    with pytest.raises(cc.ClientError, match="work tree"):
        cc.open_run_dir(str(link / "run"))
    assert not (tree / "sub" / "run").exists()


# ============================================================ the export

class GearReport:
    """A stand-in message class: the fixture's gear constants, and an upper-case name that is not a gear."""
    SOMETHING_ELSE = "not a gear"


for _name, _val in messages()["gear_constants"].items():
    setattr(GearReport, _name, _val)


def test_the_gear_names_come_from_the_message_class_constants(ex):
    names = ex.gear_names(GearReport)
    assert names[2] == "DRIVE" and names[20] == "REVERSE" and names[22] == "PARK" and names[0] == "NONE"
    assert names[23] == "LOW" and len(names) == len(messages()["gear_constants"])


def test_the_export_converts_each_message_with_pure_functions(ex):
    m = messages()["messages"]
    got = {t: ex.to_record(t, 1000 + i, ns(m[t]), gear=ex.gear_names(GearReport)) for i, t in enumerate(ex.TOPICS)}
    assert got[CONTROL_TOPIC] == {"topic": CONTROL_TOPIC, "recv_ns": 1000, "stamp_ns": 1700034000000, "fields": {
        "velocity": 2.75, "acceleration": 0.5, "jerk": 0.0, "is_defined_acceleration": True, "is_defined_jerk": False,
        "steering_tire_angle": 0.125, "steering_tire_rotation_rate": 0.25, "is_defined_steering_tire_rotation_rate": True}}
    assert got[ODOM_TOPIC]["fields"] == {"v": 2.25} and got[ODOM_TOPIC]["stamp_ns"] == 1700010000000
    assert got["/vehicle/status/velocity_status"]["fields"] == {"longitudinal_velocity": 2.0, "heading_rate": 0.0625}
    assert got["/vehicle/status/steering_status"]["fields"] == {"steering_tire_angle": 0.0625}
    assert got["/vehicle/status/steering_status"]["stamp_ns"] == 1700005500000
    assert got["/vehicle/status/gear_status"]["fields"] == {"report": 20, "report_name": "REVERSE"}
    assert got["/localization/acceleration"]["fields"] == {"ax": -0.375}
    assert list(ex.TOPICS) == [CONTROL_TOPIC, ODOM_TOPIC, "/vehicle/status/velocity_status", "/vehicle/status/steering_status",
                               "/vehicle/status/gear_status", "/localization/acceleration"]
    for r in got.values():
        assert list(r) == ["topic", "recv_ns", "stamp_ns", "fields"]


def test_every_record_the_export_makes_is_one_the_replay_takes(ex, rp):
    m = messages()["messages"]
    assert list(ex.TOPICS) == list(rp.EXPORT_FIELDS)
    for i, t in enumerate(ex.TOPICS):
        rec = ex.to_record(t, 1000 + i, ns(m[t]), gear=ex.gear_names(GearReport))
        rp.check_record(strict_json(ex.dumps(rec)))


def test_the_export_writes_a_non_finite_value_as_null(ex):
    m = messages()["messages"][CONTROL_TOPIC]
    m["longitudinal"]["jerk"] = float("nan")
    r = ex.to_record(CONTROL_TOPIC, 1, ns(m))
    assert r["fields"]["jerk"] is None
    assert "NaN" not in ex.dumps(r)


def test_x_the_export_writes_an_unknown_gear_value_as_unknown(ex):
    m = messages()["messages"]["/vehicle/status/gear_status"]
    m["report"] = 99
    r = ex.to_record("/vehicle/status/gear_status", 1, ns(m), gear=ex.gear_names(GearReport))
    assert r["fields"] == {"report": 99, "report_name": "UNKNOWN_99"}


def _ros_free_main(ex, monkeypatch, argv):
    for name in ("rosbag2_py", "rclpy", "rclpy.serialization", "rosidl_runtime_py", "rosidl_runtime_py.utilities"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    rc = ex.main(argv)
    assert "rosbag2_py" not in sys.modules
    return rc


@pytest.mark.parametrize("where", ["out in repo", "bag in repo", "out exists", "out in a work tree"])
def test_the_export_refuses_its_paths_before_it_imports_rosbag2(ex, monkeypatch, tmp_path, where, capsys):
    bag = tmp_path / "bag"
    bag.mkdir()
    out = tmp_path / "out.jsonl"
    if where == "out in repo":
        out = REPO / "sdv-out" / "refused-export.jsonl"
    elif where == "bag in repo":
        bag = REPO / "sdv" / "ctl"
    elif where == "out exists":
        out.write_text("keep\n", encoding="utf-8")
    else:
        (tmp_path / "wt").mkdir()
        (tmp_path / "wt" / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        out = tmp_path / "wt" / "sub" / "out.jsonl"
    rc = _ros_free_main(ex, monkeypatch, ["--bag", str(bag), "--out", str(out)])
    assert rc == 2 and "refused" in capsys.readouterr().err
    if where == "out exists":
        assert out.read_text(encoding="utf-8") == "keep\n"
    else:
        assert not out.exists()
    if where == "out in a work tree":
        assert not out.parent.exists()                      # no directory made for a refused output either


@pytest.mark.parametrize("where", ["out", "bag"])
def test_the_export_refuses_a_path_reached_through_a_symbolic_link_into_a_work_tree(ex, monkeypatch, tmp_path, where, capsys):
    tree, link = _linked_work_tree(tmp_path)
    (tree / "sub" / "bag").mkdir()
    (tmp_path / "bag").mkdir()
    bag, out = (tmp_path / "bag", link / "out.jsonl") if where == "out" else (link / "bag", tmp_path / "out.jsonl")
    rc = _ros_free_main(ex, monkeypatch, ["--bag", str(bag), "--out", str(out)])
    assert rc == 2 and "refused" in capsys.readouterr().err
    assert not out.exists() and not (tree / "sub" / "out.jsonl").exists()


def test_x_the_export_refuses_a_bag_that_is_not_a_directory(ex, monkeypatch, tmp_path, capsys):
    bag = tmp_path / "bag_0.mcap"
    bag.write_bytes(b"x")
    rc = _ros_free_main(ex, monkeypatch, ["--bag", str(bag), "--out", str(tmp_path / "out.jsonl")])
    assert rc == 2 and "not a directory" in capsys.readouterr().err


def test_x_the_export_refuses_a_dangling_link_as_its_output_before_rosbag2(ex, monkeypatch, tmp_path, capsys):
    bag = tmp_path / "bag"
    bag.mkdir()
    out = tmp_path / "out.jsonl"
    try:
        out.symlink_to(tmp_path / "nowhere")
    except (OSError, NotImplementedError) as err:
        pytest.skip("no symbolic link can be made here: %s" % err)
    rc = _ros_free_main(ex, monkeypatch, ["--bag", str(bag), "--out", str(out)])
    assert rc == 2 and "exists" in capsys.readouterr().err


def fake_rosbag(monkeypatch, entries, topic_types, msgs, classes):
    rb = types.ModuleType("rosbag2_py")

    class StorageOptions:
        def __init__(self, uri="", storage_id=""):
            self.uri, self.storage_id = uri, storage_id

    class ConverterOptions:
        def __init__(self, input_serialization_format="", output_serialization_format=""):
            pass

    class StorageFilter:
        def __init__(self, topics=()):
            self.topics = list(topics)

    class SequentialReader:
        def open(self, storage, conv):
            self.i, self.filter = 0, None

        def get_all_topics_and_types(self):
            return [types.SimpleNamespace(name=t, type=ty) for t, ty in topic_types.items()]

        def set_filter(self, f):
            self.filter = f

        def has_next(self):
            while self.i < len(entries) and self.filter is not None and entries[self.i][0] not in self.filter.topics:
                self.i += 1
            return self.i < len(entries)

        def read_next(self):
            e = entries[self.i]
            self.i += 1
            return e

    rb.StorageOptions, rb.ConverterOptions, rb.StorageFilter, rb.SequentialReader = StorageOptions, ConverterOptions, StorageFilter, SequentialReader
    ser = types.ModuleType("rclpy.serialization")
    ser.deserialize_message = lambda data, cls: msgs[data]
    rclpy = types.ModuleType("rclpy")
    rclpy.serialization = ser
    util = types.ModuleType("rosidl_runtime_py.utilities")
    util.get_message = lambda name: classes[name]
    top = types.ModuleType("rosidl_runtime_py")
    top.utilities = util
    for name, mod in (("rosbag2_py", rb), ("rclpy", rclpy), ("rclpy.serialization", ser), ("rosidl_runtime_py", top),
                      ("rosidl_runtime_py.utilities", util)):
        monkeypatch.setitem(sys.modules, name, mod)


def test_the_export_main_writes_the_records_and_the_summary(ex, monkeypatch, tmp_path):
    bag = tmp_path / "bag"
    bag.mkdir()
    (bag / "metadata.yaml").write_bytes(b"meta\n")
    (bag / "bag_0.mcap").write_bytes(b"\x00\x01data")
    (bag / "sub").mkdir()
    (bag / "sub" / "bag_1.mcap").write_bytes(b"nested")
    m = messages()["messages"]
    msgs = {t.encode(): ns(m[t]) for t in ex.TOPICS}
    entries = [(t, t.encode(), 5000 + i) for i, t in enumerate(ex.TOPICS)] + [(CONTROL_TOPIC, CONTROL_TOPIC.encode(), 9000),
                                                                             ("/tf", b"x", 9100)]
    topic_types = dict(ex.TOPICS)
    topic_types["/tf"] = "tf2_msgs/msg/TFMessage"
    classes = {ty: (GearReport if t == "/vehicle/status/gear_status" else object) for t, ty in ex.TOPICS.items()}
    fake_rosbag(monkeypatch, entries, topic_types, msgs, classes)
    out = tmp_path / "x" / "export.jsonl"
    assert ex.main(["--bag", str(bag), "--out", str(out)]) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    objs = [strict_json(x) for x in lines]
    assert [o["topic"] for o in objs[:-1]] == list(ex.TOPICS) + [CONTROL_TOPIC]
    assert [o["recv_ns"] for o in objs[:-1]] == [5000, 5001, 5002, 5003, 5004, 5005, 9000]
    assert objs[4]["fields"]["report_name"] == "REVERSE"
    s = objs[-1]["summary"]
    assert list(s) == ["messages", "bag_sha256", "export_format"] and s["export_format"] == 1
    assert s["messages"] == {t: (2 if t == CONTROL_TOPIC else 1) for t in ex.TOPICS}
    assert s["bag_sha256"] == {"bag_0.mcap": hashlib.sha256(b"\x00\x01data").hexdigest(),
                               "metadata.yaml": hashlib.sha256(b"meta\n").hexdigest(),
                               "sub/bag_1.mcap": hashlib.sha256(b"nested").hexdigest()}      # a sub-directory's file, by relative path
    assert all(x == json.dumps(strict_json(x), separators=(",", ":")) for x in lines)


def test_the_export_removes_a_half_written_output_when_a_read_fails(ex, monkeypatch, tmp_path):
    bag = tmp_path / "bag"
    bag.mkdir()
    m = messages()["messages"]
    msgs = {t.encode(): ns(m[t]) for t in ex.TOPICS}
    entries = [(t, t.encode(), 5000 + i) for i, t in enumerate(ex.TOPICS)]
    classes = {ty: (GearReport if t == "/vehicle/status/gear_status" else object) for t, ty in ex.TOPICS.items()}
    fake_rosbag(monkeypatch, entries, dict(ex.TOPICS), msgs, classes)
    reader = sys.modules["rosbag2_py"].SequentialReader
    real, reads = reader.read_next, []

    def third_read_fails(self):
        reads.append(1)
        if len(reads) == 3:
            raise RuntimeError("a read failed")
        return real(self)
    monkeypatch.setattr(reader, "read_next", third_read_fails)
    out = tmp_path / "x" / "export.jsonl"
    with pytest.raises(RuntimeError, match="a read failed"):
        ex.main(["--bag", str(bag), "--out", str(out)])
    assert len(reads) == 3                                   # the output was open, with two records written, when it failed
    assert not out.exists()


def test_the_export_refuses_a_topic_of_another_type(ex, monkeypatch, tmp_path, capsys):
    bag = tmp_path / "bag"
    bag.mkdir()
    topic_types = dict(ex.TOPICS)
    topic_types[CONTROL_TOPIC] = "autoware_auto_control_msgs/msg/AckermannControlCommand"
    fake_rosbag(monkeypatch, [], topic_types, {}, {})
    out = tmp_path / "x" / "export.jsonl"
    assert ex.main(["--bag", str(bag), "--out", str(out)]) == 2
    assert not out.exists() and "type" in capsys.readouterr().err
    assert not out.parent.exists()                           # the refusal came before any directory was made


# ============================================================ the README

def test_the_readme_states_the_modules_where_they_run_and_what_they_do_not_demonstrate():
    text = (CTL_DIR / "README.md").read_text(encoding="utf-8")
    for name in ("ctlframe.py", "ctlrules.py", "ctlclient.py", "ctl_claim_node.py", "ctlreplay.py", "ctl_export.py"):
        assert name in text, name
    for phrase in ("Jazzy container", "bare-metal host", "CI", "replies.jsonl", "/qnx_monitor/verdict"):
        assert phrase in text, phrase
    tail = text[text.index("## What this does not demonstrate"):]
    for phrase in ("control loop", "after the gate", "timing"):
        assert phrase in tail, phrase


def test_x_the_fixtures_say_where_their_values_come_from():
    """The fixtures' provenance sentences claim what they hold and no more (synthetic values only): the contract
    fixture's limits are in the shape of the gate's public nominal configuration and its UIDs made up, the message
    fixture's gear constants are GearReport's public definition; both say no value is a measurement or comes from a
    run, and neither says its values were not read from Autoware, which public definitions are."""
    doc = " ".join(ast.get_docstring(ast.parse(CONTRACT_FILE.read_text(encoding="utf-8"))).split())
    note = messages()["_note"]
    assert "the shape of the gate's public nominal configuration and the UIDs made up" in doc
    assert "no value is a measurement or a run's result" in doc
    assert "the gear constants are GearReport's public definition" in note and "nothing is read from a bag or a run" in note
    for text in (doc, note):
        assert "read from Autoware" not in text and "not read from" not in text


def test_x_the_readme_expects_a_reject_only_from_the_designed_causes():
    """The README claims nothing about Autoware's own traffic: a reject is expected only from an injected fault, the
    intake pause or profile 2's window, and any other is a finding of the run that shows it."""
    tail = (CTL_DIR / "README.md").read_text(encoding="utf-8").split("## What this does not demonstrate")[1]
    flat = " ".join(tail.split())
    assert "a reject is expected only from an injected fault, the intake pause or profile 2's window" in flat
    assert "any other reject is a finding of the run that shows it (WP4b)" in flat and "reject comes only from" not in flat


def test_the_package_leaves_no_carriage_return_and_no_bytecode():
    for p in list(CTL_DIR.glob("*")) + list(FIX.glob("*")) + [Path(__file__)]:
        if p.is_file():
            assert b"\r" not in p.read_bytes(), p
    assert not (CTL_DIR / "__pycache__").exists()
