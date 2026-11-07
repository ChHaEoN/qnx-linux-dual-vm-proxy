"""spool.py -- the two-field spool record, the connector's one interface to the updater (sdv/connector; SDV Phase 4
WP2; prep gap m).

Local branch only (decision 15). Standard library only. One of the two files the connector ever writes; the other is
the stamp of its own last start, beside it (startstamp.py), which is no part of this interface.

The record is the design's (manifest-classes.md section 6): exactly two fields, the requested app image ID and the
requested scenario name. null means "leave as it is"; at least one is not null. There is no version key inside it:
the version is in the path.

    {"image_id": "sha256:<64 hex>" or null, "scenario": "<name>" or null}

    image_id   an image ID (a config digest): sha256: and 64 lower-case hex digits. Not a tag, not a repository.
    scenario   a name, never a path: 1 to 48 of lower-case letters, digits and '-', not starting with '-'. No '/',
               no backslash, no '.', no whitespace.
    Both are matched whole (a trailing newline is not part of a name: Python's `$` would let one through).

THE CONNECTOR CHECKS THE RECORD'S FORM ONLY. Whether the image ID is an app-class entry of the host's manifest,
whether the scenario is defined there and allowed for that image, and whether the scenario lock is held are the
updater's checks (Phase 6): neither the manifest nor the lock is mounted into the connector.

write() puts the record into DIRECTORY/desired.json by write-then-rename: the bytes go to a temporary name in the same
directory and are renamed over the file, so the updater never reads half a record. It writes nothing else, makes no
directory, reads nothing, and refuses a record whose form is wrong before it touches the file system. The record is desired state,
not a command: writing it twice changes nothing, and the last writer wins.

The file is at most limits.SPOOL_MAX_BYTES (256) bytes; the largest valid record is 148.

Does not demonstrate: that anything reads the spool (no updater exists before Phase 6), or that a requested image or
scenario is acted on, or refused.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import limits

FIELDS = ("image_id", "scenario")
FILE = "desired.json"
TMP = ".desired.json.tmp"

_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_SCENARIO = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")


class SpoolRefused(ValueError):
    """A record whose form is not the spool's; nothing is written."""


def image_id_ok(value: Any) -> bool:
    return isinstance(value, str) and _IMAGE_ID.fullmatch(value) is not None


def scenario_ok(value: Any) -> bool:
    return isinstance(value, str) and _SCENARIO.fullmatch(value) is not None


def problems(record: Any) -> List[str]:
    """Why `record` is not a spool record: [] when it is one. No finding repeats a value."""
    if not isinstance(record, dict) or len(record) != len(FIELDS) or set(record) != set(FIELDS):
        return ["the record's fields are not exactly the two of the spool"]
    out: List[str] = []
    if record["image_id"] is not None and not image_id_ok(record["image_id"]):
        out.append("image_id is not null or an image ID (sha256: and 64 lower-case hex digits)")
    if record["scenario"] is not None and not scenario_ok(record["scenario"]):
        out.append("scenario is not null or a scenario name (1 to 48 of a-z, 0-9 and '-', never a path)")
    if not out and record["image_id"] is None and record["scenario"] is None:
        out.append("both are null: the record asks for nothing")
    return out


def record(image_id: Optional[str], scenario: Optional[str]) -> Dict[str, Optional[str]]:
    """The record for these two values, or SpoolRefused."""
    rec: Dict[str, Optional[str]] = {"image_id": image_id, "scenario": scenario}
    found = problems(rec)
    if found:
        raise SpoolRefused("; ".join(found))
    return rec


def encode(rec: Any) -> bytes:
    """The file's bytes for a record of the right form, or SpoolRefused."""
    found = problems(rec)
    if found:
        raise SpoolRefused("; ".join(found))
    data = json.dumps({name: rec[name] for name in FIELDS}, separators=(",", ":")).encode("ascii")
    if len(data) > limits.SPOOL_MAX_BYTES:
        raise SpoolRefused("a record of %d bytes: the spool takes at most %d" % (len(data), limits.SPOOL_MAX_BYTES))
    return data


def write(directory: Any, rec: Any) -> Path:
    """Write the record to DIRECTORY/desired.json by write-then-rename. Refuses a wrong form before any file is
    touched; raises OSError when the directory cannot be written."""
    data = encode(rec)
    target = Path(directory) / FILE
    tmp = Path(directory) / TMP
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(target))
    return target
