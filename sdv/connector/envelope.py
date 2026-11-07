"""envelope.py -- the telemetry batch, version 1 (sdv/connector; SDV Phase 4 WP2; prep gap f).

Standard library only.

One batch is one JSON object, one publish to the Basic Ingest topic:

    {"v": 1, "batch": N, "paths": [...], "rows": [[t_ms, v, v, ...], ...], "appstate": [{...}]}

    v         1. (0 marks test traffic, which only the separate burst tool sends; queries filter on v = 1.)
    batch     a counter, from 1 in each connector process, one more for every batch that held something, sent or not:
              a gap in it is a batch the limiter refused or the uplink failed.
    paths     the telemetry paths of this batch, named once: the effective set's members that are telemetry (channel
              T), are not AppState leaves and hold a number or a boolean, in the frozen tuple's order.
    rows      one per sample, positional against `paths`: the sample time in Linux-host milliseconds (the
              connector's own wall clock at its tick), then one number per path. A boolean is 0 or 1. A path with no
              value at that tick is null. A row in which no path has a value is not made at all.
    appstate  at most one record per app: the latest one that validated while the batch was open (appstate.py). The
              AppState leaves never appear in `paths`: they go out as a whole record or not at all.

The envelope's only fields that are not VSS values are the version, the counter and the sample times. Nothing in it
comes from a log, a record directory or the claim path.

Rows are read against the batch's one header, so the connector closes and sends the open batch before a change of
the effective path set or of the rate takes effect: no batch mixes two row shapes.

A cell is a number or null, never anything else. cell() holds each value to its catalogue datatype: a boolean leaf
takes a bool; a float leaf a finite float (NaN and the infinities are not JSON), or an int a double holds exactly (up
to 2**53 either way: a larger one would print as a digit string of any length); an integer leaf an int inside its
datatype's range. A value of another type, a string leaf, or a datatype this file does not know gives null. So a
value the source should not have delivered cannot ride out in a row as free text, and none can raise.

It is a sampled view, not an event log: a change that begins and ends between two samples is not in it.

Does not demonstrate: that the rule, the stream and the table on the cloud side read this shape as intended (first
seen in the account), or that a value is right or timely.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

VERSION = 1
FIELDS = ("v", "batch", "paths", "rows", "appstate")

_INT_RANGE = {
    "int8": (-2 ** 7, 2 ** 7 - 1), "int16": (-2 ** 15, 2 ** 15 - 1), "int32": (-2 ** 31, 2 ** 31 - 1), "int64": (-2 ** 63, 2 ** 63 - 1),
    "uint8": (0, 2 ** 8 - 1), "uint16": (0, 2 ** 16 - 1), "uint32": (0, 2 ** 32 - 1), "uint64": (0, 2 ** 64 - 1),
}
_FLOATS = ("float", "double")
_EXACT_INT = 2 ** 53          # every int up to this, either way, is a double
NUMERIC = tuple(_INT_RANGE) + _FLOATS + ("boolean",)


def number(datatype: str, value: Any) -> Optional[Any]:
    """`value` when it is what a leaf of `datatype` holds (a bool, a finite number, an int in range); else None."""
    if datatype == "boolean":
        return value if isinstance(value, bool) else None
    if isinstance(value, bool):
        return None
    if datatype in _FLOATS:
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        return value if isinstance(value, int) and -_EXACT_INT <= value <= _EXACT_INT else None
    bounds = _INT_RANGE.get(datatype)
    if bounds is not None and isinstance(value, int) and bounds[0] <= value <= bounds[1]:
        return value
    return None


def cell(datatype: str, value: Any) -> Optional[Any]:
    """One row cell: the number, a boolean as 0 or 1, or None."""
    checked = number(datatype, value)
    if isinstance(checked, bool):
        return 1 if checked else 0
    return checked


def telemetry_paths(frozen: Any, effective: Sequence[str]) -> Tuple[str, ...]:
    """The columns of a batch under this effective set, in the frozen tuple's order."""
    wanted = set(effective)
    return tuple(p for p in frozen.PATHS
                 if p in wanted and "T" in frozen.CHANNELS[p] and p not in frozen.APPSTATE_FIELDS and frozen.NODES[p][1] in NUMERIC)


def row(t_ms: int, paths: Sequence[str], values: Mapping[str, Any], nodes: Mapping[str, Any]) -> List[Any]:
    """One sample: the time, then one cell per path."""
    return [int(t_ms)] + [cell(nodes[p][1], values.get(p)) for p in paths]


def has_value(sample: Sequence[Any]) -> bool:
    """Whether a row holds a value for any path."""
    return any(v is not None for v in sample[1:])


def batch(counter: int, paths: Sequence[str], rows: Sequence[Sequence[Any]], records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {"v": VERSION, "batch": int(counter), "paths": list(paths), "rows": [list(r) for r in rows],
            "appstate": [dict(r) for r in records]}


def encode(doc: Mapping[str, Any]) -> bytes:
    """Compact ASCII JSON. A NaN or an infinity anywhere raises ValueError: neither is JSON."""
    return json.dumps(doc, separators=(",", ":"), allow_nan=False).encode("ascii")
