"""kind4-spec 16.2 P1-P8, P10, P11, P13 and P15-P18: the kind 4 claim bridge's core (sdv/bridge; sdv Phase 2, WP6).

sdv/bridge/vss_claim_bridge.py packs one kind 4 claim per 10 Hz tick from the latest held values and sends it to
the monitor; sdv/bridge/reasonsets.py holds Phase 2 step 3's event-to-reason comparison. What is tested, and how:

- Deterministically, through ClaimCore with every instant passed in (no clock, no socket): the layout (P1), the
  age and its counters (P2), ticks with nothing held (P3), mode-independent packing (P4), no unit conversion (P5),
  the rule-26 skip counters against the generated table and rules.kinematics (P10), and the spread's accounting
  and attribution edges (P15), the latter also against contracts derived by sdv/vss/generate.py's own derive()
  from a profile file with another tol and a DBC with another period, so both edges are shown to come from the
  generated constants. The 1-deep queue, the seq at packing and the seq partition (replied, dropped and lost seqs
  cover 1..packed, disjoint) are checked in every run that ends.
- End to end against the native vss monitor (`monitor PORT svc 500`, built as test_monitor_kind4._build builds it:
  the native_vss line, -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 under -Werror), with a fake feed at slice.dbc's
  periods: injection (P6), the connection rules with a late connect, a stall mid-stream, a restart, a frame in
  flight when the monitor is killed, and a SIGSTOPped monitor that never replies, which the bridge gives up on after
  the 500 ms reply timeout, counts as lost_on_reconnect and closes (its close record, the lock released at it and
  taken again at the lazy reconnect, and the monitor, once it runs, seeing the given-up connection end) (P7); a
  stamp-mode exchange against `monitor PORT stamp`, whose stamps a target marked stamp allows and an unmarked one
  takes for an invalid reply; the two pause sequences, read off both the
  bridge's reply log and the monitor's console, and the frame queued when the tick pauses, which is dropped
  rather than sent inside the pause (white-box in each order the claim thread's next pass can come: a paused
  tick, the outstanding frame's reply, a stop's drain; and the review's S11 schedule: monitor stopped, bridge in
  its backoff, tick paused, monitor restarted) (P8); the scenario lock at every transition, through an observer
  the claim thread calls at the moment of each connect and close, and the updater's check as its double (P16); the
  demo-ODD window with honest cruise frames rejected 23 inside it only (P17); and a stalled stream, with the
  write-back stalled too, during which the ticks go on, the monitor logs no MISS, the values age into 22 and the
  full write-back queue drops and counts (P18).
- Against a Python peer that records its own view of each connection (accepted, frames, how it ended): one that
  answers 26 (P15's attribution, end to end), accepts everything (the command line, the event log's single file
  writer, an intake that outlives a malformed item, a start refusal that leaves no run directory, and SIGTERM or
  SIGINT ending a run given --seconds, in a subprocess, with its summary), answers late (the stop's drain: nothing
  outstanding or queued at a stop is lost), holds one reply until the tick is paused (P8: that reply releases
  nothing queued before the pause), never answers on its first connection (P7: the peer sees the bridge close it
  500 ms after its frame, then a new connection), answers one frame invalidly or twice (reply_invalid and
  stray_bytes, each closing the connection), or meets a lock held elsewhere (P16: each lock-busy attempt a
  connection closed unused, the next one only after the logged backoff); against a listener whose accept queue
  is full, so a connect stays pending: no lock while it is pending, and the connect timeout ends it (P16, P7).
- The scenario lock's path (P16): by default created if absent; in either setting a path that is not a regular
  file (/dev/null, a FIFO) refused; with SDV_SCENARIO_LOCK_MUST_EXIST=1 (the image's setting) only the designated
  path, existing, a regular file and a mount point -- here a tmp path and a mountinfo file standing in for
  /run/lock and /proc/self/mountinfo -- so a missing file (never created), --lock or SDV_SCENARIO_LOCK naming
  /dev/null or another file (the previous round's private lock, also through the command line), and a file that
  is not a mount point are each refused at start, with a hint chosen by errno.
- The import graph (P11) and the event-to-reason sets (P13).

Every test that ends a run holds the run to spec 14.2's identity (packed = replied + drop + lost_on_reconnect,
computed here from the counters and as the summary states it), ticks = packed + ticks_empty, the seq partition and
nothing left in flight.

What this does NOT show: any timing (the slacks below only bound when a line may come on a loaded host); anything
about the guest (the monitor here is the native build of monitor.c, not the qcc binary); the source adapters, the
container, the Monitor write-back's paths and the L checks against a databroker (P4's replay half, P9, P12, P14:
tests/test_sdv_bridge_sources.py).

Needs the generated contract (sdv-out/gen); the native tests also need gcc on Linux (WSL Ubuntu-24.04 or CI's
tooling job).
"""
import ast
import copy
import errno
import hashlib
import json
import math
import os
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import test_monitor_kind4 as tmk
import test_monitor_vss as tmv
import test_sdv_frame as tsf
import test_sdv_vss as tsv

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BRIDGE_DIR = REPO / "sdv" / "bridge"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))
import reasonsets as rs  # noqa: E402
import vss_claim_bridge as vb  # noqa: E402

sys.dont_write_bytecode = _saved

rules = tsf.rules
vf = tsf.vf
C = tsf.C
H = vf.FRAME_HEADER_BYTES
MS = 1_000_000

pytestmark = [tsf.NEEDS_CONTRACT]

NAMES = ("v", "a_x", "delta", "psi_dot", "gear")
HONEST = {"v": 5.0, "a_x": 0.0, "delta": 0.0, "psi_dot": 0.0, "gear": 1}
SLACK = 0.25          # how late a timed event may be on a loaded host, s


# ============================================================ helpers

def nominal():
    return tsf.nominal()


def vehicle(pid=None):
    """The declared source vehicle of profile pid's row (the nominal profile's for an id with no row)."""
    rows = {r["id"]: r for r in C.PROFILES}
    row = rows.get(pid, rows[nominal()])
    return {"name": row["source_vehicle"], "wheelbase_mm": row["l_mm"]}


def cfg(port=0, **kw):
    base = dict(host="127.0.0.1", port=port or 1, mode="replay", profile_id=nominal(), profile_source="scenario",
                source_vehicle=vehicle(kw.get("profile_id")))
    base.update(kw)
    return vb.Config(**base)


def core(c=None, contract=None):
    c = c or cfg()
    tables, problems = vb.bind(c, contract or C)
    assert not problems, problems
    return vb.ClaimCore(c, contract or C, tables, vb.EventLog())


def snap(t=10**12, **slots):
    """A held-values snapshot: each named slot as value or (value, t_ns)."""
    out = []
    for i, n in enumerate(NAMES):
        if n in slots:
            val, ts = slots[n] if isinstance(slots[n], tuple) else (slots[n], t)
            out.append((vb.raw_of(i, val), ts))
        else:
            out.append(None)
    return tuple(out)


def honest_snap(t=10**12, **kw):
    s = dict(HONEST)
    s.update(kw)
    return snap(t, **s)


