#!/usr/bin/env python3
"""gen_allowlist.py -- check the twin allowlist's source list against the generated catalogue and write the frozen
module, or refuse (sdv/connector; SDV Phase 4 WP1).

Run it in WSL with the vss-tools venv's python, which has the YAML reader the id
file needs; everything else here is standard library.

    ~/sdv-venv/bin/python sdv/connector/gen_allowlist.py [--gen DIR] [--source FILE] [--schema FILE] [--out FILE]
    ~/sdv-venv/bin/python sdv/connector/gen_allowlist.py --check [--gen DIR] [--source FILE] [--schema FILE] [--out FILE]

Exit 0 when the module was written (or, with --check, when --out is byte for byte what the inputs generate); 1 on
any refusal, with every problem on stderr and nothing written; 2 on a usage error.

INPUTS
  --gen     the generated outputs' directory (default <repo>/sdv-out/gen). Its vss-ids.vspec is read: the id
            exporter's output of the one generation run (sdv/vss/generate.py), every node with its type, datatype,
            unit and staticUID.
  --source  twin_allowlist.json, the project-written source list: the exact leaves that may reach the cloud twin,
            each with its type, datatype, unit and channels (S: the `vss` named shadow; T: batched telemetry).
  --schema  appstate.schema.json, the AppState record's flat schema (sdv/apps/hard-brake-hazard). Each property's
            x-vss-leaf annotation names the leaf that fills it.
  The excluded branch is no input of the command line. It is attribution.MONITOR_PREFIX (sdv/stack/attribution.py)
  less its closing dot; ControlCommand is that node's sibling under the project branch.

OUTPUT
  --out     the frozen module (default <repo>/sdv-out/twin/twin_allowlist.py; sdv-out/ is ignored by git, and an
            --out elsewhere inside the repository is refused). It holds: the allowlist's version; the ordered path
            tuple; each path's staticUID; an FNV-1 32 digest over those UIDs as u32 little-endian in tuple order (the
            construction of the kind 4 catalogue digest); each path's node (type, datatype, unit) and channels; the
            AppState sub-branches and the leaf-to-property map; and the sha256 of the id file, the source list and
            the schema it was made from. A pure function of the three inputs: no timestamp, no path of the run. The
            module checks its own parts against each other when it is imported, so a careless hand edit does not
            import; a careful one is caught by --check, which is also what an image build runs before it bakes the
            module in. It is never mounted and never read from a file at run time.

WHY A SECOND STEP
  The plan lists the allowlist among the outputs of the one generation run. Writing it from generate.py would
  change that run's manifest, which the bridge image bakes in, and so move a pinned image ID though nothing the
  bridge runs changed (prep gap c). This step reads that run's id file instead and records its sha256.

REFUSALS (exit 1; each names its entry by its repr, so a blank shows)
  An entry that is not a node of the catalogue (an exact, case-sensitive match: nothing is trimmed, folded or
  otherwise normalised, because a normaliser is how a near-miss string becomes a hit); that is a branch; that holds
  a wildcard; whose type, datatype or unit differs from the catalogue's; that lies in the excluded branch (the node
  itself, or any node with it as an ancestor); that lies in ControlCommand (not on this allowlist version); that
  is listed twice; whose staticUID is malformed.
  The whole run: a source list of another shape, or with a key written twice in one object (json would keep the
  last and say nothing); an excluded prefix that is not <branch>.<node>. or that names no
  branch of the catalogue with a leaf under it (it would refuse nothing: a renamed branch must fail here, not
  pass); an AppState sub-branch that is listed in part, has a leaf no schema property names, or whose leaves differ
  from the schema's annotations in type, datatype or allowed values (a record is assembled from all the leaves of a
  sub-branch, or not at all); a digest of all zeros or all ones; an --out inside the tracked tree.

DOES NOT DEMONSTRATE. That a connector exists or sends only these paths: this checks the list, not a code path (a
connector that subscribed by branch would pass it). Nothing here holds against a malicious Linux side: the
allowlist stops honest mistakes and code-path bugs, not an attacker.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

FORMAT = 1

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ATTRIBUTION = REPO / "sdv" / "stack" / "attribution.py"
CATALOGUE_FILE = "vss-ids.vspec"
DEFAULT_GEN = REPO / "sdv-out" / "gen"
DEFAULT_SOURCE = HERE / "twin_allowlist.json"
DEFAULT_SCHEMA = REPO / "sdv" / "apps" / "hard-brake-hazard" / "appstate.schema.json"
DEFAULT_OUT = REPO / "sdv-out" / "twin" / "twin_allowlist.py"

CONTROL_BRANCH = "ControlCommand"          # Phase 8's branch under the project branch; not on allowlist v1
CHANNEL_SETS = (("S", "T"), ("S",), ("T",))
WILDCARDS = "*#+?"
SOURCE_KEYS = ("about", "entries", "version")
ENTRY_KEYS = ("channels", "datatype", "path", "type", "unit")
PREFIX_RE = re.compile(r"[A-Za-z0-9]+(\.[A-Za-z0-9]+)+\.")
UID_RE = re.compile(r"^0x[0-9A-F]{8}$")
FORBIDDEN_DIGESTS = (0x00000000, 0xFFFFFFFF)
FNV_OFFSET = 0x811C9DC5
FNV_PRIME = 0x01000193
# A schema property's leaf annotation: AppState.<App>.<Leaf> (<type>, <datatype>[, allowed: a, b, ...]).
LEAF_ANNOTATION = re.compile(r"^AppState\.<App>\.(\w+) \((\w+), (\w+)(?:, allowed: (.*))?\)$")


class Refusal(Exception):
    """Reasons to write nothing."""

    def __init__(self, problems: Any) -> None:
        self.problems: List[str] = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


# ================================================================ pure functions (no YAML, no file)

def fnv1_32(data: bytes) -> int:
    """FNV-1 32: multiply, then xor (not FNV-1a); the function vss-tools hashes staticUIDs with."""
    h = FNV_OFFSET
    for b in data:
        h = (h * FNV_PRIME) & 0xFFFFFFFF
        h ^= b
    return h


def digest_of(uids: Sequence[int]) -> int:
    """FNV-1 32 over the UIDs as u32 little-endian, in order (by shifts, never the host's byte order)."""
    out = bytearray()
    for u in uids:
        out += bytes(((u >> 0) & 0xFF, (u >> 8) & 0xFF, (u >> 16) & 0xFF, (u >> 24) & 0xFF))
    return fnv1_32(bytes(out))


def parse_uid(text: Any, path: str) -> int:
    if not isinstance(text, str) or not UID_RE.match(text):
        raise Refusal("%r: staticUID %r is malformed: expected exactly 0x followed by 8 upper-case hex digits" % (path, text))
    return int(text, 16)


def attribution() -> Any:
    """sdv/stack/attribution.py, loaded by its file for the excluded prefix (standard library only; no bytecode left)."""
    name = "_sdv_attribution_for_twin_allowlist"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(ATTRIBUTION))
    if spec is None or spec.loader is None:
        raise Refusal("cannot load %s" % ATTRIBUTION)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    sys.modules[name] = mod
    return mod


