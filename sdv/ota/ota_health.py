"""ota_health.py -- the updater's health check of an app container it started (sdv/ota; SDV Phase 6 WP1).

Standard library only; the AppState validator and schema are the connector's
(sdv/connector/appstate.py, sdv/apps/hard-brake-hazard/appstate.schema.json), read from the tree and never changed.

THE CHECK (spec section 3 item 7; design values DEADLINE_S, BEATS and POLL_S, here and nowhere else)
  Every POLL_S the container's state is read first: anything but `running` fails at once (a container that exits, or
  that is gone). Then the app's eight AppState leaves are read from a source and put together into one record by the
  connector's own assembly (the leaf-to-property map comes from the schema's x-vss-leaf annotations, under
  Vehicle.DualVm.). A record counts only when it is valid against the AppState schema and its app, app_version and
  image_id are the started entry's name, version and config digest: a heartbeat of the old container, or the
  databroker's kept value of a dead one, carries another image_id and never counts. Counted records must rise in seq
  from one to the next: a read that repeats the last seq is the same heartbeat (its state is kept as the latest), and a
  seq that falls starts the count again from that record. The check passes as soon as BEATS records have counted and
  the last one's state is `running` (with the container still running at that read); it fails at DEADLINE_S.

  The source is any object with read(paths) -> {path: value or None}. The updater's is ota_kuksa.KuksaSource, the one
  module that imports kuksa-client; the tests use a fake one. The deadline is read between reads, so it holds only
  as far as each read returns: KuksaSource bounds every call (its RPC_TIMEOUT_S) and never calls when it connects,
  so the check ends within DEADLINE_S plus one read and one POLL_S.

Does not demonstrate: that the app is correct (a heartbeat is the app's own report of itself), that its inputs are
fresh beyond what its own `state` says, or any timing (the deadline is a bound, not a measurement).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

DEADLINE_S = 30.0       # a design value: thirty 1 s heartbeats' worth of room for the app's start and its first reads
BEATS = 3               # a design value: three rising heartbeats are a running loop, not one value left behind
POLL_S = 0.5            # half the heartbeat period, so no heartbeat is missed between two reads

REPO = Path(__file__).resolve().parents[2]
APPSTATE_PY = REPO / "sdv" / "connector" / "appstate.py"
SCHEMA_FILE = REPO / "sdv" / "apps" / "hard-brake-hazard" / "appstate.schema.json"
LEAF_ROOT = "Vehicle.DualVm."

_cache: Dict[str, Any] = {}


def appstate() -> Any:
    """The connector's AppState module, loaded from its file under a name of its own (no bytecode written)."""
    if "mod" not in _cache:
        spec = importlib.util.spec_from_file_location("ota_appstate", str(APPSTATE_PY))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        saved = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.dont_write_bytecode = saved
        _cache["mod"] = mod
    return _cache["mod"]


def schema() -> Dict[str, Any]:
    if "schema" not in _cache:
        _cache["schema"] = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    return _cache["schema"]


def leaf_fields(app: str) -> Tuple[str, Dict[str, str]]:
    """(the app's AppState branch, {leaf path: schema property}) from the schema's x-vss-leaf annotations."""
    sub = appstate().branch_name(app)
    branch = LEAF_ROOT + "AppState." + sub
    fields: Dict[str, str] = {}
    for prop, p in schema()["properties"].items():
        leaf = p["x-vss-leaf"].split(" ", 1)[0].replace("<App>", sub)
        fields[LEAF_ROOT + leaf] = prop
    return branch, fields


def check(source: Any, name: str, app_version: str, image_id: str, status: Callable[[], Optional[str]],
          clock: Callable[[], float], sleep: Callable[[float], None]) -> Tuple[bool, str, int]:
    """(passed, why, heartbeats counted) for the container just started from the entry (name, app_version, image_id)."""
    branch, fields = leaf_fields(name)
    paths = sorted(fields)
    mod, sch = appstate(), schema()
    t0 = clock()
    count, last_seq, last_state = 0, None, None
    source_errors = 0
    while True:
        state = status()
        if state != "running":
            return False, "the container is %s" % (state or "gone"), count
        try:
            values = source.read(paths)
        except Exception:  # noqa: BLE001 -- a source that cannot be read this time is a read with nothing in it
            values, source_errors = {}, source_errors + 1
        rec = mod.assemble(fields, branch, values)
        if not mod.validate(sch, rec) and rec["app"] == name and rec["app_version"] == app_version and rec["image_id"] == image_id:
            seq = rec["seq"]
            if last_seq is not None and seq > last_seq:
                count += 1
            elif last_seq is None or seq < last_seq:
                count = 1
            last_seq, last_state = seq, rec["state"]
        if count >= BEATS and last_state == "running":
            return True, "%d rising heartbeats of the started image, the last one running" % count, count
        if clock() - t0 >= DEADLINE_S:
            return False, ("no %d rising heartbeats of the started image ending in running within %g s (%d counted, last state %s%s)"
                           % (BEATS, DEADLINE_S, count, last_state, ", %d unreadable reads" % source_errors if source_errors else "")), count
        sleep(POLL_S)
