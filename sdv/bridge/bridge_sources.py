#!/usr/bin/env python3
"""bridge_sources.py -- the kind 4 claim bridge's source adapters (broker, can, replay), its write-back to the
databroker's Monitor branch, and its command line with a real source (sdv/bridge; Phase 2 WP7).

The core (vss_claim_bridge.py) packs, sends and accounts; this module gives it
the three intakes of the kind 4 wire specification (the project's local design notes, section 14.1; not in this
tree), the broker mode's start checks (section 5.6) and the write-back (section 14.4). Every third-party import
-- grpc and kuksa-client, python-can, cantools -- is made inside the function or class that needs it, never at
module level, so importing this module (and the core) loads none of them.

    bridge_sources.py run --port PORT [--host ADDR] (--header FILE | --mode MODE --profile ID
        --profile-source SOURCE --vehicle NAME --wheelbase-mm MM [--demo-odd START_S,DURATION_S])
        [--broker HOST:PORT] [--writeback on|off] [--channel IFACE] [--log CANDUMP] [--dbc FILE]
        [--seconds S] [--script FILE] [--name NAME | --out DIR] [--lock PATH] [--gen DIR]
    bridge_sources.py check [--dbc FILE] [--gen DIR]

`run` opens the mode's source, then runs the core exactly as vss_claim_bridge.py's own `run` does (the same
run items, refusals, lock, output directory, script, signals and exit codes: SIGTERM or SIGINT ends a run given
--seconds too), and adds source.json (the source's counts) to the run directory. A script (vss_claim_bridge.py,
SCRIPT) is parsed before any source is opened; its origin is replay's grid anchor (ReplaySource.origin_ns, its
clock the raw CLOCK_MONOTONIC, raw_now_ns), and in can and broker the first held update's age-source
timestamp. `check` imports every adapter's third-party modules, loads the generated contract and the DBC, and
prints what it found: the container's smoke.

THE MODES (spec 14.1; the run header's bridge_mode)
  broker  One kuksa.val.v2 Subscribe on the five slot paths (the generated SLOT_PATHS; the template is
          sdv/stack/witness.py), buffer SUBSCRIBE_BUFFER. A notification's value is held with its datapoint
          timestamp as the age source; a value with no timestamp has no age source and is never held (counted,
          logged once). The clock the ages are read on is CLOCK_REALTIME, the clock a protobuf Timestamp counts
          (seconds since the epoch), and the clock basis this adapter expects for the served stamp. It assumes a
          receipt stamp rather than the writer's source timestamp; `stack.py ageprobe` can check the broker's stamping behaviour.
          Under that assumption broker mode's age is the bridge's realtime now minus the databroker's receipt: the
          provider's leg (CAN receive, decode, the write) lies outside it. A wall-clock step moves the ages
          (age_negative counts a backward one). The stream is read in the bridge's intake thread, so pausing the
          intake keeps draining it and only stops updating the held values (the core's Intake discards while
          paused): a pause does not fill the databroker's per-subscriber queue, and a resume reads no stale
          backlog. A stream that ends or fails is logged by the core and not retried: the values then age into 22.
          So a databroker restart during a broker-mode run turns every later frame into 22 until the bridge is
          restarted (the write-back's VSSClient may reconnect on its own): the stack restarts the bridge after
          the databroker (WP8), or a long run resubscribes, which this module does not.
  can     python-can's SocketCAN bus on --channel, filtered in the kernel to the slot messages' CAN ids, each frame
          decoded with cantools through the DBC (scaled, choices not applied). The age source is the frame's
          SocketCAN receive time (python-can's Message.timestamp), treated as CLOCK_REALTIME. The adapter
          requires that clock basis; its unit tests do not establish it for a kernel or device. source.json counts the
          standard data frames received per CAN id before decoding (received_by_id = decoded_by_id +
          decode_errors_by_id, other ids apart): spec 14.2's count, reconciled against the sender's.
  replay  The candump file (--log) read here, line by line, never through SocketCAN, a bus or a databroker, and
          decoded with the same DBC at open. It is scheduled by its recorded timestamps on a grid of the core's
          tick (TICK_NS): the file's first frame maps to the grid's origin, half a tick after the first reading
          of the replay clock; every frame maps to the origin plus its offset from the first, which is its age
          source, and is delivered at the first grid instant at or after that; and the replay clock is
          CLOCK_MONOTONIC read down to the last grid instant. The origin is a per-run value, so it is logged once
          when set (`replay-anchored`, anchor_ns; source.json's anchor_ns too): a recording offset off is at
          anchor_ns + off on the run's src_now_ns, which is how a replay run's event windows are built
          (reasonsets.py). The bridge reads the clock at its start and then once per tick, so its readings
          fall mid-step, half a tick from any delivery, and its first tick, before the file's first frame,
          finds nothing held. So at every reading the held values are exactly the frames recorded up to it, the
          age is the file's own (a gap in the file ages a value; the host's scheduling does not), and two
          replays of one file pack the same frames apart from the header's tstamp (spec 16.2 P4). That holds
          only while every tick reads the clock within half a tick of its schedule: a later reading can land
          on or past a grid instant and race that instant's delivery, and an overrun (a tick a whole tick
          late, counted as tick_overruns) also moves the core's tick phase, since it reschedules from the late
          tick. On a loaded host two replays can then differ, and tick_overruns 0 does not show the condition
          held (a tick less than a whole tick late is not counted). The file ending is the replay's provider
          stopping: the values age into 22.
  Units are never converted (spec 14.1): the DBC's units must equal the contract's (checked at open), and
  `can` and `replay` bypass the VSS API, which every record of theirs must say.

START CHECKS (refusals, exit 2, before the run starts)
  The core's own (vss_claim_bridge.bind: mode, profile, the declared source vehicle's wheelbase against the
  profile's L in every mode, AGE_MAX, the demo-ODD window) run first, before any source is opened. Then:
  broker  the databroker serves each slot path with the contract's datatype; and its Vehicle.Chassis.Wheelbase
          (spec 5.6): a served value that is not the profile's L is refused (the catalogue default 0 included),
          one equal to L is logged, and none served starts with the note WHEELBASE_NOTE (log and stderr).
  can, replay  the DBC is the one the contract was generated from (its sha256 equals the generation
          manifest's), its slot signals carry the contract's units and its slot messages the contract's
          periods; replay also refuses a file that is not candump -l standard data frames in time order, or
          whose slot frames do not decode.
  write-back  the databroker serves every Monitor.VssClaim leaf; their datatypes are read from it.

THE WRITE-BACK (spec 14.4; on by default in broker mode, optional in can and replay)
  The core's write-back thread calls MonitorWriteBack with each record; it writes the record's leaves, and only
  them, under <project branch>.Monitor.VssClaim with kuksa-client's set(try_v2=True) (v2 PublishValue), with
  the datatypes the databroker gave at open. It is never called from the tick: the core queues to it and
  drops and counts when its queue is full. A leaf with no value yet (no reply received) is not written.

DESIGN VALUES (this file's, also rows of spec 15; none is generated)
  SUBSCRIBE_BUFFER = 1000: witness.py's BUFFER_SIZE, the largest buffer databroker 0.7.1 accepts. The intake
  drains the stream continuously, paused or not, so the buffer only absorbs a stall of the intake thread itself.
  BROKER_TIMEOUT_S = 10 s: how long a start check waits for the databroker before refusing.
  WRITEBACK_RPC_TIMEOUT_S = 2 s: one write-back's wait for the databroker (the write-back thread's, never the tick's).
  CAN_RECV_POLL_S = 0.2 s: the CAN intake's longest wait per receive, so a close ends it within that.

DOES NOT DEMONSTRATE: any timing; that the databroker serves what a provider wrote (broker mode samples what the
VSS API presents, spec 14.2); the databroker's stamping behaviour (the adapter assumes a receipt stamp and
`stack.py ageprobe` checks it); a broker run end to end (the tests use a fake databroker client and a fake bus; WP8 and WP10 run the real stack,
sdv/stack); anything about the guest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import reasonsets as rs  # noqa: E402
import vss_claim_bridge as vb  # noqa: E402

vf = vb.vf
REPO = vb.REPO
SLICE_DBC = REPO / "sdv" / "vss" / "slice.dbc"
MANIFEST_NAME = "manifest.json"          # beside the generated contract (sdv/vss/generate.py writes both)

WHEELBASE_PATH = "Vehicle.Chassis.Wheelbase"     # VSS 6.0: attribute, uint16, mm (spec 5.6)
WHEELBASE_NOTE = "wheelbase: not served by the databroker, checked against the declared source vehicle only"
DEFAULT_BROKER = "127.0.0.1:55555"
DEFAULT_CHANNEL = "vcan0"

# Design values (module docstring, DESIGN VALUES).
SUBSCRIBE_BUFFER = 1000
BROKER_TIMEOUT_S = 10.0
WRITEBACK_RPC_TIMEOUT_S = 2.0
CAN_RECV_POLL_S = 0.2

REALTIME = "CLOCK_REALTIME"
MONOTONIC_GRID = "CLOCK_MONOTONIC, read down to the tick grid"

BridgeError = vb.BridgeError


class BrokerError(BridgeError):
    """The databroker could not be asked, or answered something the bridge cannot use."""


def _no_log(_event: str, **_fields: Any) -> None:
    return None


def us_to_ns(seconds: float) -> int:
    """A python-can timestamp (float seconds, microsecond resolution) as int ns at that resolution."""
    return int(round(seconds * 1_000_000)) * 1000


# --- the DBC side (can, replay) -----------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def generation_manifest(contract: Any) -> Dict[str, Any]:
    """The generation manifest beside the contract (sdv-out/gen/manifest.json)."""
    path = Path(getattr(contract, "__file__", "") or ".").with_name(MANIFEST_NAME)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise BridgeError("no readable generation manifest at %s, so the DBC cannot be matched to the contract: %s" % (path, err)) from err


def check_dbc_generation(path: Path, contract: Any) -> str:
    """The DBC is the one the contract was generated from: its sha256 equals the manifest's slice.dbc input."""
    want = generation_manifest(contract).get("inputs", {}).get("slice.dbc")
    got = sha256_file(path)
    if got != want:
        raise BridgeError("the DBC %s (sha256 %s) is not the one the contract was generated from (%s): regenerate, or name that DBC"
                          % (path, got, want))
    return got