def excluded_nodes(attr: Any) -> Tuple[str, str]:
    """(the excluded node, the ControlCommand node): the node attribution.MONITOR_PREFIX names less its closing dot,
    and its sibling under the project branch. A prefix of any other form is refused: the generator would otherwise
    compare against a node no catalogue can hold."""
    prefix = getattr(attr, "MONITOR_PREFIX", None)
    if not isinstance(prefix, str) or not PREFIX_RE.fullmatch(prefix):
        raise Refusal("attribution.MONITOR_PREFIX is %r: expected <branch>.<node>. (a dotted node path and one closing dot)" % (prefix,))
    node = prefix[:-1]
    return node, node.rsplit(".", 1)[0] + "." + CONTROL_BRANCH


def lineage(path: str) -> List[str]:
    """The path's ancestors and the path itself, root first."""
    parts = path.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


def leaves_under(nodes: Mapping[str, Any], node: str) -> List[str]:
    """Every leaf of the catalogue that has `node` as an ancestor."""
    return sorted(p for p, n in nodes.items() if isinstance(n, dict) and n.get("type") != "branch" and node in lineage(p)[:-1])


def _object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """A JSON object of the source list. A key written twice is refused: json would keep the last and say nothing,
    and a reviewer would have read the first."""
    keys = [k for k, _v in pairs]
    twice = sorted({k for k in keys if keys.count(k) > 1})
    if twice:
        raise Refusal("the source list holds a key twice in one object: %s" % ", ".join(twice))
    return dict(pairs)


