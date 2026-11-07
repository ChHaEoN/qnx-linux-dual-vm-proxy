"""ctlclient.py -- the kind 2 claim node's core (sdv/ctl): one frame per Control, sent to the QNX guest's monitor
(:7150 svc 500; :7151 stamp for pre-registered timing runs only), with the claim bridge's connection rules.

The Phase 8 specification (the project's local design notes, sections 2.1, 2.2, 2.6
and 4; not in this tree) defines it; the connection rules are sdv/bridge/vss_claim_bridge.py's (its CONNECTION and
ACCOUNTING), applied to kind 2, and the bridge is the pattern only: nothing of it is imported. Standard library only,
so the claim node (ctl_claim_node.py, rclpy in the Jazzy container) and the replay (ctlreplay.py, no ROS) run the
same core; the frame is ctlframe.py's. No clock of its own: every instant comes from `clock` (CLOCK_MONOTONIC ns by
default), so the tests drive it deterministically.

INTAKE AND PACKING
  offer(control, odometry) packs one frame per counted Control, at once, in the caller's thread: seq from 1 (never
  the sentinel), tstamp the client's clock, the flags from the Control's is_defined_* fields, b3 only when the
  odometry was received within ODOM_FRESH_NS before the Control (on the clock both receive times are on: the node's
  monotonic clock, or the export's recorded receive times in a replay), else b3 clear (odom_absent or odom_stale
  counted); r17_skip counts the frames packed with b3 clear (an injection that sets b3 packs none); the
  interval from this Control's stamp and the previous counted one's (ctlframe.interval_ms). A value the gate sent is
  packed as its binary32 bits even when it is not finite (counted nonfinite_in; the monitor answers 9): no counted
  Control goes without its frame. Profile 2 (DEMO_PROFILE) only inside one bounded window counted from the first
  packed frame; the base profile is never 2.
  The intake pause (--pause AFTER_SEQ:DURATION_MS): once the frame AFTER_SEQ is packed, Controls offered for
  DURATION_MS are not counted (controls_paused, outside the identity) and pack nothing, and the first one after it
  carries the interval from the last counted Control's stamp. This is the plan's node-injected silence: the monitor
  sees no frame, closes the idle connection at its deadline, and the first frame after the pause gets reason 11.

ACCOUNTING: controls = packed = replied + drop + lost_on_reconnect.
  One request outstanding at a time; a frame packed while one is outstanding (or while no connection is open) waits in
  a 1-deep queue, and a frame packed while one waits replaces it, the replaced one counted drop. At a stop: no new
  connect; the queued frame is sent if a connection is open and nothing is outstanding, the outstanding frame gets its
  reply or the reply timeout (at most DRAIN_NS), and whatever is left is counted (lost or drop): the identity holds
  when a run ends.

CONNECTION (the bridge's rules; 2.1's design values)
  Connect at the first Control (nothing before it: Autoware sends none until it engages, and an early connection
  would only be closed at the monitor's deadline); after a close, reconnect only when the next frame is to be sent,
  never during a silence; a failed connect (refused, or not completed within CONNECT_TIMEOUT_NS) backs off from
  BACKOFF_FIRST_NS, doubling, capped at BACKOFF_CAP_NS, and a connect resets it. Before every send, a non-blocking
  recv(MSG_PEEK) checks whether the peer has closed, and reconnects first if it has (without it, the first frame after
  a silence goes into the dead connection and is lost, and the next one's interval is one control period: reason 11
  would not show). A frame sent and unanswered when the connection drops is lost_on_reconnect, apart from drop; so is
  one with no reply for REPLY_TIMEOUT_NS, after which the client closes the connection itself. A reply must be the
  request with only p[6] and p[7] written (and p[8..23] on a stamp target), with a consistent verdict and reason;
  anything else is reply_invalid: the frame is lost and the connection closed, as it is for bytes that arrive with
  nothing outstanding (stray_bytes). "Lost" means unanswered, not unjudged.

OUTPUTS
  The reply log (JSON Lines, never overwritten): a first line {"header": {...}} (format 1, kind 2, the mode, the
  target, the stamp flag, the profile, the demo window, the injections, the pause, the contract's sha256 and digest,
  the design values), one line per frame outcome {"seq", "frame" (the 64 bytes sent, hex), "outcome" (replied, drop,
  lost), "verdict", "reason", "mono_ns" (the client's clock at the outcome); on a stamp target a reply's record adds
  "t_in_ns" and "t_out_ns", the monitor's stamps}, and a last line {"summary": {...}}.
  2.6's verdict message, built by the one pure function verdict_message(), handed to `sink` once per frame outcome
  and once per connection change (the node publishes it on /qnx_monitor/verdict). The sink is called with the
  client's lock held, from whichever thread caused the outcome: it must not block or call the client.

INJECTION (OP Phase 1 step 8; demos and tests only): each at a fixed seq from a list given at start: nan (v_cmd a
  quiet NaN: 9), undef (acceleration bytes with b0 clear: 10), reserved (b4: 10), profile0 (8), kind9 (the kind byte
  9: the monitor's unknown kind, 5), and the value injections interval (11), speed (12), accel (13), jerk (14), steer
  (15), steer-rate (16), lat-accel (17), overspeed (18), rolling-back (19), each putting its field beyond the frame's
  profile limit (VALUE_FACTOR) or threshold (INJECT_MARGIN_MPS) so the designed reason is the first failure for an
  honest Control. Every injection, the pause and the demo window are refused on a stamp target (:7151 always, or a
  target marked --stamp), so none can enter a timing run. A rolling-back injection is also refused when the contract's
  OVERSPEED_MARGIN is under its |v_meas| as packed (rule 18 would come first for a small v_cmd: rollback_v_meas). And
  any injection is refused when the contract leaves it no frame that carries its designed reason, for a Control at
  rest and each profile the run may send (injection_problem: a steer_max with no binary32 above 0 below it, a limit
  whose VALUE_FACTOR-fold has no binary32 above the limit, a DT_MAX_MS that is not an int below 0xFFFF, a constant
  that puts rule 18's or 19's threshold out of reach), so offer() never raises for an injection. A value only the
  Control puts beyond binary32 (overspeed's v_meas for a v_cmd near the binary32 maximum) is packed as an infinity,
  as an honest value is, and gets 9.

THREADS
  offer() runs in the caller's thread (the node's subscription callback); the socket is only touched by pump() and
  wait(), which the client's own thread runs in a loop once start() is called (the node), or the caller runs inline
  (the replay, the tests). One lock holds the state; offer() wakes the loop through a socket pair.

DOES NOT DEMONSTRATE: any timing (the logs order events; nothing here is a measurement); that the monitor is in any
control loop (it is not: the node observes the gate's output after the fact); anything about the guest beyond its
replies.
"""
from __future__ import annotations

