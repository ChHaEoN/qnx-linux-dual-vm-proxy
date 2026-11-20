"""C2b S4: the lane claim client alone (sdv/lane/laneclient.py), against a fake monitor written here. Its rules come from
the project's local design notes, not in this tree.

What is tested, and how:

- The estimates file (2): an estimate with a lane and vehicle values, one without either, a float field written as a
  JSON integer; every refusal (a line that does not parse, a key missing, unknown or given twice, each field's type and
  range, a lane value with lane_found false, speed and yaw rate one without the other, a value beyond binary32, a t_ms
  before the line above, an empty file, a blank line, bytes that are not UTF-8) refuses the whole file and names the line.
- The packing: one frame per estimate by laneframe.encode, seq from 1, tstamp the client's clock at the pack, LANE from
  lane_found and VEH from the vehicle values (each of the four combinations), conf and the lane values packed only with
  LANE, the age saturated at u16 and counted; every frame a well-formed request.
- The host check: loopback and RFC 1918 IPv4 literals taken (near each block's both ends), anything else refused (a
  public or documentation address, link-local, a name, IPv6); the port, the profile and the reply timeout refused out of
  range.
- The connection rules and the accounting, against a loopback peer that answers as lanerules judges (or as a test tells
  it): no connect before the first frame, one request outstanding and the 1-deep queue's drop, a frame in flight at a
  close lost, the reply timeout (the default and a given one) on a clock the test moves and the loop's wait bounded by
  it, a reply with another seq or tstamp or a layout fault invalid, a reply read in two parts taken at its 64th byte (a
  byte after it stray), the lazy reconnect after an idle close, the peer-closed check before a send (a peek that fails
  is a close), the connect timeout and the backoff (the loop's wait bounded by its end), stray bytes, the stop's drain
  (a connect in progress let complete) and its refusal to connect anew (a frame left queued a drop, with its line).
  Every run that ends is held to packed = replied + drop + lost_on_reconnect, and a broken identity exits 1 and its
  summary line says BROKEN.
- replies.jsonl: the header (format, kind, the estimates' sha256, the target, the profile, the reply timeout,
  --expect-judge, the connection's design values), one line per frame (seq, t_ms, outcome, verdict, reason, its name,
  the reply's layout check, the frame), the summary (the counters, the identity, verdicts by reason); never overwritten.
- --expect-judge: each reply compared with lanerules.judge of its frame, each difference (a verdict, a reason) counted
  and named by seq, and the run's exit 1 for one, or when nothing was compared (no monitor: every frame a drop).
- The command line: run paced by t_ms (the first estimate at once, each later one at its offset, each wait bounded by
  next_due_s), a file of one estimate sent, check printing what would be sent with no connection, every refusal exit 2
  before any connection or file.
- What sdv/lane/README.md and laneclient.py's module docstring say: the client takes only a reply with nothing but p[6]
  and p[7] written, as a monitor's plain TCP and svc modes reply, so a stamp port is no target (and against a peer that
  answers as the stamp mode does, every frame is lost as reply_invalid, the run's exit 0 without --expect-judge and 1
  with it); make lane and ifs-lane.build define the guest build and its ports, with native-test limits stated.
- The live source (run --estimates -), its stdin an os.pipe a thread writes, every
  estimate made up: each line held to the file's rules and to the line before it, ending in a newline and at most 4096
  bytes with it (4096 taken in one write or two, 4097 refused, 4096 with no newline refused before more comes); each
  offered when its line is complete, never paced by t_ms; a reply taken while the producer is silent (one select over
  the pipe and the socket); a silence over the peer's deadline reconnected at the next line; the first bad line ending
  the source (nothing after it packed, the summary naming it, exit 1, the pipe still open), an unterminated tail at EOF a
  bad line, EOF ending the run through the drain, an empty source refused; the summary line one ASCII line whatever the
  refused line holds (its reason JSON-escaped: a newline, a non-ASCII character, a lone surrogate); the header saying
  stdin with no sha256 and no count, the summary adding the sha256 and the count of the lines taken; the identity with a
  drop and frames left at EOF; exit 2 on Windows (and ON_WINDOWS's assignment true for os.name "nt" alone, on every
  host), with stdin not open, and for check -; a file named - reached as ./-; the file mode's header and summary keys,
  and its outputs the base's byte for byte but for each frame's tstamp (the base's laneclient.py by git show).
- Earlier edge cases: next_due_s with nothing queued after a failed connect (om07), an interrupted peek
  (om11), and the drain's span of twice the reply timeout, on a hand clock the drain's own waits move.

What this does NOT show: that the native monitor answers the client's claims as lanerules judges them, from a file or
from stdin (tests/test_sdv_laneclient_contract.py); anything about a lane model, a camera or CARLA; any timing (the waits
below only bound when an event may come on a loaded host, and the pacing is held only from below).

Standard library only: runs on Windows and in WSL alike, but for the live source's tests (POSIX: a select over a pipe;
they skip on Windows) and the comparison with the base. That one runs git, so it skips, saying why, where git cannot
give the base: where the worktree's .git file names a Windows path and the test does not run on Windows (WSL), in a tree
with no .git (no git is then asked), where git cannot start, and where the base commit is not in the repository (each
skip held by a test with git a stand-in). So a skip there is no pass: it is run by name on Windows, where it passes.
"""
import ast
import errno
import hashlib
import importlib
import importlib.util
import json
import os
import re
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LANE_DIR = REPO / "sdv" / "lane"
CLIENT_FILE = LANE_DIR / "laneclient.py"

MS = 1_000_000
H = 16
T0 = 10 ** 12
SLACK_S = 5.0          # how long a wait may run on a loaded host before the test gives up
KEYS = ("t_ms", "lane_found", "conf", "offset_m", "heading_rad", "curvature_1pm", "lane_width_m", "v_mps", "yaw_rps",
        "age_ms")


# ============================================================ loading the package

def _import(name):
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        if str(LANE_DIR) not in sys.path:
            sys.path.insert(0, str(LANE_DIR))
        return importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved


@pytest.fixture(scope="module")
def lc():
    return _import("laneclient")


@pytest.fixture(scope="module")
def lf():
    return _import("laneframe")


@pytest.fixture(scope="module")
def lr():
    return _import("lanerules")


# ============================================================ helpers

class Clock:
    """A clock the test moves by hand, in ns."""

    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, ms=0, ns=0):
        self.t += ms * MS + ns


def row(**over):
    """An estimate line's object: a lane found, inside profile 1's limits, with vehicle values; `over` replaces or adds
    keys, and a value DROP removes its key."""
    r = {"t_ms": 0, "lane_found": True, "conf": 90, "offset_m": 0.1, "heading_rad": 0.0, "curvature_1pm": 0.001,
         "lane_width_m": 3.5, "v_mps": 10.0, "yaw_rps": 0.0, "age_ms": 20}
    r.update(over)
    return {k: v for k, v in r.items() if v is not DROP}


DROP = object()
NO_LANE = dict(lane_found=False, offset_m=DROP, heading_rad=DROP, curvature_1pm=DROP, lane_width_m=DROP)


def jsonl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows).encode("utf-8")


def est(lc, **over):
    return lc.parse_estimate(row(**over), 1)


def client(lc, port=1, clock=None, reply_log=None, **kw):
    cfg = lc.Config(port=port, **kw)
    return lc.LaneClient(cfg, clock=clock or Clock(), reply_log=reply_log, estimates_sha256="0" * 64, frames=0)


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


def closed_out(c, drain=True):
    """Stop the client and hold the run to the identity: every packed frame replied, dropped or lost, nothing left."""
    s = c.stop(drain=drain)
    n = c.n
    assert n["packed"] == n["replied"] + n["drop"] + n["lost_on_reconnect"], n
    assert s["identity"]["holds"] and s["identity"]["packed"] == n["packed"]
    assert c.queued is None and c.outstanding is None and not c.connected
    return s


def log_lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines()]


def free_port():
    """A loopback port nothing listens on (bound, then released)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ============================================================ the fake monitor

class FakeMonitor:
    """A loopback peer in place of the monitor's svc mode: one connection at a time, each recorded (the frames it read
    and how it ended). `script(conn_index, frame_index, frame)` says what to do with each complete frame: "reply" (the
    frame with p[6], p[7] written as lanerules judges it), "close", "none", ("raw", bytes) sent as they are, or ("wait",
    event), which waits for the test to set the event; a list of those is done in order. idle_close_s closes a connection
    that has no complete frame for that long, as svc's deadline does."""

    def __init__(self, lr, script=None, idle_close_s=None):
        self.lr = lr
        self.script = script or (lambda ci, fi, f: "reply")
        self.idle_close_s = idle_close_s
        self.conns = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lsock.bind(("127.0.0.1", 0))
        self.lsock.listen(8)
        self.port = self.lsock.getsockname()[1]
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def answer(self, f, verdict_reason=None):
        b = bytearray(f)
        b[H + 6], b[H + 7] = verdict_reason if verdict_reason is not None else self.lr.judge(f)
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
                    elif isinstance(a, tuple) and a[0] == "wait":
                        a[1].wait(SLACK_S)
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
def monitor(lr):
    made = []

    def make(**kw):
        m = FakeMonitor(lr, **kw)
        made.append(m)
        return m
    yield make
    for m in made:
        m.close()


# ============================================================ 2: the estimates file

def test_an_estimate_with_a_lane_and_vehicle_values_parses_to_its_fields(lc):
    e = lc.parse_estimate(row(t_ms=40, conf=77, offset_m=-0.25, heading_rad=0.02, curvature_1pm=-0.004,
                              lane_width_m=3.6, v_mps=12.5, yaw_rps=-0.01, age_ms=33), 7)
    assert (e.line, e.t_ms, e.lane_found, e.conf, e.age_ms) == (7, 40, True, 77, 33)
    assert (e.offset_m, e.heading_rad, e.curvature_1pm, e.lane_width_m) == (-0.25, 0.02, -0.004, 3.6)
    assert (e.v_mps, e.yaw_rps) == (12.5, -0.01)


@pytest.mark.parametrize("absent", ["absent", "null"])
def test_lane_found_false_takes_the_lane_values_absent_or_null(lc, absent):
    lane = {k: (DROP if absent == "absent" else None) for k in ("offset_m", "heading_rad", "curvature_1pm", "lane_width_m")}
    e = lc.parse_estimate(row(lane_found=False, conf=12, v_mps=None, yaw_rps=None, **lane), 1)
    assert (e.lane_found, e.conf, e.offset_m, e.heading_rad, e.curvature_1pm, e.lane_width_m) == (False, 12, None, None, None, None)
    assert (e.v_mps, e.yaw_rps) == (None, None)


def test_a_float_field_takes_a_json_integer(lc):
    e = lc.parse_estimate(json.loads('{"t_ms": 0, "lane_found": true, "conf": 90, "offset_m": 0, "heading_rad": 0, '
                                     '"curvature_1pm": 0, "lane_width_m": 3, "v_mps": 10, "yaw_rps": 0, "age_ms": 0}'), 1)
    assert (e.offset_m, e.lane_width_m, e.v_mps) == (0.0, 3.0, 10.0)
    assert all(isinstance(x, float) for x in (e.offset_m, e.heading_rad, e.curvature_1pm, e.lane_width_m, e.v_mps, e.yaw_rps))


