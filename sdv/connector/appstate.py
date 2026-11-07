"""appstate.py -- AppState's field whitelist in the twin connector (sdv/connector; SDV Phase 4 WP1).

Standard library only; no file is written, nothing is sent.

WHAT IT IS
  An app writes its heartbeat and own state as leaves under its own sub-branch of the project's AppState branch
  (sdv/apps/hard-brake-hazard: eight leaves). Those leaves are on the twin allowlist, but never leaf by leaf: the
  connector forwards an app's state only as one record that passes all of this.

    assemble   the leaves of one app's sub-branch into one record, each leaf into the schema property the frozen
               allowlist's leaf-to-property map gives it (twin_allowlist.APPSTATE_FIELDS). Nothing else is read:
               a value under any other path, another app's sub-branch included, cannot reach the record. A leaf
               with no value yet leaves its property out, so the record fails as incomplete.
    validate   the record against the flat AppState schema (appstate.schema.json), with the keywords that schema
               uses: additionalProperties false, required, propertyNames (pattern, maxLength and the `not` pattern
               that makes a name such as last_verdict unusable), and per property type, const, enum, pattern,
               maxLength, minimum and maximum. This is the validator the stack's tests held the app's records to
               (tests/test_sdv_stack.py), moved here so the connector and those tests use one.
    derives    the record's `app` must derive the sub-branch the record came from, by the overlay's one rule:
               split the name on '-', upper-case the first letter of each part, join (hard-brake-hazard ->
               HardBrakeHazard). A record that names another app's sub-branch is dropped.
    checked    the three together: the record when it may be forwarded, else None and why. The reasons name
               properties and keywords, never a value: they go to a local log, and a refused value must not
               travel by way of its own refusal.

WHERE IT IS STRICTER THAN A PYTHON JSON SCHEMA VALIDATOR (tests/test_twin_allowlist.py holds both)
  - An integer property takes an int and never a float: JSON Schema's integer also takes 1.0, but the databroker
    hands an integer leaf over as an int, so a float there is something else.
  - A pattern is read as ECMA-262 reads it, which is what the schema's draft says a pattern is: `$` matches at the
    end of the input only. Python's `$` also matches before a trailing newline, so "1.0.0" followed by a newline
    would pass app_version's pattern under re.search unchanged.

Does not demonstrate: that an app cannot hide information in a permitted field (a boolean can carry one bit of
anything; the data-flow proof is the app's Monitor-independence test), that the connector calls this on every
record (WP2's egress test), or anything against a malicious Linux side.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


def load_schema(path: Any) -> Dict[str, Any]:
    """The AppState schema from its JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ecma(pattern: str) -> str:
    """The pattern with every `$` outside a character class and not escaped written as \\Z: the end of the input and
    nothing else, as ECMA-262 reads `$` without the multiline flag."""
    out: List[str] = []
    i, in_class = 0, False
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "$":
            c = "\\Z"
        out.append(c)
        i += 1
    return "".join(out)


def _search(pattern: str, text: str) -> bool:
    return re.search(ecma(pattern), text) is not None


def validate(schema: Mapping[str, Any], record: Mapping[str, Any]) -> List[str]:
    """Why `record` is not an AppState record: [] when it is one. A check of the flat schema with the keywords it
    uses; each finding is `<keyword> <property>`."""
    errs: List[str] = []
    props = schema["properties"]
    names = schema["propertyNames"]
    for k in record:
        if k not in props:
            errs.append("extra %s" % k)
        if not (isinstance(k, str) and _search(names["pattern"], k)) or len(k) > names["maxLength"] or _search(names["not"]["pattern"], k):
            errs.append("name %s" % k)
    for k in schema["required"]:
        if k not in record:
            errs.append("missing %s" % k)
    for k, v in record.items():
        p = props.get(k)
        if p is None:
            continue
        t = p.get("type")
        ok = {"integer": isinstance(v, int) and not isinstance(v, bool), "string": isinstance(v, str),
              "boolean": isinstance(v, bool)}.get(t, True)
        if not ok:
            errs.append("type %s" % k)
            continue
        if "const" in p and v != p["const"]:
            errs.append("const %s" % k)
        if "enum" in p and v not in p["enum"]:
            errs.append("enum %s" % k)
        if "pattern" in p and not _search(p["pattern"], v):
            errs.append("pattern %s" % k)
        if "maxLength" in p and len(v) > p["maxLength"]:
            errs.append("maxLength %s" % k)
        if "minimum" in p and v < p["minimum"] or "maximum" in p and v > p["maximum"]:
            errs.append("range %s" % k)
    return errs


def branch_name(app: str) -> str:
    """The sub-branch name an app's manifest name derives: split on '-', upper-case each part's first letter, join."""
    return "".join(part[:1].upper() + part[1:] for part in app.split("-"))


def derives(app: Any, branch: str) -> bool:
    """Whether `app` derives the sub-branch `branch` (a full path: <the AppState branch>.<App>)."""
    if not isinstance(app, str) or not app or "." not in branch:
        return False
    return branch.rsplit(".", 1)[1] == branch_name(app)


def assemble(fields: Mapping[str, str], branch: str, values: Mapping[str, Any]) -> Dict[str, Any]:
    """The record of the app whose sub-branch is `branch`: for each leaf directly under it that `fields` maps (leaf
    path -> property), the leaf's value under that property. A leaf that has no value (absent, or None) is left out.
    No other key of `values` is read."""
    record: Dict[str, Any] = {}
    for leaf, prop in fields.items():
        if leaf.rsplit(".", 1)[0] != branch:
            continue
        value = values.get(leaf)
        if value is not None:
            record[prop] = value
    return record


def checked(schema: Mapping[str, Any], fields: Mapping[str, str], branch: str,
            values: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """(the record, []) when the sub-branch's leaves give a record that validates and whose `app` derives `branch`;
    otherwise (None, the reasons), and the caller drops it and counts it in its local log."""
    record = assemble(fields, branch, values)
    problems = validate(schema, record)
    if not problems and not derives(record["app"], branch):
        problems.append("app does not derive the sub-branch the record came from")
    return (record, []) if not problems else (None, problems)
