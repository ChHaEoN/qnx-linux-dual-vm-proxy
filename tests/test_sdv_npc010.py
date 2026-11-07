"""5b's stopped NPC (sdv/carla/npc010.py): SDV plan Phase 8 WP9 P1, the WP9 specification's section 1 item 9 and section 4's P1
row.

What is tested, and how. npc010.py runs against tests/fixtures/npc010/fake_npc_carla.py on a fake clock: no CARLA, GPU or
PowerShell runs in any test.

- place: every refusal before connecting (a host other than 127.0.0.1, fwcheck --carla 0.10.0 --for windows-client not
  passing or not run, a --out that exists or lies inside a work tree, a negative spawn) and after it (versions, the level, not
  exactly one ego, an NPC already there, a spawn index the level lacks, a failed spawn, a bounding box with no size), nothing
  left on the server; one actor, vehicle.lincoln.mkz, role_name npc, at the level's spawn point; one apply_control of brake 1.0
  and hand brake; its timeouts set explicitly; no tick, apply_settings, load_world, get_trafficmanager or any other call the
  fake refuses; the hold's lines, each second, its transform and the gap; how the hold ends;
- the gap: bumper to bumper, from each actor's bounding box, signed along the NPC's heading, so an ego that has passed reads
  negative; never between origins;
- destroy: the NPC alone, never the ego;
- the source: the same calls statically, carla imported inside main only, the standard library and this directory's modules.

Every number here is a design value or this file's own synthetic input; none is a reading of CARLA's.

What this does NOT show: that the real server spawns the blueprint there, or that its hand brake holds the car; that the real
bounding boxes are the car's size (the 0.10.0 models' are unread); that Autoware stops behind it; any timing.
"""
import ast
import importlib
import json
import math
import os
import re
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CARLA_DIR = REPO / "sdv" / "carla"
SIM_DIR = REPO / "sdv" / "sim"
FRAME_DIR = REPO / "sdv" / "frame"
MODULE = CARLA_DIR / "npc010.py"
README = CARLA_DIR / "README.md"
FIXTURES = HERE / "fixtures" / "npc010"
FWCHECK_OK = (0, ["fwcheck: PASS (windows-client)"])

for _d in (CARLA_DIR, SIM_DIR, FRAME_DIR, FIXTURES):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _import(name):
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved


fake = _import("fake_npc_carla")


@pytest.fixture(scope="module")
def npc():
    return _import("npc010")


def _lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="ascii").splitlines()]


def _destroy_after(frames):
    def on_frame(sim):
        if sim.frame - sim.start_frame == frames:
            sim.npc().destroy()
    return on_frame


def _world(ego_x=-20.0, **kw):
    sim = fake.Sim()
    sim.add_ego(x=ego_x)
    sim.spawn_points[54] = fake.Transform(fake.Location(19.35, 137.46, 0.6), fake.Rotation(yaw=0.32))
    for k, v in kw.items():
        setattr(sim, k, v)
    return sim


def _place(npc, tmp_path, sim, *extra, frames=3, argv=None, windows=True, fwcheck_run=None):
    """Runs place against the fake and returns (rc, sim, out path, the fake clock's state)."""
    if sim.on_frame is None and frames is not None:
        sim.on_frame = _destroy_after(frames)
    out = tmp_path / "npc.jsonl"
    clock, sleep, state = fake.fake_clock()
    args = argv if argv is not None else ["place", "--spawn", "54", "--out", str(out)] + list(extra)
    rc = npc.main(args, carla=fake.make(sim), windows=windows, fwcheck_run=fwcheck_run or (lambda: FWCHECK_OK), clock=clock, sleep=sleep)
    return rc, sim, out, state


# =================================================================================================================
# The actor: one, the blueprint, the role name, the spawn point, the brake once
# =================================================================================================================

def test_place_spawns_one_actor_of_the_blueprint_with_role_npc_at_the_levels_spawn_point(npc, tmp_path):
    rc, sim, _out, _s = _place(npc, tmp_path, _world())
    assert rc == 0
    assert len(sim.spawned) == 1 and sim.calls.count("spawn_actor:vehicle.lincoln.mkz") == 1
    bp, transform = sim.spawned[0]
    assert bp.id == "vehicle.lincoln.mkz" and bp.attributes == {"role_name": "npc"}
    assert transform is sim.spawn_points[54] or (transform.location.x, transform.location.y) == (19.35, 137.46)


def test_the_role_name_is_npc_and_never_the_followers_ego(npc):
    follow = _import("follow010")
    assert npc.ROLE_NAME == "npc" != follow.ROLE_NAME == npc.EGO_ROLE_NAME
    assert npc.BLUEPRINT == "vehicle.lincoln.mkz" != follow.BLUEPRINT
    assert (npc.HOST, npc.PORT, npc.VERSION, npc.MAP) == (follow.HOST, follow.PORT, follow.VERSION, follow.MAP)


def test_the_followers_one_ego_rule_still_holds_beside_the_npc(npc, tmp_path):
    """follow010.py keeps the actors whose role_name is its own and refuses unless one remains (its own line, written out)."""
    follow = _import("follow010")
    seen = []
    sim = _world()
    ego = sim.actors[0]

    def on_frame(s):
        seen.append([x for x in fake.World(s).get_actors() if dict(x.attributes).get("role_name") == follow.ROLE_NAME])
        s.npc().destroy()

    sim.on_frame = on_frame
    rc, _sim, _out, _s = _place(npc, tmp_path, sim)
    assert rc == 0 and seen == [[ego]]


