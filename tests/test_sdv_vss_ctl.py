"""The kind 2 contract generated (SDV plan Phase 8, WP1b; the Phase 8 specification spec-2.md, sections 2.2, 2.3 and 3).

sdv/vss/generate.py loads overlay-ctl.vspec (the ControlCommand layer) with units-project.yaml and
quantities-project.yaml after overlay.vspec, reads the seven kind 2 slot UIDs from that catalogue as it reads kind 4's
five, and writes vss_ctl.h and vss_ctl.py from it and from sdv/vss/profiles-ctl.toml, beside today's outputs. What is
held here, in three groups:

- Pure (Python 3.11+ for tomllib; no venv, no gcc): profiles-ctl.toml is spec 2.3's table, each value READ in WP4a's
  facts held once more in READ (and each design value in DESIGN), so a re-read changes the file and this dict; every
  refusal of 2.3, each with its own message, and the values exactly at a bound accepted; a stand-in never compiled; the
  digest, FNV-1 32 over the seven UIDs as u32 little-endian, recomputed here; the two renderers on the fixtures' values
  give tests/fixtures/ctl-c/vss_ctl.h's macros and tests/fixtures/ctl-py/vss_ctl.py's names and values exactly (WP1a's
  and WP2's fixtures, which the integration stage holds equal); the ControlCommand layer's own checks on crafted
  catalogues; a refused profiles-ctl.toml stops generate.py before the venv and any vss-tools run.
- Against a generation (the vss-tools venv, sdv/vss/README.md; one run into a temporary directory, the pinned archive
  read where it is, the extraction under the temporary directory): vss_ctl.h and vss_ctl.py written and recorded in
  the manifest (ctl_contract, outputs, inputs); the unchanged set (below) byte for byte; the seven UIDs and the digest by
  hand from the catalogue's own node attributes (vss-tools' identifier, recomputed); the project units reaching the
  catalogue as written (rad, rad/s, m/s^3: D5); no ControlCommand path in vss-can-mapping.json or vss-ids.vspec;
  vss_ctl.py through WP2's loader (sdv/ctl/ctlframe.py, imported read only) equal to profiles-ctl.toml; the committed
  uid-baseline.txt keeping every line and gaining the ControlCommand lines only; and refused end to end: a ctl layer with
  a dbc2vss block or an entry outside ControlCommand, a kind 2 slot of another datatype, unit files that do not define
  the layer's units, a forbidden kind 2 digest.
- With gcc (WSL, CI's tooling job): the generated header compiles with monitor.c under 0x14 and tests/ctl_driver.c's
  `constants` and `selfcheck` see vss_ctl.py's values; the native ctl build of orin-native's build-monitor-native.sh,
  run on loopback in `PORT svc 500`, announces the generation's digest and compiled profiles in its `ctl rules:` and
  `ctl profile` lines.

THE UNCHANGED SET is held against SHA-256 values from a generation of the unedited base tree. The hashes cover
vss_contract.h (which carries the kind 4 digest), vehicle-sigsim.vspec, vehicle-carla.vspec,
vss-can-mapping.json and vss-ids.vspec, and each databroker catalogue once its ControlCommand branch is taken out;
vss_contract.py and vss_profiles.h in tests/test_sdv_vss.py (BASE_KIND4_SHA256), because WP3b's profile 4 moves those
two (spec 2.2) and owns that file after this package, not this one (spec-2 section 12). A kind 4 profile change of that
sort is generated here once, and leaves every pin of this module green.

What this does NOT show: that the guest image (qcc) is built or judges kind 2 (WP5); that any value of the table is
right for a run (WP4b); that the databroker serves the ControlCommand nodes or the feeder writes them (WP3d, WP4b); any
timing. Every number asserted here is a design value, a parameter READ from the planning stack's released
configuration, or computed from them; none is a measurement.
"""
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import monitor_corpus as mc

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
VSSDIR = REPO / "sdv" / "vss"
GENERATE = VSSDIR / "generate.py"
PROFILES_CTL = VSSDIR / "profiles-ctl.toml"
OVERLAY_CTL = VSSDIR / "overlay-ctl.vspec"
UNITS_PROJECT = VSSDIR / "units-project.yaml"
UID_BASELINE = VSSDIR / "uid-baseline.txt"
CTL_DIR = REPO / "sdv" / "ctl"
MONITOR_C = REPO / "ipc-test" / "qnx-safety-monitor" / "monitor.c"
COMMON = REPO / "ipc-test" / "common"
SHM_MAP_POSIX_C = COMMON / "shm_map_posix.c"
IVSHM_CLIENT_C = COMMON / "ivshm_client.c"
CTL_DRIVER_C = HERE / "ctl_driver.c"
NATIVE = REPO / "orin-native" / "gpu-concurrency" / "build-monitor-native.sh"
C_FIXTURE = HERE / "fixtures" / "ctl-c" / "vss_ctl.h"
PY_FIXTURE = HERE / "fixtures" / "ctl-py" / "vss_ctl.py"
VENV = Path(os.environ.get("SDV_VENV", "~/sdv-venv")).expanduser()
VENV_PY = VENV / "bin" / "python"
CACHE = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser()
REQUIRE_ENV = "SDV_REQUIRE_GEN"

# tests/test_monitor_vss.py's DEFAULT_FLAGS and the ctl build's two additions, written out here.
DEFAULT_FLAGS = ("-O2", "-std=gnu99", "-Wall", "-Wextra", "-Wformat=2", "-Wundef", "-Werror")
CTL_FLAGS = DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x14")

# Spec 2.4's names, slot order and the ControlCommand layer's nodes, written out here.
SLOT_PATHS = ("Vehicle.DualVm.ControlCommand.Velocity", "Vehicle.DualVm.ControlCommand.Acceleration",
              "Vehicle.DualVm.ControlCommand.Jerk", "Vehicle.DualVm.ControlCommand.SteeringTireAngle",
              "Vehicle.DualVm.ControlCommand.SteeringTireRotationRate", "Vehicle.DualVm.Motion.LongitudinalVelocity",
              "Vehicle.DualVm.ControlCommand.StampInterval")
SLOT_DATATYPES = ("float", "float", "float", "float", "float", "float", "uint16")
CC = "Vehicle.DualVm.ControlCommand"
CONTROL_COMMAND = (CC,) + tuple(CC + "." + x for x in (
    "Velocity", "Acceleration", "IsAccelerationDefined", "Jerk", "IsJerkDefined", "SteeringTireAngle",
    "SteeringTireRotationRate", "IsSteeringTireRotationRateDefined", "ProfileId", "StampInterval"))
# D5 (S19's default): the units as overlay-ctl.vspec writes them; rad and m/s^3 come from units-project.yaml.
CTL_UNITS = {"Velocity": "m/s", "Acceleration": "m/s^2", "Jerk": "m/s^3", "SteeringTireAngle": "rad",
             "SteeringTireRotationRate": "rad/s", "StampInterval": "ms"}
PY_NAMES = ("FORMAT", "SLOT_PATHS", "SLOT_UIDS", "DIGEST", "DT_MAX_MS", "TOL17", "OVERSPEED_FACTOR", "OVERSPEED_MARGIN",
            "ROLLBACK_V", "PROFILES", "COMPILED_PROFILE_IDS")
ROW_KEYS = ("l_mm", "v_max", "a_max", "jerk_max", "steer_max", "steer_rate_max", "lat_acc_max", "run_window_max_ms", "compiled")

# READ: the values spec 2.3 takes from WP4a's reads of Autoware 1.9.0's planning simulator, each named by its
# configuration parameter. This dict is the tests' one copy; profiles-ctl.toml marks each key with a comment block
# starting `# READ (` right above it, naming the parameter and the fact id (READ_SOURCES). A re-read changes this
# dict and those lines, and the generation is made again.
READ = {
    ("profiles.1", "l_mm"): 2790,                # W4 P1: sample_vehicle's vehicle_info.wheel_base, 2.79 m
    ("profiles.1", "v_max"): 25.0,               # W4 P2: the gate's nominal filter, vel_lim
    ("profiles.1", "a_max"): 5.0,                # W4 P2: lon_acc_lim_for_lon_vel, its loosest cell
    ("profiles.1", "jerk_max"): 80.0,            # W4 P2: lon_jerk_lim_for_lon_acc, its loosest cell (the near-stop row)
    ("profiles.1", "steer_max"): 1.0,            # W4 P2: steer_cmd_lim, its loosest cell
    ("profiles.1", "steer_rate_max"): 1.0,       # W4 P2: steer_rate_lim_for_steer_cmd, its loosest cell
    ("profiles.1", "lat_acc_max"): 5.0,          # W4 P2: lat_acc_lim_for_steer_cmd, its loosest cell
}
READ_SOURCES = {
    ("profiles.1", "l_mm"): ("W4 P1", "wheel_base"),
    ("profiles.1", "v_max"): ("W4 P2", "vel_lim"),
    ("profiles.1", "a_max"): ("W4 P2", "lon_acc_lim_for_lon_vel"),
    ("profiles.1", "jerk_max"): ("W4 P2", "lon_jerk_lim_for_lon_acc"),
    ("profiles.1", "steer_max"): ("W4 P2", "steer_cmd_lim"),
    ("profiles.1", "steer_rate_max"): ("W4 P2", "steer_rate_lim_for_steer_cmd"),
    ("profiles.1", "lat_acc_max"): ("W4 P2", "lat_acc_lim_for_steer_cmd"),
}
# DESIGN: spec 2.3's design values (OP 2.2's constants, rule 11's bound, profile 2's demo limit and window). Two rest on
# a READ parameter, which their comment names (DESIGN_SOURCES). Profile 2 is otherwise profile 1's vehicle and limits.
DESIGN = {
    ("", "format"): 1,
    ("", "dt_max_ms"): 100,                       # three 30 ms controller periods and a margin, to 10 ms
    ("", "tol17"): 0.5,                           # rule 17's tolerance, m/s^2
    ("", "overspeed_factor"): 1.2,                # OP 2.2, rule 18
    ("", "overspeed_margin"): 2.0,                # OP 2.2, rule 18, m/s
    ("", "rollback_v"): 0.5,                      # OP 2.2, rule 19, m/s
    ("profiles.2", "v_max"): 3.0,                 # under the planner's max_vel by about a quarter
    ("profiles.2", "run_window_max_ms"): 30000,   # as kind 4's profile 2 and WP2's demo rule
}
DESIGN_SOURCES = {("", "dt_max_ms"): ("W4 P6", "ctrl_period"), ("profiles.2", "v_max"): ("W4 P8", "max_vel")}

