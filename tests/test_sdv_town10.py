"""Town 10's scenarios (sdv/carla/town10.py, sdv/ctl/scenarios/town10-*.json): SDV plan Phase 8 WP9 P1, the WP9 specification's
section 2.5 and section 1's items 5, 6 and 8.

What is tested, and how. Standard library and sdv/ctl/aw_scenario.py's own form only: no server, no ROS, no container, and no
test reads a map: tests/fixtures/town10/facts.json holds the map folder's three hashes, WP9a's spawn points by index (x, y, z,
yaw in degrees, in the CARLA frame, as its level read lists them), the F table's map-frame poses and, for the frame's control,
the nearest centreline point of each spawn's lanelet.

- the frame rule (map x = carla x, map y = -carla y, heading = -yaw) on the F table's points, and its control: the spawn lies
  on its lanelet's centre under the rule and far off it with map y = +carla y;
- the offset: initial_pose is the spawn's base_link pose, 1.265 m behind the origin along the heading, written in one place;
  goal is the goal spawn's origin pose;
- the regeneration: each committed scenario file is byte for byte what town10.py writes;
- the launch's spawn_point: one string of six comma-separated numbers, no brackets, in the order x, y, z, roll, pitch, yaw, in
  degrees and the CARLA frame, read as the pin's _parse_spawn_point reads it;
- the timeouts, the map's name and three hashes, the routes' spawn pairs, aw_scenario.py's own load and map check.

Every number here is a design value of the specification, a constant of the level or map as read before this package, or
computed from them; none is a result of a drive.

What this does NOT show: that the map and the level agree beyond these eight points, that a route is accepted or driven (the
routes are Autoware's to take), that the launch hands the string to the node unchanged, or anything about the server's own
spawn table beyond WP9a's read; any timing.
"""
import ast
import importlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CARLA_DIR = REPO / "sdv" / "carla"
CTL_DIR = REPO / "sdv" / "ctl"
SCENARIOS = CTL_DIR / "scenarios"
MODULE = CARLA_DIR / "town10.py"
FACTS = json.loads((HERE / "fixtures" / "town10" / "facts.json").read_text(encoding="utf-8"))
SPAWNS = {int(k): v for k, v in FACTS["spawns_x_y_z_yaw_deg"].items()}
F_TABLE = {int(k): v for k, v in FACTS["f_table_map_x_y_yaw_rad"].items()}
CENTRE = {int(k): v for k, v in FACTS["centreline_nearest"].items()}

# 2.5 and item 8, written out here (not the module's constants).
OFFSET_M = 1.265
ROUTES = {"t1": (136, 34), "t3": (16, 19), "t4": (16, 45), "t5": (86, 126)}
TIMEOUTS = {"t1": {"localize": 60, "route": 60, "engage": 120, "arrive": 300},
            "t3": {"localize": 60, "route": 60, "engage": 120, "arrive": 300},
            "t4": {"localize": 60, "route": 60, "engage": 120, "arrive": 600},
            "t5": {"localize": 60, "route": 60, "engage": 120, "arrive": 450}}
INITIAL = {"t1": (87.247, -66.36, 3.140319), "t3": (-55.61, -137.043, -0.006144), "t4": (-55.61, -137.043, -0.006144),
           "t5": (-65.529, -13.002, 3.138818)}
SPAWN_POINT = {"t1": "85.982,66.358,0.6,0.0,0.0,-179.927", "t3": "-54.345,137.051,0.6,0.0,0.0,0.352",
               "t4": "-54.345,137.051,0.6,0.0,0.0,0.352", "t5": "-66.794,12.998,0.6,0.0,0.0,-179.841"}
NPC_SPAWN = 54


def _import(name, directory):
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        return importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved


@pytest.fixture(scope="module")
def t10():
    return _import("town10", CARLA_DIR)


@pytest.fixture(scope="module")
def aw():
    return _import("aw_scenario", CTL_DIR)


