"""kind4-spec 16.2 P4, P9, P12, P13's replay arm and P14, the broker intake's pause, and the image: the claim bridge's
source adapters (sdv/bridge/bridge_sources.py, Dockerfile, requirements.lock, build_image.py; sdv Phase 2, WP7).

What is tested, and how:

- With a stand-in for cantools' database built from slice.dbc by the generator's own DBC reader (sdv/stack/attribution.py's
  parse_dbc; exact, little-endian, cantools' arithmetic: raw * scale + offset, an int for an integer scale and offset), a
  fake SocketCAN bus, and a fake databroker client (the generated catalogue's datatypes, a Wheelbase served or not, and a
  v2 subscription whose per-subscriber queue holds buffer_size + 1 notifications and drops the oldest beyond that, as
  databroker 0.7.1 does): the DBC decoding with its scaling, the receive time and the datapoint timestamp as age sources,
  the replay's schedule on the tick grid (with a fake clock), the start checks, and the write-back's paths.
- P4: one input (CAN frames, and the values a databroker would serve for them at the same timestamps) gives each adapter
  the same updates, so the same held values and the same payload; two replays of one file, end to end through the
  command line, pack the same frames apart from the header's tstamp (sdv/bridge/reasonsets.compare_frames).
- P9: through the command line against the native vss svc monitor (built as test_monitor_kind4._build builds it), the
  provider stopping (the fake feed, the fake bus, the end of the file) gives 22 at the first tick whose age exceeds
  AGE_MAX: its age is within AGE_MAX plus one tick, exactly so in replay (the grid makes it deterministic), with an
  allowance for the tick's scheduling in broker and can.
- P13's replay arm: a replay run's event windows, rebuilt from offsets on the recording and the grid origin the run
  logs (`replay-anchored`, source.json's anchor_ns), give exactly the events' reasons against the native monitor.
- SIGTERM or SIGINT ends a `bridge_sources.py run` given --seconds with its summary, source.json and printed line
  (a replay run in a subprocess).
- P12: in each of broker, can and replay a declared source vehicle whose wheelbase is not the profile's L refuses the
  start before any source is opened; broker refuses a served Wheelbase that differs (the catalogue default 0 included),
  starts on an equal one, and starts with the `wheelbase: not served` note when none is served.
- P14: the write-back writes only the Monitor.VssClaim leaves, with the databroker's datatypes, from the core's
  write-back thread and never the claim thread; none of its paths is in the twin allowlist (sdv/stack/attribution.py's
  ALLOWLIST_V1 and MONITOR_PREFIX, which the twin allowlist's tests use).
- The broker intake's pause keeps draining the stream (the fake databroker drops nothing) and only stops updating the
  held values.
- The adapters import no third-party module at import time (every import outside a function body, a guarded one
  included, is the standard library's or the core's); the lock is the union of the app's and the sim's, every
  shared pin equal, and so is the aarch64 lock of the aarch64 locks (SDV Phase 3 WP0); the Dockerfile pins the base
  by the stack's digest, sets SDV_SCENARIO_LOCK_MUST_EXIST=1 and leaves /run/lock writable by root only; the can bus
  is filtered in the kernel to the DBC's slot message ids, and can mode counts the frames received per CAN id before
  decoding (spec 14.2).
- In the sim venv (~/sdv-sim-venv, skipped without it): the stand-in decodes as cantools 44.1.0 does; the real cantools
  and python-can paths (load_dbc, a python-can virtual bus, read_candump against python-can's CanutilsLogReader) give
  the same updates.
- With SDV_BRIDGE_IMAGE set to a built image's ID (sdv/bridge/build_image.py) and Docker present (skipped otherwise):
  the image's `check` imports every adapter's module and loads the contract and the DBC; a replay `run` started without
  the host's lock file mounted refuses at start (exit 2, the scenario lock) as the image's own user, as the host user
  and as root, with a writable root filesystem; no lock but the host's mounted file is ever taken: --lock or
  SDV_SCENARIO_LOCK naming /dev/null or another file, /dev/null mounted at the designated path, and a file made there
  by root without the mount are each refused at start, before any connection; and the documented run (the host's
  file bind-mounted with --mount, --user the host user, a read-only root) holds the host's lock while connected, so
  the host's updater check is refused then and allowed after.

What this does NOT show: any timing (the allowances only bound when a line may come on a loaded host); a real databroker
or a real SocketCAN interface (a fake client and a fake bus; Phase 2 WP8 runs the real ones); anything about the guest.
"""
import ast
import collections
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import test_monitor_kind4 as tmk
import test_monitor_vss as tmv
import test_sdv_bridge as tsb
import test_sdv_frame as tsf

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BRIDGE_DIR = REPO / "sdv" / "bridge"
STACK_DIR = REPO / "sdv" / "stack"
SLICE_DBC = REPO / "sdv" / "vss" / "slice.dbc"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
for _d in (BRIDGE_DIR, STACK_DIR):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
import attribution as attr  # noqa: E402
import bridge_sources as bs  # noqa: E402
import build_image  # noqa: E402

sys.dont_write_bytecode = _saved

vb = bs.vb
vf = tsf.vf
rules = tsf.rules
C = tsf.C
H = vf.FRAME_HEADER_BYTES
MS = 1_000_000

pytestmark = [tsf.NEEDS_CONTRACT]

SIM_PY = Path(os.environ.get("SDV_SIM_VENV", "~/sdv-sim-venv")).expanduser() / "bin" / "python"
NEEDS_SIM = pytest.mark.skipif(not SIM_PY.exists(), reason="needs the sim venv ~/sdv-sim-venv (sdv/sim/requirements.lock)")
WHEELBASE_NOTE_SPEC = "wheelbase: not served by the databroker, checked against the declared source vehicle only"   # spec 5.6
LIVE_JITTER_MS = 50       # how far a live tick may slip on a loaded host; no timing claim
HONEST = {"v": 5.0, "a_x": 0.0, "delta": 0.0, "psi_dot": 0.0, "gear": 1}
NAMES = tsb.NAMES


# ============================================================ the stand-in DBC (cantools' interface, exact)

class StandInSignal:
    def __init__(self, name, spec, choices):
        self.name = name
        self.start, self.length, self.signed = spec["start"], spec["length"], spec["signed"]
        self.factor, self.offset, self.unit = spec["factor"], spec["offset"], spec["unit"]
        self.int_scale = float(self.factor).is_integer() and float(self.offset).is_integer()
        self.choices = choices
        assert spec["little_endian"], "the stand-in reads little-endian signals only (slice.dbc's)"


class StandInMessage:
    def __init__(self, name, spec, choices):
        self.name, self.frame_id, self.length, self.cycle_time = name, spec["id"], spec["dlc"], spec["period_ms"]
        self.signals = [StandInSignal(n, s, choices.get(n)) for n, s in spec["signals"].items()]
        self._by_name = {s.name: s for s in self.signals}
        self.decode_calls = []

    def get_signal_by_name(self, name):
        return self._by_name[name]

    def decode(self, data, decode_choices=True, scaling=True):
        self.decode_calls.append({"decode_choices": decode_choices, "scaling": scaling})
        if len(data) != self.length:
            raise ValueError("%s: %d bytes, not %d" % (self.name, len(data), self.length))
        word = int.from_bytes(bytes(data), "little")
        out = {}
        for s in self.signals:
            raw = (word >> s.start) & ((1 << s.length) - 1)
            if s.signed and raw & (1 << (s.length - 1)):
                raw -= 1 << s.length
            if not scaling:
                val = raw
            elif s.int_scale:
                val = raw * int(s.factor) + int(s.offset)
            else:
                val = raw * s.factor + s.offset
            if decode_choices and s.choices and val in s.choices:
                val = s.choices[val]                     # cantools gives a named value: never a number for the bridge
            out[s.name] = val
        return out

    def encode(self, values):
        word = 0
        for s in self.signals:
            raw = int(round((values.get(s.name, 0) - s.offset) / s.factor))
            word |= (raw & ((1 << s.length) - 1)) << s.start
        return word.to_bytes(self.length, "little")


class StandInDB:
    def __init__(self, text):
        parsed = attr.parse_dbc(text)
        choices = collections.defaultdict(dict)
        for m in re.finditer(r"^VAL_\s+(\d+)\s+(\w+)\s+(.*?);", text, re.M):
            for num, label in re.findall(r"(-?\d+)\s+\"([^\"]*)\"", m.group(3)):
                choices[m.group(2)][int(num)] = label
        self.messages = [StandInMessage(n, s, choices) for n, s in parsed["messages"].items()]
        self._by_name = {m.name: m for m in self.messages}

    def get_message_by_name(self, name):
        return self._by_name[name]


SLICE_TEXT = SLICE_DBC.read_text(encoding="utf-8")
DB = StandInDB(SLICE_TEXT)
DYN = C.SLOT_DBC_MESSAGES[0] if C is not None else "?"
GEAR = C.SLOT_DBC_MESSAGES[4] if C is not None else "?"


def frame_of(msg_name, **slot_values):
    """(CAN id, data) of one slot message, from slot names (v, a_x, delta, psi_dot, gear)."""
    m = DB.get_message_by_name(msg_name)
    sig = {NAMES[i]: C.SLOT_DBC_SIGNALS[i] for i in range(vf.N_SLOTS) if C.SLOT_DBC_MESSAGES[i] == msg_name}
    return m.frame_id, m.encode({sig[k]: v for k, v in slot_values.items()})


