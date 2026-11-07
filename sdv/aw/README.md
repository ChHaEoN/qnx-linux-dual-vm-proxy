# sdv/aw: the ROS environment, the project entrypoint and the host check

Phase 8 WP4b 7.1. Every container a Phase 8 run starts from Autoware's Jazzy
image, or from an image built on it (the ROS->VSS feeder's), runs under the three files here: the claim node, the
scenario driver, the planning simulator, the feeder, and later CARLA's interface and the steering shim. The Phase 8
environment and entrypoint rules are described below. Nothing here starts a container.

| file | what it is |
|---|---|
| `ros-env.json` | The ROS environment of every container of every Phase 8 run: `{"format": 1, "ros_domain_id": 73, "rmw": "rmw_cyclonedds_cpp", "cyclonedds_single_host": "<XML>"}`. |
| `aw-entrypoint.sh` | The project entrypoint, in place of the image's own `/docker-entrypoint.sh`: it sources ROS 2 Jazzy's and Autoware's setup files and replaces itself with its command, and nothing else. |
| `hostcheck.sh` | The host check: prints the four host settings the image's own entrypoint would change, in one fixed form, and with `--compare BEFORE AFTER` names each that changed. |
| `prereg-g1g2.md` | The pre-registration of gates G1 and G2: every threshold, arm and counting rule. |
| `g1_watchdog.py`, `g1_sampler.py` | Gate G1's host side (standard library only, on core 4): the memory-floor stop and its 1 s series, the 5 s sampler. |
| `aw_g1_diag.py`, `aw_g1_count.py` | Gate G1's two recorders in the image: `/diagnostics`, and the guest-stopped arm's arrival times. |

The scenario driver that drives Autoware's AD API in these containers is `sdv/ctl/aw_scenario.py`, with its scenario
files in `sdv/ctl/scenarios/`; it is described below, since its directory's README belongs to the claim side.

## The hazard and the three layers (2.12)

The image's `/docker-entrypoint.sh` turns the host's loopback multicast flag on and raises `net.core.rmem_max`,
`net.ipv4.ipfrag_time` and `net.ipv4.ipfrag_high_thresh` whenever the container is allowed to, under `--network host`,
and warns only when the loopback change fails (W4 S4, S5). On the Orin that would change the board under every later
figure; on a metal host or in WSL it would change the host silently. Three layers, each enough alone where it applies:

1. **The image's entrypoint never runs.** Every container from the image is started with `--entrypoint` set to
   `aw-entrypoint.sh`, mounted read-only; the feeder's image copies the script in as its own `ENTRYPOINT`. The script
   refuses to run as root or when `id -u` prints no number (exit 2), so a container started without `--user aw` stops
   there; it refuses an empty command (exit 2); it sources `/opt/ros/jazzy/setup.bash`, then
   `/opt/autoware/setup.bash` (exit 1 if either cannot be sourced), and `exec`s its arguments, so the command's exit
   status is the container's. It changes no network or kernel setting, no account and no file's owner or mode, and
   writes no file. `--entrypoint` runs it by its path, so the file must keep its execute bit where it is mounted from.
2. **No capability to change the host.** Every such container runs with `--user aw`, `--cap-drop ALL` and
   `--security-opt no-new-privileges`; never `--privileged`, never `--cap-add` of any capability, never a writable
   `/proc/sys` or `/sys`; `--network host` only where the single-host environment below, or the edge's LAN form, needs
   it. Output directories are made writable for `aw` by the runbook or harness, never by mode 777.
3. **The host check.** `hostcheck.sh` is run before a run's first container starts and after its last is removed,
   its output kept in the run's directory (`host-before.txt` and `host-after.txt` in the harnesses), and then
   `hostcheck.sh --compare host-before.txt host-after.txt`: any difference fails the run with the setting named, and
   nothing reverts it silently. A host setting a run does need (the edge's, WP9) is set by the board's helper or the
   harness as its own step, recorded before and after, and reverted: never by an image.

A container started from the image therefore looks like this (the digest from `sdv/stack/images.json` once WP3d
records it; the mounts read-only, every output directory outside every work tree):

    docker run --rm --name aw-sim --network host --user aw --cap-drop ALL --security-opt no-new-privileges \
        --entrypoint /sdv-aw/aw-entrypoint.sh -v <tree>/sdv/aw:/sdv-aw:ro -v <run>/dds:/sdv-dds:ro \
        -e ROS_DOMAIN_ID=73 -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
        -e CYCLONEDDS_URI=file:///sdv-dds/cyclonedds.xml -e ROS_LOG_DIR=<a fixed path under the run root> \
        ghcr.io/autowarefoundation/autoware@sha256:<digest> ros2 launch ...

Who applies it: WP4b 7.2 (every `docker run` of its runbook: `aw-sim`, `aw-claim-node`, `aw-scenario`), WP3d (the
feeder's `ENTRYPOINT`, the stack's `ros` feed and its host check), WP6 (the aw harnesses on a metal host, which end a
stem `status=FAILED at=host-check` on a difference), WP8 (the Orin day, through the helper's `before` and `after`) and
WP9 (CARLA's interface, the steering shim and the edge).

## The ROS environment (`ros-env.json`, 2.7)

- **`ros_domain_id` 73**: WP4a's choice, kept as the project's one value. Not 0, the domain every stray ROS process
  joins, and every DDS port it implies stays below the ephemeral port range.
- **`rmw` `rmw_cyclonedds_cpp`**: the image's own middleware.
- **`cyclonedds_single_host`**: WP4a's `cyclonedds-lo.xml` byte for byte but for its comment (the reasons it gave are
  here): DDS on the loopback interface `lo` (whose address is 127.0.0.1), multicast off, 127.0.0.1 the only unicast
  peer, participant indices assigned automatically up to 160 (the planning simulator's processes need more than the
  default), the image's `MaxMessageSize` 65500B and `WhcHigh` 500kB kept, and the image's receive-buffer minimum of
  10 MB dropped: WSL's `net.core.rmem_max` is below it, and raising it is a host change. So a single-host run needs
  neither loopback multicast nor any kernel setting. The image's own `/home/aw/cyclonedds.xml` is never used.

Every container of a run sets `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION` and `CYCLONEDDS_URI` from this file, and a fixed
`ROS_LOG_DIR` under the run root (ROS logs are never captured or kept). The XML is written, as it is, to a file outside
every work tree and mounted read-only, and `CYCLONEDDS_URI` names that file (`file://...`). The LAN form for the edge
(8.5) is WP9's (D12), not here.

## The host check (`hostcheck.sh`, 2.12)

    hostcheck.sh                          prints, and exits 0:      or exits 2, printing nothing, when one
        format=1                                                    of the four cannot be read
        lo.flags=LOOPBACK,UP,LOWER_UP     (`ip -br link show lo`'s flags)
        net.core.rmem_max=<value>         (`sysctl -n`, as the next two)
        net.ipv4.ipfrag_time=<value>
        net.ipv4.ipfrag_high_thresh=<value>
    hostcheck.sh --compare BEFORE AFTER   exit 0: the same four; exit 1: one line per setting that differs,
                                          `changed <setting> before=<value> after=<value>`; exit 2: a file
                                          unreadable or not in the fixed form (a line missing, repeated,
                                          unknown or malformed)

It runs `ip -br link show lo` and `sysctl -n` for the three names, nothing else, and writes nothing: the run
redirects its output into its directory. It needs no root.

## The scenario driver (`sdv/ctl/aw_scenario.py`, 2.8)

    aw_scenario.py --scenario sdv/ctl/scenarios/<name>.json --map-dir DIR --out DIR [--require-claim-node] [--serve GO_FILE]

It runs in the Autoware image (rclpy and `autoware_adapi_v1_msgs`, imported inside `main` only), with the tree's
`sdv/ctl` mounted read-only two levels below a directory that holds no output (`<root>/sdv/ctl`, as the claim node needs
too), the map read-only, and `--out` outside every work tree. It first checks that the map directory holds exactly the
scenario's files, each with the scenario's sha256. Then each step, bounded by its timeout, waits on its state as WP4a
read the AD API (W4 section 5): `/api/localization/initialize` until the initialization state is INITIALIZED (3) and an
odometry on `/localization/kinematic_state` taken after that request lies within 1 m of the start in x and y (z is not
compared: a CARLA spawn settles from above), both inside `localize`'s timeout; the availability wait below, in a driver
that has asked for a route before; `/api/routing/set_route_points` until the routing state is SET (2); until the
operation mode state says autonomous is available, then
`/api/operation_mode/change_to_autonomous` until the mode is AUTONOMOUS (2); until the routing state is ARRIVED (3);
then `/api/routing/clear_route`. A state counts only when the driver took its message after the step's request, and
every message taken since then is looked at in order (the subscriptions keep the last ten), so a state that lasted less
than one poll is still seen. Before each request the driver spins until each state topic read against that request (the
route's: the routing state and the availability) has delivered a message, for at most 5 s and never past the step's
timeout: DDS delivers a latched state only once discovery has matched, so the latched message is taken before the
request and never concludes the step, nor does one an earlier step left. A topic still silent after 5 s is accepted (it
may hold nothing latched yet); so a latched message that reaches the driver only after the first such wait for its topic
has ended, or comes from a publisher matched only after its topic's first message, can still
conclude a step. What waited on the state topics while the driver read only the
odometry is taken in just before the route's request, so it counts for nothing after it. A reply with `success` false
ends the drive. With `--require-claim-node` it refuses to set the route unless a node named `ctl_claim_node` subscribes to
`/control/command/control_cmd` (within 10 s of asking), since a run starts the claim node before the route (W4 G2: no
Control flows before one), and a run's first frame is then the first Control after `set_route_points`.

It writes `scenario.jsonl` into `--out`, made if absent; its parent must exist, so a missing mount is refused, never
made. A line for the map check (the scenario's name and sha256, each map file's sha256), then one line per step (`step`,
`outcome` done, timeout or refused, the reply's `success`, `code` and `message`, the `state` read, a `detail`, `mono_ns`
and `ros_ns`). Beside it, never in it, `odometry.jsonl` holds the odometry last read at the route's request. Exit 0:
arrived and the route cleared; 3: a step's timeout, the step named; 2: a refusal: an argument, the scenario's form, a
map file or the output directory (each before anything is made), rclpy or a message package that cannot be imported or
an output directory that cannot be made or written (each before anything is written in it), a reply with `success`
false, or no claim node. Any other failure (an exception from rclpy during the drive) ends in Python's traceback and
exit 1, which a harness counts as a failure, as it does every code but 0, 2 and 3.

**The resident driver, `--serve GO_FILE`** (gate G1's, PR's dated section, item 15; off unless given, so the one-shot
form above is what `run-aw-suite.sh` runs). One process and one rclpy participant for the whole arm, joined before the
first route. `--out` is then the directory that holds the drives. Each drive begins by one word in the go file, a plain
name and its newline, taken once; it is that drive's directory under `--out`, with the one-shot form's `scenario.jsonl`
and `odometry.jsonl`, and the answer is `exit` there, the same exit number, one line, written by a rename as the last
thing of the drive. `run()` works from its own marks, so nothing Autoware said in one drive concludes a step of the
next; what a drive leaves the next is only that it asked for a route (the availability wait below). After a non-zero exit,
before the answer, it asks for STOP (`/api/operation_mode/change_to_stop`), reads the mode back, clears the route and
writes each answer to `after-failure.jsonl`, never to `scenario.jsonl`: a set route refuses the next one, so without
this one failed drive would refuse the rest and the memory series would go on with no driving. T7 has still failed, and
a stop or a clear that fails is written and the next drive begins. After exit 0 there is none: the drive's own clear was
its last step. The map is checked once, before the join; each drive's map line carries that check. `--out` and the go
file's directory are refused before the join if the process cannot write them. A drive refused before it ran answers 2 in
its directory; where no directory takes that answer the process ends with exit 2, so docker's code carries the refusal at
once and not a bound's 124.

**The availability wait**, before each route's request and inside `route`'s timeout. A driver that has asked for a route
before waits until the newest `/api/operation_mode/state` it holds says `is_autonomous_mode_available` False; a timeout is
the route step's, its detail names the wait, and no route is asked. Autoware publishes that state only when it changes,
and its availability follows the routing status as Autoware's own timer samples it. With the resident driver, one drive's
clear and the next drive's route can both fall between two samples: Autoware then never sees the route go away, the
availability stays True, no message comes, and the engage, which wants one taken after the route's request, would wait out
its whole timeout. That would be a failure of the harness read as Autoware's, and a FAIL by a reading is never re-run. With
the route's mark taken while the state says False, the only True the engage can take is a new one, which this drive's route
caused. Where the newest state says False already, and in a driver that has never asked for a route (an arm's first drive,
every run of the one-shot form), it goes on at once; a driver started again on a `--out` that already holds drives has asked
for one (PR's dated section, item 16). The wait only holds the route back or ends the step: no state it reads concludes a
step, and the engage's own rule is unchanged. It falls before the route's line, so outside every drive's interval (PR
section 6). Each served drive that reaches it writes one line to `availability.jsonl` in its directory, by a rename,
beside `odometry.jsonl` and never in `scenario.jsonl`: the availability held before the wait (null for none), whether it
waited, and the monotonic stamps of its start and end. The one-shot form writes none. No item reads the note, so a write
of it that the disk will not take is said on the driver's stderr and ends nothing: the drive goes on, or keeps its step's
own end, and a fault of the harness's own disk there does not become the drive's exit and T7's fail.

**The first scenario, `sample-lanelet-102.json`**: the drive W4 G11 names, on the release's `sample-map-planning`.
It chooses initial and goal poses along lanelet 102, at fractions 0.3 and 0.9 of its bounds, with the same yaw
in the map frame (MGRS, grid 54SVE). Its map-file hashes bind it to the `sample-map-planning` archive named by the
1.9.0 release. Its timeouts are design values: `localize` 60 s and `route` 60 s, what WP4a's scripts allowed those two
service calls; `engage` 60 s, for the wait for autonomous to become available, the call (WP4a's script allowed it 30 s)
and the transition, which the transition manager gives up after its `transition_timeout` of 10.0 s (W4 P10); `arrive`
120 s, about six times the drive at the planner's limits (66 m at `max_vel` 4.17 m/s, accelerating and braking at 1.0
m/s^2: about 20 s, W4 P8). The driver's own: 30 s for the clear, 10 s for the claim node's discovery, 5 s for a state
topic's first message before a request. No time or rate of any run is in a scenario file.

## Gate G1's files (Phase 8 WP8)

`orin-native/gpu-concurrency/run-aw-g1.sh` runs one arm of gate G1, and `aw_g1.py judge` beside it reads the record against
`prereg-g1g2.md` (PR), which holds every threshold, arm and counting rule; nothing here restates one as a rule of its own, and a
threshold moves only by a new dated section of PR, written before the run it applies to. `prereg-g1g2.md` is published
byte for byte as registered; its publication line and its pointers to the project's local notes predate the decision that
opened this code.

- **`g1_watchdog.py`**, on core 4 from before the guest boots: one line per second to the series T3 reads (`R MONO WALL KB`), holding
  `/proc/meminfo` open; below its floor (716800 kB, a design value) the stop file the loop reads before each drive, and from then on
  the kill by the label `sdv.aw.run=g1`, repeated so that a container started after the first kill is caught, and after 5 s also
  `cgroup.kill` of each listed scope through `sudo -n tee`, because dockerd may not answer on saturated cores. It refuses a floor at
  or above T3's threshold. `G1_REHEARSAL_FLOOR_KB` is the rehearsal's one override, refused under `VSS_HOST=orin`.
- **`g1_sampler.py`**, on core 4: `meminfo`, `vmstat`, per-core CPU, `docker stats` and each scope's `memory.events` every 5 s.
  Information only: no item reads it, and a gap in it is no instrument's failure.
- **`aw_g1_diag.py`**, the `aw-g1-diag` container: each status's first observation and each change of its level, and every 5 s each
  name's last-seen time and each `control_topic_status`'s key values. PR section 7 reads them. It is load G1 would not otherwise
  have, and the record says it ran.
- **The driver** is the one container of `aw_scenario.py --serve` (above), started at the first drive. Its exit comes from `exit` in the
  drive's directory; a bound that expires while it runs is that drive's 124 and the container is removed, and a container that ended with
  no number is that drive's reading with docker's code; either way the next drive starts another (PR's dated section, item 15).
- **`aw_g1_count.py`**, the `aw-g1-count` container of the guest-stopped arm: arrival times only, with the claim node's QoS. Not the
  same instrument as the claim node, so the two arms' rates are never subtracted.

What these files do not show: that a resident driver reads T6 at drop 0 on any host; that the design values leave Autoware enough
on the Orin, which is what G1 asks; that the status names behave on the arm64 image as they did on the amd64 one; any verdict by
themselves. The startup that boots the guest under KVM is ours, not a QNX-supported configuration, and no timing claim attaches to
the boot.

## What this does not demonstrate

- That the three layers hold on the Orin or a metal host: the tests run the scripts on stand-ins for `id`, `ip`,
  `sysctl` and the setup files, and read the XML; each run's host check is what checks a host.
- That the four settings are the only host settings a container could change: they are the ones the image's own
  entrypoint changes (W4 S4).
- That the XML suits a LAN or more than one host (WP9's D12 form), or that the setup files sit at those paths in
  another image than the one WP4a read.
- That the scenario driver drives a real Autoware (WP4b 7.2's runs), or that its timeouts, and its 5 s bound for a
  latched state's delivery, suit a loaded host; that Autoware's availability follows its routing status on another
  image or host, which the availability wait assumes; anything about the claim, which the claim node and the guest's
  monitor judge.
- Any timing: the driver's times order its steps, nothing more.
