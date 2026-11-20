"""laneclient.py -- the kind 6 lane claim's client (sdv/lane): a file of lane estimates in, one kind 6 claim per estimate
out to a monitor, every reply logged.

Its rules come from the project's local design notes, not in this tree. It reads estimates a
lane model wrote elsewhere, so it runs no model and needs nothing beyond the standard library; the frame is
laneframe.py's. The connection rules are kind 2's client's (sdv/ctl/ctlclient.py), written again here, single-threaded,
because nothing in sdv/lane imports another sdv package.

    python laneclient.py run --estimates FILE|- --port N [--host 127.0.0.1] [--profile 1] --out replies.jsonl
                             [--reply-timeout-ms 500] [--expect-judge]
    python laneclient.py check --estimates FILE

THE ESTIMATES FILE (JSON Lines, one estimate per camera frame, in time order)
  {"t_ms": int >= 0, "lane_found": bool, "conf": int 0..100, "offset_m", "heading_rad", "curvature_1pm",
   "lane_width_m": number (with lane_found; absent or null without), "v_mps", "yaw_rps": number or null (both null:
   VEH clear), "age_ms": int >= 0}
  Every key is required but the four lane values without a lane; no other key, and none twice. A line that does not
  parse, breaks a field's type or range, holds a value laneframe.encode cannot pack (beyond binary32), or has a t_ms
  below the line before it refuses the whole file before any connection, naming the line. A value outside a profile's
  limits is packed: the monitor judges it.

THE LIVE SOURCE (run --estimates -; POSIX only: on Windows - refuses with exit 2 before any connection and any file)
  The estimates come on stdin as a producer writes them. Each line is held to the file's rules, its t_ms to the line
  before it, and must end in a newline and be at most LIVE_LINE_MAX (4096) bytes with it. Each estimate is packed and
  offered when its line is complete: nothing is paced by t_ms (the file's pacing below is the file's). While a line is
  awaited the socket is served: one select over stdin and the socket. The first bad line ends the source: nothing
  after it is read or packed, the end is as at EOF (the drain below), the summary names the line and why, and the exit
  code is 1. EOF ends the source; a tail with no newline is then a bad line, and a stream with no line holds no estimate,
  as an empty file. The header says the source is stdin, with no sha256 and no count; the summary adds "source":
  {"name": "stdin", "estimates_sha256": the sha256 of the lines taken (each with its newline), "estimates": their count,
  the refused line not among them, "refused": null or {"line": k or null, "why": the reason}}. check reads a file, so
  check - refuses; a file named - is reached as ./-.

PACKING
  Each estimate is one frame by laneframe.encode: seq from 1, tstamp the client's clock (CLOCK_MONOTONIC ns) at the pack,
  LANE set exactly when lane_found (conf and the four lane values packed only then), VEH exactly when v_mps and yaw_rps
  are numbers, age_ms saturated at u16 (counted age_saturated), the profile --profile (one of laneframe.PROFILES: any
  other would get 8 on every frame). A run packs each estimate at its t_ms after the first one's, on the client's clock,
  as a camera would have produced it.

CONNECTION (kind 2's rules)
  Connect at the first frame, never before; after a close, reconnect only when the next frame is to be sent; a failed
  connect (refused, or not complete within CONNECT_TIMEOUT_NS) backs off from BACKOFF_FIRST_NS, doubling, capped at
  BACKOFF_CAP_NS, and a connect resets it. Before each send a non-blocking recv(MSG_PEEK) checks whether the peer has
  closed, and reconnects first if it has. One request outstanding; a frame packed while one is outstanding (or while no
  connection is open) waits in a 1-deep queue, and one packed while one waits replaces it, the replaced one counted drop.
  A frame sent and unanswered when the connection drops is lost_on_reconnect, as is one with no reply within the reply
  timeout (--reply-timeout-ms), after which the client closes the connection itself. A reply must pass
  laneframe.decode_reply and be the request with only p[6] and p[7] written (its seq first); anything else is
  reply_invalid: the frame is lost and the connection closed, as it is for bytes that arrive with nothing outstanding
  (stray_bytes). So the client takes only a reply with nothing but p[6] and p[7] written, as a monitor's plain TCP mode
  (PORT) and its svc mode (PORT svc) reply, and a stamp port (PORT stamp) is no target: the stamp mode, the one mode
  that writes more, puts t_in and t_out at p[8..23] in every reply, so each is reply_invalid and its frame logged as
  lost (without --expect-judge such a run still exits 0, as the identity holds). At the end: no new connect, but one in
  progress is let complete (or time out); the queued frame sent if a connection is open and nothing is outstanding, the
  outstanding one given its reply or the reply timeout (at most twice the reply timeout in all), what is left counted.
  Only an IPv4 literal in 127.0.0.0/8 or RFC 1918 (the bridged guest) is a host; loopback is the default.

ACCOUNTING: packed = replied + drop + lost_on_reconnect, at every end of a run. "Lost" means unanswered, not unjudged.

OUTPUTS
  replies.jsonl (--out; never overwritten, never inside a git work tree): a first line {"header": {...}} (format 1, kind
  6, the estimates file's sha256 and its number of estimates, the host, the port, the profile, the reply timeout,
  --expect-judge, the connection's design values); one line per frame {"seq", "t_ms", "outcome" (replied, drop, lost),
  "verdict", "reason", "name" (the reason's laneframe name), "layout" ("ok" for a reply decode_reply took and that
  echoes the request, the problem for an invalid one, null when no reply came), "expect" (lanerules.judge of the frame
  under --expect-judge, else null), "frame" (the 64 bytes sent, hex)}; a last line {"summary": {"counters", "identity",
  "by_reason" (each reason replied, with its name and count), "judge"}}. The estimates file's path is not written.
  On stdout one summary line; the exit code is 0, or 1 when the identity does not hold, the live source refused a line
  or --expect-judge found a difference or compared nothing, or 2 for a refusal (before any connection and any file).

--expect-judge (tests): each reply compared with lanerules.judge of its frame; "judge" in the summary holds the number
  compared, the number that differ and each difference by seq ({"seq", "got", "want"}). A run that compared nothing (no
  reply came: every frame a drop or lost) exits 1 and its summary line says so, as a check that compared nothing has not
  passed; one that compared replies is held to those, its drops and losses counted. lanerules is imported only then:
  the client packs and sends, and the monitor judges.

check: parses the file as run does and prints what would be sent, one JSON line per frame (its seq, t_ms, LANE, VEH and
  the frame, whose tstamp is 0 here: a run packs its clock), after one line naming the file's sha256. No connection.

DOES NOT DEMONSTRATE: that a lane model finds lanes, or that the estimates are true (the file is taken as written); any
timing (nothing here is a measurement: the tstamp is the client's clock in its own process); that the monitor is in any
control loop (it judges claims beside the vehicle, never steers, brakes or stops it); anything about the guest beyond its
replies.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import ipaddress
import json
import math
import os
import select
import socket
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

# sdv/lane is no package (an __init__.py would put sdv/ on CI's mypy path): laneframe is imported by name, with this
# module's own directory on sys.path, as lanerules.py does.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import laneframe as lf  # noqa: E402

MS = 1_000_000

# --- design values: kind 2's client's (sdv/ctl/ctlclient.py), each with its reason there --------------------------------
REPLY_TIMEOUT_MS = 500             # the default --reply-timeout-ms: kind 2's reply timeout, the monitor's svc deadline
CONNECT_TIMEOUT_NS = 500 * MS      # a connect that hangs costs no more than one unanswered frame
BACKOFF_FIRST_NS = 100 * MS        # after a failed connect: from this, doubling,
BACKOFF_CAP_NS = 2000 * MS         # capped at this
LOOP_WAIT_MAX_S = 0.5              # the longest wait with nothing due
DEFAULT_HOST = "127.0.0.1"
HEADER_FORMAT = 1
LIVE = "-"                         # --estimates -: the live source, stdin
LIVE_LINE_MAX = 4096               # a live line's cap in bytes, its newline included: the lane wire's (a design value)
ON_WINDOWS = os.name == "nt"       # no select() over a pipe there, so the live source refuses

ESTIMATE_KEYS = ("t_ms", "lane_found", "conf", "offset_m", "heading_rad", "curvature_1pm", "lane_width_m", "v_mps",
                 "yaw_rps", "age_ms")
LANE_KEYS = ("offset_m", "heading_rad", "curvature_1pm", "lane_width_m")
VEH_KEYS = ("v_mps", "yaw_rps")
HOST_NETS = tuple(ipaddress.IPv4Network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))

COUNTERS = ("packed", "replied", "accepted", "rejected", "drop", "lost_on_reconnect", "connects", "reconnects",
            "connect_failures", "peer_checks", "sends", "reply_timeouts", "reply_invalid", "stray_bytes", "age_saturated")

DISCONNECTED, CONNECTING, CONNECTED = "disconnected", "connecting", "connected"


class ClientError(RuntimeError):
    """A refusal: the file, the target or the output is not taken, or a call is refused."""


# --- the estimates file --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Estimate:
    """One line of the estimates file, checked: the lane values None exactly when lane_found is false, the vehicle values
    both None or both numbers."""
    line: int
    t_ms: int
    lane_found: bool
    conf: int
    offset_m: Optional[float]
    heading_rad: Optional[float]
    curvature_1pm: Optional[float]
    lane_width_m: Optional[float]
    v_mps: Optional[float]
    yaw_rps: Optional[float]
    age_ms: int


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _number(x: Any) -> Optional[float]:
    """x as a finite float, or None when it is not a finite number (a bool is not a number)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        v = float(x)
    except OverflowError:                       # an integer beyond a double
        return None
    return v if math.isfinite(v) else None