def parse_source(text: str) -> Dict[str, Any]:
    """The source list as written, or a Refusal that says what is wrong with its shape."""
    try:
        doc = json.loads(text, object_pairs_hook=_object)
    except ValueError as exc:
        raise Refusal("the source list is not JSON: %s" % exc) from None
    if not isinstance(doc, dict) or sorted(doc) != list(SOURCE_KEYS):
        raise Refusal("the source list holds exactly the keys about, entries and version, got %s"
                      % (sorted(doc) if isinstance(doc, dict) else type(doc).__name__))
    problems: List[str] = []
    if isinstance(doc["version"], bool) or not isinstance(doc["version"], int) or doc["version"] < 1:
        problems.append("version must be an integer of at least 1, got %r" % (doc["version"],))
    if not isinstance(doc["about"], str):
        problems.append("about must be a string")
    entries = doc["entries"]
    if not isinstance(entries, list):
        raise Refusal(problems + ["entries must be a list"])
    if not entries:
        problems.append("the source list holds no entry")
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or sorted(e) != list(ENTRY_KEYS):
            problems.append("entry %d holds exactly the keys channels, datatype, path, type and unit, got %s"
                            % (i, sorted(e) if isinstance(e, dict) else type(e).__name__))
            continue
        where = "entry %d (%r)" % (i, e["path"])
        if not isinstance(e["path"], str) or not e["path"]:
            problems.append("%s: path must be a non-empty string" % where)
        for key in ("type", "datatype"):
            if not isinstance(e[key], str) or not e[key]:
                problems.append("%s: %s must be a non-empty string, got %r" % (where, key, e[key]))
        if e["unit"] is not None and (not isinstance(e["unit"], str) or not e["unit"]):
            problems.append("%s: unit must be a string or null, got %r" % (where, e["unit"]))
        if not isinstance(e["channels"], list) or tuple(e["channels"]) not in CHANNEL_SETS:
            problems.append('%s: channels must be ["S", "T"], ["S"] or ["T"], got %r' % (where, e["channels"]))
    if problems:
        raise Refusal(problems)
    return doc


def entry_problems(entry: Mapping[str, Any], nodes: Mapping[str, Any], excluded: str, control: str) -> List[str]:
    """Why this entry may not be on the allowlist, each line naming it; [] when it may. The path is compared as
    written: no trimming, no case folding."""
    path = entry["path"]
    out: List[str] = []
    wild = sorted(set(path) & set(WILDCARDS))
    if wild:
        out.append("%r: holds a wildcard (%s); the allowlist holds exact leaves only" % (path, " ".join(wild)))
    line = lineage(path)
    if excluded in line:
        out.append("%r: lies in the excluded branch %s: nothing the QNX monitor produces goes to the cloud (S11)" % (path, excluded))
    if control in line:
        out.append("%r: lies in %s, which is not on this allowlist version: a %s leaf needs a new version and the owner's "
                   "review, leaf by leaf" % (path, control, CONTROL_BRANCH))
    node = nodes.get(path)
    if not isinstance(node, dict):
        out.append("%r: is not a node of the generated catalogue (an exact, case-sensitive match; nothing is normalised)" % path)
        return out
    if node.get("type") == "branch":
        out.append("%r: is a branch of the catalogue; the allowlist holds exact leaves only" % path)
        return out
    for key in ("type", "datatype", "unit"):
        if entry[key] != node.get(key):
            out.append("%r: %s %r in the source list, %r in the catalogue" % (path, key, entry[key], node.get(key)))
    return out


def list_problems(entries: Sequence[Mapping[str, Any]], nodes: Mapping[str, Any], excluded: str, control: str) -> List[str]:
    """Every entry's problems, and an entry listed twice."""
    out: List[str] = []
    seen: List[str] = []
    for e in entries:
        if e["path"] in seen:
            out.append("%r: is listed more than once" % e["path"])
            continue
        seen.append(e["path"])
        out += entry_problems(e, nodes, excluded, control)
    return out


