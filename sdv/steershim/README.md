# sdv/steershim: D22's steering shim between Autoware and CARLA 0.10.0's interface

Phase 8 WP9b, under the owner's D22: Autoware's steering goes through the inverse
of the model in `sdv/sim/carla010_iso.py`, and Autoware's controller is not recalibrated. Its
topics, conversions and refusals are described below. Nothing here starts a container or a simulator.

| file | what it is |
|---|---|
| `steershim.py` | The pure functions, one message at a time, no state: C read by path, the inverse, the forward, the copy of a message with its steer replaced, the check of the report topic's publishers; the four topics and the interface's constants in one place. Standard library only. |
| `shim_node.py` | The rclpy node around them: two subscriptions and two publishers; no timer, no service and no parameter of its own (rclpy adds `/rosout`, `/parameter_events` and the `use_sim_time` parameter on its own). rclpy and the message packages are imported inside `main` only. |

## A project node sits in Autoware's actuation path

With the shim, a project node sits in Autoware's actuation path: between the actuation command Autoware's
`raw_vehicle_cmd_converter` publishes and CARLA's interface (`autoware_carla_interface`), and between the interface's
steering report and Autoware. It changes only the steer: the actuation command's steer field on the way to the
interface, and the steering report's `steering_tire_angle` on the way back. Every other field of either message, the
stamps among them, is copied unchanged. There is no recalibration: Autoware's controller, its gains, `vehicle_info`,
the converter's maps and every other Autoware parameter or map stay as the release ships them, and no upstream file
is changed or vendored. Every 8.5 record states that a project node sits in Autoware's actuation path and what it
changes (this section and the comparison below).

| topic | type | publisher | subscriber |
|---|---|---|---|
| `/control/command/actuation_cmd` | the actuation command (`tier4_vehicle_msgs/msg/ActuationCommandStamped`, READ by WP9 at the pinned commit) | Autoware's converter | the shim (the interface no longer) |
| `/sdv/steershim/actuation_cmd` | the same | the shim | the interface (remapped at its launch) |
| `/sdv/steershim/steering_status_raw` | `SteeringReport` | the interface (remapped) | the shim |
| `/vehicle/status/steering_status` | `SteeringReport` | the shim | Autoware |

The interface's launch remaps its two topics onto the shim's (WP9's launch; the upstream launch file stays as it is).
The shim uses these four topics and no other of its own (rclpy's Node adds `/rosout` and `/parameter_events` whatever
a node asks). It never touches `/control/command/control_cmd` (the gate's output: the claim node and the converter
both take it, upstream of the shim), `/localization/kinematic_state` or `/qnx_monitor/verdict`: the claim path is
upstream of the shim and unchanged, and kind 4's recording (`follow010.py`'s take, encoded by `encode010.py`) applies
the law to the steer CARLA applied, as it would without the shim.

## The two directions

C is the law's angle at full steer, read by path from `sdv/sim/carla010_iso.py`, the one place it is written (PROBED
there, W9 E9; fitted locally, the readings are not published); the shim neither imports that module nor holds the number.

- **Inverse** (Autoware to the taxi): the actuation command's steer field carries Autoware's commanded tire angle
  delta [rad, positive left]. `s* = sign(delta) x min(1, sqrt(|delta_deg| / C))` is the size of steer whose angle by
  the law is delta, clipped at full steer. CARLA's steer is positive right (W9 E18), so the steer that turns the taxi by
  delta is `-s*`; the shim sends the field value that the interface's own command conversion turns into that steer.
- **Forward** (the taxi to Autoware): the interface's raw report gives back the steer `s` it applied (by its own
  synthesis, with the flattened curve). The shim reports the law's angle `C x s x |s|` in radians with the message's
  sign (positive left), so `-(C x s x |s|)` degrees, as `carla010_iso.delta_iso_deg` has it.

So forward after the interface after the inverse gives Autoware's command back within rounding, up to full lock.

## The interface's constants: READ at the pinned commit

The interface's two steering conversions are constants in `steershim.py`, each a gain with its sign (the interface maps
and reports the steer linearly, W9 section 8), and so are the actuation message's type and its steer field. Each is
"READ (WP9, 94b8fbd3)", read at the pinned commit (D2): the steer as `-delta / max_steer_angle`, the report as
`-s x max_steer_angle`, with the wheels' `max_steer_angle` as W9 section 5 reads it (`CMD_STEER_PER_FIELD` and
`REPORT_RAD_PER_STEER`, the only lines that write that angle), given `max_wheel_steer_angle_deg` absent from the
interface's launch (its 0.0 leaves the physics' angle) and the flat steering curve. `STAND_INS` names any that is not
READ, none now, and the node refuses to start while it names any (exit 2, before rclpy is imported). The steering
report's type and field are READ (W4 M5: `autoware_vehicle_msgs/msg/SteeringReport`, float32 `steering_tire_angle`,
positive left). A conversion that is zero or not finite is refused too, and so is a steer field path that its imported
message type lacks or holds as no float (exit 2, before `rclpy.init`). A conversion that is not a fixed gain (the
flattening failed: a factor that moves with speed) is a failed publisher check of the run, never a shim change: these
constants cannot express it.

## Each message, and the refusals

- The callback copies the message with its steer replaced and publishes the copy; it keeps nothing between messages.
- A steer that is not a finite number, and a raw report beyond what a full steer gives (more than binary32's rounding
  of the float32 field), are refused: an error line in the node's log, nothing published for that message.