import argparse
import errno
import json
import math
import os
import select
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable, Dict, List, Mapping, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import ctlframe as cf  # noqa: E402

MS = 1_000_000

# --- design values (specification 2.1): each in this one place, with its reason --------------------------------------
# The reply timeout: the monitor's own svc deadline on :7150 (500 ms), itself aligned with the gate's timeout_thr_sec and
# heartbeat of 0.5 s; a frame unanswered that long is given up, as the bridge does.
REPLY_TIMEOUT_NS = 500 * MS
# The connect timeout: the reply timeout's value, so a connect that hangs (a guest restarting, SYNs dropped) costs no
# more than one unanswered frame would.
CONNECT_TIMEOUT_NS = 500 * MS
# The backoff after a failed connect: from about three control periods (100 ms), doubling, capped at 2 s as the
# bridge's is, so a guest that is down for long is tried every 2 s and one that restarts is found within 100 ms.
BACKOFF_FIRST_NS = 100 * MS
BACKOFF_CAP_NS = 2000 * MS
# The odometry freshness window for b3: about three of the single-source 30 ms control periods (WP4a reads the real
# rates); an older odometry leaves b3 clear and rule 17 is skipped (r17_skip).
ODOM_FRESH_NS = 100 * MS
# This file's own choices.
DRAIN_NS = 2 * REPLY_TIMEOUT_NS        # a stop's drain: the outstanding frame's reply timeout, then the queued one's
LOOP_WAIT_MAX_S = 0.5                  # the client thread's longest wait with nothing due (a wake ends it sooner)
VALUE_FACTOR = 1.5                     # a value injection's field: this times the profile's limit
INJECT_MARGIN_MPS = 1.0                # overspeed and rolling-back: this far beyond rule 18's and 19's thresholds

CLAIM_PORT = 7150
STAMP_PORT = 7151
DEMO_PROFILE = 2
REPLY_LOG = "replies.jsonl"
HEADER_FORMAT = 1
DEFAULT_CONTRACT = REPO / "sdv-out" / "gen" / "vss_ctl.py"

INJECTION_REASONS = {
    "nan": cf.RSN_NOT_FINITE, "undef": cf.RSN_FLAGS_INVALID, "reserved": cf.RSN_FLAGS_INVALID,
    "profile0": cf.RSN_PROFILE_UNBOUND, "kind9": cf.RSN_KIND_UNKNOWN, "interval": cf.RSN_CTL_INTERVAL,
    "speed": cf.RSN_CTL_SPEED, "accel": cf.RSN_CTL_ACCEL, "jerk": cf.RSN_CTL_JERK, "steer": cf.RSN_CTL_STEER,
    "steer-rate": cf.RSN_CTL_STEER_RATE, "lat-accel": cf.RSN_CTL_LAT_ACCEL, "overspeed": cf.RSN_CTL_OVERSPEED,
    "rolling-back": cf.RSN_CTL_ROLLING_BACK,
}
INJECTIONS = tuple(INJECTION_REASONS)
VALUE_INJECTION_LIMITS = {"speed": "v_max", "accel": "a_max", "jerk": "jerk_max", "steer": "steer_max",
                          "steer-rate": "steer_rate_max"}        # the profile limit each puts its field VALUE_FACTOR times beyond
QUIET_NAN_BITS = 0x7FC00000
UNDEF_BITS = 0x3F800000                # 1.0f, written into the acceleration slot with b0 clear
RESERVED_FLAG = 0x10                   # b4, the lowest reserved flag bit
INJECTED_KIND = 9

MESSAGE_FORMAT = 1
MESSAGE_KEYS = ("v", "seq", "profile", "v_cmd", "acc", "jerk", "steer", "steer_rate", "interval_ms", "verdict", "reason",
                "packed", "replied", "accepted", "rejected", "dropped", "lost_on_reconnect", "reconnects", "connected")
MESSAGE_MAX_BYTES = 1024

COUNTERS = ("controls", "packed", "controls_paused", "replied", "accepted", "rejected", "drop", "lost_on_reconnect",
            "connects", "reconnects", "connect_failures", "peer_checks", "sends", "reply_timeouts", "reply_invalid",
            "stray_bytes", "r17_skip", "odom_absent", "odom_stale", "interval_negative", "nonfinite_in", "injected",
            "demo_frames", "sink_errors")

DISCONNECTED, CONNECTING, CONNECTED = "disconnected", "connecting", "connected"


class ClientError(RuntimeError):
    """A refusal: the client does not start, or a call is refused."""


# --- what the intake hands over --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Control:
    """One autoware_control_msgs/msg/Control as the core takes it: the stamp in ns, the receive time on the clock the
    odometry's receive time is on, and the fields of Lateral and Longitudinal (a field whose is_defined flag is clear is
    carried but never packed)."""
    stamp_ns: int
    recv_ns: int
    velocity: float
    acceleration: float
    is_defined_acceleration: bool
    jerk: float
    is_defined_jerk: bool
    steering_tire_angle: float
    steering_tire_rotation_rate: float
    is_defined_steering_tire_rotation_rate: bool


@dataclass(frozen=True)
class Odometry:
    """The latest nav_msgs/msg/Odometry: twist.twist.linear.x [m/s] and its receive time."""
    v: float
    recv_ns: int


@dataclass(frozen=True)
class Config:
    """The run's items: the target, the profile, and the demo window, injections and pause (each refused on a stamp
    target). demo is (start_ms, duration_ms) from the first packed frame; injections ((seq, mode), ...); pause
    (after_seq, duration_ms)."""
    host: str
    port: int = CLAIM_PORT
    profile: int = 1
    stamp: bool = False
    demo: Optional[Tuple[int, int]] = None
    injections: Tuple[Tuple[int, str], ...] = ()
    pause: Optional[Tuple[int, int]] = None

    def is_stamp(self) -> bool:
        """A stamp target: the stamp port always, or another port marked stamp."""
        return self.port == STAMP_PORT or self.stamp is True


def _int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def rollback_v_meas(contract: Any) -> float:
    """|v_meas| of the rolling-back injection as the frame carries it: ROLLBACK_V + INJECT_MARGIN_MPS rounded to binary32
    (beyond binary32: infinity). The injection clears v_cmd's sign, so for v_cmd 0 rule 18's threshold is
    OVERSPEED_MARGIN, and 19 comes first for every v_cmd only when this is not above it (a design choice: the injection
    is refused at start, not moved closer to ROLLBACK_V)."""
    return abs(cf.bits_f32(cf.honest_bits(contract.ROLLBACK_V + INJECT_MARGIN_MPS)))


