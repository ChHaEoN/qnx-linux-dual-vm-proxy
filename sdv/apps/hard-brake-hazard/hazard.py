"""hazard.py -- the hard-brake-hazard app's pure core: the decision, the AppState record, the log.

Standard library only, no I/O and no clock: app.py (the container's
entry point) feeds it events with their times and carries out the actions it returns, and the tests
drive it directly. Everything the app decides is decided here.

WHAT THE APP DOES
  It reads two signals of the local databroker, the signed longitudinal velocity v
  (Vehicle.DualVm.Motion.LongitudinalVelocity, m/s, positive forward) and the longitudinal
  acceleration a_x (Vehicle.Acceleration.Longitudinal, m/s^2, positive toward +X). The deceleration
  along the direction of travel is -a_x * sign(v) (the overlay's comment on Acceleration.Longitudinal:
  braking forward gives a negative a_x, braking in reverse a positive one; a standing vehicle, v = 0,
  does not brake). When it exceeds DECEL_ON_MPS2 the app asks for the hazard lights
  (Vehicle.Body.Lights.Hazard.IsSignaling = true); when it falls below DECEL_OFF_MPS2 it asks for them
  off. It decides only from two present, fresh, finite inputs.

  It also reads the Monitor branch, but only to display the last verdict in its own log: the
  display is a separate object whose only output is a log record. No decision, no AppState field and
  no lifecycle state reads it, its value or whether it is fresh or present (the AppState schema's
  hard rule; tests/test_sdv_stack.py drives this core with different Monitor histories and requires
  identical actions).

  Every heartbeat it publishes the AppState record (appstate.schema.json, version 1) as the eight
  leaves under Vehicle.DualVm.AppState.HardBrakeHazard, and nothing else: the actuation request is
  the app's only other write.

DESIGN VALUES (each with its reason)
  DECEL_ON_MPS2 = 4.0 m/s^2. The slice's trip script brakes ordinarily at up to 2.0 m/s^2 (sigsim's
    approach and reverse stop) and hard at the sigsim envelope's braking_max, 6.0 m/s^2. The
    midpoint leaves 2.0 m/s^2 on each side, three orders of magnitude above LongAccel's resolution
    in slice.dbc and float32 rounding in the databroker, so neither ever decides. Compared strictly:
    exactly 4.0 does not switch the lights on.
  DECEL_OFF_MPS2 = 3.0 m/s^2. Hysteresis: a deceleration hovering at the switch-on value cannot
    toggle the lights, and a hard stop that eases into ordinary braking (at most 2.0 here) still
    releases them. Compared strictly: exactly 3.0 keeps them on.
  INPUT_DEADLINE_S = 0.5 s. An input older than this on the app's own clock is stale: no decision is
    made from it, and the app reports itself degraded. Twenty-five periods of the dynamics message
    (20 ms in slice.dbc), so one late write never trips it, and half the heartbeat period, so a dead
    feed shows by the next heartbeat.
  HEARTBEAT_S = 1.0 s. The AppState schema's own period (its comment gives the reason).
  SUBSCRIBE_BUFFER = 100 messages. Asked of the databroker's v2 Subscribe, which drops the oldest
    buffered message when a subscriber falls behind (its default keeps only the latest): about a
    second of both inputs at their message rate. The app counts the updates it received, so a drop
    would show in its log.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

APP_NAME = "hard-brake-hazard"
APP_VERSION = "1.0.0"
SCHEMA_VERSION = 1

INPUT_V = "Vehicle.DualVm.Motion.LongitudinalVelocity"
INPUT_A = "Vehicle.Acceleration.Longitudinal"
INPUTS = (INPUT_V, INPUT_A)
HAZARD = "Vehicle.Body.Lights.Hazard.IsSignaling"
MONITOR_DISPLAY = ("Vehicle.DualVm.Monitor.VssClaim.Verdict", "Vehicle.DualVm.Monitor.VssClaim.Reason")

DECEL_ON_MPS2 = 4.0
DECEL_OFF_MPS2 = 3.0
INPUT_DEADLINE_S = 0.5
HEARTBEAT_S = 1.0
SUBSCRIBE_BUFFER = 100

LIFECYCLE = ("starting", "running", "degraded", "stopping")
ACTUATE_RESULTS = ("none", "ok", "unavailable", "error")


def app_branch(name: str) -> str:
    """The AppState sub-branch of an app: split the manifest name on '-', upper-case the first letter
    of each part, join (the overlay's rule: hard-brake-hazard -> HardBrakeHazard)."""
    return "Vehicle.DualVm.AppState." + "".join(p[:1].upper() + p[1:] for p in name.split("-"))


BRANCH = app_branch(APP_NAME)

# The schema property -> (leaf under BRANCH, VSS datatype), in the schema's `required` order. The leaf
# names are the schema's x-vss-leaf annotations; tests check both against appstate.schema.json and
# the generated catalogue.
LEAVES: Tuple[Tuple[str, str, str], ...] = (
    ("schema_version", "SchemaVersion", "uint8"),
    ("app", "App", "string"),
    ("app_version", "AppVersion", "string"),
    ("image_id", "ImageId", "string"),
    ("seq", "Seq", "uint32"),
    ("state", "State", "string"),
    ("hazard_requested", "IsHazardRequested", "boolean"),
    ("actuate_result", "ActuateResult", "string"),
)
LEAF_PATHS = tuple(BRANCH + "." + leaf for _p, leaf, _t in LEAVES)
WRITES = frozenset(LEAF_PATHS)          # every path the app publishes
ACTUATES = frozenset((HAZARD,))         # every actuator it requests


def sign(x: float) -> int:
    return 1 if x > 0.0 else (-1 if x < 0.0 else 0)


def deceleration(v: float, a_x: float) -> float:
    """Deceleration along the direction of travel, m/s^2: -a_x * sign(v); 0 at standstill."""
    s = sign(v)
    return 0.0 if s == 0 else -a_x * s


def decide(hazard_on: bool, decel: float) -> bool:
    """The hazard state after one evaluation: on above DECEL_ON_MPS2, off below DECEL_OFF_MPS2,
    unchanged in between (strict comparisons; a non-finite deceleration changes nothing)."""
    if not math.isfinite(decel):
        return hazard_on
    if not hazard_on and decel > DECEL_ON_MPS2:
        return True
    if hazard_on and decel < DECEL_OFF_MPS2:
        return False
    return hazard_on


# --- actions the shell carries out --------------------------------------------------------------

@dataclass(frozen=True)
class Actuate:
    """Request the hazard lights on or off."""
    value: bool
    path: str = HAZARD


@dataclass(frozen=True)
class Publish:
    """Write these (path, value, datatype) leaves, in order."""
    leaves: Tuple[Tuple[str, Any, str], ...]


@dataclass(frozen=True)
class Note:
    """One record for the app's own log (never written to the databroker)."""
    record: Dict[str, Any]


Action = Union[Actuate, Publish, Note]


class MonitorDisplay:
    """Holds the last Monitor values for the local display. Its only output is a log record; the
    App never reads it back."""

    def __init__(self) -> None:
        self._last: Dict[str, Any] = {}

    def update(self, path: str, value: Any) -> Note:
        self._last[path] = value
        shown = {p.rsplit(".", 1)[1]: self._last.get(p) for p in MONITOR_DISPLAY}
        return Note({"event": "monitor-display", "path": path, "value": value, "shown": shown,
                     "note": "display only; no verdict has been received"
                     if value is None else "display only"})


@dataclass
class _Input:
    value: Optional[float] = None
    t: Optional[float] = None
    count: int = 0


@dataclass
class App:
    """The app's state machine. Times are seconds on one monotonic clock chosen by the caller."""
    image_id: str
    app_version: str = APP_VERSION
    seq: int = 0
    subscribed: bool = False
    stopping: bool = False
    hazard_on: bool = False
    hazard_requested: bool = False
    actuate_result: str = "none"
    inputs: Dict[str, _Input] = field(default_factory=lambda: {p: _Input() for p in INPUTS})
    display: MonitorDisplay = field(default_factory=MonitorDisplay)

    def __post_init__(self) -> None:
        if not (isinstance(self.image_id, str) and len(self.image_id) == 71 and self.image_id.startswith("sha256:")
                and all(c in "0123456789abcdef" for c in self.image_id[7:])):
            raise ValueError("image_id must be sha256: and 64 lower-case hex digits (the AppState schema)")

    # -- events --------------------------------------------------------------------------------

    def on_subscribed(self, t: float) -> List[Action]:
        self.subscribed = True
        return [Note({"event": "subscribed", "inputs": list(INPUTS), "t": t})]

    def on_input(self, path: str, value: Any, t: float) -> List[Action]:
        if path not in self.inputs:
            raise ValueError("not an input of this app: %s" % path)
        if value is None:
            return []
        slot = self.inputs[path]
        slot.value, slot.t = float(value), t
        slot.count += 1
        out: List[Action] = [Note({"event": "input", "path": path, "value": slot.value, "t": t})]
        if not self._fresh(t):
            return out
        v, a = self.inputs[INPUT_V].value, self.inputs[INPUT_A].value
        assert v is not None and a is not None
        if not (math.isfinite(v) and math.isfinite(a)):
            return out
        decel = deceleration(v, a)
        new = decide(self.hazard_on, decel)
        if new != self.hazard_on:
            self.hazard_on = new
            self.hazard_requested = new
            out.append(Note({"event": "decision", "hazard": new, "v": v, "a": a, "decel": decel, "trigger": path, "t": t}))
            out.append(Actuate(new))
        return out

    def on_actuated(self, value: bool, result: str, t: float) -> List[Action]:
        if result not in ACTUATE_RESULTS or result == "none":
            raise ValueError("not an Actuate outcome: %r" % result)
        self.actuate_result = result
        return [Note({"event": "actuate", "value": value, "result": result, "t": t})]

    def on_monitor(self, path: str, value: Any, t: float) -> List[Action]:
        """Display only: the returned record is the sole effect."""
        note = self.display.update(path, value)
        note.record["t"] = t
        return [note]

    def on_heartbeat(self, t: float) -> List[Action]:
        self.seq += 1
        rec = self.record(t)
        leaves = tuple((BRANCH + "." + leaf, rec[prop], dt) for prop, leaf, dt in LEAVES)
        counts = {p: self.inputs[p].count for p in INPUTS}
        return [Publish(leaves), Note({"event": "heartbeat", "record": rec, "inputs_received": counts, "t": t})]

    def on_stop(self, t: float) -> List[Action]:
        self.stopping = True
        return self.on_heartbeat(t)

    # -- derived -------------------------------------------------------------------------------

    def _fresh(self, t: float) -> bool:
        for p in INPUTS:
            s = self.inputs[p]
            if s.value is None or s.t is None or t - s.t > INPUT_DEADLINE_S:
                return False
        return True

    def state(self, t: float) -> str:
        """Lifecycle state from the app's own process and its own inputs only."""
        if self.stopping:
            return "stopping"
        if not self.subscribed:
            return "starting"
        if not self._fresh(t) or self.actuate_result not in ("none", "ok"):
            return "degraded"
        return "running"

    def record(self, t: float) -> Dict[str, Any]:
        """The AppState record at the current seq."""
        if self.seq < 1:
            raise ValueError("no heartbeat yet: seq starts at 1")
        return {
            "schema_version": SCHEMA_VERSION,
            "app": APP_NAME,
            "app_version": self.app_version,
            "image_id": self.image_id,
            "seq": self.seq,
            "state": self.state(t),
            "hazard_requested": self.hazard_requested,
            "actuate_result": self.actuate_result,
        }