def _binary32_problem(name: str, v: float) -> Optional[str]:
    """Why the slot cannot carry v (None when it can): a finite double beyond binary32's range."""
    try:
        lf.f32_bits(v)
    except lf.FrameError:
        return "%s %r is beyond binary32's range (the frame's slot)" % (name, v)
    return None


def claim_fields(e: Estimate) -> Dict[str, Any]:
    """laneframe.encode's keyword arguments for the estimate (all but seq, tstamp and profile)."""
    kw: Dict[str, Any] = {"age_ms": min(e.age_ms, lf.AGE_MAX)}
    if e.lane_found:
        kw.update(conf=e.conf, offset=e.offset_m, heading=e.heading_rad, curvature=e.curvature_1pm, width=e.lane_width_m)
    if e.v_mps is not None:
        kw.update(speed=e.v_mps, yaw_rate=e.yaw_rps)
    return kw


def pack(e: Estimate, seq: int, tstamp_ns: int, profile: int) -> bytes:
    """The estimate's one frame (laneframe.encode)."""
    return lf.encode(seq=seq, tstamp_ns=tstamp_ns, profile=profile, **claim_fields(e))


def parse_estimate(obj: Any, line: int) -> Estimate:
    """One line's object as an Estimate; ClientError naming the line for anything the format does not take."""
    def bad(why: str) -> ClientError:
        return ClientError("line %d: %s" % (line, why))
    if not isinstance(obj, dict):
        raise bad("not a JSON object")
    unknown = sorted(k for k in obj if k not in ESTIMATE_KEYS)
    if unknown:
        raise bad("unknown key(s) %s (the keys are %s)" % (", ".join(unknown), ", ".join(ESTIMATE_KEYS)))
    lane_found = obj.get("lane_found")
    required = ("t_ms", "lane_found", "conf") + (LANE_KEYS if lane_found is True else ()) + VEH_KEYS + ("age_ms",)
    missing = [k for k in required if k not in obj]
    if missing:
        raise bad("missing key(s) %s" % ", ".join(missing))
    t_ms = obj["t_ms"]
    if not _is_int(t_ms) or t_ms < 0:
        raise bad("t_ms %r is not an int >= 0" % (t_ms,))
    if not isinstance(lane_found, bool):
        raise bad("lane_found %r is not a bool" % (lane_found,))
    conf = obj["conf"]
    if not _is_int(conf) or not 0 <= conf <= lf.CONF_MAX:
        raise bad("conf %r is not an int in 0..%d" % (conf, lf.CONF_MAX))
    lane: Dict[str, Optional[float]] = {}
    for k in LANE_KEYS:
        x = obj.get(k)
        if lane_found:
            v = _number(x)
            if v is None:
                raise bad("%s %r is not a finite number (lane_found is true)" % (k, x))
            lane[k] = v
        elif x is not None:
            raise bad("%s %r with lane_found false (a lane value is absent or null without a lane)" % (k, x))
        else:
            lane[k] = None
    veh: Dict[str, Optional[float]] = {}
    for k in VEH_KEYS:
        x = obj[k]
        veh[k] = None if x is None else _number(x)
        if x is not None and veh[k] is None:
            raise bad("%s %r is not a finite number or null" % (k, x))
    if (veh["v_mps"] is None) != (veh["yaw_rps"] is None):
        which = "v_mps" if veh["v_mps"] is None else "yaw_rps"
        raise bad("%s is null and the other vehicle value is not (v_mps and yaw_rps are both numbers or both null)" % which)
    age = obj["age_ms"]
    if not _is_int(age) or age < 0:
        raise bad("age_ms %r is not an int >= 0" % (age,))
    for k, v in list(lane.items()) + list(veh.items()):
        why = None if v is None else _binary32_problem(k, v)
        if why is not None:
            raise bad(why)
    e = Estimate(line=line, t_ms=t_ms, lane_found=lane_found, conf=conf, offset_m=lane["offset_m"],
                 heading_rad=lane["heading_rad"], curvature_1pm=lane["curvature_1pm"], lane_width_m=lane["lane_width_m"],
                 v_mps=veh["v_mps"], yaw_rps=veh["yaw_rps"], age_ms=age)
    try:
        pack(e, 1, 0, 1)
    except lf.FrameError as err:
        raise bad("laneframe cannot pack it: %s" % err) from err
    return e