# The outputs the ControlCommand layer and kind 4 profile changes must leave byte for byte, recorded from a
# generation of the unedited base tree. vss_contract.py and vss_profiles.h, which WP3b's profile 4 moves, are pinned in tests/test_sdv_vss.py's
# BASE_KIND4_SHA256 (WP3b's file after this package, spec-2 section 12).
BASE_SHA256 = {
    "vss_contract.h": "1942767ac4a6915a2fda17fc312be52076cb6218e28f020eaaa4cdc41ce09a67",
    "vehicle-sigsim.vspec": "f94e7846b108d81f503ec06877abfdbda4625cafaedc4593eba63a1b9c582064",
    "vehicle-carla.vspec": "3e39502458b324a803f99ab727802f4470d8cb94cfaec1127ebf386a3241a730",
    "vss-can-mapping.json": "d8d69e2f6634e450aa23ff1ab9040a8ab227d30797fe7b1e58a0f1437dc8f8be",
    "vss-ids.vspec": "83fe361177a89171a2e3f06a2d1f325df1adfbdec0fddd43ecabebf60e4950a2",
}
# Each databroker catalogue as the base tree generated it: the new one with its ControlCommand branch taken out and
# dumped as generate.py dumps it must give these again.
BASE_BROKER_SHA256 = {
    "vss-databroker.json": "beac13d5fb33c65e8cbf4461776331cbfa14876467276bc6cf19f0ddf882f31e",
    "vss-databroker-carla.json": "127f4e3cec833ccb8aca39c9e97c6234708a7907f6095337fe867cd353645d05",
}
# The base tree's UID lines with this publication's header: removing ControlCommand lines must give these bytes.
BASE_BASELINE_SHA256 = "2a93e32cc8bbf278da783ff7b61fd54a7712afcfb543a2321316ed4b021dfd09"

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None  # type: ignore[assignment]
NEEDS_TOML = pytest.mark.skipif(tomllib is None, reason="profiles-ctl.toml needs Python 3.11+ (tomllib)")


def _load(name, path):
    """Import a file by path without leaving bytecode beside it."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


gen = _load("sdv_vss_generate_for_ctl", GENERATE)


def _ctlframe():
    """WP2's sdv/ctl/ctlframe.py, imported read only as its siblings import it, no bytecode written."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        if str(CTL_DIR) not in sys.path:
            sys.path.insert(0, str(CTL_DIR))
        mod = importlib.import_module("ctlframe")
    finally:
        sys.dont_write_bytecode = saved
    assert Path(mod.__file__).resolve().parent == CTL_DIR, mod.__file__
    return mod


def _missing(what):
    """An input is not there: skip, or fail under SDV_REQUIRE_GEN=1 (read strictly: 1, or off)."""
    value = os.environ.get(REQUIRE_ENV)
    if value == "1":
        pytest.fail("%s=1 and an input of the kind 2 contract tests is missing: %s" % (REQUIRE_ENV, what), pytrace=False)
    if value not in (None, "", "0"):
        pytest.fail("%s is %r: it is 1, or unset (a mistyped switch must not read as off)" % (REQUIRE_ENV, value), pytrace=False)
    pytest.skip(what)


def _gcc():
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        _missing("needs gcc on Linux: runs in WSL and in CI's tooling job")
    return gcc


def _archive():
    archive = CACHE / gen.ARCHIVE_NAME
    if not archive.is_file():
        _missing("needs the pinned VSS archive %s (the first generation run fetches it; sdv/vss/README.md)" % archive)
    return archive


def _need_venv():
    if not (VENV / "bin" / "vspec").exists() or not VENV_PY.exists():
        _missing("needs the vss-tools venv ~/sdv-venv built from sdv/vss/requirements.lock (sdv/vss/README.md; WSL)")


def _fnv1_32(data):
    """FNV-1 32 written out again here, so the digest check does not lean on the generator's copy."""
    h = 0x811C9DC5
    for b in data:
        h = (h * 0x01000193) % (1 << 32)
        h ^= b
    return h


def _uid_of(path, node):
    """A node's staticUID as vss-tools 6.0.0 computes it (name, unit, datatype, type, allowed, min, max; lower-cased,
    since the generation is case-insensitive), from the node's attributes in a JSON export."""
    ident = "%s: unit: %s, datatype: %s, type: %sallowed: %smin: %smax: %s" % (
        path, node.get("unit", ""), node.get("datatype", ""), node["type"], node.get("allowed", ""),
        "" if node.get("min") is None else node["min"], "" if node.get("max") is None else node["max"])
    return _fnv1_32(ident.lower().encode())


def _macros(text):
    """{name: value} of every #define of a header, a value continued over backslash lines joined into one, whitespace
    collapsed; a function-like name is given without its parameter list."""
    out, lines, i = {}, text.splitlines(), 0
    while i < len(lines):
        m = re.match(r"^#define (\w+)(\(X\))?(?: (.*))?$", lines[i])
        if m:
            value = m.group(3) or ""
            while value.endswith("\\"):
                i += 1
                value = value[:-1] + " " + lines[i].strip()
            assert m.group(1) not in out, m.group(1)
            out[m.group(1)] = " ".join(value.split())
        i += 1
    return out


def _json_nodes(tree):
    out = {}

    def walk(prefix, node):
        out[prefix] = node
        for name, child in node.get("children", {}).items():
            walk(prefix + "." + name, child)

    for name, node in tree.items():
        walk(name, node)
    return out


def _without_control_command(tree):
    """The catalogue with the ControlCommand branch taken out, dumped as generate.py dumps a databroker catalogue."""
    tree = copy.deepcopy(tree)
    del tree["Vehicle"]["children"]["DualVm"]["children"]["ControlCommand"]
    return json.dumps(tree, indent=2, sort_keys=True).encode("utf-8")


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


# ============================================================ pure: profiles-ctl.toml is spec 2.3's table

def _ctl_doc():
    assert tomllib is not None
    with open(PROFILES_CTL, "rb") as f:
        return tomllib.load(f)


def _row(doc, pid):
    return next(p for p in doc["profiles"] if p["id"] == pid)


def _expected():
    """Spec 2.3's table from READ and DESIGN: profile 1 READ from the gate's dump, profile 2 its vehicle and limits but
    for its own v_max and run window, both compiled, no stand-in."""
    top = {k: v for (table, k), v in DESIGN.items() if table == ""}
    p1 = dict({k: v for (table, k), v in READ.items() if table == "profiles.1"}, id=1, source="gate-dump", compiled=True,
              stand_in=[])
    p2 = dict(p1, id=2, source="design", **{k: v for (table, k), v in DESIGN.items() if table == "profiles.2"})
    return dict(top, profiles=[p1, p2])


