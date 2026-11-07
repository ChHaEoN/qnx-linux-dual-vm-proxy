"""ota_manifest.py -- the per-host manifest's loader for the updater ota-lite (sdv/ota; SDV Phase 6 WP1).

Standard library only, so the updater runs on a host's Python with no package beyond
the health check's kuksa-client.

WHAT IT CHECKS (spec section 2.5, section 3 item 2; manifest-classes.md sections 3, 4 and 9)
  load(path, host_role, arch) refuses, before anything else, a manifest whose real path lies inside the repo (the
  manifest never enters the repo), then a file over MAX_BYTES, one that is not UTF-8 JSON, or that holds a duplicate
  key (the spool's rule: a parser that keeps the last duplicate would let a second value past a reader's eye). Then:
    schema   manifest.schema.json beside this file: manifest-classes section 9 with the spec's changes (the local-build
             pull carries store_id; the ecr ref names the placeholder <registry> and sdv-twin/<name>);
    cross    the checks the schema cannot express (manifest-classes:73-76): (name, image_id) unique; an image_id never
             in both classes; every allowed_scenarios name defined; at most one replay_source; host_role and arch the
             given ones; every source.rtf min <= mean <= max. And the loader's own, each because the updater selects
             or builds by them: an image_id names one container entry only (a spool record selects by image_id
             alone); scenario names unique (the hand-off maps a name to one recording); an ecr ref's repository is
             sdv-twin/<the entry's name> and its digest the entry's manifest_digest (spec 2.2); a path starting with
             '~' starts with '~/' ('~user' would name another account's home).
  Every finding names a place in the file and a rule, never a value from it.

validate(schema, instance) is a draft 2020-12 validator for the keywords that schema uses ($ref to #/$defs, type,
const, enum, pattern, maxLength, minimum, maximum, exclusiveMinimum, items, minItems, maxItems, uniqueItems,
required, properties, additionalProperties, maxProperties, allOf, anyOf, oneOf, not, if/then/else). Two places where
it is stricter than a Python JSON Schema validator, as sdv/connector/appstate.py is: an integer is an int and never a
float such as 1.0, and a pattern's `$` is ECMA-262's (the end of the input only, never before a trailing newline).
tests/test_sdv_ota.py holds it to jsonschema's validator on every case it has.

Does not demonstrate: that any listed image or recording exists or is what its digest says (the updater proves an
image after every pull or load and hashes a recording before every hand-off), or any secure OTA property.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

REPO = Path(__file__).resolve().parents[2]
SCHEMA_FILE = Path(__file__).resolve().with_name("manifest.schema.json")
MAX_BYTES = 1 << 20                 # a design bound: 64 components and 64 scenarios fit in a small fraction of it
ECR_REPO_PREFIX = "sdv-twin/"       # spec 2.2: a constant namespace with no names-file value in it

_DIGEST = re.compile(r"@(sha256:[0-9a-f]{64})\Z")


class ManifestRefused(ValueError):
    """The manifest fails a check: the updater refuses it and nothing runs."""

    def __init__(self, problems: List[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


class _Duplicate(Exception):
    pass


def _no_duplicates(pairs: List[Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise _Duplicate()
        out[k] = v
    return out


def inside(path: Any, root: Path = REPO) -> bool:
    """Whether the real path of `path` is `root` or lies under it (symbolic links followed)."""
    r, top = Path(path).expanduser().resolve(), Path(root).resolve()
    return r == top or top in r.parents


def load_schema() -> Dict[str, Any]:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


# --- the validator ---------------------------------------------------------------------------------------------------

def ecma(pattern: str) -> str:
    """The pattern with each `$` outside a character class and not escaped written as \\Z (ECMA-262's end of input)."""
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


_TYPES = {"string": str, "object": dict, "array": list, "boolean": bool}


def _type_ok(name: str, v: Any) -> bool:
    if name == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if name == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if name == "null":
        return v is None
    t = _TYPES.get(name)
    return t is not None and isinstance(v, t)


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return bool(a == b)


def _resolve(root: Mapping[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise ValueError("only local references are followed: %s" % ref)
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(schema: Any, instance: Any, root: Optional[Mapping[str, Any]] = None, at: str = "") -> List[str]:
    """Why `instance` fails `schema`: [] when it passes. Each finding is '<where>: <keyword>'."""
    root = schema if root is None else root
    where = at or "/"
    if schema is True:
        return []
    if schema is False:
        return ["%s: false" % where]
    errs: List[str] = []
    if "$ref" in schema:
        errs += validate(_resolve(root, schema["$ref"]), instance, root, at)
    if "type" in schema:
        types_ = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(t, instance) for t in types_):
            return errs + ["%s: type" % where]
    if "const" in schema and not _equal(instance, schema["const"]):
        errs.append("%s: const" % where)
    if "enum" in schema and not any(_equal(instance, e) for e in schema["enum"]):
        errs.append("%s: enum" % where)
    if isinstance(instance, str):
        if "pattern" in schema and re.search(ecma(schema["pattern"]), instance) is None:
            errs.append("%s: pattern" % where)
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errs.append("%s: maxLength" % where)
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append("%s: minimum" % where)
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append("%s: maximum" % where)
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errs.append("%s: exclusiveMinimum" % where)
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errs.append("%s: minItems" % where)
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errs.append("%s: maxItems" % where)
        if schema.get("uniqueItems"):
            seen = [json.dumps(x, sort_keys=True) for x in instance]
            if len(set(seen)) != len(seen):
                errs.append("%s: uniqueItems" % where)
        if "items" in schema:
            for i, item in enumerate(instance):
                errs += validate(schema["items"], item, root, "%s/%d" % (at, i))
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in instance:
                errs.append("%s: required %s" % (where, k))
        for k, v in instance.items():
            if k in props:
                errs += validate(props[k], v, root, "%s/%s" % (at, k))
            elif "additionalProperties" in schema:
                if schema["additionalProperties"] is False:
                    errs.append("%s: additionalProperties %s" % (where, k if re.fullmatch(r"[a-z_]{1,32}", k) else "(a key)"))
                else:
                    errs += validate(schema["additionalProperties"], v, root, "%s/%s" % (at, k))
        if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
            errs.append("%s: maxProperties" % where)
    for sub in schema.get("allOf", []):
        errs += validate(sub, instance, root, at)
    if "anyOf" in schema and not any(validate(s, instance, root, at) == [] for s in schema["anyOf"]):
        errs.append("%s: anyOf" % where)
    if "oneOf" in schema:
        n = sum(1 for s in schema["oneOf"] if validate(s, instance, root, at) == [])
        if n != 1:
            errs.append("%s: oneOf (%d of %d match)" % (where, n, len(schema["oneOf"])))
    if "not" in schema and validate(schema["not"], instance, root, at) == []:
        errs.append("%s: not" % where)
    if "if" in schema:
        branch = "then" if validate(schema["if"], instance, root, at) == [] else "else"
        if branch in schema:
            errs += validate(schema[branch], instance, root, at)
    return errs


# --- the loader ------------------------------------------------------------------------------------------------------

def parse(data: bytes) -> Any:
    """The manifest's JSON value; ManifestRefused when it is not UTF-8 JSON or holds a duplicate key."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ManifestRefused(["the manifest is not UTF-8"]) from None
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates)
    except _Duplicate:
        raise ManifestRefused(["the manifest holds a duplicate key"]) from None
    except ValueError:
        raise ManifestRefused(["the manifest is not JSON"]) from None


def _paths(m: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    for c in m["components"]:
        pull = c.get("pull") or {}
        if "tar_path" in pull:
            out.append(pull["tar_path"])
        out += [f["path"] for f in c.get("files", [])]
    for s in m["scenarios"]:
        out += [s["recording"]["path"], s["ownership"]["file"]]
    return out


def cross_problems(m: Mapping[str, Any], host_role: str, arch: str) -> List[str]:
    """The checks the schema cannot express, on a manifest that passed the schema."""
    out: List[str] = []
    if m["host_role"] != host_role:
        out.append("host_role is %s, the host's role is %s" % (m["host_role"], host_role))
    if m["arch"] != arch:
        out.append("arch is %s, the host's is %s" % (m["arch"], arch))
    containers = [(i, c) for i, c in enumerate(m["components"]) if c["form"] == "container"]
    pairs = [(c["name"], c["image_id"]) for _i, c in containers]
    if len(set(pairs)) != len(pairs):
        out.append("a (name, image_id) pair is listed twice")
    ids = [c["image_id"] for _i, c in containers]
    if len(set(ids)) != len(ids):
        out.append("an image_id names more than one container entry: a spool record selects by image_id alone")
    for img in sorted(set(ids)):
        if len({c["class"] for _i, c in containers if c["image_id"] == img}) > 1:
            out.append("an image_id appears in both classes")
    names = [s["name"] for s in m["scenarios"]]
    if len(set(names)) != len(names):
        out.append("a scenario name is defined twice")
    defined = set(names)
    for i, c in enumerate(m["components"]):
        for s in c.get("allowed_scenarios", []):
            if s not in defined:
                out.append("/components/%d/allowed_scenarios names a scenario the manifest does not define" % i)
                break
    if sum(1 for c in m["components"] if c.get("replay_source")) > 1:
        out.append("more than one replay_source")
    for i, s in enumerate(m["scenarios"]):
        rtf = s["source"].get("rtf")
        if rtf is not None and not rtf["min"] <= rtf["mean"] <= rtf["max"]:
            out.append("/scenarios/%d/source/rtf: min <= mean <= max does not hold" % i)
    for i, c in containers:
        pull = c["pull"]
        if pull["via"] == "ecr":
            path, _sep, _digest = pull["ref"].partition("/")[2].partition("@")
            if path != ECR_REPO_PREFIX + c["name"]:
                out.append("/components/%d/pull/ref: the repository is not %s<the entry's name>" % (i, ECR_REPO_PREFIX))
            mt = _DIGEST.search(pull["ref"])
            if mt is None or mt.group(1) != pull["manifest_digest"]:
                out.append("/components/%d/pull: manifest_digest is not the ref's digest" % i)
    if any(p.startswith("~") and not p.startswith("~/") for p in _paths(m)):
        out.append("a path starts with '~' but not with '~/' (another account's home)")
    return out


def check(m: Any, host_role: str, arch: str) -> List[str]:
    """Every reason the manifest is refused: [] when it passes the schema and the cross-entry checks."""
    problems = validate(load_schema(), m)
    if problems:
        return problems
    return cross_problems(m, host_role, arch)


def load(path: Any, host_role: str, arch: str) -> Dict[str, Any]:
    """The manifest at `path` for a host of this role and arch, or ManifestRefused."""
    p = Path(path).expanduser()
    if inside(p):
        raise ManifestRefused(["the manifest %s is inside the repo: it never enters the repo" % p])
    try:
        with open(str(p), "rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ManifestRefused(["the manifest cannot be read (%s)" % (exc.strerror or type(exc).__name__)]) from None
    if len(data) > MAX_BYTES:
        raise ManifestRefused(["the manifest is over %d bytes" % MAX_BYTES])
    m = parse(data)
    problems = check(m, host_role, arch)
    if problems:
        raise ManifestRefused(problems)
    return m


def container_entry(m: Mapping[str, Any], image_id: str) -> Optional[Dict[str, Any]]:
    """The container entry whose image_id this is, or None (the loader made it unique)."""
    for c in m["components"]:
        if c["form"] == "container" and c.get("image_id") == image_id:
            return c
    return None


def scenario_entry(m: Mapping[str, Any], name: str) -> Optional[Dict[str, Any]]:
    for s in m["scenarios"]:
        if s["name"] == name:
            return s
    return None


def app_entry(m: Mapping[str, Any], image_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The entry when this image_id is an app-class container entry, else None."""
    e = container_entry(m, image_id) if image_id else None
    return e if e is not None and e["class"] == "app" else None