def schema_leaves(schema: Any) -> Tuple[Dict[str, Tuple[str, str, str, Optional[List[str]]]], List[str]]:
    """{leaf name: (property, type, datatype, allowed)} from the schema's x-vss-leaf annotations, in `required` order."""
    problems: List[str] = []
    props = schema.get("properties") if isinstance(schema, dict) else None
    required = schema.get("required") if isinstance(schema, dict) else None
    if not isinstance(props, dict) or not isinstance(required, list) or sorted(required) != sorted(props):
        return {}, ["AppState schema: its required list is not its properties (every field is required)"]
    out: Dict[str, Tuple[str, str, str, Optional[List[str]]]] = {}
    for prop in required:
        ann = props[prop].get("x-vss-leaf") if isinstance(props[prop], dict) else None
        m = LEAF_ANNOTATION.match(ann) if isinstance(ann, str) else None
        if m is None:
            problems.append("AppState schema: property %s has no x-vss-leaf of the form 'AppState.<App>.<Leaf> (<type>, <datatype>"
                            "[, allowed: ...])', got %r" % (prop, ann))
            continue
        allowed = [s.strip() for s in m.group(4).split(",")] if m.group(4) else None
        if allowed != props[prop].get("enum"):
            problems.append("AppState schema: property %s's x-vss-leaf lists allowed %r, its enum is %r" % (prop, allowed, props[prop].get("enum")))
        if m.group(1) in out:
            problems.append("AppState schema: properties %s and %s both name the leaf %s" % (out[m.group(1)][0], prop, m.group(1)))
            continue
        out[m.group(1)] = (prop, m.group(2), m.group(3), allowed)
    return out, problems


def appstate_fields(entries: Sequence[Mapping[str, Any]], nodes: Mapping[str, Any], schema: Any,
                    appstate_prefix: str) -> Tuple[Tuple[str, ...], Dict[str, str], List[str]]:
    """(the AppState sub-branches the list names, {leaf path: schema property}, problems). The connector assembles a
    record from every leaf of an app's sub-branch, so a sub-branch is listed whole or not at all, each of its leaves
    is filled by exactly one schema property, and the catalogue's node agrees with that property's annotation."""
    problems: List[str] = []
    root = appstate_prefix[:-1]
    branches: List[str] = []
    listed: List[str] = []
    for e in entries:
        path = e["path"]
        if root not in lineage(path):
            continue
        parts = path[len(appstate_prefix):].split(".") if path.startswith(appstate_prefix) else []
        if len(parts) != 2:
            problems.append("%r: is not a leaf directly under an AppState sub-branch (AppState.<App>.<Leaf>): no record has such a field" % path)
            continue
        listed.append(path)
        if appstate_prefix + parts[0] not in branches:
            branches.append(appstate_prefix + parts[0])
    fields: Dict[str, str] = {}
    if not branches:
        return (), fields, problems
    by_leaf, schema_problems = schema_leaves(schema)
    problems += schema_problems
    for branch in branches:
        under = leaves_under(nodes, branch)
        for p in under:
            if p.rsplit(".", 1)[0] != branch:
                problems.append("%r: lies deeper than its AppState sub-branch %s: no record has such a field" % (p, branch))
            elif p not in listed:
                problems.append("%r: is not in the source list, and a record is assembled from every leaf of its AppState sub-branch "
                                "%s: a sub-branch is listed whole or not at all" % (p, branch))
            elif p.rsplit(".", 1)[1] not in by_leaf:
                problems.append("%r: has no schema property naming it (x-vss-leaf): nothing would fill a record's field from it" % p)
        for leaf, (prop, vtype, datatype, allowed) in by_leaf.items():
            path = branch + "." + leaf
            node = nodes.get(path)
            if not isinstance(node, dict) or node.get("type") == "branch":
                problems.append("AppState schema: property %s's x-vss-leaf names no leaf of %s (%s)" % (prop, branch, leaf))
                continue
            if (node.get("type"), node.get("datatype")) != (vtype, datatype):
                problems.append("%r: type %r, datatype %r in the catalogue; the schema's property %s says type %r, datatype %r"
                                % (path, node.get("type"), node.get("datatype"), prop, vtype, datatype))
            if node.get("allowed") != allowed:
                problems.append("%r: allowed %r in the catalogue, %r in the schema's property %s" % (path, node.get("allowed"), allowed, prop))
            if path in listed:
                fields[path] = prop
    return tuple(branches), fields, problems