def _typed(x):
    """A value with its type, so 100 and 100.0 (or True and 1) are not equal here."""
    if isinstance(x, dict):
        return {k: _typed(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_typed(v) for v in x]
    return (type(x).__name__, x)


_MARKER = re.compile(r"^# READ \(")
_TABLE = re.compile(r"^\[\[?([a-z0-9_.]+)\]\]?\s*$")
_ASSIGN = re.compile(r"^([a-z0-9_]+)\s*=\s*(.+?)\s*$")


def _blocks(text):
    """{(table, key): (the comment block right above the assignment, its value)} for every assignment of the file
    (a profile's table named profiles.<id>, the top level ""); a blank line or a table line ends a block."""
    assert tomllib is not None
    out, table, pid, block = {}, "", None, []
    for line in text.splitlines():
        if not line.strip():
            block = []
        elif line.startswith("#"):
            block.append(line)
        elif _TABLE.match(line):
            table, pid, block = _TABLE.match(line).group(1), None, []
        else:
            m = _ASSIGN.match(line)
            assert m, line
            if table == "profiles" and m.group(1) == "id":
                pid = int(m.group(2))
            where = "profiles.%s" % pid if table == "profiles" else table
            assert (where, m.group(1)) not in out, (where, m.group(1))
            out[(where, m.group(1))] = (block, tomllib.loads("v = " + m.group(2))["v"])
            block = []
    return out


@NEEDS_TOML
def test_profiles_ctl_toml_is_spec_2_3s_table_value_for_value():
    """Spec 2.3 and section 3 item 3: the file is the table, typed (2790 is an int, 25.0 a float), both profiles compiled
    with no stand-in; steer_max the gate's 1.0 rad and not the vehicle's 0.70 rad, v_max the nominal filter's 25.0 and
    not the transition filter's 50.0 (the two choices 2.3 makes by D6's rule)."""
    assert _typed(_ctl_doc()) == _typed(_expected())
    p1 = _row(_ctl_doc(), 1)
    assert p1["steer_max"] == 1.0 != 0.70 and p1["v_max"] == 25.0 != 50.0
    assert gen.check_ctl_profiles(_ctl_doc()) == []


@NEEDS_TOML
def test_the_read_values_are_marked_and_each_comment_names_its_parameter_and_fact():
    """Section 3 item 3 on the PROBED pattern: every READ value has a comment block starting `# READ (` right above it,
    which names its parameter and W4's fact id; no other value is so marked; the two design values that rest on a READ
    parameter name it too, and every value of the file has a comment block (its reason)."""
    blocks = _blocks(PROFILES_CTL.read_text(encoding="utf-8"))
    marked = {k: v for k, (block, v) in blocks.items() if block and _MARKER.match(block[0])}
    assert marked == READ and all(type(marked[k]) is type(v) for k, v in READ.items())
    for key, (fact, parameter) in list(READ_SOURCES.items()) + list(DESIGN_SOURCES.items()):
        text = " ".join(" ".join(ln.lstrip("#").strip() for ln in blocks[key][0]).split())
        assert fact in text and parameter in text, (key, text)
    for key in list(READ) + [k for k in DESIGN if k != ("", "format")]:
        assert blocks[key][0], "no comment says why %s.%s is what it is" % key


# ============================================================ pure: every refusal of 2.3

def _stand_in_row(**changes):
    """A synthetic uncompiled profile 3 with a stand-in value: the case 2.3 refuses compiled and keeps out of vss_ctl.h."""
    row = dict(copy.deepcopy(_row(_expected(), 1)), id=3, source="design", steer_max=0.5, stand_in=["steer_max"],
               compiled=False)
    row.update(changes)
    return row


def _drop(d, key):
    d.pop(key)


CTL_MUTATIONS = {
    "an [invariants] table": (lambda d: d.update(invariants={"steer_max_limit": 2.0}), "[invariants]"),
    "a relaxed bound in an [invariants] table": (lambda d: (d.update(invariants={"l_mm_max": 60000}), _row(d, 1).update(l_mm=59000)),
                                                 "1000..6000"),
    "format 2": (lambda d: d.update(format=2), "format must be 1"),
    "format a bool": (lambda d: d.update(format=True), "format must be 1"),
    "an unknown top-level key": (lambda d: d.update(dt_max=100), "unknown top-level key"),
    "id 0": (lambda d: _row(d, 1).update(id=0), "id must be an integer in 1..255"),
    "id 256": (lambda d: _row(d, 2).update(id=256), "id must be an integer in 1..255"),
    "id not an integer": (lambda d: _row(d, 2).update(id=2.0), "id must be an integer in 1..255"),
    "a repeated id": (lambda d: _row(d, 2).update(id=1), "id is not unique"),
    "an unknown profile key": (lambda d: _row(d, 1).update(steer_maximum=1.0), "unknown key"),
    "a source neither gate-dump nor design": (lambda d: _row(d, 1).update(source="measured"), "source must be one of"),
    "l_mm below 1000": (lambda d: _row(d, 1).update(l_mm=999), "l_mm must be an integer in 1000..6000"),
    "l_mm above 6000": (lambda d: _row(d, 2).update(l_mm=6001), "l_mm must be an integer in 1000..6000"),
    "l_mm not integral": (lambda d: _row(d, 1).update(l_mm=2790.5), "l_mm must be an integer in 1000..6000"),
    "l_mm a bool": (lambda d: _row(d, 1).update(l_mm=True), "l_mm must be an integer in 1000..6000"),
    "v_max 0": (lambda d: _row(d, 1).update(v_max=0.0), "v_max must be a finite number > 0"),
    "a_max negative": (lambda d: _row(d, 1).update(a_max=-5.0), "a_max must be a finite number > 0"),
    "jerk_max 0": (lambda d: _row(d, 2).update(jerk_max=0.0), "jerk_max must be a finite number > 0"),
    "steer_rate_max 0": (lambda d: _row(d, 1).update(steer_rate_max=0.0), "steer_rate_max must be a finite number > 0"),
    "steer_rate_max negative": (lambda d: _row(d, 2).update(steer_rate_max=-1.0), "steer_rate_max must be a finite number > 0"),
    "lat_acc_max 0": (lambda d: _row(d, 1).update(lat_acc_max=0.0), "lat_acc_max must be a finite number > 0"),
    "lat_acc_max NaN": (lambda d: _row(d, 1).update(lat_acc_max=float("nan")), "lat_acc_max must be a finite number > 0"),
    "lat_acc_max infinite": (lambda d: _row(d, 1).update(lat_acc_max=float("inf")), "lat_acc_max must be a finite number > 0"),
    "v_max infinite": (lambda d: _row(d, 1).update(v_max=float("inf")), "v_max must be a finite number > 0"),
    "a limit not a number": (lambda d: _row(d, 1).update(a_max="5.0"), "must be numbers"),
    "steer_max 1.01": (lambda d: _row(d, 1).update(steer_max=1.01), "steer_max must be in (0, 1.0] rad"),
    "steer_max one binary32 step above 1.0": (lambda d: _row(d, 1).update(steer_max=1.0000001192092896), "steer_max must be in (0, 1.0] rad"),
    "steer_max 1.5": (lambda d: _row(d, 2).update(steer_max=1.5), "steer_max must be in (0, 1.0] rad"),
    "v_max not exact in binary32": (lambda d: _row(d, 1).update(v_max=25.1), "v_max = 25.1 is not exactly representable in binary32"),
    "a_max not exact in binary32": (lambda d: _row(d, 1).update(a_max=5.1), "a_max = 5.1 is not exactly representable in binary32"),
    "jerk_max not exact in binary32": (lambda d: _row(d, 1).update(jerk_max=80.1), "jerk_max = 80.1 is not exactly representable"),
    "steer_max 0.70, not exact in binary32": (lambda d: _row(d, 1).update(steer_max=0.7), "steer_max = 0.7 is not exactly representable"),
    "steer_rate_max not exact in binary32": (lambda d: _row(d, 1).update(steer_rate_max=0.3), "steer_rate_max = 0.3 is not exactly"),
    "a limit past binary32's range": (lambda d: _row(d, 1).update(jerk_max=1e39), "jerk_max = 1e+39 is not exactly representable"),
    "dt_max_ms 0": (lambda d: d.update(dt_max_ms=0), "dt_max_ms must be an integer in 1..0xFFFE"),
    "dt_max_ms 0xFFFF": (lambda d: d.update(dt_max_ms=0xFFFF), "dt_max_ms must be an integer in 1..0xFFFE"),
    "dt_max_ms not an integer": (lambda d: d.update(dt_max_ms=100.0), "dt_max_ms must be an integer in 1..0xFFFE"),
    "a constant negative": (lambda d: d.update(tol17=-0.5), "tol17 must be a finite number >= 0"),
    "a constant not a number": (lambda d: d.update(rollback_v="0.5"), "rollback_v must be a finite number >= 0"),
    "a constant missing": (lambda d: _drop(d, "overspeed_margin"), "overspeed_margin must be a finite number >= 0"),
    "a constant infinite": (lambda d: d.update(overspeed_factor=float("inf")), "overspeed_factor must be a finite number >= 0"),
    # A TOML integer has no bound in tomllib: one past a double's range is no value either file can carry.
    "a constant past a double's range": (lambda d: d.update(tol17=10 ** 400), "tol17 must be a finite number >= 0"),
    "a limit past a double's range": (lambda d: _row(d, 1).update(lat_acc_max=10 ** 400), "lat_acc_max must be a finite number > 0"),
    "a binary32 limit past a double's range": (lambda d: _row(d, 2).update(v_max=10 ** 400), "v_max must be a finite number > 0"),
    "a run window of 0": (lambda d: _row(d, 2).update(run_window_max_ms=0), "run_window_max_ms must be absent or a positive integer"),
    "a run window not an integer": (lambda d: _row(d, 2).update(run_window_max_ms=30000.0), "run_window_max_ms must be absent"),
    "compiled not a bool": (lambda d: _row(d, 1).update(compiled=1), "compiled must be true or false"),
    "a stand-in naming no field": (lambda d: d["profiles"].append(_stand_in_row(stand_in=["steer_maximum"])),
                                   "stand_in must be a list of this table's field names"),
    "a stand-in compiled": (lambda d: d["profiles"].append(_stand_in_row(compiled=True)), "must not be compiled"),
    "profile 2 compiled without its window": (lambda d: _drop(_row(d, 2), "run_window_max_ms"), "profile 2 is compiled without run_window_max_ms"),
    "no compiled profile": (lambda d: [p.update(compiled=False) for p in d["profiles"]], "no compiled profile"),
    "no profile at all": (lambda d: d.update(profiles=[]), "no compiled profile"),
}


@NEEDS_TOML
@pytest.mark.parametrize("name", sorted(CTL_MUTATIONS))
def test_every_refusal_of_profiles_ctl_toml(name):
    doc = copy.deepcopy(_ctl_doc())
    mutate, why = CTL_MUTATIONS[name]
    mutate(doc)
    problems = gen.check_ctl_profiles(doc)
    assert any(why in p for p in problems), problems


@NEEDS_TOML
@pytest.mark.parametrize("changes", [{"steer_max": 1.0}, {"steer_max": 2.0 ** -24}, {"l_mm": 1000}, {"l_mm": 6000}, {"id": 255},
                                     {"lat_acc_max": 5.1}],
                         ids=["steer_max 1.0", "steer_max 2**-24", "l_mm 1000", "l_mm 6000", "id 255",
                              "lat_acc_max off the binary32 grid"])
def test_a_profile_value_exactly_at_a_bound_is_accepted(changes):
    """2.3: steer_max in (0, 1.0], so 1.0 and a small binary32 power of two (2**-24) are taken; l_mm 1000..6000 inclusive;
    an id of 1..255 inclusive (row 1 becomes 255 beside profile 2); lat_acc_max is compared in double with TOL17 added
    (rule 17), not as an f32 field, so it needs no binary32 value."""
    doc = copy.deepcopy(_ctl_doc())
    _row(doc, 1).update(changes)
    assert gen.check_ctl_profiles(doc) == []


@NEEDS_TOML
@pytest.mark.parametrize("dt", [1, 0xFFFE])
def test_dt_max_ms_at_its_bounds_is_accepted(dt):
    doc = copy.deepcopy(_ctl_doc())
    doc["dt_max_ms"] = dt
    assert gen.check_ctl_profiles(doc) == []


@NEEDS_TOML
@pytest.mark.parametrize("k", ["tol17", "overspeed_factor", "overspeed_margin", "rollback_v"])
def test_a_constant_of_0_is_accepted(k):
    """The four constants are 'a finite number >= 0' (the refusal text says so): 0 itself is a value, not a refusal."""
    doc = copy.deepcopy(_ctl_doc())
    doc[k] = 0.0
    assert gen.check_ctl_profiles(doc) == []


def test_the_bounds_are_constants_of_the_generator():
    """The bounds profiles-ctl.toml is checked against are generate.py's, never the file's (as kind 4's, spec 5.4)."""
    assert gen.CTL_STEER_MAX_LIMIT == 1.0 and gen.CTL_DT_MAX_MS_MAX == 0xFFFE and (gen.L_MM_MIN, gen.L_MM_MAX) == (1000, 6000)
    assert gen.CTL_F32_LIMITS == ("v_max", "a_max", "jerk_max", "steer_max", "steer_rate_max")
    text = PROFILES_CTL.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(steer_max_limit|dt_max_ms_max|l_mm_min|l_mm_max)\s*=", text, re.M)


# ============================================================ pure: the digest and the renderers

FIXTURE_UIDS = (0xC7100001, 0xC7100002, 0xC7100003, 0xC7100004, 0xC7100005, 0xC7100006, 0xC7100007)
FIXTURE_NODES = tuple({"type": "sensor", "datatype": dt, "unit": u}
                      for dt, u in zip(SLOT_DATATYPES, ("m/s", "m/s^2", "m/s^3", "rad", "rad/s", "m/s", "ms")))


def _fixture_doc():
    """The fixtures' table (tests/fixtures/ctl-py/vss_ctl.py, tests/fixtures/ctl-c/vss_ctl.h) as a profiles-ctl.toml:
    their profiles 1 and 2 compiled, their profile 3 uncompiled with a stand-in."""
    rows = copy.deepcopy(_expected()["profiles"])
    rows.append(_stand_in_row())
    return {"format": 1, "dt_max_ms": 200, "tol17": 0.5, "overspeed_factor": 1.2, "overspeed_margin": 2.0, "rollback_v": 0.5,
            "profiles": rows}


def _fixture_ctx():
    return {"slot_paths": SLOT_PATHS, "slot_nodes": FIXTURE_NODES, "slot_uids": FIXTURE_UIDS,
            "digest": gen.ctl_digest(FIXTURE_UIDS), "doc": _fixture_doc()}


def test_the_digest_is_fnv1_32_over_the_seven_uids_as_little_endian_u32_in_slot_order():
    uids = FIXTURE_UIDS
    by_hand = _fnv1_32(struct.pack("<7I", *uids))
    assert gen.ctl_digest(uids) == by_hand == 0x682F2F02            # the fixtures' digest, which they wrote by hand
    assert by_hand != _fnv1_32(struct.pack(">7I", *uids)), "big-endian bytes give another digest"
    assert by_hand != _fnv1_32(struct.pack("<6I", *uids[:6])), "six UIDs give another digest"
    assert gen.ctl_digest(uids[::-1]) != by_hand, "another slot order gives another digest"
    with pytest.raises(gen.Refusal):
        gen.ctl_digest(uids[:6])


@pytest.mark.parametrize("digest", [0x00000000, 0xFFFFFFFF])
def test_a_forbidden_kind_2_digest_is_refused_by_kind_4s_check(digest):
    with pytest.raises(gen.Refusal, match="the kind 2 digest is 0x%08X, which is forbidden" % digest):
        gen.check_digest(digest, "kind 2 digest")
    assert gen.check_digest(0x682F2F02, "kind 2 digest") == 0x682F2F02


def test_the_slots_are_spec_2_4s_seven_in_slot_order():
    assert gen.ctl_slot_paths(gen.DEFAULT_BRANCH) == SLOT_PATHS
    assert tuple(dt for _p, _t, dt in gen.CTL_SLOTS) == SLOT_DATATYPES and all(t == "sensor" for _p, t, _d in gen.CTL_SLOTS)
    assert gen.ctl_slot_paths(gen.DEFAULT_BRANCH)[5] == gen.slot_paths(gen.DEFAULT_BRANCH)[0], "slot 5 is kind 4's slot 0"
    assert gen.CTL_FILES == ("vss_ctl.h", "vss_ctl.py") and all(f in gen.OUT_FILES for f in gen.CTL_FILES)


@NEEDS_TOML
def test_the_header_renderer_gives_the_fixture_headers_macros_on_the_fixtures_values():
    """2.4's C names exactly (WP1a's fixture header, written by hand, is the reference): the same name set and, on the
    same values, the same macro values; the uncompiled stand-in row stays out of the table."""
    text = gen.render_c_ctl(_fixture_ctx())
    assert "\r" not in text and text.endswith("\n")
    got, want = _macros(text), _macros(C_FIXTURE.read_text(encoding="ascii"))
    assert sorted(got) == sorted(want)
    assert got == want
    assert "X(3u," not in text.split()


@NEEDS_TOML
def test_the_python_renderer_gives_the_fixture_modules_names_and_values_and_passes_wp2s_loader(tmp_path):
    """2.4's Python names exactly (WP2's fixture module is the reference), each value of the same type; every profile with
    its nine keys, the stand-in row uncompiled; and WP2's loader (sdv/ctl/ctlframe.py) takes it."""
    path = tmp_path / "vss_ctl.py"
    path.write_text(gen.render_python_ctl(_fixture_ctx()), encoding="utf-8")
    got, want = _load("vss_ctl_rendered", path), _load("vss_ctl_fixture", PY_FIXTURE)
    assert sorted(n for n in vars(got) if n.isupper()) == sorted(PY_NAMES) == sorted(n for n in vars(want) if n.isupper())
    for name in PY_NAMES:
        assert _typed(getattr(got, name)) == _typed(getattr(want, name)), name
    assert _ctlframe().load_contract(path).DIGEST == 0x682F2F02
    assert sorted(p for p in tmp_path.iterdir()) == [path], "loading it left no bytecode"


@NEEDS_TOML
def test_each_constant_and_limit_reaches_its_own_name_in_both_files(tmp_path):
    """A variant table whose four constants and six limits all differ (the real table and the fixtures share 0.5 for TOL17
    and ROLLBACK_V, 5.0 for a_max and lat_acc_max, 1.0 for steer_max and steer_rate_max), so a renderer that swaps two
    names or two columns is seen; every value is exact in binary32 and passes the refusals."""
    doc = copy.deepcopy(_fixture_doc())
    doc.update(dt_max_ms=150, tol17=0.25, overspeed_factor=1.25, overspeed_margin=2.5, rollback_v=0.75)
    _row(doc, 1).update(l_mm=2700, v_max=10.0, a_max=2.0, jerk_max=40.0, steer_max=0.5, steer_rate_max=0.25, lat_acc_max=3.0)
    assert gen.check_ctl_profiles(doc) == []
    ctx = dict(_fixture_ctx(), doc=doc)
    macros = _macros(gen.render_c_ctl(ctx))
    assert [macros["VSS_CTL_" + n] for n in ("DT_MAX_MS", "TOL17", "OVERSPEED_FACTOR", "OVERSPEED_MARGIN", "ROLLBACK_V")] == [
        "150u", "0.25", "1.25", "2.5", "0.75"]
    assert macros["VSS_CTL_PROFILE_TABLE"].startswith("X(1u, 2700u, 10.0, 2.0, 40.0, 0.5, 0.25, 3.0) X(2u, "), macros
    path = tmp_path / "vss_ctl.py"
    path.write_text(gen.render_python_ctl(ctx), encoding="utf-8")
    mod = _load("vss_ctl_variant", path)
    assert (mod.DT_MAX_MS, mod.TOL17, mod.OVERSPEED_FACTOR, mod.OVERSPEED_MARGIN, mod.ROLLBACK_V) == (150, 0.25, 1.25, 2.5, 0.75)
    assert mod.PROFILES[1] == {"l_mm": 2700, "v_max": 10.0, "a_max": 2.0, "jerk_max": 40.0, "steer_max": 0.5, "steer_rate_max": 0.25,
                               "lat_acc_max": 3.0, "run_window_max_ms": None, "compiled": True}


@NEEDS_TOML
def test_a_stand_in_is_never_compiled_but_listed_in_the_python_module(tmp_path):
    doc = copy.deepcopy(_ctl_doc())
    doc["profiles"].append(_stand_in_row())
    assert gen.check_ctl_profiles(doc) == []
    assert [p["id"] for p in gen.ctl_compiled_profiles(doc)] == [1, 2]
    ctx = dict(_fixture_ctx(), doc=doc)
    assert "X(3u," not in gen.render_c_ctl(ctx).split() and _macros(gen.render_c_ctl(ctx))["VSS_CTL_PROFILE_IDS"] == '"1 2"'
    path = tmp_path / "vss_ctl.py"
    path.write_text(gen.render_python_ctl(ctx), encoding="utf-8")
    mod = _load("vss_ctl_stand_in", path)
    assert mod.PROFILES[3]["compiled"] is False and mod.COMPILED_PROFILE_IDS == (1, 2)


# ============================================================ pure: the ControlCommand layer's own checks

def _crafted():
    """A crafted catalogue with the layer's shape: the id exports without and with the layer, the layer's two entries,
    the JSON export without it (the mapping) and with it."""
    base = {"Vehicle": {"type": "branch", "staticUID": "0x00000001"},
            "Vehicle.DualVm": {"type": "branch", "staticUID": "0x00000002"},
            "Vehicle.DualVm.Motion": {"type": "branch", "staticUID": "0x00000003"},
            "Vehicle.DualVm.Motion.LongitudinalVelocity": {"type": "sensor", "datatype": "float", "unit": "m/s", "staticUID": "0x00000004"}}
    entries = {CC: {"type": "branch", "description": "b"},
               CC + ".Velocity": {"type": "sensor", "datatype": "float", "unit": "m/s", "description": "v"}}
    ids_ctl = dict(copy.deepcopy(base), **{CC: {"type": "branch", "staticUID": "0x00000005"},
                                          CC + ".Velocity": {"type": "sensor", "datatype": "float", "unit": "m/s", "staticUID": "0x00000006"}})
    motion = {"type": "branch", "children": {"LongitudinalVelocity": {"type": "sensor", "datatype": "float", "unit": "m/s"}}}
    mapping = {"Vehicle": {"type": "branch", "children": {"DualVm": {"type": "branch", "children": {"Motion": motion}}}}}
    tree = copy.deepcopy(mapping)
    tree["Vehicle"]["children"]["DualVm"]["children"]["ControlCommand"] = {
        "type": "branch", "description": "b",
        "children": {"Velocity": {"type": "sensor", "datatype": "float", "unit": "m/s", "description": "v"}}}
    return base, ids_ctl, entries, tree, mapping


def _ctl_problems(base, ids_ctl, entries, tree, mapping):
    return gen.ctl_layer_problems(base, ids_ctl, entries, tree, mapping, gen.DEFAULT_BRANCH)


def test_a_control_command_layer_that_adds_its_entries_alone_passes():
    assert _ctl_problems(*_crafted()) == []


def test_a_control_command_layer_with_a_dbc2vss_block_is_refused():
    base, ids_ctl, entries, tree, mapping = _crafted()
    entries[CC + ".Velocity"]["dbc2vss"] = {"signal": "LongVel"}
    assert any("carries a dbc2vss block" in p for p in _ctl_problems(base, ids_ctl, entries, tree, mapping))


def test_a_control_command_layer_entry_outside_its_branch_is_refused():
    base, ids_ctl, entries, tree, mapping = _crafted()
    entries["Vehicle.DualVm.Motion.Extra"] = {"type": "sensor", "datatype": "float", "unit": "m/s", "description": "x"}
    # a sibling whose name only begins with the branch's name is outside it too: the branch is its path and a dot
    entries[CC + "X"] = {"type": "sensor", "datatype": "float", "unit": "m/s", "description": "x"}
    problems = _ctl_problems(base, ids_ctl, entries, tree, mapping)
    assert any(p.startswith("Vehicle.DualVm.Motion.Extra:") and "outside Vehicle.DualVm.ControlCommand" in p for p in problems), problems
    assert any(p.startswith("Vehicle.DualVm.ControlCommandX: overlay-ctl.vspec entry outside Vehicle.DualVm.ControlCommand")
               for p in problems), problems


def test_a_control_command_layer_that_moves_another_node_is_refused():
    base, ids_ctl, entries, tree, mapping = _crafted()
    ids_ctl["Vehicle.DualVm.Motion.LongitudinalVelocity"]["staticUID"] = "0x0000000F"
    assert any(p.startswith("Vehicle.DualVm.Motion.LongitudinalVelocity: the ControlCommand layer changed")
               for p in _ctl_problems(base, ids_ctl, entries, tree, mapping))


def test_a_control_command_layer_whose_catalogue_gains_another_node_is_refused():
    base, ids_ctl, entries, tree, mapping = _crafted()
    ids_ctl[CC + ".Extra"] = {"type": "sensor", "datatype": "float", "unit": "m/s", "staticUID": "0x00000007"}
    assert any("added nodes that are not its entries" in p for p in _ctl_problems(base, ids_ctl, entries, tree, mapping))


def test_a_control_command_json_export_listing_other_nodes_than_its_id_export_is_refused():
    base, ids_ctl, entries, tree, mapping = _crafted()
    del tree["Vehicle"]["children"]["DualVm"]["children"]["ControlCommand"]["children"]["Velocity"]
    assert any("the ctl JSON export and the ctl id export list different nodes" in p
               for p in _ctl_problems(base, ids_ctl, entries, tree, mapping))


def test_a_control_command_entry_that_does_not_reach_the_catalogue_as_written_is_refused():
    base, ids_ctl, entries, tree, mapping = _crafted()
    ids_ctl[CC + ".Velocity"]["unit"] = "km/h"
    assert any("unit is 'km/h' in the id output, 'm/s' in the overlay" in p for p in _ctl_problems(base, ids_ctl, entries, tree, mapping))


def test_a_databroker_catalogue_that_differs_from_the_mapping_beyond_control_command_is_refused():
    base, ids_ctl, entries, tree, mapping = _crafted()
    tree["Vehicle"]["children"]["DualVm"]["children"]["Motion"]["description"] = "moved"
    assert any("differs from the mapping JSON beyond the ControlCommand branch" in p
               for p in _ctl_problems(base, ids_ctl, entries, tree, mapping))


# ============================================================ pure: the early refusal, end to end

@NEEDS_TOML
def test_a_refused_profiles_ctl_toml_stops_the_run_before_the_venv_and_any_export(tmp_path):
    """Section 2.3: generate.py exits 1 and writes nothing; the profile files are checked right after the archive, so a
    refused one costs no vss-tools run (a venv that does not exist is never reached, no extraction cache is made)."""
    archive = _archive()
    bad = tmp_path / "profiles-ctl.toml"
    bad.write_text(PROFILES_CTL.read_text(encoding="utf-8").replace("dt_max_ms = 100\n", "dt_max_ms = 65535\n", 1),
                   encoding="utf-8", newline="\n")
    assert bad.read_text(encoding="utf-8") != PROFILES_CTL.read_text(encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", str(GENERATE), "--profiles-ctl", str(bad), "--archive", str(archive),
                        "--cache", str(tmp_path / "cache"), "--venv", str(tmp_path / "no-venv"), "--out", str(tmp_path / "out"),
                        "--no-previous"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "profiles-ctl.toml: dt_max_ms must be an integer in 1..0xFFFE" in r.stderr and "venv" not in r.stderr
    assert not (tmp_path / "out").exists() and not (tmp_path / "cache").exists()


@NEEDS_TOML
@pytest.mark.parametrize("name,old,new,why", [
    ("profiles-ctl.toml", "lat_acc_max = 5.0\n", "lat_acc_max = 1%s\n" % ("0" * 400),
     "profiles-ctl.toml: profile 1: lat_acc_max must be a finite number > 0"),
    ("profiles-ctl.toml", "dt_max_ms = 100\n", "dt_max_ms = = 100\n", "profiles-ctl.toml: not valid TOML ("),
    ("profiles.toml", "carla_step_ms = 50\n", "carla_step_ms = = 50\n", "profiles.toml: not valid TOML ("),
], ids=["an integer past a double", "profiles-ctl.toml not TOML", "profiles.toml not TOML"])
def test_a_profile_file_the_generator_cannot_read_is_refused_with_its_reason_not_a_traceback(tmp_path, name, old, new, why):
    """generate.py's refusal line (exit 1, nothing written, before the venv) also for the two inputs that reach no check of
    2.3: an integer that no double holds (tomllib bounds no integer) and a file that is not TOML at all, in either profile
    file (one loader reads both)."""
    archive = _archive()
    src = PROFILES_CTL if name == "profiles-ctl.toml" else VSSDIR / "profiles.toml"
    text = src.read_text(encoding="utf-8")
    assert old in text
    bad = tmp_path / name
    bad.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    r = subprocess.run([sys.executable, "-B", str(GENERATE), "--profiles-ctl" if name == "profiles-ctl.toml" else "--profiles",
                        str(bad), "--archive", str(archive), "--cache", str(tmp_path / "cache"), "--venv", str(tmp_path / "no-venv"),
                        "--out", str(tmp_path / "out"), "--no-previous"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "generate.py: REFUSED: " + why in r.stderr and "Traceback" not in r.stderr, r.stderr
    assert not (tmp_path / "out").exists() and not (tmp_path / "cache").exists()


# ============================================================ against a generation (the vss-tools venv)

_DRIVER = r"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("generate_under_test", sys.argv[1])
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
exec(sys.argv[2])
sys.exit(g.main(sys.argv[3:]))
"""


def _run(tmp_path, *args, patch=None):
    """generate.py in the venv, the pinned archive read where it is, the extraction under tmp_path, never the
    committed baseline rewritten (no run here accepts a UID change)."""
    _need_venv()
    argv = [str(a) for a in args] + ["--archive", str(_archive()), "--cache", str(tmp_path / "cache")]
    assert "--accept-uid-change" not in argv
    head = [str(VENV_PY), "-B", str(GENERATE)] if patch is None else [str(VENV_PY), "-B", "-c", _DRIVER, str(GENERATE), patch]
    return subprocess.run(head + argv, capture_output=True, text=True, timeout=900)


class _Generation:
    """ctlgen's value: "proc" is generate.py's CompletedProcess; "out", "stdout", "ctl", "contract" and "broker" are read
    on first use, and each use first asserts that the run exited 0, with its stderr. So a refused generation fails each
    test that reads it, in that test's body, with generate.py's reason; the fixture asserts nothing about the run (it
    still skips, or fails under SDV_REQUIRE_GEN=1, when the venv or the archive is missing)."""

    KEYS = ("out", "stdout", "ctl", "contract", "broker")

    def __init__(self, out, proc):
        self.out, self.proc, self.loaded = out, proc, None

    def __getitem__(self, key):
        if key == "proc":
            return self.proc
        if key not in self.KEYS:
            raise KeyError(key)
        assert self.proc.returncode == 0, self.proc.stderr
        if self.loaded is None:
            out = self.out
            self.loaded = {"out": out, "stdout": self.proc.stdout, "ctl": _ctlframe().load_contract(out),
                           "contract": _load("vss_contract_for_ctl", out / "vss_contract.py"),
                           "broker": json.loads((out / "vss-databroker.json").read_text(encoding="utf-8"))}
        return self.loaded[key]


@pytest.fixture(scope="session")
def ctlgen(tmp_path_factory):
    work = tmp_path_factory.mktemp("ctlgen")
    out = work / "gen"
    return _Generation(out, _run(work, "--out", out, "--no-previous"))


def test_a_refused_generation_fails_the_test_that_reads_it_and_never_the_fixture(tmp_path):
    """ctlgen hands each test the generation's process and loads the outputs on first use, so a refused run fails every
    test that reads an output, in that test's body and with generate.py's reason; the fixture asserts nothing about the
    run (a mutation that makes the generation refuse is then a failed test, not an error of setup)."""
    proc = subprocess.CompletedProcess(["generate.py"], 1, "", "generate.py: REFUSED: the reason\n")
    run = _Generation(tmp_path / "gen", proc)
    assert run["proc"] is proc
    for key in ("out", "stdout", "ctl", "contract", "broker"):
        with pytest.raises(AssertionError, match="generate.py: REFUSED: the reason"):
            run[key]
    with pytest.raises(KeyError):
        _Generation(tmp_path / "gen", subprocess.CompletedProcess(["generate.py"], 0, "", ""))["nothing"]


def test_the_generation_writes_the_kind_2_contract_and_records_it_in_the_manifest(ctlgen):
    """Spec 2.2: vss_ctl.h and vss_ctl.py beside today's outputs; manifest.json's ctl_contract exactly as 2.2 writes it,
    both files' outputs entries, and the four new inputs' sha256; the run says the kind 2 digest."""
    out, ctl = ctlgen["out"], ctlgen["ctl"]
    assert sorted(p.name for p in out.iterdir()) == sorted(gen.OUT_FILES)
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert man["ctl_contract"] == {"format": 1, "digest": "0x%08X" % ctl.DIGEST, "files": ["vss_ctl.h", "vss_ctl.py"],
                                   "profiles_ctl_sha256": _sha256(PROFILES_CTL.read_bytes())}
    for name in ("vss_ctl.h", "vss_ctl.py"):
        data = (out / name).read_bytes()
        assert man["outputs"][name] == {"sha256": _sha256(data), "bytes": len(data)} and b"\r" not in data, name
    for name, path in (("overlay-ctl.vspec", OVERLAY_CTL), ("units-project.yaml", UNITS_PROJECT),
                       ("quantities-project.yaml", VSSDIR / "quantities-project.yaml"), ("profiles-ctl.toml", PROFILES_CTL)):
        assert man["inputs"][name] == _sha256(path.read_bytes()), name
    assert "generate.py: kind 2 digest 0x%08X" % ctl.DIGEST in ctlgen["stdout"]


def test_the_unchanged_set_is_byte_for_byte_the_base_trees(ctlgen):
    """Spec 2.2 and section 3 item 2: vss_contract.h, both vehicle layers, the CAN mapping and the id file are the base
    tree's, byte for byte (so is the kind 4 digest, which vss_contract.h carries); each databroker catalogue is the base
    tree's but for the ControlCommand branch it now serves. tests/test_sdv_vss.py holds vss_contract.py and
    vss_profiles.h (BASE_KIND4_SHA256)."""
    out = ctlgen["out"]
    assert {n: _sha256((out / n).read_bytes()) for n in BASE_SHA256} == BASE_SHA256
    for name, sha in BASE_BROKER_SHA256.items():
        tree = json.loads((out / name).read_text(encoding="utf-8"))
        assert "ControlCommand" in tree["Vehicle"]["children"]["DualVm"]["children"], name
        assert _sha256(_without_control_command(tree)) == sha, name
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert man["kind4"]["catalog_digest"] == "0x%08X" % ctlgen["contract"].CATALOG_DIGEST
    assert gen.parse_baseline(UID_BASELINE.read_text(encoding="utf-8"))[0] == ctlgen["contract"].CATALOG_DIGEST


def test_a_kind_4_profile_change_moves_no_file_this_module_pins_and_neither_kind_2_file(ctlgen, tmp_path):
    """Spec-2 2.2: WP3b's profile 4 changes vss_contract.py and vss_profiles.h and leaves vss_ctl.h, vss_ctl.py and every
    sigsim and carla output byte for byte. A kind 4 profile change of that sort (a variant profiles.toml: profile 2's a_max
    10.0 -> 9.0, a compiled profile that is no live default and enters no budget) must then leave this module's pins
    green: everything BASE_SHA256 and BASE_BROKER_SHA256 hold, and both kind 2 files, are the real generation's, while the
    two kind 4 files do move. Those two are pinned in tests/test_sdv_vss.py (BASE_KIND4_SHA256), which WP3b owns after
    this package (spec-2 section 12) and re-records when its profile 4 moves them."""
    profiles = VSSDIR / "profiles.toml"
    old = "v_max = 10.0\na_max = 10.0\n"
    text = profiles.read_text(encoding="utf-8")
    assert text.count(old) == 1, "profile 2's v_max and a_max lines"
    variant = tmp_path / "profiles.toml"
    variant.write_text(text.replace(old, "v_max = 10.0\na_max = 9.0\n"), encoding="utf-8", newline="\n")
    r = _run(tmp_path, "--profiles", variant, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 0, r.stderr
    out, real = tmp_path / "out", ctlgen["out"]
    assert {n: _sha256((out / n).read_bytes()) for n in BASE_SHA256} == BASE_SHA256
    for name, sha in BASE_BROKER_SHA256.items():
        assert _sha256(_without_control_command(json.loads((out / name).read_text(encoding="utf-8")))) == sha, name
    for name in gen.CTL_FILES:
        assert (out / name).read_bytes() == (real / name).read_bytes(), name
    for name in ("vss_contract.py", "vss_profiles.h"):
        assert (out / name).read_bytes() != (real / name).read_bytes(), "%s did not move: the variant is no kind 4 change" % name


def test_the_seven_slot_uids_and_the_digest_by_hand_from_the_catalogue(ctlgen):
    """Spec 2.2: the UIDs are read from the generated catalogue as kind 4's are; recomputed here from each node's own
    attributes in the databroker catalogue by vss-tools' identifier rule, and the digest over them by hand. Slot 5 is the
    kind 4 slot 0 node, so its UID is kind 4's."""
    ctl, nodes = ctlgen["ctl"], _json_nodes(ctlgen["broker"])
    assert ctl.SLOT_PATHS == SLOT_PATHS
    assert ctl.SLOT_UIDS == tuple(_uid_of(p, nodes[p]) for p in SLOT_PATHS)
    assert tuple(nodes[p]["datatype"] for p in SLOT_PATHS) == SLOT_DATATYPES
    assert ctl.SLOT_UIDS[5] == ctlgen["contract"].SLOT_UIDS[0]
    assert ctl.DIGEST == _fnv1_32(struct.pack("<7I", *ctl.SLOT_UIDS)) not in (0, 0xFFFFFFFF)
    macros = _macros((ctlgen["out"] / "vss_ctl.h").read_text(encoding="ascii"))
    assert [macros["VSS_CTL_UID_SLOT%d" % i] for i in range(7)] == ["0x%08Xu" % u for u in ctl.SLOT_UIDS]
    assert macros["VSS_CTL_DIGEST"] == "0x%08Xu" % ctl.DIGEST


def test_the_project_units_reach_every_databroker_catalogue_as_written(ctlgen):
    """D5: rad, rad/s and m/s^3 reach the catalogue as overlay-ctl.vspec writes them (rad and m/s^3 exist only through
    units-project.yaml and quantities-project.yaml); every databroker catalogue serves the eleven ControlCommand nodes."""
    out = ctlgen["out"]
    for name in ("vss-databroker.json", "vss-databroker-carla.json"):
        nodes = _json_nodes(json.loads((out / name).read_text(encoding="utf-8")))
        assert sorted(p for p in nodes if p == CC or p.startswith(CC + ".")) == sorted(CONTROL_COMMAND), name
        for leaf, unit in CTL_UNITS.items():
            assert nodes[CC + "." + leaf]["unit"] == unit, (name, leaf)
        assert all(nodes[p]["type"] in ("branch", "sensor") for p in CONTROL_COMMAND)
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    layer = man["vss_tools"]["ctl_layer"]
    assert layer["overlay"] == "overlay-ctl.vspec" and layer["units"] == ["<v6.0>/spec/units.yaml", "units-project.yaml"]
    assert layer["quantities"] == ["<v6.0>/spec/quantities.yaml", "quantities-project.yaml"]
    assert any("-u units-project.yaml" in c and "-q quantities-project.yaml" in c and "-l overlay.vspec -l overlay-ctl.vspec " in c
               for c in man["commands"])
    # which outputs the layer reaches and which it does not (the manifest's own record, read from the generator's tables so a
    # later package's added catalogue leaves this green without editing it)
    assert layer["loaded_for"] == [gen.DATABROKER_CATALOGUES[rt] for rt in gen.VEHICLE_RUN_TYPES] + ["vss_ctl.h", "vss_ctl.py", "uid-baseline.txt"]
    assert {"vss-databroker.json", "vss-databroker-carla.json"} <= set(layer["loaded_for"])
    assert layer["not_loaded_for"] == ["vss-ids.vspec", "vss-can-mapping.json"]


def test_no_control_command_path_reaches_the_can_mapping_or_the_id_file(ctlgen):
    """Spec 2.2's vss-can-mapping.json byte for byte: no ControlCommand node and no dbc2vss for one. The id file stays the
    kind 4 catalogue's too (vss-ids.vspec is pinned by the twin connector's label; the notes say why)."""
    out = ctlgen["out"]
    mapping = (out / "vss-can-mapping.json").read_text(encoding="utf-8")
    assert "ControlCommand" not in mapping and "ControlCommand" not in (out / "vss-ids.vspec").read_text(encoding="utf-8")
    nodes = _json_nodes(ctlgen["broker"])
    assert not any("dbc2vss" in nodes[p] for p in CONTROL_COMMAND)


def test_the_generated_python_contract_passes_wp2s_loader_and_holds_profiles_ctl_toml(ctlgen):
    ctl, doc = ctlgen["ctl"], _ctl_doc()
    assert sorted(n for n in vars(ctl) if n.isupper() and n != "CONTRACT_PATH") == sorted(PY_NAMES)
    assert ctl.FORMAT == 1 and type(ctl.DT_MAX_MS) is int and ctl.DT_MAX_MS == doc["dt_max_ms"]
    assert (ctl.TOL17, ctl.OVERSPEED_FACTOR, ctl.OVERSPEED_MARGIN, ctl.ROLLBACK_V) == (
        doc["tol17"], doc["overspeed_factor"], doc["overspeed_margin"], doc["rollback_v"])
    want = {p["id"]: dict({k: p[k] for k in ROW_KEYS if k in p}, run_window_max_ms=p.get("run_window_max_ms")) for p in doc["profiles"]}
    assert _typed(ctl.PROFILES) == _typed(want)
    assert ctl.COMPILED_PROFILE_IDS == (1, 2)


def test_the_generated_header_has_the_fixture_headers_names_and_vss_ctl_pys_values(ctlgen):
    ctl = ctlgen["ctl"]
    got = _macros((ctlgen["out"] / "vss_ctl.h").read_text(encoding="ascii"))
    assert sorted(got) == sorted(_macros(C_FIXTURE.read_text(encoding="ascii")))
    assert got["VSS_CTL_FORMAT"] == "1u" and got["VSS_CTL_DT_MAX_MS"] == "%du" % ctl.DT_MAX_MS
    assert [float(got["VSS_CTL_" + n]) for n in ("TOL17", "OVERSPEED_FACTOR", "OVERSPEED_MARGIN", "ROLLBACK_V")] == [
        ctl.TOL17, ctl.OVERSPEED_FACTOR, ctl.OVERSPEED_MARGIN, ctl.ROLLBACK_V]
    rows = re.findall(r"X\(([^)]*)\)", got["VSS_CTL_PROFILE_TABLE"])
    assert [int(r.split(",")[0].rstrip("u")) for r in rows] == list(ctl.COMPILED_PROFILE_IDS)
    for r, pid in zip(rows, ctl.COMPILED_PROFILE_IDS):
        cells = [c.strip() for c in r.split(",")]
        p = ctl.PROFILES[pid]
        assert int(cells[1].rstrip("u")) == p["l_mm"]
        assert [float(c) for c in cells[2:]] == [p[k] for k in ROW_KEYS[1:7]]
    assert got["VSS_CTL_PROFILE_COUNT"] == "%du" % len(rows)
    assert got["VSS_CTL_PROFILE_IDS"] == '"%s"' % " ".join(str(i) for i in ctl.COMPILED_PROFILE_IDS)


def test_the_committed_baseline_keeps_every_line_and_gains_the_control_command_lines_only(ctlgen):
    """Spec 2.2's UID lines, with the current publication header: removing ControlCommand lines gives the base
    expectation, the new lines exactly the eleven ControlCommand nodes, each UID vss-tools' identifier of the generated node."""
    text = UID_BASELINE.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    new = [ln for ln in lines if ln.startswith(CC + " ") or ln.startswith(CC + ".")]
    assert _sha256("".join(ln for ln in lines if ln not in new).encode("utf-8")) == BASE_BASELINE_SHA256
    nodes = _json_nodes(ctlgen["broker"])
    assert sorted(ln.split()[0] for ln in new) == sorted(CONTROL_COMMAND)
    for ln in new:
        path, uid = ln.split()
        assert int(uid, 16) == _uid_of(path, nodes[path]), path


def _ctl_overlay_variant(tmp_path, old, new):
    text = OVERLAY_CTL.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    p = tmp_path / "overlay-ctl.vspec"
    p.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
    return p


@pytest.mark.parametrize("old,new,why", [
    ("  unit: rad/s\n", "  unit: rad/s\n  dbc2vss:\n    signal: SteerAngleRow1\n",
     "Vehicle.DualVm.ControlCommand.SteeringTireRotationRate: overlay-ctl.vspec carries a dbc2vss block"),
    ("Vehicle.DualVm.ControlCommand.ProfileId:\n", "Vehicle.DualVm.Motion.ProfileId:\n",
     "Vehicle.DualVm.Motion.ProfileId: overlay-ctl.vspec entry outside Vehicle.DualVm.ControlCommand"),
    ("  datatype: uint16\n  unit: ms\n", "  datatype: uint32\n  unit: ms\n",
     "kind 2 slot 6: Vehicle.DualVm.ControlCommand.StampInterval is sensor uint32, the wire needs sensor uint16"),
    ("Vehicle.DualVm.ControlCommand.Velocity:\n  type: sensor\n", "Vehicle.DualVm.ControlCommand.Velocity:\n  type: actuator\n",
     "kind 2 slot 0: Vehicle.DualVm.ControlCommand.Velocity is actuator float, the wire needs sensor float"),
], ids=["dbc2vss", "outside ControlCommand", "slot datatype", "slot type"])
def test_a_control_command_layer_the_contract_cannot_take_is_refused_end_to_end(ctlgen, tmp_path, old, new, why):
    r = _run(tmp_path, "--overlay-ctl", _ctl_overlay_variant(tmp_path, old, new), "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1, r.stdout + r.stderr
    assert why in r.stderr, r.stderr
    assert not (tmp_path / "out").exists()


def test_unit_files_without_the_layers_units_are_refused_by_vss_tools(ctlgen, tmp_path):
    """The project unit files are what makes rad and m/s^3 units at all (vss-tools 6.0.0 refuses an unknown unit under
    --strict): with a units-project.yaml that defines neither, the generation is refused and writes nothing."""
    units = tmp_path / "units-project.yaml"
    units.write_text("# no unit\n{}\n", encoding="utf-8", newline="\n")
    r = _run(tmp_path, "--units-project", units, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1 and "vss-tools (ctl id export)" in r.stderr, r.stdout + r.stderr
    assert not (tmp_path / "out").exists()


def test_a_forbidden_kind_2_digest_is_refused_end_to_end(ctlgen, tmp_path):
    r = _run(tmp_path, "--out", tmp_path / "out", "--no-previous", patch="g.ctl_digest = lambda uids: 0xFFFFFFFF")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the kind 2 digest is 0xFFFFFFFF, which is forbidden" in r.stderr
    assert not (tmp_path / "out").exists()


# ============================================================ gcc: the header compiled, the native ctl build

def test_the_generated_header_compiles_with_monitor_c_under_0x14_and_the_driver_sees_vss_ctl_py(ctlgen, tmp_path):
    """Section 3 item 7: monitor.c and tests/ctl_driver.c with the ctl build's flags under -Werror, the contract searched
    in the generation alone (no fixture on the include path); `constants` is vss_ctl.py, bit for bit, and the monitor's
    self-check holds the generated contract consistent."""
    gcc, out = _gcc(), ctlgen["out"]
    for src, name in ((MONITOR_C, "monitor"), (CTL_DRIVER_C, "driver")):
        r = subprocess.run([gcc, *CTL_FLAGS, "-I", str(COMMON), "-I", str(out), "-o", str(tmp_path / name), str(src),
                            str(SHM_MAP_POSIX_C), str(IVSHM_CLIENT_C)], capture_output=True, text=True)
        assert r.returncode == 0, "%s must compile clean against the generated vss_ctl.h:\n%s" % (src.name, r.stderr)
    deps = subprocess.run([gcc, "-std=gnu99", "-DMONITOR_EXT_KINDS=0x14", "-I", str(COMMON), "-I", str(out), "-MM", str(MONITOR_C)],
                          check=True, capture_output=True, text=True).stdout
    assert str(out / "vss_ctl.h") in deps, deps
    ctl = ctlgen["ctl"]
    lines = subprocess.run([str(tmp_path / "driver"), "constants"], check=True, capture_output=True, text=True).stdout.splitlines()
    kv = dict(ln.split(" ", 1) for ln in lines if not ln.startswith("profile "))
    assert kv["ext_kinds"] == "0x14" and kv["format"] == "1"
    assert tuple(int(x, 16) for x in kv["uids"].split()) == ctl.SLOT_UIDS
    assert int(kv["digest"], 16) == ctl.DIGEST and int(kv["dt_max_ms"]) == ctl.DT_MAX_MS
    assert [float.fromhex(x) for x in kv["consts"].split()] == [ctl.TOL17, ctl.OVERSPEED_FACTOR, ctl.OVERSPEED_MARGIN, ctl.ROLLBACK_V]
    rows = [ln.split()[1:] for ln in lines if ln.startswith("profile ")]
    assert [int(r[0]) for r in rows] == list(ctl.COMPILED_PROFILE_IDS)
    for r in rows:
        p = ctl.PROFILES[int(r[0])]
        assert int(r[1]) == p["l_mm"] and [float.fromhex(x) for x in r[2:]] == [p[k] for k in ROW_KEYS[1:7]]
    assert kv["ids"] == "%s count %d" % (" ".join(str(i) for i in ctl.COMPILED_PROFILE_IDS), len(rows))
    check = subprocess.run([str(tmp_path / "driver"), "selfcheck"], check=True, capture_output=True, text=True).stdout.split()
    assert check == ["computed", "%08X" % ctl.DIGEST, "header", "%08X" % ctl.DIGEST, "consistent", "1"], check


def test_the_native_ctl_build_announces_the_generations_digest_on_loopback(ctlgen, tmp_path):
    """Section 3 item 7: build-monitor-native.sh with MONITOR_EXT_KINDS=0x14 and the generation, to its own OUT, then the
    binary on a loopback port in `PORT svc 500`: its `ctl rules:` line carries vss_ctl.py's digest and constants and its
    `ctl profile` lines the compiled rows, in spec 2.5's formats."""
    gcc = _gcc()
    out, ctl = ctlgen["out"], ctlgen["ctl"]
    home = tmp_path / "home"
    home.mkdir()
    binary = tmp_path / "out" / "monitor-ctl"
    env = {k: v for k, v in os.environ.items() if k not in ("MONITOR_EXT_KINDS", "MONITOR_VSS_GEN", "OUT", "FORCE")}
    env.update(HOME=str(home), CC=gcc, MONITOR_EXT_KINDS="0x14", MONITOR_VSS_GEN=str(out), OUT=str(binary))
    r = subprocess.run(["bash", str(NATIVE)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert binary.is_file() and not (home / "ladder").exists()
    proc, port = mc._start_on_port(str(binary), ["svc", "500"], socket.SOCK_STREAM, mc.BANNER["svc"])
    rc = proc.stop()
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    lines = [ln.decode("ascii").rstrip("\n") for ln in proc.out]
    rules = ("monitor: ctl rules: kind 2, catalog 0x%08X (vss %s), dt_max %u ms, overspeed %s x v_cmd + %s m/s, rollback %s m/s, "
             "tol17 %s m/s^2, profiles %s" % (ctl.DIGEST, ctlgen["contract"].VSS_VERSION, ctl.DT_MAX_MS, _g(ctl.OVERSPEED_FACTOR),
                                              _g(ctl.OVERSPEED_MARGIN), _g(ctl.ROLLBACK_V), _g(ctl.TOL17),
                                              " ".join(str(i) for i in ctl.COMPILED_PROFILE_IDS)))
    assert rules in lines, lines
    profiles = [ln for ln in lines if ln.startswith("monitor: ctl profile ")]
    want = ["monitor: ctl profile %u: L %u mm, v_max %s m/s, a_max %s m/s^2, jerk_max %s m/s^3, steer_max %s rad, "
            "steer_rate_max %s rad/s, lat_acc_max %s m/s^2" % ((pid, ctl.PROFILES[pid]["l_mm"])
                                                              + tuple(_g(ctl.PROFILES[pid][k]) for k in ROW_KEYS[1:7]))
            for pid in ctl.COMPILED_PROFILE_IDS]
    assert profiles == want
    assert lines.index(rules) == lines.index(profiles[0]) - 1


def _g(x):
    """C's %g of a double, as the monitor prints it (Python's %g is C's)."""
    return "%g" % x


# Claims a header of sdv/vss's inputs made before this package and no longer true since it, found in the comments of
# every .vspec and .yaml file of the directory (comment lines joined, whitespace collapsed, lower case).
STALE_CLAIMS = ("not loaded by generate.py", "not in generate.py yet", "the one overlay generate.py loads")
STALE_LEAD = "**Headers that are no longer true.**"


def _comments(text):
    return " ".join(" ".join(ln.lstrip()[1:].strip() for ln in text.splitlines() if ln.lstrip().startswith("#")).split()).lower()


def _stale_inputs():
    return sorted(p.name for p in VSSDIR.iterdir()
                  if p.suffix in (".vspec", ".yaml") and any(c in _comments(p.read_text(encoding="utf-8")) for c in STALE_CLAIMS))


def test_the_readme_names_every_input_whose_header_still_says_what_this_package_made_untrue():
    """generate.py loads overlay-ctl.vspec, units-project.yaml and quantities-project.yaml, for the databroker catalogues
    and the kind 2 contract only. Their headers once said it does not load them, and overlay.vspec's called itself the one
    overlay it loads; those headers have since been corrected. sdv/vss/README.md's paragraph that starts STALE_LEAD names
    exactly the inputs whose comments still carry one of STALE_CLAIMS: with every header corrected, no input carries one
    and no such paragraph is there. A check of those phrases only: it does not show that every other comment is true."""
    assert all(c in _comments("# x (sdv/vss; Phase 8, not loaded by\n#   generate.py)\n# The One Overlay generate.py loads ... "
                              "(not in\n# generate.py yet)") for c in STALE_CLAIMS)
    paragraphs = [p for p in (VSSDIR / "README.md").read_text(encoding="utf-8").split("\n\n") if p.startswith(STALE_LEAD)]
    assert len(paragraphs) <= 1, paragraphs
    named = sorted(set(re.findall(r"`([A-Za-z0-9_.-]+\.(?:vspec|yaml))`", paragraphs[0]))) if paragraphs else []
    assert named == _stale_inputs()


def test_the_packages_text_files_are_lf_only():
    for path in (PROFILES_CTL, GENERATE, VSSDIR / "README.md", UID_BASELINE, HERE / "test_make_ctl.py", Path(__file__),
                 REPO / "ipc-test" / "qnx-safety-monitor" / "Makefile", NATIVE):
        assert b"\r" not in path.read_bytes(), path