REFUSED_ROWS = [
    ("t_ms missing", row(t_ms=DROP), "t_ms"),
    ("t_ms a float", row(t_ms=1.5), "t_ms"),
    ("t_ms a bool", row(t_ms=True), "t_ms"),
    ("t_ms negative", row(t_ms=-1), "t_ms"),
    ("t_ms a string", row(t_ms="0"), "t_ms"),
    ("lane_found missing", row(lane_found=DROP), "lane_found"),
    ("lane_found an int", row(lane_found=1), "lane_found"),
    ("lane_found null", row(lane_found=None), "lane_found"),
    ("conf missing", row(conf=DROP), "conf"),
    ("conf a float", row(conf=90.0), "conf"),
    ("conf a bool", row(conf=True), "conf"),
    ("conf over 100", row(conf=101), "conf"),
    ("conf negative", row(conf=-1), "conf"),
    ("conf missing with no lane", row(conf=DROP, **NO_LANE), "conf"),
    ("conf over 100 with no lane (never packed, still refused)", row(conf=101, **NO_LANE), "conf"),
    ("offset_m missing with a lane", row(offset_m=DROP), "offset_m"),
    ("heading_rad null with a lane", row(heading_rad=None), "heading_rad"),
    ("curvature_1pm a string", row(curvature_1pm="0.001"), "curvature_1pm"),
    ("lane_width_m a bool", row(lane_width_m=True), "lane_width_m"),
    ("offset_m beyond binary32", row(offset_m=1e39), "offset_m"),
    ("offset_m an integer beyond a double", row(offset_m=10 ** 400), "offset_m"),
    ("offset_m with lane_found false", row(lane_found=False, heading_rad=DROP, curvature_1pm=DROP, lane_width_m=DROP),
     "offset_m"),
    ("lane_width_m 0 with lane_found false", dict(row(**NO_LANE), lane_width_m=0), "lane_width_m"),
    ("v_mps missing", row(v_mps=DROP), "v_mps"),
    ("yaw_rps missing", row(yaw_rps=DROP), "yaw_rps"),
    ("v_mps null, yaw_rps a number", row(v_mps=None), "v_mps"),
    ("v_mps a number, yaw_rps null", row(yaw_rps=None), "yaw_rps"),
    ("v_mps a string", row(v_mps="10"), "v_mps"),
    ("yaw_rps a bool", row(yaw_rps=False), "yaw_rps"),
    ("v_mps beyond binary32", row(v_mps=-1e39), "v_mps"),
    ("age_ms missing", row(age_ms=DROP), "age_ms"),
    ("age_ms negative", row(age_ms=-1), "age_ms"),
    ("age_ms a float", row(age_ms=20.0), "age_ms"),
    ("age_ms null", row(age_ms=None), "age_ms"),
    ("an unknown key", row(frame=12), "frame"),
    ("a key misspelt", dict(row(yaw_rps=DROP), yaw_rate=0.0), "yaw_rate"),
    ("heading_rad beyond binary32", row(heading_rad=1e39), "heading_rad"),
    ("curvature_1pm beyond binary32", row(curvature_1pm=-1e39), "curvature_1pm"),
    ("lane_width_m an integer beyond a double", row(lane_width_m=10 ** 400), "lane_width_m"),
    ("yaw_rps beyond binary32", row(yaw_rps=1e39), "yaw_rps"),
    ("v_mps an integer beyond a double", row(v_mps=10 ** 400), "v_mps"),
    ("age_ms a string", row(age_ms="20"), "age_ms"),
    ("age_ms a bool", row(age_ms=False), "age_ms"),
    ("lane_found a string", row(lane_found="true"), "lane_found"),
    ("conf a string", row(conf="90"), "conf"),
    ("conf null", row(conf=None), "conf"),
    ("heading_rad with lane_found false", row(lane_found=False, offset_m=DROP, curvature_1pm=DROP, lane_width_m=DROP),
     "heading_rad"),
    ("curvature_1pm with lane_found false", row(lane_found=False, offset_m=DROP, heading_rad=DROP, lane_width_m=DROP),
     "curvature_1pm"),
]


@pytest.mark.parametrize("bad,what", [(r, w) for _n, r, w in REFUSED_ROWS], ids=[n for n, _r, _w in REFUSED_ROWS])
def test_x_each_refused_field_refuses_the_whole_file_naming_its_line(lc, bad, what):
    data = jsonl([row(t_ms=0), bad, row(t_ms=80)])
    with pytest.raises(lc.ClientError) as ei:
        lc.parse_estimates(data)
    msg = str(ei.value)
    assert msg.startswith("line 2: ") and what in msg, msg


RAW_REFUSALS = [
    ("not JSON", b"{\"t_ms\": 40,"),
    ("a JSON array", b"[1, 2]"),
    ("a JSON number", b"40"),
    ("NaN", jsonl([row(t_ms=40)]).rstrip(b"\n").replace(b'"offset_m": 0.1', b'"offset_m": NaN')),
    ("Infinity", jsonl([row(t_ms=40)]).rstrip(b"\n").replace(b'"v_mps": 10.0', b'"v_mps": -Infinity')),
    ("1e400, a float JSON reads as infinite", jsonl([row(t_ms=40)]).rstrip(b"\n").replace(b'"lane_width_m": 3.5',
                                                                                             b'"lane_width_m": 1e400')),
    ("a key given twice", jsonl([row(t_ms=40)]).rstrip(b"\n").replace(b'"conf": 90', b'"conf": 90, "conf": 91')),
    ("a blank line", b""),
    ("bytes that are not UTF-8", b'{"t_ms": 40, "lane_found": true, "\xff": 1}'),
]


@pytest.mark.parametrize("raw", [r for _n, r in RAW_REFUSALS], ids=[n for n, _r in RAW_REFUSALS])
def test_x_a_line_that_does_not_parse_refuses_the_whole_file_naming_it(lc, raw):
    data = jsonl([row(t_ms=0)]) + raw + b"\n" + jsonl([row(t_ms=80)])
    with pytest.raises(lc.ClientError) as ei:
        lc.parse_estimates(data)
    assert str(ei.value).startswith("line 2: "), str(ei.value)


def test_x_the_file_is_in_time_order(lc):
    ok = lc.parse_estimates(jsonl([row(t_ms=0), row(t_ms=33), row(t_ms=33), row(t_ms=70)]))
    assert [e.t_ms for e in ok] == [0, 33, 33, 70] and [e.line for e in ok] == [1, 2, 3, 4]
    with pytest.raises(lc.ClientError) as ei:
        lc.parse_estimates(jsonl([row(t_ms=0), row(t_ms=33), row(t_ms=32)]))
    assert str(ei.value).startswith("line 3: ") and "t_ms" in str(ei.value)


def test_an_empty_file_is_refused_and_the_last_newline_is_optional(lc):
    with pytest.raises(lc.ClientError):
        lc.parse_estimates(b"")
    with pytest.raises(lc.ClientError):
        lc.parse_estimates(b"\n")
    assert len(lc.parse_estimates(jsonl([row(), row(t_ms=33)]).rstrip(b"\n"))) == 2


def test_read_estimates_gives_the_file_s_sha256(lc, tmp_path):
    data = jsonl([row(), row(t_ms=33, **NO_LANE)])
    p = tmp_path / "estimates.jsonl"
    p.write_bytes(data)
    es, sha = lc.read_estimates(p)
    assert len(es) == 2 and sha == hashlib.sha256(data).hexdigest()
    with pytest.raises(lc.ClientError):
        lc.read_estimates(tmp_path / "absent.jsonl")


# ============================================================ the packing

@pytest.mark.parametrize("lane,veh,flags", [(True, True, 0x03), (True, False, 0x01), (False, True, 0x02), (False, False, 0x00)],
                         ids=["lane-veh", "lane", "veh", "neither"])
def test_x_lane_comes_from_lane_found_and_veh_from_the_vehicle_values(lc, lf, lane, veh, flags):
    over = {} if lane else dict(NO_LANE, conf=77)
    if not veh:
        over.update(v_mps=None, yaw_rps=None)
    e = est(lc, **over)
    fr = lc.pack(e, 5, 123, 1)
    assert fr[H + lf.P_FLAGS] == flags and lf.layout_errors(fr) == []
    d = lf.decode_request(fr)
    assert (d.seq, d.tstamp_ns, d.profile, d.age_ms) == (5, 123, 1, 20)
    if lane:
        assert (d.conf, d.value("offset"), d.value("width")) == (90, lf.f32(0.1), 3.5)
        assert (d.value("heading"), d.value("curvature")) == (0.0, lf.f32(0.001))
    else:
        assert d.conf == 0 and all(d.value(k) is None for k in ("offset", "heading", "curvature", "width"))
    if veh:
        assert (d.value("speed"), d.value("yaw_rate")) == (10.0, 0.0)
    else:
        assert d.value("speed") is None and d.value("yaw_rate") is None


def test_x_seq_counts_from_1_and_tstamp_is_the_clock_at_the_pack(lc, lf):
    clk = Clock()
    c = client(lc, clock=clk)
    seqs = []
    for k in range(3):
        clk.advance(ms=33)
        seqs.append(c.offer(est(lc, t_ms=33 * k)))
        q = lf.decode_request(c.queued.frame)
        assert (q.seq, q.tstamp_ns) == (seqs[-1], clk())
    assert seqs == [1, 2, 3]
    assert c.n["packed"] == 3 and c.n["drop"] == 2           # nothing pumped: each one replaced the one before it
    closed_out(c)


def test_x_the_age_saturates_at_u16_and_is_counted(lc, lf):
    c = client(lc)
    c.offer(est(lc, age_ms=0xFFFF))
    assert lf.decode_request(c.queued.frame).age_ms == 0xFFFF and c.n["age_saturated"] == 0
    c.offer(est(lc, age_ms=70000))
    assert lf.decode_request(c.queued.frame).age_ms == 0xFFFF and c.n["age_saturated"] == 1
    closed_out(c)


def test_a_value_outside_the_profile_is_packed_for_the_monitor_to_judge(lc, lf, lr):
    """The client refuses only what laneframe cannot pack; a confidence under the minimum, a width outside the window or an
    offset past the lane is a claim, and the monitor answers it."""
    for over, reason in ((dict(conf=10), 28), (dict(lane_width_m=6.0), 29), (dict(offset_m=1.2), 30)):
        fr = lc.pack(est(lc, **over), 1, 0, 1)
        assert lf.layout_errors(fr) == [] and lr.judge(fr) == (1, reason)


# ============================================================ the host, the port, the profile, the timeout

@pytest.mark.parametrize("host", ["127.0.0.1", "127.5.6.7", "127.255.255.254", "10.0.0.2", "172.16.0.1", "172.31.255.254",
                                  "192.168.1.10", "10.255.255.255", "172.20.1.1", "192.168.0.0", "192.168.255.254"])
def test_the_host_is_loopback_or_rfc_1918(lc, host):
    assert lc.host_problem(host) is None
    assert lc.check_config(lc.Config(port=7170, host=host)) == []


def dotted(head, last):
    """head + "." + last, put together when the test runs: an address outside RFC 5737, RFC 1918 and loopback, written out
    whole, is a finding of tests/test_no_real_identifiers.py, which reads this file."""
    return "%s.%s" % (head, last)


@pytest.mark.parametrize("host", ["203.0.113.5", dotted("8.8.8", 8), dotted("11.0.0", 1), dotted("172.15.255", 255),
                                  dotted("172.32.0", 1), dotted("192.169.0", 1), "169.254.1.1", "0.0.0.0", "255.255.255.255",
                                  "localhost", "::1", "", "127.0.0.1 ", "127.1", dotted("010.0.0", 1),
                                  dotted("9.255.255", 255), "192.0.2.1", "198.51.100.7", dotted("100.64.0", 1),
                                  dotted("224.0.0", 1), "127.0.0.1/8", "127.0.0.1:7170", "::ffff:127.0.0.1"])
def test_x_any_other_host_is_refused(lc, host):
    assert lc.host_problem(host) is not None
    assert lc.check_config(lc.Config(port=7170, host=host)) != []
    with pytest.raises(lc.ClientError):
        client(lc, port=7170, host=host)


@pytest.mark.parametrize("kw", [dict(port=0), dict(port=65536), dict(port=True), dict(profile=0), dict(profile=2),
                                dict(profile=255), dict(reply_timeout_ms=0), dict(reply_timeout_ms=-5),
                                dict(reply_timeout_ms=1.5)],
                         ids=["port-0", "port-65536", "port-bool", "profile-0", "profile-2", "profile-255", "timeout-0",
                              "timeout-negative", "timeout-float"])
def test_x_a_port_profile_or_timeout_out_of_range_is_refused(lc, kw):
    cfg = dict(port=7170)
    cfg.update(kw)
    assert lc.check_config(lc.Config(**cfg)) != []
    with pytest.raises(lc.ClientError):
        lc.LaneClient(lc.Config(**cfg), clock=Clock())


def test_the_defaults_are_the_specifications(lc):
    cfg = lc.Config(port=7170)
    assert (cfg.host, cfg.profile, cfg.reply_timeout_ms, cfg.expect_judge) == ("127.0.0.1", 1, 500, False)
    assert lc.CONNECT_TIMEOUT_NS == 500 * MS and lc.BACKOFF_FIRST_NS == 100 * MS and lc.BACKOFF_CAP_NS == 2000 * MS


# ============================================================ the connection rules, against a peer on loopback

def test_no_connect_before_the_first_frame_and_one_at_it(lc, monitor):
    mon = monitor()
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        c.wait(0.02)
    assert mon.accepts == 0 and c.n["connects"] == 0
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: c.n["replied"] == 1)
    assert mon.accepts == 1 and c.n["connects"] == 1 and c.n["reconnects"] == 0 and mon.seqs() == [1]
    closed_out(c)