def render(version: int, entries: Sequence[Mapping[str, Any]], uids: Sequence[int], digest: int, branches: Sequence[str],
           fields: Mapping[str, str], hashes: Mapping[str, Tuple[str, str]]) -> str:
    """The frozen module's text: a pure function of its arguments."""
    L: List[str] = []
    w = L.append
    w('"""twin_allowlist.py -- GENERATED by sdv/connector/gen_allowlist.py. Do not edit; never commit (sdv-out/ is ignored).')
    w("")
    w("The twin connector's frozen allowlist, version %d: the exact VSS leaves that may reach the cloud twin, each checked" % version)
    w("against the generated catalogue when this file was written (a leaf of the listed type, datatype and unit; no branch,")
    w("no wildcard; nothing of the branch the twin excludes). It is baked into the connector image at build time: never")
    w("mounted, never read from a file at run time. The cloud's `config` may narrow the set by exact, case-sensitive")
    w("membership in PATHS and can never widen it. The AppState leaves go out only as one record per app sub-branch that")
    w("validates against the AppState schema (sdv/connector/appstate.py), never leaf by leaf.")
    w("")
    w("Does not demonstrate: that a connector keeps to it, or anything against a malicious Linux side.")
    w('"""')
    w("")
    w("FORMAT = %d" % FORMAT)
    w("VERSION = %d" % version)
    w("")
    w("# What this module was made from: the sha256 of each input's bytes. An image build compares them with the files it")
    w("# stages (gen_allowlist.py --check) and refuses a stale module.")
    for label in ("CATALOGUE", "SOURCE", "SCHEMA"):
        w("%s_FILE = %r" % (label, hashes[label][0]))
        w("%s_SHA256 = %r" % (label, hashes[label][1]))
    w("")
    w("# The allowlisted leaves, in the source list's order, and each one's staticUID in the catalogue.")
    w("PATHS = (")
    for e in entries:
        w("    %r," % e["path"])
    w(")")
    w("STATIC_UIDS = (")
    for u in uids:
        w("    0x%08X," % u)
    w(")")
    w("# FNV-1 32 over the staticUIDs as u32 little-endian, in that order (the kind 4 catalogue digest's construction).")
    w("DIGEST = 0x%08X" % digest)
    w("")
    w("# Each leaf's type, datatype and unit, as the catalogue has them.")
    w("NODES = {")
    for e in entries:
        w("    %r: (%r, %r, %r)," % (e["path"], e["type"], e["datatype"], e["unit"]))
    w("}")
    w("")
    w("# Each leaf's channels: S = the `vss` named shadow (reported), T = batched telemetry.")
    w("CHANNELS = {")
    for e in entries:
        w("    %r: %r," % (e["path"], tuple(e["channels"])))
    w("}")
    w("")
    w("# The AppState whitelist's shape: each app's sub-branch, and for each of its leaves the schema property it fills.")
    w("APPSTATE_BRANCHES = (")
    for b in branches:
        w("    %r," % b)
    w(")")
    w("APPSTATE_FIELDS = {")
    for path, prop in fields.items():
        w("    %r: %r," % (path, prop))
    w("}")
    w("")
    w("")
    w("def _fnv1_32(data):")
    w("    h = 0x%08X" % FNV_OFFSET)
    w("    for b in data:")
    w("        h = ((h * 0x%08X) & 0xFFFFFFFF) ^ b" % FNV_PRIME)
    w("    return h")
    w("")
    w("")
    w("def _check():")
    w('    """Refuse to be imported hand-edited: the parts must agree with each other and with the digest. A careful edit')
    w('    passes this; gen_allowlist.py --check, which compares the file with a fresh generation, does not."""')
    w("    wire = b\"\".join(bytes(((u >> 0) & 0xFF, (u >> 8) & 0xFF, (u >> 16) & 0xFF, (u >> 24) & 0xFF)) for u in STATIC_UIDS)")
    w("    ok = (len(PATHS) == len(STATIC_UIDS) == len(set(PATHS)) == len(set(STATIC_UIDS)) > 0")
    w("          and all(isinstance(u, int) and 0 <= u <= 0xFFFFFFFF for u in STATIC_UIDS)")
    w("          and _fnv1_32(wire) == DIGEST")
    w("          and tuple(NODES) == PATHS and tuple(CHANNELS) == PATHS")
    w("          and all(c in ((\"S\", \"T\"), (\"S\",), (\"T\",)) for c in CHANNELS.values())")
    w("          and set(APPSTATE_FIELDS) <= set(PATHS)")
    w("          and sorted({p.rsplit(\".\", 1)[0] for p in APPSTATE_FIELDS}) == sorted(APPSTATE_BRANCHES))")
    w("    if not ok:")
    w("        raise ValueError(\"twin_allowlist.py: its paths, staticUIDs, digest, nodes, channels and AppState map do not agree: \"")
    w("                         \"a hand-edited module? It is generated by sdv/connector/gen_allowlist.py and never edited\")")
    w("")
    w("")
    w("_check()")
    w("")
    return "\n".join(L)


