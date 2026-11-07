#!/usr/bin/env python3
"""town10.py -- Town 10's scenarios for Autoware on CARLA 0.10.0: one pose, two writings (sdv/carla).

The Phase 8 WP9 specification's 2.5 and section 1's items 5, 6 and 8 (the project's local
design notes; not in this tree). Standard library only: pure functions and two commands, no server, no ROS, no map read.

    usage: town10.py write --dir DIR            the four scenario files, sdv/ctl/scenarios/town10-<id>.json's bytes (DIR exists)
           town10.py spawn-point {t1,t3,t4,t5}  the interface's spawn_point for that scenario's start

THE ROUTES (SCENARIOS). t1 (spawn 136 to 34), t3 (16 to 19), t4 (16 to 45), t5 (86 to 126). NPC_SPAWN is where the stopped NPC
stands on t3's route (npc010.py). The spawns (SPAWNS) are the CARLA spawn points as WP9a's read of the level lists them, by
index; that list gives x, y, z and yaw, and roll and pitch are entered as 0.0.

THE MAP (MAP_NAME, MAP_FILES). Every scenario names the folder Town10HD-aw-n28 and its three hashes, as sdv/ctl/aw_scenario.py's
check_map holds them. Its pointcloud_map.pcd and map_projector_info.yaml are the source folder's, byte for byte; its
lanelet2_map.osm differs from CARLA's Town10HD.osm by 28 `nd` lines of 28 ways, its nodes and relations unchanged; CARLA's own map
is unchanged.

THE FRAME (origin_pose). Map x = carla x, map y = -carla y, heading = -yaw; z 0.0 (the map's every node has ele 0.0). A map-frame
position is rounded to 3 decimals [m], a heading to 6 [rad].

THE OFFSET (BASE_LINK_OFFSET_M, the one place it is written: 1.265 m). The interface puts base_link wheelbase / 2 behind the
actor origin, and item 5 sets its vehicle_config.wheelbase to twice this, so that base_link lies at the taxi's zero-slip point;
that parameter's name says nothing of the taxi's wheelbase. A scenario's initial_pose is the start spawn's base_link pose (the
origin less the offset along the heading), since the driver's initialize moves nothing and the state and the odometry must name
one place; its goal is the goal spawn's origin pose: a goal is a place, not the ego.

THE STRING (spawn_point). The launch's spawn_point is one string of six comma-separated numbers, no brackets, in the order x, y,
z, roll, pitch, yaw, in degrees and the CARLA frame: the pin's _parse_spawn_point splits on the comma and reads six items in that
order, and any other count is a random spawn. Neither the map frame's radians nor carla.Rotation's positional order (pitch, yaw,
roll) is this order.

THE TIMEOUTS (TIMEOUTS_S, SCENARIOS' arrive) are 2.5's design values: localize 60, route 60, engage 120, arrive 300 for t1 and t3,
600 for t4, 450 for t5 (margins well over the planner's top speed at a low real-time factor). A drive that outlasts arrive counts
as not at the goal.

The scenario files are written by this module and never edited; tests/test_sdv_town10.py holds each to its bytes here.

DOES NOT SHOW: that Autoware accepts or drives a route from these poses (the routes are its to take), that the map and the level
agree beyond the points the tests hold, that the level's spawn table still reads as WP9a read it, or that launch hands the string
to the node unchanged; any timing.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

FORMAT = 1
MAP_NAME = "Town10HD-aw-n28"
MAP_FILES = {"lanelet2_map.osm": "37fe677164890fddbc256891ee04faeaf15e712434625de93d9b70366f79ee0d",
             "map_projector_info.yaml": "a6fb6af33e164e61a075f9a79eeffa5eca3ead4435dc3de49e811525175b8307",
             "pointcloud_map.pcd": "7ed7890ebe983b324758835336264dcc6b7f736e51498101262e91de49eee95b"}
# Design value (item 5): base_link behind the actor origin [m], at the taxi's zero-lateral-slip point (W9 E6).
BASE_LINK_OFFSET_M = 1.265
# The level's spawn points by index: x, y, z, roll, pitch, yaw, in the CARLA frame, metres and degrees.
SPAWNS: Dict[int, Tuple[float, float, float, float, float, float]] = {
    16: (-54.345, 137.051, 0.6, 0.0, 0.0, 0.352),
    19: (45.766, 137.46, 0.6, 0.0, 0.0, 0.32),
    34: (6.007, 66.283, 0.6, 0.0, 0.0, -179.927),
    45: (65.235, 13.415, 0.6, 0.0, 0.0, -179.841),
    54: (19.35, 137.46, 0.6, 0.0, 0.0, 0.32),
    86: (-66.794, 12.998, 0.6, 0.0, 0.0, -179.841),
    126: (-52.134, -40.18, 0.6, 0.0, 0.0, 90.432),
    136: (85.982, 66.358, 0.6, 0.0, 0.0, -179.927),
}
# id: start spawn, goal spawn, arrive [s]
SCENARIOS: Dict[str, Tuple[int, int, int]] = {"t1": (136, 34, 300), "t3": (16, 19, 300), "t4": (16, 45, 600), "t5": (86, 126, 450)}
SCENARIO_IDS = tuple(SCENARIOS)
NPC_SPAWN = 54
TIMEOUTS_S = {"localize": 60, "route": 60, "engage": 120}
POS_DECIMALS = 3
HEADING_DECIMALS = 6


def route(sid: str) -> Tuple[int, int, int]:
    """(start spawn, goal spawn, arrive [s]) of a scenario."""
    return SCENARIOS[sid]


def _heading_rad(yaw_deg: float) -> float:
    return math.radians(-yaw_deg)


def origin_pose(index: int) -> Dict[str, float]:
    """A spawn's actor origin in the map frame."""
    x, y, _z, _roll, _pitch, yaw = SPAWNS[index]
    return {"x": x, "y": -y, "z": 0.0, "yaw": round(_heading_rad(yaw), HEADING_DECIMALS)}