def _doc(sid):
    return json.loads((SCENARIOS / ("town10-%s.json" % sid)).read_text(encoding="utf-8"))


def _both(t10, sid):
    """The committed file and what the module writes, so a change made to both together is seen as well as one made to either."""
    return (_doc(sid), t10.scenario(sid))


# =================================================================================================================
# The table: WP9a's spawns by index, the four routes, the NPC's spawn
# =================================================================================================================

def test_the_four_routes_and_the_npcs_spawn_are_item_8s(t10):
    assert t10.SCENARIO_IDS == ("t1", "t3", "t4", "t5")
    assert {s: t10.route(s)[:2] for s in t10.SCENARIO_IDS} == ROUTES
    assert t10.NPC_SPAWN == NPC_SPAWN
    assert sorted(p.name for p in SCENARIOS.glob("town10-*")) == ["town10-t1.json", "town10-t3.json", "town10-t4.json", "town10-t5.json"]


def test_the_spawn_table_is_wp9as_read_by_index_with_roll_and_pitch_zero(t10):
    assert sorted(t10.SPAWNS) == sorted(SPAWNS)
    for index, (x, y, z, yaw) in SPAWNS.items():
        assert t10.SPAWNS[index] == (x, y, z, 0.0, 0.0, yaw), index


def test_an_unknown_route_or_spawn_is_refused(t10):
    with pytest.raises(KeyError):
        t10.route("t2")
    with pytest.raises(KeyError):
        t10.spawn_point(7)


# =================================================================================================================
# The frame (WM M18): the F table's points, and the control
# =================================================================================================================

@pytest.mark.parametrize("index", sorted(F_TABLE))
def test_the_frame_rule_gives_the_f_tables_map_pose(t10, index):
    x, y, yaw = F_TABLE[index]
    got = t10.origin_pose(index)
    assert (got["x"], got["y"], got["z"], got["yaw"]) == pytest.approx((x, y, 0.0, yaw), abs=1e-9)


@pytest.mark.parametrize("index", sorted(CENTRE))
def test_each_spawn_lies_on_its_lanelets_centre_under_the_rule_and_far_off_it_with_y_uninverted(t10, index):
    """WM M18's control on the eight points: the map's lanelets are the y-inverted ones."""
    pose, c = t10.origin_pose(index), CENTRE[index]
    assert math.hypot(pose["x"] - c["x"], pose["y"] - c["y"]) < 0.5, index
    assert abs(math.remainder(pose["yaw"] - c["heading_rad"], math.tau)) < math.radians(1.0), index
    assert math.hypot(pose["x"] - c["x"], -pose["y"] - c["y"]) > 10.0, index


def test_the_heading_rule_is_the_negated_yaw_not_the_yaw(t10):
    """The one spawn where a sign error in the heading alone shows large: spawn 126 runs along the map's -y."""
    c, h = CENTRE[126], t10.origin_pose(126)["yaw"]
    assert abs(math.remainder(h - c["heading_rad"], math.tau)) < math.radians(1.0)
    assert abs(math.remainder(-h - c["heading_rad"], math.tau)) > math.radians(90.0)


# =================================================================================================================
# The offset: initial_pose is the base_link pose, the goal is the origin pose (items 5 and 6)
# =================================================================================================================

def test_the_offset_is_1_265_m_and_is_written_in_one_place(t10):
    assert t10.BASE_LINK_OFFSET_M == OFFSET_M
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    literals = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value in (1.265, 1.425, 1.47, 2.53, 2.85, 2.94, 2.79)]
    assert len(literals) == 1 and literals[0].value == OFFSET_M
    for f in sorted(CARLA_DIR.glob("*.py")):
        if f != MODULE:
            assert not re.search(r"(?<![\d.])1\.265(?!\d)", f.read_text(encoding="utf-8")), f.name