def generate(nodes: Mapping[str, Any], ids_bytes: bytes, source_bytes: bytes, schema_bytes: bytes, attr: Any) -> str:
    """The frozen module's text for these inputs, or a Refusal holding every problem. `attr` is attribution (its
    MONITOR_PREFIX and APPSTATE_PREFIX)."""
    excluded, control = excluded_nodes(attr)
    appstate_prefix = getattr(attr, "APPSTATE_PREFIX", None)
    if not isinstance(appstate_prefix, str) or not PREFIX_RE.fullmatch(appstate_prefix):
        raise Refusal("attribution.APPSTATE_PREFIX is %r: expected <branch>.<node>. (a dotted node path and one closing dot)" % (appstate_prefix,))
    if not isinstance(nodes, Mapping) or not nodes:
        raise Refusal("the id file holds no node")
    problems: List[str] = []
    ex = nodes.get(excluded)
    if not (isinstance(ex, dict) and ex.get("type") == "branch" and leaves_under(nodes, excluded)):
        problems.append("the excluded branch %s is not a branch of the generated catalogue with a leaf under it: nothing would be refused "
                        "(a renamed branch? attribution.MONITOR_PREFIX and the overlay must name the same node)" % excluded)
    try:
        doc = parse_source(source_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise Refusal("the source list is not UTF-8: %s" % exc) from None
    try:
        schema = json.loads(schema_bytes.decode("utf-8"))
    except ValueError as exc:
        raise Refusal("the AppState schema is not JSON: %s" % exc) from None
    entries = doc["entries"]
    problems += list_problems(entries, nodes, excluded, control)
    branches, fields, app_problems = appstate_fields(entries, nodes, schema, appstate_prefix)
    problems += [p for p in app_problems if p not in problems]
    uids: List[int] = []
    for e in entries:
        node = nodes.get(e["path"])
        if isinstance(node, dict) and node.get("type") != "branch":
            try:
                uids.append(parse_uid(node.get("staticUID"), e["path"]))
            except Refusal as r:
                problems += r.problems
    if problems:
        raise Refusal(problems)
    if len(set(uids)) != len(uids):
        raise Refusal("two entries share a staticUID")
    digest = digest_of(uids)
    if digest in FORBIDDEN_DIGESTS:
        raise Refusal("the allowlist digest is 0x%08X, which is forbidden (what an unset value would read as)" % digest)
    hashes = {"CATALOGUE": (CATALOGUE_FILE, hashlib.sha256(ids_bytes).hexdigest()),
              "SOURCE": (DEFAULT_SOURCE.name, hashlib.sha256(source_bytes).hexdigest()),
              "SCHEMA": (DEFAULT_SCHEMA.name, hashlib.sha256(schema_bytes).hexdigest())}
    return render(doc["version"], entries, uids, digest, branches, fields, hashes)


# ================================================================ I/O

def load_ids(data: bytes, where: Path) -> Dict[str, Any]:
    """The id file's nodes, {path: node}."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        raise Refusal("PyYAML is missing: run gen_allowlist.py with the vss-tools venv's python, ~/sdv-venv/bin/python "
                      "(sdv/vss/README.md)") from None
    try:
        nodes = yaml.load(data.decode("utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise Refusal("%s is not the id exporter's YAML: %s" % (where, str(exc)[:300])) from None
    if not isinstance(nodes, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in nodes.items()):
        raise Refusal("%s is not a mapping of node paths to nodes" % where)
    return nodes


def read_input(path: Path, what: str, hint: str) -> bytes:
    if not path.is_file():
        raise Refusal("%s %s is not there%s" % (what, path, hint))
    return path.read_bytes()


def inside_tracked_tree(path: Path) -> bool:
    """True when `path` lies in the repository other than under sdv-out/ (which git ignores as a whole): a generated
    module written there would be one commit away from the tree. Compared after resolving both."""
    p = path.expanduser().resolve()
    root = REPO.resolve()
    if p != root and root not in p.parents:
        return False
    ignored = root / "sdv-out"
    return not (p == ignored or ignored in p.parents)


def write_atomically(out: Path, data: bytes) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".%s." % out.name, dir=str(out.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def first_difference(a: bytes, b: bytes) -> int:
    """The 1-based number of the first line at which two texts differ."""
    la, lb = a.split(b"\n"), b.split(b"\n")
    for i, (x, y) in enumerate(zip(la, lb), 1):
        if x != y:
            return i
    return min(len(la), len(lb)) + 1


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="gen_allowlist.py", allow_abbrev=False,
                                 description="Check the twin allowlist's source list against the generated catalogue and write the "
                                             "frozen module, or refuse.")
    ap.add_argument("--gen", type=Path, default=DEFAULT_GEN,
                    help="the generated outputs' directory; its %s is read (default %%(default)s)" % CATALOGUE_FILE)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="the source list (default %(default)s)")
    ap.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="the AppState schema (default %(default)s)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the frozen module (default %(default)s)")
    ap.add_argument("--check", action="store_true", help="write nothing: exit 1 unless --out is byte for byte a fresh generation")
    return ap.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    a = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if not a.check and inside_tracked_tree(a.out):
            raise Refusal("--out %s is inside the repository: a generated module belongs under sdv-out/, which git ignores, "
                          "or outside the tree" % a.out)
        ids_path = a.gen / CATALOGUE_FILE
        ids_bytes = read_input(ids_path, "the id file", ": run sdv/vss/generate.py (sdv/vss/README.md)")
        source_bytes = read_input(a.source, "the source list", "")
        schema_bytes = read_input(a.schema, "the AppState schema", "")
        text = generate(load_ids(ids_bytes, ids_path), ids_bytes, source_bytes, schema_bytes, attribution())
    except Refusal as r:
        print("gen_allowlist.py: REFUSED: %d problem(s); nothing was written" % len(r.problems), file=sys.stderr)
        for p in r.problems:
            print("  " + p, file=sys.stderr)
        return 1
    data = text.encode("utf-8")
    version = re.search(r"^VERSION = (\d+)$", text, re.M)
    digest = re.search(r"^DIGEST = (0x[0-9A-F]{8})$", text, re.M)
    assert version is not None and digest is not None
    what = "allowlist v%s, %d paths, digest %s" % (version.group(1), len(re.findall(r"^    0x[0-9A-F]{8},$", text, re.M)), digest.group(1))
    if a.check:
        if not a.out.is_file():
            print("gen_allowlist.py: STALE: %s is missing; run gen_allowlist.py" % a.out, file=sys.stderr)
            return 1
        have = a.out.read_bytes()
        if have != data:
            print("gen_allowlist.py: STALE: %s differs from a fresh generation (first at line %d): it was edited, or an input "
                  "changed since it was written; run gen_allowlist.py" % (a.out, first_difference(have, data)), file=sys.stderr)
            return 1
        print("gen_allowlist.py: %s is a fresh generation (%s)" % (a.out, what))
        return 0
    write_atomically(a.out, data)
    print("gen_allowlist.py: %s" % what)
    print("gen_allowlist.py: wrote %s (%d bytes)" % (a.out, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