def _no_constant(name: str) -> Any:
    raise ValueError("%s is not a JSON number" % name)


def _no_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("the key %r is given twice" % k)
        out[k] = v
    return out


def parse_line(raw: bytes, i: int) -> Estimate:
    """One line's bytes, its newline dropped, as an Estimate; ClientError naming line i for anything the format does not
    take (the time order is the caller's)."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ClientError("line %d: not UTF-8 (%s)" % (i, err)) from err
    try:
        obj = json.loads(text, parse_constant=_no_constant, object_pairs_hook=_no_duplicates)
    except ValueError as err:
        raise ClientError("line %d: not a JSON line the format takes (%s)" % (i, err)) from err
    return parse_estimate(obj, i)


def parse_estimates(data: bytes) -> List[Estimate]:
    """The whole file's estimates, in its order; ClientError naming the first line it refuses (nothing is taken then)."""
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()                             # the last line's newline
    if not lines:
        raise ClientError("the estimates file holds no estimate")
    out: List[Estimate] = []
    for i, raw in enumerate(lines, start=1):
        e = parse_line(raw, i)
        if out and e.t_ms < out[-1].t_ms:
            raise ClientError("line %d: t_ms %d is before line %d's %d (the file is in time order)"
                              % (i, e.t_ms, out[-1].line, out[-1].t_ms))
        out.append(e)
    return out