@pytest.mark.parametrize("sid", sorted(ROUTES))
def test_initial_pose_is_the_spawns_base_link_pose_behind_the_origin(t10, sid):
    start = ROUTES[sid][0]
    x, y, h = F_TABLE[start]
    for doc in _both(t10, sid):
        d = doc["initial_pose"]
        assert (d["x"], d["y"], d["yaw"]) == pytest.approx(INITIAL[sid], abs=1e-9)
        assert d["z"] == 0.0
        assert d["x"] == pytest.approx(x - OFFSET_M * math.cos(h), abs=1e-3)
        assert d["y"] == pytest.approx(y - OFFSET_M * math.sin(h), abs=1e-3)
        assert math.hypot(d["x"] - x, d["y"] - y) == pytest.approx(OFFSET_M, abs=2e-3)
        behind = (x - d["x"]) * math.cos(h) + (y - d["y"]) * math.sin(h)
        assert behind == pytest.approx(OFFSET_M, abs=2e-3), "base_link lies behind the origin, not ahead of it"


@pytest.mark.parametrize("sid", sorted(ROUTES))
def test_the_goal_is_the_goal_spawns_origin_pose_with_no_offset(t10, sid):
    goal = ROUTES[sid][1]
    for doc in _both(t10, sid):
        d = doc["goal"]
        assert [d["x"], d["y"], d["yaw"]] == pytest.approx(F_TABLE[goal], abs=1e-9)
        assert d["z"] == 0.0


# =================================================================================================================
# The regeneration: one pose, two writings; the file is never edited by hand
# =================================================================================================================

@pytest.mark.parametrize("sid", sorted(ROUTES))
def test_each_committed_scenario_is_byte_for_byte_what_the_module_writes(t10, sid):
    assert (SCENARIOS / ("town10-%s.json" % sid)).read_bytes() == t10.render(t10.scenario(sid)).encode("ascii")


@pytest.mark.parametrize("sid", sorted(ROUTES))
def test_each_committed_scenario_file_ends_in_its_closing_brace_and_one_newline(sid):
    """render's docstring and the files' form promise the newline; with the module and the files regenerated together nothing else holds it."""
    assert (SCENARIOS / ("town10-%s.json" % sid)).read_bytes().endswith(b"}\n")