def test_x_one_request_outstanding_and_the_replaced_frame_is_a_drop(lc, monitor):
    release = threading.Event()

    def script(ci, fi, f):
        if fi == 0:
            release.wait(SLACK_S)
        return "reply"
    mon = monitor(script=script)
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    c.offer(est(lc))
    assert settle(c, lambda: len(mon.frames()) == 1)
    c.offer(est(lc, t_ms=33))
    for _ in range(10):
        c.wait(0.01)
    assert len(mon.frames()) == 1 and c.n["sends"] == 1 and c.queued.seq == 2
    c.offer(est(lc, t_ms=66))
    assert c.n["drop"] == 1 and c.queued.seq == 3
    release.set()
    assert settle(c, lambda: c.n["replied"] == 2)
    assert mon.seqs() == [1, 3]
    closed_out(c)
    assert (c.n["packed"], c.n["replied"], c.n["drop"], c.n["lost_on_reconnect"]) == (3, 2, 1, 0)


def test_x_a_frame_in_flight_when_the_monitor_closes_is_lost(lc, monitor, tmp_path):
    log = tmp_path / "replies.jsonl"
    mon = monitor(script=lambda ci, fi, f: "close")
    c = client(lc, port=mon.port, clock=time.monotonic_ns, reply_log=log)
    c.offer(est(lc))
    assert settle(c, lambda: c.n["lost_on_reconnect"] == 1)
    assert c.n["replied"] == 0 and not c.connected and len(mon.frames()) == 1
    s = closed_out(c)
    assert s["identity"] == {"packed": 1, "replied": 0, "drop": 0, "lost_on_reconnect": 1, "holds": True}
    recs = log_lines(log)[1:-1]
    assert [(r["seq"], r["outcome"], r["verdict"], r["reason"], r["layout"]) for r in recs] == [(1, "lost", None, None, None)]


@pytest.mark.parametrize("timeout_ms", [500, 200])
def test_x_the_reply_timeout_closes_and_counts_the_frame_lost(lc, monitor, timeout_ms):
    clk = Clock()
    mon = monitor(script=lambda ci, fi, f: "none")
    c = client(lc, port=mon.port, clock=clk, reply_timeout_ms=timeout_ms)
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: c.n["sends"] == 1)
    clk.advance(ms=timeout_ms - 1)
    c.pump()
    assert c.connected and c.n["lost_on_reconnect"] == 0 and c.outstanding is not None
    clk.advance(ms=1)
    c.pump()
    assert not c.connected and c.n["lost_on_reconnect"] == 1 and c.n["reply_timeouts"] == 1
    assert wait_for(lambda: mon.ended(0) == "eof")               # the monitor sees the client close it
    for _ in range(5):
        c.wait(0.01)
    assert mon.accepts == 1                                     # nothing reconnects until a frame is queued
    closed_out(c)


def test_x_next_due_s_is_the_reply_s_due_while_a_frame_is_outstanding(lc, monitor):
    """While a frame is outstanding the loop waits no longer than its reply's due (a reply timeout shorter than
    LOOP_WAIT_MAX_S), so play() sees a reply timeout at its due, not at the next estimate's or after the longest wait."""
    clk = Clock()
    mon = monitor(script=lambda ci, fi, f: "none")
    c = client(lc, port=mon.port, clock=clk, reply_timeout_ms=200)
    assert 200 * MS < lc.LOOP_WAIT_MAX_S * 1e9
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: c.n["sends"] == 1)
    assert c.connected and c.outstanding is not None and c.queued is None
    assert c.next_due_s() == 200 * MS / 1e9
    clk.advance(ms=150)
    assert c.next_due_s() == 50 * MS / 1e9
    clk.advance(ms=50)
    assert c.next_due_s() == 0
    c.pump()
    assert c.n["reply_timeouts"] == 1 and c.n["lost_on_reconnect"] == 1 and not c.connected
    closed_out(c)


def test_x_next_due_s_is_the_next_connect_s_due_after_a_failed_connect(lc):
    """After a failed connect, with the frame still queued, the loop waits no longer than the backoff's end, so the next
    connect is tried when it is due, not after the longest wait."""
    clk = Clock()
    c = client(lc, port=free_port(), clock=clk)
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: c.n["connect_failures"] == 1)
    assert c.next_due_s() == 100 * MS / 1e9
    q, c.queued = c.queued, None
    assert c.next_due_s() == lc.LOOP_WAIT_MAX_S
    c.queued = q
    closed_out(c)


@pytest.mark.parametrize("delta", [1, -1, 1 << 32], ids=["next-seq", "previous-seq", "high-bytes"])
def test_x_a_reply_with_another_seq_is_invalid_and_the_frame_lost(lc, monitor, tmp_path, delta):
    """A reply binds to its request by seq: one carrying another seq, every other byte as the monitor would write it,
    is reply_invalid, the outstanding frame lost and the connection closed, never counted as that frame's reply."""
    mon_ref = []

    def script(ci, fi, f):
        b = bytearray(mon_ref[0].answer(f))
        struct.pack_into("<Q", b, 0, struct.unpack_from("<Q", f, 0)[0] + delta)
        return [("raw", bytes(b))]
    mon = monitor(script=script)
    mon_ref.append(mon)
    log = tmp_path / "replies.jsonl"
    c = client(lc, port=mon.port, clock=time.monotonic_ns, reply_log=log)
    c.offer(est(lc, t_ms=0))
    c.offer(est(lc, t_ms=33))                                   # seq 2 is the one sent (seq 1 replaced): its neighbours exist
    assert settle(c, lambda: c.n["lost_on_reconnect"] + c.n["replied"] == 1)
    assert (c.n["reply_invalid"], c.n["replied"], c.n["lost_on_reconnect"]) == (1, 0, 1) and not c.connected
    closed_out(c)
    lost = [r for r in log_lines(log)[1:-1] if r["outcome"] == "lost"]
    assert len(lost) == 1 and lost[0]["seq"] == 2 and "seq" in lost[0]["layout"]


def test_x_a_reply_with_another_tstamp_is_invalid_and_the_frame_lost(lc, monitor, tmp_path):
    """The header's tstamp is the request's too: a reply that changes it, every other byte as the monitor would write it,
    is reply_invalid, the frame lost and the connection closed."""
    mon_ref = []

    def script(ci, fi, f):
        b = bytearray(mon_ref[0].answer(f))
        b[8] ^= 0x01
        return [("raw", bytes(b))]
    mon = monitor(script=script)
    mon_ref.append(mon)
    log = tmp_path / "replies.jsonl"
    c = client(lc, port=mon.port, clock=time.monotonic_ns, reply_log=log)
    c.offer(est(lc))
    assert settle(c, lambda: c.n["lost_on_reconnect"] + c.n["replied"] == 1)
    assert (c.n["reply_invalid"], c.n["replied"], c.n["lost_on_reconnect"]) == (1, 0, 1) and not c.connected
    closed_out(c)
    rec = log_lines(log)[1]
    assert rec["outcome"] == "lost" and "[8]" in rec["layout"], rec


LAYOUT_FAULTS = [
    ("verdict-2", {6: 2, 7: 28}),
    ("reject-with-0", {6: 1, 7: 0}),
    ("accept-with-a-reason", {6: 0, 7: 28}),
    ("kind-2", {24: 2}),
    ("a-stamp-in-p8", {8: 1}),
    ("reserved-flag", {0: 0x07}),
    ("a-value-byte-changed", {33: 0x01}),            # the width 3.5's lowest byte is 0x00 in the request
    ("the-profile-changed", {47: 2}),
]


@pytest.mark.parametrize("patch", [p for _n, p in LAYOUT_FAULTS], ids=[n for n, _p in LAYOUT_FAULTS])
def test_x_a_reply_with_a_layout_fault_or_another_byte_is_invalid(lc, monitor, tmp_path, patch):
    """The reply to an honest claim (a REJECT 30 as written), each byte patched as given: every patch makes it a reply
    the client does not take."""
    mon_ref = []

    def script(ci, fi, f):
        b = bytearray(mon_ref[0].answer(f, (1, 30)))
        for off, val in patch.items():
            b[H + off] = val
        assert bytes(b) != mon_ref[0].answer(f, (1, 30))
        return [("raw", bytes(b))]
    mon = monitor(script=script)
    mon_ref.append(mon)
    log = tmp_path / "replies.jsonl"
    c = client(lc, port=mon.port, clock=time.monotonic_ns, reply_log=log)
    c.offer(est(lc))
    assert settle(c, lambda: c.n["lost_on_reconnect"] + c.n["replied"] == 1)
    assert (c.n["reply_invalid"], c.n["replied"], c.n["lost_on_reconnect"]) == (1, 0, 1) and not c.connected
    closed_out(c)
    rec = log_lines(log)[1]
    assert rec["outcome"] == "lost" and isinstance(rec["layout"], str) and rec["layout"] != "ok"


def test_the_reconnect_is_lazy_after_the_monitor_closes_an_idle_connection(lc, monitor):
    mon = monitor(idle_close_s=0.15)
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: c.n["replied"] == 1)
    assert settle(c, lambda: not c.connected)                   # the client sees the close while it waits
    end = time.monotonic() + 0.6
    while time.monotonic() < end:
        c.wait(0.02)
    assert mon.accepts == 1                                     # a silence: no reconnect
    c.offer(est(lc, t_ms=900))
    c.pump()
    assert settle(c, lambda: c.n["replied"] == 2)
    assert mon.accepts == 2 and c.n["reconnects"] == 1 and c.n["lost_on_reconnect"] == 0
    closed_out(c)


def test_a_close_seen_only_by_the_peer_check_reconnects_before_the_send(lc, monitor):
    """The monitor replies and closes; the client has read the reply but not yet the close when the next frame comes.
    The non-blocking MSG_PEEK before the send finds the close, so the frame goes out on a new connection and is replied,
    never written into the dead one and lost."""
    mon = monitor(script=lambda ci, fi, f: ["reply", "close"])
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: c.n["replied"] == 1)
    assert wait_for(lambda: mon.ended(0) == "closed")
    time.sleep(0.05)
    assert c.connected                                          # not yet noticed
    checks = c.n["peer_checks"]
    c.offer(est(lc, t_ms=33))
    c.pump()
    assert settle(c, lambda: c.n["replied"] == 2)
    assert c.n["lost_on_reconnect"] == 0 and mon.accepts == 2 and c.n["peer_checks"] > checks
    closed_out(c)


def test_x_a_peek_that_fails_means_the_peer_has_closed(lc):
    """Kind 2's rule for the check before a send: a recv(MSG_PEEK) that fails (here a reset) means the peer has closed,
    and one that would block means it has not."""
    class Peek:
        """A socket whose recv raises the given error."""

        def __init__(self, err):
            self.err = err

        def recv(self, n, flags=0):
            raise self.err
    c = client(lc)
    c._sock = Peek(ConnectionResetError(errno.ECONNRESET, "reset"))
    assert c._peer_closed() is True
    c._sock = Peek(BlockingIOError(errno.EAGAIN, "would block"))
    assert c._peer_closed() is False
    c._sock = Peek(OSError(errno.ENOTCONN, "not connected"))
    assert c._peer_closed() is True
    c._sock = Peek(InterruptedError(errno.EINTR, "interrupted"))
    assert c._peer_closed() is False
    c._sock = None
    closed_out(c)


def test_a_failed_connect_backs_off_before_the_next_attempt(lc):
    clk = Clock()
    c = client(lc, port=free_port(), clock=clk)
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: c.n["connect_failures"] == 1)
    for k, wait_ms in enumerate((100, 200), start=1):
        assert c.next_connect_ns == clk() + wait_ms * MS
        clk.advance(ms=wait_ms - 1)
        for _ in range(3):
            c.wait(0.01)
        assert c.n["connect_failures"] == k                     # not before the backoff is over
        clk.advance(ms=1)
        c.pump()
        assert settle(c, lambda k=k: c.n["connect_failures"] == k + 1)
    assert c.n["connects"] == 0
    closed_out(c)
    assert c.n["drop"] == 1


