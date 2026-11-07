"""attribution.py -- the signal attribution table of a slice run, and the checks on it (sdv/stack).

Standard library only. The format is a scenario table (one
row per owned path, writers by name) and a run table (the scenario rows with each writer's image
ID, under a run header). Rule: in one run every VSS signal has exactly one writer, or none.

The rows are generated from the configurations the components are started with -- the CAN
provider's mapping JSON (its dbc2vss entries), the mock provider's behaviour file
(sdv/stack/mock/mock.py), the app's own write list (hazard.WRITES) -- and then checked, so the
table cannot drift from what the components will do. Checks C1-C12 are the design's; each returns
(id, ok, detail). A failed check refuses the start of a run.

THE PLANNING-SIM TABLE (SDV Phase 8 WP3d; spec-2 2.5) A planning-sim run (stack.py up --feed ros) has a table of
its own, by rule over the generated planning-sim catalogue: the ROS->VSS feeder (FEEDER, sdv/rosvss) writes the five
kind 4 slots, Vehicle.Speed and every ControlCommand and Monitor.CtlClaim leaf; the claim bridge its write-back
leaves under Monitor.VssClaim in broker mode, and every VssClaim leaf is unowned otherwise; the Wheelbase is the
planning-sim vehicle layer's catalogue default; nothing else is written (planning_sim_table, planning_sim_rows).
check_planning_sim runs C1, C2, C3 (broker mode), C4, C5, C6, C7, C9 and C11 on those rows, then PLANNING_SIM_CHECK:
the rows are that table and nothing else, the Wheelbase row names the planning-sim layer, no component is configured to
write the Wheelbase, the feeder none of VssClaim, no component but the feeder and the bridge writes, and the witness
watches exactly the owned paths. The feeder's configured write set is sdv/rosvss/mapping.py's, read by the stack, so
the table and the feeder are checked against each other.

Does not demonstrate that a run kept to its table: databroker 0.7.1 runs without authorization
(--insecure), so nothing stops a second client writing a sensor it does not own while the run goes.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
GENERATE = REPO / "sdv" / "vss" / "generate.py"
MOCK_FILE = HERE / "mock" / "mock.py"

CAN_PROVIDER = "kuksa-can-provider"
MOCK_PROVIDER = "kuksa-mock-provider"
RECORDER = "kuksa-csv-provider-recorder"
DATABROKER = "kuksa-databroker"
APP = "hard-brake-hazard"
BRIDGE = "vss-claim-bridge"

# The five kind 4 slots, in slot order (overlay.vspec header; the generated contract's SLOT_PATHS).
SLOT_PATHS = (
    "Vehicle.DualVm.Motion.LongitudinalVelocity",
    "Vehicle.Acceleration.Longitudinal",
    "Vehicle.Chassis.Axle.Row1.SteeringAngle",
    "Vehicle.AngularVelocity.Yaw",
    "Vehicle.Powertrain.Transmission.CurrentGear",
)
WHEELBASE = "Vehicle.Chassis.Wheelbase"
MONITOR_PREFIX = "Vehicle.DualVm.Monitor."
APPSTATE_PREFIX = "Vehicle.DualVm.AppState."

# The twin allowlist, version 1 (design twin-allowlist.md section 2): the paths that may reach the
# cloud. The `cloud` column is copied from this allowlist table;
# every Monitor path is `no` by branch.
ALLOWLIST_VERSION = 1
ALLOWLIST_V1 = frozenset(SLOT_PATHS + (
    "Vehicle.Speed",
    "Vehicle.Body.Lights.Hazard.IsSignaling",
    WHEELBASE,
) + tuple("Vehicle.DualVm.AppState.HardBrakeHazard." + leaf for leaf in (
    "SchemaVersion", "App", "AppVersion", "ImageId", "Seq", "State", "IsHazardRequested", "ActuateResult")))

# The units of each transform, declared by hand as the design requires (deriving them from the DBC
# and the catalogue would make C4's end checks tautological), and the conversion factors C4 holds.
TRANSFORM_UNITS = {"Vehicle.Speed": {"in": "m/s", "out": "km/h"}}
UNIT_FACTORS = {("m/s", "km/h"): 3.6}

NOTES = {
    "Vehicle.DualVm.Motion.LongitudinalVelocity": "signed: positive forward, negative reverse",
    "Vehicle.AngularVelocity.Yaw": "positive = yawing left (overlay convention)",
    "Vehicle.Chassis.Axle.Row1.SteeringAngle": "ISO 8855, positive = left",
    "Vehicle.Powertrain.Transmission.CurrentGear": "0 neutral, positive forward, negative reverse",
    "Vehicle.Speed": "magnitude of the signed longitudinal velocity",
    "Vehicle.Body.Lights.Hazard.IsSignaling": "current value served by the mock provider; the target is the app's request (kuksa.val.v1)",
}


# --- inputs -------------------------------------------------------------------------------------

def _generate_module() -> Any:
    """sdv/vss/generate.py, imported read-only for its DBC reader (no bytecode written)."""
    name = "_sdv_generate_for_stack"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(GENERATE))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % GENERATE)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    sys.modules[name] = mod
    return mod


def parse_dbc(text: str) -> Dict[str, Any]:
    return _generate_module().parse_dbc(text)


def json_nodes(tree: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{path: node} of a vss-tools JSON export."""
    out: Dict[str, Dict[str, Any]] = {}

    def walk(prefix: str, node: Dict[str, Any]) -> None:
        out[prefix] = node
        for name, child in node.get("children", {}).items():
            walk(prefix + "." + name, child)

    for name, node in tree.items():
        walk(name, node)
    return out