def beyond_limit_bits(limit: float) -> int:
    """The field of a value injection for 12 to 16: VALUE_FACTOR times the profile's limit, as binary32 bits. ValueError
    when binary32 has no such value above the limit (the product beyond binary32, or a limit so near 0 that the product
    rounds to it or below): the frame would then not be packed, or would miss its reason."""
    b = cf.honest_bits(VALUE_FACTOR * limit)
    if not (cf.is_finite_bits(b) and cf.bits_f32(b) > limit):
        raise ValueError("%r times the limit %r leaves no binary32 above the limit" % (VALUE_FACTOR, limit))
    return b


def lat_accel_bits(contract: Any, pr: Mapping[str, Any]) -> Tuple[int, int]:
    """The lat-accel injection's delta and v_meas bits for the profile row pr: delta the largest binary32 not above its
    steer_max (rule 15 stays quiet, also for a steer_max that binary32 cannot carry), and a v_meas whose lateral
    acceleration is VALUE_FACTOR times the bound lat_acc_max + TOL17 (math.tan and L in mm / 1000 suffice for a value
    this far beyond the edge). ValueError when the row leaves no such frame: a delta of 0 (a steer_max below the
    smallest binary32 above 0: tan 0, no lateral acceleration at any speed), a bound not above 0, or a v_meas beyond
    binary32."""
    d = cf.f32(pr["steer_max"])                 # the largest binary32 not above steer_max: rule 15 stays quiet
    if d > pr["steer_max"]:
        d = cf.f32_next_down(d)
    if not d > 0.0:
        raise ValueError("steer_max %r leaves no binary32 delta above 0 to put a lateral acceleration on" % (pr["steer_max"],))
    bound = pr["lat_acc_max"] + contract.TOL17
    if not bound > 0.0:
        raise ValueError("lat_acc_max + TOL17 = %r: no speed puts a lateral acceleration VALUE_FACTOR times beyond it" % (bound,))
    v = cf.honest_bits(math.sqrt(VALUE_FACTOR * bound * (pr["l_mm"] / 1000.0) / math.tan(d)))
    if not cf.is_finite_bits(v):
        raise ValueError("the v_meas it needs is beyond binary32")
    return cf.f32_bits(d), v


def overspeed_bits(contract: Any, v_cmd: float) -> int:
    """The overspeed injection's v_meas bits for a packed |v_cmd|: OVERSPEED_FACTOR x |v_cmd| + OVERSPEED_MARGIN +
    INJECT_MARGIN_MPS, beyond rule 18's threshold. Never raises: beyond binary32 it is an infinity, as an honest value
    is packed (the monitor answers 9)."""
    return cf.honest_bits(contract.OVERSPEED_FACTOR * v_cmd + contract.OVERSPEED_MARGIN + INJECT_MARGIN_MPS)


def rolling_back_bits(contract: Any) -> int:
    """The rolling-back injection's v_meas bits: -(ROLLBACK_V + INJECT_MARGIN_MPS), below rule 19's threshold."""
    return cf.honest_bits(-(contract.ROLLBACK_V + INJECT_MARGIN_MPS))


def injection_problem(contract: Any, profile: int, mode: str) -> Optional[str]:
    """Why the contract leaves this injection no frame that carries its designed reason when the profile is sent with a
    Control at rest (v_cmd 0, delta 0, no optional field, no odometry), or None. check_config refuses the injection for
    any such reason and every profile the run may send, so offer() never raises for an injection (in the node it would
    raise inside the ROS callback), and no frame it packs misses its reason for want of a binary32."""
    k, pr = contract, contract.PROFILES[profile]
    why: Optional[str] = None
    try:
        if mode in VALUE_INJECTION_LIMITS:
            beyond_limit_bits(pr[VALUE_INJECTION_LIMITS[mode]])
        elif mode == "lat-accel":
            lat_accel_bits(k, pr)
        elif mode == "interval":
            if not (_int(k.DT_MAX_MS) and 0 <= k.DT_MAX_MS < cf.INTERVAL_MAX):
                why = "DT_MAX_MS %r leaves no u16 interval above it (an int in 0..%d is needed)" % (k.DT_MAX_MS, cf.INTERVAL_MAX - 1)
        elif mode == "overspeed":
            v = cf.bits_f32(overspeed_bits(k, 0.0))
            if not (math.isfinite(v) and abs(v) > k.OVERSPEED_FACTOR * 0.0 + k.OVERSPEED_MARGIN):
                why = "its v_meas %r at v_cmd 0 is not beyond rule 18's threshold %r" % (v, k.OVERSPEED_FACTOR * 0.0 + k.OVERSPEED_MARGIN)
        elif mode == "rolling-back":
            v = cf.bits_f32(rolling_back_bits(k))
            if not (math.isfinite(v) and v < -k.ROLLBACK_V):
                why = "its v_meas %r is not below rule 19's threshold %r" % (v, -k.ROLLBACK_V)
    except (ValueError, ArithmeticError) as err:
        why = str(err)
    return None if why is None else "the %s injection with profile %d: %s" % (mode, profile, why)