def test_the_write_command_writes_the_four_files_as_committed_and_nothing_else(t10, tmp_path):
    r = subprocess.run([sys.executable, "-B", str(MODULE), "write", "--dir", str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["town10-t1.json", "town10-t3.json", "town10-t4.json", "town10-t5.json"]
    for name in written:
        assert (tmp_path / name).read_bytes() == (SCENARIOS / name).read_bytes(), name


@pytest.mark.parametrize("target", ["absent", "a-file"])
def test_the_write_command_refuses_a_directory_that_is_not_one_with_a_line_and_no_traceback(tmp_path, target):
    path = tmp_path / target
    if target == "a-file":
        path.write_text("kept\n", encoding="ascii")
    r = subprocess.run([sys.executable, "-B", str(MODULE), "write", "--dir", str(path)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "is not a directory" in r.stderr and "Traceback" not in r.stderr, r.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ([] if target == "absent" else ["a-file"])


def test_the_scenarios_form_is_2_8s_in_its_key_order(t10):
    for sid in ROUTES:
        d = _doc(sid)
        assert list(d) == ["format", "name", "map", "initial_pose", "goal", "timeouts_s"]
        assert d["format"] == 1 and d["name"] == "town10-%s" % sid
        assert list(d["initial_pose"]) == list(d["goal"]) == ["x", "y", "z", "yaw"]
        assert list(d["timeouts_s"]) == ["localize", "route", "engage", "arrive"]


# =================================================================================================================
# The driver's own form: aw_scenario.py loads each; the folder's name and three hashes (2.5)
# =================================================================================================================

@pytest.mark.parametrize("sid", sorted(ROUTES))
def test_aw_scenario_loads_each_and_names_it_by_its_stem(aw, t10, sid, tmp_path):
    p = SCENARIOS / ("town10-%s.json" % sid)
    written = tmp_path / p.name
    written.write_text(t10.render(t10.scenario(sid)), encoding="ascii")
    for f in (p, written):
        s = aw.load_scenario(f)
        assert s.name == p.stem
        assert s.map_name == FACTS["map"]["name"] == "Town10HD-aw-n28"
        assert s.map_files == FACTS["map"]["files"]


def test_the_folder_is_way_as_and_only_its_osm_differs_from_the_source():
    files = FACTS["map"]["files"]
    assert sorted(files) == ["lanelet2_map.osm", "map_projector_info.yaml", "pointcloud_map.pcd"]
    assert files["lanelet2_map.osm"] != FACTS["map"]["source_osm_sha256"]
    assert sorted(FACTS["map"]["source_files"]) == ["map_projector_info.yaml", "pointcloud_map.pcd"]
    for name, h in FACTS["map"]["source_files"].items():
        assert files[name] == h, name
    for sid in ROUTES:
        assert FACTS["map"]["source_osm_sha256"] not in (SCENARIOS / ("town10-%s.json" % sid)).read_text(encoding="utf-8")


@pytest.mark.parametrize("sid", sorted(ROUTES))
def test_check_map_accepts_the_three_hashes_and_refuses_the_sources_osm(aw, sid, tmp_path, monkeypatch):
    """No test reads the map: the files here are empty and their hashes the fixture's, so this holds the scenario's three
    names and hashes to check_map's rule, not any file to its hash."""
    s = aw.load_scenario(SCENARIOS / ("town10-%s.json" % sid))
    for name in FACTS["map"]["files"]:
        (tmp_path / name).write_bytes(b"")
    hashes = dict(FACTS["map"]["files"])
    monkeypatch.setattr(aw, "file_sha256", lambda p: hashes[Path(p).name])
    assert aw.check_map(s, tmp_path) == FACTS["map"]["files"]
    hashes["lanelet2_map.osm"] = FACTS["map"]["source_osm_sha256"]
    with pytest.raises(aw.ScenarioError):
        aw.check_map(s, tmp_path)


# =================================================================================================================
# The timeouts (2.5's design values)
# =================================================================================================================

@pytest.mark.parametrize("sid", sorted(ROUTES))
def test_the_timeouts_are_2_5s_design_values_and_arrive_is_never_below_route(t10, sid):
    for doc in _both(t10, sid):
        t = doc["timeouts_s"]
        assert t == TIMEOUTS[sid]
        assert t["arrive"] >= t["engage"] >= t["route"], t


# =================================================================================================================
# The launch's spawn_point: six numbers, x, y, z, roll, pitch, yaw, degrees, the CARLA frame
# =================================================================================================================

def _parse_as_the_pin_does(text):
    """The pin's _parse_spawn_point (READ, written out here): split on the comma; six items are x, y, z, roll, pitch, yaw,
    each float(); any other count is a random spawn, which this reader refuses."""
    items = text.split(",")
    assert len(items) == 6, text
    return dict(zip(("x", "y", "z", "roll", "pitch", "yaw"), [float(i) for i in items]))


@pytest.mark.parametrize("sid", sorted(SPAWN_POINT))
def test_the_spawn_point_string_is_exact_six_numbers_no_bracket(t10, sid):
    text = t10.scenario_spawn_point(sid)
    assert text == SPAWN_POINT[sid]
    assert re.fullmatch(r"-?\d+\.\d+(,-?\d+\.\d+){5}", text), text
    assert not set(text) & set("[] ")


@pytest.mark.parametrize("sid", sorted(SPAWN_POINT))
def test_the_spawn_points_fields_are_in_the_pins_order_in_degrees_and_the_carla_frame(t10, sid):
    start = ROUTES[sid][0]
    got = _parse_as_the_pin_does(t10.scenario_spawn_point(sid))
    x, y, z, yaw = SPAWNS[start]
    assert got == {"x": x, "y": y, "z": z, "roll": 0.0, "pitch": 0.0, "yaw": yaw}
    # one pose, two writings: the string's fields under the frame rule are the scenario's spawn origin
    mx, my, h = F_TABLE[start]
    assert (got["x"], -got["y"]) == pytest.approx((mx, my), abs=1e-9)
    assert math.radians(-got["yaw"]) == pytest.approx(h, abs=1e-6)


def test_the_spawn_point_yaw_is_never_the_map_frames_radians(t10):
    """A yaw in radians, or the map frame's y, would parse and spawn: two easy mistakes spelled out (2.5)."""
    got = _parse_as_the_pin_does(t10.spawn_point(136))
    assert got["yaw"] == -179.927 and abs(got["yaw"]) > math.tau
    assert got["y"] == 66.358 > 0 > F_TABLE[136][1]


def test_the_string_writes_the_tables_six_fields_in_the_tables_order(t10, monkeypatch):
    """Every roll and pitch of the table is 0.0, so a stand-in spawn shows those two fields' places too."""
    monkeypatch.setitem(t10.SPAWNS, 7, (1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
    assert _parse_as_the_pin_does(t10.spawn_point(7)) == {"x": 1.0, "y": 2.0, "z": 3.0, "roll": 4.0, "pitch": 5.0, "yaw": 6.0}


def test_the_command_prints_the_spawn_point_alone(t10):
    for sid, want in SPAWN_POINT.items():
        r = subprocess.run([sys.executable, "-B", str(MODULE), "spawn-point", sid], capture_output=True, text=True, timeout=60)
        assert (r.returncode, r.stdout) == (0, want + "\n"), r.stderr


def test_the_command_refuses_an_unknown_scenario():
    r = subprocess.run([sys.executable, "-B", str(MODULE), "spawn-point", "t2"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and r.stdout == "" and "invalid choice" in r.stderr


# =================================================================================================================
# The module and the files
# =================================================================================================================

def test_the_module_uses_the_standard_library_alone_and_holds_no_c_or_probed_name():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert names <= set(sys.stdlib_module_names) | {"__future__"}, names
    assigned = {t.id for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
    assert not assigned & {"C", "DELTA_SOURCE", "WHEEL_STEER_POSITIVE", "DRIVE", "ROUTE", "SUBSTEP_S", "FREE_MIB_MIN"}, assigned


def test_the_module_says_what_differs_in_the_osm_and_nothing_of_a_run():
    doc = re.sub(r"\s+", " ", ast.get_docstring(ast.parse(MODULE.read_text(encoding="utf-8"))) or "")
    for phrase in ("Town10HD-aw-n28", "28 `nd` lines of 28 ways", "1.265", "x, y, z, roll, pitch, yaw", "degrees", "CARLA frame",
                   "DOES NOT SHOW"):
        assert phrase in doc, phrase
    for word in ("arrive at", "arrived", "crash", "stall"):
        assert word not in doc.lower(), word


def test_the_osm_sentence_says_what_differs_with_no_figure_beyond_its_count():
    """In the module and the README: the 28 lines and what they leave alone; no tolerance of a private read."""
    doc = re.sub(r"\s+", " ", ast.get_docstring(ast.parse(MODULE.read_text(encoding="utf-8"))) or "")
    readme = re.sub(r"\s+", " ", (CARLA_DIR / "README.md").read_text(encoding="utf-8"))
    for text in (doc, readme):
        assert "28 `nd` lines of 28 ways, its nodes and relations unchanged" in text
        assert not re.search(r"[0-9]e-[0-9]|unmoved within", text), text


def test_the_files_are_lf_and_ascii_and_leave_no_bytecode():
    for f in [MODULE, Path(__file__)] + sorted(SCENARIOS.glob("town10-*")) + [HERE / "fixtures" / "town10" / "facts.json"]:
        data = f.read_bytes()
        assert b"\r" not in data and all(b < 128 for b in data), f.name
    if sys.dont_write_bytecode or os.environ.get("PYTHONDONTWRITEBYTECODE"):         # else another test file's import of town10 may have written one
        assert not list(CARLA_DIR.glob("__pycache__/town10*"))