def leaf_nodes(tree: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {p: n for p, n in json_nodes(tree).items() if n.get("type") != "branch"}


def dbc2vss_entries(mapping_tree: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{path: dbc2vss block} of a mapping JSON."""
    return {p: n["dbc2vss"] for p, n in json_nodes(mapping_tree).items() if "dbc2vss" in n}


_MOCK_PATH = re.compile(r"""\bpath\s*=\s*["']([A-Za-z0-9_.]+)["']""")


def mock_paths(text: str) -> List[str]:
    """The datapoints a mock-provider behaviour file mocks (its `path=` arguments)."""
    return _MOCK_PATH.findall(text)


# --- transforms ---------------------------------------------------------------------------------

def canonical_transform(block: Dict[str, Any]) -> Optional[str]:
    """The ingress suffix of a dbc2vss transform: the math expression without whitespace and with
    `(x)` dropped (`abs(x) * 3.6` -> `abs*3.6`); None when there is no transform."""
    tr = block.get("transform")
    if tr is None:
        return None
    if set(tr) != {"math"} or not isinstance(tr["math"], str):
        raise ValueError("only a single math transform is supported: %r" % (tr,))
    return re.sub(r"\s+", "", tr["math"]).replace("(x)", "")


_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Call, ast.Load,
                  ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)


def transform_function(block: Dict[str, Any]) -> Callable[[float], float]:
    """A dbc2vss math transform as a Python function of x: numbers, x, + - * /, unary signs and
    abs() only; anything else is refused."""
    tr = block.get("transform")
    if tr is None:
        return lambda x: x
    expr = ast.parse(tr["math"], mode="eval")
    for node in ast.walk(expr):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError("unsupported transform element %s in %r" % (type(node).__name__, tr["math"]))
        if isinstance(node, ast.Name) and node.id not in ("x", "abs"):
            raise ValueError("unsupported name %r in %r" % (node.id, tr["math"]))
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id == "abs" and len(node.args) == 1):
            raise ValueError("only abs(...) may be called in %r" % tr["math"])
    code = compile(expr, "<transform>", "eval")
    return lambda x: float(eval(code, {"__builtins__": {}}, {"x": x, "abs": abs}))  # noqa: S307 -- AST checked above


# --- rows ---------------------------------------------------------------------------------------

def node_text(node: Dict[str, Any]) -> str:
    parts = [node["type"], node["datatype"]]
    if node.get("unit"):
        parts.append(node["unit"])
    return ", ".join(parts)


def app_branch(name: str) -> str:
    return "Vehicle.DualVm.AppState." + "".join(p[:1].upper() + p[1:] for p in name.split("-"))


def scenario_rows(catalogue: Dict[str, Dict[str, Any]], mapping: Dict[str, Dict[str, Any]], dbc: Dict[str, Any],
                  mock_writes: Sequence[str], app_name: str, app_writes: Iterable[str], app_reads_monitor: Sequence[str],
                  recorded_vss: Iterable[str], seed: int, bridge_writes: Sequence[str] = (),
                  vehicle_layer: Optional[str] = None) -> List[Dict[str, Any]]:
    """The scenario table's rows for a sigsim recording (design section 4, column `sigsim`). bridge_writes: the
    claim bridge's configured write set (its Monitor.VssClaim leaves) when a broker-mode bridge runs, each a
    row it writes; empty when none runs, and then the Monitor leaves the app reads are unowned. vehicle_layer:
    the generated per-vehicle layer's file name, the Wheelbase row's ingress (catalogue:<file>); None when the
    catalogue was generated without one, and then the value is VSS 6.0's default."""
    recorded = set(recorded_vss)
    rows: List[Dict[str, Any]] = []
    order = list(SLOT_PATHS) + sorted(p for p in mapping if p not in SLOT_PATHS)
    for path in order:
        if path not in mapping:
            continue
        block = mapping[path]
        sig = block["signal"]
        msg = dbc["signal_message"][sig]
        ingress = "can:0x%03X/%s" % (dbc["messages"][msg]["id"], sig)
        tr = canonical_transform(block)
        if tr is not None:
            ingress += " " + tr
        rows.append(_row(path, catalogue, CAN_PROVIDER, "provider", ingress,
                         TRANSFORM_UNITS.get(path) if tr is not None else None, "sigsim seed %d" % seed,
                         ["candump", "vss-csv"] if path in recorded else ["candump"]))
    for path in mock_writes:
        rows.append(_row(path, catalogue, MOCK_PROVIDER, "actuation-provider" if catalogue[path]["type"] == "actuator" else "provider",
                         "vss:actuation" if catalogue[path]["type"] == "actuator" else "vss:provide", None,
                         "app %s (actuator target, kuksa.val.v1)" % app_name, ["vss-csv"] if path in recorded else ["none"]))
    if vehicle_layer is not None:
        rows.append(_row(WHEELBASE, catalogue, "catalogue", "catalogue-default", "catalogue:" + vehicle_layer, None,
                         "catalogue default", ["vss-csv"] if WHEELBASE in recorded else ["none"],
                         note="the generated per-vehicle layer's default: the source vehicle's wheelbase, its profile's L"))
    else:
        rows.append(_row(WHEELBASE, catalogue, "catalogue", "catalogue-default", "catalogue:vss-6.0-default", None,
                         "catalogue default", ["vss-csv"] if WHEELBASE in recorded else ["none"],
                         note="no vehicle layer was generated, so the value is VSS 6.0's default"))
    for path in bridge_writes:
        rows.append(_row(path, catalogue, BRIDGE, "provider", "vss:provide", None, "guest reply (the bridge's own view)",
                         ["vss-csv"] if path in recorded else ["none"],
                         note="the claim bridge's write-back, labelled as its own view; local only"))
    for path in app_reads_monitor:
        if path in bridge_writes:
            continue
        rows.append(_row(path, catalogue, "none", "provider", "-", None, "guest reply (no claim bridge runs)",
                         ["none"], note="unowned in this run; the app reads it for its local display only"))
    for path in sorted(app_writes):
        rows.append(_row(path, catalogue, app_name, "provider", "vss:provide", None, "app",
                         ["vss-csv"] if path in recorded else ["none"], note="AppState leaf (appstate.schema.json)"))
    return rows


def _row(path: str, catalogue: Dict[str, Dict[str, Any]], writer: str, role: str, ingress: str,
         transform_units: Optional[Dict[str, str]], upstream: str, recorded_in: List[str], note: Optional[str] = None) -> Dict[str, Any]:
    if path not in catalogue:
        raise ValueError("%s is not a leaf of the generated catalogue" % path)
    return {
        "path": path,
        "node": node_text(catalogue[path]),
        "writer": writer,
        "role": role,
        "ingress": ingress,
        "transform_units": transform_units,
        "upstream": upstream,
        "recorded_in": recorded_in,
        "kind4_slot": SLOT_PATHS.index(path) if path in SLOT_PATHS else "-",
        "cloud": "no" if path.startswith(MONITOR_PREFIX) else ("yes" if path in ALLOWLIST_V1 else "no"),
        "note": note if note is not None else NOTES.get(path, ""),
    }


def run_rows(rows: List[Dict[str, Any]], image_ids: Dict[str, str]) -> List[Dict[str, Any]]:
    """The scenario rows with each writer's image ID (from the host's component list)."""
    out = []
    for r in rows:
        r2 = dict(r)
        r2["writer_image_id"] = "-" if r["writer"] in ("catalogue", "none") else image_ids[r["writer"]]
        out.append(r2)
    return out


# --- checks -------------------------------------------------------------------------------------

Check = Tuple[str, bool, str]


def check_rows(rows: List[Dict[str, Any]], catalogue: Dict[str, Dict[str, Any]], mapping: Dict[str, Dict[str, Any]],
               dbc: Dict[str, Any], write_sets: Dict[str, Iterable[str]], app_name: str,
               bridge_mode: str = "none") -> List[Check]:
    """C1, C2, C4, C5, C6, C7, C9, C11 on a scenario or run table, and C3 when the bridge runs in broker mode."""
    out: List[Check] = []
    paths = [r["path"] for r in rows]
    dup = sorted({p for p in paths if paths.count(p) > 1})
    out.append(("C1", not dup, "each path once" if not dup else "duplicated: %s" % dup))

    owned = {r["path"]: r["writer"] for r in rows if r["writer"] not in ("none", "catalogue")}
    problems = []
    union: Dict[str, List[str]] = {}
    for comp, ws in write_sets.items():
        for p in ws:
            union.setdefault(p, []).append(comp)
    for p, comps in sorted(union.items()):
        if len(comps) > 1:
            problems.append("%s written by %s" % (p, comps))
        elif owned.get(p) != comps[0]:
            problems.append("%s written by %s but the table says %r" % (p, comps[0], owned.get(p)))
    for p, w in sorted(owned.items()):
        if p not in union:
            problems.append("%s: table writer %s has no such configured write" % (p, w))
    out.append(("C2", not problems, "one writer per row; configured write sets equal the rows" if not problems else "; ".join(problems)))

    problems = []
    for r in rows:
        node = catalogue.get(r["path"])
        if node is None:
            problems.append("%s not in the catalogue" % r["path"])
            continue
        if r["node"] != node_text(node):
            problems.append("%s: node %r != catalogue %r" % (r["path"], r["node"], node_text(node)))
        if r["ingress"].startswith("can:"):
            sig = r["ingress"].split("/", 1)[1].split(" ", 1)[0]
            msg = dbc["signal_message"].get(sig)
            dbc_unit = dbc["messages"][msg]["signals"][sig]["unit"] if msg else None
            if " " in r["ingress"]:
                tu = r.get("transform_units")
                if not tu:
                    problems.append("%s: transform without transform_units" % r["path"])
                    continue
                if dbc_unit != tu["in"]:
                    problems.append("%s: DBC unit %r != transform in %r" % (r["path"], dbc_unit, tu["in"]))
                if node.get("unit") != tu["out"]:
                    problems.append("%s: catalogue unit %r != transform out %r" % (r["path"], node.get("unit"), tu["out"]))
                factor = UNIT_FACTORS.get((tu["in"], tu["out"]))
                if factor is None:
                    problems.append("%s: no conversion factor held for %s -> %s" % (r["path"], tu["in"], tu["out"]))
                else:
                    got = transform_function(mapping[r["path"]])(1.0)
                    if abs(got - factor) > 1e-12:
                        problems.append("%s: transform(1) = %r, not the %s -> %s factor %r" % (r["path"], got, tu["in"], tu["out"], factor))
            elif (dbc_unit or None) != (node.get("unit") or None):
                problems.append("%s: DBC unit %r != catalogue unit %r" % (r["path"], dbc_unit, node.get("unit")))
    out.append(("C4", not problems, "nodes and units agree with the catalogue and slice.dbc" if not problems else "; ".join(problems)))

    bad = [r["path"] for r in rows if r["path"].startswith(MONITOR_PREFIX + "VssClaim.") and r["writer"] not in (BRIDGE, "none")]
    bad += [r["path"] for r in rows if r["path"].startswith(MONITOR_PREFIX + "CtlClaim.") and r["writer"] not in ("ros-vss-feeder", "none")]
    # the bridge's configured write set lies entirely under Monitor.VssClaim (twin-allowlist test A9)
    bad += ["%s (configured for the bridge)" % p for p in write_sets.get(BRIDGE, ()) if not p.startswith(MONITOR_PREFIX + "VssClaim.")]
    out.append(("C5", not bad, "Monitor rows name the bridge or none; the bridge writes under Monitor.VssClaim only" if not bad
                else "Monitor rows with another writer, or bridge writes outside Monitor.VssClaim: %s" % bad))

    bad = []
    for r in rows:
        if r["path"].startswith(APPSTATE_PREFIX):
            sub = ".".join(r["path"].split(".")[:4])
            if r["writer"] != app_name or app_branch(app_name) != sub:
                bad.append(r["path"])
    for comp, ws in write_sets.items():
        if comp != app_name:
            bad += [p for p in ws if p.startswith(APPSTATE_PREFIX)]
    out.append(("C6", not bad, "AppState rows name the app whose name derives the sub-branch" if not bad else "bad: %s" % sorted(set(bad))))

    problems = []
    for r in rows:
        node = catalogue.get(r["path"], {})
        if node.get("type") == "actuator":
            servers = [x for x in rows if x["path"] == r["path"] and x["role"] == "actuation-provider"]
            if len(servers) != 1:
                problems.append("%s has %d actuation providers" % (r["path"], len(servers)))
    out.append(("C7", not problems, "each actuator has exactly one actuation provider" if not problems else "; ".join(problems)))

    can_rows = {r["path"]: r["ingress"] for r in rows if r["ingress"].startswith("can:")}
    expected = {}
    for p, block in mapping.items():
        msg = dbc["signal_message"].get(block["signal"])
        ing = "can:0x%03X/%s" % (dbc["messages"][msg]["id"], block["signal"]) if msg else "can:?/%s" % block["signal"]
        tr = canonical_transform(block)
        expected[p] = ing + (" " + tr if tr is not None else "")
    diff = sorted(set(can_rows.items()) ^ set(expected.items()))
    out.append(("C9", not diff, "can: rows equal the mapping JSON's dbc2vss entries" if not diff else "differ: %s" % diff))

    bad = [r["path"] for r in rows
           if r["cloud"] != ("no" if r["path"].startswith(MONITOR_PREFIX) else ("yes" if r["path"] in ALLOWLIST_V1 else "no"))]
    out.append(("C11", not bad, "cloud column equals allowlist v%d; every Monitor row is no" % ALLOWLIST_VERSION if not bad else "bad: %s" % bad))
    if bridge_mode == "broker":
        writer = {r["path"]: r["writer"] for r in rows}
        bad = [p for p in SLOT_PATHS if writer.get(p) in (None, "none")]
        out.append(("C3", not bad, "every kind 4 slot has a writer (broker mode)" if not bad else
                    "broker mode, kind 4 slots with no writer (their frames could only carry flag 0): %s" % bad))
    return out


def check_images(rows: List[Dict[str, Any]], running: Dict[str, str]) -> Check:
    """C8: every writer of a run row is a started component whose image ID equals the row's."""
    problems = []
    for r in rows:
        if r["writer"] in ("none", "catalogue"):
            continue
        got = running.get(r["writer"])
        if got is None:
            problems.append("%s: writer %s is not running" % (r["path"], r["writer"]))
        elif got != r["writer_image_id"]:
            problems.append("%s: %s runs %s, table says %s" % (r["path"], r["writer"], got, r["writer_image_id"]))
    return ("C8", not problems, "every writer runs the table's image ID" if not problems else "; ".join(problems))


def check_recording(header: Dict[str, Any], actual_sha256: str, scenario_dbc_sha256: str) -> Check:
    """C10: the recording's sha256 equals the header's, and the header's DBC is the scenario's."""
    rec = [r for r in header["recordings"] if r["role"] == "candump"]
    ok = len(rec) == 1 and rec[0]["sha256"] == "sha256:" + actual_sha256 and header["dbc_sha256"] == scenario_dbc_sha256
    return ("C10", ok, "recording sha256 and DBC sha256 match" if ok else
            "recording %s vs %s; dbc %s vs %s" % (rec, actual_sha256, header["dbc_sha256"], scenario_dbc_sha256))


BRIDGE_MODES = ("broker", "can", "replay")
PROFILE_SOURCES = ("scenario", "live-default")
AGE_CLOCKS = ("realtime", "monotonic")
CARLA_RUN_TYPES = ("carla", "carla-autoware")


def check_header(header: Dict[str, Any], profiles: Dict[int, Dict[str, Any]], age_max_ms: int,
                 scenario_profile_id: Optional[int] = None, live_defaults: Optional[Dict[str, int]] = None,
                 compiled: Optional[Sequence[int]] = None, age_clock: Optional[str] = None,
                 scenario_source_rtf: Optional[Dict[str, Any]] = None) -> Check:
    """C12a at start (and C3's precondition): the run-level items describe the run, every sub-check of
    attribution-table section 5's C12a row.

    profiles: the generated table {id: row}; compiled: the ids in the guest's table (None: not checked);
    scenario_profile_id: the scenario entry's profile_id, which profile_source `scenario` must carry;
    live_defaults: {run_type: id}, the generated live defaults, which `live-default` must carry; age_clock: the
    clock the run's bridge mode reads its ages on, which time_sync.age_clock must name (None: only its form is
    checked); scenario_source_rtf: the scenario entry's source.rtf, which a recorded CARLA feed's source_rtf must
    equal (a live feed's is written at record close, C12b; every other run type's is null). Without a bridge the
    bridge items are null and their sub-checks have no operand, and so is time_sync.age_clock: nothing reads an
    age (this stack's reading; the table defines age_clock only as the bridge's clock)."""
    problems = []
    mode = header["bridge_mode"]
    none_mode = mode == "none"
    if mode not in ("none",) + BRIDGE_MODES:
        problems.append("bridge_mode %r is not none, broker, can or replay" % (mode,))
    for key in ("profile_id", "profile_source", "age_max_ms"):
        if none_mode and header[key] is not None:
            problems.append("%s must be null without a bridge" % key)
        if not none_mode and header[key] is None:
            problems.append("%s must be set with a bridge" % key)
    if none_mode and header["demo_odd_window"] is not None:
        problems.append("demo_odd_window must be null without a bridge")
    sv = header.get("source_vehicle") or {}
    if not (isinstance(sv.get("name"), str) and isinstance(sv.get("wheelbase_mm"), int)):
        problems.append("source_vehicle must name the vehicle and its wheelbase")
    if not none_mode:
        pid = header["profile_id"]
        prof = profiles.get(pid)
        if prof is None:
            problems.append("profile %r is not bound" % (pid,))
        elif compiled is not None and pid not in compiled:
            problems.append("profile %r is not compiled into the guest's table %s" % (pid, list(compiled)))
        elif prof["l_mm"] != sv.get("wheelbase_mm"):
            problems.append("source vehicle wheelbase %r != profile L %r" % (sv.get("wheelbase_mm"), prof["l_mm"]))
        src = header["profile_source"]
        if src == "scenario":
            if scenario_profile_id is None or pid != scenario_profile_id:
                problems.append("profile_source scenario, but profile %r is not the scenario entry's %r" % (pid, scenario_profile_id))
        elif src == "live-default":
            want = (live_defaults or {}).get(header["run_type"])
            if want is None or pid != want:
                problems.append("profile_source live-default, but profile %r is not run type %r's default %r" % (pid, header["run_type"], want))
        elif src is not None:
            problems.append("profile_source %r is not scenario or live-default" % (src,))
        if header["age_max_ms"] != age_max_ms:
            problems.append("age_max_ms %r != generated %r" % (header["age_max_ms"], age_max_ms))
        w = header.get("demo_odd_window")
        if w is not None:
            demo = profiles.get(w["profile_id"]) if isinstance(w, dict) and isinstance(w.get("profile_id"), int) else None
            if demo is None or "run_window_max_ms" not in demo:
                problems.append("demo_odd_window must name the demo-ODD profile (the one with a run window): %r" % (w,))
            elif not (isinstance(w.get("start_s"), (int, float)) and w["start_s"] >= 0 and isinstance(w.get("duration_s"), (int, float))
                      and 0 < w["duration_s"] * 1000 <= demo["run_window_max_ms"]):
                problems.append("demo_odd_window %r must start at >= 0 s and last more than 0 and at most %d ms"
                                % (w, demo["run_window_max_ms"]))
    ts = header.get("time_sync") or {}
    if "daemon" not in ts or "synchronised" not in ts:
        problems.append("time_sync not filled")
    if none_mode:
        if ts.get("age_clock") is not None:
            problems.append("time_sync.age_clock must be null without a bridge: no bridge reads ages")
    elif ts.get("age_clock") not in AGE_CLOCKS:
        problems.append("time_sync.age_clock %r must name the clock the bridge reads its ages on (realtime or monotonic)"
                        % (ts.get("age_clock"),))
    elif age_clock is not None and ts["age_clock"] != age_clock:
        problems.append("time_sync.age_clock %r is not the %s mode's age source clock %r" % (ts["age_clock"], mode, age_clock))
    if header["run_type"] not in CARLA_RUN_TYPES:
        if header["source_rtf"] is not None:
            problems.append("source_rtf is only for CARLA-sourced runs")
    elif header.get("feed") == "recording":
        if scenario_source_rtf is None:
            problems.append("a recorded CARLA feed needs the scenario entry's source.rtf, and there is none")
        elif header["source_rtf"] != scenario_source_rtf:
            problems.append("source_rtf %r is not the scenario entry's source.rtf %r" % (header["source_rtf"], scenario_source_rtf))
    return ("C12a", not problems, "run header describes the run" if not problems else "; ".join(problems))


_VSS_RULES = re.compile(r"^monitor: vss rules: kind 4, catalog (0x[0-9A-F]{8}) \(vss [^)]*\), age_max (\d+) ms, profiles ([0-9 ]+)$")


def vss_rules_lines(console: str) -> List[Dict[str, Any]]:
    """Every `monitor: vss rules:` announcement of a console capture (monitor.c's format, wire spec 12)."""
    out = []
    for line in console.splitlines():
        m = _VSS_RULES.match(line.strip())
        if m:
            out.append({"catalog": m.group(1), "age_max_ms": int(m.group(2)), "profiles": [int(x) for x in m.group(3).split()]})
    return out


def check_close(header: Dict[str, Any], console: Optional[str], bridge_records: Optional[List[Dict[str, Any]]]) -> Check:
    """C12b at record close. Its operands: for a CARLA-sourced run the header's source_rtf; when a bridge ran, the
    monitor's console capture (the guest console, or the native monitor's stdout on the PC), whose `monitor: vss
    rules:` line must carry the header's kind4_digest and age_max_ms and list its profile_id, and the bridge's log,
    whose connect records (spec 14.3 item 6) must carry the same digest, AGE_MAX, profile and mode. With neither,
    there is nothing to check and the detail says so. A missing operand fails the check: a record without them
    cannot show the run's bridge and guest agreed."""
    problems: List[str] = []
    seen: List[str] = []
    if header["run_type"] in CARLA_RUN_TYPES:
        rtf = header.get("source_rtf")
        if not isinstance(rtf, dict) or not all(isinstance(rtf.get(k), (int, float)) for k in ("min", "mean", "max")):
            problems.append("source_rtf is not filled for a CARLA-sourced run")
        elif rtf["max"] > 1:
            problems.append("source_rtf max %r > 1: the feeder's pacing did not hold" % (rtf["max"],))
        seen.append("source_rtf")
    if header["bridge_mode"] != "none":
        digest, age, pid = header["catalogue"]["kind4_digest"], header["age_max_ms"], header["profile_id"]
        if console is None:
            problems.append("no monitor console was captured")
            rules: List[Dict[str, Any]] = []
        else:
            rules = vss_rules_lines(console)
            if not rules:
                problems.append("the monitor console holds no 'monitor: vss rules:' line")
        for r in rules:
            if r["catalog"] != digest:
                problems.append("vss rules: catalog %s, the header's kind4_digest %s" % (r["catalog"], digest))
            if r["age_max_ms"] != age:
                problems.append("vss rules: age_max %d ms, the header's age_max_ms %r" % (r["age_max_ms"], age))
            if pid not in r["profiles"]:
                problems.append("vss rules: profiles %s do not list the header's profile %r" % (r["profiles"], pid))
        if bridge_records is None:
            problems.append("no bridge log was captured")
            connects: List[Dict[str, Any]] = []
        else:
            connects = [r for r in bridge_records if r.get("event") == "connect"]
            if not connects:
                problems.append("the bridge's log holds no connect record")
        for c in connects:
            for key, want in (("digest", digest), ("age_max_ms", age), ("profile_id", pid), ("mode", header["bridge_mode"])):
                if c.get(key) != want:
                    problems.append("bridge connect: %s %r, the header's %r" % (key, c.get(key), want))
        seen.append("%d vss rules line(s), %d bridge connect record(s)" % (len(rules), len(connects)))
    if problems:
        return ("C12b", False, "; ".join(problems))
    return ("C12b", True, "checked: %s" % "; ".join(seen) if seen else "no operand: no bridge ran and no CARLA source")


def header_check(check: Check) -> str:
    """The run header's header_check value from C12b (attribution-table 3.1): ok, or failed C12b: <items>."""
    return "ok" if check[1] else "failed C12b: %s" % check[2]


def render_markdown(header: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    """The run table as markdown, for reading."""
    cols = ("path", "node", "writer", "writer_image_id", "role", "ingress", "transform_units", "upstream",
            "recorded_in", "kind4_slot", "cloud", "note")
    lines = ["# Attribution: %s" % header["run_id"], "", "```json", json.dumps(header, indent=2, sort_keys=True), "```", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, (dict, list)):
                v = json.dumps(v, sort_keys=True)
            cells.append(str(v).replace("|", "\\|"))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


# --- the planning-sim table (SDV Phase 8 WP3d; spec-2 2.5) --------------------------------------------------------------

FEEDER = "ros-vss-feeder"          # sdv/rosvss/mapping.py's WRITER (a test holds them equal); C5's CtlClaim writer
PLANNING_SIM = "planning-sim"
SPEED = "Vehicle.Speed"
CONTROL_COMMAND_PREFIX = "Vehicle.DualVm.ControlCommand."
CTLCLAIM_PREFIX = MONITOR_PREFIX + "CtlClaim."
VSSCLAIM_PREFIX = MONITOR_PREFIX + "VssClaim."
VERDICT_TOPIC = "/qnx_monitor/verdict"     # the claim node's verdict messages: the overlay leaves' ingress
# The topic each standard path comes from in a planning-sim run (the feeder's subscriptions, sdv/rosvss/feeder_node.py,
# read: a test holds the set equal), each path's ingress `ros:<topic>`.
PLANNING_SIM_TOPICS = {
    SLOT_PATHS[0]: "/vehicle/status/velocity_status",
    SLOT_PATHS[1]: "/localization/acceleration",
    SLOT_PATHS[2]: "/vehicle/status/steering_status",
    SLOT_PATHS[3]: "/vehicle/status/velocity_status",
    SLOT_PATHS[4]: "/vehicle/status/gear_status",
    SPEED: "/vehicle/status/velocity_status",
}
PLANNING_SIM_CHECK = "C2-planning-sim"     # the check that the rows are the planning-sim table (check_planning_sim)
PLANNING_SIM_WITNESS = "vss-witness"       # the recorded_in of an owned path: the stack's witness watches it


def planning_sim_table(catalogue: Dict[str, Dict[str, Any]], bridge_writes: Iterable[str] = ()) -> Dict[str, str]:
    """{path: writer} by spec-2 2.5's rule over a generated catalogue: FEEDER for the slots, Vehicle.Speed and every
    ControlCommand and Monitor.CtlClaim leaf; BRIDGE for each VssClaim leaf of its configured write set (broker mode: pass
    it; otherwise nothing) and "none" for every other VssClaim leaf; "catalogue" for the Wheelbase. Nothing else."""
    writes = set(bridge_writes)
    table = {p: FEEDER for p in SLOT_PATHS + (SPEED,)}
    for p in sorted(catalogue):
        if p.startswith((CONTROL_COMMAND_PREFIX, CTLCLAIM_PREFIX)):
            table[p] = FEEDER
        elif p.startswith(VSSCLAIM_PREFIX):
            table[p] = BRIDGE if p in writes else "none"
    table[WHEELBASE] = "catalogue"
    return table


def planning_sim_rows(catalogue: Dict[str, Dict[str, Any]], vehicle_layer: str, bridge_writes: Sequence[str] = (),
                      witnessed: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """The planning-sim table's rows (planning_sim_table) in the scenario table's form: the slots, Vehicle.Speed, the
    ControlCommand, CtlClaim and VssClaim leaves (each sorted), then the Wheelbase, its ingress catalogue:<vehicle_layer>.
    witnessed: the paths the stack's witness watches, whose recorded_in is PLANNING_SIM_WITNESS."""
    table = planning_sim_table(catalogue, bridge_writes)
    seen = set(witnessed)
    order = (list(SLOT_PATHS) + [SPEED] + sorted(p for p in table if p.startswith(CONTROL_COMMAND_PREFIX))
             + sorted(p for p in table if p.startswith(CTLCLAIM_PREFIX)) + sorted(p for p in table if p.startswith(VSSCLAIM_PREFIX))
             + [WHEELBASE])
    rows: List[Dict[str, Any]] = []
    for path in order:
        writer = table[path]
        recorded = [PLANNING_SIM_WITNESS] if path in seen else ["none"]
        if writer == FEEDER:
            standard = path in PLANNING_SIM_TOPICS
            rows.append(_row(path, catalogue, FEEDER, "provider", "ros:" + PLANNING_SIM_TOPICS.get(path, VERDICT_TOPIC), None,
                             "Autoware's planning simulator (its vehicle status topics)" if standard else
                             "the kind 2 claim node (sdv/ctl ctl_claim_node.py, its verdict messages)", recorded,
                             note=None if standard else ("the claim node's packed command, as its verdict message carries it"
                                                         if path.startswith(CONTROL_COMMAND_PREFIX) else
                                                         "the claim node's view of the guest's kind 2 reply; local only")))
        elif writer == BRIDGE:
            rows.append(_row(path, catalogue, BRIDGE, "provider", "vss:provide", None, "guest reply (the bridge's own view)", recorded,
                             note="the claim bridge's write-back, labelled as its own view; local only"))
        elif writer == "none":
            rows.append(_row(path, catalogue, "none", "provider", "-", None, "guest reply (no claim bridge runs)", recorded,
                             note="unowned in this run"))
        else:
            rows.append(_row(path, catalogue, "catalogue", "catalogue-default", "catalogue:" + vehicle_layer, None, "catalogue default",
                             recorded, note="the planning-sim vehicle layer's default: the source vehicle's wheelbase, its profile's L"))
    return rows


def check_planning_sim(rows: List[Dict[str, Any]], catalogue: Dict[str, Dict[str, Any]], write_sets: Dict[str, Iterable[str]],
                       vehicle_layer: str, bridge_mode: str = "none", witnessed: Optional[Iterable[str]] = None) -> List[Check]:
    """check_rows on a planning-sim table (no CAN rows: C4 and C9 read none, C3 in broker mode), then PLANNING_SIM_CHECK:
    the rows are planning_sim_table's (the bridge's configured writes in broker mode) and nothing else, the Wheelbase row
    is catalogue:<vehicle_layer>, no component is configured to write the Wheelbase, the feeder no VssClaim leaf, only the
    feeder and the bridge are configured to write, and the witness (witnessed; None: not checked) watches exactly the
    rows' owned paths."""
    out = check_rows(rows, catalogue, {}, {"messages": {}, "signal_message": {}}, write_sets, APP, bridge_mode=bridge_mode)
    table = planning_sim_table(catalogue, write_sets.get(BRIDGE, ()) if bridge_mode == "broker" else ())
    got: Dict[str, List[str]] = {}
    for r in rows:
        got.setdefault(r["path"], []).append(r["writer"])
    problems = []
    for p in sorted(set(table) | set(got)):
        if p not in got:
            problems.append("%s: no row, and the table gives it to %s" % (p, table[p]))
        elif p not in table:
            problems.append("%s: a row written by %s, a path the planning-sim table does not hold" % (p, "/".join(got[p])))
        elif got[p] != [table[p]]:
            problems.append("%s: written by %s, the table's writer is %s" % (p, "/".join(got[p]), table[p]))
    for r in rows:
        if r["path"] == WHEELBASE and r["ingress"] != "catalogue:" + vehicle_layer:
            problems.append("%s: ingress %s, not catalogue:%s" % (WHEELBASE, r["ingress"], vehicle_layer))
    for comp, ws in sorted(write_sets.items()):
        paths = list(ws)
        if WHEELBASE in paths:
            problems.append("%s is configured to write %s, which only the catalogue sets" % (comp, WHEELBASE))
        if comp == FEEDER:
            problems += ["the feeder is configured to write %s (the kind 4 bridge's)" % p for p in paths if p.startswith(VSSCLAIM_PREFIX)]
        elif comp != BRIDGE and paths:
            problems.append("%s is configured to write in a planning-sim run, which starts the feeder and the bridge only" % comp)
    if witnessed is not None:
        owned = sorted({r["path"] for r in rows if r["writer"] not in ("none", "catalogue")})
        if sorted(set(witnessed)) != owned:
            problems.append("the witness's paths and the table's owned paths differ in %s" % sorted(set(witnessed) ^ set(owned)))
    out.append((PLANNING_SIM_CHECK, not problems, "the rows are the planning-sim table (spec-2 2.5), one writer per signal, nothing "
                                                  "else written" if not problems else "; ".join(problems)))
    return out