def test_the_brake_and_the_hand_brake_are_applied_once_on_the_npc_before_any_tick(npc, tmp_path):
    rc, sim, _out, _s = _place(npc, tmp_path, _world())
    assert rc == 0
    assert len(sim.controls) == 1
    actor_id, c = sim.controls[0]
    assert actor_id == 1001 and (c.throttle, c.steer, c.brake, c.hand_brake) == (0.0, 0.0, 1.0, True)
    assert sim.calls.index("spawn_actor:vehicle.lincoln.mkz") < sim.calls.index("apply_control:1001") < sim.calls.index("wait_for_tick")


def test_the_clients_timeouts_are_explicit_and_the_clients_comes_first(npc, tmp_path):
    rc, sim, _out, _s = _place(npc, tmp_path, _world())
    assert rc == 0
    assert sim.calls[0] == "connect:127.0.0.1:2000" and sim.calls[1] == "set_timeout"
    assert sim.client_timeout == npc.CLIENT_TIMEOUT_S == 20.0
    assert set(sim.tick_timeouts) == {npc.TICK_TIMEOUT_S} and npc.TICK_TIMEOUT_S > 0


def test_place_makes_no_forbidden_call_at_run_time(npc, tmp_path):
    rc, sim, _out, _s = _place(npc, tmp_path, _world())
    assert rc == 0
    assert not set(sim.calls) & set(fake.FORBIDDEN), sorted(set(sim.calls) & set(fake.FORBIDDEN))


def _source_tree():
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def test_the_source_names_no_forbidden_call_and_one_spawn(npc):
    """Attribute and bare names in the code, the docstring aside: never tick, apply_settings, load_world, get_trafficmanager, nor
    the others a client that spawns one stopped car has no use for; one spawn_actor, one apply_control."""
    assert set(npc.FORBIDDEN) >= {"tick", "apply_settings", "load_world", "get_trafficmanager"}
    assert set(fake.FORBIDDEN) >= set(npc.FORBIDDEN)
    tree = _source_tree()
    used = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)] + [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    assert not set(used) & set(fake.FORBIDDEN), sorted(set(used) & set(fake.FORBIDDEN))
    assert used.count("spawn_actor") == 1 and used.count("apply_control") == 1


def test_carla_is_imported_inside_main_and_the_rest_is_the_standard_library_and_this_directory():
    tree = _source_tree()
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name.split(".")[0] for n in top if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in top if isinstance(n, ast.ImportFrom) and n.module}
    assert names <= set(sys.stdlib_module_names) | {"__future__", "fwcheck", "frameset"}, names
    assert "carla" not in names


# =================================================================================================================
# The gap: bumper to bumper, each actor's bounding box, signed along the NPC's heading
# =================================================================================================================

def _pose(x=0.0, y=0.0, yaw=0.0):
    return (x, y, yaw)


# (box centre x, y), (half length, half width)
EGO = ((0.0, 0.0), (2.5, 1.0))
NPCB = ((0.0, 0.0), (2.4, 1.0))


def test_the_gap_is_between_the_bumpers_not_the_origins(npc):
    assert npc.bumper_gap_m(_pose(0.0), EGO, _pose(10.0), NPCB) == pytest.approx(10.0 - 2.5 - 2.4)


def test_the_gap_takes_each_boxs_centre_off_its_origin(npc):
    ego = ((0.3, 0.0), (2.5, 1.0))
    other = ((-0.2, 0.0), (2.4, 1.0))
    assert npc.bumper_gap_m(_pose(0.0), ego, _pose(10.0), other) == pytest.approx(10.0 - 0.2 - 0.3 - 2.5 - 2.4)


def test_the_gap_rotates_a_box_by_its_actors_yaw_as_carlas_axes_have_it(npc):
    """x forward, y right, yaw positive turning right: at yaw 90 an actor's nose points along +y."""
    n = _pose(0.0, 10.0, 90.0)
    assert npc.bumper_gap_m(_pose(0.0, 0.0, 90.0), EGO, n, NPCB) == pytest.approx(10.0 - 2.5 - 2.4)
    off = ((-0.2, 0.0), (2.4, 1.0))
    assert npc.bumper_gap_m(_pose(0.0, 0.0, 90.0), EGO, n, off) == pytest.approx(10.0 - 0.2 - 2.5 - 2.4)


def test_the_gap_is_read_along_the_npcs_heading_with_a_yawed_ego_by_its_corners(npc):
    """An ego turned 90 degrees shows its side to the NPC: its half width counts along the NPC's heading, not its half length."""
    assert npc.bumper_gap_m(_pose(0.0, 0.0, 90.0), EGO, _pose(10.0), NPCB) == pytest.approx(10.0 - 1.0 - 2.4)
    d = math.radians(30.0)
    reach = 2.5 * math.cos(d) + 1.0 * math.sin(d)
    assert npc.bumper_gap_m(_pose(0.0, 0.0, 30.0), EGO, _pose(10.0), NPCB) == pytest.approx(10.0 - reach - 2.4)


def test_a_gap_is_negative_once_the_boxes_overlap_along_the_road_or_the_ego_has_passed(npc):
    assert npc.bumper_gap_m(_pose(8.0), EGO, _pose(10.0), NPCB) == pytest.approx(2.0 - 4.9)        # touching or overlapping
    assert npc.bumper_gap_m(_pose(10.0, 3.5), EGO, _pose(10.0), NPCB) == pytest.approx(-4.9)       # alongside, a lane over
    assert npc.bumper_gap_m(_pose(30.0), EGO, _pose(10.0), NPCB) < -20.0                           # passed


