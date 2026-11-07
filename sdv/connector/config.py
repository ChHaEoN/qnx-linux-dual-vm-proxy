"""config.py -- what the twin connector takes from the `config` shadow (sdv/connector; SDV Phase 4 WP2; prep gap l).

Standard library only.

The cloud writes desired state into the `config` named shadow; the device answers with reported state. This module
is what the device makes of a desired state. It sends nothing and writes nothing: the connector does both.

DESIRED, four keys (KEYS); every other key is ignored
    rate_hz    1 or 10, an integer. Anything else (5, "10", 10.0, true) is ignored.
    paths      a list of exact leaf paths: the effective set becomes the frozen allowlist's members that the list
               names (pathset.py: exact, case-sensitive membership; it can narrow, never widen). An entry that is no
               member is ignored; a value that is no list is ignored whole.
    image_id   a requested app image ID,   } for the spool and nowhere else (spool.py checks the form of each;
    scenario   a requested scenario name   } a value of the wrong form is ignored).

TWO KINDS OF DESIRED STATE
    the whole of it (the answer to the get at start): a key it does not name means the default, the rate of 1 Hz and
        the whole allowlist; a key it names with a value that is refused changes nothing.
    a delta: only what it names is looked at; what it does not name stays as it is.

"IGNORED" MEANS NO EFFECT AT ALL. An ignored value changes no setting, causes no publish, and is echoed nowhere: not
in `config` reported, not in the log. Outcome.ignored is a count, for the local counters; the strings stay here.

WHY THE CONNECTOR MUST NOT ANSWER EVERY DELTA. The service sends a delta after every accepted update, with every
desired attribute that still differs from reported. This connector reports the image ID and the scenario only as the
updater's status record has them (status.py: the image that runs, the scenario last accepted), never as desired asks
for them, and never a refused value; so a desired image ID or scenario that the status does not show (not applied yet,
refused, rolled back, or any while no updater writes a status) is in every delta from then on. apply() therefore says
whether the EFFECTIVE rate or path set changed (Outcome.changed), and the connector reports only on that and on a
changed status: a connector that answered each delta with a reported publish would be answered with the same delta
again, until the limiter stopped it.

parse() reads one message: at most limits.INBOUND_MAX_BYTES of UTF-8 JSON, one object; anything else is None.

Does not demonstrate: the shadow service's real replies (the tests' fake shadow is our reading of its documentation),
or that an image ID or a scenario written to the spool is ever acted on.
"""
from __future__ import annotations

import json
from typing import Any, Dict, NamedTuple, Optional, Sequence, Tuple

import limits
import pathset
import spool

KEYS = ("rate_hz", "paths", "image_id", "scenario")


class Outcome(NamedTuple):
    changed: bool                               # the effective rate or path set is not what it was
    rate_changed: bool
    paths_changed: bool
    spool: Optional[Dict[str, Optional[str]]]   # the spool record this desired state asks for, or None
    ignored: int                                # how many keys, values and path entries had no effect


def parse(payload: Any) -> Optional[Dict[str, Any]]:
    """The JSON object in one inbound message, or None when it is too large, not UTF-8, not JSON or not an object."""
    if not isinstance(payload, (bytes, bytearray)) or len(payload) > limits.INBOUND_MAX_BYTES:
        return None
    try:
        doc = json.loads(bytes(payload).decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    return doc if isinstance(doc, dict) else None


def version_of(doc: Dict[str, Any]) -> Optional[int]:
    """A shadow message's version, when it carries one."""
    version = doc.get("version")
    return version if isinstance(version, int) and not isinstance(version, bool) else None


class Config:
    """The effective settings, and what a desired state makes of them."""

    def __init__(self, frozen_paths: Sequence[str]) -> None:
        self._frozen: Tuple[str, ...] = tuple(frozen_paths)
        self.rate_hz: int = limits.DEFAULT_RATE_HZ
        self.paths: Tuple[str, ...] = self._frozen

    def apply(self, desired: Any, full: bool) -> Outcome:
        """Take one desired state: the whole of it (`full`) or a delta."""
        if not isinstance(desired, dict):
            return Outcome(False, False, False, None, 1)
        ignored = len([k for k in desired if k not in KEYS])
        rate, paths = self.rate_hz, self.paths

        value = desired.get("rate_hz")
        if value is None:
            if full:
                rate = limits.DEFAULT_RATE_HZ
        elif isinstance(value, int) and not isinstance(value, bool) and value in limits.RATES_HZ:
            rate = value
        else:
            ignored += 1

        value = desired.get("paths")
        if value is None:
            if full:
                paths = self._frozen
        elif isinstance(value, list):
            paths, skipped = pathset.narrow(self._frozen, value)
            ignored += skipped
        else:
            ignored += 1

        wanted: Dict[str, Optional[str]] = {"image_id": None, "scenario": None}
        for key, ok in (("image_id", spool.image_id_ok), ("scenario", spool.scenario_ok)):
            value = desired.get(key)
            if value is None:
                continue
            if ok(value):
                wanted[key] = value
            else:
                ignored += 1
        record = wanted if (wanted["image_id"] is not None or wanted["scenario"] is not None) else None

        rate_changed, paths_changed = rate != self.rate_hz, paths != self.paths
        self.rate_hz, self.paths = rate, paths
        return Outcome(rate_changed or paths_changed, rate_changed, paths_changed, record, ignored)
