# sdv/carlaif -- CARLA 0.10.0's ROS 2 interface for Autoware, at the pinned commit (SDV Phase 8 WP9 P2)

Phase 8 WP9's interface image, project launches and publisher checks. The launch and image rules are
described below. This directory provides no harness for a complete drive.

| file | what |
|---|---|
| `Dockerfile`, `build_image.py` | the interface's image, `sdv-carlaif:local`, run by ID only (`sdv/stack/images.json`'s `carlaif` entry) |
| `pin.json` | the pinned source: `simulator/autoware_carla_interface` of `autoware_universe` at commit `94b8fbd3a8e4df661568270494369b06eb913d66`, tree `472ed962c44bdd6da71d32a5b8253a7fee6a5fc4`; each path with its mode and blob id, no upstream text |
| `wheel.lock` | the CARLA 0.10.0 client wheel, `carla-0.10.0-cp312-cp312-linux_x86_64.whl`, by its sha256 |
| `launch/sdv_carla.launch.xml` | the vehicle side: the interface's node and Autoware's actuation converter |
| `launch/sdv_autoware.launch.xml` | the Autoware side: `autoware.launch.xml` in planning-simulation mode, the simulator component without its dummies, `twist2accel` |
| `config/sensor_mapping_sdv.yaml` | the interface's sensor mapping: an IMU and a GNSS, nothing else |
| `pubcheck.py` | the publisher checks, read before a run's first route and after its last drive |
| `empty_cloud.py` | an empty obstacle cloud for the perception path |
| `clock_sampler.py` | (sim time, CLOCK_MONOTONIC) pairs, one a second |

## The image

`build_image.py build --source DIR --wheels DIR [--proof]` builds the image in WSL from the repo root. `--source` is a
copy of the pinned package; every file is checked by its git blob id against `pin.json`, whose list hashes back to the
tree id, and the one file `pin.json` leaves out (`docs/images/rviz_multi_camera_view.png`) is never staged. `--wheels`
holds the wheel, checked against `wheel.lock`'s sha256. Nothing is fetched: the base is Autoware's Jazzy 1.9.0 image by
its amd64 manifest digest, kept in the image store, and the build runs with `--pull=false` and `--network=none`.

The pinned package is built by colcon into an overlay prefix of its own, `/opt/sdv-carlaif/install`; the wheel goes into
a venv, `/opt/sdv-carlaif/venv`, with the system's site packages, installed with `--no-index --no-deps
--require-hashes`, and the build imports it once and fails unless it is 0.10.0 from the venv. The image's entrypoint is
`sdv/aw/aw-entrypoint.sh`, copied in; it runs as `aw`. Every command run in the image is given under `build_image.py`'s
`LAUNCH_ENV`:

    source /opt/sdv-carlaif/install/local_setup.bash && export PATH=/opt/sdv-carlaif/venv/bin:$PATH

so that `find-pkg-share autoware_carla_interface` names the pin's share (0.53.0), not the image's own 0.52.0 copy under
`/opt/autoware`, and the node's `#!/usr/bin/env python3` is the venv's Python. `build_image.py proof` reads that inside
the image, imports the node's own module there, and parses both launch files with `ros2 launch --print` (T1's spawn point
and the map folder's name from `sdv/carla/town10.py`); its record is a functional result and stays with the run. A
rebuild never removes the image `images.json` pins. The image is in no bundle and no deploy set, is never pushed, and the
stack never starts it.

## The launches

The vehicle side (`aw-carlaif`) takes two arguments, `host` (the CARLA server's address, the default route's gateway read
at run time) and `spawn_point` (`sdv/carla/town10.py spawn-point ID`: six numbers, degrees, the CARLA frame). Every other
value is fixed: the taxi `vehicle.taxi.ford`, the level `Carla/Maps/Town10HD_Opt`, port 2000, timeout 20, synchronous at
0.05 s (the generated contract's `CARLA_STEP_MS` / 1000), `max_substep_delta_time` 0.0 (a 0.10 server keeps its own
substepping), the flat steering curve and the physics nudge on, the ground-truth localization and objects on, the
project's mapping, sim time. The wheel's maximum steer angle, the minimum positive throttle and the rendering switch stay
at the code's defaults. The interface's actuation subscription goes to `/sdv/steershim/actuation_cmd` and its steering
report to `/sdv/steershim/steering_status_raw`, so the steering shim (`sdv/steershim`) sits between Autoware's converter
and the interface. The converter takes the pin's `raw_vehicle_cmd_converter.param.yaml` with `allow_substs`.

The Autoware side (`aw-sim`) takes `map_path`. Autoware runs in planning-simulation mode beside the CARLA interface, not
as upstream's E2E simulator launch: that launch, with sensing, localization and perception off, has no pose initializer,
no tracker, no prediction and no `twist2accel`. Every argument `planning_simulator.launch.xml` passes to its two includes
is passed at its value there, but for this launch's changes; no upstream launch or parameter file is changed.

## The checks and the two small nodes

`pubcheck.py --log FILE [--capture FILE]` reads the graph and judges 2.6's six items (one publisher on each of nine topics,
the actuation type, the interface's subscription, no LiDAR or camera publisher and no RViz, the flat-curve line, the
detection objects); exit 1 on any problem, which stops a run before its first route, and 2 when it cannot judge (a log or
take it cannot read, an rclpy that cannot start, a record it cannot write). With `--capture`, the take `follow010.py`
wrote (it writes `capture.json` when the take ends) is item 5's second source: not refused; its first world settings
read, at attach, synchronous at 0.05 s (the substep is recorded in the take and copied into pubcheck's record, not
judged); and the vehicle's own steering-curve points equal to the interface's flattening, `(0,1),(120,1)`, both as they
follow the client class's default prefix `(0,1),(10,0.5)` in the curve as read and as `follow010.py` recorded them. That
is `follow010.py`'s own rule: it refuses a take whose world is not synchronous at the step at attach, at any re-read or
at the end, or whose own points are not the flattening, so a refused take never passes item 5.

`empty_cloud.py` publishes a `PointCloud2` with no point, frame `base_link`, at 10 Hz of sim time, on
`/perception/obstacle_segmentation/pointcloud` alone. A project node thus feeds Autoware's perception path: every record
says so, and what it publishes.

`clock_sampler.py --out FILE` writes, each second of CLOCK_MONOTONIC, one line `SIM_NS MONO_RECEIPT_NS MONO_TICK_NS`: the
last `/clock` received, the CLOCK_MONOTONIC at which it arrived and the CLOCK_MONOTONIC of the line itself. While no
`/clock` arrives the line repeats the last pair beside a later tick, so a clock that stood still reads as an equal
receipt column under an advancing tick column: a reader interpolates between the distinct receipt pairs while the clock
advances and holds the last sim time across such a stall.

## What this does NOT show

That the image builds or runs anywhere but where its proof was read; that the interface drives a 0.10.0 server or the
taxi; that the grid node makes a grid from an empty cloud; that the publisher checks see an endpoint discovery has not
shown; that the global sim time reaches the simulator's nodes (INFERRED from the launch files' scopes); anything on an
arm64 host (no arm64 client wheel exists); any timing, isolation or safety property.