def test_the_backoff_doubles_to_its_cap_and_a_connect_resets_it(lc):
    c = client(lc)
    waits = []
    for _ in range(7):
        c._connect_failed(0)
        waits.append(c.next_connect_ns // MS)
    assert waits == [100, 200, 400, 800, 1600, 2000, 2000]
    s1, s2 = socket.socketpair()
    try:
        c._connected(s1)
        c._close("test")
        c._connect_failed(0)
        assert c.next_connect_ns == 100 * MS
    finally:
        s2.close()
    closed_out(c)


def test_x_a_connect_that_does_not_complete_is_abandoned_at_the_connect_timeout(lc, monkeypatch):
    """A connect that stays in progress (a socket whose connect_ex says so and never connects) is given up at
    CONNECT_TIMEOUT_NS on the client's clock, counted a failure, and the backoff starts; pump() alone drives it."""
    class Hanging(socket.socket):
        def connect_ex(self, address):
            return errno.EINPROGRESS
    clk = Clock()
    c = client(lc, port=7170, clock=clk)
    monkeypatch.setattr(lc.socket, "socket", Hanging)
    c.offer(est(lc))
    c.pump()
    assert c._state == lc.CONNECTING and c.n["connect_failures"] == 0
    clk.advance(ms=499)
    c.pump()
    assert c._state == lc.CONNECTING and c.n["connect_failures"] == 0
    clk.advance(ms=1)
    c.pump()
    assert c._state == lc.DISCONNECTED and c.n["connect_failures"] == 1 and c.n["connects"] == 0
    assert c.next_connect_ns == clk() + 100 * MS
    closed_out(c)
    assert c.n["drop"] == 1


def test_stray_bytes_with_nothing_outstanding_close_the_connection(lc, monitor):
    mon = monitor(script=lambda ci, fi, f: ["reply", ("raw", b"\x01")])
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: c.n["replied"] == 1)
    assert settle(c, lambda: not c.connected)
    assert c.n["stray_bytes"] > 0 and c.n["lost_on_reconnect"] == 0
    closed_out(c)


def test_x_a_reply_in_two_parts_is_read_to_its_64th_byte_and_a_byte_after_it_is_stray(lc, monitor):
    """The monitor sends a reply's first 20 bytes, waits until the client holds them, then the other 44 with one byte
    glued after them. The client reads no further than the reply's 64th byte: the reply is taken, and the byte after it
    is stray (nothing is outstanding then), never read into the reply."""
    go = threading.Event()
    mon_ref = []

    def script(ci, fi, f):
        a = mon_ref[0].answer(f)
        return [("raw", a[:20]), ("wait", go), ("raw", a[20:] + b"\x01")]
    mon = monitor(script=script)
    mon_ref.append(mon)
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: len(c._rbuf) == 20)
    assert c.n["replied"] == 0 and c.outstanding is not None
    go.set()
    assert settle(c, lambda: not c.connected)                   # closed for the stray byte (or for a reply not taken)
    assert (c.n["replied"], c.n["reply_invalid"], c.n["stray_bytes"], c.n["lost_on_reconnect"]) == (1, 0, 1, 0)
    closed_out(c)


def test_the_stop_drains_the_outstanding_and_the_queued_frame(lc, monitor):
    release = threading.Event()

    def script(ci, fi, f):
        if fi == 0:
            release.wait(SLACK_S)
        return "reply"
    mon = monitor(script=script)
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    c.offer(est(lc))
    assert settle(c, lambda: len(mon.frames()) == 1)
    c.offer(est(lc, t_ms=33))
    threading.Timer(0.1, release.set).start()
    closed_out(c)
    assert (c.n["replied"], c.n["drop"], c.n["lost_on_reconnect"]) == (2, 0, 0) and mon.seqs() == [1, 2]


def test_the_stop_makes_no_new_connection_and_the_queued_frame_is_a_drop(lc, monitor):
    mon = monitor()
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    c.offer(est(lc))
    closed_out(c)
    assert (c.n["connects"], c.n["sends"], c.n["drop"], c.n["replied"]) == (0, 0, 1, 0)
    time.sleep(0.3)                                             # the monitor's accept loop polls every 50 ms
    assert mon.accepts == 0


def test_a_frame_outstanding_at_a_stop_without_drain_is_lost(lc, monitor):
    mon = monitor(script=lambda ci, fi, f: "none")
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    c.offer(est(lc))
    c.pump()
    assert settle(c, lambda: c.n["sends"] == 1)
    closed_out(c, drain=False)
    assert (c.n["replied"], c.n["drop"], c.n["lost_on_reconnect"]) == (0, 0, 1)


def test_x_the_stop_lets_a_connect_in_progress_complete_and_sends_the_queued_frame(lc, monitor):
    """The last estimate's connect is still in progress when the stop comes (play() stops right after the last offer):
    the drain lets it complete and sends the frame, so a run's last estimate is not a drop for that alone."""
    mon = monitor()
    c = client(lc, port=mon.port, clock=time.monotonic_ns)
    c.offer(est(lc))
    c.pump()                                                    # the connect starts; the frame waits for it
    closed_out(c)
    assert (c.n["connects"], c.n["replied"], c.n["drop"]) == (1, 1, 0) and mon.seqs() == [1]


@pytest.mark.parametrize("timeout_ms,connect_ms,reply_ms,want", [(500, 450, 900, "replied"), (200, 450, 500, "drop")],
                         ids=["a-reply-past-one-reply-timeout", "a-connect-past-twice-the-reply-timeout"])
def test_x_the_drain_lasts_twice_the_reply_timeout_on_the_client_s_clock(lc, lr, monkeypatch, timeout_ms, connect_ms,
                                                                          reply_ms, want):
    """S4's open NIT 8: the drain's span, on a hand clock that the drain's own waits move. A stand-in socket's connect is
    in progress at the stop and completes at connect_ms, and its reply comes at reply_ms. With a 500 ms reply timeout the
    connect completes at 450 ms, the frame goes out, and its reply at 900 ms, past one reply timeout and inside two, is
    taken. With 200 ms the drain ends at 400 ms, before the connect (its timeout 500 ms) completes: the frame is a drop,
    never sent, and the drain's clock ends at exactly twice the reply timeout."""
    clk = Clock()
    sent = []

    class Late:
        """A socket whose connect stays in progress (the client finds out by its wait) and whose reply is the frame sent
        as lanerules judges it; a peek finds it open."""

        def __init__(self, *args):
            pass

        def setblocking(self, flag):
            pass

        def setsockopt(self, *args):
            pass

        def connect_ex(self, address):
            return errno.EINPROGRESS

        def getsockopt(self, *args):
            return 0

        def recv(self, n, flags=0):
            if flags:
                raise BlockingIOError(errno.EAGAIN, "would block")
            b = bytearray(sent[-1])
            b[H + 6], b[H + 7] = lr.judge(sent[-1])
            return bytes(b[:n])

        def send(self, data):
            sent.append(bytes(data))
            return len(data)

        def close(self):
            pass
    monkeypatch.setattr(lc.socket, "socket", Late)
    c = client(lc, port=7170, clock=clk, reply_timeout_ms=timeout_ms)

    def wait(timeout_s, fds=()):
        clk.advance(ns=max(1, round(timeout_s * 1e9)))
        if c._state == lc.CONNECTING and clk() - T0 >= connect_ms * MS:
            c._connect_done(clk())
        elif c.connected and c.outstanding is not None and clk() - T0 >= reply_ms * MS:
            c._readable()
        c.pump()
        return []
    monkeypatch.setattr(c, "wait", wait)
    c.offer(est(lc))
    c.pump()
    assert c._state == lc.CONNECTING
    closed_out(c)
    if want == "replied":
        assert (c.n["connects"], c.n["sends"], c.n["replied"], c.n["drop"], c.n["lost_on_reconnect"]) == (1, 1, 1, 0, 0)
        assert clk() - T0 == reply_ms * MS
    else:
        assert (c.n["connects"], c.n["sends"], c.n["replied"], c.n["drop"], c.n["lost_on_reconnect"]) == (0, 0, 0, 1, 0)
        assert clk() - T0 == 2 * timeout_ms * MS and sent == []


# ============================================================ replies.jsonl

def test_the_reply_log_has_a_header_one_line_per_frame_and_a_summary(lc, lf, lr, monitor, tmp_path):
    log = tmp_path / "replies.jsonl"
    mon = monitor()
    c = lc.LaneClient(lc.Config(port=mon.port), clock=time.monotonic_ns, reply_log=log, estimates_sha256="ab" * 32, frames=3)
    for k, over in enumerate((dict(), dict(conf=10), NO_LANE)):
        c.offer(est(lc, t_ms=33 * k, **over))
        c.pump()
        assert settle(c, lambda k=k: c.n["replied"] == k + 1)
    closed_out(c)
    lines = log_lines(log)
    h = lines[0]["header"]
    assert (h["format"], h["kind"], h["estimates_sha256"], h["frames"]) == (1, 6, "ab" * 32, 3)
    assert (h["host"], h["port"], h["profile"], h["reply_timeout_ms"], h["expect_judge"]) == ("127.0.0.1", mon.port, 1, 500, False)
    recs = lines[1:-1]
    assert [(r["seq"], r["t_ms"], r["outcome"], r["verdict"], r["reason"], r["name"], r["layout"]) for r in recs] == [
        (1, 0, "replied", 0, 0, "ok", "ok"), (2, 33, "replied", 1, 28, "lane-conf-low", "ok"), (3, 66, "replied", 0, 0, "ok", "ok")]
    for r in recs:
        fr = bytes.fromhex(r["frame"])
        assert lf.decode_request(fr).seq == r["seq"] and r["expect"] is None
    s = lines[-1]["summary"]
    assert s["identity"] == {"packed": 3, "replied": 3, "drop": 0, "lost_on_reconnect": 0, "holds": True}
    assert s["counters"]["packed"] == 3 and s["counters"]["accepted"] == 2 and s["counters"]["rejected"] == 1
    assert s["by_reason"] == [{"reason": 0, "name": "ok", "n": 2}, {"reason": 28, "name": "lane-conf-low", "n": 1}]
    assert s["judge"] is None
    assert len(lines) == 5


def test_the_reply_log_is_never_overwritten(lc, tmp_path):
    log = tmp_path / "replies.jsonl"
    log.write_text("kept\n", encoding="utf-8")
    with pytest.raises(lc.ClientError):
        client(lc, reply_log=log)
    assert log.read_text(encoding="utf-8") == "kept\n"


def test_x_the_header_records_the_given_host_and_reply_timeout(lc, tmp_path):
    """The header records the target as given, --expect-judge and the connection's design values (kind 2's)."""
    log = tmp_path / "replies.jsonl"
    c = client(lc, port=7170, host="10.1.2.3", reply_timeout_ms=200, reply_log=log, expect_judge=True)
    closed_out(c)
    h = log_lines(log)[0]["header"]
    assert (h["host"], h["port"], h["reply_timeout_ms"]) == ("10.1.2.3", 7170, 200)
    assert h["expect_judge"] is True
    assert h["design"] == {"connect_timeout_ms": 500, "backoff_first_ms": 100, "backoff_cap_ms": 2000}


def test_x_the_frame_left_queued_at_the_stop_is_logged_as_a_drop(lc, tmp_path):
    """A frame still queued at the stop (never sent: no pump, so no connect) is a drop with its own line in the log, so
    one line per frame holds on this path too."""
    log = tmp_path / "replies.jsonl"
    c = client(lc, reply_log=log)
    c.offer(est(lc))
    closed_out(c)
    assert [(r["seq"], r["outcome"]) for r in log_lines(log)[1:-1]] == [(1, "drop")]


def test_x_a_broken_identity_does_not_hold_and_exits_1(lc):
    n = {"packed": 3, "replied": 1, "drop": 1, "lost_on_reconnect": 0}
    assert lc.identity(n) == {"packed": 3, "replied": 1, "drop": 1, "lost_on_reconnect": 0, "holds": False}
    assert lc.exit_code({"identity": lc.identity(n), "judge": None}) == 1
    assert lc.exit_code({"identity": lc.identity(dict(n, lost_on_reconnect=1)), "judge": None}) == 0
    assert "identity=BROKEN" in lc.summary_line({"counters": dict(dict.fromkeys(lc.COUNTERS, 0), **n),
                                                 "identity": lc.identity(n), "judge": None})


# ============================================================ --expect-judge

def test_expect_judge_finds_no_difference_when_the_monitor_answers_as_lanerules(lc, lr, monitor, tmp_path):
    log = tmp_path / "replies.jsonl"
    mon = monitor()
    c = client(lc, port=mon.port, clock=time.monotonic_ns, reply_log=log, expect_judge=True)
    for k, over in enumerate((dict(), dict(conf=10), dict(lane_width_m=6.0), dict(offset_m=1.0), NO_LANE)):
        c.offer(est(lc, t_ms=33 * k, **over))
        c.pump()
        assert settle(c, lambda k=k: c.n["replied"] == k + 1)
    s = closed_out(c)
    assert s["judge"] == {"compared": 5, "differ": 0, "differences": []}
    for r in log_lines(log)[1:-1]:
        assert r["expect"] == list(lr.judge(bytes.fromhex(r["frame"])))