- A report is published only while the graph shows exactly one publisher on `/vehicle/status/steering_status`, the
  shim itself. The graph is asked only when a raw report arrives, so what the guard can see is a second publisher there
  while the interface's raw reports come in: another simulator, a second interface whose report is not remapped, or a
  second shim of the same name (a retried start that left the first alive). The report is then logged as an error with
  the count and not published; a count of none (discovery not yet showing the shim's own publisher) only delays the
  first reports. An interface whose report is not remapped sends no raw report at all, so the shim never hears of it:
  WP9's publisher checks catch that, not the shim.
- QoS: both subscriptions BEST_EFFORT, KEEP_LAST 1, VOLATILE (a best-effort subscriber matches a publisher of either
  reliability); both publishers RELIABLE, KEEP_LAST 1, VOLATILE (as W4 G7 read Autoware's vehicle status topics).

## How it runs (WP9)

`python3 <root>/sdv/steershim/shim_node.py`, with no options (the file is not executable, as the claim node's is not),
in a Jazzy container of its own from the interface's image, not inside the interface's process container, on an x86-64
host (the only CARLA 0.10.0 Linux client wheel is x86-64), with the tree's `sdv` mounted read-only under `<root>` so
that `shim_node.py` finds `steershim.py` beside it and `carla010_iso.py` at `../sim/`. The container runs under
`sdv/aw`'s rules (2.12): the project entrypoint `aw-entrypoint.sh` in place of the image's own, `--user aw`,
`--cap-drop ALL`, `--security-opt no-new-privileges`, never privileged or given a capability, and `ros-env.json`'s ROS
environment with `ROS_LOG_DIR` under the run root. No remap and no parameter reaches it from a command line: it takes no
options, `rclpy.init` is given the program's name alone, and the node ignores the context's global ROS arguments and
starts no parameter services. Exit 0 when rclpy's signal handling ends it; 2 for a refusal at start (a stand-in, a
conversion zero or not finite, C unreadable, rclpy or a message package missing, a steer field path its message type
lacks or holds as no float); any other failure ends in Python's traceback and exit 1.

The interface applies the command through a first-order lag (`tau` 0.2 s) after the gain, so the inverse holds at steady
state and Autoware's commanded angle reaches the taxi through a lag that is not first-order in the angle; the same
filter sits in the path without the shim; the shim does not model it and `steershim.py` does not change.

## What the shim changes (10.4: without the shim, not taken; with the shim, D22 as decided)

- **Code**: without the shim, 10.1 and 10.2; with the shim, 10.1, 10.2 and 10.3.
- **The interface's launch**: without the shim, the flattened curve and no remap; with the shim, the flattened curve
  and the interface's two topics remapped to the shim.
- **What Autoware's steering report says**: without the shim, `s x max_steer_angle` (the taxi's, W9 section 5; W9 E10:
  not the wheel's angle); with the shim, `C x s x |s|`, the wheel's angle by the law.
- **The angle the taxi turns at Autoware's command delta**: without the shim, `C x (delta / max_steer_angle)^2` with its
  sign (by W9 E9 and the interface's linear map, INFERRED); with the shim, about delta (the inverse law; INFERRED until
  5a).
- **Kind 2's rule 17 on honest curves**: without the shim it may REJECT (to turn as a bicycle of a small angle the taxi
  needs a steer the interface reports as several times that angle, W9 E9, E10); with the shim it judges about the real
  angle.
- **Kind 4**: 2.9's law on the applied steer, with or without the shim.
- **D22's letter, no recalibration first**: kept either way; with the shim Autoware's controller is not recalibrated,
  but a project node sits in its actuation path, which the record states.

If 5a fails with the shim, that is a finding; removing the shim, or a recalibration, is the owner's call (D22).

## What this does not demonstrate

- That the node runs with the real rclpy and message packages in the shim's own container from the interface's image:
  the tests use stand-ins for rclpy, the message packages and the graph.
- That the real taxi's wheels and curve are what the interface's conversions are given: WP9 read the two conversions,
  the actuation message's type and its steer field at the pinned commit (94b8fbd3) and ran them on stand-in physics, not
  on a server; the run's publisher checks read the flattening. The converter's steer field carries the commanded tire
  angle in radians as READ at its tag 0.52.0 (`convert_steer_cmd` false), with no node started.
- That the taxi turns by Autoware's command: the law is INFERRED from WP9a's drives (W9 E9), its coefficient fitted
  locally (the readings are not published), and 5a's runs show whether Autoware drives the taxi to its goals; nor that
  the shim makes it drive better (only 5a's count says anything).
- That the graph check sees every second publisher on `/vehicle/status/steering_status`: it is asked only when a raw
  report arrives and sees those discovery has shown it; an interface whose report is not remapped sends no raw report,
  so WP9's publisher checks, not the shim, confirm both remaps.
- That the shim's QoS matches its peers' on a running graph. READ at the pin, in the source only: the converter's
  actuation publisher (at its tag 0.52.0), the interface's report publisher and its actuation subscription are each
  depth 1, so RELIABLE, VOLATILE, KEEP_LAST 1. The shim's BEST_EFFORT, VOLATILE subscriptions match a publisher of either
  reliability. Its RELIABLE, VOLATILE publishers match every subscriber except a TRANSIENT_LOCAL one.
- Any timing.