def test_the_gap_holds_on_a_road_running_the_other_way(npc):
    """Heading -x (yaw about 180): the ego behind the NPC lies at larger x."""
    assert npc.bumper_gap_m(_pose(20.0, 0.0, -179.9), EGO, _pose(10.0, 0.0, -179.9), NPCB) == pytest.approx(10.0 - 4.9, abs=1e-4)
    assert npc.bumper_gap_m(_pose(0.0, 0.0, -179.9), EGO, _pose(10.0, 0.0, -179.9), NPCB) < -14.0


def test_the_line_gives_the_gap_from_the_actors_own_boxes_not_their_origins(npc, tmp_path):
    sim = _world(ego_x=0.0)
    sim.spawn_points[54] = fake.Transform(fake.Location(20.0, 0.0, 0.6), fake.Rotation(yaw=0.0))
    rc, _sim, out, _s = _place(npc, tmp_path, sim)
    assert rc == 0
    s = [x for x in _lines(out) if x["kind"] == "sample"][0]
    (el, _), (ee, _) = fake.NPC_BOX, fake.EGO_BOX
    assert s["gap_m"] == pytest.approx((20.0 + el[0] - fake.NPC_BOX[1][0]) - (0.0 + ee[0] + fake.EGO_BOX[1][0]))
    assert s["gap_m"] != pytest.approx(20.0)


def test_the_ego_moving_changes_the_gap_each_line(npc, tmp_path):
    sim = _world(ego_x=-30.0)
    sim.spawn_points[54] = fake.Transform(fake.Location(20.0, 0.0, 0.6), fake.Rotation(yaw=0.0))
    ego = sim.actors[0]

    def on_frame(s):
        ego.transform.location.x += 5.0
        if s.frame - s.start_frame == 3:
            s.npc().destroy()

    sim.on_frame = on_frame
    rc, _sim, out, _s = _place(npc, tmp_path, sim)
    gaps = [x["gap_m"] for x in _lines(out) if x["kind"] == "sample"]
    assert rc == 0 and len(gaps) == 2 and gaps[1] == pytest.approx(gaps[0] - 5.0)


def test_the_lines_gap_reads_each_actors_yaw_on_a_road_running_along_y(npc, tmp_path):
    """Both actors at yaw 90, their pitch 0: the NPC's nose points along +y, so the gap runs along y: 20 - (0.1 + 2.5) + (-0.2 - 2.4)."""
    sim = fake.Sim()
    sim.add_ego(x=0.0, yaw=90.0)
    sim.spawn_points[54] = fake.Transform(fake.Location(0.0, 20.0, 0.6), fake.Rotation(yaw=90.0))
    rc, _sim, out, _s = _place(npc, tmp_path, sim)
    first = [x for x in _lines(out) if x["kind"] == "sample"][0]
    assert rc == 0 and first["gap_m"] == pytest.approx(14.8)


def test_the_lines_gap_is_the_gap_functions_for_two_actors_of_different_yaws(npc, tmp_path):
    """The NPC at yaw 90 and the ego at yaw 7: a line whose gap read pitch (0.0 on both) for yaw, or one's yaw for the other's, reads another."""
    sim = fake.Sim()
    sim.add_ego(x=3.0, y=-8.0, yaw=7.0)
    sim.spawn_points[54] = fake.Transform(fake.Location(2.0, 12.0, 0.6), fake.Rotation(yaw=90.0))
    rc, _sim, out, _s = _place(npc, tmp_path, sim)
    first = [x for x in _lines(out) if x["kind"] == "sample"][0]
    ego_box = ((fake.EGO_BOX[0][0], fake.EGO_BOX[0][1]), (fake.EGO_BOX[1][0], fake.EGO_BOX[1][1]))
    npc_box = ((fake.NPC_BOX[0][0], fake.NPC_BOX[0][1]), (fake.NPC_BOX[1][0], fake.NPC_BOX[1][1]))
    want = npc.bumper_gap_m((3.0, -8.0, 7.0), ego_box, (2.0, 12.0, 90.0), npc_box)
    assert rc == 0 and first["gap_m"] == want
    for ego_yaw, npc_yaw in ((0.0, 0.0), (90.0, 7.0), (7.0, 7.0), (90.0, 90.0), (0.0, 90.0)):       # the test tells these from the line's
        assert abs(want - npc.bumper_gap_m((3.0, -8.0, ego_yaw), ego_box, (2.0, 12.0, npc_yaw), npc_box)) > 0.2, (ego_yaw, npc_yaw)


# =================================================================================================================
# The lines: its transform and the gap, each second, flushed; the boxes once
# =================================================================================================================