def load_dbc(path: Path, contract: Any) -> Any:
    """slice.dbc (or the DBC at path) through cantools, strict, after checking it is the contract's."""
    check_dbc_generation(path, contract)
    import cantools  # lazily: the core never imports it
    return cantools.database.load_file(str(path), strict=True)


class SlotDecoder:
    """The slot messages' frames into Updates, through the DBC (cantools, or a stand-in with its interface).

    Checked at construction against the contract: each slot's signal is in its message, with the contract's
    unit; each slot message's cycle time is the contract's period. decode() takes a frame's CAN id, data and
    age-source timestamp, and returns the Updates of the slots the frame carries, or None for a CAN id that
    carries none (counted)."""

    def __init__(self, db: Any, contract: Any) -> None:
        by_id: Dict[int, Tuple[Any, List[Tuple[int, str]]]] = {}
        problems: List[str] = []
        for slot, (sig, msg_name, unit) in enumerate(zip(contract.SLOT_DBC_SIGNALS, contract.SLOT_DBC_MESSAGES, contract.SLOT_DBC_UNITS)):
            try:
                msg = db.get_message_by_name(msg_name)
                s = msg.get_signal_by_name(sig)
            except KeyError:
                problems.append("slot %d: no signal %s in message %s" % (slot, sig, msg_name))
                continue
            if (s.unit or None) != unit:
                problems.append("slot %d: %s's unit %r is not the contract's %r (the bridge converts nothing)" % (slot, sig, s.unit, unit))
            period = contract.DBC_PERIOD_MS.get(msg_name)
            if msg.cycle_time != period:
                problems.append("%s: cycle time %r is not the contract's period %r" % (msg_name, msg.cycle_time, period))
            by_id.setdefault(int(msg.frame_id), (msg, []))[1].append((slot, sig))
        if problems:
            raise BridgeError("the DBC does not match the contract: " + "; ".join(problems))
        self._by_id = by_id
        self.frame_ids: Tuple[int, ...] = tuple(sorted(by_id))
        self.decoded_by_id: Dict[int, int] = {i: 0 for i in self.frame_ids}
        self.other_ids: Dict[int, int] = {}

    def decode(self, can_id: int, data: bytes, t_ns: int) -> Optional[List[vb.Update]]:
        entry = self._by_id.get(can_id)
        if entry is None:
            self.other_ids[can_id] = self.other_ids.get(can_id, 0) + 1
            return None
        msg, slots = entry
        values = msg.decode(bytes(data), decode_choices=False, scaling=True)
        self.decoded_by_id[can_id] += 1
        return [vb.Update(slot, values[sig], t_ns) for slot, sig in slots]

    def counts(self) -> Dict[str, Any]:
        return {"decoded_by_id": {"0x%03X" % k: v for k, v in sorted(self.decoded_by_id.items())},
                "other_ids": {"0x%03X" % k: v for k, v in sorted(self.other_ids.items())}}


