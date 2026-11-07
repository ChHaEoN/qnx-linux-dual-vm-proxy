# sdv/carla: the CARLA feeder (Phase 7)

CARLA 0.9.16 on the PC becomes the slice's second signal source beside
`sdv/sim/sigsim.py` and its only camera source. This directory holds the feeder's two halves: a capture
client that runs on Windows against the CARLA server and writes a *take*, and an encoder that runs in
WSL and turns a take into the stack's kind of recording directory. The live feed onto vcan0 in WSL
is described in `sdv/feeder/README.md`.

## What is here

| file | what it is |
|---|---|
| `carla_capture.py` | The Windows client (the specification's `capture.py`): the refusals, the world tie, the pacing, the drive, the camera frames, the cleanup; it writes the take and the frame set. Standard library and this directory only; `carla` is imported inside `main`. Named so because CI type-checks this directory beside `scripts/aws`, which has a `capture.py` of its own. |
| `encode.py` | The WSL encoder: a take through `sdv/sim/carla_iso.py` and cantools into `carla.log` by the send schedule, verified, with its summary and manifest line. |
| `sendpolicy.py` | The pure functions both use (and the later live sender will): when a step becomes current, the frame schedule, the RTF, gaps and skipped frames, all from the generated constants. |
| `worldtie.py` | The world settings a take runs under, pure: what the capture applies and reads back, and what the encoder checks the take's record against (the step and the physics substep). |
| `drive.py` | The drive: the route, its controller, the segments, their gears and the commands, as a state machine over steps. |
| `fwcheck.py` | The firewall predicate that gates every CARLA server start: the parsing and the predicate are pure, only `main` runs PowerShell, read only. |
| `frameset.py` | The frame reduction, the PNG writer and the frame-set reader (standard library, `zlib` and `struct`). |

## How

On Windows, in `E:\CARLA\venv312` as it is, from the repo root (or the worktree that holds the
generated contract, `sdv-out/gen`):

    E:\CARLA\venv312\Scripts\python.exe sdv\carla\carla_capture.py fwcheck --for windows-client
    E:\CARLA\venv312\Scripts\python.exe sdv\carla\carla_capture.py take --name <yyyymmdd>-carla-<seed>[suffix] --seed <seed> [--frames on|off]

Every CARLA server start is preceded by `carla_capture.py fwcheck --for windows-client` and does not
happen unless it passes. `carla_capture.py take` runs it again itself before it connects, P4 included
(`--no-tm` waives P4 for a client that starts no Traffic Manager and says so in its line; the take does
not use it).

In WSL Ubuntu-24.04, with the sim venv (`sdv/sim/README.md` says how to make it), from the repo root:

    ~/sdv-sim-venv/bin/python sdv/carla/encode.py record --take /mnt/e/CARLA/takes/<name> --name <name> [--root DIR]
    ~/sdv-sim-venv/bin/python sdv/carla/encode.py verify ~/sdv-recordings/<name>

## The files

**The take**, `E:\CARLA\takes\<name>\`, a new directory, files in this order: `steps.jsonl` (one compact
object per simulation step: the step and frame numbers, the snapshot's elapsed time, the moments the
step's readings were complete and the step became current, its segment and gear, and the ego's raw
readings in CARLA's axes and units: velocity, acceleration, forward vector, angular velocity, the
control and both front wheels' steer angles); `script.jsonl` (every scripted command and the step it
was applied before); `capture.json` (versions, map, the world settings as read back and what
`apply_settings` wrote to stderr (`apply_settings_stderr`), `tm` (null: no Traffic Manager runs), the
ego's wheels and wheelbase, the camera, the drive's values and route, any collision, the clock, the
simulated time `sim_s` and the RTF (both below), the gaps and skipped frames, the segments, the fwcheck
line, the outcome, the cleanup, the errors, and whatever is still PENDING-PROBE), written at the end
also after a failure; `take.sha256`, written last.

**The frame set** (`--frames on`), `E:\CARLA\frames\<name>\`: `frame-%06d.png` for every stride's step
(64 pixels a side, 8-bit grey, the centre square of the camera image reduced in memory: BT.601 grey,
each pixel the mean of a block of four by four) and `frames.json`, written last, which labels the set as simulated and carries CARLA's
asset licence, the take's hash and every frame's sha256. The camera's raw buffer is never written,
copied to a file or kept past the callback that reduces it. A set is never kept inside a work tree,
never committed and never uploaded. The set's reader (`frameset.read_set`) also refuses a listed file
whose name is not `frame-%06d.png` of the step index it is listed for, so a later reader that names a
step by that index cannot name the wrong one.

**The recording**, `~/sdv-recordings/<name>/`: `carla.log` (the `candump -l` text of sigsim's form,
channel vcan0, timestamps the send schedule from zero), `carla.log.sha256`, `steps.jsonl` (the take's,
byte for byte), `summary.json` (sigsim's top-level keys; its trip as the stack and the injector read
it, with the RTF, the take's hash, the encoder's module hashes and whatever is still PENDING-PROBE) and
`manifest-line.json`, written last and only when verify passed: generator `carla`, profile 3, exactly
five params, the RTF and the CARLA ego as the declared vehicle with profile 3's L.

## The world tie and the send policy

The capture applies `worldtie.py`'s tie and refuses unless every setting reads back so: synchronous
mode, `fixed_delta_seconds` = `CARLA_STEP_MS` / 1000, and the physics substep (`substepping` on,
`max_substep_delta_time` `worldtie.SUBSTEP_S`, `max_substeps` the least whole number that covers the
step). The configured tie is `worldtie.py`'s; the read-back settings go into
`capture.json`'s `world_settings`. To retain library diagnostics, the capture records whatever
`apply_settings` wrote to the process's file descriptor 2 in
`apply_settings_stderr` and does not refuse on it (on Windows, a library with a C runtime of its own
could write past that redirection; the record then holds less than the console saw). The encoder holds
a take's recorded `world_settings` to the same tie.

A step becomes current at the later of the moment its readings were complete and
`FEEDER_PACING_INTERVAL_MS` after the previous step became current; the next tick only after that,
and never a catch-up. The log carries the dynamics message at every one of its period's instants and
the gear message at every one of its own, each from the step current at that instant while that step
has been current for no longer than `FEEDER_REPEAT_CAP_MS`, otherwise no frame (`slice.dbc` DESIGN
VALUES (2)). Every one of these numbers comes from the generated contract.

Each step's RTF is the snapshot's elapsed-time advance over the wall time since the previous step
became current, the advance counted in steps of the generated length. To allow single-precision
rounding in a recorded simulation step, an advance within `sendpolicy.STEP_QUANT_TOL` (a
design value, sixteen times single precision's relative rounding error) of a whole number of steps
counts as exactly that many; any other advance reads as it reads, in whole ns. The wall time is never
rounded. The run's {min, mean, max} has min and max over the steps and the mean the sum of the same
advances over the total wall time, so min <= mean <= max holds whenever the steps became current in
increasing order (the encoder refuses any other take). `capture.json`'s `sim_s` is that sum in seconds,
the total simulation time the mean divides, not the snapshots' raw elapsed difference (their raw times
stay in `steps.jsonl`). A take whose steps all became current one interval apart has an RTF of exactly
1; a step made current even a nanosecond sooner reads above 1, and the take is refused.

## The drive

The feeder drives the ego itself, with no Traffic Manager and no autopilot call (which could start
a Traffic Manager). The segments, in order: `start` (a standstill hold), `route drive` (gear 1: the
route controller), `hard brake`, `stopped`, `reverse` and `reverse stop` (gear -1) and `stopped in
reverse`, the final hold. The route starts at the spawn point with the longest straight lane ahead
and takes junctions by a fixed sequence that prefers left turns; the controller follows a smoothed
reference path with a feed-forward wheel angle and a rate-limited steer, and a speed plan with a PI
loop, and it launches against the brake until the gearbox engages. The hard brake enters after a
number of junction turns, on a straight, with the speed in its band and the steer straight for a
while. Every control is applied with `Client.apply_batch_sync` before its tick. A collision sensor
rides on the ego; a
collision, a stuck ego, the route's end or no hard brake within its time stop the take. The seed
names the take; nothing in the drive is random. `drive.DRIVE` and `drive.ROUTE` hold every value,
each with its reason.

## The refusals

`carla_capture.py take`, before it connects: a name that is not `<yyyymmdd>-carla-<seed>[suffix]` for its
seed; on Windows, a host other than 127.0.0.1 and an fwcheck that does not pass; a take or frame-set
directory that exists or lies inside a git work tree; no generated contract. After it connects: client
and server not both 0.9.16; a second `load_world` in one process (Town01 is loaded exactly when the
server is in another map); world settings that do not read back as tied; a control the server did not
apply.

`encode.py record`: a take whose `take.sha256` does not hold, that did not complete, or whose versions,
town or blueprint are not the capture's; recorded world settings that are not the tie; steps that do
not become current in strictly increasing order; a gap, a skipped frame or an RTF max above 1, each
recomputed from `steps.jsonl`, and a `capture.json` whose record of them disagrees (a take recorded
with another computation of the RTF is taken again, never re-read with that one); profile 3 not
compiled in the generation (the guest would answer 8); a take wheelbase other than profile 3's L; a
step whose gear and reverse disagree; a value outside `slice.dbc`'s range (the step named, never
clamped); a root inside the repository (only `sdv-out/`); an existing directory. Each of these, a
missing generation included, prints `encode.py: refused: ...` and exits 2 (exit 1 is a recording that
failed verify). A recording that fails verify is renamed `<name>.failed` and has no manifest line.
Verify's `ok` wants the nine terms of the specification and `carla.log.sha256` holding for `carla.log`
(the stack and the injector read it).

`fwcheck` passes only when every firewall profile blocks inbound by default (P1); every enabled
inbound allow rule for the CARLA exe (by its path, or a program of its file name elsewhere), every
unbound one (no program, service, package or Owner) whose local ports meet 2000-2002 (Any meets
them), and every one for another program that names a port of 2000-2002 by number, is TCP on those
ports and scoped to the WSL adapter (P2); and every enabled inbound allow rule for the client's
interpreters (the base `python.exe` of `E:\CARLA\venv312`'s `pyvenv.cfg` and the venv's own), or an
unbound one whose ports meet 8000, is TCP on 8000 and scoped to the WSL adapter (P4, for the Traffic
Manager's port; `--no-tm` waives it). `--for wsl` also wants one passing P2 rule of the specification's
own (for the exe by its path, or an unbound one) and no block rule for the exe that applies to WSL
(P3). The exe-name arm, the other-program arm and P4's unbound arm widen the specification's sets:
each can only add a FAIL, since P3 counts no rule of those arms. A rule whose filters could not be
read fails. The read takes every filter through the pipeline, rule by rule (a non-elevated shell is
denied the port, address and interface filters in bulk), every cmdlet on the ActiveStore, and writes
ASCII only (every other character escaped), so a rule name in the console code page's own letters
cannot stop it.

## PENDING-PROBE

The conversion's delta source and wheel-angle sign are in `sdv/sim/carla_iso.py`; the drive's
parameters and world tie are in `drive.py` and `worldtie.py`. The pending-probe machinery stays:
a value put back into `carla_iso.PENDING_PROBE` (or `drive.DRIVE_PENDING_PROBE` set) is named in every
take and recording and said on stderr, and the wheel source is refused while its sign is pending.

## Tests

`tests/test_sdv_carla.py`: the send policy's arms, the world tie, the drive and its route, the frame
reduction and set, the firewall predicate over the fixtures in `tests/fixtures/carla/fwcheck-cases.json`,
the capture against the fake simulator `tests/fixtures/carla/fake_carla.py` (a grid of roads; its step
kept as a double, or with `float32_step` in single precision as CARLA 0.9.16's server keeps it; no CARLA
runs in any test), and the encoder against exact stand-ins for cantools and python-can and, where the
sim venv exists, once with them. The conversion's tests are in `tests/test_sdv_sim.py`.

## What this does not demonstrate

It does not demonstrate vehicle dynamics: CARLA's physics, the route controller and the scripted
segments are not a vehicle or a driver, and that the controller holds on another route or map, or at
other speeds, is not shown. Nor CAN timing: the log's timestamps are a send schedule, and vcan has no
arbitration, error frames or bus timing. Nor perception: a simulated frame is not a camera. Nor any
timing: the clock paces the take and the RTF describes the recording; neither is a performance figure.
That every frame passes the reference rules shows the take agrees with the rules' own kinematic model,
not that the rules are right. `fwcheck` reads the rules and sends no packet, and this package's tests
leave its PowerShell read unrun against a real firewall (a stand-in answers it).

## CARLA 0.10.0 (Phase 8 WP9b)

Phase 8's closed loop runs on CARLA 0.10.0 (UE 5.5; decision D17), and Phase 7's 0.9.16 files above stay
as they are: `follow010.py`, `encode010.py` and `gpucheck.py` sit beside them, `fwcheck.py` gained a
`--carla 0.9.16|0.10.0` choice whose default is 0.9.16's behaviour and constants, and the conversion is
`sdv/sim/carla010_iso.py`'s (`sdv/sim/README.md`, its 0.10.0 section). Phase 7's 0.9.16 recordings and
Phase 8's 0.10.0 drives are never compared.

| file | what it is |
|---|---|
| `follow010.py` | The passive take on Windows, in `E:\CARLA\venv312-010` (the carla 0.10.0 win wheel): it follows the ego while Autoware's CARLA interface drives it and ticks the world, and writes a take of Phase 7's directory shape. Standard library and this directory only; `carla` is imported inside `main`. |
| `encode010.py` | The WSL encoder: a 0.10.0 take into a `carla.log` recording of run type `carla-autoware` under profile 5 (`LIVE_DEFAULT_PROFILE["carla-autoware"]`), reusing `encode.py`'s functions read-only. |
| `gpucheck.py` | D21's read before every 0.10.0 server start: free VRAM, no `Carla*` or `ollama*` process, no listener on 2000-2002 or 8000. |
| `town10.py` | Town 10's scenarios, pure and standard library only: WP9a's spawn points by index, the frame rule and the `base_link` offset in one place; it writes `sdv/ctl/scenarios/town10-*.json` and the interface's `spawn_point` string, one pose in two writings. |
| `npc010.py` | The stopped NPC of the drive that must stop behind one, on Windows in `E:\CARLA\venv312-010`: one actor, braked once, held and read each second, destroyed at the end. Standard library and this directory only; `carla` is imported inside `main`. |

Before every 0.10.0 server start, on Windows, both must pass (exit 0):

    E:\CARLA\venv312-010\Scripts\python.exe sdv\carla\fwcheck.py --carla 0.10.0 --for windows-client
    E:\CARLA\venv312-010\Scripts\python.exe sdv\carla\gpucheck.py

Then, while the interface ticks the world, and afterwards in WSL with the sim venv:

    E:\CARLA\venv312-010\Scripts\python.exe sdv\carla\follow010.py take --name <yyyymmdd>-carla010-<n>[suffix] [--max-frames N]
    E:\CARLA\venv312-010\Scripts\python.exe sdv\carla\follow010.py fwcheck --for windows-client|wsl [--no-tm]
    ~/sdv-sim-venv/bin/python sdv/carla/encode010.py record --take /mnt/e/CARLA/takes/<name> --name <name> [--root DIR]
    ~/sdv-sim-venv/bin/python sdv/carla/encode010.py verify ~/sdv-recordings/<name>

**Passive.** `follow010.py` changes nothing in the world: it never calls `apply_settings`, `tick`,
`load_world`, `apply_physics_control`, `apply_control`, `set_target_velocity`, `spawn_actor` or
`get_trafficmanager` (the interface owns the settings, the ticking, the map, the ego and its control,
and no Traffic Manager runs). It reads `get_physics_control()` once, at attach, and follows every frame
through `world.on_tick()` (`wait_for_tick()` reports only the frames that arrive while it is awaited).
The ego is the one actor whose `role_name` is `ego_vehicle`, and it must be `vehicle.taxi.ford`; the
level is recorded (`Carla/Maps/Town10HD_Opt` on a fresh server) and the encoder refuses any other.

**The take** keeps Phase 7's four files. `steps.jsonl` has Phase 7's keys but `wheel_deg`
(the conversion uses commanded steer as its delta source), one line
per frame, `seg` `passive`, the control and the gear from the ego's `get_control()` of that tick; each
step becomes current by the send policy (`sendpolicy.became_current`) as a live sender would send it,
since the follower paces nothing. `script.jsonl` is empty. `capture.json` holds the world settings as
read at attach, after every `REREAD_FRAMES` frames and once more at the end, after the last frame (never
applied), the physics read (each wheel's `max_steer_angle`, the steering curve as read and the vehicle's
own points after the client class's default prefix), the client's listener reads at the start and the
end, how the take ended (the ego gone, `IDLE_TIMEOUT_S` without a frame, or `--max-frames`), and whether
it was refused. A take name is `<yyyymmdd>-carla010-<n>[suffix]`, a pattern Phase 7's never matches.

**The refusals.** Before connecting (exit 2, nothing written): a bad name; on Windows a host other than
127.0.0.1 or `fwcheck.py --carla 0.10.0 --for windows-client` not passing; an existing take directory or
one inside a work tree; no generated contract. After connecting the take is written and marked refused
with its reason (exit 1), and nothing is encoded from it: client and server not both 0.10.0; not exactly
one actor with the role name, or that actor not the taxi; the world not synchronous, or
`fixed_delta_seconds` not `CARLA_STEP_MS` / 1000, at attach, at any re-read or at the end; the vehicle's
own curve points not the interface's flattening (so the shipped curve's speed attenuation never enters); a
frame that is not the previous plus one, or not one step of simulation (its `delta_seconds`, and its
elapsed time since the previous frame's), so a step changed between two reads is refused at its first
frame; a listening socket of the client's at the start or the end (no Traffic Manager), or a read of them
that fails (every listener is read and the client's own kept, and the read stops on an error, so a failed
read is never "none"). The substep is recorded, never refused.

A take whose interface ticks slower than one frame per `FEEDER_REPEAT_CAP_MS` (the generated repeat cap)
has a gap at each such step, as a live sender's schedule would (`sendpolicy.became_current`), and the
encoder refuses it whole: an interface that slow leaves no recording, however honest its drive. The take
keeps `t_vals_ns` and `elapsed_s`, so an encoder that scheduled a passive take by the simulation clock
could still make one from it; this package does not.

**The recording** is Phase 7's kind of directory: `source.generator` `carla-autoware` (a recording's run
type is its generator), profile 5, the taxi with profile 5's L as the declared vehicle (0.10.0 gives no
wheel geometry to read), and five params: `catalog_digest`, `dbc_sha256`, `version`, `map` and
`steer_law`, which names C and the flat curve. `encode010.py record` holds the take's record to the
follower's rules again (the world settings read exactly where the follower reads them, every step one
step of simulation, an end the follower writes, `script.jsonl` empty) and to Phase 7's send-policy rules
(no gap, no skipped frame, an RTF max of at most 1, the record agreeing with its steps); verify's terms
are Phase 7's without `segments_complete` and `app_switches_as_designed`, which a drive Autoware makes
cannot hold. Until WP3c's freeze profile 5 is not compiled: a recording made meanwhile is judged by
profile 5's own row, its trip says `profile_compiled` false, stderr says `PROFILE-NOT-COMPILED` (a guest
would answer 8 to every frame), and it is made again from its take after the freeze.

**`gpucheck.py`** refuses below `FREE_MIB_MIN` (9,500 MiB free: the owner's value of 2026-10-18,
a startup threshold that reserves headroom), on any `Carla*` or `ollama*` process and on any
listener on 2000-2002 or 8000; it prints its verdict, then the record in WP9a's `d21.json` form (the GPU-relevant
processes included, a path under a user profile shown from `%USERPROFILE%` on); exit codes as `fwcheck`'s.
Each read a clause decides on stops on an error, so a failed read is exit 2, never "none"; only the
record's read of the other processes continues past one.

**`town10.py`.** Every scenario names the map folder `Town10HD-aw-n28` and its three hashes. The folder's
`pointcloud_map.pcd` and `map_projector_info.yaml` are the source folder's, byte for byte; its `lanelet2_map.osm` differs
from CARLA's `Town10HD.osm` by 28 `nd` lines of 28 ways, its nodes and relations unchanged, and CARLA's own map is
unchanged. A pose in a scenario is in the map frame (map x = carla x, map y = -carla y, heading = -yaw), `z` 0.0;
`initial_pose` is the spawn's `base_link` pose, 1.265 m behind the actor origin along the heading (`base_link` is where
the interface puts it for a `vehicle_config.wheelbase` of twice that, a parameter whose name says nothing of the taxi's
wheelbase); `goal` is the goal spawn's origin pose, a place and not the ego. The launch's `spawn_point` is one string of
six comma-separated numbers, no brackets, in the order x, y, z, roll, pitch, yaw, in degrees and the CARLA frame. The
files are written, never edited:

    python sdv/carla/town10.py write --dir sdv/ctl/scenarios
    python sdv/carla/town10.py spawn-point t4

**`npc010.py`**, after the interface attaches and before the first route, and at the end:

    E:\CARLA\venv312-010\Scripts\python.exe sdv\carla\npc010.py place --spawn 54 --out <file> [--hold-s S]
    E:\CARLA\venv312-010\Scripts\python.exe sdv\carla\npc010.py destroy

`place` refuses (exit 2, before connecting) a host other than 127.0.0.1, `fwcheck.py --carla 0.10.0 --for windows-client`
not passing, and a `--out` that exists or lies inside a work tree; (exit 1, after connecting, nothing left on the server)
client and server not both 0.10.0, another level, not exactly one `ego_vehicle` or an NPC already there, a spawn index the
level lacks, a failed spawn, a bounding box with no size. It spawns `vehicle.lincoln.mkz` with `role_name` `npc`, so
`follow010.py`'s one-ego rule holds, applies brake 1.0 and hand brake once, then holds: each second one line of its
transform, the ego's transform and the bumper-to-bumper gap, from each actor's bounding box, signed along the NPC's
heading, so an ego that has passed it reads negative. It never calls `tick`, `apply_settings`, `load_world` or
`get_trafficmanager`, and spawns no sensor. `destroy` takes the actors of that role alone; `place` then ends with exit 0.
A hold that outlasts `--hold-s`, a tick that does not come, a failed read or a Ctrl-C ends it too: it destroys its NPC and
exits 1 (130 for the Ctrl-C), the reason on the last line. A Ctrl-C inside the `spawn_actor` call or a destroy can leave the
NPC, so the run's end runs `destroy` whatever `place` said (with none left its exit 1 says so).

**Tests:** `tests/test_sdv_town10.py` (the frame rule on the level's and the map's known points, the regeneration, the
string's fields; no test reads a map) and `tests/test_sdv_npc010.py`, against `tests/fixtures/npc010/fake_npc_carla.py`;
`tests/test_sdv_carla010.py`, against `tests/fixtures/carla010/fake_carla010.py` (a fake
interface ticking a fake 0.10.0 world on a fake clock; no CARLA, GPU or PowerShell runs) and, for the
encoder, the same stand-ins for cantools and python-can as Phase 7's tests and a fixture contract with
profile 5; one test holds the real generation to that contract's names.

**This does not demonstrate** vehicle dynamics, that Autoware drives the taxi (WP9's runs show it or
not), that the steering law holds beyond the drives WP9a read it on, CAN timing, or any timing: the
clock stamps the frames as the follower saw them and the send policy schedules them. Nor that a world
made asynchronous and back between two reads, its step unchanged, is seen; nor what the 0.10.0 server
does to its settings when the interface disconnects (were it to make itself asynchronous, a take ending
after that would be refused at its end read). `gpucheck.py` and the 0.10.0 choice of `fwcheck.py` read;
they change nothing, and this package's tests leave their PowerShell reads unrun (a stand-in answers
them). `town10.py` does not show that Autoware takes a route from these poses, or that the level's spawn table still
reads as WP9a read it (WP9a's list gives x, y, z and yaw; roll and pitch are entered as 0.0). `npc010.py` does not show
that the server spawns the blueprint there or that the hand brake holds it, that the 0.10.0 models' bounding boxes are
the cars' size, how Autoware meets a moving obstacle (the NPC is stopped), or any timing.