def test_the_out_file_holds_the_placed_line_a_sample_each_second_and_the_end(npc, tmp_path):
    rc, sim, out, state = _place(npc, tmp_path, _world(), frames=4)
    assert rc == 0
    lines = _lines(out)
    assert [x["kind"] for x in lines] == ["placed", "sample", "sample", "sample", "end"]
    placed = lines[0]
    assert (placed["blueprint"], placed["role_name"], placed["spawn"]) == ("vehicle.lincoln.mkz", "npc", 54)
    spawn = placed["spawn_transform"]
    assert (spawn["x"], spawn["y"], spawn["yaw"]) == (19.35, 137.46, 0.32)
    assert placed["npc_box"] == {"location": [-0.2, 0.0], "extent": [2.4, 1.0]}
    assert placed["ego_box"] == {"location": [0.1, 0.0], "extent": [2.5, 1.0]}
    samples = lines[1:-1]
    assert state["sleeps"] == [npc.WRITE_PERIOD_S] * 3 and npc.WRITE_PERIOD_S == 1.0
    assert [x["t_s"] for x in samples] == [0.0, 1.0, 2.0]
    assert [x["frame"] for x in samples] == [4001, 4002, 4003]
    assert samples[0]["elapsed_s"] == pytest.approx(12.55)
    assert samples[0]["npc"] == {"x": 19.35, "y": 137.46, "z": 0.6, "roll": 0.0, "pitch": 0.0, "yaw": 0.32}
    assert samples[0]["control"] == {"brake": 1.0, "hand_brake": True}
    assert samples[0]["ego"]["x"] == -20.0
    assert lines[-1]["reason"] == "destroyed" and lines[-1]["npc_destroyed_here"] is False
    assert sim.calls.count("destroy:1001") == 1             # on_frame's: the end line asks no destroy of an NPC that is gone


def test_a_samples_npc_transform_carries_the_roll_and_pitch_of_its_own(npc, tmp_path):
    """Roll 0.5 and pitch 1.5 on the NPC's spawn point: each reaches its own key, on the placed line and on a sample."""
    sim = _world()
    sim.spawn_points[54] = fake.Transform(fake.Location(19.35, 137.46, 0.6), fake.Rotation(pitch=1.5, yaw=0.32, roll=0.5))
    rc, _sim, out, _s = _place(npc, tmp_path, sim)
    lines = _lines(out)
    assert rc == 0
    for doc in (lines[0]["spawn_transform"], [x for x in lines if x["kind"] == "sample"][0]["npc"]):
        assert (doc["roll"], doc["pitch"], doc["yaw"]) == (0.5, 1.5, 0.32)


def test_the_first_samples_transform_follows_a_tick_never_the_zero_before_it(npc, tmp_path):
    """As on a synchronous server, a spawned actor reads zero until the next tick: the first sample comes after one."""
    rc, sim, out, _s = _place(npc, tmp_path, _world())
    first = [x for x in _lines(out) if x["kind"] == "sample"][0]
    assert rc == 0 and first["npc"]["x"] == 19.35
    assert sim.calls.index("wait_for_tick") < sim.calls.index("get_transform:1001")


def test_a_sample_that_takes_time_comes_off_the_sleep_so_the_lines_stay_on_whole_seconds(npc, tmp_path, monkeypatch):
    """Each sample takes 0.3 s of the clock: the sleep is what is left of its second, never a whole period on top of it."""
    sim = _world(on_frame=_destroy_after(4))
    clock, sleep, state = fake.fake_clock()
    real = fake.Actor.get_transform

    def slow(self):
        if self.id == 1001:
            state["now"] += 0.3
        return real(self)

    monkeypatch.setattr(fake.Actor, "get_transform", slow)
    out = tmp_path / "npc.jsonl"
    rc = npc.main(["place", "--spawn", "54", "--out", str(out)], carla=fake.make(sim), windows=True, fwcheck_run=lambda: FWCHECK_OK,
                  clock=clock, sleep=sleep)
    assert rc == 0 and state["sleeps"] == pytest.approx([0.7, 0.7, 0.7])
    assert [x["t_s"] for x in _lines(out) if x["kind"] == "sample"] == pytest.approx([0.0, 1.0, 2.0])


def test_each_line_is_on_the_disk_when_the_next_tick_is_awaited(npc, tmp_path):
    seen = []
    sim = _world()

    def on_frame(s):
        seen.append(len((tmp_path / "npc.jsonl").read_text(encoding="ascii").splitlines()))
        if s.frame - s.start_frame == 3:
            s.npc().destroy()

    sim.on_frame = on_frame
    rc, _sim, _out, _s = _place(npc, tmp_path, sim)
    assert rc == 0 and seen == [1, 2, 3]


def test_an_ego_gone_during_the_hold_gives_no_gap_and_the_hold_goes_on(npc, tmp_path):
    sim = _world()
    ego = sim.actors[0]

    def on_frame(s):
        if s.frame - s.start_frame == 2:
            ego.destroy()
        if s.frame - s.start_frame == 3:
            s.npc().destroy()

    sim.on_frame = on_frame
    rc, _sim, out, _s = _place(npc, tmp_path, sim)
    samples = [x for x in _lines(out) if x["kind"] == "sample"]
    assert rc == 0 and samples[0]["gap_m"] is not None
    assert samples[1]["ego"] is None and samples[1]["gap_m"] is None


# =================================================================================================================
# How the hold ends
# =================================================================================================================

def test_the_hold_limit_destroys_the_npc_and_exits_1(npc, tmp_path):
    sim = _world(on_frame=lambda s: None)
    rc, _sim, out, _s = _place(npc, tmp_path, sim, "--hold-s", "2", frames=None)
    assert rc == 1 and sim.destroyed == [1001] and sim.actors[0].attributes["role_name"] == "ego_vehicle" and len(sim.actors) == 1
    end = _lines(out)[-1]
    assert (end["kind"], end["reason"], end["npc_destroyed_here"]) == ("end", "hold-limit", True)