_CANDUMP = re.compile(r"^\((\d+)\.(\d{6})\)\s+\S+\s+([0-9A-Fa-f]{3})#([0-9A-Fa-f]*)$")


def read_candump(path: Path) -> List[Tuple[int, int, bytes]]:
    """A candump -l file as (timestamp in us, CAN id, data), read here line by line. Only standard data frames
    of up to 8 bytes in non-decreasing time order: anything else (extended, remote, error or FD frames, a
    timestamp that goes back) refuses the file, as sigsim.read_log does."""
    frames: List[Tuple[int, int, bytes]] = []
    with open(path, encoding="ascii") as f:
        for n, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            m = _CANDUMP.match(s)
            if m is None or len(m.group(4)) % 2 or len(m.group(4)) > 16:
                raise BridgeError("%s:%d: not a candump -l standard data frame: %r" % (path, n, s[:80]))
            t_us = int(m.group(1)) * 1_000_000 + int(m.group(2))
            if frames and t_us < frames[-1][0]:
                raise BridgeError("%s:%d: the timestamp goes back (%d us after %d us): a replay cannot schedule it" % (path, n, t_us, frames[-1][0]))
            frames.append((t_us, int(m.group(3), 16), bytes.fromhex(m.group(4))))
    if not frames:
        raise BridgeError("%s holds no frame" % path)
    return frames


# --- the sources -----------------------------------------------------------------------------------------------