def base_link_pose(index: int) -> Dict[str, float]:
    """A spawn's base_link in the map frame: the origin less the offset along the heading."""
    origin, h = origin_pose(index), _heading_rad(SPAWNS[index][5])
    return {"x": round(origin["x"] - BASE_LINK_OFFSET_M * math.cos(h), POS_DECIMALS),
            "y": round(origin["y"] - BASE_LINK_OFFSET_M * math.sin(h), POS_DECIMALS),
            "z": 0.0, "yaw": origin["yaw"]}


def scenario(sid: str) -> Dict[str, Any]:
    """A scenario in sdv/ctl/aw_scenario.py's form (spec-2 2.8)."""
    start, goal, arrive = route(sid)
    return {"format": FORMAT, "name": "town10-%s" % sid, "map": {"name": MAP_NAME, "files": dict(MAP_FILES)},
            "initial_pose": base_link_pose(start), "goal": origin_pose(goal), "timeouts_s": dict(TIMEOUTS_S, arrive=arrive)}


def render(doc: Dict[str, Any]) -> str:
    """A scenario file's text: LF, ASCII, its keys in their order."""
    return json.dumps(doc, indent=2) + "\n"


def spawn_point(index: int) -> str:
    """The launch's spawn_point for a spawn: x,y,z,roll,pitch,yaw in degrees and the CARLA frame."""
    return ",".join(repr(float(v)) for v in SPAWNS[index])


def scenario_spawn_point(sid: str) -> str:
    """The launch's spawn_point for a scenario's start."""
    return spawn_point(route(sid)[0])


def write(directory: Path) -> None:
    """The four scenario files in an existing directory; anything else is refused, with nothing written."""
    if not directory.is_dir():
        raise SystemExit("town10.py: --dir %s is not a directory" % directory)
    for sid in SCENARIO_IDS:
        (directory / ("town10-%s.json" % sid)).write_bytes(render(scenario(sid)).encode("ascii"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write the four scenario files")
    w.add_argument("--dir", required=True, type=Path)
    s = sub.add_parser("spawn-point", help="print the interface's spawn_point for a scenario's start")
    s.add_argument("scenario", choices=SCENARIO_IDS)
    a = ap.parse_args(argv)
    if a.cmd == "write":
        write(a.dir)
    else:
        print(scenario_spawn_point(a.scenario))
    return 0


if __name__ == "__main__":
    sys.exit(main())