def test_a_tick_that_never_comes_ends_the_hold_with_exit_1(npc, tmp_path):
    sim = _world(on_frame=lambda s: None, frames_left=2)
    rc, _sim, out, _s = _place(npc, tmp_path, sim, frames=None)
    assert rc == 1 and sim.destroyed == [1001]
    end = _lines(out)[-1]
    assert end["reason"] == "no-tick" and "time-out" in end["error"]


def test_a_server_gone_cannot_stop_the_end_line(npc, tmp_path):
    sim = _world()

    def on_frame(s):
        if s.frame - s.start_frame == 2:
            s.server_gone = True

    sim.on_frame = on_frame
    rc, _sim, out, _s = _place(npc, tmp_path, sim)
    end = _lines(out)[-1]
    assert rc == 1 and (end["reason"], end["npc_destroyed_here"]) == ("no-tick", False) and "destroy_error" in end


def test_a_ctrl_c_destroys_the_npc_and_exits_130(npc, tmp_path):
    sim = _world(on_frame=lambda s: None, interrupt_at=2)
    rc, _sim, out, _s = _place(npc, tmp_path, sim, frames=None)
    assert rc == 130 and sim.destroyed == [1001]
    assert _lines(out)[-1]["reason"] == "interrupted"


def _interrupt(*_a, **_k):
    raise KeyboardInterrupt


def _no_leak(run):
    """A KeyboardInterrupt out of main would end pytest's whole session: here it fails this one test."""
    try:
        return run()
    except KeyboardInterrupt:
        pytest.fail("a Ctrl-C left main as a KeyboardInterrupt, with no exit status of its own")


def test_a_ctrl_c_in_the_first_control_destroys_the_npc_and_exits_130(npc, tmp_path, monkeypatch, capsys):
    """After spawn_actor has returned and before the hold, with no file yet."""
    monkeypatch.setattr(fake.Actor, "apply_control", _interrupt)
    sim = _world()
    rc, _sim, out, _s = _no_leak(lambda: _place(npc, tmp_path, sim, frames=None))
    assert rc == 130 and sim.destroyed == [1001] and not out.exists()
    assert "interrupted" in capsys.readouterr().err