class CanSource:
    """mode can: SocketCAN frames, decoded with the DBC; the age source is each frame's receive time."""

    mode = "can"
    clock = REALTIME

    def __init__(self, decoder: SlotDecoder, bus: Any, clock: Callable[[], int] = time.time_ns) -> None:
        self.decoder = decoder
        self._bus = bus
        self._clock = clock
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._iterating = False
        self._shut = False
        self._log: Callable[..., Any] = _no_log
        self.n: Dict[str, int] = {"received": 0, "not_data_frames": 0, "decode_errors": 0}
        # Spec 14.2: a received-frame count per CAN id (standard data frames), counted before decoding, so it reconciles
        # against the recording's or sigsim's send count: received_by_id = decoded_by_id + decode_errors_by_id + other_ids.
        self.received_by_id: Dict[int, int] = {}
        self.decode_errors_by_id: Dict[int, int] = {}

    def attach_log(self, write: Callable[..., Any]) -> None:
        self._log = write

    def now_ns(self) -> int:
        return self._clock()

    def updates(self) -> Iterator[List[vb.Update]]:
        with self._lock:
            if self._closed.is_set():
                self._shutdown_locked()
                return
            self._iterating = True
        try:
            while not self._closed.is_set():
                m = self._bus.recv(timeout=CAN_RECV_POLL_S)
                if m is None:
                    continue
                self.n["received"] += 1
                if m.is_extended_id or m.is_remote_frame or m.is_error_frame or getattr(m, "is_fd", False):
                    self.n["not_data_frames"] += 1
                    continue
                cid = int(m.arbitration_id)
                self.received_by_id[cid] = self.received_by_id.get(cid, 0) + 1
                try:
                    ups = self.decoder.decode(cid, bytes(m.data), us_to_ns(m.timestamp))
                except Exception as err:  # noqa: BLE001 -- a frame the DBC cannot decode is counted, never held
                    self.n["decode_errors"] += 1
                    self.decode_errors_by_id[cid] = self.decode_errors_by_id.get(cid, 0) + 1
                    if self.n["decode_errors"] == 1:
                        self._log("source-decode-error", can_id="0x%03X" % m.arbitration_id, error=repr(err),
                                  note="logged once; every one is counted")
                    continue
                if ups:
                    yield ups
        finally:
            with self._lock:
                self._shutdown_locked()

    def _shutdown_locked(self) -> None:
        if not self._shut:
            self._shut = True
            self._bus.shutdown()

    def close(self) -> None:
        """Ends updates() within CAN_RECV_POLL_S; the bus is shut down by the iterator, or here if none runs."""
        with self._lock:
            self._closed.set()
            if not self._iterating:
                self._shutdown_locked()

    def stats(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"mode": self.mode, "clock": self.clock, "bypasses_vss_api": True}
        out.update(self.n)
        out.update(self.decoder.counts())
        out["received_by_id"] = {"0x%03X" % k: v for k, v in sorted(self.received_by_id.items())}
        out["decode_errors_by_id"] = {"0x%03X" % k: v for k, v in sorted(self.decode_errors_by_id.items())}
        return out