@pytest.mark.parametrize("answer", [(0, 0), (1, 29), (1, 10)], ids=["accepted", "another-reason", "flags-invalid"])
def test_x_expect_judge_counts_and_names_each_difference(lc, lr, monitor, tmp_path, answer):
    """The monitor answers the second frame (lanerules: 28) otherwise: a wrong verdict, a wrong reason of the same
    verdict, reason 10. The reply is well formed, so it is replied and counted, and the summary counts and names it."""
    mon_ref = []

    def script(ci, fi, f):
        return [("raw", mon_ref[0].answer(f, answer if fi == 1 else None))]
    mon = monitor(script=script)
    mon_ref.append(mon)
    c = client(lc, port=mon.port, clock=time.monotonic_ns, expect_judge=True)
    for k, over in enumerate((dict(), dict(conf=10), dict())):
        c.offer(est(lc, t_ms=33 * k, **over))
        c.pump()
        assert settle(c, lambda k=k: c.n["replied"] == k + 1)
    s = closed_out(c)
    assert s["judge"] == {"compared": 3, "differ": 1, "differences": [{"seq": 2, "got": list(answer), "want": [1, 28]}]}
    assert lc.exit_code(s) == 1


def test_without_expect_judge_no_judge_is_imported_at_the_client_s_top(lc):
    """The client packs and sends; the monitor judges. lanerules is the tests' oracle, imported only for --expect-judge:
    the module's top level imports laneframe and the standard library alone."""
    tree = ast.parse(CLIENT_FILE.read_text(encoding="utf-8"))
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            top.add((node.module or "").split(".")[0])
    assert "lanerules" not in top and "laneframe" in top
    stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
    assert all(n in ("laneframe", "__future__") or stdlib is None or n in stdlib for n in top), top


# ============================================================ the command line

def write_estimates(tmp_path, rows, name="estimates.jsonl"):
    p = tmp_path / name
    p.write_bytes(jsonl(rows))
    return p


def test_run_sends_each_estimate_and_logs_every_reply(lc, lf, monitor, tmp_path, capsys):
    mon = monitor()
    est_file = write_estimates(tmp_path, [row(t_ms=0), row(t_ms=50, conf=10), row(t_ms=100, **NO_LANE),
                                          row(t_ms=150, v_mps=None, yaw_rps=None)])
    out = tmp_path / "replies.jsonl"
    rc = lc.main(["run", "--estimates", str(est_file), "--port", str(mon.port), "--out", str(out)])
    assert rc == 0
    lines = log_lines(out)
    assert lines[0]["header"]["estimates_sha256"] == hashlib.sha256(est_file.read_bytes()).hexdigest()
    assert lines[0]["header"]["frames"] == 4
    assert [(r["seq"], r["t_ms"], r["outcome"]) for r in lines[1:-1]] == [(1, 0, "replied"), (2, 50, "replied"),
                                                                           (3, 100, "replied"), (4, 150, "replied")]
    assert lines[-1]["summary"]["identity"]["holds"] and mon.seqs() == [1, 2, 3, 4]
    printed = capsys.readouterr().out
    assert "packed=4 replied=4" in printed and "identity=holds" in printed


def test_x_run_sends_a_file_of_one_estimate(lc, monitor, tmp_path):
    mon = monitor()
    est_file = write_estimates(tmp_path, [row(t_ms=0)])
    out = tmp_path / "replies.jsonl"
    assert lc.main(["run", "--estimates", str(est_file), "--port", str(mon.port), "--out", str(out)]) == 0
    assert [(r["seq"], r["outcome"]) for r in log_lines(out)[1:-1]] == [(1, "replied")] and mon.seqs() == [1]


def test_x_run_paces_the_estimates_by_their_t_ms(lc, lf, monitor, tmp_path):
    """Each estimate is packed no earlier than its t_ms after the first one's, on the client's clock (held from below
    only: nothing here bounds how late)."""
    mon = monitor()
    t = [1000, 1060, 1180]
    est_file = write_estimates(tmp_path, [row(t_ms=x) for x in t])
    out = tmp_path / "replies.jsonl"
    assert lc.main(["run", "--estimates", str(est_file), "--port", str(mon.port), "--out", str(out)]) == 0
    stamps = [lf.decode_request(bytes.fromhex(r["frame"])).tstamp_ns for r in log_lines(out)[1:-1]]
    assert len(stamps) == 3
    for k in (1, 2):
        assert stamps[k] - stamps[0] >= (t[k] - t[0]) * MS, (k, stamps)


def test_x_play_offers_the_first_estimate_at_once_and_each_later_one_at_its_offset(lc, monkeypatch):
    """play() on a hand clock that its waits move: the first estimate is offered at once, whatever its t_ms, and each
    later one exactly its t_ms after the first one's (an equal t_ms at once)."""
    clk = Clock()
    c = client(lc, clock=clk)
    offered = []
    monkeypatch.setattr(c, "wait", lambda timeout_s: clk.advance(ns=max(1, int(timeout_s * 1e9))))
    monkeypatch.setattr(c, "next_due_s", lambda: 10.0)
    monkeypatch.setattr(c, "pump", lambda: None)
    monkeypatch.setattr(c, "offer", lambda e: offered.append((e.t_ms, clk() - T0)))
    lc.play(c, [est(lc, t_ms=t) for t in (5000, 5040, 5040, 5100)])
    assert offered == [(5000, 0), (5040, 40 * MS), (5040, 40 * MS), (5100, 100 * MS)]
    closed_out(c)


def test_x_play_waits_no_longer_than_next_due_s(lc, monkeypatch):
    """play() on a hand clock that its waits move, with something due sooner than the next estimate: each wait is
    bounded by next_due_s, so a reply's timeout, a connect's or a backoff's end is handled when due, not at the next
    estimate's offset."""
    clk = Clock()
    c = client(lc, clock=clk)
    waits = []

    def wait(timeout_s):
        waits.append(timeout_s)
        clk.advance(ns=max(1, int(timeout_s * 1e9)))
    monkeypatch.setattr(c, "wait", wait)
    monkeypatch.setattr(c, "next_due_s", lambda: 0.01)
    monkeypatch.setattr(c, "pump", lambda: None)
    monkeypatch.setattr(c, "offer", lambda e: None)
    lc.play(c, [est(lc, t_ms=0), est(lc, t_ms=100)])
    assert waits and max(waits) <= 0.01, waits
    closed_out(c)


def test_x_run_with_expect_judge_exits_1_on_a_difference(lc, monitor, tmp_path, capsys):
    mon_ref = []

    def script(ci, fi, f):
        return [("raw", mon_ref[0].answer(f, (0, 0)))]
    mon = monitor(script=script)
    mon_ref.append(mon)
    est_file = write_estimates(tmp_path, [row(t_ms=0), row(t_ms=50, conf=10)])
    out = tmp_path / "replies.jsonl"
    rc = lc.main(["run", "--estimates", str(est_file), "--port", str(mon.port), "--out", str(out), "--expect-judge"])
    assert rc == 1
    s = log_lines(out)[-1]["summary"]
    assert s["judge"]["differ"] == 1 and s["judge"]["differences"][0]["seq"] == 2
    assert "differ=1" in capsys.readouterr().out


def test_x_expect_judge_exits_1_when_nothing_is_compared(lc, tmp_path, capsys):
    """--expect-judge with no monitor listening: every frame a drop, nothing compared. A check that compared nothing has
    not passed, so the exit code is 1 and the summary line names the case. Without --expect-judge the same run exits 0
    (the identity holds), and one reply compared with no difference exits 0."""
    ok = {"holds": True}
    assert lc.exit_code({"identity": ok, "judge": {"compared": 0, "differ": 0, "differences": []}}) == 1
    assert lc.exit_code({"identity": ok, "judge": {"compared": 1, "differ": 0, "differences": []}}) == 0
    assert lc.exit_code({"identity": ok, "judge": None}) == 0
    port = free_port()
    est_file = write_estimates(tmp_path, [row(t_ms=0), row(t_ms=20)])
    out = tmp_path / "replies.jsonl"
    rc = lc.main(["run", "--estimates", str(est_file), "--port", str(port), "--out", str(out), "--expect-judge"])
    printed = capsys.readouterr().out
    s = log_lines(out)[-1]["summary"]
    assert s["counters"]["replied"] == 0 and s["identity"]["holds"]
    assert s["judge"] == {"compared": 0, "differ": 0, "differences": []}
    assert rc == 1 and "nothing compared" in printed, printed
    out2 = tmp_path / "replies-2.jsonl"
    assert lc.main(["run", "--estimates", str(est_file), "--port", str(port), "--out", str(out2)]) == 0


def _refusal(kind, tmp_path):
    good = write_estimates(tmp_path, [row(t_ms=0), row(t_ms=20)])
    out = tmp_path / "replies.jsonl"
    extra = []
    if kind == "a-refused-line":
        bad = tmp_path / "bad.jsonl"
        bad.write_bytes(jsonl([row(t_ms=0)]) + b"{not json}\n")
        return bad, out, extra
    if kind == "a-public-host":
        return good, out, ["--host", "203.0.113.5"]
    if kind == "a-name-for-a-host":
        return good, out, ["--host", "localhost"]
    if kind == "profile-2":
        return good, out, ["--profile", "2"]
    if kind == "timeout-0":
        return good, out, ["--reply-timeout-ms", "0"]
    if kind == "out-exists":
        out.write_text("kept\n", encoding="utf-8")
        return good, out, extra
    if kind == "out-in-a-work-tree":
        wt = tmp_path / "wt"
        (wt / ".git").mkdir(parents=True)
        return good, wt / "replies.jsonl", extra
    if kind == "out-s-directory-absent":
        return good, tmp_path / "absent" / "replies.jsonl", extra
    raise AssertionError(kind)


REFUSALS = ["a-refused-line", "a-public-host", "a-name-for-a-host", "profile-2", "timeout-0", "out-exists",
            "out-in-a-work-tree", "out-s-directory-absent"]


@pytest.mark.parametrize("kind", REFUSALS)
def test_x_a_refusal_exits_2_before_any_connection_or_file(lc, monitor, tmp_path, capsys, kind):
    mon = monitor()
    est_file, out, extra = _refusal(kind, tmp_path)
    before = out.read_bytes() if out.exists() else None
    rc = lc.main(["run", "--estimates", str(est_file), "--port", str(mon.port), "--out", str(out)] + extra)
    assert rc == 2
    assert "refused" in capsys.readouterr().err
    time.sleep(0.2)
    assert mon.accepts == 0
    assert (out.read_bytes() if out.exists() else None) == before


