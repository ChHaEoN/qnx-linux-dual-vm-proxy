"""The twin's frozen allowlist and the AppState whitelist (sdv/connector/twin_allowlist.json, gen_allowlist.py and
appstate.py; the generated sdv-out/twin/twin_allowlist.py): SDV Phase 4 WP1.

NO TEST IN THIS FILE MAY SKIP. The Phase 4 CI recipe fails the run when a test of this file was skipped or did not
run (tests/twin_gate.py's skip check). A test here that needs the generated catalogue, the vss-tools venv, the
pinned VSS archive or the frozen module asks tests/twin_gate.py for it: without SDV_REQUIRE_GEN=1 a missing input
skips the test, with it the test fails. A skipped exclusion proof must not read as a pass.

No path of the excluded branch is written in this file, in the source list or in the generator (the guard of
tests/test_sdv_vss.py reads every file named *allowlist*). The excluded prefix is attribution.MONITOR_PREFIX; the
leaves under it are enumerated from the generated catalogue; the test-only ControlCommand layer is built from the
same prefix's parent.

What is held (the ids are the design's, twin-allowlist.md section 7):
  * the enumeration is not empty by accident: the node MONITOR_PREFIX names is a branch of the generated catalogue,
    22 leaves lie under it, the same 22 in the databroker's JSON, and the bridge's own write set (from its module)
    and what the app reads for its display are non-empty and inside them. The generator takes the same node, and
    refuses to write at all when the catalogue carries no such branch (a renamed branch would otherwise make it
    refuse nothing);
  * A1: every source entry is a leaf of the generated catalogue with the listed type, datatype and unit, in the id
    file and in the databroker's JSON; none under the excluded branch or under ControlCommand; none a branch or a
    wildcard. The source list's set and version are attribution.ALLOWLIST_V1 and ALLOWLIST_VERSION;
  * A2: the generator exits non-zero, naming the entry, and writes nothing, for (a) each leaf of the excluded branch
    taken from the catalogue with the catalogue's own type, datatype and unit, (b) the project branch, the excluded
    branch and each of its sub-branches as entries, (c) a ControlCommand leaf, in a catalogue generated with a
    test-only layer loaded after the overlay, where the refusal is the ControlCommand rule and not "not in the
    catalogue", (d) a case or whitespace variant of an excluded leaf and of an allowlisted one, refused as not in
    the catalogue; and for each other rule: no such node, another type, datatype or unit, a wildcard, an entry
    listed twice, a source list of another shape, an AppState sub-branch listed in part;
  * A3: the frozen module equals a fresh generation byte for byte, holds what the plan lists (version, the ordered
    paths, their staticUIDs, the FNV-1 32 digest over them recomputed here, the channels, the AppState
    leaf-to-property map, the sha256 of its inputs) and nothing of the excluded branch; a hand-edited module with
    one extra path fails, both the careless edit (the module refuses to import) and the consistent one (it imports,
    and the comparison with a fresh generation fails);
  * A7's connector half: the connector's validator agrees with the schema (jsonschema's draft 2020-12 validator, in
    the vss venv) on the schema's example and on each seeded violation, and is stricter in two stated places; a
    record is assembled from the eight leaves of one sub-branch and from nothing else; a record whose `app` names
    another sub-branch is dropped;
  * A11: the largest `vss` reported document for allowlist v1 is under 4 KB, a design value (half the 8 KB shadow
    limit); its size is printed for WP5.

Every value here is a design value, a value of the generated contract or a synthetic fixture; none is a measurement.

Does not demonstrate: the connector's code path (WP2's egress test does), or anything against a malicious Linux
side: the allowlist and these tests stop honest mistakes, not an attacker.
"""
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CONNECTOR_DIR = REPO / "sdv" / "connector"
STACK_DIR = REPO / "sdv" / "stack"
APP_DIR = REPO / "sdv" / "apps" / "hard-brake-hazard"
BRIDGE_DIR = REPO / "sdv" / "bridge"
VSS_DIR = REPO / "sdv" / "vss"
GEN_FILE = CONNECTOR_DIR / "gen_allowlist.py"
SOURCE_FILE = CONNECTOR_DIR / "twin_allowlist.json"
APPSTATE_FILE = CONNECTOR_DIR / "appstate.py"
SCHEMA_FILE = APP_DIR / "appstate.schema.json"
FROZEN = REPO / "sdv-out" / "twin" / "twin_allowlist.py"
CACHE = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser()

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
for _d in (str(STACK_DIR), str(APP_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import attribution as attr  # noqa: E402
import hazard  # noqa: E402

sys.dont_write_bytecode = _saved

SCHEMA = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
EXAMPLE = SCHEMA["examples"][0]
EXCLUDED = attr.MONITOR_PREFIX[:-1]                    # the node the prefix names
PROJECT = EXCLUDED.rsplit(".", 1)[0]                   # the project branch, its parent
CONTROL = PROJECT + ".ControlCommand"                  # Phase 8's branch: not in the catalogue before it
CONTROL_LEAF = CONTROL + ".Velocity"                   # the test-only layer's one leaf (design A2, fixture c)
EXCLUDED_LEAVES_TODAY = 22                             # the two claim sub-branches, eleven leaves each
SHADOW_DOC_LIMIT = 4096                                # design value: half of the 8 KB shadow document limit
# The order of the design's table (twin-allowlist.md section 2): the signed velocity, the standard speed, the other
# four kind 4 slots, the hazard light's current value, the wheelbase, then the app's eight leaves in schema order.
TABLE_ORDER = ((attr.SLOT_PATHS[0], "Vehicle.Speed") + attr.SLOT_PATHS[1:] + (hazard.HAZARD, attr.WHEELBASE) + hazard.LEAF_PATHS)
APP_FIELDS = {hazard.BRANCH + "." + leaf: prop for prop, leaf, _dt in hazard.LEAVES}      # leaf path -> schema property


def _load(name: str, path: Path) -> Any:
    """A module by its file, no bytecode written beside it."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, path
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[name]
        raise
    finally:
        sys.dont_write_bytecode = saved
    return mod


def _fnv1_32(data: bytes) -> int:
    """FNV-1 32 written out again here, so the digest check does not lean on the generator's copy."""
    h = 0x811C9DC5
    for b in data:
        h = (h * 0x01000193) % (1 << 32)
        h ^= b
    return h


def _yaml_as_json(py: Path, path: Path) -> Dict[str, Any]:
    code = "import json, sys, yaml; json.dump(yaml.load(open(sys.argv[1], encoding='utf-8'), Loader=yaml.CSafeLoader), sys.stdout)"
    r = subprocess.run([str(py), "-B", "-c", code, str(path)], capture_output=True, text=True, check=True, timeout=300)
    return json.loads(r.stdout)


def _attr_with(prefix: Any) -> Any:
    """A stand-in for attribution with another excluded prefix (what a renamed branch would look like)."""
    return types.SimpleNamespace(MONITOR_PREFIX=prefix, APPSTATE_PREFIX=attr.APPSTATE_PREFIX)


def _under(nodes: Dict[str, Any], node: str) -> List[str]:
    """Every leaf of `nodes` that has `node` as an ancestor, by walking each path's own ancestors."""
    out = []
    for path, n in nodes.items():
        parts = path.split(".")
        if n.get("type") != "branch" and node in (".".join(parts[:i]) for i in range(1, len(parts))):
            out.append(path)
    return sorted(out)


# ============================================================ fixtures

@pytest.fixture(scope="module")
def gate() -> Any:
    return importlib.import_module("twin_gate")           # tests/twin_gate.py: pytest puts tests/ on sys.path


@pytest.fixture(scope="module")
def gen() -> Any:
    return _load("sdv_connector_gen_allowlist", GEN_FILE)


@pytest.fixture(scope="module")
def appstate() -> Any:
    return _load("sdv_connector_appstate", APPSTATE_FILE)


@pytest.fixture(scope="module")
def source() -> Dict[str, Any]:
    return json.loads(SOURCE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def venv_py(gate) -> Path:
    return gate.vss_venv()


@pytest.fixture(scope="module")
def gen_dir(gate) -> Path:
    return gate.catalogue("vss-ids.vspec", "vss-databroker.json", "vss_contract.py")


@pytest.fixture(scope="module")
def ids(gen_dir, venv_py) -> Dict[str, Any]:
    """The id file's nodes, {path: node}: the catalogue the generator reads."""
    return _yaml_as_json(venv_py, gen_dir / "vss-ids.vspec")


@pytest.fixture(scope="module")
def broker_leaves(gen_dir) -> Dict[str, Any]:
    """The leaves of the JSON the databroker loads."""
    return attr.leaf_nodes(json.loads((gen_dir / "vss-databroker.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def excluded_leaves(ids) -> List[str]:
    return _under(ids, EXCLUDED)


@pytest.fixture(scope="module")
def frozen_file(gate) -> Path:
    if not FROZEN.is_file():
        gate.missing("needs the frozen allowlist %s: ~/sdv-venv/bin/python sdv/connector/gen_allowlist.py "
                     "(sdv/connector/README.md)" % FROZEN)
    return FROZEN


@pytest.fixture(scope="module")
def frozen(frozen_file) -> Any:
    return _load("twin_allowlist_frozen_under_test", frozen_file)


@pytest.fixture(scope="module")
def ctl_dir(gate, gen_dir, venv_py, ids, tmp_path_factory) -> Path:
    """A catalogue generated with a test-only layer loaded after the overlay and the vehicle layer: the project
    branch's ControlCommand branch with one leaf, Velocity (sensor, float, m/s: a stock VSS 6.0 unit, so the stock
    unit and quantity files do). One id export by the pinned vss-tools, with generate.py's own arguments."""
    vss = _load("sdv_vss_generate_for_twin", VSS_DIR / "generate.py")
    archive = CACHE / vss.ARCHIVE_NAME
    if not archive.is_file():
        gate.missing("needs the pinned VSS archive %s (the first generation run fetches it; sdv/vss/README.md)" % archive)
    gate.catalogue(vss.VEHICLE_LAYER)
    work = tmp_path_factory.mktemp("twin-ctl")
    vss.verify_archive(archive)
    vss.extract_spec(archive, work)
    shutil.copyfile(VSS_DIR / "overlay.vspec", work / "overlay.vspec")
    shutil.copyfile(gen_dir / vss.VEHICLE_LAYER, work / vss.VEHICLE_LAYER)
    (work / "test-ctl.vspec").write_text(
        "%s:\n  type: branch\n  description: \"Test-only layer (twin allowlist A2, fixture c).\"\n\n"
        "%s:\n  type: sensor\n  datatype: float\n  unit: m/s\n  description: \"Test-only leaf.\"\n" % (CONTROL, CONTROL_LEAF),
        encoding="utf-8", newline="\n")
    rel = vss.ARCHIVE_ROOT + "/"
    cmd = ["export", "id", "-s", rel + "spec/VehicleSignalSpecification.vspec", "-u", rel + "spec/units.yaml",
           "-q", rel + "spec/quantities.yaml", "-l", "overlay.vspec", "-l", vss.VEHICLE_LAYER, "-l", "test-ctl.vspec"]
    for e in vss.EXTENDED_ATTRIBUTES:
        cmd += ["-e", e]
    out = work / "gen"
    out.mkdir()
    vss.run_vspec(venv_py.parent / "vspec", cmd + ["--strict", "-o", "gen/vss-ids.vspec"], work, "id export with the test-only layer")
    return out


def _cli(py: Path, *args: Any) -> subprocess.CompletedProcess:
    """gen_allowlist.py as the README runs it: in the vss venv, from the repo root."""
    return subprocess.run([str(py), "-B", str(GEN_FILE)] + [str(a) for a in args], cwd=str(REPO), capture_output=True,
                          text=True, timeout=300)


def _entry(path: str, node: Optional[Dict[str, Any]] = None, **over: Any) -> Dict[str, Any]:
    """A source-list entry for `path`, with the catalogue node's own type, datatype and unit when one is given."""
    node = node or {}
    e = {"path": path, "type": node.get("type", "sensor"), "datatype": node.get("datatype", "uint8"),
         "unit": node.get("unit"), "channels": ["S", "T"]}
    if e["type"] == "branch":
        e["type"] = "sensor"          # what a careless author would write for it
    e.update(over)
    return e


def _source_file(tmp_path: Path, source: Dict[str, Any], *extra: Dict[str, Any], drop: Sequence[str] = (),
                 name: str = "source.json") -> Path:
    doc = copy.deepcopy(source)
    doc["entries"] = [e for e in doc["entries"] if e["path"] not in drop] + [dict(e) for e in extra]
    p = tmp_path / name
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    return p


def _named(stderr: str, path: str, reason: str) -> List[str]:
    """The refusal's lines that name this entry (by its repr, so a whitespace variant shows) and give this reason."""
    return [ln for ln in stderr.splitlines() if ln.startswith("  %r: " % path) and reason in ln]


def _refused(py: Path, gen_dir: Path, tmp_path: Path, src: Path, path: str, reason: str) -> str:
    """One generator run on `src`: exit 1, the entry named with `reason`, and nothing written."""
    out = tmp_path / "out" / "twin_allowlist.py"
    r = _cli(py, "--gen", gen_dir, "--source", src, "--out", out)
    assert r.returncode == 1, (path, r.returncode, r.stdout, r.stderr)
    assert "REFUSED" in r.stderr and "nothing was written" in r.stderr, r.stderr
    assert _named(r.stderr, path, reason), (path, reason, r.stderr)
    assert not out.exists() and not out.parent.exists(), "a refused run wrote %s" % out
    return r.stderr


EXCLUDED_RULE = "the excluded branch"
CONTROL_RULE = "is not on this allowlist version"
NO_NODE = "is not a node of the generated catalogue"
BRANCH_RULE = "is a branch of the catalogue"
WILDCARD_RULE = "holds a wildcard"


# ============================================================ the enumeration is not empty by accident

def test_the_excluded_enumeration_is_the_catalogues_branch_and_holds_the_bridges_write_set(gate, gen, gen_dir, ids, broker_leaves,
                                                                                         excluded_leaves):
    """Prep gap d. MONITOR_PREFIX is a literal where the design wants node ancestry: if the overlay renamed the
    branch, the generator would refuse nothing and these tests would plant no canary. This fails instead."""
    assert attr.MONITOR_PREFIX.endswith(".") and attr.MONITOR_PREFIX.count(".") == 3 and not attr.MONITOR_PREFIX.endswith("..")
    assert EXCLUDED in ids and ids[EXCLUDED]["type"] == "branch", "the node MONITOR_PREFIX names is not a branch of the catalogue"
    assert PROJECT in ids and ids[PROJECT]["type"] == "branch"
    assert len(excluded_leaves) == EXCLUDED_LEAVES_TODAY
    assert excluded_leaves == sorted(p for p in ids if p.startswith(attr.MONITOR_PREFIX) and ids[p]["type"] != "branch")
    assert excluded_leaves == sorted(p for p in broker_leaves if p.startswith(attr.MONITOR_PREFIX))      # the databroker's file agrees
    # The bridge's own write set, from its module (the design's A9(b) takes it there), on the generated contract.
    bridge = _load("sdv_bridge_core_for_twin", BRIDGE_DIR / "vss_claim_bridge.py")
    contract = _load("sdv_vss_contract_for_twin", gen_dir / "vss_contract.py")
    assert contract.PROJECT_BRANCH == PROJECT
    writes = sorted(bridge.writeback_paths(contract).values())
    assert len(writes) == len(bridge.WRITEBACK_LEAVES) == 11 and set(writes) <= set(excluded_leaves)
    assert hazard.MONITOR_DISPLAY and set(hazard.MONITOR_DISPLAY) <= set(writes)          # what the app reads for its display
    # The generator excludes this node and enumerates the same leaves.
    assert gen.excluded_nodes(attr) == (EXCLUDED, CONTROL)
    assert gen.leaves_under(ids, EXCLUDED) == excluded_leaves
    assert CONTROL not in ids and not gen.leaves_under(ids, CONTROL)          # Phase 8's layer is not loaded


def test_the_generator_writes_nothing_when_the_catalogue_carries_no_such_branch(gen, ids, source):
    """A prefix that names no branch of the catalogue would exclude nothing: the generator refuses the whole run."""
    renamed = _attr_with(PROJECT + ".Renamed.")
    with pytest.raises(gen.Refusal) as exc:
        gen.generate(ids, b"ids", SOURCE_FILE.read_bytes(), SCHEMA_FILE.read_bytes(), renamed)
    assert any("is not a branch of the generated catalogue" in p and "nothing would be refused" in p for p in exc.value.problems)
    stripped = {p: n for p, n in ids.items() if p != EXCLUDED and not p.startswith(attr.MONITOR_PREFIX)}
    with pytest.raises(gen.Refusal) as exc:
        gen.generate(stripped, b"ids", SOURCE_FILE.read_bytes(), SCHEMA_FILE.read_bytes(), attr)
    assert any("nothing would be refused" in p for p in exc.value.problems)
    leafless = dict(stripped, **{EXCLUDED: ids[EXCLUDED]})          # the branch alone, with no leaf under it
    with pytest.raises(gen.Refusal) as exc:
        gen.generate(leafless, b"ids", SOURCE_FILE.read_bytes(), SCHEMA_FILE.read_bytes(), attr)
    assert any("nothing would be refused" in p for p in exc.value.problems)
    for bad in (PROJECT, EXCLUDED, "Renamed.", ".", "", PROJECT + "..", " " + attr.MONITOR_PREFIX, attr.MONITOR_PREFIX + " ", None):
        with pytest.raises(gen.Refusal):          # a prefix that is not <branch>.<node>. exactly
            gen.excluded_nodes(_attr_with(bad))


# ============================================================ A1 and the source list

def test_the_source_lists_set_and_version_are_attributions_allowlist_v1(source):
    assert sorted(source) == ["about", "entries", "version"]
    assert source["version"] == attr.ALLOWLIST_VERSION == 1
    paths = [e["path"] for e in source["entries"]]
    assert len(paths) == 16 == len(set(paths)) and set(paths) == attr.ALLOWLIST_V1
    assert tuple(paths) == TABLE_ORDER
    for e in source["entries"]:
        assert sorted(e) == ["channels", "datatype", "path", "type", "unit"], e
    channels = {e["path"]: e["channels"] for e in source["entries"]}
    assert channels.pop(attr.WHEELBASE) == ["S"]          # an attribute: the shadow only, never telemetry
    assert all(c == ["S", "T"] for c in channels.values())
    assert "project-written" in source["about"].lower() and "gen_allowlist.py" in source["about"]


def test_a1_every_source_entry_is_a_catalogue_leaf_of_the_listed_type_datatype_and_unit(gen, source, ids, broker_leaves):
    for e in source["entries"]:
        path = e["path"]
        assert path in ids and ids[path]["type"] != "branch", path
        for nodes in (ids, broker_leaves):          # the id file the generator reads, and the JSON the databroker loads
            node = nodes[path]
            assert (e["type"], e["datatype"], e["unit"]) == (node["type"], node["datatype"], node.get("unit")), path
        parts = path.split(".")
        ancestors = [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
        assert EXCLUDED not in ancestors and CONTROL not in ancestors, path
        assert all(ids[a]["type"] == "branch" for a in ancestors[:-1]), path          # node ancestry, not only a string
        assert re.fullmatch(r"[A-Za-z0-9]+(\.[A-Za-z0-9]+)+", path), path          # no wildcard, no blank, exact
    assert gen.list_problems(source["entries"], ids, EXCLUDED, CONTROL) == []
    types = {e["path"]: (e["type"], e["datatype"], e["unit"]) for e in source["entries"]}
    assert types[hazard.HAZARD] == ("actuator", "boolean", None) and types[attr.WHEELBASE] == ("attribute", "uint16", "mm")
    assert [types[p][1] for p in hazard.LEAF_PATHS] == [dt for _prop, _leaf, dt in hazard.LEAVES]
    assert all(types[p][0] == "sensor" for p in TABLE_ORDER if p not in (hazard.HAZARD, attr.WHEELBASE))


# ============================================================ A2: what the generator refuses

def test_a2a_the_generator_refuses_every_leaf_of_the_excluded_branch_taken_from_the_catalogue(gen, venv_py, gen_dir, ids, source,
                                                                                            excluded_leaves, tmp_path):
    assert len(excluded_leaves) == EXCLUDED_LEAVES_TODAY          # a loop over nothing would prove nothing
    for i, leaf in enumerate(excluded_leaves):
        e = _entry(leaf, ids[leaf])          # the catalogue's own type, datatype and unit: only the branch rule can refuse it
        problems = gen.entry_problems(e, ids, EXCLUDED, CONTROL)
        assert len(problems) == 1 and problems[0].startswith("%r: " % leaf) and EXCLUDED_RULE in problems[0], (leaf, problems)
        d = tmp_path / ("leaf-%d" % i)
        d.mkdir()
        err = _refused(venv_py, gen_dir, d, _source_file(d, source, e), leaf, EXCLUDED_RULE)
        assert NO_NODE not in err and "REFUSED: 1 problem(s)" in err, err
    # All of them at once: each is named.
    d = tmp_path / "all"
    d.mkdir()
    out = d / "out" / "twin_allowlist.py"
    r = _cli(venv_py, "--gen", gen_dir, "--source", _source_file(d, source, *[_entry(p, ids[p]) for p in excluded_leaves]), "--out", out)
    assert r.returncode == 1 and not out.exists(), r.stderr
    assert all(_named(r.stderr, p, EXCLUDED_RULE) for p in excluded_leaves), r.stderr
    assert "REFUSED: %d problem(s)" % EXCLUDED_LEAVES_TODAY in r.stderr, r.stderr
    # And alone, with no allowed entry beside it.
    d = tmp_path / "alone"
    d.mkdir()
    only = _source_file(d, dict(source, entries=[]), _entry(excluded_leaves[0], ids[excluded_leaves[0]]))
    _refused(venv_py, gen_dir, d, only, excluded_leaves[0], EXCLUDED_RULE)


def test_a2b_the_generator_refuses_the_project_branch_and_the_excluded_branch_as_entries(venv_py, gen_dir, ids, source, tmp_path):
    sub_branches = sorted(p for p in ids if p.startswith(attr.MONITOR_PREFIX) and ids[p]["type"] == "branch")
    assert len(sub_branches) == 2
    appstate_branch = attr.APPSTATE_PREFIX[:-1]
    for i, (branch, also) in enumerate([(PROJECT, None), (EXCLUDED, EXCLUDED_RULE)] + [(b, EXCLUDED_RULE) for b in sub_branches]
                                       + [(appstate_branch, None), (hazard.BRANCH, None), ("Vehicle", None)]):
        assert ids[branch]["type"] == "branch"
        d = tmp_path / ("branch-%d" % i)
        d.mkdir()
        err = _refused(venv_py, gen_dir, d, _source_file(d, source, _entry(branch, ids[branch])), branch, BRANCH_RULE)
        assert bool(_named(err, branch, EXCLUDED_RULE)) == (also is not None), (branch, err)


def test_a2c_the_generator_refuses_a_controlcommand_leaf_by_its_own_rule(gen, venv_py, gen_dir, ctl_dir, ids, source, tmp_path):
    ctl = _yaml_as_json(venv_py, ctl_dir / "vss-ids.vspec")
    # The fixture is the generated catalogue plus the test-only layer's two nodes, nothing else moved.
    assert sorted(set(ctl) - set(ids)) == [CONTROL, CONTROL_LEAF] and not set(ids) - set(ctl)
    assert all(ctl[p] == ids[p] for p in ids)
    assert ctl[CONTROL]["type"] == "branch"
    assert (ctl[CONTROL_LEAF]["type"], ctl[CONTROL_LEAF]["datatype"], ctl[CONTROL_LEAF]["unit"]) == ("sensor", "float", "m/s")
    e = _entry(CONTROL_LEAF, ctl[CONTROL_LEAF])          # the layer's own type, datatype and unit: only the rule can refuse it
    problems = gen.entry_problems(e, ctl, EXCLUDED, CONTROL)
    assert len(problems) == 1 and problems[0].startswith("%r: " % CONTROL_LEAF) and CONTROL_RULE in problems[0], problems
    err = _refused(venv_py, ctl_dir, tmp_path, _source_file(tmp_path, source, e), CONTROL_LEAF, CONTROL_RULE)
    assert NO_NODE not in err and "REFUSED: 1 problem(s)" in err, err          # the ControlCommand rule, not merely "not in the catalogue"
    # The branch itself is refused too, as a branch and by the rule.
    d = tmp_path / "branch"
    d.mkdir()
    err = _refused(venv_py, ctl_dir, d, _source_file(d, source, _entry(CONTROL, ctl[CONTROL])), CONTROL, CONTROL_RULE)
    assert _named(err, CONTROL, BRANCH_RULE)
    # Control: on that catalogue the unchanged source list generates, and gives the module the real catalogue gives
    # but for the catalogue's sha256 (the layer added two nodes and moved none).
    out = tmp_path / "ok" / "twin_allowlist.py"
    r = _cli(venv_py, "--gen", ctl_dir, "--out", out)
    assert r.returncode == 0 and out.is_file(), r.stderr
    real = tmp_path / "real" / "twin_allowlist.py"
    assert _cli(venv_py, "--gen", gen_dir, "--out", real).returncode == 0
    differing = [(a, b) for a, b in zip(out.read_text(encoding="utf-8").splitlines(), real.read_text(encoding="utf-8").splitlines()) if a != b]
    assert len(differing) == 1 and all(ln.startswith("CATALOGUE_SHA256 = ") for ln in differing[0]), differing
    # Before Phase 8 the real catalogue has no such node: the entry is refused there as well, on both counts.
    d = tmp_path / "real-catalogue"
    d.mkdir()
    err = _refused(venv_py, gen_dir, d, _source_file(d, source, e), CONTROL_LEAF, NO_NODE)
    assert _named(err, CONTROL_LEAF, CONTROL_RULE)


def test_a2d_the_generator_refuses_a_case_or_whitespace_variant_as_not_in_the_catalogue(gen, venv_py, gen_dir, ids, source,
                                                                                      excluded_leaves, tmp_path):
    """Exact, case-sensitive membership and no normalisation: a normaliser is how a near-miss string becomes a hit."""
    n = 0
    for leaf in (excluded_leaves[0], excluded_leaves[-1], "Vehicle.Speed"):
        variants = [leaf.lower(), leaf.upper(), leaf.swapcase(), " " + leaf, leaf + " ", "\t" + leaf, leaf + "\n", leaf + ".",
                    "." + leaf, leaf.replace(".", " . ", 1), leaf.replace(".", "..", 1), leaf[:-1] + leaf[-1].swapcase()]
        assert len(set(variants)) == len(variants) and leaf not in variants
        for v in variants:
            assert v not in ids
            e = _entry(v, ids[leaf])
            assert any(p.startswith("%r: " % v) and NO_NODE in p for p in gen.entry_problems(e, ids, EXCLUDED, CONTROL)), v
            d = tmp_path / ("variant-%d" % n)
            n += 1
            d.mkdir()
            # In place of the real entry when it is a variant of an allowlisted path, so a normaliser would find no duplicate.
            _refused(venv_py, gen_dir, d, _source_file(d, source, e, drop=(leaf,)), v, NO_NODE)
    assert n == 36


@pytest.mark.parametrize("what, change, reason", [
    ("a path the catalogue lacks", {"path": "Vehicle.NoSuchSignal"}, NO_NODE),
    ("another type", {"type": "actuator"}, "type 'actuator' in the source list, 'sensor' in the catalogue"),
    ("another datatype", {"datatype": "double"}, "datatype 'double' in the source list, 'float' in the catalogue"),
    ("another unit", {"unit": "m/s"}, "unit 'm/s' in the source list, 'km/h' in the catalogue"),
    ("no unit where the catalogue has one", {"unit": None}, "unit None in the source list, 'km/h' in the catalogue"),
    ("a star", {"path": "Vehicle.*"}, WILDCARD_RULE),
    ("a trailing star", {"path": "Vehicle.Speed*"}, WILDCARD_RULE),
    ("an MQTT multi-level wildcard", {"path": "Vehicle.#"}, WILDCARD_RULE),
    ("an MQTT single-level wildcard", {"path": "Vehicle.+.Longitudinal"}, WILDCARD_RULE),
    ("a question mark", {"path": "Vehicle.Spee?"}, WILDCARD_RULE),
])
def test_the_generator_refuses_an_entry_that_differs_from_the_catalogue_or_holds_a_wildcard(venv_py, gen_dir, source, tmp_path,
                                                                                         what, change, reason):
    speed = next(e for e in source["entries"] if e["path"] == "Vehicle.Speed")
    e = dict(speed, **change)
    err = _refused(venv_py, gen_dir, tmp_path, _source_file(tmp_path, source, e, drop=("Vehicle.Speed",)), e["path"], reason)
    if reason == WILDCARD_RULE:
        assert _named(err, e["path"], NO_NODE)          # and it is no node either


def test_the_generator_refuses_a_unit_on_a_leaf_that_has_none_and_an_entry_listed_twice(venv_py, gen_dir, source, tmp_path):
    gear = next(e for e in source["entries"] if e["datatype"] == "int8")
    assert gear["unit"] is None
    d = tmp_path / "unit"
    d.mkdir()
    _refused(venv_py, gen_dir, d, _source_file(d, source, dict(gear, unit="percent"), drop=(gear["path"],)), gear["path"],
             "unit 'percent' in the source list, None in the catalogue")
    d = tmp_path / "twice"
    d.mkdir()
    _refused(venv_py, gen_dir, d, _source_file(d, source, dict(gear)), gear["path"], "is listed more than once")


@pytest.mark.parametrize("what, edit, reason", [
    ("not JSON", lambda t: t[:-3], "is not JSON"),
    ("another top-level key", lambda t: t.replace('"version"', '"versions"', 1), "holds exactly the keys about, entries and version"),
    ("a version that is no integer", lambda t: t.replace('"version": 1', '"version": "1"', 1), "version must be an integer"),
    ("a boolean version", lambda t: t.replace('"version": 1', '"version": true', 1), "version must be an integer"),
    ("an entry with another key", lambda t: t.replace('"channels"', '"channel"', 1), "holds exactly the keys"),
    ("an unknown channel", lambda t: t.replace('["S", "T"]', '["S", "X"]', 1), "channels must be"),
    ("no channel", lambda t: t.replace('["S", "T"]', '[]', 1), "channels must be"),
    ("a channel twice", lambda t: t.replace('["S", "T"]', '["S", "S"]', 1), "channels must be"),
    ("the channels the other way round", lambda t: t.replace('["S", "T"]', '["T", "S"]', 1), "channels must be"),
    ("a path that is no string", lambda t: t.replace('"path": "Vehicle.Speed"', '"path": 7', 1), "path must be a non-empty string"),
    ("an empty type", lambda t: t.replace('"type": "sensor"', '"type": ""', 1), "type must be a non-empty string"),
    ("a unit that is no string", lambda t: t.replace('"unit": "km/h"', '"unit": 3.6', 1), "unit must be a string or null"),
    ("no entry", lambda t: json.dumps(dict(json.loads(t), entries=[])), "holds no entry"),
    ("a second entries list, which json would silently prefer", lambda t: t.replace('"version": 1,', '"entries": [], "version": 1,', 1),
     "holds a key twice in one object: entries"),
    ("a path given twice in one entry", lambda t: t.replace('{"path": "Vehicle.Speed",', '{"path": "Vehicle.Other", "path": "Vehicle.Speed",', 1),
     "holds a key twice in one object: path"),
])
def test_the_generator_refuses_a_source_list_of_another_shape(gen, venv_py, gen_dir, tmp_path, what, edit, reason):
    text = SOURCE_FILE.read_text(encoding="utf-8")
    bad = edit(text)
    assert bad != text, what
    with pytest.raises(gen.Refusal) as exc:
        gen.parse_source(bad)
    assert any(reason in p for p in exc.value.problems), (what, exc.value.problems)
    src = tmp_path / "source.json"
    src.write_text(bad, encoding="utf-8", newline="\n")
    out = tmp_path / "out" / "twin_allowlist.py"
    r = _cli(venv_py, "--gen", gen_dir, "--source", src, "--out", out)
    assert r.returncode == 1 and reason in r.stderr and not out.parent.exists(), (what, r.stderr)
    assert gen.parse_source(text)["version"] == 1          # the unedited list parses


def test_the_generator_refuses_an_appstate_sub_branch_that_is_listed_in_part_or_differs_from_the_schema(gen, ids, source, venv_py,
                                                                                                    gen_dir, tmp_path):
    """A record is assembled from all the leaves of a sub-branch, so a sub-branch is listed whole or not at all, and
    every leaf has exactly one schema property naming it (the design's A7, schema to catalogue)."""
    seq = hazard.BRANCH + ".Seq"
    err = _refused(venv_py, gen_dir, tmp_path, _source_file(tmp_path, source, drop=(seq,)), seq, "is not in the source list")
    assert "AppState" in err
    entries = source["entries"]
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    branches, fields, problems = gen.appstate_fields(entries, ids, schema, attr.APPSTATE_PREFIX)
    assert problems == [] and branches == (hazard.BRANCH,) and fields == APP_FIELDS and list(fields) == list(hazard.LEAF_PATHS)
    # A schema annotation naming a leaf the catalogue lacks (the design's seeded case), one of another datatype, a
    # property with no annotation, an `allowed` list that is not the schema's enum, a leaf no property names.
    for edit, reason in (
            (lambda s: s["properties"]["hazard_requested"].update({"x-vss-leaf": "AppState.<App>.HazardRequested (sensor, boolean)"}),
             "names no leaf of"),
            (lambda s: s["properties"]["seq"].update({"x-vss-leaf": "AppState.<App>.Seq (sensor, uint8)"}), "datatype"),
            (lambda s: s["properties"]["seq"].pop("x-vss-leaf"), "x-vss-leaf"),
            (lambda s: s["properties"]["state"].update({"enum": ["starting", "running"]}), "allowed"),
            (lambda s: (s["properties"].pop("seq"), s["required"].remove("seq")), "has no schema property"),
    ):
        s = copy.deepcopy(schema)
        edit(s)
        assert any(reason in p for p in gen.appstate_fields(entries, ids, s, attr.APPSTATE_PREFIX)[2]), reason
    # A leaf deeper than the sub-branch, and a leaf directly under the AppState branch, are no record's field.
    for bad in (hazard.BRANCH + ".Sub.Leaf", attr.APPSTATE_PREFIX + "Loose"):
        nodes = dict(ids, **{bad: {"type": "sensor", "datatype": "uint8", "staticUID": "0x00000001"}})
        if bad.count(".") == 5:
            nodes[bad.rsplit(".", 1)[0]] = {"type": "branch", "staticUID": "0x00000002"}
        probs = gen.appstate_fields(entries + [_entry(bad, nodes[bad])], nodes, schema, attr.APPSTATE_PREFIX)[2]
        assert any(p.startswith("%r: " % bad) for p in probs), (bad, probs)


def test_a_refused_run_leaves_an_existing_module_as_it_was(venv_py, gen_dir, ids, source, excluded_leaves, tmp_path):
    out = tmp_path / "twin" / "twin_allowlist.py"
    assert _cli(venv_py, "--gen", gen_dir, "--out", out).returncode == 0
    before = out.read_bytes()
    r = _cli(venv_py, "--gen", gen_dir, "--source", _source_file(tmp_path, source, _entry(excluded_leaves[0], ids[excluded_leaves[0]])),
             "--out", out)
    assert r.returncode == 1 and out.read_bytes() == before
    assert sorted(p.name for p in out.parent.iterdir()) == ["twin_allowlist.py"]          # no staging file left


def test_the_generator_writes_inside_the_tree_only_under_sdv_out_and_needs_its_inputs(gen, venv_py, gen_dir, tmp_path):
    for inside in (CONNECTOR_DIR / "twin_allowlist.py", REPO / "twin_allowlist.py", HERE / "twin_allowlist_frozen.py"):
        assert not inside.exists() and gen.inside_tracked_tree(inside)
        try:
            r = _cli(venv_py, "--gen", gen_dir, "--out", inside)
            assert r.returncode == 1 and "inside the repository" in r.stderr and not inside.exists(), r.stderr
        finally:
            inside.unlink(missing_ok=True)          # a generator that failed this test must not leave its file in the tree
    assert not gen.inside_tracked_tree(FROZEN) and not gen.inside_tracked_tree(tmp_path / "x.py")
    assert gen.DEFAULT_OUT == FROZEN and gen.DEFAULT_SOURCE == SOURCE_FILE and gen.DEFAULT_SCHEMA == SCHEMA_FILE
    r = _cli(venv_py, "--gen", tmp_path / "no-gen", "--out", tmp_path / "o.py")
    assert r.returncode == 1 and "vss-ids.vspec" in r.stderr and not (tmp_path / "o.py").exists(), r.stderr
    r = _cli(venv_py, "--gen", gen_dir, "--source", tmp_path / "none.json", "--out", tmp_path / "o.py")
    assert r.returncode == 1 and "none.json" in r.stderr, r.stderr
    r = _cli(venv_py, "--gen", gen_dir, "--prefix", "Vehicle.Other.", "--out", tmp_path / "o.py")
    assert r.returncode == 2 and not (tmp_path / "o.py").exists()          # the excluded prefix is no option of the command line


@pytest.mark.parametrize("data,want", [(b"", 0x811C9DC5), (b"a", 0x050C5D7E), (b"foobar", 0x31F0B262)])
def test_the_generators_fnv1_32_gives_the_test_vectors(gen, data, want):
    assert gen.fnv1_32(data) == want == _fnv1_32(data)


def test_the_digest_serialises_the_uids_little_endian_in_tuple_order(gen):
    uids = (0x0A1B2C3D, 0x01020304, 0xDEADBEEF, 0x12345678, 0x9ABCDEF0)          # the kind 4 digest's own test vector
    assert gen.digest_of(uids) == 0xC30680E3 == _fnv1_32(struct.pack("<5I", *uids))
    assert _fnv1_32(struct.pack(">5I", *uids)) == 0xFA2112AB != gen.digest_of(uids)
    assert gen.digest_of(tuple(reversed(uids))) != 0xC30680E3
    for bad in ("0x0a1b2c3d", "0x0A1B2C3", "0A1B2C3D", " 0x0A1B2C3D", 0x0A1B2C3D, None):
        with pytest.raises(gen.Refusal):
            gen.parse_uid(bad, "Vehicle.X")
    assert gen.parse_uid("0x0A1B2C3D", "Vehicle.X") == 0x0A1B2C3D


# ============================================================ A3: the frozen module

def test_a3_the_frozen_module_equals_a_fresh_generation(venv_py, gen_dir, frozen_file, tmp_path):
    fresh = tmp_path / "a" / "twin_allowlist.py"
    r = _cli(venv_py, "--gen", gen_dir, "--out", fresh)
    assert r.returncode == 0, r.stderr
    assert fresh.read_bytes() == frozen_file.read_bytes(), "sdv-out/twin/twin_allowlist.py is not what the inputs generate: rerun gen_allowlist.py"
    again = tmp_path / "b" / "twin_allowlist.py"
    assert _cli(venv_py, "--gen", gen_dir, "--out", again).returncode == 0 and again.read_bytes() == fresh.read_bytes()
    assert b"\r" not in fresh.read_bytes() and str(tmp_path).encode() not in fresh.read_bytes()          # no path of the run in it
    before = frozen_file.read_bytes()
    r = _cli(venv_py, "--gen", gen_dir, "--check", "--out", frozen_file)
    assert r.returncode == 0 and "is a fresh generation" in r.stdout, r.stdout + r.stderr
    assert frozen_file.read_bytes() == before          # --check writes nothing
    r = _cli(venv_py, "--gen", gen_dir, "--check", "--out", tmp_path / "absent.py")
    assert r.returncode == 1 and "STALE" in r.stderr and not (tmp_path / "absent.py").exists(), r.stderr


def test_a3_the_frozen_module_holds_what_the_plan_lists(frozen, frozen_file, gen_dir, ids, source, excluded_leaves):
    entries = source["entries"]
    assert frozen.FORMAT == 1 and frozen.VERSION == attr.ALLOWLIST_VERSION == source["version"]
    assert isinstance(frozen.PATHS, tuple) and frozen.PATHS == tuple(e["path"] for e in entries) == TABLE_ORDER
    assert set(frozen.PATHS) == attr.ALLOWLIST_V1 and len(frozen.PATHS) == 16
    uids = tuple(int(ids[p]["staticUID"], 16) for p in frozen.PATHS)
    assert all(re.fullmatch(r"0x[0-9A-F]{8}", ids[p]["staticUID"]) for p in frozen.PATHS) and len(set(uids)) == 16
    assert frozen.STATIC_UIDS == uids
    assert frozen.DIGEST == _fnv1_32(struct.pack("<16I", *uids)) and frozen.DIGEST not in (0, 0xFFFFFFFF)
    contract = _load("sdv_vss_contract_for_twin_a3", gen_dir / "vss_contract.py")
    assert frozen.STATIC_UIDS[0] == contract.SLOT_UIDS[0] and frozen.STATIC_UIDS[2:6] == contract.SLOT_UIDS[1:]      # the slots' UIDs
    assert frozen.NODES == {e["path"]: (e["type"], e["datatype"], e["unit"]) for e in entries} and list(frozen.NODES) == list(frozen.PATHS)
    assert frozen.CHANNELS == {e["path"]: tuple(e["channels"]) for e in entries} and list(frozen.CHANNELS) == list(frozen.PATHS)
    assert frozen.CHANNELS[attr.WHEELBASE] == ("S",)
    assert frozen.APPSTATE_BRANCHES == (hazard.BRANCH,) == (attr.app_branch(hazard.APP_NAME),)
    assert frozen.APPSTATE_FIELDS == APP_FIELDS and list(frozen.APPSTATE_FIELDS) == list(hazard.LEAF_PATHS)
    assert list(frozen.APPSTATE_FIELDS.values()) == SCHEMA["required"]
    sha = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in
           (("ids", gen_dir / "vss-ids.vspec"), ("source", SOURCE_FILE), ("schema", SCHEMA_FILE))}
    assert (frozen.CATALOGUE_FILE, frozen.CATALOGUE_SHA256) == ("vss-ids.vspec", sha["ids"])
    assert (frozen.SOURCE_FILE, frozen.SOURCE_SHA256) == ("twin_allowlist.json", sha["source"])
    assert (frozen.SCHEMA_FILE, frozen.SCHEMA_SHA256) == ("appstate.schema.json", sha["schema"])
    manifest = json.loads((gen_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outputs"]["vss-ids.vspec"]["sha256"] == frozen.CATALOGUE_SHA256          # one generation's id file
    # Nothing of the excluded branch, no branch, no ControlCommand; the text spells no such path either.
    assert len(excluded_leaves) == EXCLUDED_LEAVES_TODAY and not set(frozen.PATHS) & set(excluded_leaves)
    assert not any(p == EXCLUDED or p.startswith(attr.MONITOR_PREFIX) or p.startswith(CONTROL) for p in frozen.PATHS)
    assert all(ids[p]["type"] != "branch" for p in frozen.PATHS)
    text = frozen_file.read_text(encoding="utf-8")
    assert EXCLUDED.lower() not in text.lower() and EXCLUDED.split(".", 1)[1].lower() not in text.lower()
    assert text.startswith('"""twin_allowlist.py -- GENERATED by sdv/connector/gen_allowlist.py. Do not edit; never commit')


def _hand_edit(text: str, path: str, uid: int, node: Dict[str, Any], digest: int) -> str:
    """The frozen module with `path` added everywhere a careful hand would add it."""
    for old, new in (("PATHS = (\n", "PATHS = (\n    %r,\n" % path),
                     ("STATIC_UIDS = (\n", "STATIC_UIDS = (\n    0x%08X,\n" % uid),
                     ("NODES = {\n", "NODES = {\n    %r: (%r, %r, %r),\n" % (path, node["type"], node["datatype"], node.get("unit"))),
                     ("CHANNELS = {\n", "CHANNELS = {\n    %r: ('S', 'T'),\n" % path)):
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    assert len(re.findall(r"^DIGEST = 0x[0-9A-F]{8}$", text, re.M)) == 1
    return re.sub(r"^DIGEST = 0x[0-9A-F]{8}$", "DIGEST = 0x%08X" % digest, text, flags=re.M)


def test_a3_a_hand_edited_module_with_one_extra_path_fails(venv_py, gen_dir, frozen, frozen_file, ids, excluded_leaves, tmp_path):
    text = frozen_file.read_text(encoding="utf-8")
    for n, extra in enumerate(("Vehicle.CurrentLocation.Latitude", excluded_leaves[0])):
        assert extra not in frozen.PATHS and ids[extra]["type"] != "branch"
        # The careless edit: one more line in PATHS. The module refuses to import, and it is not a fresh generation.
        careless = tmp_path / ("careless-%d" % n) / "twin_allowlist.py"
        careless.parent.mkdir()
        assert text.count("PATHS = (\n") == 1
        careless.write_text(text.replace("PATHS = (\n", "PATHS = (\n    %r,\n" % extra), encoding="utf-8", newline="\n")
        with pytest.raises(ValueError, match="hand-edited"):
            _load("twin_allowlist_careless_%d" % n, careless)
        r = _cli(venv_py, "--gen", gen_dir, "--check", "--out", careless)
        assert r.returncode == 1 and "STALE" in r.stderr and "differs from a fresh generation" in r.stderr, r.stderr
        # The consistent edit: the path, its staticUID, its node, its channels and the digest over all seventeen.
        uid = int(ids[extra]["staticUID"], 16)
        digest = _fnv1_32(struct.pack("<17I", uid, *frozen.STATIC_UIDS))
        careful = tmp_path / ("careful-%d" % n) / "twin_allowlist.py"
        careful.parent.mkdir()
        careful.write_text(_hand_edit(text, extra, uid, ids[extra], digest), encoding="utf-8", newline="\n")
        mod = _load("twin_allowlist_careful_%d" % n, careful)          # its own check cannot see it
        assert mod.PATHS == (extra,) + frozen.PATHS and mod.DIGEST == digest != frozen.DIGEST
        r = _cli(venv_py, "--gen", gen_dir, "--check", "--out", careful)
        assert r.returncode == 1 and "STALE" in r.stderr and "differs from a fresh generation" in r.stderr, r.stderr
        assert careful.read_text(encoding="utf-8") != text          # --check rewrote nothing


@pytest.mark.parametrize("old, new", [
    ("DIGEST = 0x", "DIGEST = 1 + 0x"),                                                    # a digest that is not the FNV-1 of the UIDs
    ("STATIC_UIDS = (\n", "STATIC_UIDS = (\n    0x00000001,\n"),                             # one UID more than paths
    ("PATHS = (\n", "PATHS = (\n    'Vehicle.Speed',\n"),                                    # a path twice
    ("CHANNELS = {\n", "CHANNELS = {\n    'Vehicle.Extra': ('S', 'T'),\n"),                  # a channel for a path that is not listed
    ("('S',),\n", "('X',),\n"),                                                              # a channel that is none
    ("NODES = {\n", "NODES = {\n    'Vehicle.Extra': ('sensor', 'float', None),\n"),
    ("APPSTATE_FIELDS = {\n", "APPSTATE_FIELDS = {\n    'Vehicle.Extra.Leaf': 'extra',\n"),  # a record field from a path that is not listed
    ("APPSTATE_BRANCHES = (\n", "APPSTATE_BRANCHES = (\n    'Vehicle.Extra',\n"),            # a sub-branch with no field
])
def test_the_frozen_module_refuses_to_import_when_its_parts_disagree(frozen_file, tmp_path, old, new):
    text = frozen_file.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    edited = tmp_path / "twin_allowlist.py"
    edited.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="hand-edited"):
        _load("twin_allowlist_edited_%08x" % _fnv1_32(new.encode()), edited)
    _load("twin_allowlist_unedited_%08x" % _fnv1_32(new.encode()), frozen_file)          # the unedited module imports


# ============================================================ A7, the connector's half: the AppState whitelist

def _seeded() -> List[Tuple[str, Dict[str, Any], List[str]]]:
    """(what, record, the validator's findings): the schema's example, valid variants, and each seeded violation."""
    ex = dict(EXAMPLE)
    out: List[Tuple[str, Dict[str, Any], List[str]]] = [("the schema's example", ex, [])]
    out += [("seq at its minimum", dict(ex, seq=1), []), ("seq at its maximum", dict(ex, seq=4294967295), []),
            ("the hazard requested", dict(ex, hazard_requested=True), []), ("another app's name", dict(ex, app="x1a-b2"), []),
            ("the largest version", dict(ex, app_version="999.999.999"), [])]
    out += [("state %s" % s, dict(ex, state=s), []) for s in SCHEMA["properties"]["state"]["enum"]]
    out += [("actuate_result %s" % s, dict(ex, actuate_result=s), []) for s in SCHEMA["properties"]["actuate_result"]["enum"]]
    # The design's seeded violations.
    out.append(("an extra last_verdict", dict(ex, last_verdict=1), ["extra last_verdict", "name last_verdict"]))
    out.append(("an extra field with an innocent name", dict(ex, uptime_s=5), ["extra uptime_s"]))
    out += [("no %s" % k, {a: b for a, b in ex.items() if a != k}, ["missing %s" % k]) for k in SCHEMA["required"]]
    out.append(("a wrong enum in state", dict(ex, state="crashed"), ["enum state"]))
    out.append(("a wrong enum in actuate_result", dict(ex, actuate_result="maybe"), ["enum actuate_result"]))
    out += [("a name that fails the tripwire: %s" % n, dict(ex, **{n: True}), ["extra %s" % n, "name %s" % n])
            for n in ("monitor_state", "guest_connected", "reject_count", "claim_age", "liveness", "bridge_up")]
    out.append(("a name that is not lower-case", dict(ex, Seq=1), ["extra Seq", "name Seq"]))
    out.append(("a name of 33 characters", dict(ex, **{"a" * 33: 1}), ["extra " + "a" * 33, "name " + "a" * 33]))
    # Each other keyword the flat schema uses.
    out += [("seq as a string", dict(ex, seq="42"), ["type seq"]), ("a boolean as 0", dict(ex, hazard_requested=0), ["type hazard_requested"]),
            ("a version that is true", dict(ex, schema_version=True), ["type schema_version"]), ("app as a number", dict(ex, app=7), ["type app"]),
            ("a null state", dict(ex, state=None), ["type state"]), ("seq as a fraction", dict(ex, seq=1.5), ["type seq"]),
            ("another schema version", dict(ex, schema_version=2), ["const schema_version"]),
            ("seq 0", dict(ex, seq=0), ["range seq"]), ("seq beyond uint32", dict(ex, seq=4294967296), ["range seq"]),
            ("an app with a capital", dict(ex, app="Hard-brake"), ["pattern app"]),
            ("an app word that starts with a digit", dict(ex, app="x-1a"), ["pattern app"]),
            ("an app with prose", dict(ex, app="verdict: reject"), ["pattern app"]),
            ("a two-part version", dict(ex, app_version="1.0"), ["pattern app_version"]),
            ("a version with a suffix", dict(ex, app_version="1.0.0-rc1"), ["pattern app_version"]),
            ("an upper-case image id", dict(ex, image_id="sha256:" + "A" * 64), ["pattern image_id"]),
            ("a short image id", dict(ex, image_id="sha256:" + "a" * 63), ["pattern image_id"]),
            ("an app of 33 characters", dict(ex, app="a" * 33), ["maxLength app"])]
    return out


_ORACLE = ("import json, sys, jsonschema\n"
           "schema = json.load(open(sys.argv[1], encoding='utf-8'))\n"
           "jsonschema.Draft202012Validator.check_schema(schema)\n"
           "v = jsonschema.Draft202012Validator(schema)\n"
           "json.dump([v.is_valid(c) for c in json.load(sys.stdin)], sys.stdout)\n")


def _oracle(py: Path, records: List[Dict[str, Any]]) -> List[bool]:
    """What the schema itself says of each record: jsonschema's draft 2020-12 validator, in the vss venv (a pin of its lock)."""
    r = subprocess.run([str(py), "-B", "-c", _ORACLE, str(SCHEMA_FILE)], input=json.dumps(records), capture_output=True, text=True,
                       timeout=300)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a7_the_validator_finds_each_seeded_violation_and_passes_the_example(appstate):
    cases = _seeded()
    assert len(cases) >= 50 and sum(1 for _w, _r, errs in cases if not errs) >= 14
    for what, record, errs in cases:
        assert sorted(appstate.validate(SCHEMA, record)) == sorted(errs), what
    assert appstate.validate(SCHEMA, {}) == ["missing %s" % k for k in SCHEMA["required"]]
    assert appstate.load_schema(SCHEMA_FILE) == SCHEMA


def test_a7_the_validator_agrees_with_the_schema_on_the_example_and_on_each_seeded_violation(appstate, venv_py):
    cases = _seeded()
    verdicts = _oracle(venv_py, [record for _w, record, _e in cases])
    assert len(verdicts) == len(cases) and verdicts[0] is True and not all(verdicts)
    for (what, record, errs), valid in zip(cases, verdicts):
        assert (appstate.validate(SCHEMA, record) == []) == valid == (not errs), what
    # Where the connector is stricter than a Python JSON Schema validator, and why. (1) JSON Schema's integer takes
    # 1.0; the databroker hands an integer leaf over as an int, so a float there is refused. (2) The schema's patterns
    # are ECMA-262, whose `$` matches at the end of input only; Python's also matches before a trailing newline.
    stricter = [("an integer as a float", dict(EXAMPLE, schema_version=1.0), ["type schema_version"]),
                ("seq as a float", dict(EXAMPLE, seq=42.0), ["type seq"]),
                ("a version with a trailing newline", dict(EXAMPLE, app_version="1.0.0\n"), ["pattern app_version"]),
                ("an app with a trailing newline", dict(EXAMPLE, app=EXAMPLE["app"] + "\n"), ["pattern app"])]
    for (what, record, errs), valid in zip(stricter, _oracle(venv_py, [r for _w, r, _e in stricter])):
        assert appstate.validate(SCHEMA, record) == errs, what
        assert valid is True, "%s: jsonschema now refuses it too; move the case to the agreed list" % what


def test_the_validator_reads_every_pattern_as_ecma_262_does(appstate):
    """`$` outside a character class is the end of the input, never the place before a trailing newline."""
    assert appstate.ecma(r"^a$") == r"^a\Z" and appstate.ecma(r"^[a$]\$$") == r"^[a$]\$\Z" and appstate.ecma(r"a\\$") == r"a\\\Z"
    assert appstate.ecma(r"^[.]$|^x$") == r"^[.]\Z|^x\Z" and appstate.ecma("abc") == "abc"
    patterns = [SCHEMA["propertyNames"]["pattern"]] + [p["pattern"] for p in SCHEMA["properties"].values() if "pattern" in p]
    assert len(patterns) == 4 and all(p.endswith("$") and appstate.ecma(p) == p[:-1] + r"\Z" for p in patterns)
    assert appstate.ecma(SCHEMA["propertyNames"]["not"]["pattern"]) == SCHEMA["propertyNames"]["not"]["pattern"]
    for prop in ("app", "app_version", "image_id"):
        for tail in ("\n", "\r\n", " ", "\x00"):
            assert appstate.validate(SCHEMA, dict(EXAMPLE, **{prop: EXAMPLE[prop] + tail})), (prop, tail)
    assert sorted(appstate.validate(SCHEMA, dict(EXAMPLE, **{"seq\n": 1}))) == ["extra seq\n", "name seq\n"]


def _values(record: Dict[str, Any], fields: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The record as the databroker holds it: one value per leaf of the app's sub-branch."""
    return {leaf: record[prop] for leaf, prop in (fields or APP_FIELDS).items() if prop in record}


def test_a7_a_record_is_assembled_from_the_eight_leaves_of_one_sub_branch_and_from_nothing_else(appstate):
    values = _values(EXAMPLE)
    assert len(values) == 8
    assert appstate.assemble(APP_FIELDS, hazard.BRANCH, values) == EXAMPLE
    assert appstate.checked(SCHEMA, APP_FIELDS, hazard.BRANCH, values) == (EXAMPLE, [])
    # Values beside the sub-branch never reach the record: a leaf of the excluded branch, another app's leaf, a
    # standard signal, a leaf of this sub-branch that no property names.
    noise = {attr.MONITOR_PREFIX + "Anything.Verdict": 1, attr.APPSTATE_PREFIX + "OtherApp.State": "degraded",
             "Vehicle.Speed": 12.5, hazard.BRANCH + ".LastVerdict": 1, hazard.BRANCH: "x", hazard.BRANCH + ".Seq.Deeper": 9}
    assert appstate.checked(SCHEMA, APP_FIELDS, hazard.BRANCH, dict(values, **noise)) == (EXAMPLE, [])
    # A leaf with no value yet (absent, or None as a source holds it) leaves its property out: no record.
    for gone in hazard.LEAF_PATHS:
        prop = APP_FIELDS[gone]
        for holed in ({k: v for k, v in values.items() if k != gone}, dict(values, **{gone: None})):
            assert appstate.checked(SCHEMA, APP_FIELDS, hazard.BRANCH, holed) == (None, ["missing %s" % prop]), gone
    assert appstate.checked(SCHEMA, APP_FIELDS, hazard.BRANCH, {})[0] is None
    # An invalid value drops the whole record, and the findings name the property, never the value.
    record, problems = appstate.checked(SCHEMA, APP_FIELDS, hazard.BRANCH, _values(dict(EXAMPLE, state="verdict-reject")))
    assert record is None and problems == ["enum state"] and "verdict-reject" not in " ".join(problems)
    # A leaf map with a field of another sub-branch gives that field to no record of this one.
    other = attr.APPSTATE_PREFIX + "OtherApp"
    mixed = dict(APP_FIELDS, **{other + ".Seq": "seq"})
    assert appstate.assemble(mixed, hazard.BRANCH, dict(values, **{other + ".Seq": 7})) == EXAMPLE
    assert appstate.assemble(mixed, other, dict(values, **{other + ".Seq": 7})) == {"seq": 7}


def test_a7_a_record_whose_app_names_another_sub_branch_is_dropped(appstate):
    """The connector checks that the record's `app` derives the sub-branch it came from: split on '-', upper-case the
    first letter of each part, join."""
    assert appstate.checked(SCHEMA, APP_FIELDS, hazard.BRANCH, _values(EXAMPLE)) == (EXAMPLE, [])
    for app in ("other-app", "hardbrake-hazard", "hard-brake", "hard-brake-hazard-two", "hardbrakehazard", "h"):
        assert appstate.validate(SCHEMA, dict(EXAMPLE, app=app)) == [], app          # a valid record in itself
        record, problems = appstate.checked(SCHEMA, APP_FIELDS, hazard.BRANCH, _values(dict(EXAMPLE, app=app)))
        assert record is None and len(problems) == 1 and "does not derive the sub-branch" in problems[0], (app, problems)
        assert not appstate.derives(app, hazard.BRANCH)
    # The same record under another app's sub-branch: its `app` names this one, not that.
    other = attr.APPSTATE_PREFIX + "OtherApp"
    other_fields = {other + "." + leaf.rsplit(".", 1)[1]: prop for leaf, prop in APP_FIELDS.items()}
    record, problems = appstate.checked(SCHEMA, other_fields, other, _values(EXAMPLE, other_fields))
    assert record is None and "does not derive the sub-branch" in problems[0]
    assert appstate.checked(SCHEMA, other_fields, other, _values(dict(EXAMPLE, app="other-app"), other_fields))[0] == dict(EXAMPLE, app="other-app")
    # An invalid `app` is the validator's finding; the rule is not asked what a non-name derives.
    assert appstate.checked(SCHEMA, APP_FIELDS, hazard.BRANCH, _values(dict(EXAMPLE, app=7))) == (None, ["type app"])
    assert not appstate.derives(7, hazard.BRANCH) and not appstate.derives("", hazard.BRANCH)


def test_the_sub_branch_rule_is_the_stacks_and_the_apps(appstate):
    names = ("hard-brake-hazard", "x", "a-b", "abc", "x1a", "lane-keep-assist", "a1-b2-c3")
    parent = attr.APPSTATE_PREFIX[:-1]
    for name in names:
        assert parent + "." + appstate.branch_name(name) == attr.app_branch(name) == hazard.app_branch(name), name
        assert appstate.derives(name, attr.app_branch(name)) and not appstate.derives(name, attr.app_branch(name) + "X")
    assert appstate.branch_name(hazard.APP_NAME) == "HardBrakeHazard" and appstate.derives(hazard.APP_NAME, hazard.BRANCH)
    assert len({appstate.branch_name(n) for n in names}) == len(names)          # no two names derive one sub-branch
    assert not appstate.derives("hard-brake-hazard", "HardBrakeHazard")          # a bare name is no sub-branch path


# ============================================================ A11: the size of the largest vss document

LONGEST_STRINGS = {"app": "a" * 32, "app_version": "999.999.999", "image_id": "sha256:" + "f" * 64}


def _largest(datatype: str, prop: Optional[str]) -> Any:
    """The value of a leaf whose JSON text is the longest its datatype (and, for a string, its schema property) allows."""
    numbers = {"float": -1.7976931348623157e+308, "double": -1.7976931348623157e+308, "int8": -128, "int16": -32768,
               "uint8": 255, "uint16": 65535, "uint32": 4294967295, "boolean": False}
    if datatype in numbers:
        return numbers[datatype]
    assert datatype == "string" and prop is not None, "a string leaf with no schema property has no bound"
    p = SCHEMA["properties"][prop]
    if "enum" in p:
        return max(p["enum"], key=len)
    assert "pattern" in p and "maxLength" in p, prop
    return LONGEST_STRINGS[prop]


def test_a11_the_largest_vss_reported_document_for_v1_is_under_4_kb(appstate, source):
    reported: Dict[str, Any] = {}
    strings = 0
    for e in source["entries"]:
        prop = APP_FIELDS.get(e["path"])
        value = reported[e["path"]] = _largest(e["datatype"], prop)
        if e["datatype"] == "string":
            assert prop is not None, e["path"]          # every string leaf of v1 is a bounded AppState field
            strings += 1
            p = SCHEMA["properties"][prop]
            assert appstate.validate(SCHEMA, dict(EXAMPLE, **{prop: value})) == []          # the longest value is a valid one
            if "maxLength" in p:
                assert len(value) == p["maxLength"]
                assert appstate.validate(SCHEMA, dict(EXAMPLE, **{prop: value + "a"}))          # one character more is refused
                assert appstate.validate(SCHEMA, dict(EXAMPLE, **{prop: "\u00e9" + value[1:]}))          # ASCII only: a character is a byte
    assert len(reported) == 16 and strings == 5 and len(json.dumps(-1.7976931348623157e+308)) == 24
    # A number stands at its datatype's bound, though the schema bounds two of them tighter (schema_version is 1).
    assert (reported[hazard.BRANCH + ".SchemaVersion"], reported[hazard.BRANCH + ".Seq"]) == (255, 4294967295)
    doc = {"state": {"reported": reported}}
    compact = len(json.dumps(doc, separators=(",", ":")).encode("utf-8"))
    spaced = len(json.dumps(doc).encode("utf-8"))
    assert compact < spaced < SHADOW_DOC_LIMIT == 4096
    # Every key null, as a connection's first document may be: smaller still.
    assert len(json.dumps({"state": {"reported": dict.fromkeys(reported)}}).encode("utf-8")) < spaced
    print("A11: the largest vss reported document for allowlist v1 (16 dotted keys, each value at its longest JSON text, "
          "wrapped in state.reported): %d bytes compact, %d bytes with json.dumps's default separators; bound %d (design value)"
          % (compact, spaced, SHADOW_DOC_LIMIT))


# ============================================================ gap d: no new file spells a path of the excluded branch

def test_no_allowlist_file_spells_a_path_of_the_excluded_branch(frozen_file):
    """The guard of tests/test_sdv_vss.py reads every file named *allowlist* under sdv/, scripts/ and tests/ for the
    branch's lower-cased name; this holds the same of the new files, with the name taken from attribution."""
    needles = (EXCLUDED.lower(), EXCLUDED.split(".", 1)[1].lower())
    files = [GEN_FILE, SOURCE_FILE, APPSTATE_FILE, HERE / "test_twin_allowlist.py", frozen_file]
    named = [p for root in (REPO / "sdv", REPO / "scripts", REPO / "tests") for p in root.rglob("*")
             if p.is_file() and "allowlist" in p.name.lower() and "__pycache__" not in p.parts]
    assert {GEN_FILE, SOURCE_FILE, HERE / "test_twin_allowlist.py"} <= set(named)
    for p in files + named:
        text = p.read_text(encoding="utf-8", errors="replace").lower()
        assert not any(n in text for n in needles), p


def test_the_stacks_tests_validate_with_the_connectors_validator(appstate):
    """The validator moved here from tests/test_sdv_stack.py: the app's heartbeat records are held to the one the
    connector uses, not to a second copy."""
    text = (HERE / "test_sdv_stack.py").read_text(encoding="utf-8")
    assert "appstate.validate(SCHEMA, record)" in text and 'errs.append("extra' not in text
    # What the app really writes at a heartbeat, taken through the connector's assembly: the app's own record.
    acts = hazard.App(image_id="sha256:" + "ab" * 32).on_heartbeat(0.0)
    writes = [a for a in acts if isinstance(a, hazard.Publish)]
    beats = [a.record["record"] for a in acts if isinstance(a, hazard.Note) and a.record["event"] == "heartbeat"]
    assert len(writes) == 1 == len(beats) and appstate.validate(SCHEMA, beats[0]) == []
    values = {path: value for path, value, _datatype in writes[0].leaves}
    assert set(values) == set(APP_FIELDS)
    assert appstate.checked(SCHEMA, APP_FIELDS, hazard.BRANCH, values) == (beats[0], [])