def read_estimates(path: Any) -> Tuple[List[Estimate], str]:
    """The file's estimates and its sha256 (hex)."""
    try:
        data = Path(path).read_bytes()
    except OSError as err:
        raise ClientError("the estimates file %s cannot be read: %s" % (path, err)) from err
    return parse_estimates(data), hashlib.sha256(data).hexdigest()


# --- the live source -----------------------------------------------------------------------------------------------------

def _unlined(msg: str, line: int) -> str:
    """A refusal's reason without its "line N: " (the live source's summary names the line apart)."""
    head = "line %d: " % line
    return msg[len(head):] if msg.startswith(head) else msg


class LiveSource:
    """run --estimates -: estimates as their lines arrive on a stream. Each line is held to the file's rules, its t_ms to
    the line before it, and must end in a newline within LIVE_LINE_MAX bytes. The first bad line ends the source and
    nothing after it is taken; EOF ends it too (end()), a tail with no newline then a bad line, and a stream with no line
    holds no estimate, as an empty file does."""

    def __init__(self) -> None:
        self.taken = 0
        self.refused: Optional[Dict[str, Any]] = None
        self.ended = False
        self._buf = b""
        self._sha = hashlib.sha256()
        self._last: Optional[Estimate] = None

    @property
    def done(self) -> bool:
        return self.ended or self.refused is not None

    def refuse(self, line: Optional[int], why: str) -> None:
        """End the source at this line (None: no line) for this reason; the first refusal stands."""
        if self.refused is None:
            self.refused = {"line": line, "why": why}
        self._buf = b""

    def push(self, data: bytes) -> List[Estimate]:
        """The estimates of the lines these bytes complete, in order, up to the source's first bad line."""
        out: List[Estimate] = []
        if self.done:
            return out
        self._buf += data
        while self.refused is None:
            k = self.taken + 1
            nl = self._buf.find(b"\n")
            if nl < 0:
                if len(self._buf) >= LIVE_LINE_MAX:
                    self.refuse(k, "%d bytes and no newline: a line is at most %d bytes, its newline included"
                                % (len(self._buf), LIVE_LINE_MAX))
                break
            raw, self._buf = self._buf[:nl + 1], self._buf[nl + 1:]
            if len(raw) > LIVE_LINE_MAX:
                self.refuse(k, "%d bytes: a line is at most %d bytes, its newline included" % (len(raw), LIVE_LINE_MAX))
                break
            sha = self._sha.copy()
            sha.update(raw)
            try:
                e = parse_line(raw[:-1], k)
            except ClientError as err:
                self.refuse(k, _unlined(str(err), k))
                break
            if self._last is not None and e.t_ms < self._last.t_ms:
                self.refuse(k, "t_ms %d is before line %d's %d (the estimates are in time order)"
                            % (e.t_ms, self._last.line, self._last.t_ms))
                break
            self._sha = sha
            self.taken = k
            self._last = e
            out.append(e)
        return out

    def end(self) -> None:
        """EOF: the source ends; a tail with no newline is a bad line, and a stream with no line holds no estimate."""
        if self.done:
            return
        if self._buf:
            self.refuse(self.taken + 1, "%d bytes and no newline at EOF: a line ends in a newline" % len(self._buf))
        elif self.taken == 0:
            self.refuse(None, "the source holds no estimate (EOF before its first line)")
        self.ended = True

    def summary(self) -> Dict[str, Any]:
        """The summary's "source": the sha256 of the lines taken, each with its newline, their count, and the refusal."""
        return {"name": "stdin", "estimates_sha256": self._sha.hexdigest(), "estimates": self.taken,
                "refused": None if self.refused is None else dict(self.refused)}


# --- the target ------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    """A run's target and options (2's command line)."""
    port: int
    host: str = DEFAULT_HOST
    profile: int = 1
    reply_timeout_ms: int = REPLY_TIMEOUT_MS
    expect_judge: bool = False


def host_problem(host: Any) -> Optional[str]:
    """Why this is not a host the client sends to (None when it is): an IPv4 literal in 127.0.0.0/8 (loopback) or RFC 1918
    (10/8, 172.16/12, 192.168/16: the bridged guest), and nothing else; no name is resolved."""
    if not isinstance(host, str):
        return "host %r is not an IPv4 literal" % (host,)
    try:
        ip = ipaddress.IPv4Address(host)
    except ValueError:
        return "host %r is not an IPv4 literal (no name is resolved)" % (host,)
    if not any(ip in n for n in HOST_NETS):
        return "host %s is neither loopback (127.0.0.0/8) nor RFC 1918 (the bridged guest)" % host
    return None


def check_config(cfg: Config) -> List[str]:
    """Every reason the client refuses this target (an empty list: it takes it)."""
    problems: List[str] = []
    hp = host_problem(cfg.host)
    if hp is not None:
        problems.append(hp)
    if not _is_int(cfg.port) or not 0 < cfg.port < 65536:
        problems.append("port %r is not in 1..65535" % (cfg.port,))
    if not _is_int(cfg.profile) or cfg.profile not in lf.PROFILES:
        problems.append("profile %r is not in laneframe.PROFILES (%s): every frame would get 8"
                        % (cfg.profile, ", ".join(str(p) for p in sorted(lf.PROFILES))))
    if not _is_int(cfg.reply_timeout_ms) or cfg.reply_timeout_ms <= 0:
        problems.append("reply timeout %r ms is not a positive int" % (cfg.reply_timeout_ms,))
    return problems