def check_config(cfg: Config, contract: Any) -> List[str]:
    """Every reason the client refuses to start with this config and contract (an empty list: it starts)."""
    problems: List[str] = []
    if not isinstance(cfg.host, str) or not cfg.host:
        problems.append("host %r" % (cfg.host,))
    if not _int(cfg.port) or not 0 < cfg.port < 65536:
        problems.append("port %r" % (cfg.port,))
    profiles = contract.PROFILES
    compiled = tuple(contract.COMPILED_PROFILE_IDS)
    pid = cfg.profile
    if not _int(pid) or pid not in profiles:
        problems.append("profile %r is not in the contract's profile table" % (pid,))
    elif pid not in compiled:
        problems.append("profile %d is not compiled into the guest (compiled: %s): every frame would get 8"
                        % (pid, ", ".join(str(i) for i in compiled)))
    elif pid == DEMO_PROFILE:
        problems.append("profile %d is the demo profile: it is sent only inside the --demo window" % DEMO_PROFILE)
    stamp = cfg.is_stamp()
    # the profiles an injection may be packed with: the base profile, and profile 2 when a demo window may send it
    may_send = (pid, DEMO_PROFILE) if cfg.demo is not None else (pid,)
    sent = sorted({p for p in may_send if _int(p) and p in compiled})
    if cfg.demo is not None:
        d = cfg.demo
        if not (isinstance(d, tuple) and len(d) == 2 and all(_int(x) for x in d)):
            problems.append("demo %r is not (start_ms, duration_ms)" % (d,))
        else:
            start, dur = d
            limit = profiles.get(DEMO_PROFILE, {}).get("run_window_max_ms")
            if DEMO_PROFILE not in compiled:
                problems.append("the demo profile %d is not compiled into the guest" % DEMO_PROFILE)
            if limit is None:
                problems.append("profile %d has no run_window_max_ms: it is not a demo profile" % DEMO_PROFILE)
            if start < 0:
                problems.append("demo start %d ms is negative" % start)
            if dur <= 0:
                problems.append("demo duration %d ms is not positive" % dur)
            elif limit is not None and dur > limit:
                problems.append("demo window of %d ms exceeds profile %d's run_window_max_ms of %d ms" % (dur, DEMO_PROFILE, limit))
        if stamp:
            problems.append("a demo window is refused on a stamp target (:%d, or one marked --stamp)" % STAMP_PORT)
    seqs = []
    for item in cfg.injections:
        if not (isinstance(item, tuple) and len(item) == 2 and _int(item[0]) and isinstance(item[1], str)):
            problems.append("injection %r is not (seq, mode)" % (item,))
            continue
        seq, mode = item
        if not 1 <= seq < cf.SENTINEL_SEQ:
            problems.append("injection seq %d: seqs count from 1" % seq)
        if mode not in INJECTION_REASONS:
            problems.append("injection mode %r is not one of %s" % (mode, ", ".join(INJECTIONS)))
        for p in sent:
            why = injection_problem(contract, p, mode)
            if why is not None:
                problems.append(why)
        if mode == "rolling-back" and not rollback_v_meas(contract) <= contract.OVERSPEED_MARGIN:
            problems.append("a rolling-back injection packs |v_meas| %r m/s, above OVERSPEED_MARGIN %r m/s: for a small "
                            "v_cmd rule 18 would come before 19" % (rollback_v_meas(contract), contract.OVERSPEED_MARGIN))
        seqs.append(seq)
    if len(seqs) != len(set(seqs)):
        problems.append("two injections at one seq")
    if cfg.injections and stamp:
        problems.append("injections are refused on a stamp target (:%d, or one marked --stamp)" % STAMP_PORT)
    if cfg.pause is not None:
        pz = cfg.pause
        if not (isinstance(pz, tuple) and len(pz) == 2 and all(_int(x) for x in pz) and pz[0] >= 1 and pz[1] > 0):
            problems.append("pause %r is not (after_seq >= 1, duration_ms > 0)" % (pz,))
        if stamp:
            problems.append("the intake pause is refused on a stamp target (:%d, or one marked --stamp)" % STAMP_PORT)
    return problems


def identity(n: Mapping[str, int]) -> Dict[str, Any]:
    """controls = packed = replied + drop + lost_on_reconnect, with its terms."""
    return {"controls": n["controls"], "packed": n["packed"], "replied": n["replied"], "drop": n["drop"],
            "lost_on_reconnect": n["lost_on_reconnect"],
            "holds": n["controls"] == n["packed"] == n["replied"] + n["drop"] + n["lost_on_reconnect"]}


class Backoff:
    """2.1: from BACKOFF_FIRST_NS, doubling, capped at BACKOFF_CAP_NS; reset by a connect."""

    def __init__(self) -> None:
        self._next = BACKOFF_FIRST_NS

    def reset(self) -> None:
        self._next = BACKOFF_FIRST_NS

    def next_ns(self) -> int:
        d = self._next
        self._next = min(2 * d, BACKOFF_CAP_NS)
        return d


# --- 2.6: the verdict message ------------------------------------------------------------------------------------------

def _json_float(x: Optional[float]) -> Optional[float]:
    """A packed binary32 as a JSON number, or None (absent, or not finite: never NaN or Infinity in the message)."""
    return float(x) if x is not None and math.isfinite(x) else None