def test_check_prints_what_would_be_sent_and_connects_nowhere(lc, lf, tmp_path, capsys):
    rows = [row(t_ms=0), row(t_ms=33, **NO_LANE), row(t_ms=66, v_mps=None, yaw_rps=None, age_ms=70000)]
    est_file = write_estimates(tmp_path, rows)
    assert lc.main(["check", "--estimates", str(est_file)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("laneclient: check: 3 estimates") and hashlib.sha256(est_file.read_bytes()).hexdigest() in out[0]
    recs = [json.loads(x) for x in out[1:]]
    assert [(r["seq"], r["t_ms"], r["lane"], r["veh"]) for r in recs] == [(1, 0, True, True), (2, 33, False, True),
                                                                          (3, 66, True, False)]
    for r, e in zip(recs, rows):
        fr = bytes.fromhex(r["frame"])
        assert lf.layout_errors(fr) == []
        assert fr == lc.pack(lc.parse_estimate(e, 1), r["seq"], 0, 1)


def test_check_refuses_a_bad_file_with_exit_2(lc, tmp_path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(jsonl([row(t_ms=0), row(t_ms=20, conf=101)]))
    assert lc.main(["check", "--estimates", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "line 2" in err and "conf" in err


# ============================================================ the live source (run --estimates -)

LIVE_LIMIT_S = 10.0    # how long a live run may take on a loaded host before the test calls it hung
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="the live source selects over a pipe: POSIX only (Windows refuses -)")
FILE_HEADER_KEYS = ["format", "kind", "estimates_sha256", "frames", "host", "port", "profile", "reply_timeout_ms",
                    "expect_judge", "design"]
LIVE_HEADER_KEYS = ["format", "kind", "source", "host", "port", "profile", "reply_timeout_ms", "expect_judge", "design"]
SUMMARY_KEYS = ["counters", "identity", "by_reason", "judge"]


class Producer:
    """An os.pipe in place of stdin (its fileno() is the read end). A thread runs the steps in order: bytes are written
    as they are, a number is a pause in seconds, a callable is waited on up to SLACK_S (whether it came true is kept in
    held). Then the write end is closed (EOF), unless keep_open: close() does that."""

    def __init__(self, steps, keep_open=False):
        self.r, self.w = os.pipe()
        self.steps = steps
        self.keep_open = keep_open
        self.held = []
        self._lock = threading.Lock()
        self._t = threading.Thread(target=self._run, daemon=True)

    def fileno(self):
        return self.r

    def start(self):
        self._t.start()

    def _write(self, data):
        with self._lock:
            if self.w is None:
                raise BrokenPipeError(errno.EPIPE, "the test closed the pipe")
            return os.write(self.w, data)

    def _run(self):
        try:
            for s in self.steps:
                if isinstance(s, bytes):
                    view = memoryview(s)
                    while view:
                        view = view[self._write(view):]
                elif callable(s):
                    self.held.append(wait_for(s))
                else:
                    time.sleep(s)
        except OSError:
            pass
        finally:
            if not self.keep_open:
                self._close_w()

    def _close_w(self):
        with self._lock:
            if self.w is not None:
                os.close(self.w)
                self.w = None

    def close(self, read_end=True):
        self._t.join(SLACK_S)
        self._close_w()
        if read_end and self.r is not None:
            os.close(self.r)
            self.r = None


def live_run(lc, monkeypatch, port, out, steps, extra=(), keep_open=False, stdin=None):
    """`run --estimates -` through lc.main in a thread, its stdin a Producer of these steps, or what stdin() makes (called
    once the producer's pipe is open): (the exit code, or None when the run had not ended within LIVE_LIMIT_S; the
    producer)."""
    prod = Producer(steps, keep_open=keep_open)
    monkeypatch.setattr(lc.sys, "stdin", prod if stdin is None else stdin())
    box = {}

    def target():
        try:
            box["rc"] = lc.main(["run", "--estimates", "-", "--port", str(port), "--out", str(out)] + list(extra))
        except BaseException as err:            # handed to the test's thread
            box["err"] = err
    t = threading.Thread(target=target, daemon=True)
    t.start()
    prod.start()
    t.join(LIVE_LIMIT_S)
    ended = not t.is_alive()
    prod.close(read_end=ended)                  # a run still going keeps its descriptor: no select over a closed one
    if "err" in box:
        raise box["err"]
    return (box.get("rc") if ended else None), prod


def ready(out):
    """A producer step: the client has made its reply log (its header written), so it is about to read stdin."""
    return lambda: Path(out).exists()


def replied(out, n):
    """A producer step: the reply log holds n replied frames (each line is written and flushed at its outcome)."""
    return lambda: Path(out).exists() and Path(out).read_text(encoding="utf-8").count('"outcome":"replied"') >= n


def padded(r, n):
    """The estimate's line padded with spaces before its closing brace to n bytes, its newline included."""
    s = json.dumps(r).encode("utf-8")
    assert n - len(s) - 1 >= 0
    return s[:-1] + b" " * (n - len(s) - 1) + b"}\n"


def live_summary(out):
    lines = log_lines(out)
    assert "summary" in lines[-1], lines[-1]
    return lines[-1]["summary"]


@POSIX_ONLY
def test_live_takes_each_line_as_it_arrives_and_logs_it_as_the_file_mode_does(lc, lr, monitor, tmp_path, monkeypatch, capsys):
    """Four made-up estimates written one at a time, each after the reply to the one before: each is packed and sent as
    its line comes, every reply is the judge's, and the log is the file mode's but for the header (the source is stdin,
    no sha256 and no count) and the summary's added source (the sha256 and the count of the lines taken)."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    lines = [jsonl([r]) for r in (row(t_ms=0), row(t_ms=40, conf=10), row(t_ms=80, **NO_LANE),
                                  row(t_ms=120, v_mps=None, yaw_rps=None))]
    steps = [ready(out)]
    for k, ln in enumerate(lines, start=1):
        steps += [ln, replied(out, k)]
    rc, prod = live_run(lc, monkeypatch, mon.port, out, steps, extra=["--expect-judge"])
    assert rc == 0 and prod.held == [True] * 5
    got = log_lines(out)
    h = got[0]["header"]
    assert list(h) == LIVE_HEADER_KEYS and h["source"] == "stdin" and h["expect_judge"] is True
    recs = got[1:-1]
    assert [(r["seq"], r["t_ms"], r["outcome"], r["layout"]) for r in recs] == [
        (1, 0, "replied", "ok"), (2, 40, "replied", "ok"), (3, 80, "replied", "ok"), (4, 120, "replied", "ok")]
    for r in recs:
        assert [r["verdict"], r["reason"]] == list(lr.judge(bytes.fromhex(r["frame"]))) == r["expect"]
    s = got[-1]["summary"]
    assert list(s) == SUMMARY_KEYS + ["source"]
    sha = hashlib.sha256(b"".join(lines)).hexdigest()
    assert s["source"] == {"name": "stdin", "estimates_sha256": sha, "estimates": 4, "refused": None}
    assert s["identity"] == {"packed": 4, "replied": 4, "drop": 0, "lost_on_reconnect": 0, "holds": True}
    assert s["judge"] == {"compared": 4, "differ": 0, "differences": []} and mon.seqs() == [1, 2, 3, 4]
    printed = capsys.readouterr().out
    assert "packed=4 replied=4" in printed and "identity=holds" in printed and "differ=0" in printed
    assert ("source=stdin estimates=4 sha256=%s" % sha) in printed and "refused" not in printed


@POSIX_ONLY
def test_x_live_lines_are_offered_when_complete_never_paced_by_t_ms(lc, lf, monitor, tmp_path, monkeypatch):
    """Three lines a minute apart in t_ms, written at once: each is packed when its line is complete, so the run ends
    within the slack and the frames' tstamps lie far closer than their t_ms (the file mode would wait two minutes). A
    line packed while one waits replaces it, a drop, by the existing rules."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    steps = [ready(out), jsonl([row(t_ms=0), row(t_ms=60000), row(t_ms=120000)])]
    rc, _p = live_run(lc, monkeypatch, mon.port, out, steps)
    assert rc == 0
    recs = log_lines(out)[1:-1]
    assert sorted(r["seq"] for r in recs) == [1, 2, 3]
    stamps = {r["seq"]: lf.decode_request(bytes.fromhex(r["frame"])).tstamp_ns for r in recs}
    assert stamps[3] - stamps[1] < 60000 * MS, stamps
    s = live_summary(out)
    assert s["identity"]["holds"] and s["counters"]["packed"] == 3 and s["source"]["estimates"] == 3


BAD_LIVE_LINES = [
    ("not-json", b'{"t_ms": 140,\n', "JSON"),
    ("conf-over-100", jsonl([row(t_ms=140, conf=101)]), "conf"),
    ("an-unknown-key", jsonl([row(t_ms=140, frame=12)]), "frame"),
    ("a-key-given-twice", jsonl([row(t_ms=140)]).replace(b'"conf": 90', b'"conf": 90, "conf": 91'), "twice"),
    ("a-blank-line", b"\n", "JSON"),
    ("not-utf-8", b'{"t_ms": 140, "\xff": 1}\n', "UTF-8"),
    ("nan", jsonl([row(t_ms=140)]).replace(b'"offset_m": 0.1', b'"offset_m": NaN'), "JSON"),
    ("beyond-binary32", jsonl([row(t_ms=140, offset_m=1e39)]), "binary32"),
    ("t_ms-before-the-line-above", jsonl([row(t_ms=99)]), "before line 1's 100"),
]


@POSIX_ONLY
@pytest.mark.parametrize("bad,what", [(b, w) for _n, b, w in BAD_LIVE_LINES], ids=[n for n, _b, _w in BAD_LIVE_LINES])
def test_x_the_first_bad_line_ends_the_source_and_the_run_exits_1(lc, monitor, tmp_path, monkeypatch, capsys, bad, what):
    """A good line, then a bad one with a good line after it in the same write, and the pipe left open: the source ends
    at the bad line, so the run ends with no EOF, nothing after the bad line is packed, the end is as at EOF (the first
    line's frame replied), and the summary names line 2 and why. The exit code is 1 (2 stays a refusal before any
    connection and any file); the sha256 and the count are the lines taken, the bad one not among them."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    first = jsonl([row(t_ms=100)])
    steps = [ready(out), first, replied(out, 1), bad + jsonl([row(t_ms=180)]), 0.2, jsonl([row(t_ms=220)])]
    rc, prod = live_run(lc, monkeypatch, mon.port, out, steps, keep_open=True)
    assert rc == 1 and prod.held == [True, True]
    assert [(r["seq"], r["outcome"]) for r in log_lines(out)[1:-1]] == [(1, "replied")]
    s = live_summary(out)
    ref = s["source"]["refused"]
    assert ref is not None and ref["line"] == 2 and what in ref["why"] and not ref["why"].startswith("line"), ref
    assert s["source"]["estimates"] == 1 and s["source"]["estimates_sha256"] == hashlib.sha256(first).hexdigest()
    assert s["identity"] == {"packed": 1, "replied": 1, "drop": 0, "lost_on_reconnect": 0, "holds": True}
    assert mon.seqs() == [1]
    printed = capsys.readouterr().out
    assert "refused: line 2: " in printed and "estimates=1 " in printed, printed


ODD_KEYS = [
    ("a-newline-and-a-non-ascii-character", "x\nlaneclient: packed=9 replied=9 identity=holds é"),
    ("a-lone-surrogate", "x\ud800"),
]


@POSIX_ONLY
@pytest.mark.parametrize("key", [k for _n, k in ODD_KEYS], ids=[n for n, _k in ODD_KEYS])
def test_x_the_summary_line_is_one_ascii_line_whatever_the_refused_line_holds(lc, monitor, tmp_path, monkeypatch, capsys,
                                                                              key):
    """A refusal's reason can carry the producer's text (an unknown key is named as it is): on stdout's one summary line
    it is JSON-escaped, so a newline in it starts no second line (a forged summary after it) and a non-ASCII character
    or a lone surrogate is an escape, not a byte stdout may refuse; the log's summary holds the reason as it is."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    steps = [ready(out), jsonl([row(t_ms=100)]), replied(out, 1), jsonl([row(t_ms=140, **{key: 1})])]
    rc, prod = live_run(lc, monkeypatch, mon.port, out, steps, keep_open=True)
    assert rc == 1 and prod.held == [True, True]
    printed = capsys.readouterr().out
    assert printed.count("\n") == 1 and printed.endswith("\n") and printed.isascii(), printed
    assert printed.startswith("laneclient: packed=1 ") and "refused: line 2: unknown key(s) " in printed, printed
    assert json.dumps(key)[1:-1] in printed, printed
    ref = live_summary(out)["source"]["refused"]
    assert ref["line"] == 2 and key in ref["why"], ref


@POSIX_ONLY
@pytest.mark.parametrize("bad,what", [(r, w) for _n, r, w in REFUSED_ROWS], ids=[n for n, _r, _w in REFUSED_ROWS])
def test_x_each_refused_field_ends_the_live_source_naming_its_line(lc, monitor, tmp_path, monkeypatch, bad, what):
    """Each refusal of the file's table, as a live line, ends the source at line 2 and names its field."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    first = jsonl([row(t_ms=0)])
    steps = [ready(out), first, replied(out, 1), jsonl([bad]) + jsonl([row(t_ms=80)])]
    rc, prod = live_run(lc, monkeypatch, mon.port, out, steps, keep_open=True)
    assert rc == 1 and prod.held == [True, True]
    s = live_summary(out)
    ref = s["source"]["refused"]
    assert ref["line"] == 2 and what in ref["why"], ref
    assert s["counters"]["packed"] == 1 and s["source"]["estimates_sha256"] == hashlib.sha256(first).hexdigest()


@POSIX_ONLY
def test_x_the_live_time_order_is_held_against_the_line_before(lc, monitor, tmp_path, monkeypatch):
    """An equal t_ms is taken, one below the line before it is not, whichever line came first."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    lines = [jsonl([row(t_ms=t)]) for t in (100, 300, 300, 200)]
    steps = [ready(out)]
    for k, ln in enumerate(lines, start=1):
        steps += [ln] + ([replied(out, k)] if k < 4 else [])
    rc, _p = live_run(lc, monkeypatch, mon.port, out, steps)
    assert rc == 1
    s = live_summary(out)
    assert s["source"]["refused"]["line"] == 4 and "before line 3's 300" in s["source"]["refused"]["why"]
    assert s["source"]["estimates"] == 3 and s["counters"]["packed"] == 3


@POSIX_ONLY
def test_x_an_unterminated_tail_at_eof_is_a_bad_line(lc, monitor, tmp_path, monkeypatch):
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    first = jsonl([row(t_ms=0)])
    steps = [ready(out), first, replied(out, 1), jsonl([row(t_ms=40)])[:-1]]          # then EOF
    rc, _p = live_run(lc, monkeypatch, mon.port, out, steps)
    assert rc == 1
    s = live_summary(out)
    assert s["source"]["refused"]["line"] == 2 and "no newline" in s["source"]["refused"]["why"]
    assert s["source"]["estimates"] == 1 and s["source"]["estimates_sha256"] == hashlib.sha256(first).hexdigest()
    assert s["counters"]["packed"] == 1 and mon.seqs() == [1]


@POSIX_ONLY
def test_v_a_blank_tail_at_eof_is_a_bad_line(lc, monitor, tmp_path, monkeypatch):
    """a tail of spaces with no newline at EOF is an unterminated tail too."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    rc, _p = live_run(lc, monkeypatch, mon.port, out, [ready(out), jsonl([row(t_ms=0)]), replied(out, 1), b"  "])
    s = live_summary(out)
    assert rc == 1 and s["source"]["refused"]["line"] == 2 and "no newline" in s["source"]["refused"]["why"]


@POSIX_ONLY
def test_v_a_read_error_on_stdin_ends_the_source_as_a_refusal_of_the_next_line(lc, monitor, tmp_path, monkeypatch):
    """a read error on the live source's stream is a refusal of the next line (exit 1), not an EOF."""
    real_os = lc.os
    reads = []

    class OsProxy:
        def __getattr__(self, name):
            return getattr(real_os, name)

        @staticmethod
        def read(fd, n):
            reads.append(fd)
            if len(reads) == 2:
                raise OSError(errno.EIO, "input/output error")
            return real_os.read(fd, n)
    monkeypatch.setattr(lc, "os", OsProxy())
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    steps = [ready(out), jsonl([row(t_ms=0)]), replied(out, 1), jsonl([row(t_ms=40)])]
    rc, _p = live_run(lc, monkeypatch, mon.port, out, steps, keep_open=True)
    s = live_summary(out)
    assert rc == 1 and s["source"]["refused"]["line"] == 2 and "cannot be read" in s["source"]["refused"]["why"]
    assert s["counters"]["packed"] == 1


@POSIX_ONLY
def test_v_a_live_frame_that_can_go_out_never_waits_for_the_next_select(lc, monitor, tmp_path, monkeypatch):
    """each live offer is followed by a send attempt, so no wait for the next line starts with a frame queued on an
    open, idle connection."""
    seen = []

    class Watched(lc.LaneClient):
        def wait(self, timeout_s, fds=()):
            if fds and self.queued is not None and self.connected and self.outstanding is None:
                seen.append(self.queued.seq)
            return super().wait(timeout_s, fds)
    monkeypatch.setattr(lc, "LaneClient", Watched)
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    steps = [ready(out), jsonl([row(t_ms=0)]), replied(out, 1), jsonl([row(t_ms=40)]), replied(out, 2),
             jsonl([row(t_ms=80)]), replied(out, 3)]
    rc, prod = live_run(lc, monkeypatch, mon.port, out, steps)
    assert rc == 0 and prod.held == [True] * 4 and seen == []


CAP_CASES = [
    ("4096-in-one-write", [padded(row(t_ms=40), 4096)], True),
    ("4096-in-two-writes", [padded(row(t_ms=40), 4096)[:-1], 0.2, b"\n"], True),
    ("4097", [padded(row(t_ms=40), 4097)], False),
    ("4097-in-two-writes", [padded(row(t_ms=40), 4097)[:2000], 0.2, padded(row(t_ms=40), 4097)[2000:]], False),
]


@POSIX_ONLY
@pytest.mark.parametrize("parts,taken", [(p, t) for _n, p, t in CAP_CASES], ids=[n for n, _p, _t in CAP_CASES])
def test_x_a_live_line_is_at_most_4096_bytes_its_newline_included(lc, monitor, tmp_path, monkeypatch, parts, taken):
    """The wire's cap: a line of 4096 bytes with its newline is taken, whether it comes in one write or its newline after
    a pause; one of 4097 is a bad line."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    steps = [ready(out), jsonl([row(t_ms=0)]), replied(out, 1)] + parts
    rc, _p = live_run(lc, monkeypatch, mon.port, out, steps)
    s = live_summary(out)
    if taken:
        assert rc == 0 and s["source"]["refused"] is None and s["counters"]["replied"] == 2 and mon.seqs() == [1, 2]
    else:
        assert rc == 1 and s["source"]["refused"]["line"] == 2 and "4096" in s["source"]["refused"]["why"]
        assert s["counters"]["packed"] == 1


@POSIX_ONLY
def test_x_4096_bytes_with_no_newline_are_refused_before_more_comes(lc, monitor, tmp_path, monkeypatch):
    """4096 bytes with no newline can be no line within the cap: the source ends there, with the pipe still open and its
    newline never written, rather than reading on."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    head = b'{"t_ms": 40'
    steps = [ready(out), jsonl([row(t_ms=0)]), replied(out, 1), head + b" " * (4096 - len(head))]
    rc, _p = live_run(lc, monkeypatch, mon.port, out, steps, keep_open=True)
    assert rc == 1
    s = live_summary(out)
    assert s["source"]["refused"]["line"] == 2 and "4096" in s["source"]["refused"]["why"]
    assert s["counters"]["packed"] == 1


@POSIX_ONLY
def test_x_a_reply_is_taken_while_the_producer_is_silent(lc, monitor, tmp_path, monkeypatch):
    """The wait for a line is one select over the pipe and the socket: the producer writes line 2 only once the reply to
    line 1 is in the log, so a wait blind to the socket would leave that reply unread (and lost at its timeout)."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    steps = [ready(out), jsonl([row(t_ms=0)]), replied(out, 1), jsonl([row(t_ms=40)])]
    rc, prod = live_run(lc, monkeypatch, mon.port, out, steps)
    assert rc == 0 and prod.held == [True, True]
    s = live_summary(out)
    assert s["identity"] == {"packed": 2, "replied": 2, "drop": 0, "lost_on_reconnect": 0, "holds": True}
    assert s["counters"]["reply_timeouts"] == 0


@POSIX_ONLY
def test_x_a_silence_over_the_peer_s_deadline_reconnects_at_the_next_line(lc, monitor, tmp_path, monkeypatch):
    """The peer closes a connection with no frame for 150 ms, as svc's deadline does: the client sees the close while it
    waits for a line, reconnects only for the next line, loses nothing, and counts the reconnect."""
    mon = monitor(idle_close_s=0.15)
    out = tmp_path / "replies.jsonl"
    steps = [ready(out), jsonl([row(t_ms=0)]), replied(out, 1), lambda: mon.ended(0) == "idle-closed", 0.1,
             jsonl([row(t_ms=900)]), replied(out, 2)]
    rc, prod = live_run(lc, monkeypatch, mon.port, out, steps)
    assert rc == 0 and prod.held == [True] * 4
    n = live_summary(out)["counters"]
    assert (n["connects"], n["reconnects"], n["replied"], n["lost_on_reconnect"]) == (2, 1, 2, 0) and mon.accepts == 2


@POSIX_ONLY
def test_x_eof_ends_the_run_and_the_drain_sends_the_last_line(lc, monitor, tmp_path, monkeypatch):
    """A line and EOF right after it: EOF ends the source, and the end is the file mode's, so the drain lets the connect
    complete and the line's frame is sent and replied."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    rc, _p = live_run(lc, monkeypatch, mon.port, out, [ready(out), jsonl([row(t_ms=0)])])
    assert rc == 0
    assert [(r["seq"], r["outcome"]) for r in log_lines(out)[1:-1]] == [(1, "replied")]
    assert live_summary(out)["source"]["refused"] is None


@POSIX_ONLY
def test_x_a_live_source_with_no_line_holds_no_estimate_and_exits_1(lc, monitor, tmp_path, monkeypatch, capsys):
    """EOF before any line: the file mode refuses an empty file, so the live source refuses an empty stream (its line
    null), with the reply log made, so exit 1; nothing is packed and no connection is made."""
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    rc, _p = live_run(lc, monkeypatch, mon.port, out, [ready(out)])
    assert rc == 1
    s = live_summary(out)
    assert s["source"]["refused"]["line"] is None and "holds no estimate" in s["source"]["refused"]["why"]
    assert s["source"]["estimates"] == 0 and s["source"]["estimates_sha256"] == hashlib.sha256(b"").hexdigest()
    assert s["counters"]["packed"] == 0 and mon.accepts == 0
    assert "refused: the source holds no estimate" in capsys.readouterr().out


@POSIX_ONLY
def test_x_live_accounting_holds_with_a_drop_and_frames_left_at_eof(lc, monitor, tmp_path, monkeypatch):
    """The peer holds its first reply: line 2 waits in the queue and line 3 replaces it (a drop), and EOF comes with
    line 1 outstanding and line 3 queued. The stop's drain takes 1's reply and sends 3, the summary is the log's last
    line, and packed = replied + drop + lost_on_reconnect with packed the count of the lines taken."""
    release = threading.Event()

    def script(ci, fi, f):
        if fi == 0:
            release.wait(SLACK_S)
        return "reply"
    mon = monitor(script=script)
    out = tmp_path / "replies.jsonl"

    def release_soon():
        threading.Timer(0.2, release.set).start()
        return True
    steps = [ready(out), jsonl([row(t_ms=0)]), lambda: len(mon.frames()) == 1, jsonl([row(t_ms=40)]), 0.1,
             jsonl([row(t_ms=80)]), 0.1, release_soon]
    rc, prod = live_run(lc, monkeypatch, mon.port, out, steps)
    assert rc == 0 and prod.held == [True, True, True]
    recs = log_lines(out)[1:-1]
    assert sorted((r["seq"], r["outcome"]) for r in recs) == [(1, "replied"), (2, "drop"), (3, "replied")]
    s = live_summary(out)
    assert s["identity"] == {"packed": 3, "replied": 2, "drop": 1, "lost_on_reconnect": 0, "holds": True}
    assert s["source"]["estimates"] == s["counters"]["packed"] == 3 and mon.seqs() == [1, 3]


def test_x_on_windows_the_live_source_refuses_with_exit_2_before_any_connection_or_file(lc, monitor, tmp_path,
                                                                                        monkeypatch, capsys):
    """- needs a select over a pipe, which Windows does not have: there it refuses before any connection and any file
    (here ON_WINDOWS is set by hand, so the refusal is held on every host)."""
    monkeypatch.setattr(lc, "ON_WINDOWS", True)
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    assert lc.main(["run", "--estimates", "-", "--port", str(mon.port), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "Windows" in err
    time.sleep(0.2)
    assert mon.accepts == 0 and not out.exists()


def test_on_windows_is_this_host_s(lc):
    """ON_WINDOWS is this host's, and laneclient.py's assignment of it gives True for os.name "nt" and False for "posix",
    so it is held on every host (a constant False would pass the first check everywhere but on Windows)."""
    assert lc.ON_WINDOWS is (os.name == "nt")
    found = [n.value for n in ast.parse(CLIENT_FILE.read_text(encoding="utf-8")).body
             if isinstance(n, ast.Assign) and [getattr(t, "id", None) for t in n.targets] == ["ON_WINDOWS"]]
    assert len(found) == 1
    expr = compile(ast.Expression(body=found[0]), str(CLIENT_FILE), "eval")
    got = {name: eval(expr, {"os": types.SimpleNamespace(name=name)}) for name in ("nt", "posix")}
    assert got == {"nt": True, "posix": False}, got


class _NoStdin:
    """stdin's stand-in whose descriptor is not open (made and closed just before the run)."""

    def __init__(self):
        r, w = os.pipe()
        os.close(r)
        os.close(w)
        self.fd = r

    def fileno(self):
        return self.fd


@POSIX_ONLY
@pytest.mark.parametrize("which", ["none", "closed"])
def test_x_a_live_run_with_stdin_not_open_refuses_with_exit_2(lc, monitor, tmp_path, monkeypatch, capsys, which):
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    rc, _p = live_run(lc, monkeypatch, mon.port, out, [], stdin=(lambda: None) if which == "none" else _NoStdin)
    assert rc == 2 and "stdin" in capsys.readouterr().err
    time.sleep(0.2)
    assert mon.accepts == 0 and not out.exists()


def test_x_check_refuses_stdin_and_a_file_named_dash_is_reached_as_dot_slash_dash(lc, monitor, tmp_path, monkeypatch,
                                                                                  capsys):
    """check reads a file: - refuses with exit 2 even beside a file named -, which is reached as ./- by check and by
    run's file mode alike."""
    monkeypatch.chdir(tmp_path)
    dash = tmp_path / "-"
    dash.write_bytes(jsonl([row(t_ms=0), row(t_ms=33)]))
    assert lc.main(["check", "--estimates", "-"]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "./-" in err
    assert lc.main(["check", "--estimates", "./-"]) == 0
    assert capsys.readouterr().out.startswith("laneclient: check: 2 estimates")
    mon = monitor()
    out = tmp_path / "replies.jsonl"
    assert lc.main(["run", "--estimates", "./-", "--port", str(mon.port), "--out", str(out)]) == 0
    h = log_lines(out)[0]["header"]
    assert list(h) == FILE_HEADER_KEYS and h["estimates_sha256"] == hashlib.sha256(dash.read_bytes()).hexdigest()


def test_x_the_file_mode_s_header_and_summary_keep_their_keys(lc, monitor, tmp_path, capsys):
    """The file mode does not change: its header, its summary and its summary line hold no key or word of the live
    source's."""
    mon = monitor()
    est_file = write_estimates(tmp_path, [row(t_ms=0), row(t_ms=20)])
    out = tmp_path / "replies.jsonl"
    assert lc.main(["run", "--estimates", str(est_file), "--port", str(mon.port), "--out", str(out)]) == 0
    lines = log_lines(out)
    assert list(lines[0]["header"]) == FILE_HEADER_KEYS and list(lines[-1]["summary"]) == SUMMARY_KEYS
    assert "source" not in capsys.readouterr().out


GIT = ["git"]                                                   # how the comparison runs git (a test puts a stand-in here)
BASE_COMMIT = "4f659c4cd5cf57b740519cef84b298b79c7bef9b"        # C2b S5-T's base: a commit of the project's local history
BASE_BLOB = "0674bf42917e39815a3a20745729bf9f5eb869fd"          # its sdv/lane/laneclient.py (git hash-object)
TSTAMP_HEX = re.compile(rb'("frame":"[0-9a-f]{16})[0-9a-f]{16}')


def git_unusable():
    """Why this test cannot run git on this tree here (None when it can): a worktree whose .git file names a Windows
    path, read from anything but Windows (WSL's git cannot follow it, and no test runs git there)."""
    g = REPO / ".git"
    if g.is_file() and os.name != "nt" and re.match(r"gitdir: [A-Za-z]:[\\/]", g.read_text(encoding="utf-8", errors="replace")):
        return "the worktree's .git file names a Windows path: this test runs from Windows (the git block)"
    return None


def base_unreachable():
    """Why git cannot give the base's laneclient.py here (None when it can): git cannot run on this tree here
    (git_unusable); the tree has no .git (an export, a batch copy, a mutant's scratch tree: git is then not asked); git
    cannot start; or BASE_COMMIT is no commit of this repository (a clone without the local base: main after a scrubbed
    batch, a shallow checkout). The commit is named in full, so it cannot become ambiguous and skip."""
    why = git_unusable()
    if why is not None:
        return why
    if not (REPO / ".git").exists():
        return "the tree has no .git (an export or a copy of it): git cannot give the base"
    try:
        r = subprocess.run(GIT + ["-C", str(REPO), "cat-file", "-e", BASE_COMMIT + "^{commit}"], capture_output=True,
                           timeout=60)
    except OSError as err:
        return "git cannot run here (%s): it cannot give the base" % err
    if r.returncode != 0:
        return "the base %s is no commit of this repository (a clone without it): git cannot give the base" % BASE_COMMIT
    return None


def test_x_the_file_mode_s_outputs_are_the_base_s_but_for_each_frame_s_tstamp(lc, lr, monitor, tmp_path, capsys):
    """The base's laneclient.py, taken by git show and held to its blob id, and this tree's, each run in file mode on one
    file against one fake monitor: the exit codes, stdout, stderr and replies.jsonl are equal byte for byte once each
    frame's tstamp (bytes 8..15, the client's clock) is masked. It skips, saying why, where git cannot give the base
    (base_unreachable). A skip is no pass: the run by name on Windows is where it must say PASSED."""
    why = base_unreachable()
    if why is not None:
        pytest.skip(why)
    r = subprocess.run(GIT + ["-C", str(REPO), "show", BASE_COMMIT + ":sdv/lane/laneclient.py"], capture_output=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    assert hashlib.sha1(b"blob %d\0" % len(r.stdout) + r.stdout).hexdigest() == BASE_BLOB
    d = tmp_path / "base"
    d.mkdir()
    (d / "laneclient.py").write_bytes(r.stdout)
    spec = importlib.util.spec_from_file_location("laneclient_base", d / "laneclient.py")
    base = importlib.util.module_from_spec(spec)
    saved_path, saved_bc = list(sys.path), sys.dont_write_bytecode
    sys.modules["laneclient_base"] = base
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(base)
    finally:
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_bc
    try:
        mon = monitor()
        est_file = write_estimates(tmp_path, [row(t_ms=0), row(t_ms=30, conf=10), row(t_ms=60, **NO_LANE),
                                              row(t_ms=90, v_mps=None, yaw_rps=None, age_ms=70000)])
        got = []
        for name, mod in (("base", base), ("tree", lc)):
            out = tmp_path / ("replies-%s.jsonl" % name)
            rc = mod.main(["run", "--estimates", str(est_file), "--port", str(mon.port), "--out", str(out),
                           "--expect-judge"])
            data, k = TSTAMP_HEX.subn(rb"\g<1>" + b"0" * 16, out.read_bytes())
            assert k == 4, (name, data)
            got.append((rc, capsys.readouterr(), data))
    finally:
        sys.modules.pop("laneclient_base", None)
    assert got[0] == got[1]
    assert got[1][0] == 0 and mon.seqs() == [1, 2, 3, 4, 1, 2, 3, 4]


GIT_SAYS_NO = [sys.executable, "-c", "import sys; sys.exit(1 if 'cat-file' in sys.argv else 3)"]   # git's stand-in


def test_x_the_base_comparison_skips_in_a_tree_with_no_git(lc, lr, monitor, tmp_path, capsys, monkeypatch):
    """A copy of the tree with no .git (an export, a batch copy, a mutant's scratch tree): git cannot give the base, so
    the comparison skips and names the missing .git, and asks git nothing (git here is a stand-in that says no)."""
    tree = tmp_path / "export"
    tree.mkdir()
    monkeypatch.setitem(globals(), "REPO", tree)
    monkeypatch.setitem(globals(), "GIT", GIT_SAYS_NO)
    with pytest.raises(pytest.skip.Exception) as got:
        test_x_the_file_mode_s_outputs_are_the_base_s_but_for_each_frame_s_tstamp(lc, lr, monitor, tmp_path, capsys)
    assert "no .git" in str(got.value), got.value


@pytest.mark.parametrize("git,why", [("says-no", "is no commit"), ("cannot-start", "cannot run")],
                         ids=["says-no", "cannot-start"])
def test_x_the_base_comparison_skips_where_git_cannot_give_the_base_commit(lc, lr, monitor, tmp_path, capsys, monkeypatch,
                                                                           git, why):
    """A tree with a .git whose git does not hold the base commit (a clone of main after a scrubbed batch, a shallow
    checkout), or a host whose git cannot start: the comparison skips and says why, rather than failing at git show."""
    tree = tmp_path / "clone"
    (tree / ".git").mkdir(parents=True)
    monkeypatch.setitem(globals(), "REPO", tree)
    monkeypatch.setitem(globals(), "GIT", GIT_SAYS_NO if git == "says-no" else [str(tmp_path / "no-such-git")])
    with pytest.raises(pytest.skip.Exception) as got:
        test_x_the_file_mode_s_outputs_are_the_base_s_but_for_each_frame_s_tstamp(lc, lr, monitor, tmp_path, capsys)
    assert why in str(got.value), got.value


# ============================================================ what the README and the module docstring say

def flat(text):
    """The text with its backticks dropped and every run of whitespace one space: a sentence as it reads across its
    wrapped lines."""
    return " ".join(text.replace("`", "").split())


def lane_readme():
    return flat((LANE_DIR / "README.md").read_text(encoding="utf-8"))


TAKES_ONLY = ("the client takes only a reply with nothing but p[6] and p[7] written, as a monitor's plain TCP mode (PORT) "
              "and its svc mode (PORT svc) reply, and a stamp port (PORT stamp")
NO_TARGET = ("is no target: the stamp mode, the one mode that writes more, puts t_in and t_out at p[8..23] in every reply, "
             "so each is reply_invalid and its frame")
STILL_0 = "(without --expect-judge such a run still exits 0, as the identity holds)"


def test_the_readme_and_the_docstring_say_the_client_takes_only_a_reply_with_p6_and_p7_written(lc):
    """B8, in the package 5 critic's words (its #3): the client takes a reply only with nothing but p[6] and p[7]
    written, the plain TCP mode's and the svc mode's (monitor.c's stamp mode is the one mode that writes more), so a
    stamp port is no target. The README's client section and the module docstring each say so once, and neither says
    the svc mode's replies only."""
    readme, doc = lane_readme(), flat(lc.__doc__ or "")
    for name, text in (("README", readme), ("docstring", doc)):
        for phrase in (TAKES_ONLY, NO_TARGET, STILL_0):
            assert text.count(phrase) == 1, (name, phrase)
        assert "svc mode's replies only" not in text, name
    assert "stamp port (PORT stamp, as ifs-lane.build's :7171) is no target" in readme


def test_the_readme_describes_make_lane_and_ifs_lane_build_and_the_native_test_limits():
    """B9: sdv/lane/README.md says the guest's build exists (make lane, 0x54, and ifs-lane.build, which starts kind 6
    on :7170 svc 500 and :7171 stamp), describes what the build file stages before its first section, '## The frame',
    and states the native-test limits without a board-run outcome, and nowhere
    that no guest build exists or that they wait (or it waits) for WP3c F-c; the Makefile target and the two start
    lines it names are this tree's."""
    readme = lane_readme()
    assert "no guest build" not in readme
    assert "wait for WP3c F-c" not in readme
    assert "waits for WP3c F-c" not in readme
    assert "waiting for WP3c F-c" not in readme
    assert not [s for s in readme.split(". ") if "F-c" in s and "wait" in s.lower()], readme  # awaits, waiting on, ...
    assert readme.count("The guest's build is make lane (0x54), whose binary ipc-test/qnx-safety-monitor/ifs-lane.build "
                        "stages to serve kind 6 on :7170 svc 500 and :7171 stamp;") == 1
    built = ("make lane refuses a generation without kind 4's profile 5, which WP3c F-c compiled. "
             "The build file stages the binary produced by make lane.")
    assert readme.split("## The frame", 1)[0].count(built) == 1 and readme.count(built) == 1
    limits = readme.split("## What this does not demonstrate", 1)[1]
    assert ("make lane and ifs-lane.build define the guest build and its ports. The native tests use gcc "
            "for the PC; they do not build, boot or serve the guest image.") in limits
    mon = REPO / "ipc-test" / "qnx-safety-monitor"
    assert ".PHONY: lane\nlane: $(LANE)\n" in (mon / "Makefile").read_text(encoding="ascii")
    starts = (mon / "ifs-lane.build").read_text(encoding="utf-8").splitlines()
    assert "/proc/boot/qnx-safety-monitor 7170 svc 500 &" in starts and "/proc/boot/qnx-safety-monitor 7171 stamp &" in starts


def test_a_stamp_port_is_no_target_and_the_run_exits_0_without_expect_judge(lc, monitor, tmp_path, capsys):
    """B8's sentence, held by what the client does: a peer that answers as the stamp mode does (each reply as
    lanerules judges it, with t_in and t_out written at p[8..23]) has no reply taken. Each frame sent is lost as
    reply_invalid, its line naming p[8..23], the identity holds and the run exits 0; with --expect-judge it exits 1,
    nothing compared."""
    mon_ref = []

    def script(ci, fi, f):
        b = bytearray(mon_ref[0].answer(f))
        b[H + 8:H + 24] = struct.pack("<QQ", T0, T0 + MS)
        return [("raw", bytes(b))]
    mon = monitor(script=script)
    mon_ref.append(mon)
    est_file = write_estimates(tmp_path, [row(t_ms=0), row(t_ms=40, conf=10)])
    for extra, want in (([], 0), (["--expect-judge"], 1)):
        out = tmp_path / ("replies-%d.jsonl" % want)
        rc = lc.main(["run", "--estimates", str(est_file), "--port", str(mon.port), "--out", str(out)] + extra)
        lines = log_lines(out)
        s = lines[-1]["summary"]
        assert rc == want, (extra, s)
        n = s["counters"]
        assert n["replied"] == 0 and n["reply_invalid"] >= 1 and s["identity"]["holds"], s
        lost = [r for r in lines[1:-1] if r["outcome"] == "lost"]
        assert len(lost) == n["reply_invalid"] and all("p[8..23]" in r["layout"] for r in lost), lines
        printed = capsys.readouterr().out
        assert "identity=holds" in printed and ("nothing compared" in printed) == bool(extra), printed