def identity(n: Mapping[str, int]) -> Dict[str, Any]:
    """packed = replied + drop + lost_on_reconnect, with its terms."""
    return {"packed": n["packed"], "replied": n["replied"], "drop": n["drop"], "lost_on_reconnect": n["lost_on_reconnect"],
            "holds": n["packed"] == n["replied"] + n["drop"] + n["lost_on_reconnect"]}


# --- the client ------------------------------------------------------------------------------------------------------------

@dataclass
class Packed:
    seq: int
    t_ms: int
    frame: bytes
    expect: Optional[Tuple[int, int]] = None
    layout: Optional[str] = None        # an invalid reply's problem, written on the lost frame's line


class LaneClient:
    """The 1-deep queue, the connection and the accounting of one run. Single-threaded: offer() packs and queues,
    pump() handles the timeouts and a send at the clock's now, wait() waits for the socket (and the live source's
    stream), then pumps."""

    def __init__(self, cfg: Config, *, clock: Callable[[], int] = time.monotonic_ns, reply_log: Optional[Any] = None,
                 estimates_sha256: str = "", frames: int = 0, live: bool = False) -> None:
        problems = check_config(cfg)
        if problems:
            raise ClientError("refused: " + "; ".join(problems))
        self.cfg = cfg
        self.clock = clock
        self.reply_timeout_ns = cfg.reply_timeout_ms * MS
        self.n: Dict[str, int] = {k: 0 for k in COUNTERS}
        self.by_reason: Dict[int, int] = {}
        self.compared = 0
        self.differences: List[Dict[str, Any]] = []
        self.next_seq = 1
        self.queued: Optional[Packed] = None
        self.outstanding: Optional[Packed] = None
        self.next_connect_ns = 0
        self._backoff_ns = BACKOFF_FIRST_NS
        self._state = DISCONNECTED
        self._sock: Optional[socket.socket] = None
        self._rbuf = b""
        self._reply_due = 0
        self._connect_due = 0
        self._draining = False
        self._stopped = False
        self._source: Optional[Dict[str, Any]] = None
        self._judge: Optional[Callable[[bytes], Tuple[int, int]]] = None
        if cfg.expect_judge:
            import lanerules                    # the tests' oracle, only for --expect-judge (the module docstring)
            self._judge = lanerules.judge
        src: Dict[str, Any] = {"source": "stdin"} if live else {"estimates_sha256": estimates_sha256, "frames": frames}
        self.header: Dict[str, Any] = {
            "format": HEADER_FORMAT, "kind": lf.KIND_LANE, **src,
            "host": cfg.host, "port": cfg.port, "profile": cfg.profile, "reply_timeout_ms": cfg.reply_timeout_ms,
            "expect_judge": bool(cfg.expect_judge),
            "design": {"connect_timeout_ms": CONNECT_TIMEOUT_NS // MS, "backoff_first_ms": BACKOFF_FIRST_NS // MS,
                       "backoff_cap_ms": BACKOFF_CAP_NS // MS},
        }
        self._log: Optional[IO[str]] = None
        if reply_log is not None:
            try:
                self._log = open(reply_log, "x", encoding="utf-8", newline="\n")
            except FileExistsError as err:
                raise ClientError("refused: the reply log %s exists (a reply log is never overwritten)" % reply_log) from err
            except OSError as err:
                raise ClientError("refused: the reply log %s cannot be made: %s" % (reply_log, err)) from err
            self._write({"header": self.header})

    # ---- state seen from outside

    @property
    def connected(self) -> bool:
        return self._state == CONNECTED

    def summary(self) -> Dict[str, Any]:
        judge = None
        if self._judge is not None:
            judge = {"compared": self.compared, "differ": len(self.differences), "differences": list(self.differences)}
        s: Dict[str, Any] = {
            "counters": dict(self.n), "identity": identity(self.n),
            "by_reason": [{"reason": r, "name": lf.REASON_NAMES.get(r), "n": k} for r, k in sorted(self.by_reason.items())],
            "judge": judge}
        if self._source is not None:
            s["source"] = dict(self._source)
        return s

    # ---- the intake

    def offer(self, e: Estimate) -> int:
        """Pack the estimate's frame at the clock's now and queue it (a frame waiting is replaced, and counted drop);
        returns its seq. It is sent by pump() or wait()."""
        if self._stopped:
            raise ClientError("the client is stopped")
        seq = self.next_seq
        frame = pack(e, seq, self.clock(), self.cfg.profile)
        self.next_seq += 1
        self.n["packed"] += 1
        if e.age_ms > lf.AGE_MAX:
            self.n["age_saturated"] += 1
        p = Packed(seq=seq, t_ms=e.t_ms, frame=frame, expect=None if self._judge is None else self._judge(frame))
        if self.queued is not None:
            self._drop(self.queued)
        self.queued = p
        return seq

    # ---- outcomes

    def _write(self, obj: Mapping[str, Any]) -> None:
        if self._log is not None:
            self._log.write(json.dumps(obj, separators=(",", ":"), allow_nan=False) + "\n")
            self._log.flush()

    def _outcome(self, p: Packed, outcome: str, verdict: Optional[int], reason: Optional[int]) -> None:
        self._write({"seq": p.seq, "t_ms": p.t_ms, "outcome": outcome, "verdict": verdict, "reason": reason,
                     "name": None if reason is None else lf.REASON_NAMES.get(reason), "layout": p.layout,
                     "expect": None if p.expect is None else list(p.expect), "frame": p.frame.hex()})

    def _drop(self, p: Packed) -> None:
        self.n["drop"] += 1
        self._outcome(p, "drop", None, None)

    def _lost(self, p: Packed) -> None:
        self.n["lost_on_reconnect"] += 1
        self._outcome(p, "lost", None, None)

    # ---- the loop

    def pump(self) -> None:
        """The timeouts and a send attempt at the clock's now; never blocks."""
        if self._stopped:
            return
        now = self.clock()
        self._check_timeouts(now)
        self._try_send(now)

    def wait(self, timeout_s: float, fds: Sequence[int] = ()) -> List[int]:
        """Wait up to timeout_s for the socket (a reply, a close, a connect completing) or for one of fds to be readable
        (the live source's stream: one select over both), handle the socket, then pump; returns the fds readable."""
        if self._stopped:
            return []
        sock, state = self._sock, self._state
        timeout_s = max(0.0, timeout_s)
        r: List[Any] = []
        if sock is None and not fds:
            time.sleep(timeout_s)
        else:
            rl: List[Any] = list(fds) + ([sock] if sock is not None and state == CONNECTED else [])
            wl: List[Any] = [sock] if sock is not None and state == CONNECTING else []
            try:
                r, w, x = select.select(rl, wl, wl, timeout_s)          # a failed connect shows in x on Windows
            except (OSError, ValueError):
                r, w, x = [], [], []
            if sock is not None and sock is self._sock:
                if self._state == CONNECTING and (sock in w or sock in x):
                    self._connect_done(self.clock())
                elif self._state == CONNECTED and sock in r:
                    self._readable()
        self.pump()
        return [f for f in fds if f in r]

    def next_due_s(self) -> float:
        """How long the loop may wait before something is due (a reply's timeout, a connect's, the next connect)."""
        now = self.clock()
        due = [now + int(LOOP_WAIT_MAX_S * 1e9)]
        if self.outstanding is not None:
            due.append(self._reply_due)
        if self._state == CONNECTING:
            due.append(self._connect_due)
        if self._state == DISCONNECTED and self.queued is not None:
            due.append(self.next_connect_ns)
        return max(0, min(due) - now) / 1e9

    def stop(self, drain: bool = True, source: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """End the run: (with drain) the drain, then the close; the queued frame left is a drop and the outstanding one
        lost, so the identity holds. The live source's summary (source) goes into the summary as "source". Writes the
        summary line and returns it."""
        if self._stopped:
            return self.summary()
        if drain:
            self._drain()
        self._close("stop")
        if self.queued is not None:
            p, self.queued = self.queued, None
            self._drop(p)
        self._stopped = True
        if source is not None:
            self._source = dict(source)
        s = self.summary()
        self._write({"summary": s})
        if self._log is not None:
            self._log.close()
            self._log = None
        return s

    def _drain(self) -> None:
        """No new connect, but one in progress is let complete (or time out), so a run's last estimate is not a drop for
        its connect alone (a file of one estimate; an estimate after the monitor closed an idle connection): the queued
        frame is sent if a connection is open and nothing is outstanding, and the outstanding frame gets its reply or the
        reply timeout; at most twice the reply timeout on the client's clock, and as long in real time (a clock that
        stands still, as a test's may, cannot hold a stop forever)."""
        self._draining = True
        span = 2 * self.reply_timeout_ns
        end = self.clock() + span
        real_end = time.monotonic() + span / 1e9
        while True:
            now = self.clock()
            self._check_timeouts(now)
            if now < end:
                self._try_send(now)
            connecting = self._state == CONNECTING and self.queued is not None
            if self.outstanding is None and not connecting:
                return
            if time.monotonic() >= real_end or now >= end:
                return
            due = self._reply_due if self.outstanding is not None else self._connect_due
            self.wait(min(0.05, max(0.0, (due - now) / 1e9)))

    def _check_timeouts(self, now: int) -> None:
        if self.outstanding is not None and now >= self._reply_due:
            self.n["reply_timeouts"] += 1
            self._close("reply timeout")
        if self._state == CONNECTING and now >= self._connect_due:
            self._abandon_connect(now)

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
        try:
            sent = self._sock.send(p.frame)
        except OSError:
            sent = -1
        self.outstanding = p
        if sent != len(p.frame):
            self._close("send failed or short")
            return
        self.n["sends"] += 1
        self._reply_due = now + self.reply_timeout_ns
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
        except OSError as e:
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
        if self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:
            s, self._sock = self._sock, None
            self._connected(s)
        else:
            self._abandon_connect(now)

    def _abandon_connect(self, now: int) -> None:
        s, self._sock = self._sock, None
        self._state = DISCONNECTED
        if s is not None:
            s.close()
        self._connect_failed(now)

    def _connect_failed(self, now: int) -> None:
        self.n["connect_failures"] += 1
        self.next_connect_ns = now + self._backoff_ns
        self._backoff_ns = min(2 * self._backoff_ns, BACKOFF_CAP_NS)

    def _connected(self, s: socket.socket) -> None:
        self._sock = s
        self._state = CONNECTED
        self._rbuf = b""
        self.n["connects"] += 1
        if self.n["connects"] > 1:
            self.n["reconnects"] += 1
        self._backoff_ns = BACKOFF_FIRST_NS

    def _close(self, why: str) -> None:
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
            self._lost(out)

    def _reply_problem(self, p: Packed, data: bytes) -> Optional[str]:
        """Why these 64 bytes are not p's reply (None when they are): the seq first (bytes 0..7), then decode_reply's
        layout check, then every later byte but p[6] and p[7] the request's."""
        rseq = struct.unpack_from("<Q", data, 0)[0]
        if rseq != p.seq:
            return "a reply with seq %d to the request with seq %d" % (rseq, p.seq)
        try:
            lf.decode_reply(data)
        except lf.FrameError as err:
            return str(err)
        h = lf.FRAME_HEADER_BYTES
        free = (h + lf.P_VERDICT, h + lf.P_REASON)
        diff = [i for i in range(8, lf.FRAME_TOTAL_BYTES) if i not in free and data[i] != p.frame[i]]
        if diff:
            return "bytes %s differ from the request's (seq %d)" % (diff[:8], p.seq)
        return None

    def _readable(self) -> None:
        assert self._sock is not None
        try:
            data = self._sock.recv(lf.FRAME_TOTAL_BYTES - len(self._rbuf))
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._close("recv failed")
            return
        if not data:
            self._close("peer closed")
            return
        if self.outstanding is None:
            self.n["stray_bytes"] += len(data)
            self._close("stray bytes with nothing outstanding")
            return
        self._rbuf += data
        if len(self._rbuf) < lf.FRAME_TOTAL_BYTES:
            return
        data, self._rbuf = self._rbuf, b""
        p = self.outstanding
        problem = self._reply_problem(p, data)
        if problem is not None:
            self.n["reply_invalid"] += 1
            p.layout = problem
            self._close("invalid reply")
            return
        self.outstanding = None
        h = lf.FRAME_HEADER_BYTES
        verdict, reason = data[h + lf.P_VERDICT], data[h + lf.P_REASON]
        self.n["replied"] += 1
        self.n["accepted" if verdict == lf.V_ACCEPT else "rejected"] += 1
        self.by_reason[reason] = self.by_reason.get(reason, 0) + 1
        if p.expect is not None:
            self.compared += 1
            if (verdict, reason) != tuple(p.expect):
                self.differences.append({"seq": p.seq, "got": [verdict, reason], "want": list(p.expect)})
        p.layout = "ok"
        self._outcome(p, "replied", verdict, reason)


def play(client: LaneClient, estimates: Sequence[Estimate]) -> None:
    """Offer each estimate at its t_ms after the first one's on the client's clock, handling the socket in between."""
    if not estimates:
        return
    start, t0 = client.clock(), estimates[0].t_ms
    for e in estimates:
        due = start + (e.t_ms - t0) * MS
        while True:
            now = client.clock()
            if now >= due:
                break
            client.wait(min((due - now) / 1e9, client.next_due_s()))
        client.offer(e)
        client.pump()


def play_live(client: LaneClient, source: LiveSource, fd: int) -> None:
    """Offer each estimate as soon as its line is complete (its t_ms carried, never waited for), serving the socket while
    a line is awaited: one select over the stream and the socket. Returns when the source has ended."""
    while not source.done:
        if fd not in client.wait(client.next_due_s(), (fd,)):
            continue
        try:
            data = os.read(fd, LIVE_LINE_MAX)
        except (BlockingIOError, InterruptedError):
            continue
        except OSError as err:
            source.refuse(source.taken + 1, "stdin cannot be read: %s" % err)
            break
        if not data:
            source.end()
        for e in source.push(data):
            client.offer(e)
            client.pump()


def run_live(client: LaneClient, fd: int) -> int:
    """The live source's run: play_live, then the stop as at EOF (the drain); prints the summary line and returns the
    exit code (1 when the source refused a line)."""
    source = LiveSource()
    try:
        play_live(client, source, fd)
    finally:
        s = client.stop(source=source.summary())
    print(summary_line(s), flush=True)
    return exit_code(s)


def stdin_fd() -> int:
    """The live source's descriptor, stdin's; ClientError when stdin is not open."""
    try:
        fd = sys.stdin.fileno()
        os.fstat(fd)
    except (AttributeError, OSError, ValueError) as err:
        raise ClientError("refused: --estimates - and stdin is not open (%s)" % err) from err
    return fd


# --- the command line --------------------------------------------------------------------------------------------------

def work_tree_of(path: Path) -> Optional[Path]:
    """The git work tree that holds this path (a .git entry in it or an ancestor), else None; links followed first."""
    p = Path(path).expanduser().resolve()
    for d in (p,) + tuple(p.parents):
        if (d / ".git").exists():
            return d
    return None


def open_out(path: str) -> Path:
    """The reply log's path: not inside a git work tree (a run's replies are a result, kept out of every tree), not an
    existing file, in a directory that exists."""
    p = Path(path).expanduser().absolute()
    wt = work_tree_of(p)
    if wt is not None:
        raise ClientError("refused: the reply log %s is inside the work tree %s" % (p, wt))
    if p.exists():
        raise ClientError("refused: the reply log %s exists (a reply log is never overwritten)" % p)
    if not p.parent.is_dir():
        raise ClientError("refused: the reply log's directory %s does not exist" % p.parent)
    return p


def summary_line(s: Mapping[str, Any]) -> str:
    n = s["counters"]
    line = ("laneclient: packed=%d replied=%d (accepted=%d rejected=%d) drop=%d lost_on_reconnect=%d reconnects=%d "
            "identity=%s" % (n["packed"], n["replied"], n["accepted"], n["rejected"], n["drop"], n["lost_on_reconnect"],
                             n["reconnects"], "holds" if s["identity"]["holds"] else "BROKEN"))
    if s["judge"] is not None:
        line += " judge: compared=%d differ=%d" % (s["judge"]["compared"], s["judge"]["differ"])
        if s["judge"]["compared"] == 0:
            line += " (nothing compared)"
    src = s.get("source")
    if src is not None:
        line += " source=stdin estimates=%d sha256=%s" % (src["estimates"], src["estimates_sha256"])
        ref = src["refused"]
        if ref is not None:
            line += " refused: %s%s" % ("" if ref["line"] is None else "line %d: " % ref["line"],
                                        json.dumps(ref["why"])[1:-1])   # JSON-escaped: a producer's key name can be in it
    return line


def exit_code(s: Mapping[str, Any]) -> int:
    """0, or 1 when the identity does not hold, when the live source refused a line, or under --expect-judge when a
    difference was found or nothing was compared (a check that compared nothing has not passed)."""
    src = s.get("source")
    if src is not None and src["refused"] is not None:
        return 1
    if s["judge"] is not None and s["judge"]["compared"] == 0:
        return 1
    differ = s["judge"]["differ"] if s["judge"] is not None else 0
    return 0 if s["identity"]["holds"] and differ == 0 else 1


def argument_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="laneclient.py", description="The kind 6 lane claim's client (sdv/lane/README.md).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="send one kind 6 claim per estimate to a monitor and log every reply")
    r.add_argument("--estimates", required=True, help="the estimates file (JSON Lines), or - for stdin (POSIX only)")
    r.add_argument("--port", type=int, required=True, help="the monitor's port")
    r.add_argument("--host", default=DEFAULT_HOST, help="an IPv4 literal, loopback or RFC 1918 (default %(default)s)")
    r.add_argument("--profile", type=int, default=1, help="the kind 6 profile (default %(default)s)")
    r.add_argument("--out", required=True, help="the reply log replies.jsonl (new, outside every git work tree)")
    r.add_argument("--reply-timeout-ms", type=int, default=REPLY_TIMEOUT_MS, help="default %(default)s")
    r.add_argument("--expect-judge", action="store_true", help="compare each reply with lanerules.judge (tests)")
    c = sub.add_parser("check", help="parse the file and print what would be sent; no connection")
    c.add_argument("--estimates", required=True, help="the estimates file (JSON Lines; a file named - is ./-)")
    return ap


def check(estimates: Sequence[Estimate], sha256: str, profile: int = 1) -> int:
    print("laneclient: check: %d estimates, sha256 %s, profile %d; each frame below with tstamp 0 (a run packs its clock)"
          % (len(estimates), sha256, profile))
    for seq, e in enumerate(estimates, start=1):
        print(json.dumps({"seq": seq, "t_ms": e.t_ms, "lane": e.lane_found, "veh": e.v_mps is not None,
                          "frame": pack(e, seq, 0, profile).hex()}, separators=(",", ":")))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = argument_parser().parse_args(argv)
    live = args.estimates == LIVE
    estimates: List[Estimate] = []
    sha, fd = "", -1
    try:
        if args.cmd == "check":
            if args.estimates == LIVE:
                raise ClientError("check reads a file, and - is stdin (a file named - is reached as ./-)")
            estimates, sha = read_estimates(args.estimates)
            return check(estimates, sha)
        if live and ON_WINDOWS:
            raise ClientError("--estimates - (stdin) is POSIX only: the live source selects over a pipe, which Windows "
                              "does not offer; give a file")
        cfg = Config(port=args.port, host=args.host, profile=args.profile, reply_timeout_ms=args.reply_timeout_ms,
                     expect_judge=bool(args.expect_judge))
        problems = check_config(cfg)
        if problems:
            raise ClientError("refused: " + "; ".join(problems))
        if live:
            fd = stdin_fd()
        else:
            estimates, sha = read_estimates(args.estimates)
        out = open_out(args.out)
        client = LaneClient(cfg, reply_log=out, estimates_sha256=sha, frames=len(estimates), live=live)
    except ClientError as err:
        msg = str(err)
        print("laneclient: %s" % (msg if msg.startswith("refused") else "refused: " + msg), file=sys.stderr)
        return 2
    if live:
        return run_live(client, fd)
    try:
        play(client, estimates)
    finally:
        s = client.stop()
    print(summary_line(s), flush=True)
    return exit_code(s)


if __name__ == "__main__":
    sys.exit(main())
