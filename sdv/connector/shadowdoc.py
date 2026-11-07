"""shadowdoc.py -- the `vss` reported document, its change rule, and the `config` report (sdv/connector; SDV Phase 4
WP2; prep gaps h, l; the report's status keys SDV Phase 6 WP2).

Standard library only.

THE `vss` DOCUMENT
    {"state": {"reported": {<path>: <value or null>, ...}}}
  One flat object: every allowlisted path that goes to the shadow (channel S) as a dotted key, in the frozen tuple's
  order, EVERY TIME. A shadow merges updates and null removes a key, so
    - a key that left the effective set is null in the next document, not left at its last value;
    - a path with no value is null;
    - a connection's first document clears whatever an earlier run left.
  Each document is whole, so a document the service refused or the uplink lost is made good by the next one.
  Values: a boolean stays a boolean, a number a number (envelope.number holds each to its catalogue datatype). The
  AppState leaves carry the fields of the app's validated record, all of them or, with no valid record, all null. A
  string leaf outside AppState is null: free text is a channel, and the AppState schema is the only place a string
  is held to an enum or a tight pattern.

THE CHANGE RULE
  changed(previous, current, ignore) is whether any key outside `ignore` differs. `ignore` is seq_keys(): the
  AppState leaves that fill the schema's `seq`. A heartbeat counter that alone moved drives no update (the schema's
  own recommendation); the document that some other change drives carries the counter as it then is. The connector
  adds the timing: no closer than limits.SHADOW_MIN_INTERVAL_S to the previous document, and one at stop.

THE `config` REPORT
    {"state": {"reported": {"rate_hz": 1, "paths": [...]}}}
    {"state": {"reported": {"rate_hz": 1, "paths": [...], "image_id": ..., "scenario": ..., "result": ...}}}
  The effective rate and path set, and, when the connector has a valid status record from the updater (status.py), the
  record's three keys as the record has them: the image that runs, the scenario last accepted and the latest outcome.
  Once the shadow shows a status (the connector reported one, or a get's answer holds one), a status that is gone or
  refused is reported as three nulls, which the service deletes.
  No desired value, no refused value, no echo of anything that was asked for.

THE GUARDS (the service's limits, aws-map A3.7; held here before anything is sent)
  reported() refuses (DocRefused) a document whose JSON is over limits.SHADOW_DOC_LIMIT_BYTES (8 KB; held on the
  whole payload, which is stricter than the state alone) or nests deeper than limits.SHADOW_DOC_MAX_DEPTH levels
  (8; objects and arrays both count, from the payload's own braces), or that is not JSON (a NaN).

Does not demonstrate: what the shadow service does with these documents (merging, the delta, a rejection): the tests'
fake shadow is our reading of its documentation.
"""
from __future__ import annotations

import json
from typing import Any, Dict, FrozenSet, Mapping, Optional, Sequence

import envelope
import limits
import status as statusrec


class DocRefused(ValueError):
    """A shadow document the guards refuse; it is not sent."""


def seq_keys(frozen: Any) -> FrozenSet[str]:
    """The AppState leaves whose change alone drives no `vss` update: the ones that fill `seq`."""
    return frozenset(leaf for leaf, prop in frozen.APPSTATE_FIELDS.items() if prop == "seq")


def vss_state(frozen: Any, effective: Sequence[str], values: Mapping[str, Any],
              records: Mapping[str, Optional[Mapping[str, Any]]]) -> Dict[str, Any]:
    """The reported state: every channel-S path of the frozen tuple, its value or None. `records` is {AppState
    sub-branch: its validated record}; a sub-branch with no record gives None for each of its leaves."""
    wanted = set(effective)
    state: Dict[str, Any] = {}
    for path in frozen.PATHS:
        if "S" not in frozen.CHANNELS[path]:
            continue
        value: Any = None
        if path in wanted:
            prop = frozen.APPSTATE_FIELDS.get(path)
            if prop is not None:
                record = records.get(path.rsplit(".", 1)[0])
                value = record.get(prop) if record is not None else None
            else:
                value = envelope.number(frozen.NODES[path][1], values.get(path))
        state[path] = value
    return state


def changed(previous: Mapping[str, Any], current: Mapping[str, Any], ignore: FrozenSet[str] = frozenset()) -> bool:
    """Whether a key outside `ignore` differs between two states (in value or in type: true is not 1)."""
    keys = (set(previous) | set(current)) - set(ignore)
    return any(type(previous.get(k)) is not type(current.get(k)) or previous.get(k) != current.get(k) for k in keys)


def config_state(rate_hz: int, effective: Sequence[str], status: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The `config` report's state: the rate and the path set, and the status record's three keys when `status` is given
    (the connector's own: a valid record, or three nulls that clear one)."""
    state: Dict[str, Any] = {"rate_hz": int(rate_hz), "paths": list(effective)}
    if status is not None:
        state.update((key, status[key]) for key in statusrec.KEYS)
    return state


def depth(obj: Any) -> int:
    """How many levels of objects and arrays `obj` nests: 0 for a scalar, 1 for an empty or flat container."""
    if isinstance(obj, dict):
        return 1 + max([depth(v) for v in obj.values()] or [0])
    if isinstance(obj, (list, tuple)):
        return 1 + max([depth(v) for v in obj] or [0])
    return 0


def reported(state: Mapping[str, Any]) -> bytes:
    """The update payload that reports `state`, or DocRefused."""
    doc = {"state": {"reported": dict(state)}}
    levels = depth(doc)
    if levels > limits.SHADOW_DOC_MAX_DEPTH:
        raise DocRefused("a shadow document of %d levels: the limit is %d levels" % (levels, limits.SHADOW_DOC_MAX_DEPTH))
    try:
        payload = json.dumps(doc, separators=(",", ":"), allow_nan=False).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise DocRefused("a shadow document that is not JSON (%s)" % type(exc).__name__) from None
    if len(payload) > limits.SHADOW_DOC_LIMIT_BYTES:
        raise DocRefused("a shadow document of %d bytes: the limit is %d" % (len(payload), limits.SHADOW_DOC_LIMIT_BYTES))
    return payload