def answer(p, verdict, reason):
    b = bytearray(p.frame)
    b[H + vf.P_VERDICT], b[H + vf.P_REASON] = verdict, reason
    return bytes(b)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_until(pred, timeout=5.0, what="a condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError("timed out after %.1f s waiting for %s" % (timeout, what))


def replies(b):
    return list(b.replies.records)


def ended(b):
    """Stop a run and hold it to spec 14.2 (module docstring)."""
    s = b.stop()
    n = s["counters"]
    assert s["fatal"] is None, s["fatal"]
    assert n["packed"] == n["replied"] + n["drop"] + n["lost_on_reconnect"], n
    assert s["identity"]["holds"] and s["identity"]["lost_on_reconnect"] == n["lost_on_reconnect"], s["identity"]
    assert n["ticks"] == n["packed"] + n["ticks_empty"] and s["ticks_identity"]["holds"], n
    assert s["seq_partition"]["holds"], s["seq_partition"]
    assert s["in_flight"] == {"outstanding": None, "queued": None}, s["in_flight"]
    assert sorted(b.core.replied_seqs) == sorted(r["seq"] for r in replies(b))
    return s


class LiveSource(vb.QueueSource):
    """A fake feed at slice.dbc's periods (the generated DBC_PERIOD_MS): the four SliceDynamics slots together, the
    gear on its own, each update timestamped on CLOCK_MONOTONIC, the clock now_ns reads."""

    def __init__(self, **values):
        super().__init__()
        self.values = dict(HONEST, **values)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _run(self):
        period = {m: C.DBC_PERIOD_MS[m] * MS for m in set(C.SLOT_DBC_MESSAGES)}
        due = {m: time.monotonic_ns() for m in period}
        while not self._stop.is_set():
            now = time.monotonic_ns()
            batch = []
            for m in period:
                if now >= due[m]:
                    batch += [vb.Update(i, self.values[NAMES[i]], now) for i in range(vf.N_SLOTS) if C.SLOT_DBC_MESSAGES[i] == m]
                    due[m] += period[m]
            if batch:
                self.push(*batch)
            time.sleep(0.002)

    def close(self):
        self._stop.set()
        super().close()


class StallableSource(LiveSource):
    """A fake broker stream that can stall: while stalled, nothing reaches the intake (its iterator blocks)."""

    def __init__(self, **values):
        super().__init__(**values)
        self.flowing = threading.Event()
        self.flowing.set()

    def updates(self):
        for batch in super().updates():
            self.flowing.wait()
            yield batch

    def close(self):
        self.flowing.set()
        super().close()


class SvcMonitor:
    """The native vss monitor in svc mode on one port, restartable; its stdout read as it prints, each line stamped."""

    def __init__(self, binary, port, deadline_ms=500):
        self.binary, self.port, self.deadline_ms = binary, port, deadline_ms
        self.lines = []
        self.p = None
        self.start()

    def start(self):
        n = len(self.lines)
        self.p = subprocess.Popen([self.binary, str(self.port), "svc", str(self.deadline_ms)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        threading.Thread(target=self._read, args=(self.p,), daemon=True).start()
        self.wait_for("liveness deadline", after=n)

    def _read(self, p):
        for line in p.stdout:
            self.lines.append((time.monotonic(), line.rstrip("\n")))

    def wait_for(self, text, timeout=5.0, after=0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for t, line in self.lines[after:]:
                if text in line:
                    return t, line
            time.sleep(0.005)
        raise AssertionError("no %r within %.1f s; the monitor printed:\n%s" % (text, timeout, self.text()))

    def count(self, text, after=0):
        return sum(1 for _t, line in self.lines[after:] if text in line)

    def text(self):
        return "\n".join(line for _t, line in self.lines)

    def signal(self, sig):
        os.kill(self.p.pid, sig)

    def stop(self):
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGCONT)
            self.p.terminate()
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        return self.p.stderr.read()

    def kill(self):
        self.p.kill()
        self.p.wait()


class FakeMonitor:
    """A Python peer: one client at a time, each 64-byte frame answered with policy(frame) (None: no answer).

    conns is the peer's own view of each connection it accepted, in order: its number n (from 1), when it was accepted,
    the frames it received (each with when), and how it ended -- "eof" (the bridge closed it), "reset", or "stopped"
    (this peer's close) -- and when (time.monotonic(), the clock the bridge's t_mono counts in ns)."""

    def __init__(self, policy):
        self.policy = policy
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.srv.settimeout(0.05)
        self.port = self.srv.getsockname()[1]
        self.frames = []
        self.conns = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.srv.accept()
            except socket.timeout:
                continue
            rec = {"n": len(self.conns) + 1, "accepted": time.monotonic(), "frames": [], "end": None, "ended": None}
            self.conns.append(rec)
            conn.settimeout(0.05)
            buf = b""
            with conn:
                while not self._stop.is_set():
                    try:
                        d = conn.recv(64 - len(buf))
                    except socket.timeout:
                        continue
                    except OSError:
                        rec["end"] = "reset"
                        break
                    if not d:
                        rec["end"] = "eof"
                        break
                    buf += d
                    if len(buf) == 64:
                        self.frames.append(buf)
                        rec["frames"].append((time.monotonic(), buf))
                        out = self.policy(buf)
                        if out is not None:
                            try:
                                conn.sendall(out)
                            except OSError:
                                rec["end"] = "reset"
                                break
                        buf = b""
            rec["end"] = rec["end"] or "stopped"
            rec["ended"] = time.monotonic()

    def close(self):
        self._stop.set()
        self._thread.join(2)
        self.srv.close()


def accept_all(f):
    return f


def answer_26(f):
    b = bytearray(f)
    b[H + vf.P_VERDICT], b[H + vf.P_REASON] = rules.V_REJECT, rules.RSN_VSS_YAW
    return bytes(b)


@pytest.fixture(scope="module")
def vss_monitor(tmp_path_factory):
    if not all((tmv.GEN / h).is_file() for h in tmv.GEN_HEADERS):
        pytest.skip("needs the generated contract in sdv-out/gen (sdv/vss/generate.py)")
    return tmk._build(tmv._gcc(), tmv.GEN, tmp_path_factory.mktemp("bridge-vss"), names=("monitor",))["monitor"]


@pytest.fixture
def lock(tmp_path):
    return str(tmp_path / "scenario.lock")


@pytest.fixture(autouse=True)
def _no_default_lock(tmp_path, monkeypatch):
    """No test reaches the default lock path (/run/lock): a bridge built without lock_path gets a tmp one, which it
    may create (the image's SDV_SCENARIO_LOCK_MUST_EXIST is cleared unless a test sets it)."""
    monkeypatch.setenv("SDV_SCENARIO_LOCK", str(tmp_path / "default-scenario.lock"))
    monkeypatch.delenv(vb.LOCK_MUST_EXIST_ENV, raising=False)


@pytest.fixture
def live(vss_monitor, lock):
    """A native svc monitor at :7160's deadline, a live feed and a bridge sending to it."""
    made = {}

    def make(observer=None, writeback_sink=None, source=None, **kw):
        port = free_port()
        made["mon"] = SvcMonitor(vss_monitor, port)
        made["src"] = (source or LiveSource()).start()
        made["bridge"] = vb.Bridge(cfg(port, lock_path=lock, **kw), made["src"], contract=C, observer=observer,
                                   writeback_sink=writeback_sink).start()
        return made["bridge"], made["mon"], made["src"]

    yield make
    if "bridge" in made:
        made["bridge"].stop()
    if "mon" in made:
        made["mon"].stop()


def paused_drops(b):
    """The drops a pause may make: the frame queued when the tick paused (dropped 'paused', never sent inside the pause).
    A pause that lands between a tick's enqueue and that pass's send makes one; anything else dropped is a finding."""
    drops = b.log.find("dropped")
    assert all(e["why"] == "paused" for e in drops), drops
    return len(drops)


def accepted_after(b, seq):
    return [r for r in replies(b) if r["seq"] > seq and r["verdict"] == 0]


def last_seq(b):
    return b.core.next_seq - 1


# ============================================================ P1: the frame

def test_p1_a_packed_frame_is_the_specs_layout():
    c = core()
    t = 10**12
    p = c.tick(snap(t, v=-5.5, a_x=1.25, delta=-3.0, psi_dot=7.75, gear=-1), t + 42 * MS + 999_999, 123456789)
    f = p.frame
    assert len(f) == 64 and p.seq == 1
    assert struct.unpack_from("<QQ", f, 0) == (1, 123456789)              # seq from 1; tstamp: the bridge's monotonic ns
    pl = f[16:]
    assert pl[0] == 0x1F and pl[1] == nominal()                            # spec 2's table, offset by offset
    assert struct.unpack_from("<I", pl, 2)[0] == C.CATALOG_DIGEST
    assert pl[6] == 0 and pl[7] == 0 and pl[8:24] == bytes(16) and pl[24] == 4
    assert struct.unpack_from("<4f", pl, 25) == (-5.5, 1.25, -3.0, 7.75)
    assert struct.unpack_from("<H", pl, 41)[0] == 42                       # truncated to ms
    assert struct.unpack_from("<b", pl, 43)[0] == -1 and pl[44:48] == bytes(4)
    d = vf.decode(f)
    assert (d.v, d.a_x, d.delta, d.psi_dot, d.gear, d.age_ms) == (-5.5, 1.25, -3.0, 7.75, -1, 42)
    assert c.tick(snap(t, v=1.0), t, 1).seq == 2


def test_p1_absent_slots_are_zero_bytes_never_negative_zero():
    c = core()
    f = c.tick(snap(gear=1, v=-0.0), 10**12, 1).frame
    pl = f[16:]
    assert pl[0] == vf.F_SPEED | vf.F_GEAR
    assert pl[25:29] == struct.pack("<I", 0x80000000)                       # a present -0.0 keeps its sign
    assert pl[29:41] == bytes(12)                                           # a_x, delta, psi_dot absent: all zero
    assert rules.judge_frame(f, tsf.tables()) == tsf.ACCEPT


def test_p1_the_seq_never_reaches_the_sentinel():
    c = core()
    c.next_seq = vf.SENTINEL_SEQ - 1
    assert c.tick(honest_snap(), 10**12, 1).seq == vf.SENTINEL_SEQ - 1
    with pytest.raises(vb.BridgeError, match="sentinel"):
        c.tick(honest_snap(), 10**12, 2)


# ============================================================ P2: the age

def test_p2_the_age_is_the_oldest_used_values_truncated_and_saturated():
    c = core()
    t0 = 10**12
    s = snap(v=(5.0, t0 + 20 * MS), a_x=(0.0, t0 + 50 * MS), delta=(0.0, t0), psi_dot=(0.0, t0 + 70 * MS), gear=(1, t0 + 10 * MS))
    p = c.tick(s, t0 + 120 * MS + 999_999, 1)
    assert (p.age_ms, p.age_slot) == (120, 2)
    assert c.tick(s, t0 + 0x10000 * MS, 2).age_ms == 0xFFFF                 # saturated
    assert c.tick(s, t0 + 10**15, 3).age_ms == 0xFFFF
    p = c.tick(s, t0 - 1, 4)                                                 # a negative difference: 0, counted, logged
    assert p.age_ms == 0 and c.n["age_negative"] == 1
    assert [e["seq"] for e in c.log.find("age-negative")] == [4]
    assert rules.judge_frame(c.tick(s, t0 + 0x10000 * MS, 5).frame, tsf.tables()) == tsf.reject(22)


def test_p2_a_flag_once_set_is_never_cleared_by_age():
    held = vb.HeldValues()
    t0 = time.monotonic_ns()
    held.put([(i, vb.raw_of(i, HONEST[n]), t0) for i, n in enumerate(NAMES)])
    c = core()
    for later_ms in (100, C.AGE_MAX_MS, C.AGE_MAX_MS + 1, 1000, 10_000, 1_000_000):
        p = c.tick(held.snapshot(), t0 + later_ms * MS, 1)
        assert p.frame[16] == vf.F_SLOTS, later_ms
        assert p.age_ms == min(later_ms, 0xFFFF)
        want = tsf.reject(22) if later_ms > C.AGE_MAX_MS else tsf.ACCEPT
        assert rules.judge_frame(p.frame, tsf.tables()) == want, later_ms


def test_p2_age_over_max_names_the_seq_and_the_slot_that_set_the_age():
    c = core()
    m = C.AGE_MAX_MS
    t0 = 10**12
    gear_oldest = honest_snap(t0 + 100 * MS, gear=(1, t0))
    steer_oldest = honest_snap(t0 + 100 * MS, delta=(0.0, t0))
    p_at = c.tick(gear_oldest, t0 + m * MS + 999_999, 1)                    # exactly AGE_MAX after truncation: not logged
    p_gear = c.tick(gear_oldest, t0 + (m + 1) * MS, 2)
    p_steer = c.tick(steer_oldest, t0 + (m + 7) * MS, 3)
    assert p_at.age_ms == m and p_gear.age_ms == m + 1 and p_steer.age_ms == m + 7
    logged = [(e["seq"], e["slot"], e["age_ms"]) for e in c.log.find("age-over-max")]
    assert logged == [(p_gear.seq, 4, m + 1), (p_steer.seq, 2, m + 7)]
    assert c.n["age_over_max"] == 2


# ============================================================ P3: nothing held, nothing packed

def test_p3_no_frame_is_packed_while_no_value_is_held():
    c = core()
    assert c.tick(snap(), 10**12, 1) is None and c.tick(snap(), 10**12, 2) is None
    assert (c.n["ticks"], c.n["ticks_empty"], c.n["packed"], c.next_seq) == (2, 2, 0, 1)
    assert c.queued is None


def test_p3_a_pack_that_raises_leaves_the_ticks_identity_whole():
    """A tick is counted with its frame or as empty, never before the pack: a clock that is not int ns (an
    adapter converting timestamps) makes pack refuse, and ticks = packed + ticks_empty still holds."""
    c = core()
    c.tick(honest_snap(), 10**12 + 5 * MS, 1)
    with pytest.raises(vf.FrameError, match="age_ms must be an int"):
        c.tick(honest_snap(), float(10**12 + 6 * MS), 2)
    c.tick(snap(), 10**12, 3)
    assert (c.n["ticks"], c.n["packed"], c.n["ticks_empty"], c.next_seq) == (2, 1, 1, 2)
    assert vb.ticks_identity(c.n)["holds"] and c.queued.seq == 1


def test_p3_a_bridge_with_nothing_held_never_connects(lock):
    port = free_port()
    b = vb.Bridge(cfg(port, lock_path=lock), vb.QueueSource(), contract=C).start()
    time.sleep(0.45)
    assert vb.updater_check(lock), "before the first connect the lock is free (P16)"
    s = ended(b)
    n = s["counters"]
    assert n["ticks"] >= 3 and n["ticks"] == n["ticks_empty"] and n["packed"] == 0
    assert n["connects"] == n["connect_failures"] == 0 and not b.log.find("connect")


# ============================================================ P4, P5: packing is mode-independent and converts nothing

def test_p4_the_same_held_values_give_the_same_payload_in_every_mode():
    s = honest_snap(10**12, v=13.25, delta=-2.5, psi_dot=-6.0)
    frames = {}
    for mode in vb.MODES:
        c = core(cfg(mode=mode))
        frames[mode] = (c.tick(s, 10**12 + 30 * MS, 777).frame, c.tick(s, 10**12 + 30 * MS, 999).frame)
    assert len({f[0] for f in frames.values()}) == 1, "same instant: the same bytes"
    for a, b in frames.values():
        assert a[8:16] != b[8:16] and a[16:] == b[16:] and a[:8] != b[:8]   # tstamp and seq move, the payload does not


def test_p5_the_dbcs_units_are_the_vss_units_and_the_bridge_converts_nothing():
    assert tuple(C.SLOT_DBC_UNITS) == tuple(C.SLOT_UNITS)
    text = (REPO / "sdv" / "vss" / "slice.dbc").read_text(encoding="utf-8")
    for sig, unit in zip(C.SLOT_DBC_SIGNALS, C.SLOT_UNITS):
        m = re.search(r"^\s*SG_\s+%s\s*:[^\"]*\"([^\"]*)\"" % re.escape(sig), text, re.M)
        assert m is not None and (m.group(1) or None) == unit, sig
    values = {"v": 13.9, "a_x": -0.123, "delta": 17.3, "psi_dot": -41.7, "gear": -2}
    f = core().tick(snap(**values), 10**12, 1).frame
    assert struct.unpack_from("<4I", f, H + 25) == tuple(vf.f32_bits(values[n]) for n in NAMES[:4])
    assert struct.unpack_from("<b", f, H + 43)[0] == -2


# ============================================================ P6: injection

def test_p6_injection_against_the_native_vss_monitor(live):
    b, mon, _src = live()
    wait_until(lambda: len(accepted_after(b, 0)) >= 3, what="three ACCEPTs")
    for mode, reason, frames in (("nan", 9, 1), ("reserved", 10, 1), ("digest", 21, 3), ("profile0", 8, 1)):
        before = last_seq(b)
        b.inject(mode, frames)
        wait_until(lambda m=mode, f=frames: sum(1 for r in replies(b) if r["inject"] == m) == f, what="%s replies" % mode)
        got = [(r["verdict"], r["reason"]) for r in replies(b) if r["inject"] == mode]
        assert got == [(1, reason)] * frames, (mode, got)
        last_injected = max(r["seq"] for r in replies(b) if r["inject"] == mode)
        assert last_injected > before
        # keep sending (reason 21 included: owner, 2026-10-01): the next honest frames are judged and accepted
        wait_until(lambda s=last_injected: len(accepted_after(b, s)) >= 2, what="ACCEPTs after %s" % mode)
    s = ended(b)
    n = s["counters"]
    assert n["injected"] == 6 and n["r21"] == n["r21_injected"] == 3 and s["r21_uninjected"] == 0
    assert len(b.log.find("catalog-mismatch")) == 1, "the first 21 is logged once; every one is counted"
    assert s["rejected_by_origin"] == {"injected": 6}
    assert mon.count("LIVENESS MISS") == 0, mon.text()


def test_p6_injection_and_the_pauses_are_refused_when_the_target_is_7161(lock):
    b = vb.Bridge(cfg(7161, lock_path=lock), vb.QueueSource(), contract=C)
    for call in (lambda: b.inject("nan"), lambda: b.inject("digest", None), lambda: b.inject("reserved"), lambda: b.inject("profile0"),
                 b.pause_tick, b.pause_intake):
        with pytest.raises(vb.BridgeError, match="7161"):
            call()
    assert b.core._inject is None and not b._tick_paused.is_set() and not b.intake.paused.is_set()
    assert len(b.log.find("injection-refused")) == 6
    ended(b)


def test_p6_the_stamp_port_cannot_be_unmarked_and_a_port_marked_stamp_refuses_too(lock):
    """The refusal keys on the port: stamp=False cannot open :7161 to injection (it is refused at start)."""
    with pytest.raises(vb.BridgeError, match="stamp=False with the stamp port :7161"):
        vb.Bridge(cfg(7161, lock_path=lock, stamp=False), vb.QueueSource(), contract=C)
    assert cfg(7161, stamp=False).is_stamp() is True and cfg(7160, stamp=None).is_stamp() is False
    b = vb.Bridge(cfg(free_port(), lock_path=lock, stamp=True), vb.QueueSource(), contract=C)
    for call in (lambda: b.inject("digest"), b.pause_tick, b.pause_intake):
        with pytest.raises(vb.BridgeError, match="stamp port"):
            call()
    assert b.core._inject is None and not b._tick_paused.is_set() and not b.intake.paused.is_set()
    ended(b)


def test_p6_the_refusal_keys_on_the_port_even_past_the_config(lock):
    """White-box: a bridge whose stamp flag is somehow off still refuses on :7161."""
    b = vb.Bridge(cfg(7161, lock_path=lock), vb.QueueSource(), contract=C)
    b.stamp = False
    with pytest.raises(vb.BridgeError, match="7161"):
        b.inject("nan")
    assert b.core._inject is None
    ended(b)


def test_an_unknown_injection_is_refused(lock):
    b = vb.Bridge(cfg(free_port(), lock_path=lock), vb.QueueSource(), contract=C)
    with pytest.raises(vb.BridgeError, match="not one of"):
        b.inject("inf")
    ended(b)


# ============================================================ P7: the connection

EXPECTED_BACKOFF_MS = [min(100 * 2 ** i, 2000) for i in range(8)]       # spec 15: one tick, doubling, capped at 2 s


def test_p7_the_backoff_starts_at_one_tick_doubles_and_caps_at_2_s():
    bo = vb.Backoff()
    assert [bo.next_ns() // MS for _ in range(8)] == EXPECTED_BACKOFF_MS
    bo.reset()
    assert bo.next_ns() // MS == 100


def test_p7_a_late_connect_backs_off_then_connects(vss_monitor, lock):
    port = free_port()
    src = LiveSource().start()
    b = vb.Bridge(cfg(port, lock_path=lock), src, contract=C).start()
    wait_until(lambda: b.counters()["connect_failures"] >= 3, what="three failed connects")
    assert vb.updater_check(lock), "no lock during the backoff"
    mon = SvcMonitor(vss_monitor, port)
    try:
        wait_until(lambda: len(accepted_after(b, 0)) >= 3, timeout=6, what="ACCEPTs after the late start")
        s = ended(b)
    finally:
        mon.stop()
    n = s["counters"]
    fails = [e["backoff_ms"] for e in b.log.find("connect-failed")]
    assert fails == EXPECTED_BACKOFF_MS[:len(fails)] and len(fails) == n["connect_failures"] >= 3
    assert n["connects"] == 1 and n["reconnects"] == 0
    assert n["drop"] >= 2 and n["lost_on_reconnect"] == 0, "frames packed with no connection replace each other"
    assert n["peer_checks"] >= n["sends"] == n["replied"]


def test_p7_a_stall_mid_stream_closes_and_the_next_frame_reconnects(live, lock):
    b, mon, _src = live()
    wait_until(lambda: len(accepted_after(b, 0)) >= 3, what="ACCEPTs")
    b.pause_tick()
    wait_until(lambda: b.log.find("closed"), timeout=1.5, what="the bridge seeing the monitor close the idle connection")
    assert b.log.find("closed")[0]["outstanding"] is None and b.counters()["lost_on_reconnect"] == 0
    mon.wait_for("client closed: no complete frame for 500 ms")
    assert vb.updater_check(lock) and not b.connected
    resumed = last_seq(b)
    b.resume_tick()
    wait_until(lambda: len(accepted_after(b, resumed)) >= 2, what="ACCEPTs after the reconnect")
    s = ended(b)
    n = s["counters"]
    assert n["reconnects"] == 1 and n["lost_on_reconnect"] == 0 and n["drop"] == paused_drops(b) <= 1, n
    assert accepted_after(b, resumed)[0]["seq"] == resumed + 1, "the first frame after the stall is answered, not lost"


def test_p7_a_restarted_monitor_is_reconnected(live):
    b, mon, _src = live()
    wait_until(lambda: len(accepted_after(b, 0)) >= 3, what="ACCEPTs")
    mon.stop()
    wait_until(lambda: b.counters()["connect_failures"] >= 2, what="failed connects while the monitor is down")
    mon.start()
    before = last_seq(b)
    wait_until(lambda: len(accepted_after(b, before)) >= 2, timeout=6, what="ACCEPTs after the restart")
    s = ended(b)
    n = s["counters"]
    assert n["reconnects"] == 1 and n["lost_on_reconnect"] <= 1
    assert n["peer_checks"] >= n["sends"]


def test_p7_a_frame_in_flight_when_the_monitor_dies_is_lost_on_reconnect(live):
    b, mon, _src = live()
    wait_until(lambda: len(accepted_after(b, 0)) >= 3, what="ACCEPTs")
    mon.signal(signal.SIGSTOP)
    time.sleep(0.12)                                   # one tick: whatever is outstanding now was sent to a stopped monitor
    wait_until(lambda: b._out is not None, what="a frame in flight")
    in_flight = b._out.seq
    time.sleep(0.1)
    assert b.counters()["lost_on_reconnect"] == 0 and b._out is not None and b._out.seq == in_flight
    mon.kill()
    wait_until(lambda: b.counters()["lost_on_reconnect"] == 1, timeout=1, what="the frame counted lost when the connection dies")
    lost = b.log.find("lost")
    assert [e["seq"] for e in lost] == [in_flight] and lost[0]["why"] != "reply-timeout"
    mon.start()
    before = last_seq(b)
    wait_until(lambda: len(accepted_after(b, before)) >= 2, timeout=6, what="ACCEPTs after the restart")
    s = ended(b)
    n = s["counters"]
    assert n["reply_timeouts"] == 0 and n["lost_on_reconnect"] == 1 and n["reconnects"] == 1


def test_p7_a_peer_that_never_replies_is_closed_after_the_reply_timeout(live, lock):
    """Design decision b: a stopped monitor keeps the connection open and never replies. At the reply timeout the bridge
    closes the connection itself -- its 'closed' record names the frame it gave up on, and the lock is released at that
    close (the observer, called at the moment of each connect and close, reads the updater's check) -- and the next frame
    reconnects lazily: the kernel completes the handshake into the stopped monitor's accept queue, and the lock is taken
    again. Once the monitor runs again it sees each connection the bridge gave up end ('client done'), and the bridge's
    current connection is answered: no late reply to a frame given up reaches it (no stray or invalid reply)."""
    seen = []
    b, mon, _src = live(observer=lambda what: seen.append((what, vb.updater_check(lock))))
    wait_until(lambda: len(accepted_after(b, 0)) >= 3, what="ACCEPTs")
    assert seen == [("connected", False)], seen
    n0 = len(mon.lines)
    mon.signal(signal.SIGSTOP)
    wait_until(lambda: b.log.find("reply-timeout"), timeout=0.5 + 0.1 + SLACK, what="the reply timeout")
    first = b.log.find("reply-timeout")[0]
    assert 500 <= first["waited_ms"] < 500 + SLACK * 1000, first
    wait_until(lambda: b.log.find("lost"), timeout=SLACK, what="the lost record of the frame given up")
    lost = b.log.find("lost")[0]
    assert lost["seq"] == first["seq"] and lost["why"] == "reply-timeout"
    wait_until(lambda: b.log.find("closed"), timeout=SLACK, what="the bridge's close at the reply timeout")
    closed = b.log.find("closed")[0]
    assert (closed["why"], closed["outstanding"]) == ("reply-timeout", first["seq"]), closed
    assert seen[1] == ("closed", True), "the lock is released at the close: %s" % seen
    wait_until(lambda: len(b.log.find("connect")) >= 2, timeout=1.0, what="the lazy reconnect into the stopped monitor's queue")
    assert seen[2] == ("connected", False), "the lock is taken again at the reconnect: %s" % seen
    assert b.log.find("connect")[1]["t_mono"] > closed["t_mono"]
    assert b.counters()["lost_on_reconnect"] >= 1
    time.sleep(0.6)                                    # a second reply timeout and reconnect, into the stopped monitor's queue
    stopped_seq = last_seq(b)
    mon.signal(signal.SIGCONT)
    wait_until(lambda: len(accepted_after(b, stopped_seq)) >= 2, timeout=6, what="ACCEPTs once the monitor runs again")
    mon.wait_for("monitor: client done:", after=n0)   # the connection given up at the timeout ended on the monitor's side
    s = ended(b)
    n = s["counters"]
    assert n["reply_timeouts"] >= 1 and n["lost_on_reconnect"] >= n["reply_timeouts"]
    assert sum(1 for e in b.log.find("lost") if e["why"] == "reply-timeout") == n["reply_timeouts"]
    assert [e["why"] for e in b.log.find("closed")][:n["reply_timeouts"]] == ["reply-timeout"] * n["reply_timeouts"]
    assert n["reconnects"] >= n["reply_timeouts"] and n["reply_invalid"] == 0 and n["stray_bytes"] == 0, n
    assert [w for w, _free in seen] == ["connected", "closed"] * (len(seen) // 2) + ["connected"] * (len(seen) % 2), seen
    assert all(free is (w == "closed") for w, free in seen), seen


def test_p7_at_the_reply_timeout_the_peer_sees_the_bridge_close_and_a_new_connection(lock):
    """Design decision b from the peer's side: a peer that never answers on its first connection (it answers on every
    later one) receives one frame there and then sees the bridge close it (EOF) 500 ms after that frame -- not a second
    frame on the same connection -- and accepts a new connection, on which the next frame is answered. The bridge's
    view matches: one reply timeout, its frame lost, the close naming it, the lock released at the close and taken
    again at the reconnect."""
    seen = []
    box = {}

    def silent_on_the_first_connection(f):
        return None if box["fake"].conns[-1]["n"] == 1 else f

    fake = box["fake"] = FakeMonitor(silent_on_the_first_connection)
    try:
        b = vb.Bridge(cfg(fake.port, lock_path=lock), LiveSource().start(), contract=C,
                      observer=lambda what: seen.append((what, vb.updater_check(lock)))).start()
        wait_until(lambda: len(fake.conns) >= 2 and len(fake.conns[1]["frames"]) >= 2, timeout=3,
                   what="two frames on a second connection")
        wait_until(lambda: len(accepted_after(b, 0)) >= 2, what="ACCEPTs on the new connection")
        s = ended(b)
    finally:
        fake.close()
    first, second = fake.conns[0], fake.conns[1]
    assert len(first["frames"]) == 1 and first["end"] == "eof", first
    t_frame, frame = first["frames"][0]
    assert 0.5 - 0.05 <= first["ended"] - t_frame < 0.5 + SLACK, (first["ended"] - t_frame)
    assert second["accepted"] >= first["ended"] - 0.05
    gave_up = _seq_of(frame)
    assert [e["seq"] for e in b.log.find("reply-timeout")] == [gave_up]
    assert [(e["seq"], e["why"]) for e in b.log.find("lost")] == [(gave_up, "reply-timeout")]
    assert [(e["why"], e["outstanding"]) for e in b.log.find("closed")][0] == ("reply-timeout", gave_up)
    assert seen[:3] == [("connected", False), ("closed", True), ("connected", False)], seen
    n = s["counters"]
    assert n["reply_timeouts"] == 1 and n["lost_on_reconnect"] == 1 and n["connects"] == 2 and n["reconnects"] == 1, n
    assert n["reply_invalid"] == 0 and n["stray_bytes"] == 0
    assert all(_seq_of(f) > gave_up for _t, f in second["frames"])


def test_p7_the_peer_closed_check_runs_before_every_send(lock):
    """Spec 14.3 item 3, white-box: a connection the peer has closed, with no select in between to see it, is
    found by the check before the send, so the frame goes to a new connection instead of being lost."""
    fake = FakeMonitor(accept_all)
    try:
        b = vb.Bridge(cfg(fake.port, lock_path=lock), vb.QueueSource(), contract=C)     # never started: driven by hand
        dead, peer = socket.socketpair()
        dead.setblocking(False)
        peer.close()
        assert b.lock.acquire()
        b._sock, b._state = dead, vb.CONNECTED
        b.core.tick(honest_snap(), 10**12, time.monotonic_ns())
        b._try_send(time.monotonic_ns())
        assert [e["why"] for e in b.log.find("closed")] == ["peer-closed (seen before a send)"]
        end = time.monotonic() + 2                        # the reconnect, which may complete asynchronously
        while b.counters()["sends"] == 0 and time.monotonic() < end:
            b._wait(0.05)
            b._try_send(time.monotonic_ns())
        n = b.counters()
        assert n["sends"] == 1 and n["peer_checks"] == 2 and n["lost_on_reconnect"] == 0 and n["connects"] == 1
        assert [e["why"] for e in b.log.find("closed")] == ["peer-closed (seen before a send)"]
        wait_until(lambda: len(fake.frames) == 1, what="the frame on the new connection")
        assert b._out is not None and fake.frames[0] == b._out.frame
        end = time.monotonic() + 2
        while b._out is not None and time.monotonic() < end:
            b._wait(0.05)
        b._close("test end")
        s = ended(b)
        assert s["counters"]["replied"] == 1 and vb.updater_check(lock)
    finally:
        fake.close()


def _connected_by_hand(b):
    """A bridge that is never started, connected by hand (the claim thread's own calls)."""
    b._connect(time.monotonic_ns())
    end = time.monotonic() + 2
    while b._state != vb.CONNECTED and time.monotonic() < end:
        b._wait(0.05)
    assert b._state == vb.CONNECTED


INVALID_REPLIES = {
    "a payload byte": lambda b: b.__setitem__(H + vf.P_V, b[H + vf.P_V] ^ 0x01),
    "another seq": lambda b: b.__setitem__(0, b[0] ^ 0x01),
    "a stamp in svc mode": lambda b: b.__setitem__(H + vf.P_T_IN, 0x5A),
    "ACCEPT with a reason": lambda b: (b.__setitem__(H + vf.P_VERDICT, rules.V_ACCEPT), b.__setitem__(H + vf.P_REASON, rules.RSN_VSS_YAW)),
    "REJECT with reason 0": lambda b: (b.__setitem__(H + vf.P_VERDICT, rules.V_REJECT), b.__setitem__(H + vf.P_REASON, rules.RSN_OK)),
    "an unknown verdict": lambda b: b.__setitem__(H + vf.P_VERDICT, 2),
}


@pytest.mark.parametrize("change", list(INVALID_REPLIES))
def test_an_invalid_reply_is_counted_its_frame_lost_and_the_connection_closed(lock, change):
    """A reply differs from its request in p[6] and p[7] only (and in stamp mode also p[8..23]), and its verdict and
    reason agree (ACCEPT with 0, REJECT with a reason). The first reply here breaks that: it counts reply_invalid, its
    frame is lost_on_reconnect ('invalid reply'), and the bridge closes the connection -- the peer sees EOF -- and sends
    the next frame on a new one, where it is answered. Nothing invalid reaches the reply log."""
    box = {"bad": None}

    def policy(f):
        if box["bad"] is None:
            box["bad"] = _seq_of(f)
            b = bytearray(f)
            INVALID_REPLIES[change](b)
            return bytes(b)
        return f

    fake = FakeMonitor(policy)
    try:
        b = vb.Bridge(cfg(fake.port, lock_path=lock), LiveSource().start(), contract=C).start()
        wait_until(lambda: len(accepted_after(b, 0)) >= 2, timeout=3, what="ACCEPTs after the invalid reply")
        s = ended(b)
    finally:
        fake.close()
    bad = box["bad"]
    n = s["counters"]
    assert n["reply_invalid"] == 1 and n["lost_on_reconnect"] == 1 and n["reconnects"] == 1, n
    inv = b.log.find("reply-invalid")
    assert [e["seq"] for e in inv] == [bad], inv
    assert [(e["seq"], e["why"]) for e in b.log.find("lost")] == [(bad, "invalid reply")]
    assert b.log.find("closed")[0]["why"] == "invalid reply"
    assert fake.conns[0]["end"] == "eof" and len(fake.conns[0]["frames"]) == 1, fake.conns[0]
    assert bad not in [r["seq"] for r in replies(b)] and all(r["verdict"] in (0, 1) for r in replies(b))


def test_a_second_answer_to_one_frame_is_stray_and_closes_the_connection(lock):
    """White-box: a peer that answers one frame twice. The first answer is the reply; the second arrives with nothing
    outstanding, so its bytes are counted (stray_bytes) and the bridge closes the connection rather than take them for
    the next frame's reply. The lock goes with the connection; nothing is lost."""
    fake = FakeMonitor(lambda f: f + f)
    try:
        b = vb.Bridge(cfg(fake.port, lock_path=lock), vb.QueueSource(), contract=C)     # never started: driven by hand
        _connected_by_hand(b)
        b.core.tick(honest_snap(), 10**12, time.monotonic_ns())
        b._try_send(time.monotonic_ns())
        end = time.monotonic() + 2
        while b._state == vb.CONNECTED and time.monotonic() < end:
            b._wait(0.05)
        assert b.core.replied_seqs == [1] and b._state == vb.DISCONNECTED and vb.updater_check(lock)
        assert b.counters()["stray_bytes"] == 64 and [e["n"] for e in b.log.find("stray-bytes")] == [64]
        assert [(e["why"], e["outstanding"]) for e in b.log.find("closed")] == [("stray bytes with nothing outstanding", None)]
        wait_until(lambda: fake.conns and fake.conns[0]["end"], what="the peer's view of the close")
        assert fake.conns[0]["end"] in ("eof", "reset"), fake.conns[0]
        s = ended(b)
    finally:
        fake.close()
    assert s["counters"]["lost_on_reconnect"] == 0 and s["counters"]["reply_invalid"] == 0


class StampMonitor(SvcMonitor):
    """The native vss monitor in stamp mode (`monitor PORT stamp`, the mode :7161 runs): every reply carries t_in and
    t_out in p[8..23]."""

    def start(self):
        n = len(self.lines)
        self.p = subprocess.Popen([self.binary, str(self.port), "stamp"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        threading.Thread(target=self._read, args=(self.p,), daemon=True).start()
        self.wait_for("monitor: stamping replies on :", after=n)


@pytest.mark.parametrize("marked", [True, False], ids=["marked-stamp", "unmarked"])
def test_a_stamp_exchange_against_the_native_stamp_monitor(vss_monitor, lock, marked):
    """A target marked stamp (Config.stamp; :7161 always is) allows the reply's p[8..23] to differ from the request and
    logs t_in_ns and t_out_ns with every reply; the same monitor's replies to an unmarked target differ in bytes the
    request fixed, so each is invalid and closes the connection. Functional only: the stamps are logged, never read
    as a time here."""
    port = free_port()
    mon = StampMonitor(vss_monitor, port)
    try:
        b = vb.Bridge(cfg(port, lock_path=lock, stamp=marked), LiveSource().start(), contract=C).start()
        if marked:
            wait_until(lambda: len(replies(b)) >= 3, what="stamped replies")
        else:
            wait_until(lambda: b.counters()["reply_invalid"] >= 2, what="invalid replies")
        s = ended(b)
    finally:
        mon.stop()
    n = s["counters"]
    assert s["run_items"]["target"]["stamp"] is marked
    if marked:
        rs_ = replies(b)
        assert n["reply_invalid"] == 0 and n["accepted"] == n["replied"] >= 3, n
        assert all(isinstance(r["t_in_ns"], int) and isinstance(r["t_out_ns"], int) and 0 < r["t_in_ns"] <= r["t_out_ns"]
                   for r in rs_), rs_[:3]
        with pytest.raises(vb.BridgeError, match="stamp port"):
            b.inject("nan")
    else:
        assert n["replied"] == 0 and n["lost_on_reconnect"] == n["reply_invalid"] >= 2, n
        for e in b.log.find("reply-invalid"):
            m = re.match(r"bytes \[([\d, ]+)\] differ from the request", e["why"])
            assert m and all(H + vf.STAMP_SPAN[0] <= int(i) < H + vf.STAMP_SPAN[1] for i in m.group(1).split(",")), e


def delayed(seconds):
    """A FakeMonitor policy: every frame answered as sent (ACCEPT), seconds late."""
    def policy(f):
        time.sleep(seconds)
        return f
    return policy


def test_p7_a_stop_drains_the_outstanding_and_the_queued_frame(lock):
    """At a stop (module docstring, ACCOUNTING): against a peer that answers 250 ms late, a frame is outstanding
    and one queued at almost every instant; the outstanding one gets its reply, the queued one is sent and
    answered, nothing is lost and nothing is dropped by the stop."""
    fake = FakeMonitor(delayed(0.25))
    try:
        b = vb.Bridge(cfg(fake.port, lock_path=lock), LiveSource().start(), contract=C).start()
        wait_until(lambda: len(replies(b)) >= 2, what="two replies")
        wait_until(lambda: b._out is not None and b.core.queued is not None, what="a frame outstanding and one queued")
        t0 = time.monotonic()
        s = ended(b)
        took = time.monotonic() - t0
    finally:
        fake.close()
    n = s["counters"]
    assert n["lost_on_reconnect"] == 0 and not b.log.find("lost"), b.log.find("lost")
    assert not [e for e in b.log.find("dropped") if e["why"] == "stop"], b.log.find("dropped")
    assert max(b.core.replied_seqs) == n["packed"], "the frame queued at the stop was sent and answered"
    assert took < vb.DRAIN_NS / 1e9 + SLACK, took


def test_p7_a_drain_that_meets_a_queued_frame_and_nothing_outstanding_sends_it_at_once(lock):
    """White-box: the state a stop meets when its wake and a reply arrive in one select (nothing outstanding, a
    frame queued, the connection open). The drain sends the frame at once and waits for its reply, rather than
    idling out its bound first and leaving the frame unanswered."""
    fake = FakeMonitor(delayed(0.1))
    try:
        b = vb.Bridge(cfg(fake.port, lock_path=lock), vb.QueueSource(), contract=C)     # never started: driven by hand
        b._connect(time.monotonic_ns())
        end = time.monotonic() + 2
        while b._state != vb.CONNECTED and time.monotonic() < end:
            b._wait(0.05)
        assert b._state == vb.CONNECTED and b._out is None and not vb.updater_check(lock)
        b.core.tick(honest_snap(), 10**12, time.monotonic_ns())
        t0 = time.monotonic()
        b._drain()
        took = time.monotonic() - t0
        assert b._out is None and b.core.queued is None and b.core.replied_seqs == [1], (b._out, b.core.n)
        assert took < 0.1 + SLACK, took
        b._close("test end")
        s = ended(b)
    finally:
        fake.close()
    assert s["counters"]["lost_on_reconnect"] == 0 and len(fake.frames) == 1


# ============================================================ P8: the pause sequences

def test_p8_tick_paused_gives_miss_close_reconnect_accept_restored(live):
    b, mon, _src = live()
    wait_until(lambda: len(accepted_after(b, 0)) >= 5, what="ACCEPTs")
    n0 = len(mon.lines)
    b.pause_tick()
    time.sleep(1.5)                                                         # the pause test's design value (spec 15)
    assert mon.count("LIVENESS MISS", after=n0) == 1, mon.text()
    console = [line for _t, line in mon.lines[n0:]]
    i_miss = next(i for i, line in enumerate(console) if "LIVENESS MISS" in line)
    i_close = next(i for i, line in enumerate(console) if "client closed: no complete frame for 500 ms" in line)
    assert i_miss < i_close
    assert b.log.find("closed") and b.log.find("closed")[-1]["outstanding"] is None
    resumed = last_seq(b)
    b.resume_tick()
    wait_until(lambda: accepted_after(b, resumed), what="the first ACCEPT after the resume")
    first = [r for r in replies(b) if r["seq"] > resumed][0]
    assert first["seq"] == resumed + 1 and (first["verdict"], first["reason"]) == (0, 0)
    _t, line = mon.wait_for("LIVENESS RESTORED", after=n0)
    assert line.startswith("monitor: LIVENESS RESTORED: seq=%d after " % first["seq"]), line
    s = ended(b)
    n = s["counters"]
    assert n["reconnects"] == 1 and n["lost_on_reconnect"] == 0 and n["drop"] == paused_drops(b) <= 1, n
    assert n["peer_checks"] == n["sends"]


def test_p8_both_paused_tick_resumed_first_gives_22_then_restored(live):
    b, mon, _src = live()
    wait_until(lambda: len(accepted_after(b, 0)) >= 5, what="ACCEPTs")
    n0 = len(mon.lines)
    b.pause_intake()
    b.pause_tick()
    time.sleep(1.5)
    resumed = last_seq(b)
    b.resume_tick()
    wait_until(lambda: [r for r in replies(b) if r["seq"] > resumed], what="the first reply after the resume")
    time.sleep(0.35)
    b.resume_intake()
    wait_until(lambda: accepted_after(b, resumed), what="ACCEPT once the intake runs again")
    after = [r for r in replies(b) if r["seq"] > resumed]
    first = after[0]
    assert first["seq"] == resumed + 1 and (first["verdict"], first["reason"]) == (1, 22), first
    assert first["age_ms"] > C.AGE_MAX_MS
    assert first["seq"] in [e["seq"] for e in b.log.find("age-over-max")]
    _t, line = mon.wait_for("LIVENESS RESTORED", after=n0)
    assert line.startswith("monitor: LIVENESS RESTORED: seq=%d after " % first["seq"]), "a 22 is life: " + line
    assert mon.count("LIVENESS MISS", after=n0) == 1
    s = ended(b)
    assert s["intake"]["discarded"] > 0, "a paused intake keeps draining the stream"


def _seq_of(frame):
    return struct.unpack_from("<Q", frame, 0)[0]


@pytest.mark.parametrize("order", ["tick", "reply", "stop"])
def test_p8_the_frame_queued_when_the_tick_pauses_is_dropped_not_sent_inside_the_pause(lock, order):
    """White-box (module docstring of the bridge, HELD VALUES AND THE TICK): a frame outstanding and one queued when
    the tick pauses, as against a peer that answers late; then the claim thread's next pass, in each order it can come:
    a paused tick before the outstanding frame's reply ("tick"), that reply before any paused tick ("reply": unfixed,
    it released the queued frame at once, inside the pause), or a stop's drain ("stop": unfixed, the drain sent it).
    Every send checks the pause first, so in each order the queued frame is dropped ('paused') and never sent: a frame
    packed before a pause never goes out inside it carrying the age it had at packing."""
    fake = FakeMonitor(accept_all)
    try:
        b = vb.Bridge(cfg(fake.port, lock_path=lock), vb.QueueSource(), contract=C)     # never started: driven by hand
        b._connect(time.monotonic_ns())
        end = time.monotonic() + 2
        while b._state != vb.CONNECTED and time.monotonic() < end:
            b._wait(0.05)
        assert b._state == vb.CONNECTED
        b.core.tick(honest_snap(), 10**12, time.monotonic_ns())
        b._try_send(time.monotonic_ns())
        assert b._out is not None and b._out.seq == 1
        b.core.tick(honest_snap(), 10**12 + vb.TICK_NS, time.monotonic_ns())       # queued behind the outstanding one
        assert b.core.queued is not None and b.core.queued.seq == 2
        b.pause_tick()
        if order == "tick":
            b._tick(time.monotonic_ns())                                         # a paused tick's pass, as _loop makes it
            b._try_send(time.monotonic_ns())
            assert b.core.queued is None and b._out is not None and b._out.seq == 1
        if order in ("tick", "reply"):
            end = time.monotonic() + 2
            while b._out is not None and time.monotonic() < end:                 # seq 1's reply
                b._wait(0.05)
            b._try_send(time.monotonic_ns())                                     # the pass the reply woke, as _loop makes it
        else:
            b._drain()
        time.sleep(0.2)
        assert b.core.replied_seqs == [1]
        assert [_seq_of(f) for f in fake.frames] == [1] and b._out is None, "seq 2, packed before the pause, was sent inside it"
        assert [(e["seq"], e["why"]) for e in b.log.find("dropped")] == [(2, "paused")]
        assert b.counters()["ticks_paused"] == (1 if order == "tick" else 0)
        b._close("test end")
        s = ended(b)
    finally:
        fake.close()
    assert s["counters"]["drop"] == 1 and s["counters"]["sends"] == 1


def test_p8_a_reply_that_comes_before_the_first_paused_tick_releases_nothing(lock):
    """The threaded bridge against a peer that holds one frame's reply until released: that frame outstanding and the
    next queued behind it, the tick paused just after the tick that queued it, and the reply released at once, about a
    tick before the first paused tick. The claim thread's pass on that reply drops the queued frame ('paused'), and
    nothing more reaches the peer while the tick stays paused (unfixed, the reply released the queued frame straight
    away, inside the pause). On resume the next seq is packed fresh and sent."""
    gate = threading.Event()
    held = {"seq": None}

    def policy(f):
        if _seq_of(f) == held["seq"]:
            gate.wait(0.45)                                  # under the 500 ms reply timeout: the bridge never gives up on it
        return f

    fake = FakeMonitor(policy)
    b = None
    try:
        b = vb.Bridge(cfg(fake.port, lock_path=lock), LiveSource().start(), contract=C).start()
        wait_until(lambda: len(accepted_after(b, 0)) >= 3, what="ACCEPTs")
        held["seq"] = target = last_seq(b) + 2
        end = time.monotonic() + 2
        while time.monotonic() < end:                        # a tight poll: pause within about 1 ms of the queuing tick
            out, q = b._out, b.core.queued
            if out is not None and out.seq == target and q is not None:
                break
            time.sleep(0.0005)
        else:
            raise AssertionError("no frame queued behind the held seq %d: %s" % (target, b.counters()))
        b.pause_tick()
        packed = last_seq(b)                                 # nothing is packed while the tick is paused
        gate.set()
        wait_until(lambda: target in b.core.replied_seqs, what="the held frame's reply")
        time.sleep(0.3)
        late = [_seq_of(f) for f in fake.frames if _seq_of(f) > target]
        assert not late, "frames packed before the pause were sent inside it: %s" % late
        assert [(e["seq"], e["why"]) for e in b.log.find("dropped") if e["why"] == "paused"] == [(packed, "paused")]
        assert last_seq(b) == packed
        b.resume_tick()
        wait_until(lambda: accepted_after(b, packed), what="the first ACCEPT after the resume")
        first = [r for r in replies(b) if r["seq"] > packed][0]
        assert first["seq"] == packed + 1 and (first["verdict"], first["reason"]) == (0, 0), first
        ended(b)
    finally:
        gate.set()
        if b is not None:
            b.stop()
        fake.close()


def test_p8_a_frame_queued_in_the_backoff_when_the_tick_pauses_is_not_sent_once_the_monitor_returns(live):
    """The review's S11 schedule against the native monitor: the monitor stopped, the bridge in its backoff with a
    frame queued, the tick paused, the monitor restarted 2.5 s later. The frame queued at the pause is dropped at the
    claim thread's first pass after it (a paused tick or the backoff's end: 'paused'), so nothing reconnects and
    nothing is sent while the tick stays paused (unfixed, it went out once the backoff allowed, seconds after its
    packing with the age it had then, and was ACCEPTed); on resume the first frame is the next seq, packed fresh."""
    b, mon, _src = live()
    wait_until(lambda: len(accepted_after(b, 0)) >= 3, what="ACCEPTs")
    mon.stop()
    wait_until(lambda: b.counters()["connect_failures"] >= 2, what="failed connects while the monitor is down")
    b.pause_tick()
    time.sleep(vb.TICK_NS / 1e9 + 0.15)                                       # past the first paused tick
    queued = last_seq(b)                                                       # nothing is packed while paused
    connects = b.counters()["connects"]
    time.sleep(2.5 - (vb.TICK_NS / 1e9 + 0.15))
    n0 = len(mon.lines)
    mon.start()
    time.sleep(vb.BACKOFF_CAP_NS / 1e9 + SLACK)                               # the longest the backoff holds a frame back
    late = [r for r in replies(b) if r["seq"] >= queued]
    assert not late, "a frame packed before the pause was sent inside it: %s" % late
    assert [(e["seq"], e["why"]) for e in b.log.find("dropped") if e["seq"] == queued] == [(queued, "paused")]
    assert b.counters()["connects"] == connects and mon.count("client done", after=n0) == 0, mon.text()
    b.resume_tick()
    wait_until(lambda: accepted_after(b, queued), timeout=3, what="the first ACCEPT after the resume")
    first = [r for r in replies(b) if r["seq"] > queued][0]
    assert first["seq"] == queued + 1 and (first["verdict"], first["reason"]) == (0, 0), first
    assert first["age_ms"] <= C.AGE_MAX_MS, first
    s = ended(b)
    assert s["counters"]["ticks_paused"] >= 20


# ============================================================ P10: rule 26's skip counters

def test_p10_rule_26_skip_counters_use_the_generated_table():
    c = core()
    p = c.tables.profiles[nominal()]
    wild = 100.0
    outside = (vf.f32_next_down(p.v26_lo), vf.f32_next_up(p.v26_hi), -vf.f32_next_up(p.v26_hi))
    inside = (p.v26_lo, p.v26_hi, -p.v26_hi)
    for v in outside + inside:
        c.tick(honest_snap(v=v, psi_dot=wild, gear=1 if v > 0 else -1), 10**12, 1)
    assert c.n["r26_skip_window"] == len(outside) and c.n["r26_skip_ay"] == 0
    c.tick(snap(v=vf.f32_next_up(p.v26_hi), delta=0.0, gear=1), 10**12, 1)          # no yaw: rule 26 does not apply
    c.tick(snap(v=vf.f32_next_up(p.v26_hi), psi_dot=wild), 10**12, 1)              # no steering
    assert c.n["r26_skip_window"] == len(outside)
    corner = honest_snap(v=min(p.v26_hi, p.v_max), delta=p.delta_max, psi_dot=0.0)  # the largest a_y_kin: never skipped without a bound
    q = c.tick(corner, 10**12, 1)
    assert p.ay26_max == 0.0 and c.n["r26_skip_ay"] == 0 and q.a_y_kin is not None
    assert rules.judge_frame(q.frame, tsf.tables()) == tsf.reject(26)


def test_p10_the_a_y_bound_skips_as_the_reference_judge_does():
    aid = tsf.ay_bounded()
    c = core(cfg(profile_id=aid, extra_profile_ids=(aid,)))
    t = c.tables
    p = t.profiles[aid]
    assert p.ay26_max > 0
    wild = 250.0
    for v in (vf.f32(8.0), vf.f32(3.0), vf.f32(p.v26_hi)):
        judged, skipped = tsf._f32_side(lambda d, u=v: rules.kinematics(u, d, p.l_mm, t)[1] > p.ay26_max, 0.0, p.delta_max)
        before = c.n["r26_skip_ay"]
        qj = c.tick(honest_snap(v=v, delta=judged, psi_dot=wild), 10**12, 1)
        assert c.n["r26_skip_ay"] == before
        qs = c.tick(honest_snap(v=v, delta=skipped, psi_dot=wild), 10**12, 1)
        assert c.n["r26_skip_ay"] == before + 1
        assert qj.a_y_kin == rules.kinematics(v, judged, p.l_mm, t)[1] and qs.a_y_kin == rules.kinematics(v, skipped, p.l_mm, t)[1]
        assert rules.judge_frame(qj.frame, t) == tsf.reject(26) and rules.judge_frame(qs.frame, t) == tsf.ACCEPT


# ============================================================ P11: no gRPC

FORBIDDEN_TOP = ("grpc", "kuksa", "can", "cantools", "google")
CORE_FILES = (BRIDGE_DIR / "vss_claim_bridge.py", BRIDGE_DIR / "reasonsets.py", REPO / "sdv" / "frame" / "vssframe.py",
              REPO / "sdv" / "frame" / "rules.py")


def test_p11_the_core_and_the_frame_import_no_grpc():
    code = ("import sys; sys.dont_write_bytecode = True; sys.path[:0] = [%r]; import vss_claim_bridge, reasonsets; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] in %r))" % (str(BRIDGE_DIR), FORBIDDEN_TOP))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[]"


def test_p11_every_import_of_the_core_is_the_standard_library_or_sdv_frame():
    for path in CORE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                top = name.split(".")[0]
                assert top in sys.stdlib_module_names or top in ("vssframe", "rules", "__future__"), (path.name, name)


# ============================================================ P13: the event-to-reason sets

def _rec(seq, reason, t_ms):
    return {"seq": seq, "verdict": 1 if reason else 0, "reason": reason, "src_now_ns": t_ms * MS}


WINDOWS = [{"event": "speed", "t0_ns": 1000 * MS, "t1_ns": 2000 * MS}, {"event": "stall", "t0_ns": 3000 * MS, "t1_ns": 4000 * MS}]


def test_p13_identical_sets_pass_and_a_missing_or_extra_event_fails():
    run = [_rec(1, 0, 500), _rec(2, 23, 1100), _rec(3, 23, 1200), _rec(4, 0, 2500), _rec(5, 22, 3500)]
    got = rs.reason_set(run, WINDOWS)
    assert got == {("speed", 23), ("stall", 22)}
    other_mode = [_rec(9, 23, 1999), _rec(10, 22, 3000)]                    # other seqs and instants, the same events
    assert rs.compare(got, rs.reason_set(other_mode, WINDOWS)) == {"ok": True, "missing": [], "extra": []}
    missing = rs.compare(got, rs.reason_set(run[:4], WINDOWS))
    assert missing == {"ok": False, "missing": [("stall", 22)], "extra": []}
    extra = rs.compare(got, rs.reason_set(run + [_rec(6, 26, 2500)], WINDOWS))
    assert extra == {"ok": False, "missing": [], "extra": [(None, 26)]}
    wrong = rs.compare(got, rs.reason_set([_rec(2, 24, 1100), _rec(5, 22, 3500)], WINDOWS))
    assert not wrong["ok"] and wrong["missing"] == [("speed", 23)] and wrong["extra"] == [("speed", 24)]
    with pytest.raises(ValueError, match="overlap"):
        rs.reason_set(run, WINDOWS + [{"event": "x", "t0_ns": 1500 * MS, "t1_ns": 2500 * MS}])


def test_p13_a_replay_runs_windows_come_from_its_one_logged_anchor():
    """reasonsets.replay_anchor reads the one `replay-anchored` record of a run's bridge.jsonl (none, or two, is
    refused); shift_windows moves offsets on the recording onto that origin and keeps every other key. The end-to-end
    case, against the native monitor, is test_sdv_bridge_sources.py's P13 test."""
    anchored = {"event": rs.REPLAY_ANCHORED, "anchor_ns": 7 * 10**9}
    assert rs.replay_anchor([{"event": "start"}, anchored, {"event": "connect"}]) == 7 * 10**9
    for records in ([{"event": "start"}], [anchored, dict(anchored)]):
        with pytest.raises(ValueError, match="exactly once"):
            rs.replay_anchor(records)
    shifted = rs.shift_windows([dict(WINDOWS[0], reason=23)], 7 * 10**9)
    assert shifted == [{"event": "speed", "t0_ns": 7 * 10**9 + 1000 * MS, "t1_ns": 7 * 10**9 + 2000 * MS, "reason": 23}]
    assert WINDOWS[0]["t0_ns"] == 1000 * MS, "the input is not changed"


def test_p13_frame_by_frame_only_between_replay_runs():
    s = honest_snap()
    a, b = core(cfg(mode="replay")), core(cfg(mode="replay"))
    fa = [a.tick(s, 10**12, 1000 + i).frame for i in range(3)]
    fb = [b.tick(s, 10**12, 5000 + i).frame for i in range(3)]
    assert fa != fb
    assert rs.compare_frames({"mode": "replay", "frames": fa}, {"mode": "replay", "frames": fb}) == {"ok": True, "differ": [], "lengths": (3, 3)}
    fc = fb[:2] + [b.tick(honest_snap(v=6.0), 10**12, 1).frame]
    assert rs.compare_frames({"mode": "replay", "frames": fa}, {"mode": "replay", "frames": fc})["differ"] == [2]
    assert not rs.compare_frames({"mode": "replay", "frames": fa}, {"mode": "replay", "frames": fb[:2]})["ok"]
    for other in ("broker", "can"):
        with pytest.raises(ValueError, match="only between two replay runs"):
            rs.compare_frames({"mode": "replay", "frames": fa}, {"mode": other, "frames": fb})


# ============================================================ P15: the rule-26 spread

def spread_snap(spread_ns, t0=10**12, **kw):
    """The rule-26 triple's timestamps spread_ns apart (delta newest, v oldest, psi_dot between)."""
    s = dict(HONEST)
    s.update(kw)
    return snap(v=(s["v"], t0), a_x=(s["a_x"], t0), delta=(s["delta"], t0 + spread_ns), psi_dot=(s["psi_dot"], t0 + spread_ns // 2),
                gear=(s["gear"], t0))


def contract_with(**changes):
    ns = types.SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if k.isupper()})
    for k, v in changes.items():
        setattr(ns, k, v)
    return ns


def test_p15_the_accounting_edge_is_the_generated_threshold_at_the_timestamps_resolution():
    assert C.SPREAD_EXCEEDED_MS == 30, "spec 14.2: one SliceDynamics period plus half a period"
    c = core()
    cases = ((20 * MS, False), (30 * MS, False), (30 * MS + 500_000, True), (31 * MS, True), (30 * MS + 1, True))
    for spread, counted in cases:
        before = c.n["spread_exceeded"]
        p = c.tick(spread_snap(spread), 10**12 + 40 * MS, 1)
        assert p.spread_ns == spread and (c.n["spread_exceeded"] == before + 1) == counted, spread
    logged = [(e["seq"], e["spread_ns"]) for e in c.log.find("spread-exceeded")]
    assert logged == [(3, 30 * MS + 500_000), (4, 31 * MS), (5, 30 * MS + 1)]
    for missing in ("v", "delta", "psi_dot"):                                 # without all of b0, b2, b3: never counted
        s = {n: (HONEST[n], 10**12 + i * 90 * MS) for i, n in enumerate(NAMES) if n != missing}
        assert c.tick(snap(**s), 10**12 + 500 * MS, 1).spread_ns is None
    assert c.n["spread_exceeded"] == 3
    assert c.tick(honest_snap(), 10**12, 1).spread_ns == 0                   # one timestamp for the triple (can, replay): 0


def _attributed(c, spread_ms_x2, profile=None):
    p = c.tick(spread_snap(spread_ms_x2 * MS // 2), 10**12 + 60 * MS, 1)
    ok, rec = c.reply(p, answer(p, 1, 26))
    assert ok and rec["reason"] == 26 and rec["spread_ns"] == spread_ms_x2 * MS // 2
    return rec["attributed"], rec


def test_p15_attribution_against_the_profiles_generated_spread():
    assert C.ATTRIBUTION_SPREAD_MS[nominal()] == 31
    c = core()
    assert _attributed(c, 62)[0] is False and _attributed(c, 64)[0] is True              # 31 ms: no, 32 ms: yes
    aid = tsf.ay_bounded()                                                               # profile 3, compiled since Phase 7 WP2
    spread = C.ATTRIBUTION_SPREAD_MS[aid]
    assert spread == (C.RULE26_BUDGET[aid]["k_attr"] - 1) * C.CARLA_STEP_MS > 0         # spec 7.4: k_attr - 1 steps
    c3 = core(cfg(profile_id=aid, extra_profile_ids=(aid,)))
    assert _attributed(c3, 2 * spread)[0] is False and _attributed(c3, 2 * spread + 2)[0] is True   # spread: no, + 1 ms: yes
    # Profile 4 (Phase 8 WP3b, compiled): summed rows at the planning-sim envelope's own skew, not slice.dbc's period; its
    # spread is where they reach tol, a whole ms, so the bridge attributes from one ms past it, as for the nominal profile.
    pid4 = C.LIVE_DEFAULT_PROFILE["planning-sim"]
    b4 = C.RULE26_BUDGET[pid4]
    spread4 = C.ATTRIBUTION_SPREAD_MS[pid4]
    assert b4["skew_ms"] == C.ENVELOPES["planning-sim"]["skew_ms"] != C.DBC_PERIOD_MS[C.RULE26_DBC_MESSAGE]
    assert spread4 == math.ceil(b4["attribution_spread_exact_ms"]) > b4["skew_ms"] and spread4 != C.ATTRIBUTION_SPREAD_MS[nominal()]
    c4 = core(cfg(profile_id=pid4))
    assert _attributed(c4, 2 * spread4)[0] is False and _attributed(c4, 2 * spread4 + 2)[0] is True  # spread: no, + 1 ms: yes


@tsv.NEEDS_TOML
def test_p15_another_tol_moves_the_attribution_edge_and_a_counted_frame_stays_unattributed():
    doc = copy.deepcopy(tsv._profiles())
    tsv._p(doc, nominal()).update(tol26=4.0)
    d = tsv.gen.derive(doc, tsv._dbc(), tsv.SLOT_SIGNALS)
    assert d["attribution_spread_ms"][nominal()] == 41                                   # spec 16.2 P15: 40.7 computed
    rows = tuple(dict(r, tol26=4.0) if r["id"] == nominal() else r for r in C.PROFILES)
    c = core(contract=contract_with(PROFILES=rows, ATTRIBUTION_SPREAD_MS=dict(d["attribution_spread_ms"])))
    attributed, rec = _attributed(c, 70)                                                 # 35 ms
    assert attributed is False and rec["attribution_spread_ms"] == 41
    assert [e["seq"] for e in c.log.find("spread-exceeded")] == [rec["seq"]], "counted, not attributed"
    assert _attributed(c, 82)[0] is False and _attributed(c, 84)[0] is True              # 41 ms: no, 42 ms: yes


@tsv.NEEDS_TOML
def test_p15_another_period_moves_the_accounting_edge():
    dbc = tsv._dbc()
    dbc["messages"][C.RULE26_DBC_MESSAGE]["period_ms"] = 10
    d = tsv.gen.derive(tsv._profiles(), dbc, tsv.SLOT_SIGNALS)
    assert d["spread_exceeded_ms"] == 15
    c = core(contract=contract_with(SPREAD_EXCEEDED_MS=d["spread_exceeded_ms"]))
    c.tick(spread_snap(15 * MS), 10**12 + 40 * MS, 1)
    assert c.n["spread_exceeded"] == 0
    c.tick(spread_snap(15 * MS + 1), 10**12 + 40 * MS, 1)
    assert c.n["spread_exceeded"] == 1


@tsv.NEEDS_TOML
def test_p15_another_envelope_row_moves_the_attribution_edge():
    doc = copy.deepcopy(tsv._profiles())
    env = doc["profiles"][[p["id"] for p in doc["profiles"]].index(nominal())]["envelope"]
    doc["envelopes"][env]["steer_rate"] = doc["envelopes"][env]["steer_rate"] / 2
    d = tsv.gen.derive(doc, tsv._dbc(), tsv.SLOT_SIGNALS)
    edge = d["attribution_spread_ms"][nominal()]
    assert edge != C.ATTRIBUTION_SPREAD_MS[nominal()]
    c = core(contract=contract_with(ATTRIBUTION_SPREAD_MS=dict(d["attribution_spread_ms"])))
    assert _attributed(c, 2 * edge)[0] is False and _attributed(c, 2 * edge + 2)[0] is True


def test_p15_every_26_is_logged_with_its_spread_against_a_monitor_that_answers_26(lock):
    fake = FakeMonitor(answer_26)
    try:
        src = vb.QueueSource()
        t0 = time.monotonic_ns() - 100 * MS
        src.push(*[vb.Update(i, HONEST[n], t0 + (40 * MS if n == "delta" else 0)) for i, n in enumerate(NAMES)])
        b = vb.Bridge(cfg(fake.port, lock_path=lock), src, contract=C).start()
        wait_until(lambda: len(replies(b)) >= 3, what="three 26 replies")
        s = ended(b)
    finally:
        fake.close()
    recs = replies(b)
    assert all(r["reason"] == 26 and r["spread_ns"] == 40 * MS and r["attributed"] is True for r in recs), recs
    assert s["counters"]["spread_exceeded"] == s["counters"]["packed"]


# ============================================================ P16: the scenario lock

def test_p16_the_lock_is_held_exactly_while_a_connection_is_open(vss_monitor, lock):
    """'Connected' is the bridge's state, which the observer reads at each connect and close: the lock gates that
    state and every send. The TCP connection the guest sees opens a little earlier, at the end of the handshake,
    and is unlocked until the claim thread sees it complete and takes the lock; nothing is sent in between."""
    seen = []
    port = free_port()
    src = LiveSource()
    box = {}

    def observer(what):
        seen.append((what, vb.updater_check(lock), box["b"].connected))

    box["b"] = b = vb.Bridge(cfg(port, lock_path=lock), src, contract=C, observer=observer).start()
    time.sleep(0.3)
    assert b.counters()["connects"] == 0 and vb.updater_check(lock), "before the first connect: free"
    mon = SvcMonitor(vss_monitor, port)
    try:
        src.start()
        wait_until(lambda: len(accepted_after(b, 0)) >= 2, what="ACCEPTs")
        assert not vb.updater_check(lock), "while connected: the updater's switch is refused"
        b.pause_tick()
        wait_until(lambda: b.log.find("closed"), timeout=1.5, what="a detected close")
        assert vb.updater_check(lock), "after a detected close: free"
        mon.stop()
        b.resume_tick()
        for _ in range(3):                                        # during the backoff, between attempts: free
            k = len(b.log.find("connect-failed"))
            wait_until(lambda k=k: len(b.log.find("connect-failed")) > k, what="a failed connect")
            assert vb.updater_check(lock)
        mon.start()
        wait_until(lambda: b.connected, timeout=4, what="the reconnect")
        assert not vb.updater_check(lock)
        ended(b)
        assert vb.updater_check(lock), "after the stop: free"
    finally:
        mon.stop()
    assert [w for w, _ok, _c in seen] == ["connected", "closed"] * (len(seen) // 2) and len(seen) >= 4
    assert all(ok is False and conn for w, ok, conn in seen if w == "connected"), seen
    assert all(ok is True and not conn for w, ok, conn in seen if w == "closed"), seen


def blackholed_listener():
    """A listener whose accept queue is full (listen(0), one connection queued and never accepted): a further
    connect's SYNs are dropped, so it stays pending, as a connect to a guest that is restarting may."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(0)
    port = srv.getsockname()[1]
    fillers = []
    for _ in range(8):
        c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c.setblocking(False)
        c.connect_ex(("127.0.0.1", port))
        fillers.append(c)
        _r, w, _x = select.select([], [c], [], 0.2)
        if not w:
            return srv, port, fillers                          # this one stays pending: the queue is full
    raise AssertionError("could not fill the accept queue")


def test_p16_a_pending_connect_holds_no_lock_and_ends_at_the_connect_timeout(lock):
    """A connect that never completes (SYNs dropped): the lock is free while it is pending (P16: no lock while the
    guest restarts), the connect timeout ends each attempt with ETIMEDOUT, and the backoff applies after each."""
    srv, port, fillers = blackholed_listener()
    try:
        b = vb.Bridge(cfg(port, lock_path=lock), LiveSource().start(), contract=C).start()
        samples = []
        end = time.monotonic() + 2.6
        while time.monotonic() < end:
            state = b._state
            samples.append((state, vb.updater_check(lock)))
            time.sleep(0.01)
        s = ended(b)
    finally:
        for c in fillers:
            c.close()
        srv.close()
    fails = b.log.find("connect-failed")
    n = s["counters"]
    assert len(fails) >= 3 and n["connect_failures"] == len(fails), fails
    assert all(f["error"] == "ETIMEDOUT" for f in fails), fails
    assert all(500 <= f["waited_ms"] < 500 + SLACK * 1000 for f in fails), fails
    assert [f["backoff_ms"] for f in fails] == EXPECTED_BACKOFF_MS[:len(fails)]
    pending = [free for state, free in samples if state == vb.CONNECTING]
    assert len(pending) >= 50 and all(pending), "the lock is free while a connect is pending: %d of %d" % (
        pending.count(True), len(pending))
    assert n["connects"] == n["lock_busy"] == n["sends"] == 0


def test_p16_the_lock_path_defaults_to_run_lock_and_moves_by_env_or_flag(monkeypatch):
    monkeypatch.delenv("SDV_SCENARIO_LOCK", raising=False)
    assert cfg().lock() == vb.DEFAULT_LOCK == "/run/lock/sdv-scenario.lock"
    monkeypatch.setenv("SDV_SCENARIO_LOCK", "/tmp/elsewhere.lock")
    assert cfg().lock() == "/tmp/elsewhere.lock" and cfg(lock_path="/tmp/flag.lock").lock() == "/tmp/flag.lock"


def test_p16_a_lock_path_that_cannot_be_opened_is_refused_at_start(tmp_path):
    with pytest.raises(vb.BridgeError, match="refused to start: the scenario lock .* cannot be opened"):
        vb.Bridge(cfg(free_port(), lock_path=str(tmp_path / "no-such-dir" / "scenario.lock")), vb.QueueSource(), contract=C)


def test_p16_by_default_a_missing_lock_file_is_created(tmp_path):
    path = tmp_path / "scenario.lock"
    b = vb.Bridge(cfg(free_port(), lock_path=str(path)), vb.QueueSource(), contract=C)
    assert b.lock.create and path.is_file()


def mountinfo_line(n, mount_point):
    """One /proc/self/mountinfo line (proc(5)): its fifth field the mount point, with space, tab, newline and backslash
    octal-escaped as the kernel writes them."""
    esc = "".join("\\%03o" % ord(ch) if ch in " \t\n\\" else ch for ch in str(mount_point))
    return "%d 651 8:48 /host/sdv-scenario.lock %s rw,relatime - ext4 /dev/sdd rw\n" % (n, esc)


@pytest.fixture
def designated(tmp_path, monkeypatch):
    """SDV_SCENARIO_LOCK_MUST_EXIST=1 (the image's setting) on this host: the designated lock path (vb.DEFAULT_LOCK, read
    at each start) moved to a tmp path whose name holds a space, and a mountinfo (vb.MOUNTINFO) listing it as a mount
    point, as the container's lists the host's file bind-mounted at /run/lock/sdv-scenario.lock. No test reaches
    /run/lock. The file itself is the test's to make."""
    d = tmp_path / "run lock"
    d.mkdir()
    path = d / "sdv-scenario.lock"
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("651 436 0:92 / / ro,relatime - overlay overlay rw\n" + mountinfo_line(663, path), encoding="utf-8")
    monkeypatch.setattr(vb, "DEFAULT_LOCK", str(path))
    monkeypatch.setattr(vb, "MOUNTINFO", str(mountinfo), raising=False)
    monkeypatch.delenv("SDV_SCENARIO_LOCK", raising=False)
    monkeypatch.setenv(vb.LOCK_MUST_EXIST_ENV, "1")
    return types.SimpleNamespace(path=path, mountinfo=mountinfo)


def test_p16_with_must_exist_a_missing_lock_file_is_refused_and_never_created(designated):
    """The image's setting: a container started without the host's lock file bind-mounted refuses at start, so it can
    never take a private lock the host's updater does not see."""
    with pytest.raises(vb.BridgeError, match=r"refused to start: the scenario lock .* cannot be opened: .*No such file.*"
                       r"SDV_SCENARIO_LOCK_MUST_EXIST=1: the bridge never creates it; it must be the host's lock file, "
                       r"bind-mounted there"):
        vb.Bridge(cfg(free_port()), vb.QueueSource(), contract=C)
    assert not designated.path.exists()
    designated.path.mkdir()                              # what `docker run -v` leaves for a missing host file
    with pytest.raises(vb.BridgeError, match=r"cannot be opened: .*Is a directory.*--mount type=bind"):
        vb.Bridge(cfg(free_port()), vb.QueueSource(), contract=C)


@pytest.mark.skipif(os.geteuid() == 0, reason="root opens a mode-0 file")
def test_p16_with_must_exist_a_file_this_user_cannot_open_is_refused_with_the_user_hint(designated):
    """The hint follows the errno (the critic's NIT): a mounted file this user cannot open read-write names --user,
    not the mount it already has."""
    designated.path.write_bytes(b"")
    designated.path.chmod(0o444)
    with pytest.raises(vb.BridgeError, match=r"cannot be opened: .*Permission denied.*--user UID:GID") as ei:
        vb.Bridge(cfg(free_port()), vb.QueueSource(), contract=C)
    assert "never creates it" not in str(ei.value)


def test_p16_with_must_exist_the_designated_mounted_lock_file_is_held_while_connected(designated, monkeypatch):
    designated.path.write_bytes(b"")
    monkeypatch.setenv("SDV_SCENARIO_LOCK", str(designated.path))       # naming the designated path itself is no override
    fake = FakeMonitor(accept_all)
    try:
        b = vb.Bridge(cfg(fake.port), LiveSource().start(), contract=C).start()
        assert not b.lock.create and str(b.lock.path) == str(designated.path)
        wait_until(lambda: len(accepted_after(b, 0)) >= 2, what="ACCEPTs")
        assert b.connected and not vb.updater_check(str(designated.path)), "the host's file, held while connected"
        ended(b)
        assert vb.updater_check(str(designated.path))
    finally:
        fake.close()


@pytest.mark.parametrize("via", ["--lock", "SDV_SCENARIO_LOCK"])
@pytest.mark.parametrize("other", ["/dev/null", "an ordinary file"])
def test_p16_with_must_exist_no_lock_but_the_designated_one_is_taken(designated, tmp_path, monkeypatch, via, other):
    """The previous round's critic: under SDV_SCENARIO_LOCK_MUST_EXIST=1, --lock or SDV_SCENARIO_LOCK naming another file
    the bridge can open read-write -- /dev/null, or an existing ordinary file (in a container, one on another mount) --
    was taken: a private lock the host's updater never sees, while the bridge connected and sent. Now the designated
    path is the only one: anything else is refused at start, before any connection, and the file is left as it was."""
    designated.path.write_bytes(b"")                     # the host's file is there, mounted: only the override is wrong
    if other == "/dev/null":
        path = "/dev/null"
    else:
        path = str(tmp_path / "private.lock")
        Path(path).write_bytes(b"")
    if via == "--lock":
        c = cfg(free_port(), lock_path=path)
    else:
        monkeypatch.setenv("SDV_SCENARIO_LOCK", path)
        c = cfg(free_port())
    with pytest.raises(vb.BridgeError, match=r"refused to start: %s names the scenario lock %s, but with "
                       r"SDV_SCENARIO_LOCK_MUST_EXIST=1 the bridge takes only %s" % (re.escape(via), re.escape(path),
                                                                                    re.escape(str(designated.path)))):
        vb.Bridge(c, vb.QueueSource(), contract=C)
    if other != "/dev/null":
        assert Path(path).read_bytes() == b"" and vb.updater_check(path)


def test_p16_with_must_exist_lock_dev_null_never_runs_from_the_command_line(designated, tmp_path, capsys):
    """The critic's reproduction, through the command line (as the image's entry point takes it): `--lock /dev/null`
    under SDV_SCENARIO_LOCK_MUST_EXIST=1 exits 2 with the refusal, makes no run directory and opens no connection
    (unfixed, it ran, connected and got replies while the host's updater saw its own file free)."""
    designated.path.write_bytes(b"")
    fake = FakeMonitor(accept_all)
    try:
        rc = vb.main(_cli_args(fake.port, tmp_path / "run", "/dev/null", "--seconds", "0.6"), source=LiveSource().start())
        time.sleep(0.2)
    finally:
        fake.close()
    out, err = capsys.readouterr()
    assert rc == 2, (rc, out[-600:], err[-600:])
    assert "refused to start: --lock names the scenario lock /dev/null" in err, err
    assert not fake.conns and not (tmp_path / "run").exists() and vb.updater_check(str(designated.path))


def test_p16_with_must_exist_a_lock_file_that_is_not_a_mount_point_is_refused(designated):
    """A file at the designated path that is not a mount point (in a container: made there, by root, with no mount) is a
    private lock; mountinfo decides, so it is refused at start. So is a mountinfo that cannot be read."""
    designated.path.write_bytes(b"")
    designated.mountinfo.write_text("651 436 0:92 / / ro,relatime - overlay overlay rw\n"
                                    + mountinfo_line(660, designated.path.parent), encoding="utf-8")   # its directory only
    with pytest.raises(vb.BridgeError, match=r"refused to start: the scenario lock .* is not a mount point: with "
                       r"SDV_SCENARIO_LOCK_MUST_EXIST=1 it must be the host's lock file, bind-mounted there"):
        vb.Bridge(cfg(free_port()), vb.QueueSource(), contract=C)
    designated.mountinfo.unlink()
    with pytest.raises(vb.BridgeError, match=r"refused to start: .*cannot be read to check"):
        vb.Bridge(cfg(free_port()), vb.QueueSource(), contract=C)
    assert vb.updater_check(str(designated.path))


@pytest.mark.parametrize("must_exist", ["0", "1"])
@pytest.mark.parametrize("kind", ["/dev/null", "a FIFO"])
def test_p16_a_lock_path_that_is_not_a_regular_file_is_refused(designated, tmp_path, monkeypatch, must_exist, kind):
    """In either setting, a lock path that opens but is not a regular file -- a character device such as /dev/null, a
    FIFO -- is refused at start: an flock there is no scenario lock (with must-exist, the designated path itself, as a
    --mount of /dev/null would leave it in a container)."""
    path = "/dev/null" if kind == "/dev/null" else str(tmp_path / "fifo.lock")
    if kind == "a FIFO":
        os.mkfifo(path)
    monkeypatch.setenv(vb.LOCK_MUST_EXIST_ENV, must_exist)
    if must_exist == "1":
        monkeypatch.setattr(vb, "DEFAULT_LOCK", path)
        designated.mountinfo.write_text(mountinfo_line(663, path), encoding="utf-8")
        c = cfg(free_port())
    else:
        c = cfg(free_port(), lock_path=path)
    what = "a character device" if kind == "/dev/null" else "a FIFO"
    with pytest.raises(vb.BridgeError, match=r"refused to start: the scenario lock %s is %s, not a regular file"
                       % (re.escape(path), what)):
        vb.Bridge(c, vb.QueueSource(), contract=C)


@pytest.mark.parametrize("value", ["yes", "", "2"])
def test_p16_a_must_exist_setting_that_is_not_0_or_1_is_refused(tmp_path, monkeypatch, value):
    monkeypatch.setenv(vb.LOCK_MUST_EXIST_ENV, value)
    with pytest.raises(vb.BridgeError, match="SDV_SCENARIO_LOCK_MUST_EXIST=.* is not 0 or 1"):
        vb.Bridge(cfg(free_port(), lock_path=str(tmp_path / "scenario.lock")), vb.QueueSource(), contract=C)
    assert not (tmp_path / "scenario.lock").exists()


LOCK_BUSY_EARLY_MS = 10      # how far a lock-busy record may follow the instant its backoff counts from (the claim thread's own work)


def test_p16_a_lock_held_elsewhere_keeps_the_bridge_from_connecting(lock):
    """Nothing is sent without the lock. A lock-busy attempt backs off like a failed connect, and the backoff is applied,
    not only logged: each next attempt comes once the previous record's backoff_ms has passed (spec 15's backoff row,
    which spares the guest's io-sock 10 connects a second). Each refused attempt is still a TCP connection on the peer's
    side, accepted and closed unused (EOF, no frame): against the guest it leaves a 'client done: seen=0' console line,
    which the bridge logs as lock-busy."""
    fake = FakeMonitor(accept_all)
    other = vb.ScenarioLock(lock)
    assert other.acquire()
    try:
        b = vb.Bridge(cfg(fake.port, lock_path=lock), LiveSource().start(), contract=C).start()
        wait_until(lambda: b.counters()["lock_busy"] >= 4, what="four refused connects")
        assert b.counters()["connects"] == 0 and b.counters()["sends"] == 0 and not fake.frames
        busy = b.log.find("lock-busy")[:4]
        assert [e["backoff_ms"] for e in busy] == EXPECTED_BACKOFF_MS[:4]
        assert all("closed unused" in e["note"] for e in busy)
        gaps_ms = [(c["t_mono"] - p["t_mono"]) / MS for p, c in zip(busy, busy[1:])]
        for p, gap in zip(busy, gaps_ms):
            assert p["backoff_ms"] - LOCK_BUSY_EARLY_MS <= gap < p["backoff_ms"] + SLACK * 1000, (
                "the next attempt is spaced by the logged backoff: gaps %s ms after backoffs %s ms" % (
                    [round(g, 1) for g in gaps_ms], [e["backoff_ms"] for e in busy]))
        wait_until(lambda: len(fake.conns) >= 4 and all(c["end"] for c in fake.conns[:4]), what="the peer's view of them")
        assert [(c["end"], c["frames"]) for c in fake.conns[:4]] == [("eof", [])] * 4, fake.conns[:4]
        assert len(fake.conns) <= b.counters()["lock_busy"] + 1, "one connection per attempt, no more"
        other.release()
        wait_until(lambda: len(accepted_after(b, 0)) >= 2, timeout=4, what="ACCEPTs once the lock is free")
        ended(b)
    finally:
        other.release()
        fake.close()


# ============================================================ P17: the run-level items

def _refused(match, contract=None, **kw):
    with pytest.raises(vb.BridgeError, match=match):
        vb.Bridge(cfg(free_port(), lock_path="/nonexistent/never-created.lock", **kw), vb.QueueSource(), contract=contract or C)


def test_p17_the_bridge_refuses_a_profile_that_is_0_or_not_in_the_generated_table():
    ids = {r["id"] for r in C.PROFILES}
    absent = next(i for i in range(1, 256) if i not in ids)
    _refused("reserved and never bound", profile_id=0)
    _refused("not in the generated profile table", profile_id=absent)
    if 255 not in ids:
        _refused("not in the generated profile table", profile_id=255)
    _refused("not a profile id", profile_id=256)
    uncompiled_ids = [r["id"] for r in C.PROFILES if not r["compiled"]]
    assert 5 in uncompiled_ids, "premise (Phase 8 WP3b): profile 5 is generated but not compiled until WP3c's freeze"
    for uncompiled in uncompiled_ids:
        _refused("generated but not compiled", profile_id=uncompiled, source_vehicle=vehicle(uncompiled))
    syn, sid = tsf.uncompiled_contract()                                                 # and a synthetic one, whatever a freeze compiles
    srow = syn.PROFILES[-1]
    _refused("profile %d is generated but not compiled" % sid, contract=syn, profile_id=sid,
             source_vehicle={"name": srow["source_vehicle"], "wheelbase_mm": srow["l_mm"]})
    _refused("not one of", mode="none")
    _refused("wheelbase 2600 mm, not profile", source_vehicle={"name": "x", "wheelbase_mm": 2600})


def test_p17_the_demo_window_is_bounded_by_the_generated_run_window(lock):
    demo = tsf.demo()
    limit = next(r["run_window_max_ms"] for r in C.PROFILES if r["id"] == demo)
    assert limit == 30000, "spec 5.7: at most 30 s"
    _refused("exceeds profile %d's generated run window" % demo,
             demo_odd_window={"profile_id": demo, "start_s": 0, "duration_s": limit / 1000 + 0.001})
    _refused("not a demo-ODD profile", demo_odd_window={"profile_id": nominal(), "start_s": 0, "duration_s": 1})
    _refused("must be > 0", demo_odd_window={"profile_id": demo, "start_s": 0, "duration_s": 0})
    ended(vb.Bridge(cfg(free_port(), lock_path=lock, demo_odd_window={"profile_id": demo, "start_s": 0, "duration_s": limit / 1000}),
                    vb.QueueSource(), contract=C))


def test_p17_the_logged_age_max_is_the_generated_constant_and_the_run_headers(lock):
    header = {"bridge_mode": "replay", "profile_id": nominal(), "profile_source": "scenario", "source_vehicle": vehicle(),
              "age_max_ms": C.AGE_MAX_MS, "demo_odd_window": None}
    with pytest.raises(vb.BridgeError, match="age_max_ms"):
        vb.Bridge(vb.Config.from_header(dict(header, age_max_ms=C.AGE_MAX_MS + 1), "127.0.0.1", free_port()), vb.QueueSource(), contract=C)
    fake = FakeMonitor(accept_all)
    try:
        b = vb.Bridge(vb.Config.from_header(header, "127.0.0.1", fake.port, lock_path=lock), LiveSource().start(), contract=C).start()
        wait_until(lambda: b.log.find("connect"), what="the connect")
        wait_until(lambda: replies(b), what="a reply")
        ended(b)
    finally:
        fake.close()
    conn = b.log.find("connect")[0]
    assert conn["age_max_ms"] == C.AGE_MAX_MS == header["age_max_ms"]
    assert conn["digest"] == "0x%08X" % C.CATALOG_DIGEST and conn["profile_id"] == nominal() and conn["profile_source"] == "scenario"
    assert conn["source_vehicle"] == vehicle() and conn["mode"] == "replay" and conn["lock"] is True
    assert conn["contract_sha256"] == hashlib.sha256(Path(C.__file__).read_bytes()).hexdigest()


def test_p17_the_demo_profile_is_sent_only_inside_its_window(live):
    demo = tsf.demo()
    cruise = C.ENVELOPES["sigsim"]["cruise_speed"]
    p_demo = tsf.tables().profiles[demo]
    assert cruise > p_demo.v_max, "premise (spec 5.7): honest cruise frames break the demo profile's v_max"
    b, _mon, _src = live(source=LiveSource(v=cruise), demo_odd_window={"profile_id": demo, "start_s": 0.3, "duration_s": 0.5})
    wait_until(lambda: b.core.demo["first_seq"] is not None and len(accepted_after(b, b.core.demo["last_seq"])) >= 3, timeout=4,
               what="the window and ACCEPTs after it")
    s = ended(b)
    recs = replies(b)
    first_t = b.core.first_mono
    demo_recs = [r for r in recs if r["profile"] == demo]
    assert demo_recs and all(r["demo"] for r in demo_recs)
    assert all(0.3e9 <= r["tstamp_ns"] - first_t < 0.8e9 for r in demo_recs), "only inside the window"
    assert all((r["verdict"], r["reason"]) == (1, 23) for r in demo_recs), "honest cruise frames under the demo ODD"
    assert all((r["verdict"], r["reason"]) == (0, 0) for r in recs if r["profile"] != demo)
    assert 3 <= len(demo_recs) <= 6
    logged = b.log.find("demo-odd-window")
    assert len(logged) == 1 and (logged[0]["first_seq"], logged[0]["last_seq"]) == (demo_recs[0]["seq"], demo_recs[-1]["seq"])
    assert s["demo_odd"] == {"first_seq": demo_recs[0]["seq"], "last_seq": demo_recs[-1]["seq"], "frames": len(demo_recs)}
    assert s["rejected_by_origin"] == {"demo_odd": len(demo_recs)}


# ============================================================ P18: the tick never waits on the gRPC side

def test_p18_a_stalled_stream_ages_into_22_without_a_miss_and_a_full_writeback_drops(live):
    gate = threading.Event()
    gate.set()
    written = []

    def sink(rec):                                     # the gRPC side's write-back; stalls with the stream
        gate.wait()
        written.append(rec)

    src = StallableSource()
    b, mon, _ = live(source=src, writeback_sink=sink)
    wait_until(lambda: len(accepted_after(b, 0)) >= 5, what="ACCEPTs")
    n0, packed0 = len(mon.lines), b.counters()["packed"]
    src.flowing.clear()
    gate.clear()
    stalled = last_seq(b)
    # Five deadlines of :7160: long enough that a tick which blocked once the write-back queue filled (about one
    # second in, at the queue's size) would stay silent past a deadline, so a blocking write-back shows as a MISS too.
    time.sleep(2.5)
    packed = b.counters()["packed"] - packed0
    assert packed >= 18, "the ticks go on through the stall: %d frames in 2.5 s" % packed
    during = [r for r in replies(b) if r["seq"] > stalled]
    assert any((r["verdict"], r["reason"]) == (1, 22) for r in during), "the held values age into 22"
    assert mon.count("LIVENESS MISS", after=n0) == 0, mon.text()
    wb = dict(b.writeback.n)
    assert wb["dropped"] >= 1, wb
    src.flowing.set()
    gate.set()
    resumed = last_seq(b)
    wait_until(lambda: len(accepted_after(b, resumed)) >= 2, what="ACCEPTs once the stream flows")
    s = ended(b)
    wb = s["writeback"]
    assert wb["dropped"] >= 1 and wb["written"] >= 1 and wb["written"] + wb["dropped"] <= wb["offered"], wb
    assert set(written[-1]) == set(vb.WRITEBACK_LEAVES)
    assert mon.count("LIVENESS MISS", after=n0) == 0


def test_one_malformed_item_from_a_source_is_refused_and_never_ends_the_intake(lock):
    """An item that is not an Update (here a bare object: AttributeError, not a FrameError) is refused and counted
    like any refused update, and the rest of its batch and every later batch are still held."""
    fake = FakeMonitor(accept_all)
    try:
        src = vb.QueueSource()
        b = vb.Bridge(cfg(fake.port, lock_path=lock), src, contract=C).start()
        src.push(*[vb.Update(i, HONEST[NAMES[i]], time.monotonic_ns()) for i in range(vf.N_SLOTS)])
        wait_until(lambda: replies(b), what="a reply")

        def held_v(v):
            s = b.held.snapshot()[0]
            return s is not None and s[0] == vb.raw_of(0, v)
        src.push(object(), vb.Update(0, 6.0, time.monotonic_ns()))
        wait_until(lambda: held_v(6.0), timeout=2, what="the update beside the malformed item held")
        src.push(vb.Update(0, 7.0, time.monotonic_ns()))
        wait_until(lambda: held_v(7.0), timeout=2, what="a later batch held")
        assert b._intake_thread.is_alive() and not b.log.find("intake-failed"), b.log.find("intake-failed")
        refused = b.log.find("update-refused")
        assert len(refused) == 1 and "AttributeError" in refused[0]["error"], refused
        s = ended(b)
    finally:
        fake.close()
    assert s["intake"]["refused"] == 1


# ============================================================ the write-back's paths

def test_the_writeback_leaves_are_under_the_project_branchs_monitor_vssclaim():
    paths = vb.writeback_paths(C)
    assert set(paths) == set(vb.WRITEBACK_LEAVES)
    assert all(p == "%s.Monitor.VssClaim.%s" % (C.PROJECT_BRANCH, leaf) for leaf, p in paths.items())
    overlay = (REPO / "sdv" / "vss" / "overlay.vspec").read_text(encoding="utf-8")
    for p in paths.values():
        assert re.search(r"^%s:\s*$" % re.escape(p), overlay, re.M), p


# ============================================================ the command line

def _cli_args(port, out, lock, *extra):
    v = vehicle()
    return ["run", "--port", str(port), "--mode", "replay", "--profile", str(nominal()), "--profile-source", "scenario",
            "--vehicle", v["name"], "--wheelbase-mm", str(v["wheelbase_mm"]), "--out", str(out), "--lock", lock, *extra]


def test_cli_runs_the_core_against_an_in_process_source(tmp_path, lock, capsys):
    fake = FakeMonitor(accept_all)
    try:
        rc = vb.main(_cli_args(fake.port, tmp_path / "run", lock, "--seconds", "0.6"), source=LiveSource().start())
    finally:
        fake.close()
    assert rc == 0, capsys.readouterr().err
    s = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert s["identity"]["holds"] and s["ticks_identity"]["holds"] and s["counters"]["accepted"] >= 3
    assert (tmp_path / "run" / "bridge.jsonl").is_file() and (tmp_path / "run" / "replies.jsonl").is_file()
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["identity"]["holds"] is True


def test_cli_takes_the_run_items_from_a_header(tmp_path, lock):
    header = {"bridge_mode": "can", "profile_id": nominal(), "profile_source": "live-default", "source_vehicle": vehicle(),
              "age_max_ms": C.AGE_MAX_MS, "demo_odd_window": None}
    hp = tmp_path / "header.json"
    hp.write_text(json.dumps(header), encoding="utf-8")
    fake = FakeMonitor(accept_all)
    try:
        rc = vb.main(["run", "--port", str(fake.port), "--header", str(hp), "--out", str(tmp_path / "run"), "--lock", lock,
                      "--seconds", "0.4"], source=LiveSource().start())
    finally:
        fake.close()
    assert rc == 0
    starts = [json.loads(line) for line in (tmp_path / "run" / "bridge.jsonl").read_text().splitlines()]
    assert starts[0]["event"] == "start" and starts[0]["mode"] == "can" and starts[0]["profile_source"] == "live-default"
    assert vb.main(["run", "--port", "1", "--header", str(hp), "--mode", "can", "--out", str(tmp_path / "x")], source=vb.QueueSource()) == 2


class TurningClock(vb.QueueSource):
    """A source whose clock turns from int ns to float after `good` reads (an adapter converting timestamps)."""

    def __init__(self, good):
        super().__init__()
        self.good, self.reads = good, 0

    def now_ns(self):
        self.reads += 1
        t = time.monotonic_ns()
        return t if self.reads <= self.good else t / 1.0


def test_cli_a_fatal_in_the_claim_thread_ends_the_run(tmp_path, lock):
    """Without --seconds and with no signal, the claim thread's end (here a fatal: the source's clock turned
    float) ends main(), with exit 1, the fatal in the summary and both identities whole."""
    src = TurningClock(good=3)                             # the start's probe, then two ticks
    box = {}
    th = threading.Thread(target=lambda: box.update(rc=vb.main(_cli_args(1, tmp_path / "run", lock), source=src)), daemon=True)
    th.start()
    th.join(5.0)
    assert not th.is_alive(), "main() still waits after the claim thread's fatal"
    assert box["rc"] == 1
    s = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert "now_ns() returned" in s["fatal"] and s["identity"]["holds"] and s["ticks_identity"]["holds"], s
    assert s["counters"]["ticks"] == s["counters"]["ticks_empty"] == 2


def test_a_source_clock_that_is_not_int_ns_is_refused_at_start(tmp_path, lock, capsys):
    b = vb.Bridge(cfg(free_port(), lock_path=lock), TurningClock(good=0), contract=C)
    with pytest.raises(vb.BridgeError, match="not an int of ns"):
        b.start()
    assert not b._claim_thread.is_alive() and not b._intake_thread.is_alive()
    assert vb.main(_cli_args(1, tmp_path / "run", lock, "--seconds", "0.1"), source=TurningClock(good=0)) == 2
    assert "not an int of ns" in capsys.readouterr().err


def test_cli_a_refused_start_leaves_no_run_directory_behind(tmp_path, lock, capsys):
    """A start refusal (the source's clock is not int ns) removes the empty log files it opened, and the run
    directory if the bridge made it, so the same --out runs next time; a directory that was there stays, empty. A log
    that already holds records (bridge_sources.py writes what it opened before the start; none of its three sources
    is refused there, so this is reached here directly) is kept, and the directory with it."""
    out = tmp_path / "run"
    assert vb.main(_cli_args(1, out, lock, "--seconds", "0.1"), source=TurningClock(good=0)) == 2
    assert "not an int of ns" in capsys.readouterr().err
    assert not out.exists(), sorted(p.name for p in out.iterdir())
    kept = tmp_path / "kept"
    kept.mkdir()
    assert vb.main(_cli_args(1, kept, lock, "--seconds", "0.1"), source=TurningClock(good=0)) == 2
    assert kept.is_dir() and not any(kept.iterdir()), sorted(p.name for p in kept.iterdir())
    written = tmp_path / "written"
    b = vb.Bridge(cfg(1, lock_path=lock), TurningClock(good=0), contract=C, run_dir=written)
    b.log.write("source-opened", note="written before the start, as bridge_sources.py writes what it opened")
    with pytest.raises(vb.BridgeError, match="not an int of ns"):
        b.start()
    assert sorted(p.name for p in written.iterdir()) == ["bridge.jsonl"], sorted(p.name for p in written.iterdir())
    recs = [json.loads(x) for x in (written / "bridge.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["event"] for r in recs] == ["source-opened"], recs
    fake = FakeMonitor(accept_all)
    try:
        assert vb.main(_cli_args(fake.port, out, lock, "--seconds", "0.4"), source=LiveSource().start()) == 0
    finally:
        fake.close()
    assert (out / "summary.json").is_file()


SIGNALLED_RUN = r"""
import sys, threading, time
sys.path.insert(0, sys.argv[1])
import vss_claim_bridge as vb
src = vb.QueueSource()
def feed():
    while True:
        t = time.monotonic_ns()
        src.push(*[vb.Update(i, v, t) for i, v in enumerate(%r)])
        time.sleep(0.02)
threading.Thread(target=feed, daemon=True).start()
sys.exit(vb.main(sys.argv[2:], source=src))
""" % (tuple(HONEST[n] for n in NAMES),)


def signalled(argv, out, sig, timeout=10.0):
    """Run argv (a python -c script and its arguments) in a subprocess until out/replies.jsonl holds two replies, send
    sig, and return (returncode, stdout, stderr)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.Popen([sys.executable, "-c", *argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        rl = out / "replies.jsonl"
        end = time.monotonic() + timeout
        while time.monotonic() < end and p.poll() is None:
            if rl.is_file() and len(rl.read_text(encoding="utf-8").splitlines()) >= 2:
                break
            time.sleep(0.02)
        assert p.poll() is None, p.communicate()
        p.send_signal(sig)
        stdout, stderr = p.communicate(timeout=timeout)
    finally:
        if p.poll() is None:
            p.kill()
            p.communicate()
    return p.returncode, stdout, stderr


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_cli_a_signal_ends_a_run_given_seconds_with_its_summary(tmp_path, lock, sig):
    """SIGTERM (docker stop) or SIGINT before --seconds runs out ends the run as a stop does: the drain, the summary,
    the stop record (after a record naming the signal) and the printed line, exit 0."""
    fake = FakeMonitor(accept_all)
    out = tmp_path / "run"
    try:
        rc, stdout, stderr = signalled([SIGNALLED_RUN, str(BRIDGE_DIR), *_cli_args(fake.port, out, lock, "--seconds", "30")],
                                       out, sig)
    finally:
        fake.close()
    assert rc == 0, (rc, stderr[-3000:])
    s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert s["identity"]["holds"] and s["ticks_identity"]["holds"] and s["seq_partition"]["holds"] and s["fatal"] is None, s
    assert s["counters"]["replied"] >= 2
    recs = [json.loads(x) for x in (out / "bridge.jsonl").read_text(encoding="utf-8").splitlines()]
    assert recs[-1]["event"] == "stop", recs[-1]
    assert [r["signal"] for r in recs if r["event"] == "signal"] == [signal.Signals(sig).name]
    assert json.loads(stdout.strip().splitlines()[-1])["identity"]["holds"] is True


def test_cli_refuses_a_lock_path_that_cannot_be_opened(tmp_path, capsys):
    bad = str(tmp_path / "no-such-dir" / "scenario.lock")
    assert vb.main(_cli_args(1, tmp_path / "run", bad, "--seconds", "0.1"), source=vb.QueueSource()) == 2
    assert "scenario lock" in capsys.readouterr().err and not (tmp_path / "run").exists()


def test_the_claim_thread_is_the_logs_only_file_writer_while_it_runs(tmp_path, lock):
    """Design decision c: the intake's and the control calls' records reach the file through the claim thread,
    which so never waits on another thread's file I/O; the file holds every record, in order."""
    fake = FakeMonitor(accept_all)
    try:
        src = LiveSource().start()
        b = vb.Bridge(cfg(fake.port, lock_path=lock), src, contract=C, run_dir=tmp_path / "run")
        real = b.log._f
        writers = []

        class Spy:
            def write(self, line):
                writers.append((threading.current_thread().name, json.loads(line)["event"]))
                return real.write(line)

            def close(self):
                real.close()

        b.log._f = Spy()
        b.start()
        wait_until(lambda: len(replies(b)) >= 2, what="replies")
        src.push(vb.Update(vf.N_SLOTS, 1.0, time.monotonic_ns()))         # refused by the intake: its record
        b.inject("nan", 1)
        b.pause_intake()
        b.resume_intake()
        wait_until(lambda: {"update-refused", "inject", "pause", "resume"} <= {e for _w, e in writers},
                   what="the intake's and the control calls' records in the file")
        ended(b)
    finally:
        fake.close()
    assert writers[0] == ("MainThread", "start") and writers[-1] == ("MainThread", "stop"), (writers[:2], writers[-2:])
    during = writers[1:-1]
    assert {w for w, _e in during} == {"vss-bridge-claim"}, sorted(set(during))
    lines = [json.loads(x) for x in (tmp_path / "run" / "bridge.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["event"], r["t_mono"]) for r in lines] == [(r["event"], r["t_mono"]) for r in b.log.records]


def test_cli_without_a_source_refuses_and_names_the_adapters_command_line(tmp_path, lock, capsys):
    assert vb.main(_cli_args(1, tmp_path / "run", lock)) == 2
    err = capsys.readouterr().err
    assert "from a shell use bridge_sources.py run" in err and not (tmp_path / "run").exists(), err
    assert (vb.HERE / "bridge_sources.py").is_file()


def test_cli_refuses_a_run_directory_in_the_repo_or_the_recordings(tmp_path, lock, monkeypatch, capsys):
    monkeypatch.setattr(vb, "RECORDINGS", tmp_path / "recs")
    (tmp_path / "recs").mkdir()
    for bad in (REPO / "sdv-out" / "bridge-run", tmp_path / "recs" / "r1"):
        assert vb.main(_cli_args(1, bad, lock, "--seconds", "0.1"), source=vb.QueueSource()) == 2
        assert "inside" in capsys.readouterr().err and not bad.exists()
    assert not any((tmp_path / "recs").iterdir())


# ============================================================ errno names used above exist (a typo would hide a branch)

def test_the_errno_names_the_connect_path_uses_exist():
    for name in ("EINPROGRESS", "EWOULDBLOCK", "EALREADY", "EAGAIN", "ETIMEDOUT"):
        assert hasattr(errno, name)