def verdict_message(*, seq: int, frame: Optional[bytes], verdict: Optional[int], reason: Optional[int],
                    counters: Mapping[str, int], connected: bool) -> str:
    """2.6's message: one compact ASCII JSON object of exactly MESSAGE_KEYS, in that order, at most 1024 bytes.

    A frame outcome passes the frame as packed (its fields read by its own flags: null exactly when a flag is clear,
    and null for a non-finite value) with its seq, and the reply's verdict and reason (None unless replied); a
    connection change passes frame None and seq 0, and then carries profile 0, interval 0 and null command fields.
    counters: packed, replied, accepted, rejected, drop, lost_on_reconnect, reconnects, cumulative."""
    if frame is None:
        if seq != 0 or verdict is not None or reason is not None:
            raise ValueError("a connection change carries seq 0 and no verdict")
        cmd: Dict[str, Any] = {"profile": 0, "v_cmd": None, "acc": None, "jerk": None, "steer": None, "steer_rate": None,
                               "interval_ms": 0}
    else:
        f = cf.fields_of(frame)
        if seq != f["seq"] or seq == 0:
            raise ValueError("seq %r is not the frame's (%r)" % (seq, f["seq"]))
        cmd = {"profile": f["profile"], "v_cmd": _json_float(f["v_cmd"]), "acc": _json_float(f["accel"]),
               "jerk": _json_float(f["jerk"]), "steer": _json_float(f["delta"]), "steer_rate": _json_float(f["rate"]),
               "interval_ms": f["interval_ms"]}
    obj: Dict[str, Any] = {"v": MESSAGE_FORMAT, "seq": seq}
    obj.update(cmd)
    obj.update({"verdict": verdict, "reason": reason, "packed": counters["packed"], "replied": counters["replied"],
                "accepted": counters["accepted"], "rejected": counters["rejected"], "dropped": counters["drop"],
                "lost_on_reconnect": counters["lost_on_reconnect"], "reconnects": counters["reconnects"],
                "connected": bool(connected)})
    s = json.dumps(obj, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    if len(s) > MESSAGE_MAX_BYTES:
        raise ValueError("verdict message of %d bytes is over %d" % (len(s), MESSAGE_MAX_BYTES))
    return s


# --- the core ------------------------------------------------------------------------------------------------------------

@dataclass
class Packed:
    seq: int
    frame: bytes
    profile: int
    inject: Optional[str]
    demo: bool
    mono_ns: int
    sent_ns: Optional[int] = None


class CtlClient:
    """The intake, the 1-deep queue, the connection and the accounting of one run."""

    def __init__(self, cfg: Config, contract: Any, *, clock: Callable[[], int] = time.monotonic_ns,
                 sink: Optional[Callable[[str], None]] = None, reply_log: Optional[os.PathLike] = None, mode: str = "node",
                 header_extra: Optional[Mapping[str, Any]] = None) -> None:
        problems = check_config(cfg, contract)
        if problems:
            raise ClientError("refused: " + "; ".join(problems))
        self.cfg = cfg
        self.contract = contract
        self.clock = clock
        self.sink = sink
        self.mode = mode
        self.stamp = cfg.is_stamp()
        self.n: Dict[str, int] = {k: 0 for k in COUNTERS}
        self.next_seq = 1
        self.queued: Optional[Packed] = None
        self.outstanding: Optional[Packed] = None
        self.last_reply: Optional[Tuple[int, int, int]] = None      # verdict, reason, seq
        self.next_connect_ns = 0
        self.fatal: Optional[str] = None
        self.backoff = Backoff()
        self._injections = dict(cfg.injections)
        self._last_stamp_ns: Optional[int] = None
        self._first_mono: Optional[int] = None
        self._pause_until: Optional[int] = None
        self._demo: Dict[str, Any] = {"first_seq": None, "last_seq": None, "frames": 0}
        self._state = DISCONNECTED
        self._sock: Optional[socket.socket] = None
        self._rbuf = b""
        self._reply_due = 0
        self._connect_due = 0
        self._draining = False
        self._stopped = False
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self.header: Dict[str, Any] = {
            "format": HEADER_FORMAT, "kind": cf.KIND_CTL, "mode": mode, "target": "%s:%d" % (cfg.host, cfg.port),
            "stamp": self.stamp, "profile": cfg.profile,
            "demo": None if cfg.demo is None else {"profile": DEMO_PROFILE, "start_ms": cfg.demo[0], "duration_ms": cfg.demo[1]},
            "injections": [{"seq": s, "mode": m} for s, m in sorted(cfg.injections)],
            "pause": None if cfg.pause is None else {"after_seq": cfg.pause[0], "duration_ms": cfg.pause[1]},
            "contract_sha256": cf.contract_sha256(contract), "digest": int(contract.DIGEST),
            "design": {"reply_timeout_ms": REPLY_TIMEOUT_NS // MS, "connect_timeout_ms": CONNECT_TIMEOUT_NS // MS,
                       "backoff_first_ms": BACKOFF_FIRST_NS // MS, "backoff_cap_ms": BACKOFF_CAP_NS // MS,
                       "odom_fresh_ms": ODOM_FRESH_NS // MS},
        }
        self.header.update(header_extra or {})
        self._log: Optional[IO[str]] = None
        if reply_log is not None:
            try:
                self._log = open(reply_log, "x", encoding="utf-8", newline="\n")
            except FileExistsError as err:
                raise ClientError("refused: the reply log %s exists (a reply log is never overwritten)" % reply_log) from err
            self._write({"header": self.header})
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._wake_w.setblocking(False)

    # ---- state seen from outside

    @property
    def connected(self) -> bool:
        return self._state == CONNECTED

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            demo = None
            if self.cfg.demo is not None:
                demo = {"profile": DEMO_PROFILE, "first_seq": self._demo["first_seq"], "last_seq": self._demo["last_seq"],
                        "frames": self._demo["frames"]}
            return {"counters": dict(self.n), "identity": identity(self.n), "demo": demo,
                    "last_reply": list(self.last_reply) if self.last_reply else None, "fatal": self.fatal}

    # ---- the intake

    def offer(self, ctl: Control, odom: Optional[Odometry]) -> Optional[int]:
        """Count and pack one Control (None while the intake is paused: not counted); returns the seq packed."""
        with self._lock:
            if self._stopped:
                raise ClientError("the client is stopped")
            now = self.clock()
            if self._pause_until is not None:
                if now < self._pause_until:
                    self.n["controls_paused"] += 1
                    return None
                self._pause_until = None
            p = self._pack(ctl, odom, now)
            if self.queued is not None:
                self._drop(self.queued, "replaced")
            self.queued = p
        self._wake()
        return p.seq

    def _profile_at(self, now: int, first: int) -> Tuple[int, bool]:
        if self.cfg.demo is None:
            return self.cfg.profile, False
        start, dur = self.cfg.demo
        el = now - first
        if start * MS <= el < (start + dur) * MS:
            return DEMO_PROFILE, True
        return self.cfg.profile, False

    def _pack(self, ctl: Control, odom: Optional[Odometry], now: int) -> Packed:
        """Everything that can refuse happens before anything is counted, so a refusal leaves the identity whole."""
        if self.next_seq >= cf.SENTINEL_SEQ:
            raise ClientError("seq would reach the sentinel %#x: a new run starts from 1" % cf.SENTINEL_SEQ)
        seq = self.next_seq
        first = self._first_mono if self._first_mono is not None else now
        profile, demo = self._profile_at(now, first)
        flags = 0
        slots: Dict[str, Optional[int]] = {"v_cmd": cf.honest_bits(ctl.velocity), "delta": cf.honest_bits(ctl.steering_tire_angle),
                                           "accel": None, "jerk": None, "rate": None, "v_meas": None}
        if ctl.is_defined_acceleration:
            flags |= cf.F_ACCEL
            slots["accel"] = cf.honest_bits(ctl.acceleration)
        if ctl.is_defined_jerk:
            flags |= cf.F_JERK
            slots["jerk"] = cf.honest_bits(ctl.jerk)
        if ctl.is_defined_steering_tire_rotation_rate:
            flags |= cf.F_RATE
            slots["rate"] = cf.honest_bits(ctl.steering_tire_rotation_rate)
        odom_state = "absent"
        if odom is not None:
            age = ctl.recv_ns - odom.recv_ns
            if 0 <= age <= ODOM_FRESH_NS:
                flags |= cf.F_ODOM
                slots["v_meas"] = cf.honest_bits(odom.v)
                odom_state = "fresh"
            else:
                odom_state = "stale"
        nonfinite = any(b is not None and not cf.is_finite_bits(b) for b in slots.values())
        interval = cf.interval_ms(self._last_stamp_ns, ctl.stamp_ns)
        negative = self._last_stamp_ns is not None and ctl.stamp_ns < self._last_stamp_ns
        inject = self._injections.get(seq)
        frame = self._build(seq, now, flags, profile, slots, interval, inject)
        # counted from here on: the Control and its one frame
        self.next_seq += 1
        self._first_mono = first
        self._last_stamp_ns = ctl.stamp_ns
        self.n["controls"] += 1
        self.n["packed"] += 1
        if not frame[cf.FRAME_HEADER_BYTES + cf.P_FLAGS] & cf.F_ODOM:
            self.n["r17_skip"] += 1                # 2.3: b3 clear in the frame as packed (an injection may set it)
        if odom_state != "fresh":
            self.n["odom_absent" if odom_state == "absent" else "odom_stale"] += 1
        if negative:
            self.n["interval_negative"] += 1
        if nonfinite:
            self.n["nonfinite_in"] += 1
        if inject is not None:
            self.n["injected"] += 1
        if demo:
            self.n["demo_frames"] += 1
            self._demo["frames"] += 1
            if self._demo["first_seq"] is None:
                self._demo["first_seq"] = seq
            self._demo["last_seq"] = seq
        if self.cfg.pause is not None and seq == self.cfg.pause[0]:
            self._pause_until = now + self.cfg.pause[1] * MS
        return Packed(seq=seq, frame=frame, profile=frame[cf.FRAME_HEADER_BYTES + cf.P_PROFILE], inject=inject, demo=demo,
                      mono_ns=now)

    def _build(self, seq: int, now: int, flags: int, profile: int, slots: Dict[str, Optional[int]], interval: int,
               inject: Optional[str]) -> bytes:
        """The frame, with the injection at this seq applied: value injections change fields before packing, layout
        injections (undef, reserved, kind9) patch the packed bytes (ctlframe never writes a layout fault). check_config
        has refused every injection the contract leaves no frame for (injection_problem), so nothing here raises."""
        k = self.contract
        pr = k.PROFILES[profile]
        patches: List[Tuple[int, bytes]] = []
        if inject == "nan":
            slots["v_cmd"] = QUIET_NAN_BITS
        elif inject == "profile0":
            profile = 0
        elif inject == "interval":
            interval = k.DT_MAX_MS + 1
        elif inject == "speed":
            slots["v_cmd"] = beyond_limit_bits(pr["v_max"])
        elif inject == "accel":
            flags |= cf.F_ACCEL
            slots["accel"] = beyond_limit_bits(pr["a_max"])
        elif inject == "jerk":
            flags |= cf.F_JERK
            slots["jerk"] = beyond_limit_bits(pr["jerk_max"])
        elif inject == "steer":
            slots["delta"] = beyond_limit_bits(pr["steer_max"])
        elif inject == "steer-rate":
            flags |= cf.F_RATE
            slots["rate"] = beyond_limit_bits(pr["steer_rate_max"])
        elif inject == "lat-accel":
            flags |= cf.F_ODOM
            slots["delta"], slots["v_meas"] = lat_accel_bits(k, pr)
        elif inject == "overspeed":
            flags |= cf.F_ODOM
            slots["delta"] = 0
            v_cmd = cf.bits_f32(slots["v_cmd"] or 0)
            v_cmd = abs(v_cmd) if math.isfinite(v_cmd) else 0.0
            slots["v_meas"] = overspeed_bits(k, v_cmd)
        elif inject == "rolling-back":
            flags |= cf.F_ODOM
            slots["delta"] = 0
            slots["v_cmd"] = (slots["v_cmd"] or 0) & 0x7FFFFFFF                    # v_cmd >= 0 (its sign bit cleared)
            slots["v_meas"] = rolling_back_bits(k)                               # check_config: 19, and rule 18 stays quiet
        elif inject == "undef":
            flags &= ~cf.F_ACCEL
            slots["accel"] = None
            patches.append((cf.P_ACCEL, UNDEF_BITS.to_bytes(4, "little")))
        v_cmd_bits, delta_bits = slots.pop("v_cmd"), slots.pop("delta")
        assert v_cmd_bits is not None and delta_bits is not None
        frame = bytearray(cf.pack_bits(seq=seq, tstamp_ns=now, flags=flags, profile=profile, v_cmd=v_cmd_bits,
                                       delta=delta_bits, interval_ms=interval, **slots))
        if inject == "reserved":
            frame[cf.FRAME_HEADER_BYTES + cf.P_FLAGS] |= RESERVED_FLAG
        elif inject == "kind9":
            frame[cf.FRAME_HEADER_BYTES + cf.P_KIND] = INJECTED_KIND
        for off, data in patches:
            frame[cf.FRAME_HEADER_BYTES + off:cf.FRAME_HEADER_BYTES + off + len(data)] = data
        return bytes(frame)

    # ---- outcomes

    def _write(self, obj: Mapping[str, Any]) -> None:
        if self._log is not None:
            self._log.write(json.dumps(obj, separators=(",", ":"), allow_nan=False) + "\n")
            self._log.flush()

    def _emit(self, s: str) -> None:
        """Hand a message to the sink; a sink that raises (a publisher whose context a signal has shut down) is counted
        and never breaks the accounting."""
        if self.sink is not None:
            try:
                self.sink(s)
            except Exception:  # noqa: BLE001 -- counted; the reply log still has every outcome
                self.n["sink_errors"] += 1

    def _outcome(self, p: Packed, outcome: str, verdict: Optional[int], reason: Optional[int],
                 stamps: Optional[Tuple[int, int]] = None) -> None:
        rec: Dict[str, Any] = {"seq": p.seq, "frame": p.frame.hex(), "outcome": outcome, "verdict": verdict, "reason": reason,
                               "mono_ns": self.clock()}
        if stamps is not None:
            rec["t_in_ns"], rec["t_out_ns"] = stamps
        self._write(rec)
        self._emit(verdict_message(seq=p.seq, frame=p.frame, verdict=verdict, reason=reason, counters=self.n,
                                   connected=self.connected))

    def _connection_change(self) -> None:
        self._emit(verdict_message(seq=0, frame=None, verdict=None, reason=None, counters=self.n, connected=self.connected))

    def _drop(self, p: Packed, why: str) -> None:
        self.n["drop"] += 1
        self._outcome(p, "drop", None, None)

    def _lost(self, p: Packed, why: str) -> None:
        self.n["lost_on_reconnect"] += 1
        self._outcome(p, "lost", None, None)

    # ---- the connection

    def _wake(self) -> None:
        try:
            self._wake_w.send(b"\x00")
        except OSError:
            pass                                   # full (a wake is pending anyway) or closed (stopped)

    def pump(self) -> None:
        """The timeouts and a send attempt at the clock's now; never blocks."""
        with self._lock:
            if self._stopped:
                return
            now = self.clock()
            self._check_timeouts(now)
            self._try_send(now)

    def wait(self, timeout_s: float) -> None:
        """Wait up to timeout_s for the socket (a reply, a close, a connect completing) or a wake, handle it, then pump."""
        with self._lock:
            if self._stopped:
                return
            sock, state = self._sock, self._state
        rl: List[Any] = [self._wake_r]
        wl: List[Any] = []
        if sock is not None and state == CONNECTED:
            rl.append(sock)
        elif sock is not None and state == CONNECTING:
            wl.append(sock)
        try:
            r, w, _x = select.select(rl, wl, [], max(0.0, timeout_s))
        except (OSError, ValueError):
            r, w = [], []
        if self._wake_r in r:
            try:
                while self._wake_r.recv(64):
                    pass
            except OSError:
                pass
        with self._lock:
            if sock is not None and sock is self._sock:
                if self._state == CONNECTING and sock in w:
                    self._connect_done(self.clock())
                elif self._state == CONNECTED and sock in r:
                    self._readable()
        self.pump()

    def _next_due_s(self) -> float:
        with self._lock:
            now = self.clock()
            due = [now + int(LOOP_WAIT_MAX_S * 1e9)]
            if self.outstanding is not None:
                due.append(self._reply_due)
            if self._state == CONNECTING:
                due.append(self._connect_due)
            if self._state == DISCONNECTED and self.queued is not None:
                due.append(self.next_connect_ns)
            return max(0, min(due) - now) / 1e9

    def run(self) -> None:
        """The client thread's loop: wait for the socket, a wake or the next due instant, until stop()."""
        try:
            while not self._stop_evt.is_set():
                self.wait(self._next_due_s())
        except Exception as err:  # noqa: BLE001 -- recorded; stop() still closes the identity
            with self._lock:
                self.fatal = "%s: %s" % (type(err).__name__, err)
                self._close("fatal")                   # nothing pumps the socket now: connected must read false from here on
            print("ctlclient: fatal: %s" % self.fatal, file=sys.stderr, flush=True)

    def start(self) -> "CtlClient":
        if self._thread is not None:
            raise ClientError("the client thread is running already")
        self._thread = threading.Thread(target=self.run, name="ctl-client", daemon=True)
        self._thread.start()
        return self

    def stop(self, drain: bool = True) -> Dict[str, Any]:
        """End the run: the client thread joined, then (with drain) the drain, then the close; the queued frame left is
        a drop and the outstanding one lost, so the identity holds. Writes the summary line and returns it."""
        if self._thread is not None:
            self._stop_evt.set()
            self._wake()
            self._thread.join()
            self._thread = None
        with self._lock:
            if self._stopped:
                return self.summary()
        if drain:
            self._drain()
        with self._lock:
            self._close("stop")
            if self.queued is not None:
                p, self.queued = self.queued, None
                self._drop(p, "stop")
            self._stopped = True
            s = self.summary()
            self._write({"summary": s})
            if self._log is not None:
                self._log.close()
                self._log = None
        for sk in (self._wake_r, self._wake_w):
            sk.close()
        return s

    def _drain(self) -> None:
        """No new connect: the queued frame is sent if a connection is open and nothing is outstanding, and the
        outstanding frame gets its reply or the reply timeout; at most DRAIN_NS on the client's clock, and as long in
        real time (a clock that stands still, as a test's may, cannot hold a stop forever)."""
        self._draining = True
        end = self.clock() + DRAIN_NS
        real_end = time.monotonic() + DRAIN_NS / 1e9
        while True:
            with self._lock:
                now = self.clock()
                self._check_timeouts(now)
                if now < end:
                    self._try_send(now)
                if self.outstanding is None:
                    return
                left = self._reply_due - now
            if time.monotonic() >= real_end or now >= end:
                return
            self.wait(min(0.05, max(0.0, left / 1e9)))

    def _check_timeouts(self, now: int) -> None:
        if self.outstanding is not None and now >= self._reply_due:
            self.n["reply_timeouts"] += 1
            self._close("reply timeout")
        if self._state == CONNECTING and now >= self._connect_due:
            self._abandon_connect(now, errno.ETIMEDOUT)

    def _try_send(self, now: int) -> None:
        if self.outstanding is not None or self.queued is None or self._state == CONNECTING:
            return
        for _attempt in range(2):
            if self._state == DISCONNECTED:
                if self._draining or now < self.next_connect_ns:
                    return
                self._connect(now)
            if self._state != CONNECTED:
                return
            self.n["peer_checks"] += 1
            if not self._peer_closed():
                break
            self._close("peer closed (seen before a send)")
        else:
            return
        p, self.queued = self.queued, None
        assert self._sock is not None
        why = ""
        try:
            sent = self._sock.send(p.frame)
        except OSError as err:
            sent = -1
            why = "send failed: %s" % (errno.errorcode.get(err.errno or 0, str(err)),)
        p.sent_ns = now
        self.outstanding = p
        if sent != len(p.frame):
            self._close(why or "short send of %d bytes" % sent)
            return
        self.n["sends"] += 1
        self._reply_due = now + REPLY_TIMEOUT_NS
        self._rbuf = b""

    def _peer_closed(self) -> bool:
        """A non-blocking recv(MSG_PEEK) that returns 0 bytes, or fails, means the peer has closed."""
        assert self._sock is not None
        try:
            data = self._sock.recv(1, socket.MSG_PEEK)
        except (BlockingIOError, InterruptedError):
            return False
        except OSError:
            return True
        return data == b""

    def _connect(self, now: int) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setblocking(False)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            err = s.connect_ex((self.cfg.host, self.cfg.port))
        except OSError as e:                         # a host name that does not resolve
            err = e.errno or errno.EHOSTUNREACH
        if err == 0:
            self._connected(s)
        elif err in (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EAGAIN):
            self._sock = s
            self._state = CONNECTING
            self._connect_due = now + CONNECT_TIMEOUT_NS
        else:
            s.close()
            self._connect_failed(now)

    def _connect_done(self, now: int) -> None:
        assert self._sock is not None
        err = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if err == 0:
            s, self._sock = self._sock, None
            self._connected(s)
        else:
            self._abandon_connect(now, err)

    def _abandon_connect(self, now: int, err: int) -> None:
        s, self._sock = self._sock, None
        self._state = DISCONNECTED
        if s is not None:
            s.close()
        self._connect_failed(now)

    def _connect_failed(self, now: int) -> None:
        self.n["connect_failures"] += 1
        self.next_connect_ns = now + self.backoff.next_ns()

    def _connected(self, s: socket.socket) -> None:
        self._sock = s
        self._state = CONNECTED
        self._rbuf = b""
        self.n["connects"] += 1
        if self.n["connects"] > 1:
            self.n["reconnects"] += 1
        self.backoff.reset()
        self._connection_change()

    def _close(self, why: str) -> None:
        was = self._state
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._state = DISCONNECTED
        self._rbuf = b""
        out, self.outstanding = self.outstanding, None
        if out is not None:
            self._lost(out, why)
        if was == CONNECTED:
            self._connection_change()

    def _reply_problem(self, p: Packed, data: bytes) -> Optional[str]:
        h = cf.FRAME_HEADER_BYTES
        free = {h + cf.P_VERDICT, h + cf.P_REASON}
        if self.stamp:
            free.update(range(h + cf.STAMP_SPAN[0], h + cf.STAMP_SPAN[1]))
        diff = [i for i in range(cf.FRAME_TOTAL_BYTES) if i not in free and data[i] != p.frame[i]]
        if diff:
            return "bytes %s differ from the request (seq %d)" % (diff[:8], p.seq)
        verdict, reason = data[h + cf.P_VERDICT], data[h + cf.P_REASON]
        if verdict not in (cf.V_ACCEPT, cf.V_REJECT) or (verdict == cf.V_ACCEPT) != (reason == cf.RSN_OK):
            return "verdict %d with reason %d" % (verdict, reason)
        return None

    def _readable(self) -> None:
        assert self._sock is not None
        try:
            data = self._sock.recv(cf.FRAME_TOTAL_BYTES - len(self._rbuf))
        except (BlockingIOError, InterruptedError):
            return
        except OSError as err:
            self._close("recv failed: %s" % (errno.errorcode.get(err.errno or 0, str(err)),))
            return
        if not data:
            self._close("peer closed")
            return
        if self.outstanding is None:
            self.n["stray_bytes"] += len(data)
            self._close("stray bytes with nothing outstanding")
            return
        self._rbuf += data
        if len(self._rbuf) < cf.FRAME_TOTAL_BYTES:
            return
        data, self._rbuf = self._rbuf, b""
        p = self.outstanding
        problem = self._reply_problem(p, data)
        if problem is not None:
            self.n["reply_invalid"] += 1
            self._close("invalid reply: " + problem)
            return
        self.outstanding = None
        h = cf.FRAME_HEADER_BYTES
        verdict, reason = data[h + cf.P_VERDICT], data[h + cf.P_REASON]
        self.n["replied"] += 1
        self.n["accepted" if verdict == cf.V_ACCEPT else "rejected"] += 1
        self.last_reply = (verdict, reason, p.seq)
        stamps = None
        if self.stamp:
            stamps = (int.from_bytes(data[h + cf.P_T_IN:h + cf.P_T_IN + 8], "little"),
                      int.from_bytes(data[h + cf.P_T_OUT:h + cf.P_T_OUT + 8], "little"))
        self._outcome(p, "replied", verdict, reason, stamps)


# --- the command line both the node and the replay take ---------------------------------------------------------------

def _pair(text: str) -> Tuple[int, int]:
    a, sep, b = text.partition(":")
    try:
        if not sep:
            raise ValueError(text)
        return int(a), int(b)
    except ValueError as err:
        raise argparse.ArgumentTypeError("%r is not two integers A:B" % text) from err


def _injection(text: str) -> Tuple[int, str]:
    a, sep, mode = text.partition(":")
    try:
        if not sep:
            raise ValueError(text)
        return int(a), mode
    except ValueError as err:
        raise argparse.ArgumentTypeError("%r is not SEQ:MODE" % text) from err


def argument_parser(prog: str, description: Optional[str] = None) -> argparse.ArgumentParser:
    """The arguments of the core, which the node and the replay both take."""
    ap = argparse.ArgumentParser(prog=prog, description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True, help="the monitor's address (the guest's, on the bridge)")
    ap.add_argument("--port", type=int, default=CLAIM_PORT, help="the monitor's port (default %(default)s; :7151 is the stamp port)")
    ap.add_argument("--stamp", action="store_true", help="mark the target a stamp port (:7151 always is)")
    ap.add_argument("--profile", type=int, default=1, help="the base kind 2 profile (never the demo profile 2)")
    ap.add_argument("--demo", type=_pair, metavar="START_MS:DURATION_MS",
                    help="send profile 2 inside this window from the first packed frame (at most its run_window_max_ms)")
    ap.add_argument("--inject", type=_injection, action="append", default=[], metavar="SEQ:MODE",
                    help="inject MODE at frame SEQ (%s); repeatable" % ", ".join(INJECTIONS))
    ap.add_argument("--pause", type=_pair, metavar="AFTER_SEQ:DURATION_MS",
                    help="pause the intake for DURATION_MS once frame AFTER_SEQ is packed")
    ap.add_argument("--contract", default=str(DEFAULT_CONTRACT), help="the kind 2 contract vss_ctl.py (default %(default)s)")
    ap.add_argument("--out", required=True, help="the run directory for %s (never inside the repo)" % REPLY_LOG)
    return ap


def config_from_args(args: argparse.Namespace) -> Config:
    return Config(host=args.host, port=args.port, profile=args.profile, stamp=bool(args.stamp), demo=args.demo,
                  injections=tuple(args.inject), pause=args.pause)


def work_tree_of(path: Path) -> Optional[Path]:
    """The repo, or any git work tree, that holds this path (a .git entry in it or an ancestor), else None. Symbolic links
    are followed first (a path that is absent is taken as it stands): a link into a work tree is inside it."""
    p = Path(path).expanduser().resolve()
    for d in (p,) + tuple(p.parents):
        if d == REPO or (d / ".git").exists():
            return d
    return None


def open_run_dir(path: str) -> Path:
    """The run directory: never inside the repo or another work tree, and empty if it exists; made if absent."""
    d = Path(path).expanduser().absolute()
    wt = work_tree_of(d)
    if wt is not None:
        raise ClientError("refused: the run directory %s is inside the work tree %s" % (d, wt))
    if d.exists() and (not d.is_dir() or any(d.iterdir())):
        raise ClientError("refused: %s exists and is not an empty directory" % d)
    d.mkdir(parents=True, exist_ok=True)
    return d


def prepare(args: argparse.Namespace) -> Tuple[Config, Any, Path]:
    """The config, the contract and the run directory, in that order, each refusal a ClientError before anything is
    made (the run directory last)."""
    cfg = config_from_args(args)
    try:
        contract = cf.load_contract(args.contract)
    except cf.ContractError as err:
        raise ClientError("refused: %s" % err) from err
    problems = check_config(cfg, contract)
    if problems:
        raise ClientError("refused: " + "; ".join(problems))
    return cfg, contract, open_run_dir(args.out)


def summary_line(prog: str, s: Mapping[str, Any]) -> str:
    n = s["counters"]
    return ("%s: controls=%d replied=%d (accepted=%d rejected=%d) drop=%d lost_on_reconnect=%d reconnects=%d identity=%s"
            % (prog, n["controls"], n["replied"], n["accepted"], n["rejected"], n["drop"], n["lost_on_reconnect"],
               n["reconnects"], "holds" if s["identity"]["holds"] else "BROKEN"))


def exit_code(s: Mapping[str, Any]) -> int:
    return 0 if s["identity"]["holds"] and s.get("fatal") is None else 1
