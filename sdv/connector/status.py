"""status.py -- the updater's status record, read (sdv/connector; SDV Phase 6 WP2; Phase 6 spec 2.4).

Standard library only. The one file the connector reads that it did not write: the
updater (sdv/ota, Phase 6 WP1) writes it, the stack mounts its directory read-only into the connector's container at
DEFAULT_STATUS_DIR, and `config` reported carries what it says (connector.py).

THE RECORD, version 1 (the version is in the path), exactly one JSON object of these three keys:

    {"image_id": "sha256:<64 hex>" or null, "scenario": "<name>" or null, "result": "applied" | "rolled-back" | "refused"}

    image_id   the config digest of the app container that ran when the record was written; null when none ran.
               The spool's form (spool.image_id_ok): sha256: and 64 lower-case hex digits, matched whole.
    scenario   the scenario last accepted, or null. The spool's form (spool.scenario_ok): 1 to 48 of a-z, 0-9 and '-',
               not starting with '-'; never a path.
    result     the outcome of the latest spool record the updater processed. No cause is ever in the record.

  The updater writes it compact, ASCII, keys in that order, by write-then-rename. This reader holds the content, not
  the layout: another key order or white space is the same object and is taken. MAX_BYTES, the bound of 256 bytes, is
  the record's own (spec 2.4), not a design value of the connector's: limits.py holds those.

read(directory) reads DIRECTORY/status.json and returns Status(record, why): the record (a dict of the three keys in
their order) and None, or None and why not, one of REASONS. A reason holds no value of what was read:
    missing        no file (or no directory): the updater has processed no record yet, or nothing runs here
    unreadable     no regular file can be read there (a directory, a FIFO, no permission)
    too-large      over MAX_BYTES (at most MAX_BYTES + 1 bytes are ever read)
    not-utf8       not UTF-8
    not-json       not one JSON value (nothing, half a document, two documents, a byte order mark)
    not-object     a JSON value that is no object
    duplicate-key  a key that comes twice, at any depth
    keys           not exactly the three keys
    image_id, scenario, result   that value outside the record's rules
It opens the file without waiting (a FIFO in its place is refused, never waited on), reads it once, and never raises.

Does not demonstrate: that the updater wrote what this reads (the tests write the records themselves; the contract
between the two is the integration stage's test), or that a record says what runs on the host (it is the updater's
own report).
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import spool

DEFAULT_STATUS_DIR = "/run/sdv-local/status/v1"
FILE = "status.json"
MAX_BYTES = 256
KEYS = ("image_id", "scenario", "result")
RESULTS = ("applied", "rolled-back", "refused")
MISSING = "missing"
REASONS = (MISSING, "unreadable", "too-large", "not-utf8", "not-json", "not-object", "duplicate-key", "keys", "image_id", "scenario",
           "result")


class Status(NamedTuple):
    record: Optional[Dict[str, Optional[str]]]          # the three keys in KEYS' order, or None
    why: Optional[str]                                  # None, or one of REASONS


class _Duplicate(ValueError):
    pass


def _no_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise _Duplicate()
        out[key] = value
    return out


def parse(data: bytes) -> Status:
    """The record in `data`, the bytes of a status file, or why not."""
    if len(data) > MAX_BYTES:
        return Status(None, "too-large")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return Status(None, "not-utf8")
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicates)
    except _Duplicate:
        return Status(None, "duplicate-key")
    except (ValueError, RecursionError):
        return Status(None, "not-json")
    if not isinstance(doc, dict):
        return Status(None, "not-object")
    if len(doc) != len(KEYS) or set(doc) != set(KEYS):
        return Status(None, "keys")
    if doc["image_id"] is not None and not spool.image_id_ok(doc["image_id"]):
        return Status(None, "image_id")
    if doc["scenario"] is not None and not spool.scenario_ok(doc["scenario"]):
        return Status(None, "scenario")
    if not isinstance(doc["result"], str) or doc["result"] not in RESULTS:
        return Status(None, "result")
    return Status({key: doc[key] for key in KEYS}, None)


def read(directory: Any) -> Status:
    """DIRECTORY/status.json, read once: Status(record, None), or Status(None, why)."""
    path = Path(directory) / FILE
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except (FileNotFoundError, NotADirectoryError):
        return Status(None, MISSING)
    except OSError:
        return Status(None, "unreadable")
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return Status(None, "unreadable")
        chunks: List[bytes] = []
        size = 0
        while size <= MAX_BYTES:
            chunk = os.read(fd, MAX_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    except OSError:
        return Status(None, "unreadable")
    finally:
        os.close(fd)
    return parse(b"".join(chunks))