def test_a_ctrl_c_opening_the_file_destroys_the_npc_and_exits_130(npc, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(npc, "open", _interrupt, raising=False)
    sim = _world()
    rc, _sim, out, _s = _no_leak(lambda: _place(npc, tmp_path, sim, frames=None))
    assert rc == 130 and sim.destroyed == [1001] and not out.exists()
    assert "no end line" in capsys.readouterr().err


def test_a_ctrl_c_writing_the_lines_destroys_the_npc_once_and_exits_130(npc, tmp_path, monkeypatch):
    """The placed line's Ctrl-C ends the hold; the end line's own, on an NPC already gone, finds nothing more to destroy."""
    monkeypatch.setattr(npc, "_line", _interrupt)
    sim = _world()
    rc, _sim, _out, _s = _no_leak(lambda: _place(npc, tmp_path, sim, frames=None))
    assert rc == 130 and sim.destroyed == [1001] and sim.calls.count("destroy:1001") == 1


def test_a_ctrl_c_in_the_end_lines_destroy_is_said_on_that_line_and_exits_130(npc, tmp_path, monkeypatch):
    """The hold had ended for its limit, so the Ctrl-C alone is what makes this 130; it is not retried, and the NPC may stay."""
    monkeypatch.setattr(fake.Actor, "destroy", _interrupt)
    sim = _world(on_frame=lambda s: None)
    rc, _sim, out, _s = _no_leak(lambda: _place(npc, tmp_path, sim, "--hold-s", "2", frames=None))
    end = _lines(out)[-1]
    assert rc == 130 and (end["kind"], end["reason"], end["npc_destroyed_here"]) == ("end", "interrupted", False)
    assert "Ctrl-C" in end["destroy_error"]


@pytest.mark.parametrize("argv", [["destroy"], ["place", "--spawn", "54", "--out", "OUT"]])
def test_a_ctrl_c_before_anything_is_placed_exits_130(npc, tmp_path, monkeypatch, capsys, argv):
    monkeypatch.setattr(fake.Client, "get_world", _interrupt)
    sim = _world()
    args = [str(tmp_path / "n.jsonl") if a == "OUT" else a for a in argv]
    rc = _no_leak(lambda: npc.main(args, carla=fake.make(sim), windows=True, fwcheck_run=lambda: FWCHECK_OK))
    assert rc == 130 and sim.spawned == [] and not (tmp_path / "n.jsonl").exists()
    assert "interrupted" in capsys.readouterr().err


def test_a_failed_read_during_the_hold_still_ends_in_the_end_line_and_the_cleanup(npc, tmp_path):
    sim = _world()

    def on_frame(s):
        if s.frame - s.start_frame == 2:
            def broken():
                raise RuntimeError("time-out reading the fake actor")
            s.npc().get_transform = broken

    sim.on_frame = on_frame
    rc, _sim, out, _s = _place(npc, tmp_path, sim)
    end = _lines(out)[-1]
    assert rc == 1 and end["reason"] == "error" and "time-out" in end["error"] and sim.destroyed == [1001]


def test_a_destroy_the_server_refuses_is_said(npc, tmp_path):
    sim = _world(on_frame=lambda s: None, destroy_answers_false=True, frames_left=1)
    rc, _sim, out, _s = _place(npc, tmp_path, sim, frames=None)
    assert rc == 1 and _lines(out)[-1]["npc_destroyed_here"] is False


def test_a_control_the_server_fails_leaves_no_npc_no_file_and_exit_1(npc, tmp_path, monkeypatch, capsys):
    """After the spawn, before the hold: apply_control raises a RuntimeError, as a timed-out client does."""
    def broken(self, control):
        raise RuntimeError("time-out applying the fake control")

    monkeypatch.setattr(fake.Actor, "apply_control", broken)
    rc, sim, out, _s = _place(npc, tmp_path, _world(), frames=None)
    assert rc == 1 and sim.destroyed == [1001] and not out.exists()
    assert "time-out applying" in capsys.readouterr().err


def test_a_write_that_fails_in_the_hold_destroys_the_npc_before_the_end_lines_write_fails_out_of_main(npc, tmp_path, monkeypatch):
    """Every write from the third on raises OSError: the hold ends as an error, the NPC is destroyed, the end line's own write
    raises the same, and the OSError leaves main (a traceback, exit 1) with the NPC gone."""
    real, kinds = npc._line, []

    def failing(f, doc):
        kinds.append(doc["kind"])
        if len(kinds) >= 3:
            raise OSError(28, "No space left on device (the fake disk)")
        real(f, doc)

    monkeypatch.setattr(npc, "_line", failing)
    sim = _world()
    with pytest.raises(OSError):
        _place(npc, tmp_path, sim)
    assert sim.destroyed == [1001] and kinds == ["placed", "sample", "sample", "end"]


# =================================================================================================================
# The refusals before connecting: exit 2, no client made, no file written
# =================================================================================================================

@pytest.mark.parametrize("host", ["203.0.113.5", "localhost", "::1", "127.000.000.001"])
def test_a_host_other_than_loopback_is_refused_before_connecting(npc, tmp_path, capsys, host):
    """Only the literal 127.0.0.1: another name for the same machine is not it, and the host is judged before fwcheck is asked."""
    asked = []
    rc, sim, out, _s = _place(npc, tmp_path, _world(), "--host", host, fwcheck_run=lambda: asked.append(1) or FWCHECK_OK)
    assert rc == 2 and sim.calls == [] and asked == [] and not out.exists()
    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize("answer", [(1, ["fwcheck: FAIL (windows-client): P1: a rule"]), (2, ["fwcheck: the firewall read failed"])])
def test_an_fwcheck_that_does_not_pass_is_refused_before_connecting(npc, tmp_path, capsys, answer):
    rc, sim, out, _s = _place(npc, tmp_path, _world(), fwcheck_run=lambda: answer)
    assert rc == 2 and sim.calls == [] and not out.exists()
    assert answer[1][0] in capsys.readouterr().err


def test_fwcheck_is_asked_for_the_windows_client_of_0_10_0(npc, monkeypatch):
    asked = []
    monkeypatch.setattr(npc.fwcheck, "run", lambda for_, **k: asked.append((for_, k)) or FWCHECK_OK)
    assert npc.preflight(npc.HOST, None, True, None) == FWCHECK_OK[1][0]
    assert asked == [("windows-client", {"carla": "0.10.0"})]


def test_a_run_off_windows_is_refused_since_the_gate_cannot_run(npc, tmp_path, capsys):
    rc, sim, _out, _s = _place(npc, tmp_path, _world(), windows=False)
    assert rc == 2 and sim.calls == []
    assert "Windows" in capsys.readouterr().err


def test_an_out_file_that_exists_is_refused_and_kept(npc, tmp_path):
    out = tmp_path / "npc.jsonl"
    out.write_text("kept\n", encoding="ascii")
    rc, sim, _o, _s = _place(npc, tmp_path, _world())
    assert rc == 2 and sim.calls == [] and out.read_text(encoding="ascii") == "kept\n"


def test_an_out_file_inside_a_work_tree_is_refused(npc, tmp_path):
    (tmp_path / ".git").mkdir()
    rc, sim, out, _s = _place(npc, tmp_path, _world())
    assert rc == 2 and sim.calls == [] and not out.exists()


def test_an_out_file_whose_parent_is_no_directory_is_refused_before_connecting(npc, tmp_path):
    sim = _world()
    rc, _sim, _o, _s = _place(npc, tmp_path, sim, argv=["place", "--spawn", "54", "--out", str(tmp_path / "absent" / "n.jsonl")])
    assert rc == 2 and sim.calls == []


def test_an_out_file_that_cannot_be_made_after_the_spawn_leaves_no_npc(npc, tmp_path, monkeypatch, capsys):
    """The file appears between the check and the spawn: open("x") refuses it, and the NPC does not stay."""
    sim = _world()
    out = tmp_path / "npc.jsonl"
    real = sim.spawn_points

    def on_spawn_points():
        out.write_text("kept\n", encoding="ascii")
        return list(real)

    monkeypatch.setattr(fake.Map, "get_spawn_points", lambda self: on_spawn_points())
    rc, _sim, _o, _s = _place(npc, tmp_path, sim, frames=None)
    assert rc == 1 and "refused" in capsys.readouterr().err
    assert sim.destroyed == [1001] and out.read_text(encoding="ascii") == "kept\n"


def test_a_client_that_fails_before_any_placing_exits_1_without_a_traceback(npc, tmp_path, capsys):
    sim = _world()

    def broken():
        raise RuntimeError("time-out of the fake server")

    carla = fake.make(sim)
    real_client = carla.Client

    def client(host, port):
        c = real_client(host, port)
        c.get_world = broken
        return c

    carla.Client = client
    out = tmp_path / "n.jsonl"
    assert npc.main(["place", "--spawn", "54", "--out", str(out)], carla=carla, windows=True, fwcheck_run=lambda: FWCHECK_OK) == 1
    assert npc.main(["destroy"], carla=carla, windows=True, fwcheck_run=lambda: FWCHECK_OK) == 1
    assert "time-out" in capsys.readouterr().err and not out.exists() and sim.spawned == []


@pytest.mark.parametrize("spawn", ["-1", "1.5", "x"])
def test_a_spawn_that_is_no_index_is_refused(npc, tmp_path, spawn):
    out = tmp_path / "npc.jsonl"
    sim = _world()
    with pytest.raises(SystemExit) as e:
        _place(npc, tmp_path, sim, argv=["place", "--spawn=" + spawn, "--out", str(out)])
    assert e.value.code == 2 and sim.calls == []


@pytest.mark.parametrize("hold", ["0", "-5", "nan", "inf", "x"])
def test_a_hold_that_is_no_positive_time_is_refused(npc, tmp_path, hold):
    sim = _world()
    with pytest.raises(SystemExit) as e:
        _place(npc, tmp_path, sim, "--hold-s=" + hold)
    assert e.value.code == 2 and sim.calls == []


def test_place_requires_its_spawn_and_out(npc):
    for argv in (["place", "--out", "x"], ["place", "--spawn", "54"]):
        with pytest.raises(SystemExit) as e:
            npc.main(argv, carla=fake.make(fake.Sim()), windows=True, fwcheck_run=lambda: FWCHECK_OK)
        assert e.value.code == 2


def test_no_carla_client_is_a_refusal(npc, tmp_path, monkeypatch, capsys):
    real = importlib.import_module

    def refuse(name, *a, **k):
        if name == "carla":
            raise ImportError("no carla here")
        return real(name, *a, **k)

    monkeypatch.setattr(npc.importlib, "import_module", refuse)
    rc = npc.main(["place", "--spawn", "54", "--out", str(tmp_path / "n.jsonl")], windows=True, fwcheck_run=lambda: FWCHECK_OK)
    assert rc == 2 and "refused" in capsys.readouterr().err and not (tmp_path / "n.jsonl").exists()


def test_the_client_is_the_module_named_carla_when_none_is_handed_in(npc, tmp_path, monkeypatch):
    sim = _world(on_frame=_destroy_after(3))
    monkeypatch.setitem(sys.modules, "carla", fake.make(sim))
    clock, sleep, _state = fake.fake_clock()
    rc = npc.main(["place", "--spawn", "54", "--out", str(tmp_path / "n.jsonl")], windows=True, fwcheck_run=lambda: FWCHECK_OK,
                  clock=clock, sleep=sleep)
    assert rc == 0 and sim.calls[0] == "connect:127.0.0.1:2000"


@pytest.mark.skipif(os.name == "nt", reason="the default is read from os.name: on Windows it reads as Windows, and the gate can run")
def test_the_platform_is_read_when_the_caller_does_not_say_and_off_windows_it_is_refused(npc, tmp_path, capsys):
    sim = _world(on_frame=_destroy_after(3))                 # and the fake clock: a place that is not refused ends at once, never in real time
    clock, sleep, _state = fake.fake_clock()
    out = tmp_path / "n.jsonl"
    rc = npc.main(["place", "--spawn", "54", "--out", str(out)], carla=fake.make(sim), fwcheck_run=lambda: FWCHECK_OK, clock=clock, sleep=sleep)
    assert rc == 2 and sim.calls == [] and not out.exists()
    assert "Windows" in capsys.readouterr().err


# =================================================================================================================
# The refusals after connecting: exit 1, the reason said, nothing left on the server
# =================================================================================================================

@pytest.mark.parametrize("change", [
    lambda s: setattr(s, "client_version", "0.9.16"),
    lambda s: setattr(s, "server_version", "0.9.16"),
    lambda s: setattr(s, "map_name", "Carla/Maps/Town01"),
    lambda s: s.actors.clear(),                                       # no ego: the interface has not attached (item 9's order)
    lambda s: s.add_ego(x=5.0),                                       # two egos
    lambda s: s.add_ego(x=5.0, role="npc", type_id="vehicle.lincoln.mkz"),   # an NPC is already there: never a second actor
    lambda s: setattr(s, "spawn_points", s.spawn_points[:54]),        # the index is past the level's table
    lambda s: setattr(s, "blueprints", ("vehicle.taxi.ford",)),
    lambda s: setattr(s, "spawn_raises", True),
])
def test_a_world_that_is_not_the_one_expected_is_refused_with_nothing_placed(npc, tmp_path, capsys, change):
    sim = _world()
    change(sim)
    before = list(sim.actors)
    rc, _sim, out, _s = _place(npc, tmp_path, sim, frames=None)
    assert rc == 1, capsys.readouterr().err
    assert sim.actors == before and sim.destroyed == [] and sim.controls == []
    assert "refused" in capsys.readouterr().err and not out.exists()


@pytest.mark.parametrize("which", ["npc", "ego"])
@pytest.mark.parametrize("extent", [(0.0, 0.0, 0.0), (float("nan"), 1.0, 0.7), (-2.4, 1.0, 0.7)])
def test_a_bounding_box_with_no_size_is_refused_since_the_gap_would_read_between_origins(npc, tmp_path, capsys, which, extent):
    sim = _world()
    box = types.SimpleNamespace(location=fake.Location(), extent=fake.Location(*extent), rotation=fake.Rotation())
    if which == "npc":
        sim.npc_box = box
    else:
        sim.actors[0].bounding_box = box
    rc, _sim, out, _s = _place(npc, tmp_path, sim, frames=None)
    assert rc == 1 and "bounding box" in capsys.readouterr().err
    assert len(sim.actors) == 1 and sim.actors[0].attributes["role_name"] == "ego_vehicle" and not out.exists()


# =================================================================================================================
# destroy
# =================================================================================================================

def _destroy(npc, sim, *extra, fwcheck_run=None, windows=True):
    return npc.main(["destroy"] + list(extra), carla=fake.make(sim), windows=windows, fwcheck_run=fwcheck_run or (lambda: FWCHECK_OK))


def test_destroy_takes_the_npc_alone_and_never_the_ego(npc, capsys):
    sim = _world()
    ego = sim.actors[0]
    placed = sim.add_ego(x=19.0, role="npc", type_id="vehicle.lincoln.mkz")
    other = sim.add_ego(x=30.0, role="other", type_id="vehicle.lincoln.mkz")
    assert _destroy(npc, sim) == 0
    assert sim.destroyed == [placed.id] and sim.actors == [ego, other]
    assert sim.client_timeout == npc.CLIENT_TIMEOUT_S and sim.calls[1] == "set_timeout"
    assert "destroyed" in capsys.readouterr().out


def test_destroy_with_no_npc_says_so_and_exits_1(npc, capsys):
    sim = _world()
    assert _destroy(npc, sim) == 1 and sim.destroyed == []
    assert "no actor" in capsys.readouterr().err


def test_destroy_that_the_server_refuses_exits_1(npc):
    sim = _world(destroy_answers_false=True)
    sim.add_ego(x=19.0, role="npc", type_id="vehicle.lincoln.mkz")
    assert _destroy(npc, sim) == 1


def test_destroy_exits_1_when_the_server_refuses_one_of_two_npcs(npc, capsys, monkeypatch):
    sim = _world()
    first = sim.add_ego(x=19.0, role="npc", type_id="vehicle.lincoln.mkz")
    second = sim.add_ego(x=30.0, role="npc", type_id="vehicle.lincoln.mkz")
    monkeypatch.setattr(second, "destroy", lambda: False)
    assert _destroy(npc, sim) == 1
    assert sim.destroyed == [first.id] and "destroyed 1 of 2" in capsys.readouterr().out


def test_destroy_keeps_the_same_refusals_before_connecting(npc):
    sim = _world()
    assert _destroy(npc, sim, "--host", "203.0.113.5") == 2 and sim.calls == []
    assert _destroy(npc, sim, fwcheck_run=lambda: (1, ["fwcheck: FAIL (windows-client): P1: a rule"])) == 2 and sim.calls == []
    assert _destroy(npc, sim, windows=False) == 2 and sim.calls == []


def test_destroy_makes_no_forbidden_call(npc):
    sim = _world()
    sim.add_ego(x=19.0, role="npc", type_id="vehicle.lincoln.mkz")
    _destroy(npc, sim)
    assert not set(sim.calls) & set(fake.FORBIDDEN)


def test_a_destroy_beside_a_hold_ends_the_hold_with_exit_0(npc, tmp_path):
    """The run's end: the second process's destroy, seen by place at its next sample."""
    sim = _world()

    def on_frame(s):
        if s.frame - s.start_frame == 2:
            assert _destroy(npc, s) == 0

    sim.on_frame = on_frame
    rc, _sim, out, _s = _place(npc, tmp_path, sim)
    assert rc == 0 and _lines(out)[-1]["reason"] == "destroyed" and sim.destroyed == [1001]


# =================================================================================================================
# The texts and the files
# =================================================================================================================

def _doc():
    return re.sub(r"\s+", " ", ast.get_docstring(_source_tree()) or "")


def test_the_module_says_what_it_does_and_does_not_show():
    doc = _doc()
    for phrase in ("place --spawn N", "destroy", "vehicle.lincoln.mkz", "role_name", "hand brake", "bumper", "bounding box", "127.0.0.1",
                   "fwcheck", "wait_for_tick", "DOES NOT SHOW", "a moving NPC", "a failed write",
                   "is_alive turns false on a destroy from a second process"):
        assert phrase in doc, phrase


def test_the_readme_table_gains_the_two_modules():
    text = re.sub(r"\s+", " ", README.read_text(encoding="utf-8"))
    tail = text[text.index("## CARLA 0.10.0 (Phase 8 WP9b)"):]
    for row in ("| `town10.py` |", "| `npc010.py` |"):
        assert row in tail, row
    for phrase in ("Town10HD-aw-n28", "28 `nd` lines of 28 ways", "npc010.py place --spawn", "npc010.py destroy", "x, y, z, roll, pitch, yaw",
                   "moving obstacle", "roll and pitch are entered as 0.0"):
        assert phrase in tail, phrase
    for word in ("crash", "stall"):
        assert word not in tail.lower(), word


def test_the_module_and_the_readme_say_that_a_ctrl_c_can_leave_the_npc():
    """The windows no handler can close: the run's end takes the NPC whatever place said."""
    assert "the run's end runs destroy whatever place said" in _doc()
    assert "the run's end runs `destroy` whatever `place` said" in re.sub(r"\s+", " ", README.read_text(encoding="utf-8"))


def test_the_files_are_lf_and_ascii():
    for f in (MODULE, Path(__file__), FIXTURES / "fake_npc_carla.py", README):
        data = f.read_bytes()
        assert b"\r" not in data and all(b < 128 for b in data), f.name