def trip(ms=400, vary=True):
    """(t_us, CAN id, data) at slice.dbc's periods from 0 to ms inclusive; varying values or honest ones."""
    out = []
    for name in (DYN, GEAR):
        for t in range(0, ms + 1, C.DBC_PERIOD_MS[name]):
            if name == DYN:
                vals = ({"v": 5.0 + t / 100.0, "a_x": -1.234 + t / 1000.0, "delta": -2.5 + t / 50.0, "psi_dot": 7.77 - t / 40.0}
                        if vary else {k: HONEST[k] for k in NAMES[:4]})
            else:
                vals = {"gear": (1 if (t // 100) % 2 else -1) if vary else HONEST["gear"]}
            cid, data = frame_of(name, **vals)
            out.append((t * 1000, cid, data))
    return sorted(out, key=lambda f: (f[0], f[1]))


def candump(frames, path, base_s=0):
    path.write_text("".join("(%010d.%06d) vcan0 %03X#%s\n" % (base_s + t // 1_000_000, t % 1_000_000, cid, d.hex().upper())
                            for t, cid, d in frames), encoding="ascii")
    return path


def decoded(cid, data):
    """The slots' values a frame carries, as the stand-in decodes it: {slot: value}."""
    m = next(x for x in DB.messages if x.frame_id == cid)
    vals = m.decode(data, decode_choices=False, scaling=True)
    return {i: vals[C.SLOT_DBC_SIGNALS[i]] for i in range(vf.N_SLOTS) if C.SLOT_DBC_MESSAGES[i] == m.name}


def as_served(slot, value):
    """A value as the databroker serves it: a float slot through binary32 (its float type), the gear as an int."""
    return value if slot == vb.GEAR_SLOT else vf.bits_f32(vf.f32_bits(value))


def can_msg(cid, data, ts, **kind):
    base = dict(arbitration_id=cid, data=bytearray(data), timestamp=ts, is_extended_id=False, is_remote_frame=False,
                is_error_frame=False, is_fd=False)
    base.update(kind)
    return types.SimpleNamespace(**base)


# ============================================================ fakes

class FakeBus:
    """python-can's Bus as CanSource uses it: recv(timeout) and shutdown()."""

    def __init__(self, messages=()):
        self.q: "queue.Queue" = queue.Queue()
        for m in messages:
            self.q.put(m)
        self.shut = False
        self.reading = threading.Event()             # set at the first recv: a feed that waits for it leaves no backlog

    def push(self, m):
        self.q.put(m)

    def recv(self, timeout=None):
        self.reading.set()
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def shutdown(self):
        self.shut = True


def catalogue():
    """{path: datatype} of the generated catalogue the databroker loads (sdv-out/gen/vss-databroker.json)."""
    tree = json.loads((tmv.GEN / "vss-databroker.json").read_text(encoding="utf-8"))
    return {p: n["datatype"] for p, n in attr.leaf_nodes(tree).items() if "datatype" in n}


NOT_SERVED = object()


class FakeBroker:
    """The databroker as the BrokerClient protocol sees it (module docstring)."""

    def __init__(self, wheelbase=NOT_SERVED, types_override=None, unbounded=False):
        self.types = catalogue()
        self.types.update(types_override or {})
        self.wheelbase = wheelbase
        self.unbounded = unbounded
        self.calls = []
        self.published = []
        self.closed = False
        self.capacity = None
        self.lagged = 0
        self.delivered = 0
        self.subscribed = threading.Event()
        self.subscribed_paths = None
        self._q: "collections.deque" = collections.deque()
        self._cv = threading.Condition()
        self._cancelled = False
        self._finished = False

    def value_types(self, paths):
        self.calls.append(("value_types", tuple(paths)))
        missing = [p for p in paths if p not in self.types]
        if missing:
            raise bs.BrokerError("NOT_FOUND %s" % missing)
        return {p: self.types[p] for p in paths}

    def get_value(self, path):
        self.calls.append(("get_value", path))
        assert path == "Vehicle.Chassis.Wheelbase"
        return (False, None) if self.wheelbase is NOT_SERVED else (True, self.wheelbase)

    def subscribe(self, paths, buffer_size):
        self.calls.append(("subscribe", tuple(paths), buffer_size))
        self.subscribed_paths = tuple(paths)
        self.capacity = None if self.unbounded else buffer_size + 1
        self.subscribed.set()
        while True:
            with self._cv:
                while not self._q and not self._cancelled and not self._finished:
                    self._cv.wait(0.05)
                if self._cancelled or not self._q:
                    return
                note = self._q.popleft()
                self.delivered += 1
            yield note

    def notify(self, note):
        """The databroker sends one notification to this subscriber: a full queue drops its oldest (a lag)."""
        with self._cv:
            if self.capacity is not None and len(self._q) >= self.capacity:
                self._q.popleft()
                self.lagged += 1
            self._q.append(dict(note))
            self._cv.notify_all()

    def pending(self):
        with self._cv:
            return len(self._q)

    def finish(self):
        """The stream ends once what is queued has been delivered (a test's end of input)."""
        with self._cv:
            self._finished = True
            self._cv.notify_all()

    def cancel(self):
        with self._cv:
            self._cancelled = True
            self._cv.notify_all()

    def publish(self, items):
        self.published.append((threading.current_thread().name, list(items)))

    def close(self):
        self.closed = True
        self.cancel()


class Feed(threading.Thread):
    """A provider at slice.dbc's periods for `seconds`, then stopped. emit(message, slots) sends one message; each
    slot's last age-source timestamp (in the source's clock) is kept in last_ns."""

    def __init__(self, emit, seconds, wait=None):
        super().__init__(daemon=True)
        self.emit, self.seconds, self.wait = emit, seconds, wait
        self.last_ns = {}
        self.stopped_ns = None
        self.sent = collections.Counter()

    def run(self):
        if self.wait is not None:
            self.wait()
        period = {m: C.DBC_PERIOD_MS[m] * MS for m in (DYN, GEAR)}
        t0 = time.monotonic_ns()
        due = dict.fromkeys(period, t0)
        while time.monotonic_ns() - t0 < self.seconds * 1e9:
            now = time.monotonic_ns()
            for m in (DYN, GEAR):
                if now >= due[m]:
                    slots = [i for i in range(vf.N_SLOTS) if C.SLOT_DBC_MESSAGES[i] == m]
                    t_ns = self.emit(m, slots)
                    self.sent[m] += 1
                    for i in slots:
                        self.last_ns[i] = t_ns
                    due[m] += period[m]
            time.sleep(0.002)
        self.stopped_ns = max(self.last_ns.values()) if self.last_ns else None


def bus_feed(bus, seconds, **values):
    vals = dict(HONEST, **values)

    def emit(m, slots):
        ts = time.time()
        cid, data = frame_of(m, **{NAMES[i]: vals[NAMES[i]] for i in slots})
        bus.push(can_msg(cid, data, ts))
        return bs.us_to_ns(ts)
    return Feed(emit, seconds, wait=lambda: bus.reading.wait(10))


def broker_feed(fake, seconds, **values):
    vals = dict(HONEST, **values)

    def emit(_m, slots):
        t_ns = time.time_ns()
        fake.notify({C.SLOT_PATHS[i]: (as_served(i, vals[NAMES[i]]), t_ns) for i in slots})
        return t_ns
    return Feed(emit, seconds, wait=lambda: fake.subscribed.wait(10))


class FakeTime:
    """A clock and a sleep that advances it: the replay iterated in one thread, deterministically."""

    def __init__(self, t0=10**12):
        self.t = t0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += max(1, int(round(s * 1e9)))


# ============================================================ fixtures and the command line

@pytest.fixture(scope="module")
def vss_monitor(tmp_path_factory):
    if not all((tmv.GEN / h).is_file() for h in tmv.GEN_HEADERS):
        pytest.skip("needs the generated contract in sdv-out/gen (sdv/vss/generate.py)")
    return tmk._build(tmv._gcc(), tmv.GEN, tmp_path_factory.mktemp("bridge-sources-vss"), names=("monitor",))["monitor"]


@pytest.fixture(autouse=True)
def _no_default_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("SDV_SCENARIO_LOCK", str(tmp_path / "default-scenario.lock"))
    monkeypatch.delenv(vb.LOCK_MUST_EXIST_ENV, raising=False)


class Opens:
    """The Env the command line opens through, recording every open."""

    def __init__(self, broker=None, bus=None):
        self.calls = []
        self.broker_client, self.bus_obj = broker, bus

    def env(self):
        def broker(target):
            self.calls.append(("broker", target))
            assert self.broker_client is not None, "no databroker client in this test"
            return self.broker_client

        def bus(channel, ids):
            self.calls.append(("bus", channel, tuple(ids)))
            assert self.bus_obj is not None, "no bus in this test"
            return self.bus_obj

        def dbc(path, contract):
            self.calls.append(("dbc", str(path)))
            bs.check_dbc_generation(path, contract)
            return DB

        def read_log(path):
            self.calls.append(("log", str(path)))
            return bs.read_candump(path)
        return bs.Env(broker=broker, bus=bus, dbc=dbc, read_log=read_log)


def argv_for(mode, port, out, lock, *extra, wheelbase=None, header=None):
    if header is not None:
        return ["run", "--port", str(port), "--header", str(header), "--out", str(out), "--lock", str(lock), *extra]
    v = tsb.vehicle()
    return ["run", "--port", str(port), "--mode", mode, "--profile", str(tsb.nominal()), "--profile-source", "scenario",
            "--vehicle", v["name"], "--wheelbase-mm", str(v["wheelbase_mm"] if wheelbase is None else wheelbase),
            "--out", str(out), "--lock", str(lock), *extra]


def run_cli(argv, opens, capsys):
    rc = bs.main(argv, env=opens.env())
    out, err = capsys.readouterr()
    return rc, out, err


def jsonl(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def summary_ok(out_dir):
    s = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    n = s["counters"]
    assert s["fatal"] is None and s["identity"]["holds"] and s["ticks_identity"]["holds"] and s["seq_partition"]["holds"], s
    assert n["packed"] == n["replied"] + n["drop"] + n["lost_on_reconnect"]
    return s


# ============================================================ the DBC side

def test_can_decodes_through_the_dbcs_scaling_and_keeps_the_receive_time():
    dec = bs.SlotDecoder(DB, C)
    vals = {"v": 13.25, "a_x": -1.234, "delta": -2.5, "psi_dot": 7.77}
    cid, data = frame_of(DYN, **vals)
    gid, gdata = frame_of(GEAR, gear=-1)
    bus = FakeBus([can_msg(cid, data, 1700000000.123456), can_msg(gid, gdata, 1700000000.223457)])
    src = bs.CanSource(dec, bus)
    it = src.updates()
    ups = next(it) + next(it)
    src.close()
    assert [u.slot for u in ups] == list(range(vf.N_SLOTS))
    for u in ups[:4]:
        assert vf.f32_bits(u.value) == vf.f32_bits(vals[NAMES[u.slot]]), (NAMES[u.slot], u.value)    # scaled, not raw
        assert u.t_ns == 1700000000123456000                     # SocketCAN's receive time, at its microsecond resolution
    assert ups[4].value == -1 and type(ups[4].value) is int and ups[4].t_ns == 1700000000223457000
    msg = DB.get_message_by_name(DYN)
    assert msg.decode_calls[-1] == {"decode_choices": False, "scaling": True}
    assert dec.decoded_by_id == {cid: 1, gid: 1}


def test_can_never_holds_what_is_not_a_slot_data_frame():
    log = []
    dec = bs.SlotDecoder(DB, C)
    cid, data = frame_of(DYN, **{k: HONEST[k] for k in NAMES[:4]})
    msgs = [can_msg(cid, data, 1.0, is_extended_id=True), can_msg(cid, data, 1.0, is_remote_frame=True),
            can_msg(cid, data, 1.0, is_error_frame=True), can_msg(cid, data, 1.0, is_fd=True),
            can_msg(0x7FF, data, 1.0), can_msg(cid, data[:3], 1.0), can_msg(cid, data[:2], 1.0), can_msg(cid, data, 2.0)]
    bus = FakeBus(msgs)
    src = bs.CanSource(dec, bus)
    src.attach_log(lambda ev, **f: log.append((ev, f)))
    batches = []
    for b in src.updates():
        batches.append(b)
        src.close()
    assert len(batches) == 1 and all(u.t_ns == 2_000_000_000 for u in batches[0])
    st = src.stats()
    assert st["received"] == 8 and st["not_data_frames"] == 4 and st["decode_errors"] == 2
    assert st["other_ids"] == {"0x7FF": 1} and st["bypasses_vss_api"] is True
    assert [e for e, _f in log] == ["source-decode-error"], "logged once; every one counted"
    assert bus.shut
    # Spec 14.2's per-CAN-id count is of what arrived, before decoding: the slot id's two undecodable frames are in it,
    # so it reconciles against a sender's count (received = decoded + decode errors, per id; other ids apart).
    sid = "0x%03X" % cid
    assert st["received_by_id"] == {sid: 3, "0x7FF": 1}, st
    assert st["decoded_by_id"][sid] == 1 and st["decode_errors_by_id"] == {sid: 2}
    assert st["received_by_id"][sid] == st["decoded_by_id"][sid] + st["decode_errors_by_id"][sid]


def test_a_can_source_closed_before_it_runs_shuts_its_bus():
    bus = FakeBus()
    src = bs.CanSource(bs.SlotDecoder(DB, C), bus)
    src.close()
    assert bus.shut and list(src.updates()) == []


@pytest.mark.parametrize("change", ["unit", "period", "signal"])
def test_the_slot_decoder_refuses_a_dbc_that_is_not_the_contracts(change):
    text = SLICE_TEXT
    sig = C.SLOT_DBC_SIGNALS[0]
    if change == "unit":
        text = re.sub(r"(SG_ %s .*?)\"%s\"" % (sig, re.escape(C.SLOT_UNITS[0])), r'\1"km/h"', text, count=1)
    elif change == "period":
        text = re.sub(r"(GenMsgCycleTime\" BO_ \d+ )%d;" % C.DBC_PERIOD_MS[DYN], r"\g<1>%d;" % (C.DBC_PERIOD_MS[DYN] + 1), text, count=1)
    else:
        text = text.replace(" SG_ %s " % sig, " SG_ %sX " % sig, 1)
    assert text != SLICE_TEXT
    with pytest.raises(bs.BridgeError, match="does not match the contract"):
        bs.SlotDecoder(StandInDB(text), C)


def test_the_dbc_must_be_the_one_the_contract_was_generated_from(tmp_path):
    assert bs.check_dbc_generation(SLICE_DBC, C) == json.loads((tmv.GEN / "manifest.json").read_text())["inputs"]["slice.dbc"]
    other = tmp_path / "slice.dbc"
    other.write_text(SLICE_TEXT + "\n// a comment changes the file\n", encoding="utf-8")
    with pytest.raises(bs.BridgeError, match="not the one the contract was generated from"):
        bs.check_dbc_generation(other, C)
    lonely = types.SimpleNamespace(__file__=str(tmp_path / "vss_contract.py"))
    with pytest.raises(bs.BridgeError, match="no readable generation manifest"):
        bs.check_dbc_generation(SLICE_DBC, lonely)


def test_read_candump_reads_standard_frames_and_refuses_everything_else(tmp_path):
    frames = trip(60, vary=True)
    got = bs.read_candump(candump(frames, tmp_path / "ok.log", base_s=1700000000))
    assert [(t - got[0][0], i, d) for t, i, d in got] == frames and got[0][0] == 1700000000 * 1_000_000
    bad = {"extended": "(0000000000.000000) vcan0 00000100#00\n", "remote": "(0000000000.000000) vcan0 100#R\n",
           "fd": "(0000000000.000000) vcan0 100##0aa\n", "odd": "(0000000000.000000) vcan0 100#0\n",
           "long": "(0000000000.000000) vcan0 100#" + "00" * 9 + "\n",
           "back": "(0000000000.020000) vcan0 100#00\n(0000000000.010000) vcan0 100#00\n", "empty": "\n"}
    for name, text in bad.items():
        p = tmp_path / ("%s.log" % name)
        p.write_text(text, encoding="ascii")
        with pytest.raises(bs.BridgeError):
            bs.read_candump(p)


# ============================================================ the replay's schedule

def test_replay_schedules_by_the_recorded_timestamps_on_the_tick_grid():
    """A gap in the file is a gap in delivery: each frame comes at the first grid instant at or after its mapped instant,
    carrying that mapped instant, never the time it was delivered or read."""
    frames = [f for f in trip(300, vary=True)] + [(t + 900_000, i, d) for t, i, d in trip(200, vary=True)]   # a 600 ms gap
    ft = FakeTime()
    src = bs.ReplaySource(bs.SlotDecoder(DB, C), frames, clock=ft.now, sleep=ft.sleep)
    t_first_read = ft.now()
    first = src.now_ns()
    base = t_first_read + vb.TICK_NS // 2
    assert first == base - vb.TICK_NS, "the first reading falls half a tick before the file's first frame"
    released = []
    for batch in src.updates():
        released.append((ft.now(), batch))
    r0 = frames[0][0]
    expect = collections.defaultdict(list)
    for t_us, cid, data in frames:
        off = (t_us - r0) * 1000
        k = -(-off // vb.TICK_NS)
        for slot, value in decoded(cid, data).items():
            expect[k].append((slot, vf.f32_bits(value) if slot != vb.GEAR_SLOT else value, base + off))
    got = {}
    for at, batch in released:
        k = (at - base) // vb.TICK_NS
        assert at == base + k * vb.TICK_NS, "delivered at a grid instant, not when read"
        got[k] = [(u.slot, vf.f32_bits(u.value) if u.slot != vb.GEAR_SLOT else u.value, u.t_ns) for u in batch]
    assert got == dict(expect)
    assert sorted(got) == [0, 1, 2, 3, 9, 10, 11], "nothing is delivered inside the gap"
    assert src.stats()["ended"] is True and src.stats()["frames"] == len(frames)


def test_the_replay_clock_reads_the_last_grid_instant():
    ft = FakeTime()
    src = bs.ReplaySource(bs.SlotDecoder(DB, C), trip(100), clock=ft.now, sleep=ft.sleep)
    base = ft.now() + vb.TICK_NS // 2
    src.now_ns()
    for el_ms, k in ((0, 0), (1, 0), (99, 0), (100, 1), (149, 1), (250, 2), (1000, 10)):
        ft.t = base + el_ms * MS
        assert src.now_ns() == base + k * vb.TICK_NS, el_ms


def test_replay_refuses_a_file_whose_slot_frames_do_not_decode():
    frames = trip(40)
    t, cid, data = frames[2]
    frames[2] = (t, cid, data[:3])
    with pytest.raises(bs.BridgeError, match="does not decode"):
        bs.ReplaySource(bs.SlotDecoder(DB, C), frames)


def test_replay_counts_frames_per_can_id_and_skips_other_ids():
    frames = trip(100) + [(100_000, 0x7AB, b"\x00")]
    src = bs.ReplaySource(bs.SlotDecoder(DB, C), sorted(frames, key=lambda f: f[0]))
    st = src.stats()
    dyn_id, gear_id = DB.get_message_by_name(DYN).frame_id, DB.get_message_by_name(GEAR).frame_id
    n_dyn, n_gear = 100 // C.DBC_PERIOD_MS[DYN] + 1, 100 // C.DBC_PERIOD_MS[GEAR] + 1
    assert st["frames_by_id"] == {"0x%03X" % dyn_id: n_dyn, "0x%03X" % gear_id: n_gear, "0x7AB": 1}
    assert st["other_ids"] == {"0x7AB": 1} and st["frames"] == n_dyn + n_gear + 1


# ============================================================ P4: one input, one payload

def _held_after(updates):
    held = vb.HeldValues()
    vb.Intake(held, vb.EventLog()).offer(updates)
    return held.snapshot()


def test_p4_one_input_gives_every_mode_the_same_updates_and_the_same_payload():
    frames = trip(400, vary=True)
    t0_s = 1700000000
    streams = {}
    # can: the frames on a bus, received at their recorded instants
    bus = FakeBus([can_msg(cid, data, t0_s + t / 1e6) for t, cid, data in frames])
    src = bs.CanSource(bs.SlotDecoder(DB, C), bus)
    ups = []
    for b in src.updates():
        ups += b
        if bus.q.empty():
            src.close()
    streams["can"] = (ups, t0_s * 10**9)
    # broker: what a databroker serves for the same frames, stamped at the same instants
    fake = FakeBroker(unbounded=True)
    for t, cid, data in frames:
        fake.notify({C.SLOT_PATHS[s]: (as_served(s, v), t0_s * 10**9 + t * 1000) for s, v in decoded(cid, data).items()})
    fake.finish()
    bsrc = bs.BrokerSource(fake, C)
    streams["broker"] = ([u for b in bsrc.updates() for u in b], t0_s * 10**9)
    # replay: the same frames in a file, on the grid
    ft = FakeTime()
    rsrc = bs.ReplaySource(bs.SlotDecoder(DB, C), frames, clock=ft.now, sleep=ft.sleep)
    rsrc.now_ns()
    ups = [u for b in rsrc.updates() for u in b]
    streams["replay"] = (ups, rsrc._anchor())
    rel = {}
    for mode, (ups, origin) in streams.items():
        groups = collections.defaultdict(dict)
        for u in ups:
            groups[u.t_ns - origin][u.slot] = vb.raw_of(u.slot, u.value)
        rel[mode] = dict(groups)
    assert len(rel["can"]) == len({t for t, _i, _d in frames}) and rel["can"] == rel["broker"] == rel["replay"]
    payloads = set()
    for mode, (ups, origin) in streams.items():
        snap = _held_after(ups)
        p = tsb.core(tsb.cfg(mode=mode)).tick(snap, origin + 437 * MS, 1).frame
        payloads.add(p[H:])
    assert len(payloads) == 1, "the same held values give the same payload in every mode"


def test_p4_two_replays_of_one_file_pack_the_same_frames_apart_from_tstamp(tmp_path, capsys):
    log = candump(trip(1000, vary=True), tmp_path / "trip.log")
    runs = []
    for n in range(2):
        mon = tsb.FakeMonitor(tsb.accept_all)
        try:
            rc, out, err = run_cli(argv_for("replay", mon.port, tmp_path / ("run%d" % n), tmp_path / "lock", "--log", str(log),
                                            "--seconds", "1.6"), Opens(), capsys)
        finally:
            mon.close()
        assert rc == 0, err
        summary_ok(tmp_path / ("run%d" % n))
        runs.append(list(mon.frames))
    n = min(len(r) for r in runs)
    assert n >= 12, [len(r) for r in runs]
    res = tsb.rs.compare_frames({"mode": "replay", "frames": runs[0][:n]}, {"mode": "replay", "frames": runs[1][:n]})
    assert res["ok"], res
    assert len({f[H + vf.P_V:H + vf.P_V + 4] for f in runs[0][:n]}) >= 10, "the frames carry the file's changing values"
    assert vf.decode(runs[0][0]).age_ms == 0 and vf.decode(runs[0][0]).seq == 1


# ============================================================ P9: the provider stopping gives 22

def _p9(replies, live):
    first = next(r for r in replies if r["reason"] == rules.RSN_VSS_STALE)
    before = [r for r in replies if r["seq"] < first["seq"]]
    assert before and all(r["verdict"] == rules.V_ACCEPT for r in before), before[-3:]
    assert all(r["reason"] == rules.RSN_VSS_STALE for r in replies if r["seq"] >= first["seq"])
    prev = [r for r in before if r["seq"] == first["seq"] - 1]
    assert prev and prev[0]["age_ms"] <= C.AGE_MAX_MS, "22 at the first tick whose age exceeds AGE_MAX"
    bound = C.AGE_MAX_MS + vb.TICK_NS // MS + (LIVE_JITTER_MS if live else 0)
    assert C.AGE_MAX_MS < first["age_ms"] <= bound, first
    return first


@pytest.mark.parametrize("mode", vb.MODES)
def test_p9_the_provider_stopping_gives_22_within_age_max_plus_one_tick(mode, vss_monitor, tmp_path, capsys):
    port = tsb.free_port()
    mon = tsb.SvcMonitor(vss_monitor, port)
    extra = ["--seconds", "2.2"]
    opens = Opens()
    feed = None
    if mode == "broker":
        opens.broker_client = FakeBroker(wheelbase=tsb.vehicle()["wheelbase_mm"])
        feed = broker_feed(opens.broker_client, 1.0)
    elif mode == "can":
        opens.bus_obj = FakeBus()
        feed = bus_feed(opens.bus_obj, 1.0)
    else:
        extra += ["--log", str(candump(trip(1000, vary=False), tmp_path / "honest.log"))]
    try:
        if feed is not None:
            feed.start()
        rc, out, err = run_cli(argv_for(mode, port, tmp_path / "run", tmp_path / "lock", *extra), opens, capsys)
    finally:
        mon.stop()
    assert rc == 0, err
    summary_ok(tmp_path / "run")
    replies = jsonl(tmp_path / "run" / "replies.jsonl")
    first = _p9(replies, live=mode != "replay")
    if feed is not None:
        assert feed.stopped_ns is not None
        assert 0 < first["src_now_ns"] - feed.stopped_ns <= (C.AGE_MAX_MS + vb.TICK_NS // MS + LIVE_JITTER_MS) * MS
    else:
        # the file ends at 1000 ms with both messages: the grid gives the first 22 its age exactly
        k = next(k for k in range(100) if k * vb.TICK_NS // MS - 1000 > C.AGE_MAX_MS)
        assert first["age_ms"] == k * vb.TICK_NS // MS - 1000
        ended = [r for r in jsonl(tmp_path / "run" / "bridge.jsonl") if r["event"] == "replay-ended"]
        assert len(ended) == 1
    assert mon.count("LIVENESS MISS") == 0, mon.text()


# ============================================================ P13: a replay run's windows, from its logged anchor

def test_p13_a_replay_runs_windows_are_the_events_offsets_from_its_logged_anchor(vss_monitor, tmp_path, capsys):
    """Events given as offsets from the recording's first frame (a stand-in for WP9's events file) map onto a replay
    run's src_now_ns by the grid's origin the run logs (`replay-anchored`, and source.json's anchor_ns), read back
    from the run's own record; the windows so rebuilt give exactly the events' reasons against the native monitor:
    23 inside an overspeed window, 22 once the file has ended, nothing outside them."""
    over = (400, 600)                                                     # ms from the first frame
    v_bad = tsf.tables().profiles[tsb.nominal()].v_max + 5.0
    dyn_id = DB.get_message_by_name(DYN).frame_id
    frames = []
    for t, cid, data in trip(1000, vary=False):
        if cid == dyn_id and over[0] <= t // 1000 < over[1]:
            cid, data = frame_of(DYN, **dict({k: HONEST[k] for k in NAMES[:4]}, v=v_bad))
        frames.append((t, cid, data))
    log = candump(frames, tmp_path / "overspeed.log", base_s=1700000000)
    events = [{"event": "overspeed", "t0_ns": over[0] * MS, "t1_ns": over[1] * MS, "reason": rules.RSN_VSS_SPEED},
              {"event": "file-end", "t0_ns": 1000 * MS, "t1_ns": 60_000 * MS, "reason": rules.RSN_VSS_STALE}]
    port = tsb.free_port()
    mon = tsb.SvcMonitor(vss_monitor, port)
    try:
        rc, out, err = run_cli(argv_for("replay", port, tmp_path / "run", tmp_path / "lock", "--log", str(log), "--seconds", "2.2"),
                               Opens(), capsys)
    finally:
        mon.stop()
    assert rc == 0, err
    summary_ok(tmp_path / "run")
    anchor = tsb.rs.replay_anchor(jsonl(tmp_path / "run" / "bridge.jsonl"))
    assert json.loads((tmp_path / "run" / "source.json").read_text(encoding="utf-8"))["anchor_ns"] == anchor
    replies = jsonl(tmp_path / "run" / "replies.jsonl")
    windows = tsb.rs.shift_windows(events, anchor)
    got = tsb.rs.reason_set(replies, windows)
    res = tsb.rs.compare({(e["event"], e["reason"]) for e in events}, got)
    assert res["ok"], res
    offs = {r["reason"]: set() for r in replies if r["verdict"]}
    for r in replies:
        if r["verdict"]:
            offs[r["reason"]].add((r["src_now_ns"] - anchor) // MS)
    assert offs[rules.RSN_VSS_SPEED] <= {400, 500}, offs                    # the grid: exactly the ticks that hold a bad v
    assert min(offs[rules.RSN_VSS_STALE]) > 1000 + C.AGE_MAX_MS, offs


# ============================================================ P12: L

@pytest.mark.parametrize("mode", vb.MODES)
@pytest.mark.parametrize("via", ["flags", "header"])
def test_p12_a_declared_vehicle_that_is_not_the_profiles_l_refuses_in_every_mode(mode, via, tmp_path, capsys):
    v = tsb.vehicle()
    bad = v["wheelbase_mm"] + 1
    extra = ["--seconds", "0.5"] + (["--log", str(candump(trip(40), tmp_path / "t.log"))] if mode == "replay" else [])
    header = None
    if via == "header":
        header = tmp_path / "header.json"
        header.write_text(json.dumps({"bridge_mode": mode, "profile_id": tsb.nominal(), "profile_source": "scenario",
                                      "source_vehicle": {"name": v["name"], "wheelbase_mm": bad}, "age_max_ms": C.AGE_MAX_MS,
                                      "demo_odd_window": None}), encoding="utf-8")
    opens = Opens(broker=FakeBroker(wheelbase=v["wheelbase_mm"]), bus=FakeBus())
    rc, out, err = run_cli(argv_for(mode, 1, tmp_path / "run", tmp_path / "lock", *extra, wheelbase=bad, header=header), opens, capsys)
    assert rc == 2, (out, err)
    assert "wheelbase %d mm, not profile %d's L %d mm (spec 5.6" % (bad, tsb.nominal(), v["wheelbase_mm"]) in err
    assert opens.calls == [], "refused before any source is opened"
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("served", [0, "L+1", "L-1", "float", "bool"])
def test_p12_broker_refuses_a_served_wheelbase_that_is_not_l(served, tmp_path, capsys):
    L = tsb.vehicle()["wheelbase_mm"]
    value = {"L+1": L + 1, "L-1": L - 1, "float": float(L), "bool": True}.get(served, served)
    fake = FakeBroker(wheelbase=value)
    rc, out, err = run_cli(argv_for("broker", 1, tmp_path / "run", tmp_path / "lock", "--seconds", "0.5"), Opens(broker=fake), capsys)
    assert rc == 2, (out, err)
    assert "serves Vehicle.Chassis.Wheelbase = %r, not the profile's L %d mm" % (value, L) in err
    assert fake.closed and not fake.subscribed.is_set() and fake.published == []


def test_p12_broker_starts_on_a_served_wheelbase_equal_to_l(tmp_path, capsys):
    L = tsb.vehicle()["wheelbase_mm"]
    fake = FakeBroker(wheelbase=L)
    mon = tsb.FakeMonitor(tsb.accept_all)
    feed = broker_feed(fake, 0.6)
    feed.start()
    try:
        rc, out, err = run_cli(argv_for("broker", mon.port, tmp_path / "run", tmp_path / "lock", "--seconds", "0.8"), Opens(broker=fake), capsys)
    finally:
        mon.close()
    assert rc == 0, err
    rec = [r for r in jsonl(tmp_path / "run" / "bridge.jsonl") if r["event"] == "wheelbase"]
    assert len(rec) == 1 and rec[0]["served"] is True and rec[0]["value_mm"] == L == rec[0]["l_mm"]
    assert WHEELBASE_NOTE_SPEC not in err
    assert summary_ok(tmp_path / "run")["counters"]["replied"] >= 3


def test_p12_broker_starts_with_the_note_when_no_wheelbase_is_served(tmp_path, capsys):
    fake = FakeBroker(wheelbase=NOT_SERVED)
    mon = tsb.FakeMonitor(tsb.accept_all)
    feed = broker_feed(fake, 0.6)
    feed.start()
    try:
        rc, out, err = run_cli(argv_for("broker", mon.port, tmp_path / "run", tmp_path / "lock", "--seconds", "0.8"), Opens(broker=fake), capsys)
    finally:
        mon.close()
    assert rc == 0, err
    assert bs.WHEELBASE_NOTE == WHEELBASE_NOTE_SPEC
    assert err.count(WHEELBASE_NOTE_SPEC) == 1
    rec = [r for r in jsonl(tmp_path / "run" / "bridge.jsonl") if r["event"] == "wheelbase"]
    assert len(rec) == 1 and rec[0]["served"] is False and rec[0]["note"] == WHEELBASE_NOTE_SPEC
    assert summary_ok(tmp_path / "run")["counters"]["replied"] >= 3


def test_broker_refuses_a_catalogue_whose_slots_are_not_the_contracts(tmp_path, capsys):
    assert C.SLOT_DATATYPES[4] != "int32"
    fake = FakeBroker(wheelbase=tsb.vehicle()["wheelbase_mm"], types_override={C.SLOT_PATHS[4]: "int32"})
    rc, out, err = run_cli(argv_for("broker", 1, tmp_path / "run", tmp_path / "lock", "--seconds", "0.5"), Opens(broker=fake), capsys)
    assert rc == 2 and "%s served as int32, the contract's is %s" % (C.SLOT_PATHS[4], C.SLOT_DATATYPES[4]) in err, err
    assert fake.closed and not fake.subscribed.is_set()


# ============================================================ P14: the write-back, only under Monitor

def _writeback_checks(fake):
    paths = vb.writeback_paths(C)
    cat = catalogue()
    assert fake.published, "the write-back ran"
    for thread, items in fake.published:
        assert thread == "vss-bridge-writeback", "never the claim thread: %s" % thread
        for path, _value, dtype in items:
            assert path in paths.values() and path.startswith(attr.MONITOR_PREFIX + "VssClaim."), path
            assert path not in attr.ALLOWLIST_V1, path
            assert dtype == cat[path], (path, dtype)
    written = {p for _t, items in fake.published for p, _v, _d in items}
    assert written == set(paths.values()), "every leaf, once a reply came"
    return paths


def test_p14_the_broker_writes_back_only_under_monitor_from_the_writeback_thread(tmp_path, capsys):
    fake = FakeBroker(wheelbase=tsb.vehicle()["wheelbase_mm"])
    mon = tsb.FakeMonitor(tsb.accept_all)
    feed = broker_feed(fake, 1.0)
    feed.start()
    try:
        rc, out, err = run_cli(argv_for("broker", mon.port, tmp_path / "run", tmp_path / "lock", "--seconds", "1.0"), Opens(broker=fake), capsys)
    finally:
        mon.close()
    assert rc == 0, err
    paths = _writeback_checks(fake)
    s = summary_ok(tmp_path / "run")
    last = {p: v for _t, items in fake.published for p, v, _d in items}
    n = s["counters"]
    assert last[paths["Packed"]] <= n["packed"] and last[paths["Replied"]] <= n["replied"]
    assert {c[0] for c in fake.calls} == {"value_types", "get_value", "subscribe"}
    assert fake.subscribed_paths == tuple(C.SLOT_PATHS) and fake.calls[-1][2] == bs.SUBSCRIBE_BUFFER


def test_p14_replay_opens_no_databroker_unless_asked_and_then_writes_only_under_monitor(tmp_path, capsys):
    log = candump(trip(600, vary=False), tmp_path / "t.log")
    for wb in ("off", "on"):
        fake = FakeBroker()
        opens = Opens(broker=fake)
        mon = tsb.FakeMonitor(tsb.accept_all)
        extra = ["--log", str(log), "--seconds", "0.8"] + (["--writeback", "on"] if wb == "on" else [])
        try:
            rc, out, err = run_cli(argv_for("replay", mon.port, tmp_path / wb, tmp_path / "lock", *extra), opens, capsys)
        finally:
            mon.close()
        assert rc == 0, err
        if wb == "off":
            assert not any(c[0] == "broker" for c in opens.calls) and fake.calls == []
        else:
            assert ("broker", bs.DEFAULT_BROKER) in opens.calls
            _writeback_checks(fake)
            assert not fake.subscribed.is_set() and not any(c[0] == "get_value" for c in fake.calls)


def test_p14_a_databroker_without_the_monitor_branch_is_refused(tmp_path, capsys):
    fake = FakeBroker(wheelbase=tsb.vehicle()["wheelbase_mm"])
    for p in vb.writeback_paths(C).values():
        del fake.types[p]
    rc, out, err = run_cli(argv_for("broker", 1, tmp_path / "run", tmp_path / "lock", "--seconds", "0.5"), Opens(broker=fake), capsys)
    assert rc == 2 and "Monitor" in err, err
    assert fake.closed


def test_the_writeback_refuses_a_leaf_outside_the_overlay():
    fake = FakeBroker()
    sink = bs.MonitorWriteBack(fake, C)
    with pytest.raises(KeyError):
        sink({"Verdict": 0, "NotALeaf": 1})
    sink({"Verdict": None, "Reason": None, "Packed": 3})
    assert fake.published[-1][1] == [(vb.writeback_paths(C)["Packed"], 3, catalogue()[vb.writeback_paths(C)["Packed"]])]


# ============================================================ broker: the pause keeps draining

def test_broker_pause_keeps_draining_the_stream_and_only_stops_updating_the_held_values():
    fake = FakeBroker(wheelbase=tsb.vehicle()["wheelbase_mm"])
    src = bs.BrokerSource(fake, C, buffer_size=8)
    mon = tsb.FakeMonitor(tsb.accept_all)
    counter = {"v": 0}
    stop = threading.Event()

    def produce():
        fake.subscribed.wait(10)
        while not stop.is_set():
            counter["v"] += 1
            t = time.time_ns()
            fake.notify({C.SLOT_PATHS[0]: (float(counter["v"]), t), C.SLOT_PATHS[4]: (1, t)})
            time.sleep(0.001)
    prod = threading.Thread(target=produce, daemon=True)
    b = vb.Bridge(tsb.cfg(mon.port, mode="broker", lock_path=None), src, contract=C).start()
    prod.start()
    try:
        tsb.wait_until(lambda: b.counters()["replied"] >= 3, what="replies")
        b.pause_intake()
        time.sleep(0.02)                                 # a batch already past the paused check lands first
        held = b.held.snapshot()
        d0, n0 = b.intake.n["discarded"], counter["v"]
        time.sleep(0.6)
        pushed = counter["v"] - n0
        assert pushed > 10 * fake.capacity, pushed
        assert fake.lagged == 0, "the paused intake kept draining: the databroker's queue never overflowed"
        assert b.intake.n["discarded"] - d0 >= pushed - 2 * fake.capacity, (b.intake.n, pushed)
        assert b.held.snapshot() == held, "a paused intake updates no held value"
        b.resume_intake()
        n1 = counter["v"]
        tsb.wait_until(lambda: vf.bits_f32(b.held.snapshot()[0][0]) > n1, what="a fresh value after the resume")
        assert vf.bits_f32(b.held.snapshot()[0][0]) <= counter["v"]
    finally:
        stop.set()
        prod.join(2)
        s = b.stop()
        mon.close()
    assert fake.lagged == 0 and s["fatal"] is None and s["identity"]["holds"]


def test_broker_holds_values_with_their_datapoint_timestamps_and_never_an_untimed_one():
    fake = FakeBroker(unbounded=True)
    log = []
    src = bs.BrokerSource(fake, C)
    src.attach_log(lambda ev, **f: log.append(ev))
    fake.notify({p: (None, None) for p in C.SLOT_PATHS})                      # the initial notification, nothing set yet
    fake.notify({C.SLOT_PATHS[0]: (3.5, None), C.SLOT_PATHS[1]: (0.25, 123), C.SLOT_PATHS[2]: (None, 5)})
    fake.notify({C.SLOT_PATHS[0]: (4.5, 777), C.SLOT_PATHS[0] + "X": (1.0, 1)})
    fake.notify({C.SLOT_PATHS[0]: (5.5, None)})
    fake.finish()
    got = [(u.slot, u.value, u.t_ns) for batch in src.updates() for u in batch]
    assert got ==[(1, 0.25, 123), (0, 4.5, 777)]
    assert src.n == {"notifications": 4, "values": 2, "valueless": 6, "untimed": 2, "unknown_paths": 1}
    assert log == ["source-untimed"]
    assert src.stats()["bypasses_vss_api"] is False and src.clock == bs.REALTIME


# ============================================================ the command line's own refusals

@pytest.mark.parametrize("mode,extra,match", [
    ("can", ["--log", "x.log"], "--log is replay mode's"),
    ("broker", ["--channel", "vcan1"], "--channel is can mode's"),
    ("broker", ["--dbc", "x.dbc"], "--dbc is can and replay modes'"),
    ("replay", [], "replay mode needs --log"),
])
def test_each_modes_flags_are_refused_in_the_others(mode, extra, match, tmp_path, capsys):
    opens = Opens(broker=FakeBroker(), bus=FakeBus())
    rc, out, err = run_cli(argv_for(mode, 1, tmp_path / "run", tmp_path / "lock", "--seconds", "0.5", *extra), opens, capsys)
    assert rc == 2 and match in err, err
    assert opens.calls == []


def test_a_header_with_the_item_flags_is_refused(tmp_path, capsys):
    header = tmp_path / "h.json"
    header.write_text("{}", encoding="utf-8")
    rc, out, err = run_cli(["run", "--port", "1", "--header", str(header), "--mode", "replay", "--out", str(tmp_path / "r")], Opens(), capsys)
    assert rc == 2 and "refused with it" in err


SIGNALLED_RUN = r"""
import sys
for d in sys.argv[1:4]:
    sys.path.insert(0, d)
import test_sdv_bridge_sources as t
sys.exit(t.bs.main(sys.argv[4:], env=t.Opens().env()))
"""


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_a_signal_ends_a_run_given_seconds_with_its_summary_and_source_json(sig, tmp_path):
    """bridge_sources.py run with --seconds, ended early by SIGTERM (docker stop) or SIGINT: the summary, source.json
    and the printed line, exit 0 (a replay run, with the stand-in DBC, in a subprocess)."""
    log = candump(trip(5000, vary=False), tmp_path / "honest.log")
    mon = tsb.FakeMonitor(tsb.accept_all)
    out = tmp_path / "run"
    paths = [str(HERE), str(REPO), str(REPO / "scripts" / "ci")]
    try:
        rc, stdout, stderr = tsb.signalled([SIGNALLED_RUN, *paths, *argv_for("replay", mon.port, out, tmp_path / "lock", "--log",
                                                                              str(log), "--seconds", "30")], out, sig)
    finally:
        mon.close()
    assert rc == 0, (rc, stderr[-3000:])
    summary_ok(out)
    source = json.loads((out / "source.json").read_text(encoding="utf-8"))
    assert source["mode"] == "replay" and source["released_batches"] >= 1, source
    printed = json.loads(stdout.strip().splitlines()[-1])
    assert printed["identity"]["holds"] is True and printed["source"]["mode"] == "replay"
    recs = jsonl(out / "bridge.jsonl")
    assert recs[-1]["event"] == "stop" and [r["signal"] for r in recs if r["event"] == "signal"] == [signal.Signals(sig).name]


def test_the_can_mode_opens_the_bus_on_the_slot_ids(tmp_path, capsys):
    bus = FakeBus()
    opens = Opens(bus=bus)
    mon = tsb.FakeMonitor(tsb.accept_all)
    feed = bus_feed(bus, 0.5)
    feed.start()
    try:
        rc, out, err = run_cli(argv_for("can", mon.port, tmp_path / "run", tmp_path / "lock", "--channel", "vcan7", "--seconds", "0.7"),
                               opens, capsys)
    finally:
        mon.close()
    assert rc == 0, err
    ids = tuple(sorted({DB.get_message_by_name(m).frame_id for m in C.SLOT_DBC_MESSAGES}))
    assert ("bus", "vcan7", ids) in opens.calls and bus.shut
    src = json.loads((tmp_path / "run" / "source.json").read_text())
    assert src["mode"] == "can" and src["bypasses_vss_api"] is True and src["decode_errors"] == 0
    assert sum(src["decoded_by_id"].values()) == src["received"] > 0
    printed = json.loads(out.strip().splitlines()[-1])
    assert printed["source"] == src
    recs = {r["event"]: r for r in jsonl(tmp_path / "run" / "bridge.jsonl")}
    assert recs["source"]["mode"] == "can" and recs["source"]["bypasses_vss_api"] is True
    assert recs["dbc"]["sha256"] == bs.sha256_file(SLICE_DBC) and recs["can-bus"]["channel"] == "vcan7"


def test_the_socketcan_bus_is_filtered_in_the_kernel_to_exactly_the_slot_ids(monkeypatch):
    """socketcan_bus with python-can's module stood in: the kernel filter matches every bit of a standard (11-bit) id,
    one filter per slot message id from the DBC, standard frames only; the bus does not receive its own frames."""
    seen = []
    fake_can = types.ModuleType("can")
    fake_can.Bus = lambda **kw: seen.append(kw) or "the bus"
    monkeypatch.setitem(sys.modules, "can", fake_can)
    ids = bs.SlotDecoder(DB, C).frame_ids
    assert bs.socketcan_bus("vcan7", ids) == "the bus"
    assert seen == [{"interface": "socketcan", "channel": "vcan7", "receive_own_messages": False,
                     "can_filters": [{"can_id": i, "can_mask": (1 << 11) - 1, "extended": False} for i in ids]}]
    assert set(ids) == {DB.get_message_by_name(m).frame_id for m in C.SLOT_DBC_MESSAGES} and len(ids) >= 2


# ============================================================ the imports, the lock, the Dockerfile

THIRD_PARTY = ("grpc", "kuksa", "kuksa_client", "can", "cantools", "google")


def test_importing_the_adapters_loads_no_third_party_module():
    code = ("import sys; sys.dont_write_bytecode = True; sys.path[:0] = [%r]; import bridge_sources, build_image; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] in %r))" % (str(BRIDGE_DIR), THIRD_PARTY))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[]"


def imports_run_at_import(tree):
    """Every import statement that runs when the module is imported: anywhere outside a function or lambda body (a
    try/except, an if, a with or a class body at module level included)."""
    found = []

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                found.append(child)
            visit(child)
    visit(tree)
    return found


def test_the_import_walk_sees_a_guarded_module_level_import():
    """The previous round's survivor: an import inside a module-level try/except (or if, or class body) runs at import
    time too, so the walk below must see it; one inside a function must not be seen."""
    tree = ast.parse("import json\ntry:\n    import grpc\nexcept ImportError:\n    grpc = None\nif True:\n    import can\n"
                     "class K:\n    import cantools\ndef f():\n    import kuksa_client\n")
    names = [a.name for n in imports_run_at_import(tree) for a in n.names]
    assert names == ["json", "grpc", "can", "cantools"], names


def test_every_third_party_import_of_the_adapters_is_inside_a_function():
    for name in ("bridge_sources.py", "build_image.py"):
        tree = ast.parse((BRIDGE_DIR / name).read_text(encoding="utf-8"))
        lazy = []
        for node in imports_run_at_import(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                top = n.split(".")[0]
                # the core's own modules, stdlib-only by test_sdv_bridge's P11 (its CORE_FILES)
                assert top in sys.stdlib_module_names or top in ("vss_claim_bridge", "reasonsets", "vssframe", "__future__"), (name, n)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.ImportFrom) and (sub.module or "").split(".")[0] in THIRD_PARTY:
                        lazy.append(sub.module)
                    elif isinstance(sub, ast.Import):
                        lazy += [a.name for a in sub.names if a.name.split(".")[0] in THIRD_PARTY]
        if name == "bridge_sources.py":
            assert {"grpc", "kuksa_client.grpc", "kuksa.val.v2", "can", "cantools"} <= set(lazy), lazy


def test_the_subscribe_buffer_is_the_witness_buffer():
    """witness.py's BUFFER_SIZE (the largest buffer databroker 0.7.1 accepts), read from its source: it imports grpc."""
    tree = ast.parse((STACK_DIR / "witness.py").read_text(encoding="utf-8"))
    sizes = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "BUFFER_SIZE" for t in n.targets)
             and isinstance(n.value, ast.Constant)]
    assert sizes == [bs.SUBSCRIBE_BUFFER]


def _pins(path):
    text = path.read_text(encoding="ascii")
    pins = re.findall(r"^([a-z0-9-]+)==(\S+) \\\n\s+--hash=sha256:([0-9a-f]{64})\n\s+# (\S+\.whl)$", text, re.M)
    assert len(pins) == len(re.findall(r"^[a-z0-9-]+==", text, re.M)), path
    names = [p[0] for p in pins]
    assert len(names) == len(set(names)) and names == sorted(names), path
    return {n: (v, h) for n, v, h, _w in pins}


@pytest.mark.parametrize("lock", ["requirements.lock", "requirements.aarch64.lock"])
def test_the_lock_is_the_union_of_the_app_and_sim_locks_with_every_shared_pin_equal(lock):
    bridge = _pins(BRIDGE_DIR / lock)
    app = _pins(REPO / "sdv" / "apps" / "hard-brake-hazard" / lock)
    sim = _pins(REPO / "sdv" / "sim" / lock)
    for other in (app, sim):
        for name in set(other) & set(bridge):
            assert other[name] == bridge[name], name
    assert set(bridge) == set(app) | set(sim)
    assert bridge["kuksa-client"][0] == "0.6.0" and bridge["cantools"][0] == "44.1.0" and bridge["python-can"][0] == "4.6.1"


def test_the_dockerfile_pins_the_base_by_the_stacks_digest_and_installs_only_the_lock():
    images = json.loads((STACK_DIR / "images.json").read_text(encoding="utf-8"))
    base = images["base"]["python"]
    text = (BRIDGE_DIR / "Dockerfile").read_text(encoding="utf-8")
    froms = [ln for ln in text.splitlines() if ln.startswith("FROM ")]
    assert froms == ["FROM %s:%s@%s" % (base["repo"], base["tag"], base["index_digest"])]
    assert "pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock" in text
    assert re.search(r"^USER 10001:10001$", text, re.M) and 'ENTRYPOINT ["python", "/app/sdv/bridge/bridge_sources.py"]' in text
    # The scenario lock must be the host's: the bridge never creates it, and its user cannot create one in /run/lock.
    assert re.search(r"^\s+%s=1$" % vb.LOCK_MUST_EXIST_ENV, text, re.M), "the image sets %s=1" % vb.LOCK_MUST_EXIST_ENV
    assert vb.DEFAULT_LOCK.startswith("/run/lock/")
    chmod = text.index("chmod 0755 /run/lock")
    assert chmod < text.index("USER 10001:10001") and text.rfind("\nRUN ", 0, chmod) > text.index("FROM ")
    staged = build_image.staged(tmv.GEN)
    for rel, src in staged.items():
        assert src.is_file(), rel
    imported = {"vss_claim_bridge.py", "reasonsets.py", "bridge_sources.py", "vssframe.py", "rules.py", "slice.dbc",
                "vss_contract.py", "manifest.json"}
    assert {Path(r).name for r in staged} == imported
    assert all(not r.startswith("tests/") for r in staged)


# ============================================================ the sim venv: real cantools and python-can

SIM_SCRIPT = r"""
import json, sys
sys.dont_write_bytecode = True
sys.path[:0] = [sys.argv[1]]
import bridge_sources as bs
import can
vf = bs.vf
C = vf.load_contract()
frames = [(int(t), int(i), bytes.fromhex(d)) for t, i, d in json.loads(sys.argv[2])]
log_path = sys.argv[3]
out = {}
db = bs.load_dbc(bs.SLICE_DBC, C)
dec = bs.SlotDecoder(db, C)
out["cantools"] = {"%d:%s" % (i, d.hex()): {s: v for s, v in db.get_message_by_frame_id(i).decode(d, decode_choices=False).items()}
                   for _t, i, d in frames}
out["gear_types"] = sorted({type(db.get_message_by_frame_id(i).decode(d, decode_choices=False)[C.SLOT_DBC_SIGNALS[4]]).__name__
                            for _t, i, d in frames if C.SLOT_DBC_SIGNALS[4] in [s.name for s in db.get_message_by_frame_id(i).signals]})
# replay: the file through read_candump, then the python-can reader on the same file
mine = bs.read_candump(log_path)
with can.CanutilsLogReader(log_path) as r:
    theirs = [(int(round(m.timestamp * 1_000_000)), m.arbitration_id, bytes(m.data)) for m in r]
out["readers_agree"] = mine == theirs
out["n_frames"] = len(mine)
# can: the same frames over python-can's virtual bus, at their recorded instants
tx = can.Bus(interface="virtual", channel="wp7", receive_own_messages=False)
rx = can.Bus(interface="virtual", channel="wp7", receive_own_messages=False)
src = bs.CanSource(dec, rx)
for t, i, d in frames:
    tx.send(can.Message(arbitration_id=i, data=d, is_extended_id=False, timestamp=0.0))
got = []
it = src.updates()
while len(got) < len(frames):
    b = next(it)
    got.append([(u.slot, vf.f32_bits(u.value) if u.slot < 4 else u.value) for u in b])
src.close()
tx.shutdown()
out["can_updates"] = got
# replay through the real decoder, on a clock its own sleep advances
now = [0]
rs = bs.ReplaySource(dec, frames, clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + int(s * 1e9) + 1))
out["replay_updates"] = [[(u.slot, vf.f32_bits(u.value) if u.slot < 4 else u.value) for u in b] for b in rs.updates()]
print(json.dumps(out))
"""


@NEEDS_SIM
def test_the_real_cantools_and_python_can_paths_agree_with_the_stand_in(tmp_path):
    frames = trip(200, vary=True)
    log = candump(frames, tmp_path / "t.log")
    r = subprocess.run([str(SIM_PY), "-c", SIM_SCRIPT, str(BRIDGE_DIR), json.dumps([(t, i, d.hex()) for t, i, d in frames]), str(log)],
                       capture_output=True, text=True, timeout=120, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    for _t, i, d in frames:
        m = next(x for x in DB.messages if x.frame_id == i)
        assert out["cantools"]["%d:%s" % (i, d.hex())] == m.decode(d, decode_choices=False, scaling=True), (i, d.hex())
    assert out["gear_types"] == ["int"]
    assert out["readers_agree"] is True and out["n_frames"] == len(frames)
    stand_in = [[(s, vf.f32_bits(v) if s < 4 else v) for s, v in sorted(decoded(i, d).items())] for _t, i, d in frames]
    assert [[tuple(x) for x in b] for b in out["can_updates"]] == stand_in, "can: the real path decodes as the stand-in"
    assert [tuple(x) for b in out["replay_updates"] for x in b] == [x for b in stand_in for x in b], "replay: likewise"


@NEEDS_SIM
def test_read_candump_reads_the_recording_as_python_cans_reader_does():
    rec = Path("~/sdv-recordings/20260930-sigsim-1b/sigsim.log").expanduser()
    if not rec.is_file():
        pytest.skip("no Phase 1 recording at %s" % rec)
    code = ("import sys, json, can; sys.dont_write_bytecode = True; sys.path[:0] = [%r]; import bridge_sources as bs\n"
            "mine = bs.read_candump(%r)\n"
            "with can.CanutilsLogReader(%r) as r:\n"
            "    theirs = [(int(round(m.timestamp * 1_000_000)), m.arbitration_id, bytes(m.data)) for m in r]\n"
            "print(json.dumps({'same': mine == theirs, 'n': len(mine)}))" % (str(BRIDGE_DIR), str(rec), str(rec)))
    r = subprocess.run([str(SIM_PY), "-c", code], capture_output=True, text=True, timeout=120, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["same"] is True and out["n"] > 1000


# ============================================================ the image

@pytest.mark.skipif(not os.environ.get("SDV_BRIDGE_IMAGE") or shutil.which("docker") is None,
                    reason="set SDV_BRIDGE_IMAGE to an image ID built by sdv/bridge/build_image.py (needs Docker)")
def test_the_container_image_imports_the_adapters_and_loads_the_contract_and_the_dbc():
    image = os.environ["SDV_BRIDGE_IMAGE"]
    r = subprocess.run(["docker", "run", "--rm", "--network", "none", "--read-only", image, "check"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    pins = _pins(BRIDGE_DIR / "requirements.lock")
    assert out["modules"] == {"kuksa-client": pins["kuksa-client"][0], "grpcio": pins["grpcio"][0], "python-can": pins["python-can"][0],
                              "cantools": pins["cantools"][0]}
    assert out["python"].startswith("3.12.")
    assert out["contract"]["digest"] == "0x%08X" % C.CATALOG_DIGEST and out["contract"]["slot_paths"] == list(C.SLOT_PATHS)
    assert out["dbc"]["sha256"] == bs.sha256_file(SLICE_DBC)
    assert out["writeback_paths"] == sorted(vb.writeback_paths(C).values())
    labels = json.loads(subprocess.run(["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", image],
                                       capture_output=True, text=True, timeout=60).stdout)
    assert labels["sdv.kind4.catalog_digest"] == "0x%08X" % C.CATALOG_DIGEST
    assert labels["sdv.kind4.dbc_sha256"] == bs.sha256_file(SLICE_DBC)
    assert labels["sdv.kind4.contract_sha256"] == bs.sha256_file(tmv.GEN / "vss_contract.py")


NEEDS_IMAGE = pytest.mark.skipif(not os.environ.get("SDV_BRIDGE_IMAGE") or shutil.which("docker") is None,
                                 reason="set SDV_BRIDGE_IMAGE to an image ID built by sdv/bridge/build_image.py (needs Docker)")


def _image_workdir(tmp_path):
    """A directory every container user can use (the image's own, the host's, root): the candump file and --out."""
    w = tmp_path / "w"
    w.mkdir()
    candump(trip(1000), w / "trip.log")
    os.chmod(w, 0o777)
    os.chmod(w / "trip.log", 0o644)
    return w


def _image_replay(port, *extra):
    v = tsb.vehicle()
    return ["run", "--host", "127.0.0.1", "--port", str(port), "--mode", "replay", "--profile", str(tsb.nominal()),
            "--profile-source", "scenario", "--vehicle", v["name"], "--wheelbase-mm", str(v["wheelbase_mm"]),
            "--log", "/w/trip.log", "--out", "/w/run", *extra]


def _docker_run(name, opts, argv, timeout=120):
    try:
        return subprocess.run(["docker", "run", "--rm", "--name", name, *opts, os.environ["SDV_BRIDGE_IMAGE"], *argv],
                              capture_output=True, text=True, timeout=timeout)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=60)


@NEEDS_IMAGE
@pytest.mark.parametrize("user,env", [(None, None), ("host", None), ("0:0", None), (None, "0")],
                         ids=["image-user", "host-user", "root", "image-user-must-exist-0"])
def test_the_image_refuses_to_start_without_the_hosts_lock_file_mounted(tmp_path, user, env):
    """No --read-only, no mount: the bridge must not create a private lock the host's updater never sees. The image's
    SDV_SCENARIO_LOCK_MUST_EXIST=1 refuses a missing file for every user (root included); with it overridden to 0, the
    image's user still cannot create one, since /run/lock is writable by root only."""
    w = _image_workdir(tmp_path)
    opts = ["--network", "none", "-v", "%s:/w" % w]
    if user is not None:
        opts += ["--user", "%d:%d" % (os.getuid(), os.getgid()) if user == "host" else user]
    if env is not None:
        opts += ["-e", "%s=%s" % (vb.LOCK_MUST_EXIST_ENV, env)]
    r = _docker_run("sdv-bridge-test-nolock-%d" % os.getpid(), opts, _image_replay(7160, "--seconds", "1"))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "refused to start: the scenario lock %s cannot be opened" % vb.DEFAULT_LOCK in r.stderr, r.stderr
    if env is None:
        assert "No such file or directory" in r.stderr and "%s=1" % vb.LOCK_MUST_EXIST_ENV in r.stderr, r.stderr
    else:
        assert "Permission denied" in r.stderr, r.stderr
    assert not (w / "run").exists()


@NEEDS_IMAGE
def test_the_images_documented_mount_refuses_a_missing_host_file_instead_of_making_a_directory(tmp_path):
    missing = tmp_path / "no-such.lock"
    w = _image_workdir(tmp_path)
    opts = ["--network", "none", "--read-only", "--user", "%d:%d" % (os.getuid(), os.getgid()), "-v", "%s:/w" % w,
            "--mount", "type=bind,src=%s,dst=%s" % (missing, vb.DEFAULT_LOCK)]
    r = _docker_run("sdv-bridge-test-missing-%d" % os.getpid(), opts, _image_replay(7160, "--seconds", "1"))
    assert r.returncode not in (0, 2) and not missing.exists() and not (w / "run").exists(), (r.returncode, r.stderr)


PRIVATE_LOCKS = {
    # case: what the refusal says after "refused to start: "
    "lock-flag-dev-null": "--lock names the scenario lock /dev/null, but with SDV_SCENARIO_LOCK_MUST_EXIST=1",
    "lock-flag-private-file": "--lock names the scenario lock /w/private.lock, but with SDV_SCENARIO_LOCK_MUST_EXIST=1",
    "lock-env-private-file": "SDV_SCENARIO_LOCK names the scenario lock /w/private.lock, but with SDV_SCENARIO_LOCK_MUST_EXIST=1",
    "dev-null-mounted": "the scenario lock %s is a character device, not a regular file" % "/run/lock/sdv-scenario.lock",
    "root-made-file-unmounted": "the scenario lock %s is not a mount point" % "/run/lock/sdv-scenario.lock",
}


@NEEDS_IMAGE
@pytest.mark.parametrize("case", list(PRIVATE_LOCKS))
def test_the_image_takes_no_lock_but_the_hosts_mounted_file(tmp_path, case):
    """Under the image's SDV_SCENARIO_LOCK_MUST_EXIST=1 the only lock is the host's file mounted at the designated path.
    Each of these would be a private lock the host's updater never sees, and each is refused at start (exit 2) before
    any connection, with no run directory: --lock or SDV_SCENARIO_LOCK naming /dev/null or an existing ordinary file on
    another mount (the host's file mounted as documented beside it), /dev/null mounted at the designated path, and a
    file made there by root in a container started without the mount. Unfixed (the previous round's image), each ran,
    connected and was answered while the host's updater saw its own file free."""
    w = _image_workdir(tmp_path)
    (w / "private.lock").write_bytes(b"")
    os.chmod(w / "private.lock", 0o666)
    lock = tmp_path / "sdv-scenario.lock"
    lock.write_bytes(b"")
    mon = tsb.FakeMonitor(tsb.accept_all)
    host_user = ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    documented = host_user + ["--mount", "type=bind,src=%s,dst=%s" % (lock, vb.DEFAULT_LOCK)]
    opts = ["--network", "host", "-v", "%s:/w" % w]
    argv = _image_replay(mon.port, "--seconds", "2")
    if case == "lock-flag-dev-null":
        opts += documented
        argv += ["--lock", "/dev/null"]
    elif case == "lock-flag-private-file":
        opts += documented
        argv += ["--lock", "/w/private.lock"]
    elif case == "lock-env-private-file":
        opts += documented + ["-e", "SDV_SCENARIO_LOCK=/w/private.lock"]
    elif case == "dev-null-mounted":
        opts += ["--mount", "type=bind,src=/dev/null,dst=%s" % vb.DEFAULT_LOCK]
    else:
        opts += ["--user", "0:0", "--entrypoint", "sh"]
        argv = ["-c", 'touch %s && exec python /app/sdv/bridge/bridge_sources.py "$@"' % vb.DEFAULT_LOCK, "sh", *argv]
    try:
        r = _docker_run("sdv-bridge-test-private-%d" % os.getpid(), opts, argv)
        time.sleep(0.2)
    finally:
        mon.close()
    assert r.returncode == 2, (r.returncode, r.stdout[-2000:], r.stderr[-2000:])
    assert "refused to start: " + PRIVATE_LOCKS[case] in r.stderr, r.stderr
    assert not mon.conns and not mon.frames, mon.conns
    assert not (w / "run").exists() and vb.updater_check(str(lock))
    assert (w / "private.lock").read_bytes() == b""


@NEEDS_IMAGE
def test_the_image_run_as_documented_holds_the_hosts_lock_while_connected(tmp_path):
    """The host's lock file bind-mounted with --mount, --user the host user, a read-only root, the host's network (the
    peer is a Python monitor on the host): while the bridge in the container is connected the host's updater check is
    refused, and after the run it is allowed (one inode)."""
    lock = tmp_path / "sdv-scenario.lock"
    lock.write_bytes(b"")
    w = _image_workdir(tmp_path)
    mon = tsb.FakeMonitor(tsb.accept_all)
    name = "sdv-bridge-test-lock-%d" % os.getpid()
    opts = ["--network", "host", "--read-only", "--user", "%d:%d" % (os.getuid(), os.getgid()), "-v", "%s:/w" % w,
            "--mount", "type=bind,src=%s,dst=%s" % (lock, vb.DEFAULT_LOCK)]
    assert vb.updater_check(str(lock)), "free before the run"
    held = 0
    try:
        p = subprocess.Popen(["docker", "run", "--rm", "--name", name, *opts, os.environ["SDV_BRIDGE_IMAGE"],
                              *_image_replay(mon.port, "--seconds", "3")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 60
        while p.poll() is None and time.monotonic() < deadline:
            if not vb.updater_check(str(lock)):
                held += 1
            time.sleep(0.01)
        out, err = p.communicate(timeout=60)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=60)
        mon.close()
    assert p.returncode == 0, (out, err)
    assert held >= 10, "the host's updater saw the container's lock held %d times" % held
    assert vb.updater_check(str(lock)), "free after the run"
    s = summary_ok(w / "run")
    assert s["counters"]["replied"] > 0 and s["counters"]["lock_busy"] == 0
    assert any(r["event"] == "connect" for r in jsonl(w / "run" / "bridge.jsonl"))