class ReplaySource:
    """mode replay: the candump file, scheduled by its recorded timestamps on the tick grid (module docstring)."""

    mode = "replay"
    clock = MONOTONIC_GRID

    def __init__(self, decoder: SlotDecoder, frames: Sequence[Tuple[int, int, bytes]],
                 clock: Callable[[], int] = time.monotonic_ns, tick_ns: int = vb.TICK_NS,
                 sleep: Optional[Callable[[float], Any]] = None) -> None:
        if not frames:
            raise BridgeError("a replay needs at least one frame")
        self.decoder = decoder
        self._tick = int(tick_ns)
        self._clock = clock
        self._closed = threading.Event()
        self._sleep = sleep if sleep is not None else self._closed.wait
        self._lock = threading.Lock()
        self._base: Optional[int] = None
        self._log: Callable[..., Any] = _no_log
        r0 = frames[0][0]
        batches: Dict[int, List[Tuple[int, Any, int, int]]] = {}
        self.frames_by_id: Dict[int, int] = {}
        for n, (t_us, can_id, data) in enumerate(frames, 1):
            self.frames_by_id[can_id] = self.frames_by_id.get(can_id, 0) + 1
            off = (t_us - r0) * 1000
            try:
                ups = decoder.decode(can_id, data, off)
            except Exception as err:  # noqa: BLE001 -- the file is refused, not skipped over
                raise BridgeError("frame %d (CAN id 0x%03X at %d us) does not decode: %r" % (n, can_id, t_us, err)) from err
            if ups is None:
                continue
            k = -(-off // self._tick)                    # the first grid instant at or after the frame's mapped instant
            batches.setdefault(k, []).extend((u.slot, u.value, off, can_id) for u in ups)
        self._batches = sorted(batches.items())
        self.duration_us = frames[-1][0] - r0
        self.n: Dict[str, Any] = {"frames": len(frames), "released_updates": 0, "released_batches": 0, "ended": False}

    def attach_log(self, write: Callable[..., Any]) -> None:
        self._log = write

    def _anchor(self) -> int:
        """The grid's origin, where the file's first frame maps to: half a tick after the first reading of the clock.
        Logged once, when set (`replay-anchored`; the bridge's start reads the clock first), so a recording offset
        off is at anchor_ns + off on the replay clock, read from the run's own record (reasonsets.replay_anchor)."""
        with self._lock:
            new = self._base is None
            if self._base is None:
                self._base = self._clock() + self._tick // 2
            base: int = self._base
        if new:
            self._log(rs.REPLAY_ANCHORED, anchor_ns=base, tick_ns=self._tick, clock=self.clock,
                      note="the file's first frame maps to anchor_ns: a recording offset off is at anchor_ns + off on src_now_ns")
        return base

    def now_ns(self) -> int:
        """The replay clock: the last grid instant at or before now (the grid anchored by the first reading)."""
        b = self._anchor()
        return b + ((self._clock() - b) // self._tick) * self._tick

    def origin_ns(self) -> int:
        """A script's origin (vss_claim_bridge.py, SCRIPT): the grid's anchor, where the file's first frame maps, so a
        script step's at_ns is an offset on the recording, as the events file's are."""
        return self._anchor()

    def raw_now_ns(self) -> int:
        """A script's clock: the replay clock before it is read down to the grid, so a step can land between a delivery
        (on the grid) and the tick that reads it (half a tick later)."""
        return self._clock()

    def updates(self) -> Iterator[List[vb.Update]]:
        b = self._anchor()
        for k, items in self._batches:
            due = b + k * self._tick
            while True:
                if self._closed.is_set():
                    return
                left = due - self._clock()
                if left <= 0:
                    break
                self._sleep(left / 1e9)
            self.n["released_batches"] += 1
            self.n["released_updates"] += len(items)
            yield [vb.Update(slot, value, b + off) for slot, value, off, _id in items]
        self.n["ended"] = True
        self._log("replay-ended", frames=self.n["frames"], duration_us=self.duration_us,
                  note="the file ended: from here the held values age (22 within AGE_MAX plus one tick)")

    def close(self) -> None:
        self._closed.set()

    def stats(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"mode": self.mode, "clock": self.clock, "bypasses_vss_api": True, "tick_ns": self._tick,
                               "anchor_ns": self._base, "duration_us": self.duration_us,
                               "frames_by_id": {"0x%03X" % k: v for k, v in sorted(self.frames_by_id.items())}}
        out.update(self.n)
        out.update(self.decoder.counts())
        return out


class BrokerSource:
    """mode broker: one kuksa.val.v2 Subscribe on the five slot paths; the age source is the datapoint timestamp.

    `client` keeps the BrokerClient protocol (KuksaBroker, or a test's fake): value_types(paths) -> {path:
    datatype name}; get_value(path) -> (served, value); subscribe(paths, buffer_size) -> an iterator of
    notifications, each {path: (value or None, timestamp in ns since the epoch or None)}; cancel() ends a running
    subscribe from another thread; publish(items) writes [(path, value, datatype)]; close()."""

    mode = "broker"
    clock = REALTIME

    def __init__(self, client: Any, contract: Any, clock: Callable[[], int] = time.time_ns, buffer_size: int = SUBSCRIBE_BUFFER) -> None:
        self.client = client
        self.contract = contract
        self.paths: Tuple[str, ...] = tuple(contract.SLOT_PATHS)
        self.slot_of = {p: i for i, p in enumerate(self.paths)}
        self.buffer_size = int(buffer_size)
        self._clock = clock
        self._log: Callable[..., Any] = _no_log
        self.n: Dict[str, int] = {"notifications": 0, "values": 0, "valueless": 0, "untimed": 0, "unknown_paths": 0}

    def attach_log(self, write: Callable[..., Any]) -> None:
        self._log = write

    def start_checks(self, l_mm: int) -> Dict[str, Any]:
        """Spec 5.6 and the slots' datatypes: a BridgeError is a refusal. Returns the record the run logs."""
        try:
            types = self.client.value_types(list(self.paths))
        except BridgeError:
            raise
        except Exception as err:  # noqa: BLE001 -- whatever the client raised, the start is refused with it
            raise BrokerError("the databroker did not give the slot paths' datatypes: %s" % err) from err
        wrong = ["%s served as %s, the contract's is %s" % (p, types.get(p), want)
                 for p, want in zip(self.paths, self.contract.SLOT_DATATYPES) if types.get(p) != want]
        if wrong:
            raise BrokerError("the databroker's catalogue is not the contract's: " + "; ".join(wrong))
        try:
            served, value = self.client.get_value(WHEELBASE_PATH)
        except BridgeError:
            raise
        except Exception as err:  # noqa: BLE001
            raise BrokerError("the databroker did not answer for %s: %s" % (WHEELBASE_PATH, err)) from err
        if not served:
            return {"event": "wheelbase", "path": WHEELBASE_PATH, "served": False, "l_mm": l_mm, "note": WHEELBASE_NOTE}
        if isinstance(value, bool) or not isinstance(value, int) or value != l_mm:
            raise BridgeError("the databroker serves %s = %r, not the profile's L %d mm: the catalogue and the profile describe "
                              "different vehicles (spec 5.6)" % (WHEELBASE_PATH, value, l_mm))
        return {"event": "wheelbase", "path": WHEELBASE_PATH, "served": True, "value_mm": value, "l_mm": l_mm}

    def now_ns(self) -> int:
        return self._clock()

    def updates(self) -> Iterator[List[vb.Update]]:
        for note in self.client.subscribe(self.paths, self.buffer_size):
            self.n["notifications"] += 1
            batch: List[vb.Update] = []
            for path in sorted(note):
                value, t_ns = note[path]
                slot = self.slot_of.get(path)
                if slot is None:
                    self.n["unknown_paths"] += 1
                    continue
                if value is None:
                    self.n["valueless"] += 1
                    continue
                if t_ns is None:
                    self.n["untimed"] += 1
                    if self.n["untimed"] == 1:
                        self._log("source-untimed", path=path, note="a value with no datapoint timestamp has no age source and is "
                                  "never held; logged once, every one is counted")
                    continue
                batch.append(vb.Update(slot, value, t_ns))
            self.n["values"] += len(batch)
            if batch:
                yield batch

    def close(self) -> None:
        self.client.cancel()

    def stats(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"mode": self.mode, "clock": self.clock, "bypasses_vss_api": False, "buffer_size": self.buffer_size}
        out.update(self.n)
        return out


# --- the write-back ---------------------------------------------------------------------------------------------

class MonitorWriteBack:
    """The core's write-back sink (spec 14.4): a record's leaves to <project branch>.Monitor.VssClaim, nothing else."""

    def __init__(self, client: Any, contract: Any) -> None:
        self.client = client
        self.paths = vb.writeback_paths(contract)
        branch = "%s.%s." % (contract.PROJECT_BRANCH, vb.MONITOR_BRANCH)
        outside = [p for p in self.paths.values() if not p.startswith(branch)]
        if outside:
            raise BridgeError("write-back paths outside %s: %s" % (branch, outside))
        try:
            self.types = self.client.value_types(list(self.paths.values()))
        except BridgeError:
            raise
        except Exception as err:  # noqa: BLE001
            raise BrokerError("the databroker did not give the Monitor leaves' datatypes (no Monitor branch?): %s" % err) from err
        missing = [p for p in self.paths.values() if not self.types.get(p)]
        if missing:
            raise BrokerError("the databroker serves no %s" % ", ".join(missing))
        self.callers: Dict[str, int] = {}

    def __call__(self, rec: Mapping[str, Any]) -> None:
        name = threading.current_thread().name
        self.callers[name] = self.callers.get(name, 0) + 1
        items = []
        for leaf, value in rec.items():
            path = self.paths[leaf]                      # a leaf the overlay does not define: KeyError, counted failed
            if value is not None:
                items.append((path, value, self.types[path]))
        if items:
            self.client.publish(items)


# --- the real databroker client ---------------------------------------------------------------------------------

class KuksaBroker:
    """The BrokerClient protocol (BrokerSource) over grpc and kuksa-client 0.6.0, imported here. The subscription
    and the Wheelbase read use the kuksa.val.v2 stub on a channel of their own (witness.py's template); the
    datatypes and the write-back go through kuksa-client's VSSClient (set with try_v2=True)."""

    def __init__(self, target: str, timeout_s: float = BROKER_TIMEOUT_S) -> None:
        import grpc
        from kuksa.val.v2 import types_pb2, val_pb2, val_pb2_grpc
        from kuksa_client.grpc import VSSClient
        host, _sep, port = target.rpartition(":")
        if not host or not port.isdigit():
            raise BridgeError("the databroker address %r is not HOST:PORT" % target)
        self._grpc, self._types, self._val = grpc, types_pb2, val_pb2
        self._timeout = timeout_s
        self._channel = grpc.insecure_channel(target)
        self._stub = val_pb2_grpc.VALStub(self._channel)
        self._client = VSSClient(host, int(port), ensure_startup_connection=False)
        self._client.connect()
        self._lock = threading.Lock()
        self._call: Any = None
        self._cancelled = False

    def _rpc_error(self, what: str, err: Any) -> BrokerError:
        code = err.code().name if hasattr(err, "code") and callable(err.code) else type(err).__name__
        details = err.details() if hasattr(err, "details") and callable(err.details) else str(err)
        return BrokerError("%s: %s %s" % (what, code, str(details)[:300]))

    def value_types(self, paths: Sequence[str]) -> Dict[str, str]:
        from kuksa_client.grpc import VSSClientError
        try:
            got = self._client.get_value_types(list(paths), timeout=self._timeout, wait_for_ready=True)
        except (VSSClientError, self._grpc.RpcError) as err:
            raise BrokerError("the datatypes of %s: %s" % (", ".join(paths), err)) from err
        return {p: t.name.lower() for p, t in got.items()}

    def get_value(self, path: str) -> Tuple[bool, Any]:
        req = self._val.GetValueRequest(signal_id=self._types.SignalID(path=path))
        try:
            resp = self._stub.GetValue(req, timeout=self._timeout, wait_for_ready=True)
        except self._grpc.RpcError as err:
            if err.code() == self._grpc.StatusCode.NOT_FOUND:
                return False, None
            raise self._rpc_error("GetValue %s" % path, err) from err
        fields = resp.data_point.value.ListFields()
        if not fields:
            return False, None
        return True, getattr(resp.data_point.value, fields[0][0].name)

    def subscribe(self, paths: Sequence[str], buffer_size: int) -> Iterator[Dict[str, Tuple[Any, Optional[int]]]]:
        req = self._val.SubscribeRequest(signal_paths=list(paths), buffer_size=buffer_size)
        with self._lock:
            if self._cancelled:
                return
            call = self._call = self._stub.Subscribe(req, wait_for_ready=True)
        try:
            for resp in call:
                out: Dict[str, Tuple[Any, Optional[int]]] = {}
                for path, dp in resp.entries.items():
                    fields = dp.value.ListFields()
                    value = getattr(dp.value, fields[0][0].name) if fields else None
                    t_ns = dp.timestamp.seconds * 1_000_000_000 + dp.timestamp.nanos if dp.HasField("timestamp") else None
                    out[path] = (value, t_ns)
                yield out
        except self._grpc.RpcError as err:
            if self._cancelled and err.code() == self._grpc.StatusCode.CANCELLED:
                return
            raise self._rpc_error("the subscription", err) from err

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            if self._call is not None:
                self._call.cancel()

    def publish(self, items: Sequence[Tuple[str, Any, str]]) -> None:
        from kuksa_client.grpc import DataEntry, Datapoint, DataType, EntryUpdate, Field, Metadata
        updates = [EntryUpdate(DataEntry(path, value=Datapoint(value), metadata=Metadata(data_type=DataType[dtype.upper()])), (Field.VALUE,))
                   for path, value, dtype in items]
        self._client.set(updates=updates, try_v2=True, timeout=WRITEBACK_RPC_TIMEOUT_S)

    def close(self) -> None:
        self.cancel()
        try:
            self._client.disconnect()
        finally:
            self._channel.close()


def socketcan_bus(channel: str, frame_ids: Sequence[int]) -> Any:
    """python-can's SocketCAN bus on channel, filtered in the kernel to the given standard CAN ids."""
    import can
    filters = [{"can_id": i, "can_mask": 0x7FF, "extended": False} for i in frame_ids]
    return can.Bus(interface="socketcan", channel=channel, can_filters=filters, receive_own_messages=False)


# --- the run ------------------------------------------------------------------------------------------------------

@dataclass
class Env:
    """What the run opens, replaceable by a test: the databroker client, the CAN bus, the DBC, the candump reader
    and the clocks."""
    broker: Callable[[str], Any] = KuksaBroker
    bus: Callable[[str, Sequence[int]], Any] = socketcan_bus
    dbc: Callable[[Path, Any], Any] = load_dbc
    read_log: Callable[[Path], List[Tuple[int, int, bytes]]] = read_candump
    realtime: Callable[[], int] = time.time_ns
    monotonic: Callable[[], int] = time.monotonic_ns


@dataclass
class Opened:
    source: Any
    sink: Optional[Callable[[Dict[str, Any]], None]]
    clients: List[Any]
    records: List[Dict[str, Any]]

    def close_clients(self) -> None:
        for c in self.clients:
            try:
                c.close()
            except Exception:  # noqa: BLE001,S110 -- closing what is already gone
                pass


def open_source(cfg: vb.Config, contract: Any, l_mm: int, opts: argparse.Namespace, env: Env) -> Opened:
    """The mode's source and the write-back sink, after their start checks (a BridgeError is a refusal)."""
    clients: List[Any] = []
    records: List[Dict[str, Any]] = []
    try:
        sink: Optional[Callable[[Dict[str, Any]], None]] = None
        if cfg.mode == "broker":
            client = env.broker(opts.broker)
            clients.append(client)
            src: Any = BrokerSource(client, contract, clock=env.realtime)
            records.append(src.start_checks(l_mm))
            if opts.writeback != "off":
                sink = MonitorWriteBack(client, contract)
        else:
            dbc_path = Path(opts.dbc)
            dec = SlotDecoder(env.dbc(dbc_path, contract), contract)
            records.append({"event": "dbc", "path": str(dbc_path), "sha256": sha256_file(dbc_path),
                            "frame_ids": ["0x%03X" % i for i in dec.frame_ids]})
            if cfg.mode == "can":
                src = CanSource(dec, env.bus(opts.channel, dec.frame_ids), clock=env.realtime)
                records.append({"event": "can-bus", "channel": opts.channel})
            else:
                log = Path(opts.log)
                src = ReplaySource(dec, env.read_log(log), clock=env.monotonic)
                records.append({"event": "replay-file", "path": str(log), "sha256": sha256_file(log), "frames": src.n["frames"],
                                "duration_us": src.duration_us})
            if opts.writeback == "on":
                client = env.broker(opts.broker)
                clients.append(client)
                sink = MonitorWriteBack(client, contract)
        records.append({"event": "source", "mode": cfg.mode, "clock": src.clock, "bypasses_vss_api": cfg.mode != "broker",
                        "writeback": sink is not None})
        return Opened(src, sink, clients, records)
    except BaseException:
        Opened(None, None, clients, records).close_clients()
        raise


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the bridge with the mode's source")
    r.add_argument("--host", default="127.0.0.1")
    r.add_argument("--port", type=int, required=True)
    r.add_argument("--header", help="a run header (JSON): its bridge items configure the bridge; the item flags are then refused")
    r.add_argument("--mode", choices=vb.MODES)
    r.add_argument("--profile", type=int)
    r.add_argument("--profile-source", choices=vb.PROFILE_SOURCES)
    r.add_argument("--vehicle")
    r.add_argument("--wheelbase-mm", type=int)
    r.add_argument("--demo-odd", metavar="START_S,DURATION_S")
    r.add_argument("--broker", default=DEFAULT_BROKER, help="the databroker: broker mode's source, and the write-back's target")
    r.add_argument("--writeback", choices=("on", "off"), default=None,
                   help="write replies to the databroker's Monitor branch (default: on in broker mode, off otherwise)")
    r.add_argument("--channel", default=None, help="can mode: the SocketCAN interface (default %s)" % DEFAULT_CHANNEL)
    r.add_argument("--log", default=None, help="replay mode: the candump file")
    r.add_argument("--dbc", default=None, help="can and replay modes: the DBC (default sdv/vss/slice.dbc)")
    r.add_argument("--seconds", type=float, default=None, help="run this long (SIGTERM or SIGINT ends it earlier; default: until one)")
    r.add_argument("--script", default=None, help="a script of control calls (JSON; vss_claim_bridge.py, SCRIPT)")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--name")
    g.add_argument("--out")
    r.add_argument("--lock", default=None, help="the scenario lock (default: SDV_SCENARIO_LOCK or %s; with "
                   "SDV_SCENARIO_LOCK_MUST_EXIST=1 no other path is taken)" % vb.DEFAULT_LOCK)
    r.add_argument("--gen", default=None, help="the generated contract's directory (default: SDV_GEN or sdv-out/gen)")
    c = sub.add_parser("check", help="import the adapters' modules, load the contract and the DBC, print what was found")
    c.add_argument("--dbc", default=None)
    c.add_argument("--gen", default=None)
    return ap


def config_of(a: argparse.Namespace, contract: Any) -> vb.Config:
    """The run items, as vss_claim_bridge.py's own run takes them: from --header, or from the item flags."""
    items = (a.mode, a.profile, a.profile_source, a.vehicle, a.wheelbase_mm, a.demo_odd)
    if a.header:
        if any(x is not None for x in items):
            raise BridgeError("--header gives the run items: --mode, --profile, --profile-source, --vehicle, --wheelbase-mm "
                              "and --demo-odd are refused with it")
        with open(a.header, encoding="utf-8") as f:
            return vb.Config.from_header(json.load(f), a.host, a.port, lock_path=a.lock)
    if any(x is None for x in items[:5]):
        raise BridgeError("without --header, give --mode, --profile, --profile-source, --vehicle and --wheelbase-mm")
    demo = None
    if a.demo_odd:
        start, dur = (float(x) for x in a.demo_odd.split(","))
        demo = {"profile_id": [int(r["id"]) for r in contract.PROFILES if "run_window_max_ms" in r][0], "start_s": start, "duration_s": dur}
    return vb.Config(host=a.host, port=a.port, mode=a.mode, profile_id=a.profile, profile_source=a.profile_source,
                     source_vehicle={"name": a.vehicle, "wheelbase_mm": a.wheelbase_mm}, demo_odd_window=demo, lock_path=a.lock)


def mode_options(a: argparse.Namespace, mode: str) -> argparse.Namespace:
    """Each mode's own flags, refused in the others; the defaults filled in."""
    wrong = []
    if mode != "can" and a.channel is not None:
        wrong.append("--channel is can mode's")
    if mode != "replay" and a.log is not None:
        wrong.append("--log is replay mode's")
    if mode == "broker" and a.dbc is not None:
        wrong.append("--dbc is can and replay modes'")
    if mode == "replay" and a.log is None:
        wrong.append("replay mode needs --log (the candump file)")
    if wrong:
        raise BridgeError("; ".join(wrong))
    o = argparse.Namespace(**vars(a))
    o.channel = a.channel or DEFAULT_CHANNEL
    o.dbc = a.dbc or str(SLICE_DBC)
    o.writeback = a.writeback or ("on" if mode == "broker" else "off")
    return o


def check(a: argparse.Namespace) -> int:
    """The container's smoke: every adapter's third-party module imports, and the contract and the DBC load."""
    import importlib.metadata as md

    import can
    import cantools
    import grpc
    from kuksa.val.v2 import val_pb2_grpc  # noqa: F401
    from kuksa_client.grpc import VSSClient  # noqa: F401
    contract = vf.load_contract(a.gen)
    dbc = Path(a.dbc) if a.dbc else SLICE_DBC
    dec = SlotDecoder(load_dbc(dbc, contract), contract)
    out = {"python": sys.version.split()[0],
           "modules": {"kuksa-client": md.version("kuksa-client"), "grpcio": grpc.__version__, "python-can": can.__version__,
                       "cantools": cantools.__version__},
           "contract": {"digest": "0x%08X" % contract.CATALOG_DIGEST, "sha256": vb.contract_sha256(contract),
                        "slot_paths": list(contract.SLOT_PATHS)},
           "dbc": {"path": str(dbc), "sha256": sha256_file(dbc), "frame_ids": ["0x%03X" % i for i in dec.frame_ids]},
           "writeback_paths": sorted(vb.writeback_paths(contract).values())}
    print(json.dumps(out, sort_keys=True))
    return 0


def main(argv: Optional[Sequence[str]] = None, env: Optional[Env] = None) -> int:
    a = _parser().parse_args(argv)
    if a.cmd == "check":
        try:
            return check(a)
        except (BridgeError, vf.ContractError, OSError, ImportError) as err:
            print("bridge_sources: check: %s" % err, file=sys.stderr)
            return 1
    env = env or Env()
    ending = vb.Ending()
    opened: Optional[Opened] = None
    try:
        script = vb.load_script_file(a.script)
        contract = vf.load_contract(a.gen)
        cfg = config_of(a, contract)
        tables, problems = vb.bind(cfg, contract)
        if problems or tables is None:
            raise BridgeError("refused to start: " + "; ".join(problems))
        opts = mode_options(a, cfg.mode)
        opened = open_source(cfg, contract, tables.profiles[cfg.profile_id].l_mm, opts, env)
        run_dir = vb.out_dir(a.name, a.out)
        bridge = vb.Bridge(cfg, opened.source, contract=contract, writeback_sink=opened.sink, run_dir=run_dir, on_end=ending.done.set,
                           script=script)
    except (BridgeError, vf.ContractError, OSError, ValueError) as err:
        if opened is not None:
            opened.source.close()
            opened.close_clients()
        print("bridge_sources: %s" % err, file=sys.stderr)
        return 2
    for rec in opened.records:
        rec = dict(rec)
        bridge.log.write(rec.pop("event"), **rec)
        if rec.get("note") == WHEELBASE_NOTE:
            print("bridge_sources: " + WHEELBASE_NOTE, file=sys.stderr, flush=True)
    opened.source.attach_log(bridge.log.write)
    ending.install()
    try:
        try:
            bridge.start()
        except BridgeError as err:
            bridge.log.close()
            bridge.replies.close()
            opened.source.close()
            opened.close_clients()
            print("bridge_sources: %s" % err, file=sys.stderr)
            return 2
        try:
            ending.wait(a.seconds)
            ending.log_to(bridge.log)
        finally:
            s = bridge.stop()
            opened.close_clients()
    finally:
        ending.restore()
    source = opened.source.stats()
    (run_dir / "source.json").write_text(json.dumps(source, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "identity": s["identity"], "ticks_identity": s["ticks_identity"],
                      "by_reason": s["by_reason"], "fatal": s["fatal"], "source": source}, sort_keys=True))
    ok = s["fatal"] is None and s["identity"]["holds"] and s["ticks_identity"]["holds"] and s["seq_partition"]["holds"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
