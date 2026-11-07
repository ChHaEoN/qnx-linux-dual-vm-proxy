#!/usr/bin/env python3
"""stack.py -- the SDV slice's local stack on the PC: databroker, providers, recorder, app (sdv/stack).

Runs in WSL Ubuntu-24.04 with the sim venv's Python (cantools and
python-can, sdv/sim/requirements.lock), from the repo root:

    ~/sdv-sim-venv/bin/python sdv/stack/stack.py prepare              # pull by digest, build, check
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py replay --feed dumpfile
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py exit-test            # 3 x dumpfile, 3 x vcan0, S2
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py up --feed dumpfile   # start and leave running
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py up --feed vcan --app external   # every container but the app (APP)
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py down
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py loadcheck            # which catalogues databroker 0.7.1 loads
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py ageprobe             # who stamps a datapoint, on which clock
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py wheelbaseprobe       # Wheelbase served with and without a default
    SDV_BRIDGE_IMAGE=<image ID> ~/sdv-sim-venv/bin/python sdv/stack/stack.py replay --feed vcan --bridge broker
    SDV_CONNECTOR_IMAGE=<image ID> SDV_DEVICE_DIR=<directory> ~/sdv-sim-venv/bin/python sdv/stack/stack.py replay --feed vcan --connector
    SDV_BRIDGE_IMAGE=<image ID> ~/sdv-sim-venv/bin/python sdv/stack/stack.py live [--name N] --bridge broker|can --feeder-out DIR [--native]
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py up --feed ros --run-type planning-sim [--bridge broker]     # ROS FEED

Phase 2 step 3 (the bridge in each of its modes, the injected recordings' runs, the scripted injections and pauses,
and the comparison across the modes) is sdv/stack/step3.py's, built on this module (WP10). The local images' arm64
builds (build_local_arm64, SDV Phase 3 WP0) are sdv/arm64/arm64.py's; this module's own runs use the host's images.

IMAGES (--images, every command but down; SDV Phase 3 WP1)  `build` (the default) is the PC's path above: pull the
  upstream images by index digest, build the local ones. `loaded` is an aarch64 host's (the a1.metal instance), whose
  images came before the run: the upstream ones pulled by index digest and the local arm64 images loaded from the
  upload bundle (sdv/stack/bundle.py). Each is only inspected: an upstream image's ID must be its index digest, its
  revision label the pinned commit, repo@index-digest among its RepoDigests, and it must be linux/arm64; each local
  image must be present by its arm64 pin's ID (images.json local.*.arm64) as linux/arm64, and the witness runs in the
  recorder's; the bridge must be its arm64 pin (images.json bridge.arm64), SDV_BRIDGE_IMAGE naming it, with today's label
  checks. A missing image is refused, never pulled or built mid-suite. bundle.py's verify --loaded and verify-upstream
  apply the same rules (one module holds them). The run manifest's docker record names the mode.

THE RECORDING (SDV_RECORDING, a sigsim or a CARLA recording directory; read, never written)
  Everything expected of a replay comes from that directory, never from re-running the trip script
  or the encoder: its manifest line gives the recording's sha256, the seed, the DBC's sha256 and the
  run type (RECORDING KINDS below); its log must hash to the line's and to <log>.sha256's value, which
  names no file but the log; summary.json's trip.segments give the hard brake the windows are
  derived from, and its name, seed and message counts must be the line's and the decoded log's. A
  --seed that disagrees with the line is refused. Whether the current sdv/sim/sigsim.py is the one
  that made a sigsim recording (the line's sigsim_sha256), or the current sdv/carla modules and
  sdv/sim/carla_iso.py the ones that encoded a CARLA recording (its trip's encoder_sha256), is
  recorded, not required. The DBC is staged only from ~/sdv-cache/dbc/<sha256>.dbc, checked against
  the line's sha256 and the git blob id in dbc-sources.json; when it is missing the run is refused
  with the Windows command that exports it from the commit dbc-sources.json names.

RECORDING KINDS AND RUN TYPES (SDV Phase 7 WP3b; spec-2 2.1, 2.2)  A recording's run type is its line's source.generator:
  sigsim, whose log is sigsim.log, or carla, whose log is carla.log (LOG_NAMES, bundle.py's copy of sdv/inject/inject.py's
  table, held equal by a test). The log is the basename of the line's recording.path; any other pair, another name or
  another generator is refused naming both. That is the one rule of the stack, step3.py, bundle.py and setup's
  vss_setup.py alike: the form of the path is not read (sdv/inject/inject.py, which writes a rewrite's line, checks it
  is a scenario entry path), so a sigsim recording sigsim.py wrote under a relative --out runs as it did before Phase 7.
  The log is staged under its own name in in/, and the dumpfile feed, replay
  mode's --log, the player and every record name it so. The run uses the generation's pair for its run type: a sigsim run
  exactly today's (manifest.json's vehicle_layer and vss-databroker.json, whatever else the generation holds), a carla run
  vehicle_layers.carla and databroker_catalogues.carla, each file checked against the manifest's outputs. The run type's
  catalogue is staged as in/vss-databroker.json (the containers' argument vectors unchanged), and its vehicle layer is the
  one the scenario table's Wheelbase row and the run manifest's catalogue name. A generation without vehicle_layers (one
  made before Phase 7's freeze) runs sigsim only: a CARLA recording is refused there before anything is written. The run
  header's run_type is the generator, its feed recording, its profile the line's, its source_rtf the line's source.rtf for
  carla and null for sigsim; the scenario entry's source is the line's, rtf included, so C12a holds (attribution.py's CARLA
  checks are unchanged). The CAN provider's rows name the run type's upstream (attribution-table section 4): sigsim's
  `sigsim seed N` as attribution.py writes it, a CARLA run's `carla-feeder (<version>, <town>, seed N, <vehicle>)` from
  its line (with_provider_upstream). loadcheck, and so exit-test's last step, loads a CARLA run's staged catalogue too,
  beside the generation's sigsim one. A sigsim run's in/, argument vectors and records are what they were before Phase 7.

LIVE (SDV Phase 7 WP3c; spec-2 2.4)  `live` plays no recording: the stack's up path on the vcan feed (every container, the
  app included), the CAN provider on vcan0, the bridge in broker or can mode and the native `7160 svc 500` monitor, while
  sdv/feeder/live.py drives CARLA from WSL and sends each step onto vcan0 (its own README). The run is the PC's only (any other
  SDV_HOST_ROLE is refused) and --feeder-out, the take's directory, must not exist yet and must lie outside the repo (the
  feeder makes it, never the stack); the stack prints when to start the feeder. Its context (LiveContext) stages the
  generation's carla pair as a carla recording's (the carla catalogue as in/vss-databroker.json, its vehicle layer in the
  records) and the generation's own slice.dbc input (resolve_dbc from the cache), and no log. The run header: run_type
  carla, feed live, profile_source live-default with the carla live default (3), the source vehicle the take's blueprint at
  that profile's L, no recording, source_rtf null at the start (C12a). The stack waits for the take's capture.json to read
  completed (then at most LIVE_SETTLE_S more for its cleanup's end), or for the take to end without completing
  (take.sha256), or LIVE_TAKE_WAIT_S; at record close source_rtf is filled from that capture.json's rtf and C12b reads it
  (live_close). The run's live-1/ holds the bridge's per-frame verdicts (bridge/replies.jsonl), every frame the stack saw on
  vcan0 with its SocketCAN receive time (LIVE_CAPTURE), the monitor's console and result.json (live_gates: C12a, C8, the three
  listener snapshots, the take completed within the wait, cleaned up and in the declared vehicle, C12b, the bridge's own
  result, whose replies split at the take's end as the wait saw it); sdv/feeder/f2check.py judges F2 from them and requires
  those gates. The listener gate is unchanged: the feeder opens no listener, so nothing is allowed for it.

WHAT RUNS (every container: --cap-drop ALL, no-new-privileges, a memory cap equal to its swap cap,
a bounded json log; never --privileged; no docker.sock; upstream images by repo@index-digest, local
images by image ID)
  kuksa-databroker 0.7.1  --vss <the generated vss-databroker.json> --address 127.0.0.1 --insecure,
                          and KUKSA_DATABROKER_ADDR=127.0.0.1 over the image's 0.0.0.0 default.
  kuksa-mock-provider     serves Vehicle.Body.Lights.Hazard.IsSignaling only (sdv/stack/mock/mock.py
                          mounted over the image's sample behaviour file).
  recorder                kuksa-csv-provider 0.4.6's recorder.py (images.json: sources) in a local
                          image: every allowlisted and slot path into a CSV, the design's VSS-layer
                          recording (a kuksa.val.v1 subscriber, which the databroker lets drop an
                          update when it lags: the behaviour key and the window gate never read its
                          hazard rows, only the app's log and the mock provider's own).
  vss-witness             sdv/stack/witness.py in the recorder image (the same base, and the same
                          pinned versions and hashes, as the app's): a kuksa.val.v2 subscription with
                          the databroker's largest buffer on the six CAN-fed paths, so every value of
                          every replay is compared exactly.
  hard-brake-hazard       the app (sdv/apps/hard-brake-hazard), started by its store ID with APP_IMAGE_ID its config
                          digest (IMAGE IDS); with up --app external not started here at all (APP).
  vss-claim-bridge        only with --bridge broker (Phase 2 WP8): the claim bridge image (sdv/bridge, by the
                          image ID SDV_BRIDGE_IMAGE names, its labels checked against the generated contract),
                          in broker mode with the run header as its configuration, the run's scenario lock file
                          bind-mounted, writing back to Monitor.VssClaim; started after the app, before the feed.
                          Never while the twin-control marker exists (TWIN CONTROL).
                          step3.py (WP10) starts it here in its can and replay modes too (start_bridge), always in
                          the host's namespace, with a run's script mounted when its replay directory holds one.
  vss monitor (native)    only with --bridge broker (and step3.py's runs): monitor.c built for the host by build-monitor-native.sh with
                          MONITOR_EXT_KINDS=0x10 into the run directory (never the default OUT), run as
                          `<bin> 7160 svc 500`, its stdout the run's console capture. Not a container: it binds
                          INADDR_ANY, as in the guest (monitor.c; never changed), which the listener check allows
                          for that one PID and port only. The bridge reaches it on 127.0.0.1.
  vss monitor (guest)     guest mode instead (Context(monitor="guest"); step3.py --monitor guest, SDV Phase 3 WP2): the
                          QNX guest's vss monitor, which the image's build file starts as `qnx-safety-monitor 7160 svc
                          500` (ifs-vss.build, or ifs-vss-carla.build for plan carla's ifs-vss-carla.bin).
                          Nothing is built or started here and the listener check allows nothing; the bridge reaches
                          the guest at its host (an IPv4 address on br0, never loopback, and off the PC never one of
                          this host's own addresses), and the run's console is the guest's serial console file. The
                          run manifest's component is the image's file name and sha256, the host (and host_local:
                          whether it is this host's own, as the PC's stand-in is), port 7160 and `7160 svc 500`, and
                          started_by, the build file by the image's name (GUEST_IMAGE_BUILDS; any other image names
                          none). A functional mode: judged by the QNX guest over br0, no timing.
  twin-connector          only with --connector (SDV Phase 4 WP3): the twin connector image (sdv/connector, by the image
                          ID SDV_CONNECTOR_IMAGE names, its labels checked against this generation), the one container
                          of the stack with a way out of the host. It reads the databroker on 127.0.0.1 and sends
                          allowlisted paths up its uplink. Started after the app (and the bridge), before the feed, with
                          a read-only root, as the host user (never root), restart policy `no`, and three mounts and no
                          other: the spool (read-write: the spool record and the connector's own start stamp), the status
                          (read-only: the updater's record, sdv/connector/status.py), each the replay's own spool/ and
                          status/ or the host's (HOST SPOOL AND STATUS), and the device directory SDV_DEVICE_DIR
                          (read-only: the key, the certificate, the CA file).
                          The endpoint and the thing's and the rule's names reach it through --env-file from the device
                          directory's connector.env, never on the argv, and the stack writes none of them, nor the
                          device directory's path, into a run directory. vcan feed only (the dumpfile feed's namespace
                          has no way out); never beside the guest monitor mode; never with --images loaded (an aarch64
                          host's connector is Phase 5's). A connector start within 120 s of the previous one this host's
                          stack made is refused before anything starts (the start spacing: the stamp is
                          sdv/connector/startstamp.py's, kept in SDV_STATE, by default ~/.local/state/sdv-local/twin,
                          so it outlives every run directory; the connector's own stamp holds one spool directory, and
                          each replay has a new one). Stopped with SIGTERM before the databroker, so its last flush
                          runs. A reader, not a writer: it has no row in the attribution table.
  kuksa-can-provider 0.5.0  the generated mapping (vss-can-mapping.json) and slice.dbc; last.

FEEDS (both replay one recording, identified by its sha256)
  dumpfile  the provider replays the log in-process (python-can VirtualBus, paced by the log's
            timestamps). The databroker runs with --network none and every other container joins
            its network namespace, so nothing of the stack is reachable from the host at all.
  vcan      the provider reads SocketCAN vcan0, created with sudo -n if missing, onto which
            python-can's player (the sim venv's) plays the recording file at its own pace while a
            capture socket checks that the frames on the bus are the log's. SocketCAN interfaces
            belong to a network namespace, so every container uses the host's; the databroker still
            binds 127.0.0.1 only.
  Each replay starts a fresh stack: the databroker keeps last values, and a value left from one
  replay must not reach the next.
  Broker mode (--bridge broker) needs the vcan feed: the dumpfile feed's --network none leaves the
  databroker's namespace with loopback only, so a bridge there could reach the databroker but never the
  monitor on the host's :7160 (the alternative, the native monitor inside that namespace, is not built).
  The vcan feed puts every container in the host's namespace, where the bridge reaches both.
  The ros feed (ROS FEED below) is no member of FEEDS: it replays nothing, and replay and exit-test refuse it.

ROS FEED (SDV Phase 8 WP3d; spec-2 2.5, 2.6, 2.7, 2.12)  `up --feed ros --run-type planning-sim [--bridge none|broker]`
  plays no recording: Autoware's planning simulator, started outside the stack (WP4b's runbook), is the source, and the
  ROS->VSS feeder (sdv/rosvss, container ros-vss-feeder) the feed. Every container takes the host's namespace. The run
  starts the databroker on the generation's planning-sim catalogue (staged as in/vss-databroker.json), the witness on the
  table's owned paths, with --bridge broker the native vss monitor first (or, with --monitor guest and step3.py's three
  guest options, the guest's) and the claim bridge on profile 4 (the planning-sim live default, profile_source
  live-default), and the feeder last: by images.json's rosvss.amd64 ID, its ID, labels, architecture, entrypoint
  (sdv/aw/aw-entrypoint.sh as the image holds it), user (aw) and tag checked first; `--run-type planning-sim --databroker
  127.0.0.1:55555`; COMMON, --user aw, ros-env.json's domain and middleware, its single-host XML as in/cyclonedds.xml,
  ROS_LOG_DIR in the run's up/ros-log (never captured); never privileged, never --cap-add, no /proc or /sys mount, no
  mount of the host's root or the docker socket, none of the host's pid, ipc, user, uts or cgroup namespaces and no X11
  socket or display (aw_argv_problems refuses each before docker runs, every option in each form docker takes). It is
  started once it logs its start record and still runs FEEDER_SETTLE_S after it (feeder_node.py logs that record before
  its ROS side comes up). Never the CAN provider, the mock provider, the recorder, vcan0 or an app; only the databroker
  is pulled and only the recorder image built (the witness runs in it).
  Refused before anything is written: another run type or none (a carla-autoware drive's standard signals come from the
  CAN path), --run-type, --bridge or the monitor options on another feed's up, replay or exit-test with it, --app,
  --connector, --seed, --images loaded and any host role but pc (the feeder's image is amd64 only), the monitor options
  without --bridge broker, the guest's host, console or image without --monitor guest (Context's words), and a ros run
  still up (ros_runs_left: down first). Then, before any container starts: a generation without the planning-sim pair,
  --bridge broker while profile 4 is not compiled (every frame would get reason 8), a feeder image that is not
  images.json's, a host user whose uid is not the image's aw (the run's ros-log is the host user's directory and aw
  writes it), C12a, and a host check that cannot be read.
  The host check (2.12): sdv/aw/hostcheck.sh is read into <run>/host-before.txt before the first container starts and,
  after the sweep, into host-after.txt, then compared (host-check.json); any difference fails the run with the setting
  named, and nothing reverts it. A start that fails is swept at once (the native monitor stopped, every container of the
  stack removed) and the host check read after it. Otherwise up leaves the stack running and returns; the feeder carries
  sdv.stack.ros-run=<run directory> beside the stack's label. down finds the ros runs to close by that label and, since
  every other start removes the stack's containers first (the feeder and its label with them), by their directories
  under RUNS too (ros_runs_open: feed ros, host-before.txt, no host-check.json); it stops each run's claim bridge and
  then its witness (docker stop -t 10, each only while it runs with that run's own label <run directory's name>/up: the
  bridge's drain and summary.json, then the witness's stop record), then it removes every container of the stack (the
  feeder with the rest), stops the native monitor each run left (its pid in up/monitor.json, signalled only while /proc
  says that pid runs the monitor's binary) and reads its host check after, failing on a difference.
  The run manifest records run_type planning-sim, feed ros, the feeder's image ID, config digest and base digest, the
  catalogue's sha256, ros-env.json's values, the witness's paths and the publishers W4 read beside the feeder's topics;
  the scenario table is attribution.py's planning-sim table (its C2-planning-sim among the checks), and
  up/attribution.json adds C8 once the feeder runs (its image taken from a running feeder only).

BRIDGE MODE (--bridge broker; Phase 2 WP8, a functional mode, not WP10's runs)  The run header carries the
  bridge items: bridge_mode broker, the scenario entry's profile_id (profile_source scenario), the generated
  AGE_MAX, no demo-ODD window, and time_sync.age_clock, the clock broker mode's ages are read on (AGE_CLOCK:
  the databroker stamps every datapoint on receipt on CLOCK_REALTIME, Phase 2 WP8's probe, `ageprobe`). C3
  and C12a are checked at start. At record close C12b reads its two operands -- the native monitor's `vss
  rules:` line and the bridge's connect records -- and the header's header_check says what it found.
  Wheelbase (spec 5.6): prepare predicts what the databroker serves from the staged catalogue's default. A
  value other than the profile's L is refused before anything starts, as the bridge would refuse it; none
  served starts, as the bridge does with its note, which the run manifest records (bridge.wheelbase). The
  replay compares the bridge's own wheelbase record with that prediction (`wheelbaseprobe` checks both
  branches against databroker 0.7.1).

LISTENERS  Before a stack starts, and three times while it runs (once it is up, a few seconds into
  the feed, and when the replay is over just before the stop), every listening socket of the host
  (sudo -n ss -ltnup, with owners) and, for dumpfile, of the databroker's namespace (the same inside
  it) is recorded; a replay fails (replay's exit status, replay_gates(); exit-test's verdict()) if the
  stack added a listener on anything but loopback in any of the three. The
  one allowance is by PID: the native vss monitor's INADDR_ANY listener on its port (the PID the stack
  started); the same port under any other PID, or with no owners known, is not allowed. Guest mode has none:
  the stack starts no listener of its own.

OUTPUT  ~/sdv-runs/<date>-<name>/ (SDV_RUNS overrides the root; never inside the repo): the staged
  inputs (in/), the run manifest (manifest.json: components with image IDs, catalogue, recording
  with its manifest line and summary.json by sha256, the expected windows, the scenario table's
  checks), and per replay the attribution run table, the containers' logs, the recorder's CSV, the
  witness's and the app's logs, the listener record and result.json. With --bridge broker also the
  monitor's build (bin/) and per replay its console (monitor.log; in guest mode no build, and step3.py's
  guest-console.log, the guest's console with NUL and CR removed), the bridge's run directory (bridge/:
  bridge.jsonl, replies.jsonl, summary.json, source.json), the header it ran with and the scenario lock
  file it held. `ageprobe` writes ageprobe/ageclock.json and the throwaway databroker's log, `wheelbaseprobe`
  wheelbaseprobe/wheelbase.json, the stripped catalogue and the two databrokers' logs. The run
  manifest stands in for the design's per-host manifest (~/.local/share/sdv-local/manifest.json), which
  Phase 1 does not write: sdv/stack/README.md says why.

HOST ROLE  SDV_HOST_ROLE names the host a run is on, as the run manifest's and the run header's host_role and in the
  run_id: pc (the default), a1-metal, c7g-metal (AWS c7g.metal, 2026-10-17: what a1-metal is, on another bare-metal
  host) or orin (attribution-table: a role, never a hostname). Any other value is refused before anything is written.

PLACEMENT (SDV Phase 5 WP1, plan 3.7)  SDV_CONTAINER_CPUSET, a CPU list N[,N...] of distinct decimal integers, puts
  --cpuset-cpus <it> right after the common flags of every container the stack starts (start(), and the throwaway ones
  of loadcheck, ageprobe and wheelbaseprobe); unset, no argument vector changes. SDV_AFTER_START, a command line split
  with shlex and never given to a shell, runs after each container start() made, with the container's name appended as
  its last argument, under AFTER_START_TIMEOUT_S. Its exit status and the last lines of its stdout and stderr go into
  the replay's result.json (and a step-3 run's) under after_start, one record per container in start order; a non-zero
  exit, a timeout or a command that cannot be started stops the run as a failed start does, naming the container. On
  orin the cpuset is required, and beside either monitor the hook too (the board's re-pin of QEMU's threads to 0-2,
  which reads them first, so a record says whether a start moved them). Both are allowed on any role (the PC rehearsal).
  A list that is empty or malformed, names a CPU twice or holds core 0, 1, 2 or 4 (on the board QEMU's cores and the
  probe's) is refused on every role, and so is a hook that shlex cannot split or that is empty; each before anything is
  written. The run manifest's placement records the cpuset and the hook's argv as given, or that none was set.
  loadcheck, ageprobe and wheelbaseprobe start containers outside start(), and exit-test ends with loadcheck: on orin
  all four are refused before anything is written.

IMAGE IDS (SDV Phase 6 WP2; Phase 6 spec 2.1)  The image ID a Phase 6 record carries is the config digest; what docker
  calls an image's ID is its store ID (under the containerd image store a built or loaded image's manifest digest). The
  app runs by its store ID with APP_IMAGE_ID its config digest: --images build proves that digest after the build from a
  `docker save` stream of the store ID (the manifest and the config each checked against its digest by
  sdv/arm64/a64scan.py's reader, and a store ID that names an index refused); --images loaded takes the arm64 pin's
  config_digest, which the store ID names by content (bundle.py's verify --loaded checked the pair). The run manifest's
  app component records config_digest beside its store image_id; a start with none is refused before docker is asked.
  Every other container's argument vector is as it was.

APP (up --app; SDV Phase 6 WP2)  `stack`, the default: this run starts the app. `external`: up starts every container
  but the app, the CAN provider included, which comes last, once up() has returned, started as live starts it with the
  run's <run>/up label and waited for until it logs its ready line (live's pattern, START_TIMEOUT_S); one that does not
  start or never logs its ready line takes the stack down (down's teardown), and up fails with the reason;
  up/listeners.json holds up's listener record, and nothing waits for the app; the updater (sdv/ota) starts the app
  outside the stack, with its own flags. The vcan feed only (an app on the host's network reaches the databroker on
  127.0.0.1 only there), refused otherwise before anything starts; not on replay or exit-test, whose gates read the app
  (a context whose app is external is never replayed). The run manifest's `app` says which.

HOST SPOOL AND STATUS (SDV Phase 6 WP2)  SDV_SPOOL_DIR and SDV_STATUS_DIR, both or neither (one alone is refused): host
  directories the connector mounts at its spool and status paths in place of the replay's spool/ and status/. Each must
  be named by an absolute path, exist, be a directory and lie outside the repo; the stack never makes either, and a
  connector start with either gone is refused before the stamp. Read when a context with a connector is made, and by no
  other run: a run without a connector (exit-test, step3.py, a replay or an up without one) does not look, so an
  exported pair whose directories are not made yet refuses nothing there. Taken only by up --app external --connector:
  the host's spool hands the twin's requests to the updater, which starts its own app, so a run that starts the stack's
  app with a connector (replay --connector, up --connector) is refused while either is set, before anything is written.
  A refusal names the variable, never its value. The run manifest's twin.spool_status says which pair a run had and
  holds no path.

TWIN CONTROL (SDV Phase 6 WP2; owner decision D11)  While the twin-control marker exists no bridge starts, so that the
  updater may take scenario requests. SDV_TWIN_CONTROL_MARKER names it (an absolute path; unset,
  /run/sdv-local/twin-control); any entry at that path is the marker (a file, a directory, a link to nothing), and one
  that cannot be looked for counts as one. replay --bridge and prepare --bridge are refused before anything is written,
  so is a Context with a bridge (step3.py makes its own), and the bridge's own start refuses first thing. A run with no
  bridge does not look.

Does not demonstrate: any timing (the replays are paced by wall clock and every window carries a
mapping allowance), CAN arbitration, error frames or bus timing (vcan has none; --dumpfile never
touches a bus), anything about the QNX guest in native mode (the bridge mode's monitor is the native build of the
same source, not the guest), or that the table's one-writer rule held while a run went (the databroker runs
without authorization). For a CARLA recording: anything about CARLA, the drive or vehicle dynamics (the stack replays a
recorded file as it replays sigsim's), or that a guest image lists profile 3 (C12b reads that at record close). In guest
mode: any timing; the guest's boot, io-sock or its image beyond the image's sha256.
With --connector: anything about the far end the connector talks to (the stack starts it and reads its exit status and
its log's first and last lines; what arrived is the far end's to say), or that the start spacing holds across hosts or
state directories. With a cpuset or a hook: that docker kept a container on those CPUs, or that QEMU's pin held (the
hook's output is the hook's own report). With --app external: anything about the app (this run neither starts nor reads
it). With the twin-control marker: that no bridge starts by another way (this stack's and step3.py's starts look, nothing
else does), or that one started before the marker stops. With the ros feed: that the feeder writes anything or runs right
with the real rclpy and kuksa-client (WP4b's runs), that the planning simulator runs at all, any timing, or that a host
setting did not change and change back between the two readings of the host check.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
APP_DIR = REPO / "sdv" / "apps" / "hard-brake-hazard"
SIGSIM = REPO / "sdv" / "sim" / "sigsim.py"
SLICE_DBC = REPO / "sdv" / "vss" / "slice.dbc"
OVERLAY = REPO / "sdv" / "vss" / "overlay.vspec"
MOCK_FILE = HERE / "mock" / "mock.py"
PROBE_FILE = HERE / "catalogue_probe.py"
AGEPROBE_FILE = HERE / "ageclock_probe.py"
WITNESS_FILE = HERE / "witness.py"
IMAGES_FILE = HERE / "images.json"
DBC_SOURCES_FILE = HERE / "dbc-sources.json"
NATIVE_BUILD = REPO / "orin-native" / "gpu-concurrency" / "build-monitor-native.sh"
BRIDGE_DIR = REPO / "sdv" / "bridge"
CONNECTOR_DIR = REPO / "sdv" / "connector"

sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import attribution as attr  # noqa: E402
import bundle as bd  # noqa: E402
import replaycheck as rc  # noqa: E402

GEN = Path(os.environ.get("SDV_GEN", str(REPO / "sdv-out" / "gen"))).expanduser()
RECORDING_DIR = Path(os.environ.get("SDV_RECORDING", "~/sdv-recordings/20260930-sigsim-1")).expanduser()
RUNS = Path(os.environ.get("SDV_RUNS", "~/sdv-runs")).expanduser()
CACHE = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser()
SIM_PY = Path(os.environ.get("SDV_SIM_VENV", "~/sdv-sim-venv")).expanduser() / "bin" / "python"

# Recording kinds (module docstring, RECORDING KINDS AND RUN TYPES; spec-2 2.1): a recording's log by its line's
# source.generator, read from bundle.py (sdv/inject/inject.py's LOG_NAMES, held equal by tests/test_sdv_stack.py).
LOG_NAMES = bd.LOG_NAMES
SIGSIM_CATALOGUE = "vss-databroker.json"      # a sigsim run's catalogue; every run stages its run type's under this name
# The modules that encode a CARLA recording, whose sha256 its trip records (sdv/carla/encode.py's ENCODER_MODULES, held
# equal by tests/test_sdv_stack.py): the CARLA provenance, reported as sigsim's is (carla_provenance).
CARLA_ENCODER_MODULES = ("sdv/carla/encode.py", "sdv/carla/sendpolicy.py", "sdv/carla/drive.py", "sdv/carla/worldtie.py",
                         "sdv/sim/carla_iso.py")
HOST_ROLE_ENV = "SDV_HOST_ROLE"               # the run's host role (module docstring, HOST ROLE)
HOST_ROLES = ("pc", "a1-metal", "c7g-metal", "orin")   # attribution-table: a role, never a hostname
DEFAULT_HOST_ROLE = "pc"
# Placement (module docstring, PLACEMENT; SDV Phase 5 WP1, plan 3.7).
CPUSET_ENV = "SDV_CONTAINER_CPUSET"           # a CPU list N[,N...]: --cpuset-cpus on every container; required on orin
AFTER_START_ENV = "SDV_AFTER_START"           # a command line (shlex, never a shell) run after each container start
CPUSET_FORBIDDEN = (0, 1, 2, 4)               # on the Orin QEMU's cores (0-2) and the probe's (4): no container runs there
AFTER_START_KEY = "after_start"               # a replay's and a step-3 run's result: the hook's records, in start order
PC_ONLY = ("loadcheck", "ageprobe", "wheelbaseprobe", "exit-test")    # the PC's probes (exit-test ends with loadcheck): not on orin
BROKER_HOST, BROKER_PORT = "127.0.0.1", 55555
BROKER = "%s:%d" % (BROKER_HOST, BROKER_PORT)
VCAN = "vcan0"
FEEDS = ("dumpfile", "vcan")
LABEL = "sdv.stack.run"
WITNESS = "vss-witness"      # a reader, not a writer: it has no row in the attribution table
NAMES = {
    attr.DATABROKER: "sdv-stack-databroker",
    attr.MOCK_PROVIDER: "sdv-stack-mock-provider",
    attr.RECORDER: "sdv-stack-recorder",
    WITNESS: "sdv-stack-witness",
    attr.APP: "sdv-stack-app",
    attr.CAN_PROVIDER: "sdv-stack-can-provider",
}
WITNESS_LOG = "vss-witness.jsonl"
WITNESS_CAPACITY = rc.WITNESS_CAPACITY      # witness.py's BUFFER_SIZE + 1: how the databroker names its lags ('capacity 1001')
MOCK_OFFENDING_KEPT = 50      # lines of the mock's log that are not INFO, kept in result.json (offending_total counts them all)
COMMON =["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-opt", "max-size=10m",
          "--memory", "512m", "--memory-swap", "512m"]
HAZARD = "Vehicle.Body.Lights.Hazard.IsSignaling"
MONITOR_DISPLAY = ("Vehicle.DualVm.Monitor.VssClaim.Verdict", "Vehicle.DualVm.Monitor.VssClaim.Reason")

# The bridge mode (Phase 2 WP8, WP10). `replay --bridge` runs the bridge in broker mode only (WP8's functional
# mode); "none" is Phase 1's stack. Phase 2 step 3 (sdv/stack/step3.py, WP10) runs it in each of the bridge's
# three modes, so a Context takes them all.
BRIDGE_MODES = ("none", "broker", "can", "replay")
REPLAY_BRIDGE_MODES = ("none", "broker")
BRIDGE_NOTES = {
    "none": None,
    "broker": "broker mode over the vcan feed with the native vss monitor (WP8; WP10's step-3 runs); a functional mode: no "
              "timing, not the guest",
    "can": "can mode on vcan0 (the bridge's SocketCAN adapter, no databroker; Phase 2 step 3, WP10) with the native vss monitor; "
           "bypasses the VSS API; a functional mode: no timing, not the guest",
    "replay": "replay mode (the bridge reads the recording itself, no databroker; Phase 2 step 3, WP10) with the native vss monitor; "
              "bypasses the VSS API; a functional mode: no timing, not the guest",
}
# Guest mode's wording (SDV Phase 3 WP2): the same bridge modes, judged by the QNX guest's vss monitor over br0.
BRIDGE_NOTES_GUEST = {
    "broker": "broker mode over the vcan feed, judged by the QNX guest's vss monitor over br0 (SDV Phase 3 WP2); a functional mode: "
              "no timing",
    "can": "can mode on vcan0 (the bridge's SocketCAN adapter, no databroker), judged by the QNX guest's vss monitor over br0 (SDV "
           "Phase 3 WP2); bypasses the VSS API; a functional mode: no timing",
    "replay": "replay mode (the bridge reads the recording itself, no databroker), judged by the QNX guest's vss monitor over br0 (SDV "
              "Phase 3 WP2); bypasses the VSS API; a functional mode: no timing",
}
BRIDGE_CONTAINER = "sdv-stack-bridge"
# The twin connector (module docstring, twin-connector; SDV Phase 4 WP3). Not in NAMES: the six of Phase 1 stay six.
CONNECTOR = "twin-connector"                  # manifest-classes: platform class. A reader: no row in the attribution table
CONNECTOR_CONTAINER = "sdv-stack-connector"
CONTAINERS = dict(NAMES, **{attr.BRIDGE: BRIDGE_CONTAINER, CONNECTOR: CONNECTOR_CONTAINER})      # every container a run may start
CONNECTOR_IMAGE_ENV = "SDV_CONNECTOR_IMAGE"   # the connector image's ID (sdv/connector/build_image.py prints it)
DEVICE_DIR_ENV = "SDV_DEVICE_DIR"             # the device directory: the key, the certificate, the CA file, connector.env
CONNECTOR_ENV_FILE = "connector.env"          # in the device directory: the endpoint and the two names, for --env-file
# The connector's three mounts and no other (manifest-classes.md sections 5 to 7): where each lies in the container.
CONNECTOR_MOUNTS = {"spool": "/run/sdv-local/spool/v1", "status": "/run/sdv-local/status/v1", "device": "/run/sdv-local/device"}
CONNECTOR_LABELS = ("sdv.twin.allowlist_version", "sdv.twin.allowlist_digest", "sdv.twin.catalogue_sha256")
CONNECTOR_STOP_S = 30      # its stop's grace (a design value): the last flush is two publishes, each waited for (sdv/connector/limits.py)
CONNECTOR_EXITS = {0: "stopped", 1: "the uplink could not be opened", 2: "it could not be put together (a setting, a file, a part of the build)",
                   3: "an error nobody expected", 4: "its start was refused by its own start stamp"}
STATE_ENV = "SDV_STATE"                       # the host's state directory: what must outlive a run directory
STATE = Path(os.environ.get(STATE_ENV, "~/.local/state/sdv-local")).expanduser()
CONNECTOR_NEEDS_VCAN = ("--connector needs --feed vcan: the dumpfile feed's namespace holds loopback only, so a connector there "
                        "could read the databroker but never reach its far end; the vcan feed puts every container in the host's "
                        "namespace")
CONNECTOR_NOT_WITH_GUEST = ("--connector is refused with the guest monitor mode: nothing the QNX monitor produces goes to the cloud "
                            "(owner decision S11), and until Phase 5 brings its own evidence no connector runs beside a QNX guest")
CONNECTOR_NOT_LOADED = ("--connector is refused with --images loaded: an aarch64 host's connector is Phase 5's (its arm64 image is "
                        "pinned in images.json, connector.arm64, and runs nowhere yet)")
# SDV Phase 6 WP2 (module docstring, APP, HOST SPOOL AND STATUS, TWIN CONTROL; Phase 6 spec 2.2 and 2.7).
APP_MODES = ("stack", "external")             # up --app: this run starts the app (Phase 1's way), or something outside the stack does
APP_NOTES = {
    "stack": "the app is one of this run's containers: this run starts it by its store ID, with APP_IMAGE_ID its config digest",
    "external": "the app is not this run's: up --app external starts every container but the app, the CAN provider included, "
                "and waits for no app; the updater (sdv/ota) or whoever starts the app starts it outside the stack, with its own "
                "flags (Phase 6 spec 2.6)",
}
APP_EXTERNAL_NEEDS_VCAN = ("--app external needs --feed vcan: an app started outside the stack runs in the host's network namespace "
                           "and reaches the databroker on 127.0.0.1, which only the vcan feed puts in that namespace")
APP_EXTERNAL_NOT_REPLAYED = ("a replay judges the app it starts itself: --app external is up's alone, never a replay's or the exit "
                             "test's (Phase 6 spec section 4 item 5)")
SPOOL_DIR_ENV = "SDV_SPOOL_DIR"               # the host's spool directory for the connector, with SDV_STATUS_DIR or not at all
STATUS_DIR_ENV = "SDV_STATUS_DIR"             # the host's status directory (the updater's record), read-only in the connector
HOST_DIRS_NEED_EXTERNAL_APP = ("%s and %s are taken only by up --app external --connector: the host's spool hands the twin's requests "
                               "to the updater, which starts its app outside the stack, and a run that starts the stack's own app "
                               "(replay --connector, up --connector) would put a second app on the same databroker beside the one it "
                               "judges; unset both for this run" % (SPOOL_DIR_ENV, STATUS_DIR_ENV))
TWIN_CONTROL_ENV = "SDV_TWIN_CONTROL_MARKER"  # the twin-control marker's path: while it exists no bridge starts (owner decision D11)
TWIN_CONTROL_MARKER = "/run/sdv-local/twin-control"
TWIN_CONTROL_REFUSAL = ("a run with a bridge is refused while the twin-control marker exists (%s, by default %s): in that mode no "
                        "bridge starts, so the updater may take scenario requests (owner decision D11, Phase 6); remove the marker to "
                        "run a bridge" % (TWIN_CONTROL_ENV, TWIN_CONTROL_MARKER))
_SHA256_ID = re.compile(r"sha256:[0-9a-f]{64}")
SAVE_BLOB_LIMIT = 4 << 20                     # a save stream's blobs kept to read a manifest and its config (sdv/arm64/arm64.py's bound)
A64SCAN_FILE = REPO / "sdv" / "arm64" / "a64scan.py"     # the save stream's manifest and config reader (standard library only)
BRIDGE_IMAGE_ENV = "SDV_BRIDGE_IMAGE"         # the bridge image's ID (sdv/bridge/build_image.py prints it)
BRIDGE_SCRIPT = "bridge-script.json"          # a step-3 run's script of control calls (step3.py), in its replay directory
LOCK_IN_CONTAINER = "/run/lock/sdv-scenario.lock"     # the bridge image's designated lock path (sdv/bridge/Dockerfile)
# The kind 4 svc monitor (wire spec 13: :7160, deadline 500 ms; :7161 is the stamp port, never the stack's).
MONITOR_PORT = 7160
MONITOR_DEADLINE_MS = 500
MONITOR_EXT_KINDS = "0x10"                    # the vss build (build-monitor-native.sh, monitor.c)
MONITOR_BIN = "monitor-vss"                   # in <run>/bin/, never the script's default OUT
# Which vss monitor judges a bridge run (module docstring, vss monitor): the native build on this host, or the QNX
# guest's (SDV Phase 3 WP2), reached over br0 and started by the guest image itself.
MONITOR_MODES = ("native", "guest")
LOCAL_MONITOR_HOST = "127.0.0.1"              # native mode: the bridge reaches the native monitor on the host's loopback
# What starts the guest's monitor as `7160 svc 500`, by the image's file name: the build file that made it (ifs-vss.bin
# Phase 2's, ifs-vss-carla.bin plan carla's, spec-2 2.3; ifs-ctl.bin Phase 8 WP5's, whose :7160 runs the ctl build,
# kind 4 judged by the vss build's code, spec-2 2.1); tests/test_sdv_stack.py holds the table to every build file of
# the tree that starts the vss monitor so. Any other image names none of them (GUEST_IMAGE_OTHER_BUILD).
GUEST_IMAGE_BUILDS = {"ifs-vss.bin": "ipc-test/qnx-safety-monitor/ifs-vss.build",
                      "ifs-vss-carla.bin": "ipc-test/qnx-safety-monitor/ifs-vss-carla.build",
                      "ifs-ctl.bin": "ipc-test/qnx-safety-monitor/ifs-ctl.build"}
GUEST_IMAGE_OTHER_BUILD = "the image's own build file, not one this tree names"
# The clock each bridge mode reads its ages on (attribution-table 3.1, time_sync.age_clock), named as the
# header names it. broker: the adapter expects the databroker's receipt stamp on CLOCK_REALTIME;
# can: the adapter expects python-can's SocketCAN receive time on CLOCK_REALTIME; replay: the bridge's
# own replay clock, CLOCK_MONOTONIC. These are clock-basis assumptions, not a kernel or device proof. The bridge's
# sources name the same clocks (bridge_sources.py, each source's `clock`); a test holds the two equal. With no
# bridge (bridge_mode none) the header's age_clock is null: nothing reads an age. That is this stack's reading;
# attribution-table 3.1 defines age_clock only as the bridge's clock and says nothing about a run without one.
AGE_CLOCK = {"broker": "realtime", "can": "realtime", "replay": "monotonic"}
# Spec 5.6: what the bridge logs when the databroker serves no Wheelbase (bridge_sources.py's WHEELBASE_NOTE, which
# a test holds equal); the run manifest records it when the stack predicts that branch (served_wheelbase()).
WHEELBASE_NOTE = "wheelbase: not served by the databroker, checked against the declared source vehicle only"

# Waits (design values of the harness, not claims): long enough for a cold start on the PC.
START_TIMEOUT_S = 60.0
QUIET_S = 5.0          # the recorder's CAN rows unchanged this long after the feed ended: the replay is over
SETTLE_S = 2.0         # after the app's stop, for its final heartbeat to reach the recorder
VCAN_READY_S = 3.0     # after the provider opened vcan0, before the player starts
AFTER_START_TIMEOUT_S = 30.0    # SDV_AFTER_START's bound per container (the board's re-pin reads and pins a few threads)
AFTER_START_KEPT = 5            # the last lines of the hook's stdout, and of its stderr, kept in each record

# The live run (module docstring, LIVE; SDV Phase 7 WP3c, spec-2 2.4).
LIVE_FEED = "live"                            # the run header's feed
LIVE_RUN_TYPE = "carla"                       # the run header's run_type (attribution.CARLA_RUN_TYPES)
LIVE_BRIDGE_MODES = ("broker", "can")
LIVE_REPLAY = "live-1"                        # the live run's one replay directory (sdv/feeder/f2check.py reads it)
LIVE_CAPTURE = "vcan-capture.json"            # in it: every frame the stack saw on vcan0, with its SocketCAN receive time
LIVE_SCENARIO = "live"
LIVE_SOURCE_VEHICLE = "vehicle.toyota.prius"  # the take's blueprint (sdv/carla/carla_capture.py BLUEPRINT; a test holds them equal)
LIVE_UPSTREAM = "carla-feeder live (sdv/feeder/live.py; 0.9.16, Town01, vehicle.toyota.prius; the seed is the take's)"
LIVE_TAKE_WAIT_S = 1200.0     # the take's own cap (sdv/carla/drive.py DRIVE.max_take_s, 900 s) and five minutes for the feeder's start
                              # and the server's load_world; a test holds it above the cap
LIVE_POLL_S = 0.5             # how often the wait reads the take's directory
LIVE_TORN_READS = 3           # a capture.json the take is rewriting is read again this many times at most
LIVE_SETTLE_S = 3.0           # once the take's capture.json reads completed, how long its cleanup may take to its last file; and after
                              # the wait, for the bridge's last ticks to reach its record and the feeder to write live.json

# The ros feed (module docstring, ROS FEED; SDV Phase 8 WP3d, spec-2 2.5, 2.6, 2.7, 2.12).
ROS_FEED = "ros"                              # no member of FEEDS: replay's and exit-test's feeds stay the two
ROS_RUN_TYPE = attr.PLANNING_SIM              # the ros feed's one run type
RUN_TYPE_CHOICES = ("sigsim", "carla", ROS_RUN_TYPE, "carla-autoware")    # up --run-type: each but planning-sim refused, with why
FEEDER = attr.FEEDER                          # the feeder's component and writer (sdv/rosvss/mapping.py's WRITER)
FEEDER_CONTAINER = "ros-vss-feeder"           # spec-2 2.1; in neither NAMES nor CONTAINERS, which the harnesses' fallback lists hold
ROS_LABEL = "sdv.stack.ros-run"               # on the feeder: the run directory, by which down finds the run's host check
ROSVSS_DIR = REPO / "sdv" / "rosvss"
AW_DIR = REPO / "sdv" / "aw"
HOSTCHECK = AW_DIR / "hostcheck.sh"           # 2.12's host check (WP4b 7.1's; reads, never sets)
ROS_ENV_FILE = AW_DIR / "ros-env.json"        # 2.7's ROS environment (WP4b 7.1's)
HOST_BEFORE, HOST_AFTER, HOST_CHECK_RECORD = "host-before.txt", "host-after.txt", "host-check.json"     # in the run directory
AW_USER = "aw"                                # the image's user; every container from the Autoware image runs as it (2.12)
AW_UID = 1000                                 # aw's uid in the image (WP3d's read of it, `id`): the host user owns up/ros-log
AW_ENTRYPOINT = "/sdv-aw/aw-entrypoint.sh"    # sdv/aw/aw-entrypoint.sh as the feeder's image holds it: its ENTRYPOINT
FEEDER_PYTHON = "/opt/sdv-rosvss/venv/bin/python"      # the image's venv and program (sdv/rosvss/Dockerfile's CMD; a test holds them)
FEEDER_PROGRAM = "/app/sdv/rosvss/feeder_node.py"
FEEDER_READY = r'"event":"start"'             # the feeder's start record: its start checks passed (sdv/rosvss/vsswriter.py's log)
FEEDER_SETTLE_S = 3.0         # how long the feeder must run on after that record, which feeder_node.py logs before rclpy.init, its node and
                              # its subscriptions (a failure there ends it just after the line); a design value
FEEDER_SETTLE_POLL_S = 0.5    # how often its state is read in that window
RUN_BOOL_SHORTS = "ditP"      # docker run's boolean short options, which may lead a cluster of short ones (-du root): aw_argv_problems
HOST_NAMESPACES = ("--pid", "--ipc", "--userns", "--uts", "--cgroupns")     # never `host` in a container from the Autoware image
ROS_IN = "/sdv-in"                            # in/, read-only in the feeder: in/cyclonedds.xml
ROS_LOG_IN = "/sdv-ros-log"                   # the feeder's ROS_LOG_DIR: <run>/up/ros-log, never captured
CYCLONEDDS_FILE = "cyclonedds.xml"            # ros-env.json's cyclonedds_single_host, staged in in/
ROS_LOG_DIR_NAME = "ros-log"
MONITOR_RECORD = "monitor.json"               # up/: the native monitor a ros up left running, which down stops
MONITOR_STOP_S = 10.0                         # down's wait for it after SIGTERM, before SIGKILL (a design value)
# The publishers of the feeder's planning-sim topics, READ (W4 G6, G7: `ros2 topic info -v` of the planning simulator) and,
# for the verdict, the claim node's (sdv/ctl/ctl_claim_node.py): what the feeder's QoS must match (spec-2 5 item 3), in
# its subscriptions' order. A test holds them to sdv/rosvss/feeder_node.py's, which this package does not change.
_SIM_PUB = {"publisher": "simple_planning_simulator", "reliability": "RELIABLE", "history": "KEEP_LAST", "depth": 1,
            "durability": "VOLATILE"}
ROS_FEED_PUBLISHERS: Dict[str, Dict[str, Any]] = {
    "/vehicle/status/velocity_status": dict(_SIM_PUB, type="autoware_vehicle_msgs/msg/VelocityReport"),
    "/vehicle/status/steering_status": dict(_SIM_PUB, type="autoware_vehicle_msgs/msg/SteeringReport"),
    "/vehicle/status/gear_status": dict(_SIM_PUB, type="autoware_vehicle_msgs/msg/GearReport"),
    "/localization/acceleration": dict(_SIM_PUB, type="geometry_msgs/msg/AccelWithCovarianceStamped"),
    "/qnx_monitor/verdict": {"type": "std_msgs/msg/String", "publisher": "ctl_claim_node", "reliability": "RELIABLE",
                             "history": "KEEP_LAST", "depth": 10, "durability": "VOLATILE"},
}
ROS_NEEDS_PLANNING_SIM = ("--feed ros needs --run-type planning-sim: a carla-autoware drive's standard signals come from the CAN "
                          "path, and the feeder writes only the overlay there (spec-2 2.5); sigsim and carla replay recordings")
RUN_TYPE_NEEDS_ROS = ("--run-type is the ros feed's (up --feed ros --run-type planning-sim): every other feed's run type is its "
                      "recording's")
ROS_NOT_REPLAYED = ("--feed ros is up's alone: replay and exit-test replay a recording, and the ros feed plays none (spec-2 2.5)")
ROS_NO_APP = "--app with --feed ros: a planning-sim run starts no app (spec-2 2.5)"
ROS_NO_CONNECTOR = "--connector with --feed ros: a planning-sim run starts no twin connector (spec-2 2.5)"
ROS_NO_SEED = "--seed with --feed ros: the ros feed plays no recording, so it has no seed to check"
ROS_NOT_LOADED = ("--images loaded with --feed ros: the feeder's image is amd64 only (spec-2 section 0 item 5), and the ros feed "
                  "runs on the PC")
ROS_PC_ONLY = ("--feed ros on %s=%%s: the feeder's image is amd64 only (spec-2 section 0 item 5), and the ros feed runs on the PC"
               % HOST_ROLE_ENV)
MONITOR_NEEDS_BROKER = ("--monitor and the guest options with --feed ros need --bridge broker: without a bridge no claim is "
                        "judged")
UP_BRIDGE_IS_ROS = "--bridge on up is the ros feed's: up --feed dumpfile or vcan starts no bridge (replay --bridge does)"
UP_MONITOR_IS_ROS = "--monitor and the guest options on up are the ros feed's (with --bridge broker)"
ROS_BRIDGE_NOTES = {
    "none": "no bridge: the ros feed without kind 4 (the VssClaim leaves unowned)",
    "broker": "broker mode on the ros feed: the claim bridge reads the slots the feeder writes, on profile 4 (the planning-sim live "
              "default); a functional mode: no timing",
}


class StackError(RuntimeError):
    pass


# --- small helpers ------------------------------------------------------------------------------

def run(cmd: Sequence[str], check: bool = True, timeout: Optional[float] = None, input_text: Optional[str] = None) -> subprocess.CompletedProcess:
    p = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, input=input_text)
    if check and p.returncode != 0:
        raise StackError("%s failed (%d): %s" % (" ".join(cmd[:4]), p.returncode, (p.stderr or p.stdout)[-800:]))
    return p


def docker(*args: str, check: bool = True, timeout: Optional[float] = 120) -> subprocess.CompletedProcess:
    return run(["docker"] + list(args), check=check, timeout=timeout)


def docker_stream(*args: str) -> "subprocess.Popen[bytes]":
    """`docker ARGS` with its stdout and its stderr as pipes, for a stream read as it comes (saved_config_digest's `docker
    save`): the stack's one docker call that is not docker()'s, and a seam of its own, which the tests replace as they
    replace docker()."""
    return subprocess.Popen(["docker"] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, obj: Any) -> str:
    text = json.dumps(obj, indent=1, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_images() -> Dict[str, Any]:
    return json.loads(IMAGES_FILE.read_text(encoding="utf-8"))


def upstream_ref(images: Dict[str, Any], name: str) -> str:
    u = images["upstream"][name]
    return "%s@%s" % (u["repo"], u["index_digest"])


def wait_for(pred: Callable[[], bool], timeout: float, what: str, poll: float = 0.2) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(poll)
    raise StackError("timed out after %.0f s waiting for %s" % (timeout, what))


def container_logs(name: str) -> str:
    p = docker("logs", name, check=False, timeout=60)
    return (p.stdout or "") + (p.stderr or "")


def wait_log(name: str, pattern: str, timeout: float) -> None:
    rx = re.compile(pattern)

    def seen() -> bool:
        st = docker("inspect", "-f", "{{.State.Running}}", name, check=False)
        if st.stdout.strip() != "true":
            raise StackError("%s stopped while waiting for /%s/:\n%s" % (name, pattern, container_logs(name)[-1500:]))
        return bool(rx.search(container_logs(name)))

    wait_for(seen, timeout, "%s to log /%s/" % (name, pattern), poll=0.3)


# --- listeners ----------------------------------------------------------------------------------

def parse_ss(text: str) -> List[Dict[str, str]]:
    """`ss -ltnupH` lines -> [{proto, local, process}] (listening TCP and unconnected UDP)."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        out.append({"proto": parts[0], "local": parts[4], "process": " ".join(parts[6:])})
    return out


def local_host(local: str) -> str:
    """The host part of ss's Local Address:Port ('127.0.0.53%lo:53' -> '127.0.0.53', '[::1]:5' -> '::1')."""
    host = local.rsplit(":", 1)[0]
    host = host.split("%", 1)[0]
    return host.strip("[]")


def is_loopback(local: str) -> bool:
    h = local_host(local)
    return h.startswith("127.") or h == "::1" or h.startswith("::ffff:127.")


def parse_proc_net(text: str, v6: bool, listen_state: str = "0A") -> List[str]:
    """Listening sockets of /proc/<pid>/net/tcp[6] as 'addr:port' (TCP state 0A = LISTEN)."""
    out = []
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) < 4 or f[3] != listen_state:
            continue
        addr_hex, port_hex = f[1].split(":")
        port = int(port_hex, 16)
        if not v6:
            b = bytes.fromhex(addr_hex)[::-1]
            addr = ".".join(str(x) for x in b)
        else:
            raw = bytes.fromhex(addr_hex)
            words = [raw[i:i + 4][::-1] for i in range(0, 16, 4)]
            b = b"".join(words)
            groups = ["%x" % int.from_bytes(b[i:i + 2], "big") for i in range(0, 16, 2)]
            addr = "[" + ":".join(groups) + "]"
            if addr == "[0:0:0:0:0:0:0:1]":
                addr = "[::1]"
            elif addr == "[0:0:0:0:0:0:0:0]":
                addr = "[::]"
        out.append("%s:%d" % (addr, port))
    return out


def host_listeners() -> Dict[str, Any]:
    p = run(["sudo", "-n", "ss", "-ltnupH"], check=False)
    owners = p.returncode == 0
    if not owners:
        p = run(["ss", "-ltnupH"])
    return {"with_owners": owners, "sockets": parse_ss(p.stdout)}


def netns_listeners(pid: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"pid_namespace_of": "databroker", "proc_net": []}
    for name, v6, state in (("tcp", False, "0A"), ("tcp6", True, "0A"), ("udp", False, "07"), ("udp6", True, "07")):
        path = Path("/proc/%d/net/%s" % (pid, name))
        if path.exists():
            out["proc_net"] += [name + " " + a for a in parse_proc_net(path.read_text(), v6, state)]
    p = run(["sudo", "-n", "nsenter", "-t", str(pid), "-n", "ss", "-ltnupH"], check=False)
    out["ss_in_namespace"] = parse_ss(p.stdout) if p.returncode == 0 else None
    return out


_PID = re.compile(r"pid=(\d+)")


def owner_pids(process: str) -> List[int]:
    return [int(x) for x in _PID.findall(process)]


def stack_pids(extra: Sequence[int] = ()) -> List[int]:
    """Host PIDs of every process in the stack's containers, and of the stack's host processes (extra: the
    native monitor's)."""
    pids: List[int] = list(extra)
    for name in CONTAINERS.values():
        p = docker("top", name, "-eo", "pid", check=False)
        if p.returncode == 0:
            pids += [int(x) for x in p.stdout.split()[1:] if x.isdigit()]
    return sorted(set(pids))


def local_port(local: str) -> Optional[int]:
    """The port of ss's Local Address:Port, or None ('*')."""
    port = local.rsplit(":", 1)[-1]
    return int(port) if port.isdigit() else None


def listener_verdict(before: Dict[str, Any], during: Dict[str, Any], ns: Optional[Dict[str, Any]],
                     pids: Sequence[int], allowed: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """The stack may add listeners on loopback only. With owners (sudo ss -p), a listener added by a
    process outside the stack's containers is recorded, not held against the stack; without them
    every added listener counts.

    allowed: the stack's own non-loopback listeners, each {pid, proto, port, why}, allowed by PID: a listener
    passes only when ss names that PID among its owners and it is on that protocol and port (the native vss
    monitor binds INADDR_ANY, as in the guest, and its bind is never changed). The same port under another PID,
    a name that looks the same, or a listener with no owners known is not allowed."""
    key = lambda s: (s["proto"], s["local"])  # noqa: E731
    old = {key(s) for s in before["sockets"]}
    added = [s for s in during["sockets"] if key(s) not in old]
    ours = set(pids) | {int(a["pid"]) for a in allowed}

    def is_allowed(s: Dict[str, str]) -> bool:
        if not during["with_owners"]:
            return False                          # no owners: no PID to allow by
        owners = set(owner_pids(s["process"]))
        return any(int(a["pid"]) in owners and s["proto"] == a["proto"] and local_port(s["local"]) == int(a["port"])
                   for a in allowed)

    if during["with_owners"]:
        stack_added = [s for s in added if set(owner_pids(s["process"])) & ours]
        others = [s for s in added if not set(owner_pids(s["process"])) & ours]
    else:
        stack_added, others = added, []
    bad = [s for s in stack_added if not is_loopback(s["local"]) and not is_allowed(s)]
    allowed_seen = [s for s in stack_added if not is_loopback(s["local"]) and is_allowed(s)]
    ns_bad: List[str] = []
    if ns is not None:
        ns_bad = [a for a in ns["proc_net"] if not is_loopback(a.split(" ", 1)[1])]
        if ns.get("ss_in_namespace"):
            ns_bad += [s["local"] for s in ns["ss_in_namespace"] if not is_loopback(s["local"])]
    return {"ok": not bad and not ns_bad, "stack_pids": sorted(ours), "added_by_stack": stack_added, "added_not_loopback": bad,
            "allowed_by_pid": allowed_seen, "allowances": [dict(a) for a in allowed],
            "added_by_other_processes": others, "namespace_not_loopback": ns_bad,
            "preexisting_not_loopback": [s for s in before["sockets"] if not is_loopback(s["local"])]}


# --- preparation --------------------------------------------------------------------------------

def image_id(ref: str) -> str:
    return docker("image", "inspect", "-f", "{{.Id}}", ref).stdout.strip()


# --- the config digest (module docstring, IMAGE IDS; SDV Phase 6 WP2, spec 2.1) ----------------------------------------
# The store's ID of a built image is its manifest digest under the containerd image store; the identity every Phase 6
# record carries is the config digest, which no store changes. It is read from a `docker save` stream of the store ID, the
# manifest and the config each checked against its digest by sdv/arm64/a64scan.py's reader (the one bundle.py's pins and
# sdv/arm64/arm64.py rest on), and a store ID that names an index is refused.

def _a64scan() -> Any:
    """sdv/arm64/a64scan.py (standard library only), loaded by its file under a name of the stack's own, when first needed:
    only build mode reads a save stream, so a host that runs --images loaded never loads it."""
    key = "_sdv_a64scan_for_stack"
    if key in sys.modules:
        return sys.modules[key]
    import importlib.util
    spec = importlib.util.spec_from_file_location(key, str(A64SCAN_FILE))
    if spec is None or spec.loader is None:
        raise StackError("cannot load %s" % A64SCAN_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[key] = mod
    return mod


def config_digest_from_save(stream: Any, store_id: str) -> str:
    """The config digest of the manifest `store_id` names, from a `docker save` tar stream: the manifest blob must hash to
    the store ID and be a single-platform image manifest (an index is refused), the config blob must hash to its digest."""
    blobs: Dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=stream, mode="r|") as tf:
            for m in tf:
                if m.isreg() and m.name.startswith("blobs/sha256/") and m.size <= SAVE_BLOB_LIMIT:
                    f = tf.extractfile(m)
                    if f is not None:
                        blobs["sha256:" + m.name.rsplit("/", 1)[1]] = f.read()
    except tarfile.TarError as exc:
        raise StackError("the image %s: its config digest is not proved: its save stream is no tar (%s)" % (store_id, exc)) from None
    a64 = _a64scan()

    def get(digest: str) -> bytes:
        if digest not in blobs:
            raise a64.ScanError("the save stream has no blob %s" % digest)
        return blobs[digest]
    try:
        man, _cfg = a64.saved_image(get, store_id)
        digest = man["config"]["digest"]
    except (a64.ScanError, ValueError, KeyError, TypeError) as exc:
        raise StackError("the image %s: its config digest is not proved by its save stream: %s" % (store_id, exc)) from None
    return str(digest)


def saved_config_digest(store_id: str) -> str:
    """config_digest_from_save on `docker save <store_id>` (docker_stream), the stream read once and to its end. An error
    nobody expected while it is read (a64scan.py that cannot be read, an interrupt) kills the save before its stderr is
    read: nobody drains its stdout any more, so a save still writing would block that read, and the bounded wait after it,
    for ever. The error then goes on as it was."""
    p = docker_stream("save", store_id)
    assert p.stdout is not None and p.stderr is not None
    error: Optional[StackError] = None
    digest = ""
    try:
        try:
            digest = config_digest_from_save(p.stdout, store_id)
        except StackError as exc:
            error = exc
        for _chunk in iter(lambda: p.stdout.read(1 << 20), b""):    # type: ignore[union-attr]
            pass
    except BaseException:
        p.kill()          # its pipes close with it, so the reads below end
        raise
    finally:
        err = p.stderr.read().decode("utf-8", "replace")
        rc = p.wait(timeout=600)
    if rc != 0:
        raise StackError("docker save %s: exit %d: %s" % (store_id, rc, err.strip()[-500:]))
    if error is not None:
        raise error
    return digest


def app_config_digest(ctx: Any) -> str:
    """The app's config digest, the APP_IMAGE_ID of its start (spec 2.1): build mode's proved from the save stream after the
    build (build_local), loaded mode's the arm64 pin's (loaded_local). A context with none is refused, before docker is asked."""
    comp = (getattr(ctx, "components", None) or {}).get(attr.APP) or {}
    digest = comp.get("config_digest")
    if not isinstance(digest, str) or not _SHA256_ID.fullmatch(digest):
        raise StackError("the app image has no proved config digest (sha256:<64 hex>), which its start passes as APP_IMAGE_ID "
                         "(Phase 6 spec 2.1): prepare proves it after a build and takes the arm64 pin's when the images are loaded")
    return digest


def pull_upstream(images: Dict[str, Any]) -> Dict[str, Any]:
    """Pull each upstream image by index digest (a no-op when present), check its revision label."""
    out = {}
    for name, u in images["upstream"].items():
        ref = upstream_ref(images, name)
        docker("pull", "-q", ref, timeout=900)
        info = json.loads(docker("image", "inspect", ref).stdout)[0]
        labels = (info.get("Config") or {}).get("Labels") or {}
        rev = labels.get("org.opencontainers.image.revision")
        if rev != u["revision"]:
            raise StackError("%s: revision label %r, pinned %r" % (name, rev, u["revision"]))
        if ref not in info.get("RepoDigests", []):
            raise StackError("%s: %s not among the image's repo digests %r" % (name, ref, info.get("RepoDigests")))
        out[name] = {"class": "platform", "form": "container", "image_id": info["Id"], "ref": ref,
                     "version": u["version"], "revision": rev, "arch": info.get("Architecture"),
                     "pull": {"via": "upstream", "ref": ref, "manifest_digest": u["index_digest"]}}
    return out


def fetch_recorder_source(images: Dict[str, Any]) -> Path:
    src = images["sources"]["csv-recorder"]
    ctx = CACHE / "csv-recorder-0.4.6"
    ctx.mkdir(parents=True, exist_ok=True)
    dest = ctx / src["path"]
    if not dest.exists():
        req = urllib.request.Request(src["url"], headers={"User-Agent": "sdv-stack"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        dest.write_bytes(data)
    data = dest.read_bytes()
    if hashlib.sha256(data).hexdigest() != src["sha256"] or git_blob_sha1(data) != src["git_blob"]:
        raise StackError("%s does not match its pins (sha256 %s, blob %s)" % (dest, hashlib.sha256(data).hexdigest(), git_blob_sha1(data)))
    return ctx


def build_local(images: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    base = "%s@%s" % (images["base"]["python"]["repo"], images["base"]["python"]["index_digest"])
    docker("pull", "-q", base, timeout=900)
    for name, spec in images["local"].items():
        if name == attr.RECORDER:
            ctx = fetch_recorder_source(images)
            shutil.copyfile(REPO / spec["lock"], ctx / "requirements.lock")
        else:
            ctx = REPO / spec["context"]
        # No provenance or SBOM attestation: they carry the build's time, which would give every
        # rebuild of unchanged inputs a new image ID; without them a cached rebuild keeps its ID.
        docker("build", "-q", "--provenance=false", "--sbom=false", "-f", str(REPO / spec["dockerfile"]), "-t", spec["tag"], str(ctx),
               timeout=1800)
        iid = image_id(spec["tag"])
        entry = {"class": spec["class"], "form": "container", "image_id": iid, "tag": spec["tag"],
                 "pull": {"via": "local-build", "dockerfile": spec["dockerfile"], "base": base}}
        if name == attr.APP:
            entry["config_digest"] = saved_config_digest(iid)      # its APP_IMAGE_ID (IMAGE IDS), beside its store ID
        if "app_version" in spec:
            entry["app_version"] = spec["app_version"]
        if "source" in spec:
            entry["source"] = images["sources"][spec["source"]]
        out[name] = entry
    return out


# --- the arm64 images (SDV Phase 3 WP0) -----------------------------------------------------------
# build_local above stays the amd64 path, unchanged. The arm64 build stages both contexts outside the repo, each
# with its image's aarch64 lock as requirements.lock, builds them with buildx for linux/arm64 from the same
# Dockerfiles (their FROM index digest resolves to the base's arm64 manifest) and tags them <tag>-arm64, never the
# amd64 tag. sdv/stack/images.json pins the result per local image (arm64: id, config_digest, tag, lock;
# sdv/arm64/arm64.py build --write-pins), and sdv/arm64/arm64.py scans and smokes it.
ARM64_PLATFORM = "linux/arm64"
ARM64_APP_FILES = ("hazard.py", "app.py", "appstate.schema.json")     # the app Dockerfile's COPY into /app/


def arm64_tag(spec: Dict[str, Any]) -> str:
    return spec["tag"] + "-arm64"


def arm64_lock(spec: Dict[str, Any]) -> str:
    """The repo path of a local image's aarch64 lock: requirements.aarch64.lock beside its requirements.lock."""
    x86 = spec.get("lock") or spec["context"] + "/requirements.lock"
    if not x86.endswith("/requirements.lock"):
        raise StackError("no requirements.lock to pair an aarch64 lock with: %r" % x86)
    return x86[:-len("requirements.lock")] + "requirements.aarch64.lock"


def build_local_arm64(images: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    base = "%s@%s" % (images["base"]["python"]["repo"], images["base"]["python"]["index_digest"])
    root = CACHE / "arm64-build"
    if str(root.resolve()).startswith(str(REPO.resolve()) + os.sep):
        raise StackError("the staging root %s is inside the repo" % root)
    root.mkdir(parents=True, exist_ok=True)
    for name, spec in images["local"].items():
        tag, lock = arm64_tag(spec), arm64_lock(spec)
        ctx = Path(tempfile.mkdtemp(prefix=name + "-", dir=str(root)))
        try:
            if name == attr.RECORDER:
                src = images["sources"][spec["source"]]["path"]
                shutil.copyfile(fetch_recorder_source(images) / src, ctx / src)
                files = [src]
            else:
                files = list(ARM64_APP_FILES)
                for f in files:
                    shutil.copyfile(REPO / spec["context"] / f, ctx / f)
            shutil.copyfile(REPO / lock, ctx / "requirements.lock")
            staged = {f: sha256_file(ctx / f) for f in files + ["requirements.lock"]}
            # As build_local: no provenance or SBOM attestation, so a cached rebuild keeps its ID.
            docker("buildx", "build", "-q", "--platform", ARM64_PLATFORM, "--provenance=false", "--sbom=false", "--load",
                   "-f", str(REPO / spec["dockerfile"]), "-t", tag, str(ctx), timeout=3600)
            # A --load that exits 0 but leaves no image under the tag is the error build_image.build raises for the
            # bridge, in the same words, not whatever docker's inspect prints about a missing tag.
            p = docker("image", "inspect", "-f", "{{.Id}}", tag, check=False)
            iid = p.stdout.strip() if p.returncode == 0 else ""
            if not iid:
                raise StackError("the build left no image tagged %s" % tag)
        finally:
            shutil.rmtree(ctx, ignore_errors=True)
        out[name] = {"class": spec["class"], "image_id": iid, "tag": tag, "platform": ARM64_PLATFORM, "lock": lock,
                     "lock_sha256": sha256_file(REPO / lock), "dockerfile": spec["dockerfile"], "base": base, "staged": staged}
    return out


# --- --images loaded: the images an aarch64 instance runs (SDV Phase 3 WP1) ----------------------------
# prepare's `images` is "build" (today's: pull_upstream, build_local) or "loaded": the upstream images were pulled before
# the run (run-vss-setup.sh) and the local ones loaded from the upload bundle (sdv/stack/bundle.py), so each is only
# inspected here, by the rules bundle.py's verify and verify-upstream apply (bd.upstream_problems, bd.loaded_problems),
# and a missing one is refused, never pulled or built mid-suite.
IMAGE_MODES = ("build", "loaded")
LOADED_NOTE = ("--images loaded: the upstream images pulled before the run and the local arm64 images loaded from the bundle, "
               "each inspected here (its ID, linux/arm64, the upstream revision label and repo digest), never pulled or built")


def inspect_image(ref: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """The daemon's record of one image, or (None, why) when it has none."""
    p = docker("image", "inspect", ref, check=False)
    if p.returncode != 0:
        return None, bd.tail(p.stderr or p.stdout) or "exit %d" % p.returncode
    data = json.loads(p.stdout)
    return (data[0], "") if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict) else (None, "no single record")


def loaded_upstream(images: Dict[str, Any]) -> Dict[str, Any]:
    """Each upstream image as pulled before the run, inspected and never pulled: its ID the index digest, its revision
    label the pinned commit, repo@index-digest among its RepoDigests, linux/arm64."""
    out, problems = {}, []
    for name, u in images["upstream"].items():
        ref = upstream_ref(images, name)
        info, why = inspect_image(ref)
        bad = bd.upstream_problems(name, u, info, why)
        if bad or info is None:
            problems += bad
            continue
        out[name] = {"class": "platform", "form": "container", "image_id": info["Id"], "ref": ref, "version": u["version"],
                     "revision": bd.labels_of(info).get(bd.REVISION), "arch": info.get("Architecture"),
                     "pull": {"via": "upstream", "ref": ref, "manifest_digest": u["index_digest"],
                              "pulled": "before the run (--images loaded); inspected here, never pulled"}}
    if problems:
        raise StackError("--images loaded: " + "; ".join(problems))
    return out


def loaded_local(images: Dict[str, Any]) -> Dict[str, Any]:
    """Each local image's arm64 pin (images.json local.*.arm64), present by its ID as linux/arm64; never built."""
    out, problems = {}, []
    for name, spec in images["local"].items():
        pin = spec["arm64"]
        info, why = inspect_image(pin["id"])
        bad = bd.loaded_problems(name, pin, info, why)
        if bad:
            problems += bad
            continue
        entry = {"class": spec["class"], "form": "container", "image_id": pin["id"], "tag": pin["tag"],
                 "config_digest": pin["config_digest"], "arch": bd.ARCH,
                 "pull": {"via": "loaded", "pin": "images.json local.%s.arm64" % name, "lock": pin["lock"]}}
        if "app_version" in spec:
            entry["app_version"] = spec["app_version"]
        if "source" in spec:
            entry["source"] = images["sources"][spec["source"]]
        out[name] = entry
    if problems:
        raise StackError("--images loaded: " + "; ".join(problems))
    return out


def _read_recording_file(rec_dir: Path, name: str) -> bytes:
    try:
        return (rec_dir / name).read_bytes()
    except OSError as exc:
        raise StackError("the recording directory %s has no readable %s: %s" % (rec_dir, name, exc)) from exc


def recording_identity(rec_dir: Path) -> Dict[str, Any]:
    """The recording and its manifest line (module docstring, RECORDING KINDS AND RUN TYPES): its log is the one the
    line names by its generator (bundle.log_name_of: sigsim.log or carla.log; any other pair or name refused naming
    both), whose sha256 must equal the line's and the one <log>.sha256 lists, which names no file but the log. The run
    type is the line's generator."""
    raw_line = _read_recording_file(rec_dir, "manifest-line.json")
    line = json.loads(raw_line.decode("ascii"))
    name, why = bd.log_name_of(line)
    if name is None:
        raise StackError("the recording %s: %s" % (rec_dir, why))
    log = rec_dir / name
    sha = hashlib.sha256(_read_recording_file(rec_dir, name)).hexdigest()
    listed = _read_recording_file(rec_dir, name + ".sha256").decode("ascii").split()
    if sha != line["recording"]["sha256"]:
        raise StackError("%s hashes to %s, its manifest line says %s" % (name, sha, line["recording"]["sha256"]))
    if not listed or listed[0] != sha:
        raise StackError("%s hashes to %s, %s.sha256 says %s" % (name, sha, name, listed[0] if listed else "nothing"))
    if len(listed) > 1 and listed[1:] != [name]:
        raise StackError("%s.sha256 names %s, not %s" % (name, listed[1:], name))
    return {"dir": str(rec_dir), "log": str(log), "log_name": name, "run_type": line["source"]["generator"], "sha256": sha,
            "manifest_line": line, "manifest_line_sha256": hashlib.sha256(raw_line).hexdigest()}


def log_of(ctx: Any) -> str:
    """The name the context's recording is staged under (its log's, module docstring, RECORDING KINDS AND RUN TYPES); a
    context that names none (the tests' stand-ins of Phase 1's) is a sigsim one."""
    return getattr(ctx, "log_name", None) or LOG_NAMES["sigsim"]


def recording_seed(line: Dict[str, Any], cli_seed: Optional[int]) -> int:
    """The seed is the recording's (its manifest line's source.params.seed), never the command
    line's: a --seed that disagrees is refused."""
    seed = line["source"]["params"]["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise StackError("the manifest line's seed is not an integer: %r" % (seed,))
    if cli_seed is not None and cli_seed != seed:
        raise StackError("--seed %d disagrees with the recording's manifest line (seed %d); the seed is the recording's, "
                         "so leave --seed out" % (cli_seed, seed))
    return seed


def recording_summary(rec_dir: Path, line: Dict[str, Any]) -> Dict[str, Any]:
    """summary.json, which sigsim wrote into the recording directory with the recording: its trip
    (trip.segments is what the windows are derived from) must be the manifest line's -- same name,
    same seed -- and have exactly one hard-brake segment. Its message counts are checked against
    the decoded log by check_summary_counts once the log is decoded."""
    raw = _read_recording_file(rec_dir, "summary.json")
    try:
        summary = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise StackError("summary.json is not valid JSON: %s" % exc) from exc
    trip = summary.get("trip") if isinstance(summary, dict) else None
    if not isinstance(trip, dict) or not isinstance(trip.get("segments"), list):
        raise StackError("summary.json has no trip.segments")
    seed = line["source"]["params"]["seed"]
    problems = []
    if summary.get("name") != line["name"]:
        problems.append("name %r, the manifest line's %r" % (summary.get("name"), line["name"]))
    if trip.get("seed") != seed:
        problems.append("trip.seed %r, the manifest line's %r" % (trip.get("seed"), seed))
    if "params" in trip and (not isinstance(trip["params"], dict) or trip["params"].get("seed", seed) != seed):
        problems.append("trip.params.seed %r, the manifest line's %r" % (
            trip["params"].get("seed") if isinstance(trip["params"], dict) else trip["params"], seed))
    if problems:
        raise StackError("summary.json does not describe this recording: " + "; ".join(problems))
    try:
        start, end = rc.hard_brake_segment(trip)
    except (ValueError, KeyError, IndexError, TypeError) as exc:      # no hard brake, or a segment that is not [name, start, end]
        raise StackError("summary.json: trip.segments is not a list of [name, start_ms, end_ms] with one 'hard brake': %s: %s"
                         % (type(exc).__name__, exc)) from exc
    return {"path": str(rec_dir / "summary.json"), "sha256": hashlib.sha256(raw).hexdigest(), "trip": trip,
            "hard_brake_ms": [start, end]}


def check_summary_counts(trip: Dict[str, Any], frames: Sequence[Tuple[int, str, Dict[str, Any]]]) -> Dict[str, int]:
    """The decoded log carries exactly the frames per message the summary's trip says it wrote."""
    counts: Dict[str, int] = {}
    for _t, name, _dec in frames:
        counts[name] = counts.get(name, 0) + 1
    if counts != trip.get("messages"):
        raise StackError("the decoded recording has %s frames per message, summary.json's trip says %s" % (counts, trip.get("messages")))
    return counts


def sigsim_provenance(line: Dict[str, Any], path: Path = SIGSIM) -> Dict[str, Any]:
    """Whether sdv/sim/sigsim.py is now the file that made the recording. Reported, never required:
    nothing of a run comes from running it."""
    want = line["source"]["params"].get("sigsim_sha256")
    try:
        now: Optional[str] = sha256_file(path)
    except OSError:
        now = None
    return {"file": "sdv/sim/sigsim.py", "recording_sigsim_sha256": want, "current_sha256": now,
            "current_equals_recording": now is not None and now == want,
            "note": "reported only: the windows come from the recording's summary.json, never from running sigsim"}


def carla_provenance(trip: Dict[str, Any], repo: Path = REPO) -> Dict[str, Any]:
    """Whether the sdv/carla modules and sdv/sim/carla_iso.py that encoded a CARLA recording (its trip's encoder_sha256)
    are now the files of CARLA_ENCODER_MODULES. Reported, never required, as sigsim's is: nothing of a run comes from
    running the encoder. A trip that names none (an injected rewrite drops it: sdv/inject/inject.py TRIP_KEPT) reports
    None."""
    want = trip.get("encoder_sha256") if isinstance(trip.get("encoder_sha256"), dict) else None
    now: Dict[str, Optional[str]] = {}
    for rel in CARLA_ENCODER_MODULES:
        try:
            now[rel] = sha256_file(repo / rel)
        except OSError:
            now[rel] = None
    return {"files": list(CARLA_ENCODER_MODULES), "recording_encoder_sha256": want, "current_sha256": now,
            "current_equals_recording": want is not None and want == now,
            "note": "reported only: the windows come from the recording's summary.json, never from running the encoder"}


def provider_upstream(line: Dict[str, Any], seed: int) -> str:
    """The upstream of the CAN provider's rows for the recording's run type (attribution-table section 4, its column of
    the run type): sigsim's is attribution.scenario_rows' own `sigsim seed N`; a CARLA recording's is the feeder's,
    `carla-feeder (<version>, <town>, seed N, <vehicle>)`, from its line (sdv/carla/encode.py's params and source vehicle;
    a value the line lacks reads `?`)."""
    source = line["source"]
    if source["generator"] == "sigsim":
        return "sigsim seed %d" % seed
    params = source.get("params") if isinstance(source.get("params"), dict) else {}
    vehicle = source.get("vehicle") if isinstance(source.get("vehicle"), dict) else {}
    return "carla-feeder (%s, %s, seed %d, %s)" % (params.get("version", "?"), params.get("town", "?"), seed, vehicle.get("name", "?"))


def with_provider_upstream(rows: List[Dict[str, Any]], line: Dict[str, Any], seed: int) -> List[Dict[str, Any]]:
    """attribution.scenario_rows names sigsim as the CAN provider's upstream whatever the recording (attribution.py is
    relied on unchanged, spec-2 5): a CARLA run's rows that do take provider_upstream's label, every other column, key and
    row as they are. A sigsim run's rows are returned as they are."""
    want, sigsim = provider_upstream(line, seed), "sigsim seed %d" % seed
    if want == sigsim:
        return rows
    return [dict(r, upstream=want) if r["writer"] == attr.CAN_PROVIDER and r["upstream"] == sigsim else r for r in rows]


def dbc_body(text: str) -> str:
    """slice.dbc without its // comment lines: what cantools and the provider read."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("//"))


def load_dbc_sources() -> Dict[str, Dict[str, str]]:
    return json.loads(DBC_SOURCES_FILE.read_text(encoding="utf-8"))["dbc"]


def windows_path(path: str, distro: Optional[str]) -> str:
    """A path as Windows names it: /mnt/<d>/x and <D>:/x as <D>:\\x; any other absolute path of
    the WSL distribution as \\\\wsl.localhost\\<distro>\\x."""
    p = path.replace("\\", "/")
    m = re.match(r"^/mnt/([A-Za-z])(/.*)?$", p) or re.match(r"^([A-Za-z]):(/.*)?$", p)
    if m:
        return m.group(1).upper() + ":" + (m.group(2) or "/").replace("/", "\\")
    if not p.startswith("/"):
        raise StackError("not an absolute path: %s" % path)
    return "\\\\wsl.localhost\\%s%s" % (distro or "<WSL distribution>", p.replace("/", "\\"))


def main_checkout(repo: Path) -> str:
    """The Windows path of the checkout whose .git holds this tree's repository. A worktree's .git
    is a file naming <main>/.git/worktrees/<name>; it is read here, git is never run."""
    dotgit = repo / ".git"
    if dotgit.is_file():
        m = re.match(r"gitdir:\s*(\S.*?)\s*$", dotgit.read_text(encoding="utf-8").strip())
        gitdir = m.group(1).replace("\\", "/") if m else ""
        if "/.git/" not in gitdir + "/":
            raise StackError("%s does not name a repository's .git directory: %r" % (dotgit, gitdir))
        main = (gitdir + "/").split("/.git/", 1)[0]
    else:
        main = str(repo)
    return windows_path(main, os.environ.get("WSL_DISTRO_NAME"))


def dbc_export_command(main: str, commit: str, path: str, dest: str) -> str:
    """The exact Windows command that writes <commit>:<path> to dest byte for byte: a read-only git
    under cmd, whose redirection keeps the bytes (PowerShell 5.1's `>` re-encodes and would change
    the sha256)."""
    return 'cmd /c "git -C %s show %s:%s > %s"' % (main, commit, path, dest)


# Said next to every export command a refusal prints: where it runs. cmd's /c is what Git Bash's path
# conversion rewrites, so there the same command is `cmd //c`, and its argument goes in single quotes:
# in double quotes bash itself collapses the `\\` that starts `\\wsl.localhost` to one backslash, and
# cmd's redirect then fails to find the path (nothing is written).
EXPORT_SHELL = "run it in PowerShell or cmd; in Git Bash use cmd //c with the argument in single quotes"


def resolve_dbc(sha: str, cache: Optional[Path] = None, sources: Optional[Dict[str, Dict[str, str]]] = None,
                repo: Path = REPO, working_copy: Path = SLICE_DBC) -> Dict[str, Any]:
    """The DBC the recording was encoded with, byte for byte, from <cache>/dbc/<sha256>.dbc only
    (the working copy of slice.dbc is never staged: others edit it). The copy must hash to sha and,
    when dbc-sources.json knows sha, have its git blob id. When it is missing the run is refused
    with the Windows command that exports it from the commit dbc-sources.json names, or, for a
    sha256 that file does not know, with the commands that find the commit; a commit is never guessed."""
    cache = CACHE if cache is None else cache
    sources = load_dbc_sources() if sources is None else sources
    cached = (cache / "dbc" / ("%s.dbc" % sha)).absolute()
    src = sources.get(sha)
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)       # so the export has a directory to write into
        main = main_checkout(repo)
        dest = windows_path(str(cached), os.environ.get("WSL_DISTRO_NAME"))
        if src is None:
            raise StackError(
                "the recording's DBC (sha256 %s) is not in %s, and %s names no commit for it. List the commits that "
                "carried slice.dbc on Windows (read-only): git -C %s log --all --format=%%H -- sdv/vss/slice.dbc ; export "
                "each with %s (%s) and keep the one whose sha256 is %s, then add that commit to dbc-sources.json. The "
                "stack never picks a commit." % (sha, cached.parent, DBC_SOURCES_FILE.name, main,
                                                 dbc_export_command(main, "<commit>", "sdv/vss/slice.dbc", dest), EXPORT_SHELL, sha))
        raise StackError("the recording's DBC (sha256 %s) is not in %s. Export it on Windows (a read-only git, from commit "
                         "%s as %s names it); %s: %s" % (sha, cached.parent, src["commit"][:12], DBC_SOURCES_FILE.name, EXPORT_SHELL,
                                                         dbc_export_command(main, src["commit"], src["path"], dest)))
    data = cached.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        raise StackError("%s hashes to %s, not %s: remove it and export it again" % (cached, got, sha))
    blob = git_blob_sha1(data)
    if src is not None and blob != src["git_blob"]:
        raise StackError("%s has git blob %s, %s says %s" % (cached, blob, DBC_SOURCES_FILE.name, src["git_blob"]))
    out: Dict[str, Any] = {"wanted_sha256": sha, "path": str(cached), "git_blob": blob, "source": src}
    try:
        wc = working_copy.read_bytes()
        out["working_copy_sha256"] = hashlib.sha256(wc).hexdigest()
        out["working_copy_body_equal"] = dbc_body(wc.decode("utf-8")) == dbc_body(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError):
        out["working_copy_sha256"] = None
    return out


def generation_manifest() -> Dict[str, Any]:
    return json.loads((GEN / "manifest.json").read_text(encoding="utf-8"))


def vehicle_layer_of(man: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The generation's per-vehicle layer (sdv/vss/generate.py, from Phase 2), its file checked against the
    manifest's output sha256; None for a generation made without one (the catalogue then serves VSS 6.0's
    Wheelbase default)."""
    layer = man.get("vehicle_layer")
    if layer is None:
        return None
    return dict(layer, sha256=_generated_sha256(man, layer["file"], "vehicle layer"))


def _generated_sha256(man: Dict[str, Any], name: str, what: str) -> str:
    """A generated file's sha256, which must be the one its manifest lists among its outputs."""
    path = GEN / name
    want = (man.get("outputs", {}).get(name) or {}).get("sha256")
    got = sha256_file(path) if path.is_file() else None
    if got is None or got != want:
        raise StackError("sdv-out/gen's %s %s hashes to %s, its manifest says %s (regenerate with sdv/vss/generate.py)"
                         % (what, name, got, want))
    return got


def generation_pair(man: Dict[str, Any], run_type: str) -> Dict[str, Any]:
    """The generation's files for a run type (module docstring, RECORDING KINDS AND RUN TYPES; spec-2 2.2): the databroker
    catalogue staged as in/vss-databroker.json and the vehicle layer its Wheelbase default comes from. sigsim: exactly
    today's, vss-databroker.json and manifest.json's vehicle_layer (vehicle_layer_of), whatever else the generation holds.
    Any other run type: vehicle_layers[<it>] and databroker_catalogues[<it>], each file's sha256 the manifest's; a
    generation without them (made before Phase 7's freeze) is refused, before anything is written."""
    if run_type == "sigsim":
        return {"run_type": run_type, "catalogue": SIGSIM_CATALOGUE, "vehicle_layer": vehicle_layer_of(man)}
    layers, cats = man.get("vehicle_layers"), man.get("databroker_catalogues")
    if not isinstance(layers, dict) or not isinstance(layers.get(run_type), dict):
        raise StackError("the generation has no %s vehicle layer (sdv-out/gen's manifest.json names no vehicle_layers.%s): a %s "
                         "recording runs only on a generation that compiles its profile (regenerate with sdv/vss/generate.py)"
                         % (run_type, run_type, run_type))
    if not isinstance(cats, dict) or not isinstance(cats.get(run_type), str):
        raise StackError("the generation has no %s databroker catalogue (sdv-out/gen's manifest.json names no "
                         "databroker_catalogues.%s; regenerate with sdv/vss/generate.py)" % (run_type, run_type))
    layer = layers[run_type]
    _generated_sha256(man, cats[run_type], "%s databroker catalogue" % run_type)
    return {"run_type": run_type, "catalogue": cats[run_type],
            "vehicle_layer": dict(layer, sha256=_generated_sha256(man, layer["file"], "%s vehicle layer" % run_type))}


def catalogue_identity(contract: Any, dbc_sha: str, pair: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The run header's catalogue item. The binding to the recording is the DBC's and the overlay's: the
    generation's manifest must name the recording's slice.dbc and the overlay as it is now. Its other inputs
    (profiles.toml, generate.py, the lock) and the vehicle layer generated from them are recorded, not
    compared: the recording does not depend on them (a Wheelbase default never reaches a CAN frame). pair: the
    run type's (generation_pair), whose catalogue and vehicle layer are recorded; by default sigsim's."""
    man = generation_manifest()
    current = {"overlay.vspec": sha256_file(OVERLAY), "slice.dbc": dbc_sha}
    stale = {k: {"generated_from": man["inputs"].get(k), "now": v} for k, v in current.items() if man["inputs"].get(k) != v}
    if stale:
        raise StackError("sdv-out/gen was not generated from these inputs (regenerate with sdv/vss/generate.py): %s" % stale)
    pair = generation_pair(man, "sigsim") if pair is None else pair
    layer = pair["vehicle_layer"]
    return {
        "vss_archive_sha256": "sha256:" + contract.VSS_ARCHIVE_SHA256,
        "vss_commit": contract.VSS_COMMIT,
        "vss_tools": contract.VSS_TOOLS_VERSION,
        "overlay_sha256": "sha256:" + current["overlay.vspec"],
        "overlay_ctl_sha256": None,
        "units_project_sha256": None,
        "quantities_project_sha256": None,
        "vehicle_layer_sha256": None if layer is None else "sha256:" + layer["sha256"],
        "databroker_json_sha256": "sha256:" + sha256_file(GEN / pair["catalogue"]),
        "mapping_json_sha256": "sha256:" + sha256_file(GEN / "vss-can-mapping.json"),
        "kind4_digest": "0x%08X" % contract.CATALOG_DIGEST,
    }


def load_contract() -> Any:
    import importlib.util
    spec = importlib.util.spec_from_file_location("_vss_contract_for_stack", str(GEN / "vss_contract.py"))
    if spec is None or spec.loader is None:
        raise StackError("no generated contract in %s" % GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def time_sync() -> Dict[str, Any]:
    """The host's time-sync state (attribution-table 3.1 time_sync, without age_clock: that one is the bridge
    mode's, age_clock())."""
    p = run(["timedatectl", "show", "-p", "NTPSynchronized", "-p", "NTP", "--value"], check=False, timeout=20)
    daemon = "unknown"
    for unit in ("systemd-timesyncd", "chrony", "ntpsec", "ntp"):
        q = run(["systemctl", "is-active", unit], check=False, timeout=20)
        if q.stdout.strip() == "active":
            daemon = unit
            break
    else:
        daemon = "none"
    vals = p.stdout.split() if p.returncode == 0 else []
    return {"daemon": daemon, "synchronised": (vals[0] == "yes") if vals else None}


def age_clock(bridge_mode: str) -> Optional[str]:
    """time_sync.age_clock for a run: the clock the bridge mode reads its ages on, or None when no bridge runs."""
    if bridge_mode == "none":
        return None
    if bridge_mode not in AGE_CLOCK:
        raise StackError("bridge mode %r has no known age clock" % bridge_mode)
    return AGE_CLOCK[bridge_mode]


BROKER_NEEDS_VCAN = ("--bridge broker needs --feed vcan: the dumpfile feed runs the databroker with --network none and every "
                     "container in its namespace, where the bridge could never reach the monitor on the host's :%d" % MONITOR_PORT)
VSS_MONITOR = "vss-monitor-native"            # the native vss monitor's entry in the run manifest's components
VSS_MONITOR_GUEST = "vss-monitor-guest"       # guest mode's entry: the QNX guest's vss monitor (SDV Phase 3 WP2)


def host_role() -> str:
    """The run's host role (module docstring, HOST ROLE): SDV_HOST_ROLE, one of HOST_ROLES, pc when unset. Any other value
    is refused."""
    role = os.environ.get(HOST_ROLE_ENV, DEFAULT_HOST_ROLE)
    if role not in HOST_ROLES:
        raise StackError("%s=%r: one of %s (a role, never a hostname)" % (HOST_ROLE_ENV, role, ", ".join(HOST_ROLES)))
    return role


# --- placement (module docstring, PLACEMENT; SDV Phase 5 WP1) --------------------------------------------------------------

_CPU = re.compile(r"0|[1-9][0-9]*")


def container_cpuset(role: str) -> Optional[str]:
    """SDV_CONTAINER_CPUSET as given, or None when it is not set. Required on orin; refused when empty, when it is not a list
    N[,N...] of distinct decimal integers, or when it holds a core of CPUSET_FORBIDDEN (on every role: one rule, so the PC
    rehearsal runs the board's). Each refusal names the variable, never a host value."""
    raw = os.environ.get(CPUSET_ENV)
    if raw is None:
        if role == "orin":
            raise StackError("%s=orin needs %s, the CPU list every container runs on (on the board cores 0-2 are QEMU's and core 4 "
                             "the probe's, plan 3.7)" % (HOST_ROLE_ENV, CPUSET_ENV))
        return None
    if not raw:
        raise StackError("%s is set but empty: give a CPU list N[,N...], or leave it unset off the Orin" % CPUSET_ENV)
    items = raw.split(",")
    if not all(_CPU.fullmatch(i) for i in items):
        raise StackError("%s is not a CPU list N[,N...] of decimal integers (no space, range or leading zero)" % CPUSET_ENV)
    cpus = [int(i) for i in items]
    if len(set(cpus)) != len(cpus):
        raise StackError("%s names a CPU twice" % CPUSET_ENV)
    bad = sorted(set(cpus) & set(CPUSET_FORBIDDEN))
    if bad:
        raise StackError("%s holds CPU %s: on the Orin cores 0-2 are QEMU's and core 4 the probe's (plan 3.7), and no container "
                         "runs there" % (CPUSET_ENV, ", ".join(str(c) for c in bad)))
    return raw


def after_start_argv(role: str) -> Optional[List[str]]:
    """SDV_AFTER_START split with shlex (it never reaches a shell), or None when it is not set. Required on orin beside either
    monitor: the stack knows the board only by its role, and a guest may run beside a native-monitor run too, so no container
    starts there without the re-pin after it. Refused when shlex cannot split it or it holds no word. Its value is never
    echoed: a path in it can name a login."""
    raw = os.environ.get(AFTER_START_ENV)
    if raw is None:
        if role == "orin":
            raise StackError("%s=orin needs %s beside either monitor, the command run after each container start that re-pins "
                             "QEMU's threads and reads them back (plan 3.7)" % (HOST_ROLE_ENV, AFTER_START_ENV))
        return None
    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        raise StackError("%s cannot be split into words by shlex (%s)" % (AFTER_START_ENV, exc)) from None
    if not argv:
        raise StackError("%s is set but empty: give the command, or leave it unset off the Orin" % AFTER_START_ENV)
    return argv


def placement_record(cpuset: Optional[str], after_start: Optional[Sequence[str]]) -> Dict[str, Any]:
    """The run manifest's placement: the cpuset and the hook's argv as given (it holds no secret), or that none was set."""
    return {"cpuset": cpuset,
            "cpuset_note": ("--cpuset-cpus %s after the common flags of every container this run starts (%s)" % (cpuset, CPUSET_ENV)
                            if cpuset else "%s not set: no --cpuset-cpus, docker's default placement" % CPUSET_ENV),
            "after_start": None if after_start is None else list(after_start),
            "after_start_note": ("run after each container start with the container's name appended, its records in each result's %s "
                                 "(%s)" % (AFTER_START_KEY, AFTER_START_ENV) if after_start else
                                 "%s not set: nothing runs after a container start" % AFTER_START_ENV)}


def common_flags(ctx: Any) -> List[str]:
    """The flags every container of the stack takes (COMMON), then --cpuset-cpus <SDV_CONTAINER_CPUSET> when the run has one:
    the one place a docker run of the stack takes them from. A context that knows no cpuset (Phase 1's, a test's) has none."""
    cpuset = getattr(ctx, "cpuset", None)
    return COMMON + (["--cpuset-cpus", cpuset] if cpuset else [])


def new_hook_records(ctx: Any) -> List[Dict[str, Any]]:
    """A run's hook records begun afresh (each replay, each step-3 run): a run records only the containers it started."""
    ctx.after_start_records = []
    return ctx.after_start_records


def hook_records(ctx: Any) -> Optional[List[Dict[str, Any]]]:
    """What a run's result carries under AFTER_START_KEY: this run's hook records in start order, or None when no hook is set
    (the result then has no such key, as before Phase 5)."""
    if not getattr(ctx, "after_start", None):
        return None
    return list(getattr(ctx, "after_start_records", None) or [])


def _last_lines(text: Any) -> List[str]:
    if isinstance(text, bytes):          # a timeout's partial output is bytes whatever text= said
        text = text.decode("utf-8", errors="replace")
    return (text or "").splitlines()[-AFTER_START_KEPT:]


def run_after_start(ctx: Any, name: str) -> None:
    """SDV_AFTER_START after the container `name` started: its argv with the name appended, no shell, under
    AFTER_START_TIMEOUT_S. Its record (the container, the exit status, the last lines of its stdout and its stderr, and an
    error when it timed out or could not be started) is appended to the run's records before any refusal; a non-zero exit, a
    timeout or a command that cannot be started is a StackError naming the container, which stops the run as a failed start
    does. No hook set: nothing runs."""
    argv = getattr(ctx, "after_start", None)
    if not argv:
        return
    records = getattr(ctx, "after_start_records", None)
    if records is None:
        records = new_hook_records(ctx)
    rec: Dict[str, Any] = {"container": name, "exit": None, "output": [], "stderr": [], "error": None}
    records.append(rec)
    what = "%s after %s started" % (AFTER_START_ENV, name)
    try:
        p = subprocess.run(list(argv) + [name], capture_output=True, text=True, timeout=AFTER_START_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        rec.update(output=_last_lines(exc.stdout), stderr=_last_lines(exc.stderr), error="did not end within %g s" % AFTER_START_TIMEOUT_S)
        raise StackError("%s: %s" % (what, rec["error"])) from None
    except OSError as exc:
        rec["error"] = "could not be started: %s" % (exc.strerror or type(exc).__name__)
        raise StackError("%s: %s" % (what, rec["error"])) from None
    rec.update(exit=p.returncode, output=_last_lines(p.stdout), stderr=_last_lines(p.stderr))
    if rec["exit"] != 0:
        raise StackError("%s: exit %d (%s)" % (what, rec["exit"], " | ".join(rec["output"][-1:] + rec["stderr"][-1:]) or "no output"))


def refuse_pc_only(cmd: str) -> None:
    """loadcheck, ageprobe and wheelbaseprobe start containers outside start(), and exit-test ends with loadcheck: the PC's
    Phase 1 and 2 probes, refused on orin before anything is pulled, written or started (Phase 5 runs none of them)."""
    if cmd in PC_ONLY and host_role() == "orin":
        raise StackError("%s is the PC's (it starts containers outside the run's start path%s): refused on %s=orin" % (
            cmd, ", in its last step loadcheck" if cmd == "exit-test" else "", HOST_ROLE_ENV))


def ipv4_of(ip_json: str) -> Optional[List[str]]:
    """The IPv4 addresses in `ip -j -4 addr show`'s JSON, sorted; None when it is not that JSON."""
    try:
        doc = json.loads(ip_json)
    except ValueError:
        return None
    if not isinstance(doc, list):
        return None
    return sorted({str(a["local"]) for i in doc if isinstance(i, dict) for a in (i.get("addr_info") or [])
                   if isinstance(a, dict) and a.get("family") == "inet" and a.get("local")})


def local_ipv4() -> Optional[List[str]]:
    """This host's own IPv4 addresses (`ip -j -4 addr show`), or None when they cannot be read."""
    try:
        p = subprocess.run(["ip", "-j", "-4", "addr", "show"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return ipv4_of(p.stdout) if p.returncode == 0 else None


def host_is_local(host: str) -> Optional[bool]:
    """Whether host is one of this host's own IPv4 addresses; None when they cannot be read."""
    local = local_ipv4()
    return None if local is None else str(host) in local


def guest_problems(host: Optional[str], console: Optional[Any], image: Optional[Any]) -> List[str]:
    """What guest mode refuses in its three operands (SDV Phase 3 WP2): a host that is not an IPv4 address (the bridge
    connects over AF_INET) or is a loopback or unspecified one (guest mode judges over br0, never this host's own stack),
    off the PC one of this host's own addresses (on a1-metal, c7g-metal or orin the guest is never this host, and whatever listens
    here, a native monitor, would judge the run; on the PC the stand-in guest is this host by design), and a console or
    an image that is not a file."""
    problems = []
    try:
        addr = ipaddress.IPv4Address(str(host))
    except ValueError:
        problems.append("the guest host %r is not an IPv4 address" % (host,))
    else:
        if addr.is_loopback or addr.is_unspecified:
            problems.append("the guest host %s is a loopback or unspecified address: guest mode judges over br0, never on this host's own "
                            "loopback" % addr)
        elif host_role() != "pc" and host_is_local(str(addr)):
            problems.append("the guest host %s is one of this host's own addresses: on %s the guest is never this host, and what "
                            "listens here would judge the run" % (addr, host_role()))
    if console is None or not Path(console).is_file():
        problems.append("no guest console file %s" % (console,))
    if image is None or not Path(image).is_file():
        problems.append("no guest image file %s" % (image,))
    return problems


def monitor_mode(ctx: Any) -> str:
    """native or guest (MONITOR_MODES); a context that names none is native."""
    return getattr(ctx, "monitor_mode", "native")


def monitor_host(ctx: Any) -> str:
    """Where the bridge reaches the vss monitor (its --host): the guest's address in guest mode, else the loopback."""
    return str(ctx.guest["host"]) if monitor_mode(ctx) == "guest" else LOCAL_MONITOR_HOST


def monitor_component(ctx: Any) -> Dict[str, Any]:
    """The run manifest's component of the vss monitor that judges the run: the guest's, or the native build's."""
    return ctx.components[VSS_MONITOR_GUEST if monitor_mode(ctx) == "guest" else VSS_MONITOR]


def guest_component(guest: Dict[str, Any]) -> Dict[str, Any]:
    """Guest mode's component (no build): the image's file name and sha256, the host and port the bridge reaches (and
    whether the host is one of this host's own addresses: the PC's stand-in is, a guest never; None when unknown), and the
    arguments the image's build file (GUEST_IMAGE_BUILDS, by the image's name) starts the guest's monitor with."""
    image = Path(guest["image"])
    return {"class": "platform", "form": "guest", "image": image.name, "sha256": sha256_file(image), "host": str(guest["host"]),
            "host_local": host_is_local(str(guest["host"])),
            "port": MONITOR_PORT, "run_as": "%d svc %d" % (MONITOR_PORT, MONITOR_DEADLINE_MS),
            "started_by": "%s (qnx-safety-monitor %d svc %d)" % (GUEST_IMAGE_BUILDS.get(image.name, GUEST_IMAGE_OTHER_BUILD), MONITOR_PORT,
                                                                MONITOR_DEADLINE_MS),
            "note": "the QNX guest's vss monitor, judged over br0; nothing built or started here; a functional mode: no timing"}


def guest_info(ctx: Any) -> Dict[str, Any]:
    """A run's record of the monitor it did not start (guest mode): where the bridge reaches it."""
    return {"form": "guest", "host": str(ctx.guest["host"]), "port": MONITOR_PORT}


def bridge_core() -> Any:
    """sdv/bridge/vss_claim_bridge.py, read for the bridge's configured write set (standard library only)."""
    name = "_sdv_bridge_core_for_stack"
    if name in sys.modules:
        return sys.modules[name]
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(BRIDGE_DIR / "vss_claim_bridge.py"))
    if spec is None or spec.loader is None:
        raise StackError("cannot load %s" % (BRIDGE_DIR / "vss_claim_bridge.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[name]
        raise
    return mod


def bridge_writes(contract: Any) -> List[str]:
    """The bridge's configured write set: its write-back leaves under the project branch's Monitor.VssClaim."""
    return sorted(bridge_core().writeback_paths(contract).values())


def catalogue_default(tree: Any, path: str) -> Any:
    """What databroker 0.7.1 serves for an attribute nothing writes: its catalogue `default`, and nothing (None) when
    the node has none or the catalogue lacks the node (Phase 1 stage 3, finding 2; `wheelbaseprobe` checks both)."""
    return (attr.leaf_nodes(tree).get(path) or {}).get("default")


def served_wheelbase(catalogue_tree: Any, l_mm: Optional[int], vehicle: Dict[str, Any], layer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Spec 5.6's broker-mode Wheelbase branches, as the stack predicts them from the catalogue it stages, before
    anything starts. A served value that is not the profile's L: refused here, as the bridge would refuse it. None
    served: the bridge starts and logs WHEELBASE_NOTE, and L's only cross-check is then the declared source vehicle's
    (C12a); the run manifest records the note. Returns the run manifest's record, which bridge_result() compares with
    the wheelbase record the bridge logged."""
    served = catalogue_default(catalogue_tree, attr.WHEELBASE)
    if served is None:
        return {"path": attr.WHEELBASE, "served": False, "l_mm": l_mm, "note": WHEELBASE_NOTE,
                "from": "the staged catalogue has no default for it"}
    if isinstance(served, bool) or served != l_mm:
        raise StackError("--bridge broker: the generated catalogue serves %s = %r (vehicle layer %s), not the profile's L %r mm "
                         "(source vehicle %s, %r mm): the bridge would refuse to start (spec 5.6). Regenerate with "
                         "sdv/vss/generate.py" % (attr.WHEELBASE, served, layer["file"] if layer else "none", l_mm,
                                                  vehicle.get("name"), vehicle.get("wheelbase_mm")))
    return {"path": attr.WHEELBASE, "served": True, "value_mm": served, "l_mm": l_mm,
            "from": "the staged catalogue's default (vehicle layer %s)" % (layer["file"] if layer else "none")}


def bridge_image(contract: Any, dbc_sha: str, pin: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The bridge image SDV_BRIDGE_IMAGE names, by ID only, its labels checked against this generation: the
    catalogue digest, the contract's sha256 and slice.dbc's (sdv/bridge/build_image.py sets them). An image
    built from another generation is refused: rebuild it. With pin (--images loaded: images.json bridge.arm64) the image
    must also be that pin, present by its ID as linux/arm64."""
    ref = os.environ.get(BRIDGE_IMAGE_ENV, "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", ref):
        raise StackError("--bridge broker needs the claim bridge image by ID: set %s to sha256:<64 hex> (sdv/bridge/build_image.py "
                         "prints it); got %r" % (BRIDGE_IMAGE_ENV, ref))
    if pin is not None:
        if ref != pin["id"]:
            raise StackError("%s names %s; --images loaded runs the bridge's arm64 pin %s (images.json bridge.arm64)" % (
                BRIDGE_IMAGE_ENV, ref, pin["id"]))
        found, why = inspect_image(ref)
        bad = bd.loaded_problems(attr.BRIDGE, pin, found, why)
        if bad or found is None:
            raise StackError("--images loaded: " + "; ".join(bad))
        info = found
    else:
        info = json.loads(docker("image", "inspect", ref).stdout)[0]
    if info.get("Id") != ref:
        raise StackError("%s names %s, whose image ID is %s" % (BRIDGE_IMAGE_ENV, ref, info.get("Id")))
    labels = (info.get("Config") or {}).get("Labels") or {}
    want = {"sdv.kind4.catalog_digest": "0x%08X" % contract.CATALOG_DIGEST, "sdv.kind4.contract_sha256": sha256_file(GEN / "vss_contract.py"),
            "sdv.kind4.dbc_sha256": dbc_sha}
    wrong = {k: {"image": labels.get(k), "this_run": v} for k, v in want.items() if labels.get(k) != v}
    if wrong:
        raise StackError("the bridge image %s was built from another generation (rebuild it with sdv/bridge/build_image.py): %s" % (ref, wrong))
    if pin is not None:
        return {"class": "platform", "form": "container", "image_id": ref, "labels": want, "tag": pin["tag"],
                "config_digest": pin["config_digest"], "arch": bd.ARCH,
                "pull": {"via": "loaded", "pin": "images.json bridge.arm64", "built_by": "sdv/bridge/build_image.py --arch arm64"}}
    return {"class": "platform", "form": "container", "image_id": ref, "labels": want, "tag": (info.get("RepoTags") or [None])[0],
            "pull": {"via": "local-build", "built_by": "sdv/bridge/build_image.py"}}


# --- the twin connector (SDV Phase 4 WP3) -----------------------------------------------------------

def has_connector(ctx: Any) -> bool:
    """Whether this context's runs start a twin connector; a context that names none (Phase 1's, step3.py's) has none."""
    return bool(getattr(ctx, "connector", False))


def inside_repo(path: Path) -> bool:
    r, repo = path.resolve(), REPO.resolve()
    return r == repo or repo in r.parents


def connector_part(name: str) -> Any:
    """A module of sdv/connector the stack reads, loaded by its file under a name of the stack's own (the connector's
    modules have plain names and import each other by them; none of them goes onto the stack's sys.path): limits.py for
    the start spacing, startstamp.py for the stamp that keeps it. One implementation, the connector's."""
    key = "_sdv_connector_%s_for_stack" % name
    if key in sys.modules:
        return sys.modules[key]
    import importlib.util
    spec = importlib.util.spec_from_file_location(key, str(CONNECTOR_DIR / (name + ".py")))
    if spec is None or spec.loader is None:
        raise StackError("cannot load %s" % (CONNECTOR_DIR / (name + ".py")))
    mod = importlib.util.module_from_spec(spec)
    missing = object()
    saved = sys.modules.get("limits", missing)
    if name != "limits":
        sys.modules["limits"] = connector_part("limits")          # what startstamp.py's `import limits` finds
    try:
        spec.loader.exec_module(mod)
    finally:
        if name != "limits":
            if saved is missing:
                del sys.modules["limits"]
            else:
                sys.modules["limits"] = saved          # type: ignore[assignment]
    sys.modules[key] = mod
    return mod


def device_dir() -> Path:
    """The device directory SDV_DEVICE_DIR names: an absolute path outside the repo, holding connector.env. Its path
    and its files' names go onto the connector's argument vector and nowhere else: never into a run directory."""
    raw = os.environ.get(DEVICE_DIR_ENV, "")
    d = Path(raw).expanduser() if raw else None
    if d is None or not d.is_absolute() or not d.is_dir():
        raise StackError("--connector needs the device directory: set %s to an absolute path of a directory that holds the device's "
                         "key, certificate and CA file and %s" % (DEVICE_DIR_ENV, CONNECTOR_ENV_FILE))
    if inside_repo(d):
        raise StackError("the device directory %s names is inside the repo: a key, a certificate and an endpoint stay outside it" % DEVICE_DIR_ENV)
    if not (d / CONNECTOR_ENV_FILE).is_file():
        raise StackError("the device directory %s names holds no %s (the endpoint and the thing's and the rule's names, one NAME=value a "
                         "line, for --env-file)" % (DEVICE_DIR_ENV, CONNECTOR_ENV_FILE))
    return d


def connector_image() -> Dict[str, Any]:
    """The connector image SDV_CONNECTOR_IMAGE names, by ID only, its labels checked against this generation: the
    allowlist version this stack runs on and the sha256 of the catalogue's id file the frozen allowlist in the image was
    generated from (sdv/connector/build_image.py sets them). An image built from another generation is refused: rebuild
    it. So is an image whose own user is root (the stack starts it as the host user in any case)."""
    ref = os.environ.get(CONNECTOR_IMAGE_ENV, "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", ref):
        raise StackError("--connector needs the connector image by ID: set %s to sha256:<64 hex> (sdv/connector/build_image.py prints "
                         "it); got %r" % (CONNECTOR_IMAGE_ENV, ref))
    info = json.loads(docker("image", "inspect", ref).stdout)[0]
    if info.get("Id") != ref:
        raise StackError("%s names %s, whose image ID is %s" % (CONNECTOR_IMAGE_ENV, ref, info.get("Id")))
    config = info.get("Config") or {}
    labels = config.get("Labels") or {}
    got = {k: labels.get(k) for k in CONNECTOR_LABELS}
    want = {"sdv.twin.allowlist_version": str(attr.ALLOWLIST_VERSION), "sdv.twin.catalogue_sha256": sha256_file(GEN / "vss-ids.vspec")}
    wrong = {k: {"image": got.get(k), "this_run": v} for k, v in want.items() if got.get(k) != v}
    if not re.fullmatch(r"0x[0-9A-F]{8}", str(got.get("sdv.twin.allowlist_digest"))):
        wrong["sdv.twin.allowlist_digest"] = {"image": got.get("sdv.twin.allowlist_digest"), "this_run": "0x<8 hex>"}
    if wrong:
        raise StackError("the connector image %s was built from another generation (rebuild it with sdv/connector/build_image.py): %s"
                         % (ref, wrong))
    user = str(config.get("User") or "")
    if user.split(":")[0] in ("", "0", "root"):
        raise StackError("the connector image %s runs as root by itself (its User is %r): the connector's image names a user of its own"
                         % (ref, user))
    return {"class": "platform", "form": "container", "image_id": ref, "labels": got, "user": user,
            "tag": (info.get("RepoTags") or [None])[0], "pull": {"via": "local-build", "built_by": "sdv/connector/build_image.py"}}


def wall_ms() -> int:
    """The host's wall clock in whole milliseconds: the clock of the start stamps (the connector's and the stack's)."""
    return time.time_ns() // 1_000_000


def connector_state_dir(make: bool = True) -> Path:
    """Where the stack keeps the time of the last connector start: the host's state directory (SDV_STATE), which outlives
    every run directory. Never inside the repo."""
    d = STATE / "twin"
    if inside_repo(d):
        raise StackError("the state directory %s is inside the repo: set %s to a directory outside it" % (d, STATE_ENV))
    if make:
        d.mkdir(parents=True, exist_ok=True)
    return d


def connector_spacing_left(now_ms: int) -> float:
    """How many seconds until this host's stack may start a connector again (0.0: now), read from the stack's stamp
    without writing it. A stamp that cannot be judged here (no stamp, a file that is none, one from the future) is left
    to mark_connector_start(), which is what refuses."""
    ss, limits = connector_part("startstamp"), connector_part("limits")
    try:
        data = (connector_state_dir(make=False) / ss.FILE).read_bytes()
    except OSError:
        return 0.0
    previous = ss.parse(data)
    if previous is None or now_ms < previous:
        return 0.0
    return max(0, limits.START_SPACING_S * 1000 - (now_ms - previous)) / 1000.0


def spacing_refusal(left_s: float) -> StackError:
    return StackError("a connector was started less than %d s ago by this host's stack: the start spacing: wait %d s (each start costs "
                      "shadow publishes whatever the run's length, and each run has a limiter of its own; sdv/connector/limits.py)"
                      % (connector_part("limits").START_SPACING_S, int(-(-left_s // 1))))


def mark_connector_start() -> None:
    """Record a connector start now in the stack's stamp, or refuse it: sdv/connector/startstamp.py's rule, on the host's
    state directory. A refused start leaves the stamp as it is."""
    ss = connector_part("startstamp")
    try:
        ss.mark(connector_state_dir(), wall_ms())
    except ss.StartRefused as refused:
        if refused.why == "spacing" and refused.retry_after_s is not None:
            raise spacing_refusal(refused.retry_after_s) from None
        raise StackError("the stack's connector start stamp refuses this start (%s%s): %s" % (
            refused.why, "" if refused.retry_after_s is None else ", wait %d s" % int(-(-refused.retry_after_s // 1)),
            connector_state_dir(make=False) / ss.FILE)) from None


# --- SDV Phase 6 WP2: the app outside the stack, the host's spool and status, the twin-control marker -----------------

def app_mode(ctx: Any) -> str:
    """Who starts the app (APP_MODES): `stack`, this run; `external`, something outside it. A context that names none
    (Phase 1's, step3.py's own, a test's) is the stack's."""
    return str(getattr(ctx, "app", "stack"))


def host_spool_status() -> Optional[Tuple[Path, Path]]:
    """SDV_SPOOL_DIR and SDV_STATUS_DIR (module docstring, HOST SPOOL AND STATUS): None when neither is set; else both, each
    the absolute path of an existing directory outside the repo. One alone is refused. The stack never makes either. A
    refusal names the variable, never its value (a path can name a login)."""
    raw = {name: os.environ.get(name) for name in (SPOOL_DIR_ENV, STATUS_DIR_ENV)}
    given = [name for name, value in raw.items() if value is not None]
    if not given:
        return None
    if len(given) == 1:
        raise StackError("%s and %s are set both or neither: %s alone is refused (the connector takes its spool and its status "
                         "from the host together, or both from the replay)" % (SPOOL_DIR_ENV, STATUS_DIR_ENV, given[0]))
    out: List[Path] = []
    for name in (SPOOL_DIR_ENV, STATUS_DIR_ENV):
        value = raw[name] or ""
        d = Path(value)
        if not value or not d.is_absolute() or not d.is_dir():
            raise StackError("%s must be the absolute path of an existing directory: the stack never makes it" % name)
        if inside_repo(d):
            raise StackError("%s names a directory inside the repo: the host's spool and status stay outside it" % name)
        out.append(d)
    return out[0], out[1]


def twin_control_marker() -> Path:
    """The twin-control marker's path: SDV_TWIN_CONTROL_MARKER, an absolute path, or TWIN_CONTROL_MARKER when unset."""
    raw = os.environ.get(TWIN_CONTROL_ENV)
    if raw is None:
        return Path(TWIN_CONTROL_MARKER)
    if not raw or not os.path.isabs(raw):
        raise StackError("%s must be an absolute path (the twin-control marker; unset, %s)" % (TWIN_CONTROL_ENV, TWIN_CONTROL_MARKER))
    return Path(raw)


def refuse_twin_control() -> None:
    """Refuse a bridge while the twin-control marker exists (module docstring, TWIN CONTROL). Its existence is the mode: any
    entry at its path (a file, a directory, a link to nothing) is the marker, and one that cannot be looked for counts as one."""
    marker = twin_control_marker()
    try:
        os.lstat(str(marker))
    except (FileNotFoundError, NotADirectoryError):
        return
    except OSError as exc:
        raise StackError("cannot tell whether the twin-control marker exists (%s: %s): a run with a bridge is refused"
                         % (TWIN_CONTROL_ENV, exc.strerror or type(exc).__name__)) from None
    raise StackError(TWIN_CONTROL_REFUSAL)


def refuse_bridge_in_twin_control(bridge: str) -> None:
    """A run in `bridge` mode, refused while the marker exists (refuse_twin_control). A run with no bridge does not look."""
    if bridge != "none":
        refuse_twin_control()


def connector_checks(ctx: Any, feed: str) -> None:
    """What refuses a run with a connector before anything is started, removed or made: a feed other than vcan, the
    guest monitor mode, and a start inside the start spacing."""
    if feed != "vcan":
        raise StackError(CONNECTOR_NEEDS_VCAN)
    if monitor_mode(ctx) == "guest":
        raise StackError(CONNECTOR_NOT_WITH_GUEST)
    left = connector_spacing_left(wall_ms())
    if left > 0:
        raise spacing_refusal(left)


def build_native_monitor(out: Path) -> Dict[str, Any]:
    """monitor.c's vss build for the host (build-monitor-native.sh with MONITOR_EXT_KINDS=0x10), into out, a path in
    the run directory: never the script's default OUT, whose source guard protects the ladder's host arm."""
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, MONITOR_EXT_KINDS=MONITOR_EXT_KINDS, MONITOR_VSS_GEN=str(GEN), OUT=str(out))
    p = subprocess.run(["bash", str(NATIVE_BUILD)], env=env, capture_output=True, text=True, timeout=300)
    (out.parent / "build.log").write_text(p.stdout + p.stderr, encoding="utf-8")
    if p.returncode != 0:
        raise StackError("build-monitor-native.sh failed (%d): %s" % (p.returncode, (p.stderr or p.stdout)[-1500:]))
    return {"class": "platform", "form": "native", "path": str(out), "sha256": sha256_file(out),
            "source_tree_sha256": out.with_name(out.name + ".source-sha256").read_text(encoding="utf-8").strip(),
            "headers_sha256": {h: sha256_file(GEN / h) for h in ("vss_contract.h", "vss_profiles.h")},
            "build": "MONITOR_EXT_KINDS=%s MONITOR_VSS_GEN=<gen> OUT=<run>/bin/%s %s" % (MONITOR_EXT_KINDS, out.name, NATIVE_BUILD.relative_to(REPO)),
            "run_as": "%s %d svc %d" % (out.name, MONITOR_PORT, MONITOR_DEADLINE_MS),
            "note": "the native build of the guest's monitor.c, not the guest: no QNX, no io-sock, no timing"}


class Context:
    """Everything a replay needs, prepared once per run."""

    def __init__(self, run_dir: Path, cli_seed: Optional[int] = None, bridge: str = "none", monitor: str = "native",
                 guest_host: Optional[str] = None, guest_console: Optional[Any] = None, guest_image: Optional[Any] = None,
                 connector: bool = False, app: str = "stack") -> None:
        """monitor (SDV Phase 3 WP2): "native", the native vss monitor built and started here, or "guest", the QNX guest's,
        which needs a bridge mode, the guest's IPv4 host (never loopback; off the PC never this host's own), its console
        file and its image file. connector (SDV Phase 4 WP3): the run starts the twin connector too; refused beside the
        guest monitor mode. app (SDV Phase 6 WP2): who starts the app, APP_MODES. A context with a bridge is refused while
        the twin-control marker exists. SDV_SPOOL_DIR and SDV_STATUS_DIR are read here by a context with a connector, and
        by no other, and taken only when the app is external. Every refusal comes before anything is written."""
        self.host_role = host_role()
        if bridge not in BRIDGE_MODES:
            raise StackError("--bridge %r: the stack runs %s" % (bridge, ", ".join(BRIDGE_MODES)))
        refuse_bridge_in_twin_control(bridge)          # TWIN CONTROL: step3.py makes its own contexts, so here as in main()
        if monitor not in MONITOR_MODES:
            raise StackError("--monitor %r: one of %s" % (monitor, ", ".join(MONITOR_MODES)))
        if app not in APP_MODES:
            raise StackError("--app %r: one of %s" % (app, ", ".join(APP_MODES)))
        if connector and monitor == "guest":
            raise StackError(CONNECTOR_NOT_WITH_GUEST)
        self.connector = bool(connector)
        self.app = app
        # HOST SPOOL AND STATUS: None, or (spool, status), each checked here; only the connector mounts them, so a run without
        # one does not read them, and only an external app may sit beside them (the updater's, which their spool feeds)
        self.host_dirs = host_spool_status() if self.connector else None
        if self.host_dirs is not None and app != "external":
            raise StackError(HOST_DIRS_NEED_EXTERNAL_APP)
        self.guest: Optional[Dict[str, Any]] = None
        if monitor == "guest":
            if bridge == "none":
                raise StackError("--monitor guest needs a bridge mode (%s): the guest judges the bridge's claims" % ", ".join(BRIDGE_MODES[1:]))
            bad = guest_problems(guest_host, guest_console, guest_image)
            if bad:
                raise StackError("guest mode: %s" % "; ".join(bad))
            self.guest = {"host": str(guest_host), "console": Path(str(guest_console)), "image": Path(str(guest_image))}
        elif (guest_host, guest_console, guest_image) != (None, None, None):
            raise StackError("the guest's host, console and image are guest mode's (--monitor guest), not the native monitor's")
        # placement (module docstring, PLACEMENT): read once, refused here after the refusals above, before anything is written
        self.cpuset = container_cpuset(self.host_role)
        self.after_start = after_start_argv(self.host_role)
        self.after_start_records: List[Dict[str, Any]] = []
        self.monitor_mode = monitor
        self.bridge = bridge
        self.monitor: Optional["NativeMonitor"] = None      # the running native vss monitor, while a replay runs
        self.run_dir = run_dir
        self.cli_seed = cli_seed          # checked against the recording, never used as the seed
        self.seed: Optional[int] = None   # the recording's, set by prepare()
        # the recording's run type and the name its log is staged under, set by prepare() (a context that has not read its
        # recording is Phase 1's sigsim one)
        self.run_type = "sigsim"
        self.log_name = LOG_NAMES["sigsim"]
        self.catalogue_file = SIGSIM_CATALOGUE         # the generation's file staged as in/vss-databroker.json (prepare)
        self.images = load_images()
        self.components: Dict[str, Any] = {}
        self.contract = load_contract()
        self.catalogue_tree = json.loads((GEN / "vss-databroker.json").read_text(encoding="utf-8"))
        self.mapping_tree = json.loads((GEN / "vss-can-mapping.json").read_text(encoding="utf-8"))
        self.catalogue = attr.leaf_nodes(self.catalogue_tree)
        self.mapping = attr.dbc2vss_entries(self.mapping_tree)
        self.dbc: Dict[str, Any] = {}
        self.hz = rc.hazard_module()
        self.mock_writes = attr.mock_paths(MOCK_FILE.read_text(encoding="utf-8"))
        self.recorded = list(attr.SLOT_PATHS) + ["Vehicle.Speed", HAZARD, attr.WHEELBASE] + list(self.hz.LEAF_PATHS)
        self.witness_paths = sorted(self.mapping)           # every path the CAN provider writes
        self.in_dir = run_dir / "in"

    def prepare(self, pull: bool = True, build: bool = True, bridge_parts: Optional[bool] = None, images: str = "build") -> Dict[str, Any]:
        """Check the recording, pull and build what the run uses, stage the inputs, derive the expectations and write the run
        manifest. bridge_parts (default: build): with a bridge, check its image's labels and build the native vss monitor
        (guest mode: record the guest's component, vss-monitor-guest, and build nothing); Phase 2 step 3's can and replay
        runs (step3.py) take them without pulling or building the stack's own images.
        images (SDV Phase 3 WP1): "build", today's path, or "loaded", where pull and build mean inspecting the upstream images
        pulled before the run and the local images' arm64 pins (loaded_upstream, loaded_local), and the bridge must be its
        arm64 pin; nothing is pulled or built, and a missing image is refused."""
        if images not in IMAGE_MODES:
            raise StackError("--images %r: one of %s" % (images, ", ".join(IMAGE_MODES)))
        loaded = images == "loaded"
        bridge_parts = build if bridge_parts is None else bridge_parts
        if self.connector:
            # refused before anything is pulled or written: an aarch64 host's connector, and a missing device directory
            # (it is checked here and read again at the start; its path is never recorded)
            if loaded:
                raise StackError(CONNECTOR_NOT_LOADED)
            device_dir()
        # the recording, its manifest line and its summary: refused before anything is pulled or written
        rec = recording_identity(RECORDING_DIR)
        line = rec["manifest_line"]
        seed = recording_seed(line, self.cli_seed)
        self.seed = seed
        summ = recording_summary(RECORDING_DIR, line)
        # the provenance, reported as sigsim's is for either kind (module docstring, THE RECORDING)
        provenance = {"sigsim": sigsim_provenance(line)} if rec["run_type"] == "sigsim" else {"carla": carla_provenance(summ["trip"])}
        dbc = resolve_dbc(line["source"]["params"]["dbc_sha256"])
        # the run type's catalogue and vehicle layer (RECORDING KINDS AND RUN TYPES): refused here, before anything is written
        pair = generation_pair(generation_manifest(), rec["run_type"])
        cat = catalogue_identity(self.contract, dbc["wanted_sha256"], pair)
        layer = pair["vehicle_layer"]
        self.run_type, self.log_name, self.catalogue_file = rec["run_type"], rec["log_name"], pair["catalogue"]
        self.catalogue_tree = json.loads((GEN / pair["catalogue"]).read_text(encoding="utf-8"))
        self.catalogue = attr.leaf_nodes(self.catalogue_tree)
        self.wheelbase: Optional[Dict[str, Any]] = None
        if self.bridge == "broker":
            # Spec 5.6, both branches, predicted from the catalogue the stack stages: a served value other than the
            # profile's L is refused before anything starts; none served starts, with the bridge's note recorded.
            prof = {int(p["id"]): p for p in self.contract.PROFILES}.get(line.get("profile_id"))
            self.wheelbase = served_wheelbase(self.catalogue_tree, prof["l_mm"] if prof else None, line["source"]["vehicle"], layer)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if pull:
            self.components.update(loaded_upstream(self.images) if loaded else pull_upstream(self.images))
        if build:
            self.components.update(loaded_local(self.images) if loaded else build_local(self.images))
            rec_img = self.components[attr.RECORDER]
            self.components[WITNESS] = {
                "class": "platform", "form": "container", "image_id": rec_img["image_id"], "runs_in": attr.RECORDER,
                "program": str(WITNESS_FILE.relative_to(REPO)), "program_sha256": sha256_file(WITNESS_FILE),
                "note": "the recorder image (the pinned base, kuksa-client 0.6.0 with the same pinned versions and hashes as the app's "
                        "lock) with --entrypoint python and the program mounted read-only; a reader, not a writer"}
        if bridge_parts and self.bridge != "none":
            self.components[attr.BRIDGE] = bridge_image(self.contract, line["source"]["params"]["dbc_sha256"],
                                                        self.images["bridge"]["arm64"] if loaded else None)
            if self.guest is not None:
                self.components[VSS_MONITOR_GUEST] = guest_component(self.guest)        # nothing to build: the guest's own
            else:
                self.components[VSS_MONITOR] = build_native_monitor(self.run_dir / "bin" / MONITOR_BIN)
        if self.connector:
            self.components[CONNECTOR] = connector_image()
        # stage the exact inputs the containers read
        self.in_dir.mkdir(exist_ok=True)
        # the run type's catalogue under the one name the databroker's argv reads, the log under its own name
        staged = {SIGSIM_CATALOGUE: GEN / pair["catalogue"], "vss-can-mapping.json": GEN / "vss-can-mapping.json",
                  "slice.dbc": Path(dbc["path"]), self.log_name: Path(rec["log"])}
        for dest, src in staged.items():
            shutil.copyfile(src, self.in_dir / dest)
        self.dbc = attr.parse_dbc((self.in_dir / "slice.dbc").read_text(encoding="utf-8"))
        (self.in_dir / "can-provider.ini").write_text(
            "# the CAN provider's configuration file for the slice (written by sdv/stack/stack.py)\n"
            "[general]\ndbc2val = True\nval2dbc = False\n[can]\nj1939 = False\ninfinite = False\n", encoding="ascii")
        self.staged = {k: sha256_file(self.in_dir / k) for k in sorted(os.listdir(self.in_dir))}
        if self.staged[self.log_name] != rec["sha256"]:
            raise StackError("the staged recording differs from the recording")
        # expected values and windows, from the recording directory only (never from running sigsim or the encoder)
        transforms = {p: attr.transform_function(b) for p, b in self.mapping.items()}
        self.decoded = rc.decode_recording(self.in_dir / self.log_name, self.in_dir / "slice.dbc", self.mapping, transforms)
        frame_counts = check_summary_counts(summ["trip"], self.decoded["frames"])
        dyn = self.contract.RULE26_DBC_MESSAGE
        try:
            self.windows = rc.expected_windows(summ["trip"], self.decoded["frames"], self.mapping[rc.V_PATH]["signal"],
                                               int(self.contract.DBC_PERIOD_MS[dyn]))
        except ValueError as exc:         # e.g. the vehicle never moves again after the hard brake
            raise StackError("the windows cannot be derived from summary.json and the decoded recording: %s" % exc) from exc
        self.windows["summary_sha256"] = summ["sha256"]
        self.prediction = rc.predict(self.decoded["frames"], self.mapping[rc.V_PATH]["signal"], self.mapping[rc.A_PATH]["signal"], self.hz)
        pred_ok = (len(self.prediction) == 2 and self.prediction[0]["hazard"] and not self.prediction[1]["hazard"]
                   and rc.in_window(self.prediction[0]["t_rec_ms"], self.windows["on_window_ms"])
                   and rc.in_window(self.prediction[1]["t_rec_ms"], self.windows["off_window_ms"]))
        if not pred_ok:
            raise StackError("the decision function applied to the decoded recording does not switch once inside the "
                             "windows summary.json gives: %s vs %s" % (self.prediction, self.windows))
        # the scenario table and its checks
        self.bridge_writes = bridge_writes(self.contract) if self.bridge == "broker" else []
        self.rows = with_provider_upstream(attr.scenario_rows(self.catalogue, self.mapping, self.dbc, self.mock_writes, attr.APP,
                                                              self.hz.WRITES, list(MONITOR_DISPLAY), self.recorded, seed,
                                                              bridge_writes=self.bridge_writes,
                                                              vehicle_layer=layer["file"] if layer else None), line, seed)
        write_sets: Dict[str, Iterable[str]] = {attr.CAN_PROVIDER: list(self.mapping), attr.MOCK_PROVIDER: self.mock_writes,
                                                attr.APP: list(self.hz.WRITES)}
        if self.bridge_writes:
            write_sets[attr.BRIDGE] = list(self.bridge_writes)
        checks = attr.check_rows(self.rows, self.catalogue, self.mapping, self.dbc, write_sets, attr.APP, bridge_mode=self.bridge)
        line = rec["manifest_line"]
        self.scenario = {
            "format": 1,
            "scenario": line["name"],
            "recording": {"path": line["recording"]["path"], "sha256": "sha256:" + rec["sha256"], "format": line["recording"]["format"]},
            "dbc_sha256": "sha256:" + line["source"]["params"]["dbc_sha256"],
            "source": line["source"],
            "profile_id": line.get("profile_id"),
            "rows": self.rows,
        }
        self.ownership_sha256 = write_json(self.run_dir / "ownership.json", self.scenario)
        wc_note = ("" if dbc["working_copy_sha256"] == dbc["wanted_sha256"] else
                   "; the working copy of slice.dbc (not staged) is %s, same body without comment lines: %s" % (
                       dbc["working_copy_sha256"], dbc.get("working_copy_body_equal")))
        checks.append(("C10-dbc", self.staged["slice.dbc"] == line["source"]["params"]["dbc_sha256"],
                       "the staged slice.dbc is the one the recording was encoded with (%s)%s" % (self.staged["slice.dbc"], wc_note)))
        failed = [c for c in checks if not c[1]]
        self.manifest: Dict[str, Any] = {
            "format": 1,
            "run": self.run_dir.name,
            "utc_prepared": utc_now(),
            "host_role": self.host_role,
            "placement": placement_record(self.cpuset, self.after_start),
            "app": self.app,
            "app_note": APP_NOTES[self.app],
            "stack_files": {str(p.relative_to(REPO)): sha256_file(p) for p in sorted(
                [HERE / "stack.py", HERE / "attribution.py", HERE / "replaycheck.py", HERE / "catalogue_probe.py", HERE / "bundle.py",
                 AGEPROBE_FILE, MOCK_FILE, IMAGES_FILE, WITNESS_FILE, DBC_SOURCES_FILE, APP_DIR / "hazard.py", APP_DIR / "app.py",
                 APP_DIR / "Dockerfile",
                 APP_DIR / "requirements.lock", HERE / "recorder" / "Dockerfile", HERE / "recorder" / "requirements.lock"])},
            "bridge": {"mode": self.bridge, "writes": list(self.bridge_writes), "wheelbase": self.wheelbase, "monitor": self.monitor_mode,
                       "note": BRIDGE_NOTES_GUEST[self.bridge] if self.guest is not None else BRIDGE_NOTES[self.bridge]},
            "docker": {"server": docker("version", "-f", "{{.Server.Version}}").stdout.strip(),
                       "storage": docker("info", "-f", "{{.Driver}} {{json .DriverStatus}}").stdout.strip(),
                       "image_id_note": "under the containerd image store a pulled image's ID is its index digest",
                       "images": images,
                       "images_note": LOADED_NOTE if loaded else "--images build: the upstream images pulled by index digest and "
                                                                 "the local images built here (the host's architecture)"},
            "components": self.components,
            "catalogue": cat,
            "recording": dict({
                "dir": rec["dir"], "sha256": rec["sha256"], "manifest_line": line,
                "manifest_line_sha256": rec["manifest_line_sha256"],
                "seed": seed, "seed_from": "the manifest line (source.params.seed)", "cli_seed": self.cli_seed,
                "summary": {"path": summ["path"], "sha256": summ["sha256"], "hard_brake_ms": summ["hard_brake_ms"],
                            "frames_per_message": frame_counts},
            }, **provenance),
            "dbc": dbc,
            "staged_inputs_sha256": self.staged,
            "expected": {"windows": self.windows, "windows_from": "summary.json %s (trip.segments) and the decoded recording" % summ["sha256"],
                         "prediction": self.prediction,
                         "counts": {p: len(v) for p, v in self.decoded["values"].items()}, "half_lsb": self.decoded["half_lsb"]},
            "scenario_table": {"file": "ownership.json", "sha256": "sha256:" + self.ownership_sha256,
                               "note": "the design keeps it beside the recording; written here so the recording directory stays untouched"},
            "scenario_checks": [list(c) for c in checks],
            "time_sync": dict(time_sync(), age_clock=age_clock(self.bridge)),
        }
        if self.connector:
            self.manifest["twin"] = {
                "connector": True, "allowlist_version": attr.ALLOWLIST_VERSION, "start_spacing_s": connector_part("limits").START_SPACING_S,
                "mounts": dict(CONNECTOR_MOUNTS),
                "spool_status": ("the host's: %s and %s, mounted at the connector's spool and status paths (their paths are recorded "
                                 "nowhere here)" % (SPOOL_DIR_ENV, STATUS_DIR_ENV) if self.host_dirs is not None else
                                 "the replay's own spool/ and status/, made in each replay directory"),
                "note": "the twin connector runs in this run's replays (vcan feed): a reader of the databroker with an uplink out of "
                        "the host. Its endpoint, its thing's and rule's names and its device directory are read from the "
                        "environment at the start and are recorded nowhere in this directory; what reached the far end is the far "
                        "end's to say"}
        write_json(self.run_dir / "manifest.json", self.manifest)
        if failed:
            raise StackError("scenario table checks failed: %s" % failed)
        return self.manifest

    def image_ids(self) -> Dict[str, str]:
        """The containers' image IDs (the native vss monitor is a host binary: its sha256 is in its component)."""
        return {k: v["image_id"] for k, v in self.components.items() if "image_id" in v}

    def run_header(self, replay_id: str, feed: str) -> Dict[str, Any]:
        """The run header (attribution-table 3.1). With a bridge: bridge_mode, the scenario entry's profile_id
        (profile_source scenario: a recorded feed), the generated AGE_MAX, no demo-ODD window, and time_sync's
        age_clock the bridge mode's; without one, all four null. run_type is the recording's (its line's generator), and
        source_rtf the line's source.rtf for a CARLA recording, null for sigsim (module docstring, RECORDING KINDS AND
        RUN TYPES; C12a holds it to the scenario entry's)."""
        line = self.scenario
        bridge = self.bridge != "none"
        rtf = line["source"].get("rtf") if self.run_type != "sigsim" else None
        return {
            "run_id": "%sT-%s-vss-%s-%s" % (self.run_dir.name[:8], self.host_role, line["scenario"], replay_id),
            "utc_start": utc_now(),
            "host_role": self.host_role,
            "run_type": self.run_type,
            "feed": "recording",
            "bridge_mode": self.bridge,
            "profile_id": line["profile_id"] if bridge else None,
            "profile_source": "scenario" if bridge else None,
            "source_vehicle": dict(line["source"]["vehicle"]),
            "age_max_ms": int(self.contract.AGE_MAX_MS) if bridge else None,
            "demo_odd_window": None,
            "time_sync": dict(self.manifest["time_sync"]),
            "source_rtf": dict(rtf) if isinstance(rtf, dict) else None,
            "catalogue": self.manifest["catalogue"],
            "scenario": {"name": line["scenario"], "ownership_sha256": "sha256:" + self.ownership_sha256},
            "recordings": [{"role": "candump", "path": line["recording"]["path"], "sha256": line["recording"]["sha256"]}],
            "dbc_sha256": line["dbc_sha256"],
            "allowlist_version": attr.ALLOWLIST_VERSION,
            "header_check": None,
        }

    def check_header(self, header: Dict[str, Any]) -> attr.Check:
        """C12a on this run's header, against the generated table, the scenario entry and the bridge mode's clock."""
        c = self.contract
        return attr.check_header(header, {int(p["id"]): p for p in c.PROFILES}, int(c.AGE_MAX_MS),
                                 scenario_profile_id=self.scenario.get("profile_id"),
                                 live_defaults=dict(getattr(c, "LIVE_DEFAULT_PROFILE", {})),
                                 compiled=tuple(getattr(c, "COMPILED_PROFILE_IDS", ())) if self.bridge != "none" else None,
                                 age_clock=age_clock(self.bridge), scenario_source_rtf=self.scenario["source"].get("rtf"))


class LiveContext(Context):
    """A live run's context (module docstring, LIVE): no recording. The run type is carla, the profile the carla live default
    (profile_source live-default), the source vehicle the take's blueprint at that profile's L; the generation's carla pair is
    staged as a carla recording's is, with the generation's own slice.dbc input, which the feeder encodes with."""

    def __init__(self, run_dir: Path, bridge: str, feeder_out: Path) -> None:
        if bridge not in LIVE_BRIDGE_MODES:
            raise StackError("live --bridge %r: one of %s" % (bridge, ", ".join(LIVE_BRIDGE_MODES)))
        super().__init__(run_dir, None, bridge)
        self.feeder_out = Path(feeder_out)
        self.run_type = LIVE_RUN_TYPE

    def live_vehicle(self) -> Tuple[int, Dict[str, Any]]:
        """The carla live-default profile and the source vehicle at its L, refused unless the generation compiles it."""
        c = self.contract
        pid = int(c.LIVE_DEFAULT_PROFILE[LIVE_RUN_TYPE])
        prof = {int(p["id"]): p for p in c.PROFILES}.get(pid)
        if prof is None or pid not in tuple(c.COMPILED_PROFILE_IDS):
            raise StackError("profile %d (the carla live default) is not compiled in this generation: the bridge and the guest would "
                             "refuse every frame (regenerate with sdv/vss/generate.py)" % pid)
        return pid, {"name": LIVE_SOURCE_VEHICLE, "wheelbase_mm": int(prof["l_mm"])}

    def prepare(self, pull: bool = True, build: bool = True, bridge_parts: Optional[bool] = None, images: str = "build") -> Dict[str, Any]:
        """Pull and build what the run uses, stage the inputs, write the scenario table and the run manifest; every refusal
        (another images mode, a generation without the carla pair or the profile, a missing DBC) before anything is written."""
        if images != "build":
            raise StackError("live runs on the PC only (--images build): the hosts replay recordings")
        bridge_parts = build if bridge_parts is None else bridge_parts
        c = self.contract
        man = generation_manifest()
        pair = generation_pair(man, LIVE_RUN_TYPE)
        pid, vehicle = self.live_vehicle()
        dbc_sha = (man.get("inputs") or {}).get("slice.dbc")
        if not isinstance(dbc_sha, str):
            raise StackError("sdv-out/gen's manifest.json names no slice.dbc input (regenerate with sdv/vss/generate.py)")
        dbc = resolve_dbc(dbc_sha)
        cat = catalogue_identity(c, dbc_sha, pair)
        layer = pair["vehicle_layer"]
        self.catalogue_file = pair["catalogue"]
        self.catalogue_tree = json.loads((GEN / pair["catalogue"]).read_text(encoding="utf-8"))
        self.catalogue = attr.leaf_nodes(self.catalogue_tree)
        self.wheelbase = served_wheelbase(self.catalogue_tree, vehicle["wheelbase_mm"], vehicle, layer) if self.bridge == "broker" else None
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if pull:
            self.components.update(pull_upstream(self.images))
        if build:
            self.components.update(build_local(self.images))
            rec_img = self.components[attr.RECORDER]
            self.components[WITNESS] = {
                "class": "platform", "form": "container", "image_id": rec_img["image_id"], "runs_in": attr.RECORDER,
                "program": str(WITNESS_FILE.relative_to(REPO)), "program_sha256": sha256_file(WITNESS_FILE),
                "note": "the recorder image (the pinned base, kuksa-client 0.6.0 with the same pinned versions and hashes as the app's "
                        "lock) with --entrypoint python and the program mounted read-only; a reader, not a writer"}
        if bridge_parts:
            self.components[attr.BRIDGE] = bridge_image(c, dbc_sha)
            self.components[VSS_MONITOR] = build_native_monitor(self.run_dir / "bin" / MONITOR_BIN)
        self.in_dir.mkdir(exist_ok=True)
        staged = {SIGSIM_CATALOGUE: GEN / pair["catalogue"], "vss-can-mapping.json": GEN / "vss-can-mapping.json",
                  "slice.dbc": Path(dbc["path"])}
        for dest, src in staged.items():
            shutil.copyfile(src, self.in_dir / dest)
        self.dbc = attr.parse_dbc((self.in_dir / "slice.dbc").read_text(encoding="utf-8"))
        (self.in_dir / "can-provider.ini").write_text(
            "# the CAN provider's configuration file for the slice (written by sdv/stack/stack.py)\n"
            "[general]\ndbc2val = True\nval2dbc = False\n[can]\nj1939 = False\ninfinite = False\n", encoding="ascii")
        self.staged = {k: sha256_file(self.in_dir / k) for k in sorted(os.listdir(self.in_dir))}
        self.bridge_writes = bridge_writes(c) if self.bridge == "broker" else []
        rows = attr.scenario_rows(self.catalogue, self.mapping, self.dbc, self.mock_writes, attr.APP, self.hz.WRITES, list(MONITOR_DISPLAY),
                                  self.recorded, 0, bridge_writes=self.bridge_writes, vehicle_layer=layer["file"] if layer else None)
        self.rows = [dict(r, upstream=LIVE_UPSTREAM) if r["writer"] == attr.CAN_PROVIDER else r for r in rows]
        write_sets: Dict[str, Iterable[str]] = {attr.CAN_PROVIDER: list(self.mapping), attr.MOCK_PROVIDER: self.mock_writes,
                                                attr.APP: list(self.hz.WRITES)}
        if self.bridge_writes:
            write_sets[attr.BRIDGE] = list(self.bridge_writes)
        checks = attr.check_rows(self.rows, self.catalogue, self.mapping, self.dbc, write_sets, attr.APP, bridge_mode=self.bridge)
        checks.append(("C10-dbc", self.staged["slice.dbc"] == dbc_sha,
                       "the staged slice.dbc is the generation's own input (%s), the one the feeder encodes with" % self.staged["slice.dbc"]))
        failed = [ch for ch in checks if not ch[1]]
        self.scenario = {"format": 1, "scenario": LIVE_SCENARIO, "recording": None, "feed": LIVE_FEED, "dbc_sha256": "sha256:" + dbc_sha,
                         "source": {"generator": LIVE_RUN_TYPE, "feed": LIVE_FEED, "feeder": "sdv/feeder/live.py", "vehicle": vehicle},
                         "profile_id": pid, "rows": self.rows}
        self.ownership_sha256 = write_json(self.run_dir / "ownership.json", self.scenario)
        self.manifest = {
            "format": 1, "run": self.run_dir.name, "utc_prepared": utc_now(), "host_role": self.host_role,
            "placement": placement_record(self.cpuset, self.after_start), "app": self.app, "app_note": APP_NOTES[self.app],
            "stack_files": {str(p.relative_to(REPO)): sha256_file(p) for p in sorted(
                [HERE / "stack.py", HERE / "attribution.py", HERE / "replaycheck.py", HERE / "bundle.py", MOCK_FILE, IMAGES_FILE, WITNESS_FILE,
                 DBC_SOURCES_FILE, APP_DIR / "hazard.py", APP_DIR / "app.py", APP_DIR / "Dockerfile", APP_DIR / "requirements.lock",
                 HERE / "recorder" / "Dockerfile", HERE / "recorder" / "requirements.lock", REPO / "sdv" / "feeder" / "live.py"])},
            "bridge": {"mode": self.bridge, "writes": list(self.bridge_writes), "wheelbase": self.wheelbase, "monitor": self.monitor_mode,
                       "note": "%s; the feed is live (sdv/feeder/live.py on vcan0), nothing is replayed" % BRIDGE_NOTES[self.bridge]},
            "docker": {"server": docker("version", "-f", "{{.Server.Version}}").stdout.strip(),
                       "storage": docker("info", "-f", "{{.Driver}} {{json .DriverStatus}}").stdout.strip(),
                       "image_id_note": "under the containerd image store a pulled image's ID is its index digest", "images": images,
                       "images_note": "--images build: the upstream images pulled by index digest and the local images built here"},
            "components": self.components,
            "catalogue": cat,
            "recording": None,
            "live": {"feed": LIVE_FEED, "run_type": LIVE_RUN_TYPE, "profile_id": pid, "profile_source": "live-default",
                     "source_vehicle": vehicle, "feeder_out": str(self.feeder_out), "take_wait_s": LIVE_TAKE_WAIT_S,
                     "note": "sdv/feeder/live.py run --out <feeder_out> drives CARLA from WSL and sends each step onto vcan0; the "
                             "stack plays no recording and waits for the take's capture.json"},
            "dbc": dbc,
            "staged_inputs_sha256": self.staged,
            "scenario_table": {"file": "ownership.json", "sha256": "sha256:" + self.ownership_sha256,
                               "note": "the live run's table: the CAN provider's upstream is the live feeder"},
            "scenario_checks": [list(ch) for ch in checks],
            "time_sync": dict(time_sync(), age_clock=age_clock(self.bridge)),
        }
        write_json(self.run_dir / "manifest.json", self.manifest)
        if failed:
            raise StackError("scenario table checks failed: %s" % failed)
        return self.manifest

    def run_header(self, replay_id: str, feed: str) -> Dict[str, Any]:
        """The live run's header (module docstring, LIVE): run_type carla, feed live, profile_source live-default, no recording,
        source_rtf null until record close (live_close fills it from the take, C12b)."""
        sc = self.scenario
        return {
            "run_id": "%sT-%s-vss-%s-%s" % (self.run_dir.name[:8], self.host_role, sc["scenario"], replay_id),
            "utc_start": utc_now(),
            "host_role": self.host_role,
            "run_type": LIVE_RUN_TYPE,
            "feed": LIVE_FEED,
            "bridge_mode": self.bridge,
            "profile_id": sc["profile_id"],
            "profile_source": "live-default",
            "source_vehicle": dict(sc["source"]["vehicle"]),
            "age_max_ms": int(self.contract.AGE_MAX_MS),
            "demo_odd_window": None,
            "time_sync": dict(self.manifest["time_sync"]),
            "source_rtf": None,
            "catalogue": self.manifest["catalogue"],
            "scenario": {"name": sc["scenario"], "ownership_sha256": "sha256:" + self.ownership_sha256},
            "recordings": [],
            "dbc_sha256": sc["dbc_sha256"],
            "allowlist_version": attr.ALLOWLIST_VERSION,
            "header_check": None,
        }


# --- one stack ----------------------------------------------------------------------------------

def remove_stack() -> None:
    ids = docker("ps", "-aq", "--filter", "label=" + LABEL).stdout.split()
    if ids:
        docker("rm", "-f", *ids, timeout=120)


def stop_bridge_and_witness(runs: Sequence[Path]) -> None:
    """down's stop for the ros runs it found (ros_runs_left), before remove_stack's `docker rm -f` (WP3d's down-path fix):
    each run's claim bridge and then its witness, each only while it runs with that run's own label (sdv.stack.run=<the
    run directory's name>/up, which ros_main's up gives every container of the run), get `docker stop -t 10` with
    check=False. The bridge first, as the replay and live paths stop it before stop_containers' witness: SIGTERM, so the
    bridge drains and writes its stop event and summary.json while its monitor still runs (a native one, which down stops
    only after the sweep, or the guest's), and the witness's stop record then comes after the bridge's last write-back; a
    kill writes neither. One listing per run first, so a container that is not there (a --bridge none run's bridge, both
    of a run another start swept) or that is another start's (its witness carries its own run's label) gets no stop call;
    a listing docker cannot give stops nothing, and remove_stack's own then fails as it did."""
    for run_dir in runs:
        p = docker("ps", "--filter", "label=%s=%s/up" % (LABEL, run_dir.name), "--format", "{{.Names}}", check=False)
        running = set((p.stdout or "").split()) if p.returncode == 0 else set()
        for name in (BRIDGE_CONTAINER, NAMES[WITNESS]):
            if name in running:
                docker("stop", "-t", "10", name, check=False)


def net_of(feed: str, component: str) -> List[str]:
    """A container's network. The bridge always takes the host's namespace, where the native monitor's :7160 is (and
    br0 to the guest's in guest mode, vcan0, and the databroker's 127.0.0.1 over the vcan feed); never the dumpfile
    feed's, which has loopback only.
    feed "none": no CAN feed at all (the replay-mode bridge reads the recording itself; step3.py).
    The connector takes the host's namespace too, and only over the vcan feed: the dumpfile feed's namespace has no way
    out, and a run with no feed has no databroker to read."""
    if component == CONNECTOR:
        if feed != "vcan":
            raise StackError(CONNECTOR_NEEDS_VCAN)
        return ["--network", "host"]
    if component == attr.BRIDGE:
        if feed == "dumpfile":
            raise StackError(BROKER_NEEDS_VCAN)
        return ["--network", "host"]
    if feed in ("vcan", ROS_FEED):          # the ros feed: the feeder's DDS on lo and the databroker's 127.0.0.1, one namespace
        return ["--network", "host"]
    if component == attr.DATABROKER:
        return ["--network", "none"]
    return ["--network", "container:" + NAMES[attr.DATABROKER]]


class NativeMonitor:
    """The native vss monitor as a host process, `<bin> 7160 svc 500`: monitor.c's vss build, binding INADDR_ANY
    as the guest's does (never changed). Its stdout and stderr are the run's console capture (monitor.log), from
    which C12b reads the `vss rules:` line."""

    def __init__(self, binary: Path, log: Path, port: int = MONITOR_PORT, deadline_ms: int = MONITOR_DEADLINE_MS) -> None:
        self.log = log
        self.port = port
        self.argv = [str(binary), str(port), "svc", str(deadline_ms)]
        self._f = open(log, "w", encoding="utf-8")
        self.proc = subprocess.Popen(self.argv, stdout=self._f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        self.pid = self.proc.pid
        self.exit_code: Optional[int] = None

    def text(self) -> str:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def wait_listening(self, timeout: float) -> None:
        banner = "service monitor listening on :%d " % self.port

        def up() -> bool:
            if self.proc.poll() is not None:
                raise StackError("the native vss monitor exited %s before it listened:\n%s" % (self.proc.returncode, self.text()[-1500:]))
            return banner in self.text()
        wait_for(up, timeout, "the native vss monitor's svc banner on :%d" % self.port)

    def allowance(self) -> Dict[str, Any]:
        """Its listener, allowed by PID (listener_verdict)."""
        return {"pid": self.pid, "proto": "tcp", "port": self.port,
                "why": "the native vss monitor binds INADDR_ANY as the guest's does (monitor.c svc); its bind is never changed"}

    def stop(self) -> Optional[int]:
        if self.proc.poll() is None:
            self.proc.terminate()                  # SIGTERM: monitor.c's handler stops the loop, it prints `stopped`
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self._f.close()
        self.exit_code = self.proc.returncode
        return self.exit_code


def start(ctx: Context, component: str, feed: str, replay_dir: Path, run_label: str) -> str:
    name = CONTAINERS[component]
    ids = ctx.image_ids()
    base = ["run", "-d", "--name", name, "--label", "%s=%s" % (LABEL, run_label)] + common_flags(ctx) + net_of(feed, component)
    uid = "%d:%d" % (os.getuid(), os.getgid())
    if component == attr.DATABROKER:
        args = base + ["--read-only", "-e", "KUKSA_DATABROKER_ADDR=" + BROKER_HOST, "-v", "%s:/in:ro" % ctx.in_dir,
                       upstream_ref(ctx.images, component), "--vss", "/in/vss-databroker.json",
                       "--address", BROKER_HOST, "--port", str(BROKER_PORT), "--insecure"]
    elif component == attr.MOCK_PROVIDER:
        args = base + ["-e", "VDB_ADDRESS=" + BROKER, "-e", "MOCK_ADDR=%s:50053" % BROKER_HOST,
                       "-v", "%s:/mock/mock.py:ro" % MOCK_FILE, upstream_ref(ctx.images, component)]
    elif component == attr.RECORDER:
        args = base + ["--read-only", "--user", uid, "-v", "%s:/out" % replay_dir, ids[component],
                       "-a", BROKER_HOST, "-p", str(BROKER_PORT), "-f", "/out/vss-recorder.csv", "-l", "INFO", "-s"] + ctx.recorded
    elif component == WITNESS:
        args = base + ["--read-only", "--user", uid, "-v", "%s:/out" % replay_dir, "-v", "%s:/witness.py:ro" % WITNESS_FILE,
                       "--entrypoint", "python", ids[attr.RECORDER], "/witness.py", BROKER, "/out/" + WITNESS_LOG] + list(ctx.witness_paths)
    elif component == attr.APP:
        # IMAGE IDS: run by its store ID, APP_IMAGE_ID its config digest (Phase 6 spec 2.1; the one argument Phase 6 changed)
        args = base + ["--read-only", "--user", uid, "-v", "%s:/out" % replay_dir, "-e", "APP_IMAGE_ID=" + app_config_digest(ctx),
                       "-e", "KUKSA_ADDRESS=" + BROKER, "-e", "HBH_LOG=/out/hard-brake-hazard.jsonl", ids[component]]
    elif component == attr.CAN_PROVIDER:
        feed_args = (["--dumpfile", "/in/" + log_of(ctx), "--canport", VCAN] if feed == "dumpfile"
                     else ["--use-socketcan", "--canport", VCAN])
        args = base + ["--read-only", "--tmpfs", "/tmp:rw,exec,size=256m", "-v", "%s:/in:ro" % ctx.in_dir, upstream_ref(ctx.images, component),
                       "grpc://" + BROKER, "--config", "/in/can-provider.ini", "--dbcfile", "/in/slice.dbc",
                       "--mapping", "/in/vss-can-mapping.json", "--dbc2val", "--no-val2dbc", "--no-infinite"] + feed_args
    elif component == attr.BRIDGE:
        # sdv/bridge/Dockerfile's way: the run's lock file bind-mounted at the designated path with --mount (a missing
        # source is refused, never made a directory), the container as the host user so the flock is the file's,
        # a read-only root with the run's bridge directory as --out, the run header as its configuration. The host's
        # namespace reaches the native monitor's :7160 (or the guest's over br0: --host is monitor_host's), the
        # databroker on 127.0.0.1 (broker, over the vcan feed) and vcan0 (can). can and replay read the staged inputs
        # (the recording's slice.dbc, and in replay its staged log) mounted read-only; a run's script (step3.py, WP10), when
        # the replay directory holds one, likewise.
        out, lock, hdr = replay_dir / "bridge", replay_dir / "scenario.lock", replay_dir / "bridge-header.json"
        script = replay_dir / BRIDGE_SCRIPT
        if not (lock.is_file() and hdr.is_file() and out.is_dir()):
            raise StackError("the bridge needs %s, %s and %s before it starts" % (lock, hdr, out))
        mode = ctx.bridge
        mounts = ["--mount", "type=bind,src=%s,dst=%s" % (lock, LOCK_IN_CONTAINER), "-v", "%s:/out" % out, "-v", "%s:/header.json:ro" % hdr]
        if mode in ("can", "replay"):
            mounts += ["-v", "%s:/in:ro" % ctx.in_dir]
        if script.is_file():
            mounts += ["-v", "%s:/script.json:ro" % script]
        by_mode = {"broker": ["--broker", BROKER], "can": ["--channel", VCAN, "--dbc", "/in/slice.dbc"],
                   "replay": ["--log", "/in/" + log_of(ctx), "--dbc", "/in/slice.dbc"]}
        if mode not in by_mode:
            raise StackError("bridge mode %r has no container arguments" % (mode,))
        args = base + ["--read-only", "--user", uid] + mounts + [ids[component], "run", "--host", monitor_host(ctx), "--port", str(MONITOR_PORT),
                                                                 "--header", "/header.json"] + by_mode[mode] + ["--out", "/out"]
        if script.is_file():
            args += ["--script", "/script.json"]
    elif component == CONNECTOR:
        # Three mounts and no other (manifest-classes.md sections 5 to 7), each with --mount, which refuses a missing
        # source where -v would make a directory: the spool (read-write: the spool record and the connector's own start
        # stamp), the status (read-only: the updater's record), the device directory (read-only). The spool and the
        # status are the replay's own directories, or the host's (HOST SPOOL AND STATUS: SDV_SPOOL_DIR, SDV_STATUS_DIR) at
        # the same container paths. The endpoint and the thing's and the rule's names come in through --env-file from the
        # device directory, so none of them is on this argument vector; the databroker's address, the spool's and the
        # status's paths are the image's defaults. A read-only root, the host user (never root: the key is the host
        # user's file), restart policy no (a refused or failed start is not tried again by docker), and no argument: the
        # image's own entry point.
        host_dirs = getattr(ctx, "host_dirs", None)
        spool, status = host_dirs if host_dirs is not None else (replay_dir / "spool", replay_dir / "status")
        if not (spool.is_dir() and status.is_dir()):
            where = ("%s and %s" % (SPOOL_DIR_ENV, STATUS_DIR_ENV)) if host_dirs is not None else ("%s and %s" % (spool, status))
            raise StackError("the connector needs %s before it starts" % where)          # the host's paths are never printed
        if os.getuid() == 0:
            raise StackError("the connector is never run as root: start the stack as the user the device directory belongs to")
        device = device_dir()
        args = base + ["--read-only", "--user", uid, "--restart", "no",
                       "--mount", "type=bind,src=%s,dst=%s" % (spool, CONNECTOR_MOUNTS["spool"]),
                       "--mount", "type=bind,src=%s,dst=%s,readonly" % (status, CONNECTOR_MOUNTS["status"]),
                       "--mount", "type=bind,src=%s,dst=%s,readonly" % (device, CONNECTOR_MOUNTS["device"]),
                       "--env-file", str(device / CONNECTOR_ENV_FILE), ids[component]]
    else:
        raise StackError("unknown component %s" % component)
    docker(*args)
    run_after_start(ctx, name)          # PLACEMENT: after the start, never before it, and only once it succeeded
    return name


def csv_rows(replay_dir: Path) -> List[Dict[str, Any]]:
    path = replay_dir / "vss-recorder.csv"
    if not path.exists():
        return []
    try:
        return rc.read_recorder_csv(path)
    except (ValueError, KeyError):
        return []          # a line being written


def ensure_vcan() -> Dict[str, Any]:
    if run(["ip", "link", "show", VCAN], check=False).returncode == 0:
        return {"created": False}
    run(["sudo", "-n", "modprobe", "vcan"])
    run(["sudo", "-n", "ip", "link", "add", "dev", VCAN, "type", "vcan"])
    run(["sudo", "-n", "ip", "link", "set", "up", VCAN])
    return {"created": True, "how": "sudo -n modprobe vcan; ip link add dev vcan0 type vcan; ip link set up vcan0"}


class VcanCapture:
    """Receive every frame on vcan0 while the player plays (python-can, the sim venv), with its SocketCAN receive time
    (CLOCK_REALTIME on this kernel, as the bridge's can source reads it): the first frame's is a can or broker run's
    origin for its events' windows (Phase 2 WP10, step3.py; reasonsets.py)."""

    def __init__(self) -> None:
        import can  # type: ignore[import-not-found]
        self.bus = can.Bus(interface="socketcan", channel=VCAN)
        self.frames: List[Tuple[int, bytes]] = []
        self.times_ns: List[int] = []
        self.first = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop.is_set():
            m = self.bus.recv(timeout=0.2)
            if m is not None:
                self.times_ns.append(int(round(m.timestamp * 1_000_000)) * 1000)      # its microseconds, as bridge_sources.us_to_ns
                self.frames.append((m.arbitration_id, bytes(m.data)))
                self.first.set()

    def close(self) -> List[Tuple[int, bytes]]:
        self.stop.set()
        self.thread.join(timeout=5)
        self.bus.shutdown()
        return self.frames


def log_frames(path: Path) -> List[Tuple[int, bytes]]:
    import can  # type: ignore[import-not-found]
    return [(m.arbitration_id, bytes(m.data)) for m in can.LogReader(str(path))]


def up(ctx: Context, feed: str, replay_dir: Path, run_label: str, header: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Start the stack without its feed and wait until each component is serving. With a bridge (vcan only): the
    native vss monitor right after the first listener snapshot (in guest mode none: the guest's runs already, and
    nothing is allowed), and the bridge, configured by `header`, after the app; ctx.monitor holds the monitor until
    the replay stops it. With a connector (vcan only, never beside the guest monitor mode, never inside the start
    spacing: connector_checks, before anything is started or made): the twin connector after the app and the bridge,
    before the listener snapshot, which then covers it. With an external app (APP; vcan only, refused before anything is
    started or made): every container but the app, and nothing waits for the app."""
    if ctx.bridge != "none" and feed != "vcan":
        raise StackError(BROKER_NEEDS_VCAN)
    external = app_mode(ctx) == "external"
    if external and feed != "vcan":
        raise StackError(APP_EXTERNAL_NEEDS_VCAN)
    if has_connector(ctx):
        connector_checks(ctx, feed)
    replay_dir.mkdir(parents=True, exist_ok=True)
    remove_stack()
    info: Dict[str, Any] = {"feed": feed, "listeners_before": host_listeners()}
    if feed == "vcan":
        info["vcan"] = ensure_vcan()
    if ctx.bridge != "none":
        if header is None:
            raise StackError("a bridge run needs its run header")
        if monitor_mode(ctx) == "guest":
            info["monitor"] = guest_info(ctx)
        else:
            start_monitor(ctx, replay_dir, info)
    start(ctx, attr.DATABROKER, feed, replay_dir, run_label)
    wait_log(NAMES[attr.DATABROKER], r"Listening on 127\.0\.0\.1:%d" % BROKER_PORT, START_TIMEOUT_S)
    start(ctx, attr.MOCK_PROVIDER, feed, replay_dir, run_label)
    wait_log(NAMES[attr.MOCK_PROVIDER], r"Feeding 'Vehicle\.Body\.Lights\.Hazard\.IsSignaling' with value False", START_TIMEOUT_S)
    start(ctx, attr.RECORDER, feed, replay_dir, run_label)

    def recorder_ready() -> bool:
        rows = csv_rows(replay_dir)
        return bool(rc.series(rows, HAZARD)) and bool(rc.series(rows, attr.WHEELBASE))
    wait_for(recorder_ready, START_TIMEOUT_S, "the recorder's first rows (the hazard light's initial value, the wheelbase)")
    start(ctx, WITNESS, feed, replay_dir, run_label)
    wlog = replay_dir / WITNESS_LOG

    def witness_ready() -> bool:
        st = docker("inspect", "-f", "{{.State.Running}}", NAMES[WITNESS], check=False)
        if st.stdout.strip() != "true":
            raise StackError("the witness stopped before it subscribed:\n%s" % container_logs(NAMES[WITNESS])[-1500:])
        return wlog.exists() and any(r.get("event") == "subscribed" for r in rc.read_witness(wlog, strict=False)["records"])
    wait_for(witness_ready, START_TIMEOUT_S, "the witness's subscription")
    if not external:
        start(ctx, attr.APP, feed, replay_dir, run_label)
        log = replay_dir / "hard-brake-hazard.jsonl"

        def app_ready() -> bool:
            if not log.exists():
                return False
            recs = rc.read_jsonl(log)
            return any(r.get("event") == "subscribed" for r in recs) and bool(rc.series(csv_rows(replay_dir), ctx.hz.LEAF_PATHS[4]))
        wait_for(app_ready, START_TIMEOUT_S, "the app's subscription and its first heartbeat in the recorder")
    if ctx.bridge != "none":
        assert header is not None
        start_bridge(ctx, feed, replay_dir, run_label, header)
    if has_connector(ctx):
        start_connector(ctx, feed, replay_dir, run_label)
    listeners_now(info, feed, "", allowances(ctx))
    return info


def start_monitor(ctx: Context, replay_dir: Path, info: Dict[str, Any]) -> None:
    """The native vss monitor prepare built (its sha256 checked again), `<bin> 7160 svc 500`, its console capture the replay
    directory's monitor.log; ctx.monitor holds it until the replay stops it."""
    binary = Path(ctx.components[VSS_MONITOR]["path"])
    if sha256_file(binary) != ctx.components[VSS_MONITOR]["sha256"]:
        raise StackError("%s is not the binary prepare built" % binary)
    ctx.monitor = NativeMonitor(binary, replay_dir / "monitor.log")
    ctx.monitor.wait_listening(START_TIMEOUT_S)
    info["monitor"] = {"pid": ctx.monitor.pid, "argv": [binary.name] + ctx.monitor.argv[1:]}


def start_bridge(ctx: Context, feed: str, replay_dir: Path, run_label: str, header: Dict[str, Any]) -> None:
    """The bridge container in ctx.bridge's mode, configured by the run header (bridge-header.json), holding the replay's own
    scenario.lock, writing into bridge/; started once its start record is logged (its start checks passed). Refused while
    the twin-control marker exists (TWIN CONTROL), before anything is made: the last moment before a bridge container, so a
    marker set after a run's context was made still keeps the bridge from starting."""
    refuse_twin_control()
    (replay_dir / "bridge").mkdir(exist_ok=True)
    (replay_dir / "scenario.lock").touch()
    write_json(replay_dir / "bridge-header.json", header)
    start(ctx, attr.BRIDGE, feed, replay_dir, run_label)
    blog = replay_dir / "bridge" / "bridge.jsonl"

    def bridge_started() -> bool:
        st = docker("inspect", "-f", "{{.State.Running}}", BRIDGE_CONTAINER, check=False)
        if st.stdout.strip() != "true":
            raise StackError("the bridge stopped before it started (its start checks refuse with exit 2):\n%s"
                             % container_logs(BRIDGE_CONTAINER)[-1500:])
        return any(r.get("event") == "start" for r in jsonl_records(blog))
    wait_for(bridge_started, START_TIMEOUT_S, "the bridge's start record (its start checks passed)")


def start_connector(ctx: Context, feed: str, replay_dir: Path, run_label: str) -> None:
    """The twin connector's container on the replay's own spool/ and status/ directories (made here), or the host's
    (HOST SPOOL AND STATUS: never made, and refused when either is gone), and the device directory. First the stack's start
    stamp, which refuses a start inside the start spacing (nothing is made or started then); then the container; it counts
    as started once its log holds its start line. One that ended before that is an error here, named by its exit status,
    and the feed is not started."""
    host_dirs = getattr(ctx, "host_dirs", None)
    if host_dirs is not None and not all(d.is_dir() for d in host_dirs):
        raise StackError("the connector needs the host's spool and status directories (%s, %s), and the stack never makes them"
                         % (SPOOL_DIR_ENV, STATUS_DIR_ENV))
    mark_connector_start()
    if host_dirs is None:
        (replay_dir / "spool").mkdir(exist_ok=True)
        (replay_dir / "status").mkdir(exist_ok=True)
    start(ctx, CONNECTOR, feed, replay_dir, run_label)

    def started() -> bool:
        st = docker("inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", CONNECTOR_CONTAINER, check=False).stdout.split()
        if '"event":"start"' in container_logs(CONNECTOR_CONTAINER):
            return True
        if st[:1] != ["true"]:
            code = int(st[1]) if len(st) > 1 and st[1].lstrip("-").isdigit() else None
            raise StackError("the connector stopped before its start line: exit %s (%s)" % (code, CONNECTOR_EXITS.get(code, "unknown")))
        return False
    wait_for(started, START_TIMEOUT_S, "the connector's start line")


def connector_result(replay_dir: Path, states: Dict[str, str]) -> Dict[str, Any]:
    """A replay's record of its connector, from what the stack collected: the container's last state and its log (JSON
    lines after dockerd's time stamp). ok: it exited 0 after its stop, its log's first record is its start line and its
    last its stop line, so its last flush ran to its end. Its counters are copied; they are counts of what it tried and
    what its uplink took, never of what a far end received. `uplink` is the uplink's own (connections opened, lost and
    given up or found without life; resumed_by_sdk counts an SDK that came back by itself, which the connector's
    uplink_aws.py says it does with nothing to send). The log holds no endpoint, name, topic or path (its tests)."""
    state = (states.get(CONNECTOR) or "").split()
    code = int(state[1]) if len(state) > 1 and state[1].lstrip("-").isdigit() else None
    records: List[Dict[str, Any]] = []
    other = 0
    try:
        text = (replay_dir / ("%s.log" % CONNECTOR)).read_text(encoding="utf-8")
    except OSError:
        text = ""
    for line in text.splitlines():
        m = _DOCKER_TS.match(line)
        try:
            rec = json.loads(m.group(3) if m else line)
        except ValueError:
            rec = None
        if isinstance(rec, dict) and isinstance(rec.get("event"), str):
            records.append(rec)
        elif line.strip():
            other += 1
    events: Dict[str, int] = {}
    for rec in records:
        events[rec["event"]] = events.get(rec["event"], 0) + 1
    first, last = (records[0], records[-1]) if records else ({}, {})
    ok = state[:1] == ["exited"] and code == 0 and first.get("event") == "start" and last.get("event") == "stop"
    return {"ok": ok, "state": state[0] if state else None, "exit": code, "exit_means": CONNECTOR_EXITS.get(code, "unknown"),
            "events": events, "lines_that_are_no_record": other,
            "start": {k: first.get(k) for k in ("allowlist_version", "allowlist_digest", "catalogue", "paths", "rate_hz")} if first else None,
            "counters": last.get("counters") if last.get("event") == "stop" else None,
            "limiter": last.get("limiter") if last.get("event") == "stop" else None,
            "uplink": last.get("uplink") if last.get("event") == "stop" else None,
            "note": "the connector's own counts of what it tried and what its uplink took; nothing here says what a far end received"}


def stop_containers(ctx: Any) -> None:
    """Stop a replay's containers in their order (docker stop: SIGTERM, then KILL after the grace): the CAN provider and the
    app; the witness once the app's last heartbeat has settled; the bridge (stopped at the player's end already: a no-op
    then); the connector, while the databroker still runs, so that its last read and its last flush run; then the
    recorder, the mock provider and the databroker."""
    docker("stop", "-t", "10", NAMES[attr.CAN_PROVIDER], check=False)
    docker("stop", "-t", "10", NAMES[attr.APP], check=False)
    time.sleep(SETTLE_S)
    docker("stop", "-t", "10", NAMES[WITNESS], check=False)   # it handles SIGTERM: writes its stop record and exits
    if ctx.bridge != "none":
        docker("stop", "-t", "10", BRIDGE_CONTAINER, check=False)      # stopped at the player's end; a no-op then
    if has_connector(ctx):
        docker("stop", "-t", str(CONNECTOR_STOP_S), CONNECTOR_CONTAINER, check=False)   # SIGTERM: one last read, the open batch, one document
    for comp in (attr.RECORDER, attr.MOCK_PROVIDER, attr.DATABROKER):
        docker("stop", "-t", "3", NAMES[comp], check=False)   # the recorder and the mock ignore SIGTERM: killed after 3 s


def jsonl_records(path: Path) -> List[Dict[str, Any]]:
    """The whole JSON lines of a log another process is writing (a torn last line is skipped); [] when absent."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def allowances(ctx: Context) -> List[Dict[str, Any]]:
    """The stack's own non-loopback listeners, allowed by PID: the native vss monitor's, while it runs. None in guest mode,
    where the stack starts no listener of its own."""
    if monitor_mode(ctx) == "guest":
        return []
    return [ctx.monitor.allowance()] if ctx.monitor is not None else []


def listeners_now(info: Dict[str, Any], feed: str, suffix: str, allowed: Sequence[Dict[str, Any]] = ()) -> None:
    """Snapshot the host's listeners (and the databroker's namespace for dumpfile) and judge them
    against the snapshot taken before the stack started."""
    info["listeners_during" + suffix] = host_listeners()
    ns = None
    if feed == "dumpfile":
        pid = int(docker("inspect", "-f", "{{.State.Pid}}", NAMES[attr.DATABROKER]).stdout.strip())
        ns = netns_listeners(pid)
        info["listeners_namespace" + suffix] = ns
    info["listeners" + suffix] = listener_verdict(info["listeners_before"], info["listeners_during" + suffix], ns,
                                                  stack_pids([a["pid"] for a in allowed]), allowed)


def running_images() -> Dict[str, str]:
    out = {}
    for comp, name in CONTAINERS.items():
        p = docker("inspect", "-f", "{{.Image}}", name, check=False)
        if p.returncode == 0:
            out[comp] = p.stdout.strip()
    return out


def collect(replay_dir: Path) -> Dict[str, Any]:
    states = {}
    for comp, name in CONTAINERS.items():
        p = docker("inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", name, check=False)
        if p.returncode != 0:
            continue
        states[comp] = p.stdout.strip()
        q = docker("logs", "-t", name, check=False, timeout=60)     # -t: dockerd's receive time on every line
        (replay_dir / ("%s.log" % comp)).write_text((q.stdout or "") + (q.stderr or ""), encoding="utf-8")
    return states


_DOCKER_TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z\s+(.*)$")


def docker_log_times(text: str, pattern: str) -> List[Tuple[float, str]]:
    """(epoch seconds, line) of every `docker logs -t` line matching pattern."""
    rx = re.compile(pattern)
    out = []
    for line in text.splitlines():
        m = _DOCKER_TS.match(line)
        if not m or not rx.search(m.group(3)):
            continue
        base = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp()
        out.append((base + float("0" + (m.group(2) or ".0")), m.group(3)))
    return out


def replay_once(ctx: Context, feed: str, replay_id: str) -> Dict[str, Any]:
    if app_mode(ctx) != "stack":
        raise StackError(APP_EXTERNAL_NOT_REPLAYED)
    if monitor_mode(ctx) == "guest":
        raise StackError("stack.py's replay runs the native vss monitor only; guest mode is step3.py's (--monitor guest)")
    replay_dir = ctx.run_dir / replay_id
    if replay_dir.exists():
        raise StackError("%s exists: a replay directory is never reused" % replay_dir)
    if ctx.bridge != "none" and feed != "vcan":
        raise StackError(BROKER_NEEDS_VCAN)
    if has_connector(ctx) and feed != "vcan":
        raise StackError(CONNECTOR_NEEDS_VCAN)
    run_label = "%s/%s" % (ctx.run_dir.name, replay_id)
    result: Dict[str, Any] = {"replay": replay_id, "feed": feed, "bridge_mode": ctx.bridge}
    new_hook_records(ctx)
    header = ctx.run_header(replay_id, feed)
    rows = attr.run_rows(ctx.rows, ctx.image_ids())
    capture: Optional[VcanCapture] = None
    checks: List[attr.Check] = []
    clock: Dict[str, Optional[int]] = {"player_start_realtime_ns": None, "player_end_realtime_ns": None}

    def write_table() -> None:
        write_json(replay_dir / "attribution.json", {"header": header, "rows": rows,
                                                     "scenario_checks": ctx.manifest["scenario_checks"],
                                                     "checks": [list(c) for c in checks]})
        (replay_dir / "attribution.md").write_text(attr.render_markdown(header, rows), encoding="utf-8")

    try:
        info = up(ctx, feed, replay_dir, run_label, header)
        result["setup"] = {k: v for k, v in info.items() if not k.startswith("listeners")}
        result["listeners"] = info["listeners"]
        write_json(replay_dir / "listeners.json", info)
        checks += [attr.check_recording(header, ctx.staged[log_of(ctx)], ctx.scenario["dbc_sha256"]), ctx.check_header(header)]
        write_table()
        failed = [c for c in checks if not c[1]]
        if failed or not info["listeners"]["ok"]:
            raise StackError("refused to start the feed: %s %s" % (failed, info["listeners"]))
        dyn_count = len(ctx.decoded["values"][rc.V_PATH])
        gear_path = attr.SLOT_PATHS[4]
        gear_count = len(ctx.decoded["values"][gear_path])
        t_feed = time.monotonic()
        start(ctx, attr.CAN_PROVIDER, feed, replay_dir, run_label)
        checks.append(attr.check_images(rows, running_images()))     # C8, once every writer has started
        write_table()
        if not checks[-1][1]:
            raise StackError("C8 failed: %s" % checks[-1][2])
        if feed == "dumpfile":
            time.sleep(VCAN_READY_S)
            listeners_now(info, feed, "_feed", allowances(ctx))
            write_json(replay_dir / "listeners.json", info)
            wait_log(NAMES[attr.CAN_PROVIDER], r"Replayed all messages from CAN log file", 300)
        else:
            wait_log(NAMES[attr.CAN_PROVIDER], r"Starting to receive CAN messages|Using DBC reader", START_TIMEOUT_S)
            time.sleep(VCAN_READY_S)
            listeners_now(info, feed, "_feed", allowances(ctx))
            write_json(replay_dir / "listeners.json", info)
            capture = VcanCapture()
            clock["player_start_realtime_ns"] = time.time_ns()
            p = run([str(SIM_PY), "-m", "can.player", "-i", "socketcan", "-c", VCAN, str(ctx.in_dir / log_of(ctx))], check=False, timeout=300)
            clock["player_end_realtime_ns"] = time.time_ns()
            if ctx.bridge != "none":
                # The recording is over: stop the bridge now (SIGTERM: its drain and summary). From here on the provider
                # writes nothing and the held values only age, so a frame packed later is an honest 22 (spec 14.4);
                # bridge_result() counts the replies packed after the player ended apart.
                docker("stop", "-t", "10", BRIDGE_CONTAINER, check=False)
            (replay_dir / "player.log").write_text(p.stdout + p.stderr, encoding="utf-8")
            time.sleep(1.0)
            frames = capture.close()
            capture = None
            expected = log_frames(ctx.in_dir / log_of(ctx))
            result["vcan_capture"] = {"player_exit": p.returncode, "frames_on_bus": len(frames), "frames_in_log": len(expected),
                                      "identical": frames == expected}
        result["feed_wall_s"] = round(time.monotonic() - t_feed, 1)
        result["listeners_feed"] = info["listeners_feed"]
        last: List[Any] = [None]
        stable_since = [time.monotonic()]
        want = {p: len(v) for p, v in ctx.decoded["values"].items()}
        wlog = replay_dir / WITNESS_LOG

        def replay_over() -> bool:
            rows_now = csv_rows(replay_dir)
            n = len(rc.series(rows_now, rc.V_PATH))
            seen = rc.read_witness(wlog, strict=False)["values"] if wlog.exists() else {}
            m = sum(len(v) for v in seen.values())
            if (n >= dyn_count and len(rc.series(rows_now, gear_path)) >= gear_count
                    and all(len(seen.get(p, [])) >= k for p, k in want.items())):
                return True
            if (n, m) != last[0]:
                last[0] = (n, m)
                stable_since[0] = time.monotonic()
            return time.monotonic() - stable_since[0] > QUIET_S
        wait_for(replay_over, 120, "the recorder and the witness to hold the replay's values")
        listeners_now(info, feed, "_end", allowances(ctx))   # the third snapshot: the replay is over, nothing stopped yet
        write_json(replay_dir / "listeners.json", info)
        result["listeners_end"] = info["listeners_end"]
        stop_containers(ctx)
    finally:
        if capture is not None:
            capture.close()
        if ctx.monitor is not None:
            result["monitor_exit"] = ctx.monitor.stop()        # after the bridge, so its drain was answered
            ctx.monitor = None
        result["containers"] = collect(replay_dir) if replay_dir.exists() else {}
        hooks = hook_records(ctx)
        if hooks is not None:
            result[AFTER_START_KEY] = hooks
        remove_stack()
    result.update(analyse(ctx, replay_dir))
    close = record_close(header, replay_dir)
    checks.append(close)
    result["c12b"] = list(close)
    write_table()
    if ctx.bridge != "none":
        result["bridge"] = bridge_result(replay_dir, clock, ctx.manifest["bridge"].get("wheelbase"))
    if has_connector(ctx):
        result["connector"] = connector_result(replay_dir, result["containers"])
    write_json(replay_dir / "result.json", result)
    return result


def replay_gates(r: Dict[str, Any]) -> Dict[str, bool]:
    """`stack.py replay`'s exit status, gate by gate, from one replay's result: Phase 1's value, decision and light
    gates, the three listener snapshots (the PID allowance applied in each), the bus frames for vcan, C12b, and with a
    bridge its own result. The same listener and bus gates as exit-test's verdict()."""
    gates = {
        "values": bool(r["values"]["ok"] and r["witness_values"]["ok"] and r["app_values"]["ok"]),
        "decisions": bool(r["decisions"]["ok"]),
        "lights": bool(r["lights"]["mock_log"]["ok"]),
        "listeners": all(r.get(k, {}).get("ok", False) for k in ("listeners", "listeners_feed", "listeners_end")),
        "c12b": bool(r["c12b"][1]),
    }
    if r["feed"] == "vcan":
        gates["bus_frames_identical"] = bool(r.get("vcan_capture", {}).get("identical", False))
    if r.get("bridge_mode", "none") != "none":
        gates["bridge"] = bool(r.get("bridge", {}).get("ok", False))
    if r.get("connector") is not None:          # a replay with the twin connector: it stopped cleanly, its last flush run to its end
        gates["connector"] = bool(r["connector"].get("ok", False))
    return gates


def record_close(header: Dict[str, Any], replay_dir: Path, console: Optional[Path] = None) -> attr.Check:
    """C12b at record close, from the files the replay left: the monitor's console capture (console; by default the
    native monitor's monitor.log, in guest mode step3.py's stripped copy of the guest's console) and the bridge's log
    (bridge/bridge.jsonl), each None when the run made none. Writes header_check."""
    mlog = replay_dir / "monitor.log" if console is None else Path(console)
    blog = replay_dir / "bridge" / "bridge.jsonl"
    text = mlog.read_text(encoding="utf-8", errors="replace") if mlog.is_file() else None
    records = jsonl_records(blog) if blog.is_file() else None
    check = attr.check_close(header, text, records)
    header["header_check"] = attr.header_check(check)
    return check


_MISS = re.compile(r"^monitor: LIVENESS MISS: ", re.M)
_RESTORED = re.compile(r"^monitor: LIVENESS RESTORED: ", re.M)


def wheelbase_agrees(predicted: Optional[Dict[str, Any]], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The bridge's own wheelbase record (spec 5.6, logged at its start) against the run manifest's prediction
    (served_wheelbase()): the same branch, and the same value when one was served. None predicted: not compared."""
    logged = [r for r in records if r.get("event") == "wheelbase"]
    out: Dict[str, Any] = {"predicted": predicted, "logged": logged}
    if predicted is None:
        out["agrees"] = None
        return out
    keys = ("served", "value_mm") if predicted.get("served") else ("served", "note")
    out["agrees"] = len(logged) == 1 and all(logged[0].get(k) == predicted.get(k) for k in keys)
    return out


def bridge_result(replay_dir: Path, clock: Dict[str, Optional[int]], wheelbase: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a bridge run's own files say: the bridge's summary (its counters, the accounting identity), its replies
    by verdict and reason, split at the player's end (broker mode's src_now_ns is CLOCK_REALTIME, AGE_CLOCK, as the
    player's end is), the native monitor's liveness lines, and its wheelbase record against the run manifest's
    prediction (wheelbase). Functional evidence only: no field is a timing."""
    bdir = replay_dir / "bridge"
    out: Dict[str, Any] = {"clock": dict(clock)}
    try:
        s = json.loads((bdir / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return dict(out, ok=False, error="no bridge summary: %s" % exc)
    n = s.get("counters", {})
    out["counters"] = {k: n.get(k) for k in ("ticks", "ticks_empty", "packed", "replied", "accepted", "rejected", "drop",
                                              "lost_on_reconnect", "connects", "age_over_max", "age_negative", "r21")}
    out["identity_holds"] = bool(s.get("identity", {}).get("holds")) and bool(s.get("ticks_identity", {}).get("holds"))
    out["fatal"] = s.get("fatal")
    out["writeback"] = s.get("writeback")
    end = clock.get("player_end_realtime_ns")
    replies = [r for r in jsonl_records(bdir / "replies.jsonl") if r.get("event") == "reply"]
    split: Dict[str, Dict[str, int]] = {"while_playing": {}, "after_player_end": {}}
    for r in replies:
        part = "after_player_end" if end is not None and r.get("src_now_ns", 0) > end else "while_playing"
        key = "ACCEPT" if r.get("reason") == 0 else "REJECT %s" % r.get("reason")
        split[part][key] = split[part].get(key, 0) + 1
    out["replies"] = split
    console = (replay_dir / "monitor.log").read_text(encoding="utf-8", errors="replace") if (replay_dir / "monitor.log").is_file() else ""
    out["monitor"] = {"vss_rules": [ln for ln in console.splitlines() if ln.startswith("monitor: vss rules:")],
                      "liveness_miss": len(_MISS.findall(console)), "liveness_restored": len(_RESTORED.findall(console))}
    out["wheelbase"] = wheelbase_agrees(wheelbase, jsonl_records(bdir / "bridge.jsonl"))
    out["ok"] = (out["identity_holds"] and out["fatal"] is None and split["while_playing"].get("ACCEPT", 0) > 0
                 and out["wheelbase"]["agrees"] is not False)
    return out


# --- the live run (module docstring, LIVE; SDV Phase 7 WP3c) ------------------------------------

def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def take_state(out: Path, vehicle: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the feeder's take directory says now: its capture.json (completed, the RTF, the vehicle), and whether take.sha256,
    the take's last file, exists (the take has ended, completed or not). vehicle: the header's source vehicle, which the take's
    blueprint and wheelbase must be (None: not compared). A capture.json read while the take rewrites it (it writes the file
    once before its cleanup and once after) is read again, up to LIVE_TORN_READS times."""
    doc: Any = None
    for _n in range(LIVE_TORN_READS):
        try:
            doc = json.loads((out / "capture.json").read_text(encoding="utf-8"))
            break
        except OSError:
            break                      # not written yet
        except ValueError:
            doc = None                 # being written: read again
            time.sleep(LIVE_POLL_S / 10)
    if not isinstance(doc, dict):
        doc = None
    ego = doc.get("ego") if doc is not None and isinstance(doc.get("ego"), dict) else {}
    state: Dict[str, Any] = {
        "dir": str(out), "capture": doc is not None, "ended": (out / "take.sha256").is_file(),
        "completed": doc is not None and doc.get("completed") is True, "cleanup": doc.get("cleanup") if doc else None,
        "errors": list(doc.get("errors") or []) if doc else [], "steps": doc.get("steps") if doc else None,
        "rtf": doc.get("rtf") if doc else None, "name": doc.get("name") if doc else None, "seed": doc.get("seed") if doc else None,
        "blueprint": doc.get("blueprint") if doc else None, "wheelbase_mm": ego.get("wheelbase_mm"), "vehicle_agrees": None}
    if vehicle is not None:
        state["vehicle_agrees"] = (doc is not None and state["blueprint"] == vehicle["name"]
                                   and state["wheelbase_mm"] == vehicle["wheelbase_mm"])
    return state


def wait_for_take(out: Path, timeout_s: float, vehicle: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Until the take's capture.json reads completed (and then until the take has ended, take.sha256 written after its
    cleanup, for at most LIVE_SETTLE_S more), or the take has ended without completing, or timeout_s."""
    t0 = time.monotonic()
    completed_at: Optional[float] = None
    while True:
        state = take_state(out, vehicle)
        now = time.monotonic()
        if state["ended"]:
            state["timed_out"] = False
            break
        if state["completed"]:
            completed_at = now if completed_at is None else completed_at
            if now - completed_at >= LIVE_SETTLE_S:
                state["timed_out"] = False
                break
        elif now - t0 > timeout_s:
            state["timed_out"] = True
            break
        time.sleep(LIVE_POLL_S)
    state["waited_s"] = round(time.monotonic() - t0, 1)
    state["seen_end_realtime_ns"] = time.time_ns()
    return state


def live_close(header: Dict[str, Any], replay_dir: Path, feeder_out: Path) -> attr.Check:
    """C12b at a live run's record close: source_rtf filled from the take's capture.json (its rtf {min, mean, max}; null when
    the take wrote none), then record_close's operands, the native monitor's console and the bridge's log."""
    rtf = take_state(feeder_out)["rtf"]
    keys = ("min", "mean", "max")
    header["source_rtf"] = {k: rtf[k] for k in keys} if isinstance(rtf, dict) and all(_is_number(rtf.get(k)) for k in keys) else None
    return record_close(header, replay_dir)


def live_gates(r: Dict[str, Any]) -> Dict[str, bool]:
    """`stack.py live`'s exit status, gate by gate, from its result: C12a and C8 at the start, the three listener snapshots, the
    take completed within the wait, cleaned up with no error (as carla_capture.take's own exit 0 and encode.check_take want: its
    capture.json reads completed before its cleanup runs) and in the declared vehicle, C12b at record close, and the bridge's
    own result."""
    take = r.get("take") or {}
    return {
        "c12a": bool(r.get("c12a") and r["c12a"][1]),
        "c8": bool(r.get("c8") and r["c8"][1]),
        "listeners": all((r.get(k) or {}).get("ok", False) for k in ("listeners", "listeners_feed", "listeners_end")),
        "take_completed": take.get("completed") is True and take.get("timed_out") is False,
        "take_clean": take.get("cleanup") == "ok" and take.get("errors") == [],
        "take_vehicle": take.get("vehicle_agrees") is True,
        "c12b": bool(r.get("c12b") and r["c12b"][1]),
        "bridge": bool((r.get("bridge") or {}).get("ok", False)),
    }


def live_once(ctx: LiveContext) -> Dict[str, Any]:
    """One live run (module docstring, LIVE): up on the vcan feed with the header, the CAN provider, the capture of vcan0, the
    wait for the take, then the stops; at close source_rtf from the take, C12b, the bridge's result. Nothing is replayed."""
    replay_dir = ctx.run_dir / LIVE_REPLAY
    if replay_dir.exists():
        raise StackError("%s exists: a replay directory is never reused" % replay_dir)
    feed = "vcan"
    label = "%s/%s" % (ctx.run_dir.name, LIVE_REPLAY)
    vehicle = ctx.scenario["source"]["vehicle"]
    result: Dict[str, Any] = {"live": LIVE_REPLAY, "feed": LIVE_FEED, "run_type": LIVE_RUN_TYPE, "bridge_mode": ctx.bridge,
                              "monitor": monitor_mode(ctx), "feeder_out": str(ctx.feeder_out)}
    new_hook_records(ctx)
    header = ctx.run_header(LIVE_REPLAY, feed)
    rows = attr.run_rows(ctx.rows, ctx.image_ids())
    checks: List[attr.Check] = [ctx.check_header(header)]
    result["c12a"] = list(checks[0])
    capture: Optional[VcanCapture] = None
    take: Dict[str, Any] = {"timed_out": None, "completed": False, "ended": False, "note": "not waited for"}

    def write_table() -> None:
        write_json(replay_dir / "attribution.json", {"header": header, "rows": rows, "scenario_checks": ctx.manifest["scenario_checks"],
                                                     "checks": [list(ch) for ch in checks]})
        (replay_dir / "attribution.md").write_text(attr.render_markdown(header, rows), encoding="utf-8")

    try:
        info = up(ctx, feed, replay_dir, label, header)
        result["setup"] = {k: v for k, v in info.items() if not k.startswith("listeners")}
        result["listeners"] = info["listeners"]
        write_json(replay_dir / "listeners.json", info)
        write_table()
        if not checks[0][1] or not info["listeners"]["ok"]:
            raise StackError("refused to start the feed: %s %s" % (checks[0], info["listeners"]))
        start(ctx, attr.CAN_PROVIDER, feed, replay_dir, label)
        c8 = attr.check_images(rows, running_images())
        checks.append(c8)
        result["c8"] = list(c8)
        write_table()
        if not c8[1]:
            raise StackError("C8 failed: %s" % c8[2])
        wait_log(NAMES[attr.CAN_PROVIDER], r"Starting to receive CAN messages|Using DBC reader", START_TIMEOUT_S)
        time.sleep(VCAN_READY_S)
        listeners_now(info, feed, "_feed", allowances(ctx))
        result["listeners_feed"] = info["listeners_feed"]
        write_json(replay_dir / "listeners.json", info)
        capture = VcanCapture()
        print("stack.py live: ready: start the feeder now (sdv/feeder/live.py run ... --out %s); waiting up to %d s for its take"
              % (ctx.feeder_out, int(LIVE_TAKE_WAIT_S)), flush=True)
        take = wait_for_take(ctx.feeder_out, LIVE_TAKE_WAIT_S, vehicle)
        time.sleep(LIVE_SETTLE_S)
        listeners_now(info, feed, "_end", allowances(ctx))   # the third snapshot: the take is over, nothing stopped yet
        result["listeners_end"] = info["listeners_end"]
        write_json(replay_dir / "listeners.json", info)
        docker("stop", "-t", "10", BRIDGE_CONTAINER, check=False)     # SIGTERM: its drain and summary, before the monitor stops
        frames, times = capture.close(), list(capture.times_ns)
        capture = None
        write_json(replay_dir / LIVE_CAPTURE, {
            "format": 1, "channel": VCAN, "keys": ["t_ns", "can_id", "data"],
            "clock": "realtime: python-can's SocketCAN receive time (its microseconds, as ns), the clock the bridge's can source ages on",
            "frames": [[t, cid, data.hex()] for t, (cid, data) in zip(times, frames)]})
        stop_containers(ctx)
    finally:
        if capture is not None:
            capture.close()
        if ctx.monitor is not None:
            result["monitor_exit"] = ctx.monitor.stop()        # after the bridge, so its drain was answered
            ctx.monitor = None
        result["containers"] = collect(replay_dir) if replay_dir.exists() else {}
        hooks = hook_records(ctx)
        if hooks is not None:
            result[AFTER_START_KEY] = hooks
        remove_stack()
    result["take"] = dict(take_state(ctx.feeder_out, vehicle), timed_out=take.get("timed_out"), waited_s=take.get("waited_s"),
                          seen_end_realtime_ns=take.get("seen_end_realtime_ns"))
    close = live_close(header, replay_dir, ctx.feeder_out)
    checks.append(close)
    result["c12b"] = list(close)
    write_table()
    end = take.get("seen_end_realtime_ns")          # what fed the bridge ended there: a replay's player end (bridge_result splits at it)
    result["bridge"] = bridge_result(replay_dir, {"player_end_realtime_ns": end, "take_end_seen_realtime_ns": end},
                                     ctx.manifest["bridge"].get("wheelbase"))
    result["gates"] = live_gates(result)
    write_json(replay_dir / "result.json", result)
    return result


def live_main(a: argparse.Namespace) -> int:
    """`stack.py live`: its refusals before anything is written (the twin-control marker, a role other than the PC's, a
    --feeder-out that exists or lies inside the repo), then the context, the run and its gates."""
    refuse_bridge_in_twin_control(a.bridge)
    role = host_role()
    if role != "pc":
        raise StackError("live runs on the PC only (%s=%s): the feeder drives CARLA there, and the hosts replay recordings"
                         % (HOST_ROLE_ENV, role))
    out = Path(a.feeder_out).expanduser().absolute()
    if out.exists() or out.is_symlink():
        raise StackError("--feeder-out %s exists: a live run reads the take made during it (live.py refuses an existing one too)" % out)
    if inside_repo(out):
        raise StackError("--feeder-out %s is inside the repository: a take belongs outside it" % out)
    run_dir = new_run_dir(a.name)
    ctx = LiveContext(run_dir, a.bridge, out)
    ctx.prepare()
    print("prepared %s" % run_dir, flush=True)
    r = live_once(ctx)
    print("C12b: %s" % (r["c12b"],))
    print("bridge: %s" % json.dumps({k: r["bridge"].get(k) for k in ("ok", "counters", "identity_holds", "replies", "monitor", "wheelbase")},
                                    indent=1))
    print("gates: %s" % json.dumps(r["gates"], sort_keys=True))
    print("F2: python sdv/feeder/f2check.py %s" % run_dir)
    return 0 if all(r["gates"].values()) else 1


# --- analysis -----------------------------------------------------------------------------------

def analyse(ctx: Context, replay_dir: Path) -> Dict[str, Any]:
    """One replay's judgement, from the files the replay left in replay_dir. Two sources are lossless
    and carry the behaviour key and the window gate: the app's own log (its decisions and actuations)
    and the mock provider's own log (its 'Feeding' lines, each written just before the mock makes the
    write it names, so a line is not proof the databroker accepted it: a failed write leaves the line and
    then an error, which is why the gate also wants every line of that log to be an INFO record,
    rc.mock_log_clean). The recorder's CSV is a kuksa.val.v1
    subscription of one buffered update, which the databroker lets drop an update when it lags: it
    is judged for the CAN-fed values (aligned, within the lags the databroker logged) and its hazard
    rows are reported (lights.recorder), never read by the key or by a gate."""
    rows = rc.read_recorder_csv(replay_dir / "vss-recorder.csv")
    got = {p: [v for _t, v in rc.series(rows, p)] for p in ctx.mapping}
    broker_log = (replay_dir / ("%s.log" % attr.DATABROKER)).read_text(encoding="utf-8")
    # the recorder (kuksa.val.v1, capacity 1): aligned, its unrecorded values bounded by the misses the
    # databroker logged for capacity-1 subscribers (the recorder and the mock provider share that count)
    v1_lags = rc.broker_misses(broker_log, capacity=1)
    values = rc.compare_values(ctx.decoded["values"], ctx.decoded["half_lsb"], got, v1_lags)
    values["broker_lags_by_capacity"] = rc.broker_lags(broker_log)
    # the witness (kuksa.val.v2, buffer 1000): every value of the six CAN-fed paths, exactly. A missing
    # or torn log is judged (load_witness), not fatal to the replay's record; each gate is in
    # rc.witness_verdict, which tests/test_sdv_stack.py holds one by one.
    wit, read_error = rc.load_witness(replay_dir / WITNESS_LOG)
    witness = rc.witness_verdict(ctx.decoded["values"], ctx.decoded["half_lsb"], wit, read_error, broker_log,
                                 capacity=WITNESS_CAPACITY)
    recs = rc.read_jsonl(replay_dir / "hard-brake-hazard.jsonl")
    # the same comparison on the app's own subscription (kuksa.val.v2, buffer hazard.SUBSCRIBE_BUFFER): its two inputs
    app_seen = {p: [r["value"] for r in recs if r.get("event") == "input" and r.get("path") == p] for p in ctx.hz.INPUTS}
    app_values = rc.compare_values({p: ctx.decoded["values"][p] for p in ctx.hz.INPUTS},
                                   {p: ctx.decoded["half_lsb"][p] for p in ctx.hz.INPUTS}, app_seen, 0)
    anchor_rec = int(ctx.windows["anchor"]["t_rec_ms"])
    first_v = [r for r in recs if r.get("event") == "input" and r.get("path") == rc.V_PATH and r.get("value") not in (None, 0, 0.0)]
    mock_log = (replay_dir / ("%s.log" % attr.MOCK_PROVIDER)).read_text(encoding="utf-8")
    fed = docker_log_times(mock_log, r"Feeding 'Vehicle\.Body\.Lights\.Hazard\.IsSignaling' with value (True|False)")
    mock_writes = [{"value": line.rstrip().endswith("True"),
                    "t_rec_ms": None if not first_v else rc.to_rec_ms(t, first_v[0]["t_wall"], anchor_rec)} for t, line in fed]
    t_anchor_csv = rc.anchor_time(rc.series(rows, rc.V_PATH))
    app = rc.app_events(recs, anchor_rec)
    decisions = rc.window_verdict(app["decisions"], ctx.windows)
    appstate = rc.collapse(app["heartbeats"], ("state", "hazard_requested", "actuate_result"))
    # the app's decisions recomputed from the inputs it logged
    offline = ctx.hz.App(image_id=ctx.image_ids()[attr.APP])
    offline.on_subscribed(0.0)
    re_dec = []
    for r in recs:
        if r.get("event") == "input":
            for act in offline.on_input(r["path"], r["value"], r["t"]):
                if isinstance(act, ctx.hz.Note) and act.record.get("event") == "decision":
                    re_dec.append((act.record["hazard"], act.record["trigger"], act.record["v"], act.record["a"]))
    logged_dec = [(d["hazard"], d["trigger"], d["v"], d["a"]) for d in app["decisions"]]
    mock_clean = rc.mock_log_clean(mock_log)
    mock_offending = rc.mock_log_offending(mock_log)
    mock_ok = rc.mock_gate(mock_writes, ctx.windows, mock_clean)
    # the recorder's own hazard rows against the two lossless sources: the lags the databroker logged
    # for capacity-1 subscribers, less those the recorder's CAN-fed rows already account for
    recorder_light = rc.recorder_light_view(rows, t_anchor_csv, mock_writes, app["actuations"], max(0, v1_lags - values["unrecorded_total"]),
                                            ctx.windows, anchor_rec)
    return {
        "values": values,
        "witness_values": witness,
        "app_values": app_values,
        "anchor": {"csv_found": t_anchor_csv is not None, "app_found": app["anchor_found"], "t_rec_ms": anchor_rec},
        "lights": {"mock_log": {"ok": mock_ok, "clean": mock_clean, "writes": mock_writes,
                                "offending_lines": mock_offending[:MOCK_OFFENDING_KEPT], "offending_total": len(mock_offending),
                                "note": "the mock provider's own 'Feeding' lines, timed by dockerd's receive stamp, mapped with the app's anchor: "
                                        "the gate, and the lights of the behaviour key. The mock logs each line just before it makes the write, "
                                        "so the gate also wants a clean log: every line an INFO record (offending_lines: the first lines that "
                                        "are not, offending_total: how many)"},
                   "recorder": recorder_light},
        "decisions": decisions,
        "decision_list": app["decisions"],
        "actuations": app["actuations"],
        "app_decisions_reproduced_offline": re_dec == logged_dec,
        "appstate_sequence": [list(x) for x in appstate],
        "appstate_first_last": [app["heartbeats"][0], app["heartbeats"][-1]] if app["heartbeats"] else [],
        "app_inputs_received": app["inputs_received"],
        "monitor_display": app["monitor_display"][:4],
        "app_errors": app["errors"],
        "behaviour_key": rc.behaviour_key(logged_dec, app["actuations"], mock_writes, appstate),
    }


def verdict(ctx: Context, results: List[Dict[str, Any]], feed: str, n: int) -> Dict[str, Any]:
    """One feed's verdict over its replays' results. Every boolean in it is a gate (`ok` is their
    conjunction); the counts are reported. `lights_in_window` is the app's decisions and the mock
    provider's own writes inside their windows, with a mock log that holds nothing but INFO records
    (the mock logs a write before it makes it), and `same_behaviour` is the behaviour key equal across
    the replays: neither reads the recorder's hazard rows (lights.recorder is reported, and only
    counted here)."""
    rs = [r for r in results if r["feed"] == feed]
    keys = [json.dumps(r["behaviour_key"], sort_keys=True) for r in rs]
    same = len(set(keys)) == 1 and len(rs) == n
    windows = all(r["decisions"]["ok"] and r["lights"]["mock_log"]["ok"] for r in rs)
    recorder = all(r["values"]["ok"] for r in rs)
    witness = all(r["witness_values"]["ok"] for r in rs)
    app_inputs = all(r["app_values"]["ok"] for r in rs)
    listeners = all(r.get(k, {}).get("ok", False) for r in rs for k in ("listeners", "listeners_feed", "listeners_end"))
    out = {"feed": feed, "replays": len(rs), "same_behaviour": same, "lights_in_window": windows,
           "values_equal_decoded": recorder and witness and app_inputs,
           "recorder_values_aligned": recorder, "witness_values_exact": witness, "app_inputs_exact": app_inputs,
           "recorder_values_exact_replays": sum(1 for r in rs if r["values"]["exact"]),
           "recorder_lights_consistent_replays": sum(1 for r in rs if r["lights"]["recorder"]["consistent"]["ok"]),   # a count: reported, not a gate
           "only_loopback_listeners": listeners}
    if feed == "vcan":
        out["bus_frames_identical"] = all(r.get("vcan_capture", {}).get("identical", False) for r in rs)
    out["ok"] = all(v for k, v in out.items() if isinstance(v, bool))       # every boolean above; the count is reported
    return out


# --- catalogue loading (the S2 check's databroker half) -----------------------------------------

def load_catalogue(ctx: Context, name: str, path: Path, probe_paths: Sequence[str], out_dir: Path) -> Dict[str, Any]:
    """Start databroker 0.7.1 on one catalogue file (private namespace, nothing else running) and
    record whether it serves it, and what it says about a few paths."""
    remove_stack()
    stage = out_dir / ("in-" + name)
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, stage / "catalogue.json")
    res: Dict[str, Any] = {"name": name, "file": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
    dbn = NAMES[attr.DATABROKER]
    docker("run", "-d", "--name", dbn, "--label", "%s=loadcheck" % LABEL, *common_flags(ctx), "--network", "none", "--read-only",
           "-e", "KUKSA_DATABROKER_ADDR=" + BROKER_HOST, "-v", "%s:/in:ro" % stage, upstream_ref(ctx.images, attr.DATABROKER),
           "--vss", "/in/catalogue.json", "--address", BROKER_HOST, "--insecure")
    try:
        try:
            wait_log(dbn, r"Listening on 127\.0\.0\.1:%d" % BROKER_PORT, 30)
            res["loads"] = True
        except StackError as exc:
            res["loads"] = False
            res["error"] = str(exc)[-1500:]
            return res
        p = docker("run", "--rm", "--network", "container:" + dbn, *common_flags(ctx), "--read-only", "-v", "%s:/probe.py:ro" % PROBE_FILE,
                   "--entrypoint", "python", ctx.image_ids()[attr.RECORDER], "/probe.py", BROKER, *probe_paths, check=False)
        res["probe"] = json.loads(p.stdout) if p.returncode == 0 else {"error": p.stderr[-1500:]}
    finally:
        (out_dir / ("databroker-%s.log" % name)).write_text(container_logs(dbn), encoding="utf-8")
        remove_stack()
    return res


def ageprobe_args(contract: Any) -> List[str]:
    """ageclock_probe.py's arguments after the address: every float slot (yaw first: the write cases use the first)
    and the int8 slot, from the generated contract (the paths and datatypes the bridge subscribes to)."""
    pairs = list(zip(contract.SLOT_PATHS, contract.SLOT_DATATYPES))
    floats = sorted((p for p, dt in pairs if dt == "float"), key=lambda p: (p != attr.SLOT_PATHS[3], p))
    args: List[str] = []
    for p in floats:
        args += ["--float", p]
    for p, dt in pairs:
        if dt == "int8":
            args += ["--int8", p]
    return args


def age_probe(ctx: Context, out_dir: Path) -> Dict[str, Any]:
    """Spec 17.1 items 1-2 against a throwaway databroker 0.7.1 (the pinned image, the run's staged catalogue, its own
    loopback-only namespace, nothing else running): ageclock_probe.py in the recorder image, joined to that namespace.
    Its clocks are the host kernel's (a container shares them), so its realtime and monotonic readings bound the
    databroker's stamps. Writes ageclock.json and the databroker's log into out_dir."""
    remove_stack()
    out_dir.mkdir(parents=True, exist_ok=True)
    dbn = NAMES[attr.DATABROKER]
    docker("run", "-d", "--name", dbn, "--label", "%s=ageprobe" % LABEL, *common_flags(ctx), "--network", "none", "--read-only",
           "-e", "KUKSA_DATABROKER_ADDR=" + BROKER_HOST, "-v", "%s:/in:ro" % ctx.in_dir, upstream_ref(ctx.images, attr.DATABROKER),
           "--vss", "/in/vss-databroker.json", "--address", BROKER_HOST, "--port", str(BROKER_PORT), "--insecure")
    try:
        wait_log(dbn, r"Listening on 127\.0\.0\.1:%d" % BROKER_PORT, 30)
        args = ageprobe_args(ctx.contract)
        p = docker("run", "--rm", "--network", "container:" + dbn, *common_flags(ctx), "--read-only", "-v", "%s:/probe.py:ro" % AGEPROBE_FILE,
                   "--entrypoint", "python", ctx.image_ids()[attr.RECORDER], "/probe.py", BROKER, *args, check=False, timeout=300)
        if p.returncode != 0:
            raise StackError("ageclock_probe.py failed (%d): %s" % (p.returncode, (p.stderr or p.stdout)[-1500:]))
        res = json.loads(p.stdout)
    finally:
        (out_dir / "databroker.log").write_text(container_logs(dbn), encoding="utf-8")
        remove_stack()
    res["probe"] = {"file": str(AGEPROBE_FILE.relative_to(REPO)), "sha256": sha256_file(AGEPROBE_FILE), "args": args,
                    "image": ctx.image_ids()[attr.RECORDER], "databroker": upstream_ref(ctx.images, attr.DATABROKER),
                    "catalogue_sha256": sha256_file(ctx.in_dir / "vss-databroker.json")}
    write_json(out_dir / "ageclock.json", res)
    return res


def without_default(tree: Any, path: str) -> Any:
    """A copy of a vss-tools JSON tree with one leaf's `default` removed and nothing else changed."""
    out = json.loads(json.dumps(tree))
    first, *rest = path.split(".")
    node = out[first]
    for name in rest:
        node = node["children"][name]
    node.pop("default", None)
    return out


def probe_served(entry: Dict[str, Any]) -> Any:
    """catalogue_probe.py's answer for one path read as the bridge reads it (bridge_sources.py get_value): the value
    when one is served, None when the path is unknown, has no value, or GetValue failed."""
    value = entry.get("value") if entry.get("known") else None
    return next(iter(value.values())) if isinstance(value, dict) and len(value) == 1 else None


def wheelbase_probe(ctx: Context, out_dir: Path) -> Dict[str, Any]:
    """Spec 5.6's two broker-mode branches against a throwaway databroker 0.7.1 (load_catalogue: the pinned image, one
    catalogue at a time, its own loopback-only namespace): the staged catalogue (the vehicle layer's default) and a
    copy of it with Wheelbase's default removed, each asked for Wheelbase's value by kuksa.val.v2 GetValue, as the
    bridge asks. catalogue_default() predicts the first serves its default and the second nothing; `agrees` says
    whether the databroker did. Writes wheelbase.json, the stripped copy and each databroker's log into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    staged = ctx.in_dir / "vss-databroker.json"
    bare = out_dir / "vss-databroker-no-wheelbase-default.json"
    bare.write_text(json.dumps(without_default(json.loads(staged.read_text(encoding="utf-8")), attr.WHEELBASE), indent=2) + "\n",
                    encoding="utf-8")
    cats = []
    for name, path in (("staged", staged), ("no-default", bare)):
        got = load_catalogue(ctx, name, path, [attr.WHEELBASE], out_dir)
        predicted = catalogue_default(json.loads(path.read_text(encoding="utf-8")), attr.WHEELBASE)
        probe = got.get("probe", {})
        served = probe_served(probe.get("paths", {}).get(attr.WHEELBASE, {}))
        cats.append(dict(got, predicted=predicted, served=served,
                         agrees=got.get("loads") is True and "error" not in probe and served == predicted))
    res = {"catalogues": cats, "agrees": all(c["agrees"] for c in cats),
           "probe": {"file": str(PROBE_FILE.relative_to(REPO)), "sha256": sha256_file(PROBE_FILE), "image": ctx.image_ids()[attr.RECORDER],
                     "databroker": upstream_ref(ctx.images, attr.DATABROKER)}}
    write_json(out_dir / "wheelbase.json", res)
    return res


ROAD_SURFACE = "Vehicle.Exterior.RoadSurfaceCondition"
# What the load check asks of every catalogue it loads: a slot, the mirrored speed, the attribute, the
# actuator, an AppState leaf, a node VSS 6.1 removed, one it added. The 6.1 file's enum nodes join them
# (loadcheck_probe), and a value inside the enum and one outside it are written to one of them.
PROBE_PATHS = ("Vehicle.DualVm.Motion.LongitudinalVelocity", "Vehicle.Speed", "Vehicle.Chassis.Wheelbase", HAZARD,
               "Vehicle.DualVm.AppState.HardBrakeHazard.State", "Vehicle.Powertrain.ElectricMotor.EngineCode", "Vehicle.Cabin.AirQuality.PM25")
PROBE_WRITES = (ROAD_SURFACE + "=4", ROAD_SURFACE + "=200")


def enum_nodes_of(tree: Any) -> List[str]:
    """The leaf paths of a catalogue file that carry an enum."""
    return sorted(p for p, n in attr.leaf_nodes(tree).items() if "enum" in n)


def loadcheck_probe(enum_nodes: Sequence[str]) -> List[str]:
    """catalogue_probe.py's arguments after the address: the two writes, then every path to ask about
    -- PROBE_PATHS, and every enum node of the 6.1 file (not only the one written to)."""
    args: List[str] = []
    for w in PROBE_WRITES:
        args += ["--write", w]
    paths = list(PROBE_PATHS)
    for p in [ROAD_SURFACE] + list(enum_nodes):
        if p not in paths:
            paths.append(p)
    return args + paths


def loadcheck(ctx: Context, out_dir: Path) -> Dict[str, Any]:
    """The S2 check's databroker half: databroker 0.7.1 on the generation's 6.0 catalogue and mapping and on the 6.1 files.
    A run whose run type stages another catalogue than sigsim's (a CARLA run: databroker_catalogues.carla, RECORDING KINDS
    AND RUN TYPES) has that one loaded too, as 6.0-databroker-<run type>, after the generation's sigsim catalogue; a sigsim
    run's (and a context's that read no recording) are the four of before."""
    out_dir.mkdir(parents=True, exist_ok=True)
    s2 = CACHE / "s2-check"
    raw61 = s2 / "b-mapping.json"
    stripped61 = s2 / "b-databroker.json"
    tree = json.loads(raw61.read_text(encoding="utf-8"))
    stripped61.write_text(json.dumps(attr_strip(tree, "dbc2vss"), indent=2) + "\n", encoding="utf-8")
    leaves = lambda t: len(attr.leaf_nodes(t))  # noqa: E731
    enum_nodes = enum_nodes_of(tree)
    probe = loadcheck_probe(enum_nodes)
    staged = getattr(ctx, "catalogue_file", SIGSIM_CATALOGUE)
    gen60 = [("6.0-databroker", GEN / "vss-databroker.json")]
    if staged != SIGSIM_CATALOGUE:
        gen60.append(("6.0-databroker-%s" % ctx.run_type, GEN / staged))
    gen60.append(("6.0-mapping", GEN / "vss-can-mapping.json"))
    res = {
        "note": ("VSS 6.1 + overlay generated by the stage-1 S2 check (vss-tools 6.1.0) under ~/sdv-cache/s2-check; "
                 "its overlay copy's body equals sdv/vss/overlay.vspec"),
        "enum_nodes_in_6.1_file": enum_nodes,
        "probe_args": probe,
        "RoadSurfaceCondition_in_6.1_file": {k: v for k, v in attr.leaf_nodes(tree)["Vehicle.Exterior.RoadSurfaceCondition"].items()
                                              if k in ("type", "datatype", "enum", "allowed", "min", "max")},
        "catalogues": [
            *[dict(load_catalogue(ctx, name, path, probe, out_dir), leaves_in_file=leaves(json.loads(path.read_text(encoding="utf-8"))))
              for name, path in gen60],
            dict(load_catalogue(ctx, "6.1-mapping", raw61, probe, out_dir), leaves_in_file=leaves(tree)),
            dict(load_catalogue(ctx, "6.1-databroker", stripped61, probe, out_dir), leaves_in_file=leaves(tree)),
        ],
        "s2_overlay_copy_sha256": sha256_file(s2 / "overlay.vspec"),
    }
    write_json(out_dir / "loadcheck.json", res)
    return res


def attr_strip(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return {k: attr_strip(v, key) for k, v in obj.items() if k != key}
    if isinstance(obj, list):
        return [attr_strip(v, key) for v in obj]
    return obj


# --- CLI ----------------------------------------------------------------------------------------

def new_run_dir(name: str) -> Path:
    d = RUNS / ("%s-%s" % (datetime.datetime.now().strftime("%Y%m%d"), name))
    if d.exists():
        raise StackError("%s exists: pick another --name" % d)
    return d


def up_can_provider(ctx: Context, feed: str, up_dir: Path, run_label: str, info: Dict[str, Any]) -> None:
    """`up --app external`'s CAN provider (SDV Phase 6, the CAN-provider fix), once up() has returned: started as live starts
    it (start(), so it carries the run's `<run>/up` label as the rest of the stack does), its ready line waited for with
    live's pattern and START_TIMEOUT_S; VCAN_READY_S later the `_feed` listener snapshot, written with the rest of up's
    listener record (info) to up/listeners.json. The vcan0 player of the updater's drill (drill.py run) reaches the
    databroker only through it. One that does not start or never logs its ready line (or an interrupt while it is waited
    for) takes the stack down, down's own teardown (remove_stack), the CAN provider included: nothing is left running, and
    up fails with the reason. When that teardown fails too (the daemon gone, a docker call past its timeout), up fails with
    one StackError, whatever the first failure was (an interrupt included): it names the CAN provider's reason and the
    teardown's, says the stack's containers may still be running and how to list and remove them (the __main__ handler
    prints str() alone, so nothing of it may live only in __context__)."""
    name = NAMES[attr.CAN_PROVIDER]

    def said(e: BaseException) -> str:          # a StackError by its words; an interrupt or a timeout by its type too
        return str(e) if isinstance(e, StackError) else ": ".join(x for x in (type(e).__name__, str(e)) if x)
    try:
        start(ctx, attr.CAN_PROVIDER, feed, up_dir, run_label)
        wait_log(name, r"Starting to receive CAN messages|Using DBC reader", START_TIMEOUT_S)
    except BaseException as exc:
        try:
            remove_stack()
        except Exception as teardown:          # a double fault: one error that names both, and what may be left
            raise StackError("the CAN provider (%s) failed (%s), and taking the stack down failed too (%s): containers of the "
                             "stack may still be running; `docker ps --filter label=%s` lists them and stack.py down removes them"
                             % (name, said(exc), said(teardown), LABEL)) from exc
        if isinstance(exc, StackError):
            raise StackError("the CAN provider (%s) did not start, failed its after-start hook or never logged its ready line, "
                             "so the stack was taken down "
                             "(stack.py down's teardown) and nothing is left running: %s" % (name, exc)) from exc
        raise
    time.sleep(VCAN_READY_S)
    listeners_now(info, feed, "_feed", allowances(ctx))
    write_json(up_dir / "listeners.json", info)
    print("CAN provider started: %s reads %s (its ready line logged); the listener snapshot with it running: ok %s (%s)"
          % (name, VCAN, info["listeners_feed"]["ok"], up_dir / "listeners.json"), flush=True)


# --- the ros feed (module docstring, ROS FEED; SDV Phase 8 WP3d, spec-2 2.5, 2.6, 2.7, 2.12) ---------------------------------

def host_uid() -> int:
    """The host user's uid (a seam of its own, which the tests replace)."""
    return os.getuid()


def hostcheck_run(args: Sequence[str]) -> subprocess.CompletedProcess:
    """sdv/aw/hostcheck.sh with args, under bash: no argument reads the four settings, `--compare BEFORE AFTER` compares two
    readings. It reads and never sets. The ros feed's one way to the host check, and a seam the tests replace."""
    return subprocess.run(["bash", str(HOSTCHECK)] + list(args), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)


def host_check_read(run_dir: Path, name: str) -> str:
    """The host check read into run_dir/name (HOST_BEFORE, HOST_AFTER). One that cannot be read is a StackError, and nothing
    is written then."""
    try:
        p = hostcheck_run([])
    except (OSError, subprocess.SubprocessError) as exc:
        raise StackError("the host check (sdv/aw/hostcheck.sh, spec-2 2.12) could not be run: %s" % (exc,)) from None
    if p.returncode != 0 or not p.stdout.startswith("format="):
        raise StackError("the host check (sdv/aw/hostcheck.sh, spec-2 2.12) cannot be read (exit %d): %s" % (
            p.returncode, (p.stderr or p.stdout).strip()[-300:] or "no output"))
    (run_dir / name).write_text(p.stdout, encoding="utf-8")
    return p.stdout


def host_check_after(run_dir: Path) -> Dict[str, Any]:
    """The host check read again after a sweep (HOST_AFTER) and compared with HOST_BEFORE by hostcheck.sh --compare: the
    record, also written as HOST_CHECK_RECORD. `same` is true only when both readings exist and the four settings agree;
    `changed` holds the script's `changed <setting> before=<v> after=<v>` lines; an after-reading that cannot be read, or a
    comparison that cannot be made, is `error`, never `same`."""
    rec: Dict[str, Any] = {"script": str(HOSTCHECK.relative_to(REPO)), "before": HOST_BEFORE, "after": HOST_AFTER, "same": False,
                           "changed": [], "error": None, "exit": None}
    try:
        host_check_read(run_dir, HOST_AFTER)
        p = hostcheck_run(["--compare", str(run_dir / HOST_BEFORE), str(run_dir / HOST_AFTER)])
        rec["exit"] = p.returncode
        rec["changed"] = [ln.strip() for ln in p.stdout.splitlines() if ln.startswith("changed ")]
        rec["same"] = p.returncode == 0
        if p.returncode not in (0, 1):
            rec["error"] = "the comparison failed (exit %d): %s" % (p.returncode, (p.stderr or "").strip()[-300:])
    except (StackError, OSError, subprocess.SubprocessError) as exc:
        rec["error"] = str(exc)
    write_json(run_dir / HOST_CHECK_RECORD, rec)
    return rec


def host_check_words(rec: Dict[str, Any]) -> str:
    """What a host check record says, for a run's failure or down's report."""
    if rec["same"]:
        return "the host check after the sweep: the four settings as before"
    if rec["changed"]:
        return "the host check after the sweep: %s (nothing reverted it)" % "; ".join(rec["changed"])
    return "the host check after the sweep could not be compared: %s" % rec["error"]


def load_ros_env() -> Dict[str, Any]:
    """sdv/aw/ros-env.json (2.7): its format, domain id, middleware and single-host XML, or a StackError."""
    try:
        env = json.loads(ROS_ENV_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StackError("sdv/aw/ros-env.json cannot be read: %s" % exc) from None
    if not (isinstance(env, dict) and env.get("format") == 1 and isinstance(env.get("ros_domain_id"), int)
            and not isinstance(env.get("ros_domain_id"), bool) and isinstance(env.get("rmw"), str)
            and isinstance(env.get("cyclonedds_single_host"), str)):
        raise StackError("sdv/aw/ros-env.json is not spec-2 2.7's {format 1, ros_domain_id, rmw, cyclonedds_single_host}")
    return env


def rosvss_mapping() -> Any:
    """sdv/rosvss/mapping.py (WP3a's, read only; standard library only), loaded by its file under a name of the stack's own,
    for the feeder's configured write set. Its plain `import update` finds sdv/rosvss/update.py, loaded under a name of the
    stack's own too; sys.path and sys.modules' `update` are put back after."""
    key = "_sdv_rosvss_mapping_for_stack"
    if key in sys.modules:
        return sys.modules[key]
    import importlib.util
    missing = object()
    saved_update, saved_path = sys.modules.get("update", missing), list(sys.path)
    try:
        uspec = importlib.util.spec_from_file_location("_sdv_rosvss_update_for_stack", str(ROSVSS_DIR / "update.py"))
        mspec = importlib.util.spec_from_file_location(key, str(ROSVSS_DIR / "mapping.py"))
        if uspec is None or uspec.loader is None or mspec is None or mspec.loader is None:
            raise StackError("cannot load %s" % ROSVSS_DIR)
        umod = importlib.util.module_from_spec(uspec)
        uspec.loader.exec_module(umod)
        sys.modules["update"] = umod
        mod = importlib.util.module_from_spec(mspec)
        mspec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved_path
        if saved_update is missing:
            sys.modules.pop("update", None)
        else:
            sys.modules["update"] = saved_update          # type: ignore[assignment]
    sys.modules[key] = mod
    return mod


def rosvss_image(images: Dict[str, Any]) -> Dict[str, Any]:
    """The feeder's image, images.json's rosvss.amd64 pin, inspected and never built here: present by its ID; that ID its
    own; linux/amd64; its labels the pin's (whose base digest is images.json's autoware.amd64 manifest digest); its
    entrypoint the project's (AW_ENTRYPOINT: the base's /docker-entrypoint.sh never runs, 2.12); its user aw; and its tag,
    when present, naming the same image (another ID there is a rebuild without a re-pin). Any other is refused."""
    entry, aw = images.get("rosvss") or {}, images.get("autoware") or {}
    pin, want, base = entry.get("amd64") or {}, entry.get("labels") or {}, (aw.get("amd64") or {}).get("manifest_digest")
    if not (isinstance(pin.get("id"), str) and want and isinstance(base, str)):
        raise StackError("images.json has no rosvss.amd64 pin, rosvss labels or autoware.amd64 manifest digest: build the feeder's "
                         "image with sdv/rosvss/build_image.py and pin it (spec-2 2.6)")
    if want.get("sdv.rosvss.base_digest") != base:
        raise StackError("images.json's rosvss labels name the base %s, its autoware.amd64 manifest digest is %s" % (
            want.get("sdv.rosvss.base_digest"), base))
    info, why = inspect_image(pin["id"])
    if info is None:
        raise StackError("the feeder's image %s (images.json rosvss.amd64) is not present: build it with sdv/rosvss/build_image.py "
                         "and pin it (%s)" % (pin["id"], why))
    if info.get("Id") != pin["id"]:
        raise StackError("images.json's rosvss.amd64 names %s, whose image ID is %s" % (pin["id"], info.get("Id")))
    if info.get("Architecture") != "amd64":
        raise StackError("the feeder's image %s is linux/%s, not amd64 (its one architecture, spec-2 section 0 item 5)" % (
            pin["id"], info.get("Architecture")))
    config = info.get("Config") or {}
    labels = config.get("Labels") or {}
    wrong = {k: {"image": labels.get(k), "pinned": v} for k, v in sorted(want.items()) if labels.get(k) != v}
    if wrong:
        raise StackError("the feeder's image %s does not carry images.json's rosvss labels: %s" % (pin["id"], wrong))
    entrypoint = config.get("Entrypoint")
    if entrypoint != [AW_ENTRYPOINT]:
        raise StackError("the feeder's image %s has the entrypoint %r, not the project's [%r]: the base's would run (spec-2 2.12)"
                         % (pin["id"], entrypoint, AW_ENTRYPOINT))
    user = str(config.get("User") or "")
    if user.split(":")[0] != AW_USER:
        raise StackError("the feeder's image %s runs as %r, root or no user of its own: its image names %s (spec-2 2.12)"
                         % (pin["id"], user, AW_USER))
    tagged, _why = inspect_image(pin["tag"])
    if tagged is not None and tagged.get("Id") != pin["id"]:
        raise StackError("the tag %s names %s, not images.json's %s: the image was rebuilt without a re-pin (sdv/rosvss/build_image.py "
                         "prints the pin)" % (pin["tag"], tagged.get("Id"), pin["id"]))
    return {"class": "platform", "form": "container", "image_id": pin["id"], "config_digest": pin["config_digest"], "tag": pin["tag"],
            "labels": dict(want), "base_digest": base, "entrypoint": list(entrypoint), "user": user, "arch": "amd64",
            "pull": {"via": "local-build", "built_by": "sdv/rosvss/build_image.py", "pin": "images.json rosvss.amd64"},
            "note": "the ROS->VSS feeder (sdv/rosvss): a platform component, never an OTA target; built FROM the Autoware image's "
                    "amd64 manifest digest, its own entrypoint the project's"}


def run_opt_values(args: Sequence[str], long: str, short: Optional[str] = None) -> List[str]:
    """Every value args give the docker run option `long` (--x V, --x=V) or its short form (-c V, -cV, -c=V, and after a
    cluster of docker run's boolean short options, RUN_BOOL_SHORTS: -dc V, -dcV). The whole vector is read, the
    container's command too, so a word there can only add a value, never hide one."""
    out = []
    for i, a in enumerate(args):
        nxt = args[i + 1] if i + 1 < len(args) else None
        if a == long:
            if nxt is not None:
                out.append(nxt)
        elif a.startswith(long + "="):
            out.append(a[len(long) + 1:])
        elif short and a.startswith("-") and not a.startswith("--"):
            body = a[1:].lstrip(RUN_BOOL_SHORTS)
            if body[:1] == short:
                rest = body[2:] if body[1:2] == "=" else body[1:]
                if rest:
                    out.append(rest)
                elif nxt is not None:
                    out.append(nxt)
    return out


def aw_argv_problems(argv: Sequence[str]) -> List[str]:
    """What spec-2 2.12 forbids in a `docker run` of a container from the Autoware image or built on it, read from its
    argument vector, each option in every form docker takes (run_opt_values): --privileged; --cap-add of any capability;
    less than --cap-drop ALL; no --security-opt no-new-privileges; another user than --user aw (-u counted), or a second;
    the host's pid, ipc, user, uts or cgroup namespace (HOST_NAMESPACES); a mount of /proc or /sys (or below either), as
    source or target; a mount of the host's root or of the docker socket; the X11 socket; a display (DISPLAY,
    XAUTHORITY). Empty when none."""
    args = [str(a) for a in argv]
    problems = []
    if any(a == "--privileged" or a.startswith("--privileged=") for a in args):
        problems.append("--privileged")
    if any(a == "--cap-add" or a.startswith("--cap-add=") for a in args):
        problems.append("--cap-add (a capability given)")
    if "ALL" not in run_opt_values(args, "--cap-drop"):
        problems.append("no --cap-drop ALL")
    if "no-new-privileges" not in run_opt_values(args, "--security-opt"):
        problems.append("no --security-opt no-new-privileges")
    users = run_opt_values(args, "--user", "u")
    if users != [AW_USER]:
        problems.append("not --user aw (the user given: %s)" % (", ".join(users) or "none"))
    for ns in HOST_NAMESPACES:
        if "host" in run_opt_values(args, ns):
            problems.append("%s host (the host's %s namespace)" % (ns, ns[2:]))
    mounts = run_opt_values(args, "--volume", "v") + run_opt_values(args, "--mount")
    for m in mounts:
        if m.startswith("type="):
            fields = dict(f.split("=", 1) for f in m.split(",") if "=" in f)
            paths = [fields.get(k, "") for k in ("src", "source", "dst", "destination", "target")]
            source = fields.get("src") or fields.get("source") or ""
        else:
            paths = m.split(":")[:2]
            source = paths[0]
        for p in paths:
            q = p.rstrip("/") or "/"
            if q in ("/proc", "/sys") or q.startswith(("/proc/", "/sys/")):
                problems.append("a mount of %s (%s)" % (q, m))
        if source.startswith("/") and source.rstrip("/") == "":
            problems.append("a mount of the host's root / (%s)" % m)
        if source.rstrip("/").endswith("/docker.sock"):
            problems.append("the docker socket mounted (%s)" % m)
        if ".X11-unix" in m:
            problems.append("the X11 socket mounted (%s)" % m)
    for e in run_opt_values(args, "--env", "e"):
        if e.split("=", 1)[0] in ("DISPLAY", "XAUTHORITY"):
            problems.append("a display for X11 (%s)" % e)
    return problems


def feeder_argv(ctx: Any, up_dir: Path, run_label: str) -> List[str]:
    """The feeder's `docker run`: the stack's label and ROS_LABEL (the run directory), COMMON (and the cpuset), the host's
    network, --user aw, in/ read-only (in/cyclonedds.xml) and up/ros-log as ROS_LOG_DIR, 2.7's environment, the image by
    images.json's ID, and the command: the venv's Python, feeder_node.py, --run-type planning-sim, the databroker's
    loopback address. Its own entrypoint (the image's, the project's)."""
    env = ctx.ros_env
    return (["run", "-d", "--name", FEEDER_CONTAINER, "--label", "%s=%s" % (LABEL, run_label), "--label", "%s=%s" % (ROS_LABEL, ctx.run_dir)]
            + common_flags(ctx)
            + ["--network", "host", "--user", AW_USER,
               "-v", "%s:%s:ro" % (ctx.in_dir, ROS_IN), "-v", "%s:%s" % (up_dir / ROS_LOG_DIR_NAME, ROS_LOG_IN),
               "-e", "ROS_DOMAIN_ID=%d" % env["ros_domain_id"], "-e", "RMW_IMPLEMENTATION=%s" % env["rmw"],
               "-e", "CYCLONEDDS_URI=file://%s/%s" % (ROS_IN, CYCLONEDDS_FILE), "-e", "ROS_LOG_DIR=" + ROS_LOG_IN,
               ctx.components[FEEDER]["image_id"], FEEDER_PYTHON, FEEDER_PROGRAM, "--run-type", ROS_RUN_TYPE, "--databroker", BROKER])


def start_feeder(ctx: Any, up_dir: Path, run_label: str) -> str:
    """The feeder's container (feeder_argv), refused before docker runs when aw_argv_problems finds anything; the hook after
    it (PLACEMENT); started once it logs its start record (its start checks passed: the databroker serves its write set)
    and still runs after it (feeder_settled)."""
    argv = feeder_argv(ctx, up_dir, run_label)
    bad = aw_argv_problems(argv)
    if bad:
        raise StackError("the feeder's docker run is refused (spec-2 2.12): %s" % "; ".join(bad))
    (up_dir / ROS_LOG_DIR_NAME).mkdir(parents=True, exist_ok=True)
    docker(*argv)
    run_after_start(ctx, FEEDER_CONTAINER)
    wait_log(FEEDER_CONTAINER, FEEDER_READY, START_TIMEOUT_S)
    feeder_settled()
    return FEEDER_CONTAINER


def feeder_settled() -> None:
    """The feeder's state read again through FEEDER_SETTLE_S after its start record, every FEEDER_SETTLE_POLL_S and at least
    once: feeder_node.py (WP3a's) logs that record before rclpy.init, its node and its subscriptions, so a feeder whose ROS
    side fails (its DDS file, its log directory) ends just after the line wait_log took. One that is not running is a
    StackError with its last log lines."""
    end = time.monotonic() + FEEDER_SETTLE_S
    while True:
        st = docker("inspect", "-f", "{{.State.Running}}", FEEDER_CONTAINER, check=False)
        if st.stdout.strip() != "true":
            raise StackError("%s exited right after its start record (its ROS side did not come up: rclpy, its node or a "
                             "subscription):\n%s" % (FEEDER_CONTAINER, container_logs(FEEDER_CONTAINER)[-1500:]))
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(FEEDER_SETTLE_POLL_S, left))


class RosContext(Context):
    """A ros feed's context (module docstring, ROS FEED): no recording. The run type is planning-sim, the profile the
    planning-sim live default (profile_source live-default, with a bridge), the source vehicle that profile's, the
    generation's planning-sim catalogue staged as a recording's run type's is, the scenario table attribution.py's
    planning-sim table."""

    def __init__(self, run_dir: Path, bridge: str = "none", monitor: str = "native", guest_host: Optional[str] = None,
                 guest_console: Optional[Any] = None, guest_image: Optional[Any] = None) -> None:
        if bridge not in REPLAY_BRIDGE_MODES:
            raise StackError("--feed ros takes --bridge %s, not %r" % (" or ".join(REPLAY_BRIDGE_MODES), bridge))
        super().__init__(run_dir, None, bridge, monitor, guest_host, guest_console, guest_image)
        self.run_type = ROS_RUN_TYPE
        self.feed = ROS_FEED
        self.ros_env: Dict[str, Any] = {}

    def prepare(self, pull: bool = True, build: bool = True, bridge_parts: Optional[bool] = None, images: str = "build") -> Dict[str, Any]:
        """Check the generation, the profile, the feeder's image and the host user, pull the databroker and build the recorder
        image (the witness's), take the bridge's parts, stage in/, write the scenario table and the run manifest. Every
        refusal before anything is written; a failed table check after the manifest is written, as Context's."""
        if images != "build":
            raise StackError(ROS_NOT_LOADED)
        bridge_parts = build if bridge_parts is None else bridge_parts
        c = self.contract
        man = generation_manifest()
        pair = generation_pair(man, ROS_RUN_TYPE)
        live = dict(getattr(c, "LIVE_DEFAULT_PROFILE", {}) or {}).get(ROS_RUN_TYPE)
        prof = {int(p["id"]): p for p in c.PROFILES}.get(live) if isinstance(live, int) else None
        if prof is None:
            raise StackError("the generation names no planning-sim live-default profile in its table (regenerate with sdv/vss/generate.py)")
        pid = int(prof["id"])
        compiled = tuple(getattr(c, "COMPILED_PROFILE_IDS", ()))
        if self.bridge == "broker" and pid not in compiled:
            raise StackError("--bridge broker with --feed ros needs profile %d (the planning-sim live default) compiled, and the "
                             "generation compiles %s: the bridge and the monitor would give every frame reason 8 (spec-2 2.5)"
                             % (pid, list(compiled)))
        dbc_sha = (man.get("inputs") or {}).get("slice.dbc")
        if not isinstance(dbc_sha, str):
            raise StackError("sdv-out/gen's manifest.json names no slice.dbc input (regenerate with sdv/vss/generate.py)")
        cat = catalogue_identity(c, dbc_sha, pair)
        layer = pair["vehicle_layer"]
        vehicle: Dict[str, Any] = {"name": str(prof["source_vehicle"]), "wheelbase_mm": int(prof["l_mm"])}
        self.catalogue_file = pair["catalogue"]
        self.catalogue_tree = json.loads((GEN / pair["catalogue"]).read_text(encoding="utf-8"))
        self.catalogue = attr.leaf_nodes(self.catalogue_tree)
        self.wheelbase = served_wheelbase(self.catalogue_tree, vehicle["wheelbase_mm"], vehicle, layer) if self.bridge == "broker" else None
        self.ros_env = load_ros_env()
        if host_uid() != AW_UID:
            raise StackError("the host user's uid %d is not the feeder image's aw (uid %d): the run's up/ros-log, the host user's "
                             "directory, would not be aw's to write (spec-2 2.12: never mode 777)" % (host_uid(), AW_UID))
        feeder = rosvss_image(self.images)
        feeder_writes = sorted(rosvss_mapping().write_set(ROS_RUN_TYPE))
        self.bridge_writes = bridge_writes(c) if self.bridge == "broker" else []
        self.witness_paths = sorted(set(feeder_writes) | set(self.bridge_writes))     # what the configured writers write
        self.rows = attr.planning_sim_rows(self.catalogue, layer["file"], bridge_writes=self.bridge_writes, witnessed=self.witness_paths)
        write_sets: Dict[str, Iterable[str]] = {FEEDER: feeder_writes}
        if self.bridge_writes:
            write_sets[attr.BRIDGE] = list(self.bridge_writes)
        checks = attr.check_planning_sim(self.rows, self.catalogue, write_sets, layer["file"], bridge_mode=self.bridge,
                                         witnessed=self.witness_paths)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if pull:
            self.components.update(pull_upstream(dict(self.images, upstream={attr.DATABROKER: self.images["upstream"][attr.DATABROKER]})))
        if build:
            self.components.update(build_local(dict(self.images, local={attr.RECORDER: self.images["local"][attr.RECORDER]})))
            self.components[WITNESS] = {
                "class": "platform", "form": "container", "image_id": self.components[attr.RECORDER]["image_id"], "runs_in": attr.RECORDER,
                "program": str(WITNESS_FILE.relative_to(REPO)), "program_sha256": sha256_file(WITNESS_FILE),
                "note": "the recorder image with --entrypoint python and the program mounted read-only, on the planning-sim table's "
                        "owned paths; a reader, not a writer"}
        if bridge_parts and self.bridge != "none":
            self.components[attr.BRIDGE] = bridge_image(c, dbc_sha)
            if self.guest is not None:
                self.components[VSS_MONITOR_GUEST] = guest_component(self.guest)
            else:
                self.components[VSS_MONITOR] = build_native_monitor(self.run_dir / "bin" / MONITOR_BIN)
        self.components[FEEDER] = feeder
        self.in_dir.mkdir(exist_ok=True)
        shutil.copyfile(GEN / pair["catalogue"], self.in_dir / SIGSIM_CATALOGUE)
        (self.in_dir / CYCLONEDDS_FILE).write_text(self.ros_env["cyclonedds_single_host"], encoding="utf-8")
        self.staged = {k: sha256_file(self.in_dir / k) for k in sorted(os.listdir(self.in_dir))}
        failed = [ch for ch in checks if not ch[1]]
        self.scenario = {"format": 1, "scenario": ROS_RUN_TYPE, "recording": None, "feed": ROS_FEED, "dbc_sha256": "sha256:" + dbc_sha,
                         "source": {"generator": ROS_RUN_TYPE, "feed": ROS_FEED, "feeder": "sdv/rosvss/feeder_node.py", "vehicle": vehicle},
                         "profile_id": pid, "rows": self.rows}
        self.ownership_sha256 = write_json(self.run_dir / "ownership.json", self.scenario)
        catalogue_sha = "sha256:" + sha256_file(GEN / pair["catalogue"])
        self.manifest = {
            "format": 1, "run": self.run_dir.name, "utc_prepared": utc_now(), "host_role": self.host_role,
            "placement": placement_record(self.cpuset, self.after_start), "run_type": ROS_RUN_TYPE, "feed": ROS_FEED,
            "app": None, "app_note": "a ros run starts no app (spec-2 2.5)",
            "stack_files": {str(p.relative_to(REPO)): sha256_file(p) for p in sorted(
                [HERE / "stack.py", HERE / "attribution.py", IMAGES_FILE, WITNESS_FILE, HOSTCHECK, ROS_ENV_FILE, AW_DIR / "aw-entrypoint.sh",
                 ROSVSS_DIR / "mapping.py", ROSVSS_DIR / "Dockerfile", ROSVSS_DIR / "requirements.lock", HERE / "recorder" / "Dockerfile",
                 HERE / "recorder" / "requirements.lock"])},
            "bridge": {"mode": self.bridge, "writes": list(self.bridge_writes), "wheelbase": self.wheelbase, "monitor": self.monitor_mode,
                       "note": ROS_BRIDGE_NOTES[self.bridge]},
            "docker": {"server": docker("version", "-f", "{{.Server.Version}}").stdout.strip(),
                       "storage": docker("info", "-f", "{{.Driver}} {{json .DriverStatus}}").stdout.strip(),
                       "image_id_note": "under the containerd image store a pulled image's ID is its index digest", "images": images,
                       "images_note": "--images build: the databroker pulled by index digest, the recorder image built here, the "
                                      "feeder's image taken by images.json's ID (sdv/rosvss/build_image.py built it)"},
            "components": self.components,
            "catalogue": cat,
            "recording": None,
            "ros_feed": {
                "run_type": ROS_RUN_TYPE, "feeder_image_id": feeder["image_id"], "feeder_config_digest": feeder["config_digest"],
                "feeder_base_digest": feeder["base_digest"], "catalogue": pair["catalogue"], "catalogue_sha256": catalogue_sha,
                "vehicle_layer": layer, "profile_id": pid, "profile_compiled": pid in compiled, "source_vehicle": vehicle,
                "ros_env": {"ros_domain_id": self.ros_env["ros_domain_id"], "rmw": self.ros_env["rmw"],
                            "cyclonedds_single_host_sha256": self.staged[CYCLONEDDS_FILE]},
                "witness_paths": list(self.witness_paths), "topics": list(ROS_FEED_PUBLISHERS), "publishers": ROS_FEED_PUBLISHERS,
                "host_check": {"script": str(HOSTCHECK.relative_to(REPO)), "before": HOST_BEFORE, "after": HOST_AFTER,
                               "record": HOST_CHECK_RECORD},
                "note": "the feeder writes what Autoware's planning simulator and the claim node publish into the databroker; the "
                        "stack starts neither of those, and the ROS logs stay in up/ros-log, never captured"},
            "staged_inputs_sha256": self.staged,
            "scenario_table": {"file": "ownership.json", "sha256": "sha256:" + self.ownership_sha256,
                               "note": "the planning-sim table (attribution.py, spec-2 2.5)"},
            "scenario_checks": [list(ch) for ch in checks],
            "time_sync": dict(time_sync(), age_clock=age_clock(self.bridge)),
        }
        write_json(self.run_dir / "manifest.json", self.manifest)
        if failed:
            raise StackError("scenario table checks failed: %s" % failed)
        return self.manifest

    def run_header(self, replay_id: str, feed: str) -> Dict[str, Any]:
        """The ros feed's run header: run_type planning-sim, feed ros, no recording, source_rtf null; with a bridge the
        planning-sim live default (profile_source live-default) and the generated AGE_MAX, without one all null."""
        sc = self.scenario
        bridge = self.bridge != "none"
        return {
            "run_id": "%sT-%s-vss-%s-%s" % (self.run_dir.name[:8], self.host_role, sc["scenario"], replay_id),
            "utc_start": utc_now(),
            "host_role": self.host_role,
            "run_type": ROS_RUN_TYPE,
            "feed": ROS_FEED,
            "bridge_mode": self.bridge,
            "profile_id": sc["profile_id"] if bridge else None,
            "profile_source": "live-default" if bridge else None,
            "source_vehicle": dict(sc["source"]["vehicle"]),
            "age_max_ms": int(self.contract.AGE_MAX_MS) if bridge else None,
            "demo_odd_window": None,
            "time_sync": dict(self.manifest["time_sync"]),
            "source_rtf": None,
            "catalogue": self.manifest["catalogue"],
            "scenario": {"name": sc["scenario"], "ownership_sha256": "sha256:" + self.ownership_sha256},
            "recordings": [],
            "dbc_sha256": sc["dbc_sha256"],
            "allowlist_version": attr.ALLOWLIST_VERSION,
            "header_check": None,
        }


def ros_listeners_now(info: Dict[str, Any], ctx: Any) -> None:
    """The listener snapshot of a ros run, judged against the one before it started, the feeder's processes counted as the
    stack's (it is in neither NAMES nor CONTAINERS) and the native monitor's listener allowed by its PID."""
    allowed = allowances(ctx)
    info["listeners_during"] = host_listeners()
    pids = set(stack_pids([a["pid"] for a in allowed]))
    p = docker("top", FEEDER_CONTAINER, "-eo", "pid", check=False)
    if p.returncode == 0:
        pids |= {int(x) for x in p.stdout.split()[1:] if x.isdigit()}
    info["listeners"] = listener_verdict(info["listeners_before"], info["listeners_during"], None, sorted(pids), allowed)


def ros_sweep(ctx: Any) -> str:
    """A failed ros up's sweep: the native monitor stopped, every container of the stack removed, the host check read after
    and compared (host_check_after). Returns what the host check says."""
    if getattr(ctx, "monitor", None) is not None:
        ctx.monitor.stop()
        ctx.monitor = None
    remove_stack()
    return host_check_words(host_check_after(ctx.run_dir))


def up_ros(ctx: Any, up_dir: Path, run_label: str) -> Dict[str, Any]:
    """The ros feed's up (module docstring, ROS FEED): refused while a ros run is left (refuse_ros_runs_left), before
    anything is swept or read; C12a on the run header; the host check read (refused when it cannot be read), the run's
    first host reading, so a run refused before it leaves no open directory; then the stack: in broker mode the native
    monitor (or the guest's, started by nothing here), the databroker, the witness on the owned paths, the claim bridge,
    and the feeder last; C8 once it runs; the listener snapshot; the records in up/. A native monitor is left running, its
    pid in up/monitor.json, for down to stop. Any failure sweeps the run (ros_sweep) and goes on with the host check's
    words added; an interrupt goes on as it was, after the sweep. A sweep that fails too is one StackError that names both."""
    refuse_ros_runs_left()
    header = ctx.run_header("up", ROS_FEED)
    checks: List[attr.Check] = [ctx.check_header(header)]
    if not checks[0][1]:
        raise StackError("C12a failed: %s" % checks[0][2])
    up_dir.mkdir(parents=True, exist_ok=True)
    host_check_read(ctx.run_dir, HOST_BEFORE)
    remove_stack()
    info: Dict[str, Any] = {"feed": ROS_FEED, "listeners_before": host_listeners()}
    try:
        if ctx.bridge != "none":
            if monitor_mode(ctx) == "guest":
                info["monitor"] = guest_info(ctx)
            else:
                start_monitor(ctx, up_dir, info)
        start(ctx, attr.DATABROKER, ROS_FEED, up_dir, run_label)
        wait_log(NAMES[attr.DATABROKER], r"Listening on 127\.0\.0\.1:%d" % BROKER_PORT, START_TIMEOUT_S)
        start(ctx, WITNESS, ROS_FEED, up_dir, run_label)
        wlog = up_dir / WITNESS_LOG

        def witness_ready() -> bool:
            st = docker("inspect", "-f", "{{.State.Running}}", NAMES[WITNESS], check=False)
            if st.stdout.strip() != "true":
                raise StackError("the witness stopped before it subscribed:\n%s" % container_logs(NAMES[WITNESS])[-1500:])
            return wlog.exists() and any(r.get("event") == "subscribed" for r in rc.read_witness(wlog, strict=False)["records"])
        wait_for(witness_ready, START_TIMEOUT_S, "the witness's subscription")
        if ctx.bridge != "none":
            start_bridge(ctx, ROS_FEED, up_dir, run_label, header)
        start_feeder(ctx, up_dir, run_label)
        rows = attr.run_rows(ctx.rows, ctx.image_ids())
        running = running_images()
        p = docker("inspect", "-f", "{{.State.Running}} {{.Image}}", FEEDER_CONTAINER, check=False)
        state = p.stdout.split() if p.returncode == 0 else []
        if len(state) == 2 and state[0] == "true":          # an exited feeder still names its image: it is no writer
            running[FEEDER] = state[1]
        checks.append(attr.check_images(rows, running))
        write_json(up_dir / "attribution.json", {"header": header, "rows": rows, "scenario_checks": ctx.manifest["scenario_checks"],
                                                 "checks": [list(ch) for ch in checks]})
        (up_dir / "attribution.md").write_text(attr.render_markdown(header, rows), encoding="utf-8")
        if not checks[-1][1]:
            raise StackError("C8 failed: %s" % checks[-1][2])
        ros_listeners_now(info, ctx)
        write_json(up_dir / "listeners.json", info)
        if ctx.monitor is not None:
            write_json(up_dir / MONITOR_RECORD, {"pid": ctx.monitor.pid, "binary": ctx.monitor.argv[0],
                                                 "argv": [Path(ctx.monitor.argv[0]).name] + list(ctx.monitor.argv[1:]),
                                                 "log": str(ctx.monitor.log)})
            ctx.monitor = None              # left running: down stops it (stop_left_monitor)
        return info
    except BaseException as exc:
        def said(e: BaseException) -> str:
            return str(e) if isinstance(e, StackError) else ": ".join(x for x in (type(e).__name__, str(e)) if x)
        try:
            words = ros_sweep(ctx)
        except Exception as sweep:
            raise StackError("the ros run failed (%s), and its sweep failed too (%s): containers of the stack may still be running; "
                             "`docker ps --filter label=%s` lists them and stack.py down removes them" % (said(exc), said(sweep), LABEL)) from exc
        if isinstance(exc, StackError):
            raise StackError("the ros run failed and was swept (every container of the stack removed): %s; %s" % (exc, words)) from exc
        raise


def proc_argv0(pid: int) -> Optional[str]:
    """The first word of /proc/<pid>/cmdline, or None when the process is gone (or a zombie, whose cmdline is empty)."""
    try:
        raw = Path("/proc/%d/cmdline" % pid).read_bytes()
    except OSError:
        return None
    word = raw.split(b"\0", 1)[0]
    return word.decode("utf-8", "replace") if word else None


def signal_process(pid: int, sig: int) -> None:
    """os.kill, a process that has gone in between taken as stopped."""
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


def stop_left_monitor(up_dir: Path) -> Optional[Dict[str, Any]]:
    """The native monitor a ros up left running (up/monitor.json), stopped by down: SIGTERM only while /proc says its pid
    runs the monitor's binary (any other process holding the pid is left alone), SIGKILL after MONITOR_STOP_S. Its record
    goes to up/monitor-stop.json; None when the run left none."""
    path = up_dir / MONITOR_RECORD
    if not path.is_file():
        return None
    rec = json.loads(path.read_text(encoding="utf-8"))
    pid, binary = int(rec["pid"]), str(rec["binary"])
    out: Dict[str, Any] = {"pid": pid, "binary": binary}
    if proc_argv0(pid) != binary:
        out["stopped"] = "not running it any more (the process ended, or another holds its pid): left alone"
    else:
        signal_process(pid, signal.SIGTERM)
        end = time.monotonic() + MONITOR_STOP_S
        while proc_argv0(pid) == binary and time.monotonic() < end:
            time.sleep(0.2)
        if proc_argv0(pid) == binary:
            signal_process(pid, signal.SIGKILL)
            out["stopped"] = "on SIGKILL, %g s after SIGTERM" % MONITOR_STOP_S
        else:
            out["stopped"] = "on SIGTERM"
    write_json(up_dir / "monitor-stop.json", out)
    return out


def ros_runs_up() -> List[Path]:
    """The run directories of the ros runs whose containers are there (ROS_LABEL on the feeder), for down; none when docker
    cannot list them (remove_stack, which comes next, then says why)."""
    p = docker("ps", "-a", "--filter", "label=" + ROS_LABEL, "--format", '{{index .Labels "%s"}}' % ROS_LABEL, check=False)
    if p.returncode != 0:
        return []
    return sorted({Path(x.strip()) for x in (p.stdout or "").splitlines() if x.strip()})


def ros_runs_open() -> List[Path]:
    """The run directories under RUNS of the ros runs not closed yet: the manifest says feed ros, host-before.txt is there
    and host-check.json, which host_check_after always writes (a comparison that could not be made included), is not.
    Every other start removes the stack's containers first, the feeder and its label with them, and leaves these: so down
    still finds such a run."""
    try:
        dirs = sorted(d for d in RUNS.iterdir() if d.is_dir())
    except OSError:
        return []
    out = []
    for d in dirs:
        if not (d / HOST_BEFORE).is_file() or (d / HOST_CHECK_RECORD).exists():
            continue
        try:
            feed = json.loads((d / "manifest.json").read_text(encoding="utf-8")).get("feed")
        except (OSError, ValueError, AttributeError):
            continue
        if feed == ROS_FEED:
            out.append(d)
    return out


def ros_runs_left() -> List[Path]:
    """The ros runs down has to close: those whose feeder is there (ros_runs_up) and those whose directory is open
    (ros_runs_open)."""
    return sorted(set(ros_runs_up()) | set(ros_runs_open()))


def refuse_ros_runs_left() -> None:
    """A ros up while a ros run is left is refused: its sweep would remove that run's feeder and with it the label
    down finds the run by, but neither stop the native monitor the run left (which holds :7160) nor read its host check
    after the sweep (spec-2 2.12)."""
    left = ros_runs_left()
    if left:
        raise StackError("a ros run is still up (%s): stack.py down first, which stops its native monitor and reads its host "
                         "check after the sweep; this up's sweep would do neither (spec-2 2.12)" % ", ".join(str(p) for p in left))


def down_ros(runs: Sequence[Path]) -> None:
    """down's part for the ros runs it found (ros_runs_left, read before remove_stack): each run's native monitor stopped
    (stop_left_monitor) and its host check read after the sweep and compared; any difference, or an after-reading that
    cannot be compared, fails down with the setting named. Nothing is reverted."""
    problems = []
    for run_dir in runs:
        stop_left_monitor(run_dir / "up")
        if not (run_dir / HOST_BEFORE).is_file():
            problems.append("%s: no %s to compare with" % (run_dir, HOST_BEFORE))
            continue
        rec = host_check_after(run_dir)
        if rec["same"]:
            print("%s: %s" % (run_dir.name, host_check_words(rec)), flush=True)
        else:
            problems.append("%s: %s" % (run_dir.name, host_check_words(rec)))
    if problems:
        raise StackError("the ros run's host check failed (spec-2 2.12): %s" % "; ".join(problems))


def ros_cli_refusals(a: argparse.Namespace) -> None:
    """The ros feed's refusals the command line decides (module docstring, ROS FEED), before a context is made, docker is
    asked or anything is written: replay and exit-test with it; on up, --run-type, --bridge and the monitor options on
    another feed; with it, another run type or none, --app, --connector, --seed, --images loaded, a host role but pc,
    the monitor options without --bridge broker, and the guest's options without --monitor guest."""
    if a.cmd == "replay" and a.feed == ROS_FEED or a.cmd == "exit-test" and ROS_FEED in a.feeds:
        raise StackError(ROS_NOT_REPLAYED)
    if a.cmd != "up":
        return
    monitor_opts = [x for x in (a.monitor, a.guest_host, a.guest_console, a.guest_image) if x is not None]
    if a.feed != ROS_FEED:
        if a.run_type is not None:
            raise StackError(RUN_TYPE_NEEDS_ROS)
        if a.bridge is not None:
            raise StackError(UP_BRIDGE_IS_ROS)
        if monitor_opts:
            raise StackError(UP_MONITOR_IS_ROS)
        return
    if a.run_type != ROS_RUN_TYPE:
        raise StackError(ROS_NEEDS_PLANNING_SIM)
    if a.app is not None:
        raise StackError(ROS_NO_APP)
    if a.connector:
        raise StackError(ROS_NO_CONNECTOR)
    if a.seed is not None:
        raise StackError(ROS_NO_SEED)
    if a.images != "build":
        raise StackError(ROS_NOT_LOADED)
    if host_role() != "pc":
        raise StackError(ROS_PC_ONLY % host_role())
    if monitor_opts and (a.bridge or "none") != "broker":
        raise StackError(MONITOR_NEEDS_BROKER)
    if a.monitor != "guest" and (a.guest_host, a.guest_console, a.guest_image) != (None, None, None):
        raise StackError("the guest's host, console and image are guest mode's (--monitor guest), not the native monitor's")


def ros_main(a: argparse.Namespace) -> int:
    """`up --feed ros --run-type planning-sim` (module docstring, ROS FEED), its command-line refusals already made. The
    context gets the monitor mode (native when none is given) and the three guest options as given, every time, so that
    Context's own refusals see them too (the guest's options without --monitor guest among them, which ros_cli_refusals
    refuses first); then a ros run left is refused; both before anything is written."""
    bridge = a.bridge or "none"
    refuse_bridge_in_twin_control(bridge)
    run_dir = new_run_dir(a.name)
    ctx = RosContext(run_dir, bridge, monitor=a.monitor or "native", guest_host=a.guest_host, guest_console=a.guest_console,
                     guest_image=a.guest_image)
    refuse_ros_runs_left()
    ctx.prepare(images=a.images)
    print("prepared %s" % run_dir, flush=True)
    info = up_ros(ctx, run_dir / "up", "%s/up" % run_dir.name)
    print(json.dumps(info["listeners"], indent=1))
    print("stack running (the ros feed, run type planning-sim); stop it with: stack.py down, which reads the host check again "
          "after its sweep")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("prepare", "replay", "exit-test", "up", "loadcheck", "ageprobe", "wheelbaseprobe"):
        s = sub.add_parser(cmd)
        s.add_argument("--name", default={"exit-test": "phase1-exit"}.get(cmd, cmd))
        s.add_argument("--seed", type=int, default=None,
                       help="optional: refused unless it equals the recording's seed (its manifest line), which is the one used")
        s.add_argument("--images", choices=IMAGE_MODES, default="build",
                       help="build (default): pull the upstream images and build the local ones; loaded: an aarch64 host whose "
                            "images were pulled and loaded before the run, inspected here and never pulled or built")
        if cmd in ("replay", "up"):
            s.add_argument("--feed", choices=FEEDS + (ROS_FEED,), default="dumpfile",
                           help="dumpfile (default) or vcan: replay a recording; ros: up's alone (ROS FEED in the docstring)")
            s.add_argument("--connector", action="store_true",
                           help="the twin connector runs too (SDV_CONNECTOR_IMAGE, SDV_DEVICE_DIR); needs --feed vcan")
        if cmd == "up":
            s.add_argument("--app", choices=APP_MODES, default=None,
                           help="stack (default): this run starts the app; external: every container but the app, which something "
                                "outside the stack starts (the updater, sdv/ota); needs --feed vcan")
            s.add_argument("--run-type", choices=RUN_TYPE_CHOICES, default=None,
                           help="the ros feed's run type: planning-sim, the one it takes (--feed ros only)")
            s.add_argument("--bridge", choices=REPLAY_BRIDGE_MODES, default=None,
                           help="--feed ros only: broker runs the claim bridge (SDV_BRIDGE_IMAGE) on profile 4 and a vss monitor")
            s.add_argument("--monitor", choices=MONITOR_MODES, default=None,
                           help="--feed ros --bridge broker only: native (default), the native vss monitor; guest, a monitor the "
                                "stack does not start, at --guest-host (step3.py's guest options)")
            s.add_argument("--guest-host", default=None, help="guest mode: the monitor's IPv4 address (never loopback)")
            s.add_argument("--guest-console", default=None, help="guest mode: its console file (read, never written)")
            s.add_argument("--guest-image", default=None, help="guest mode: its image file (its name and sha256 recorded)")
        if cmd in ("prepare", "replay"):
            s.add_argument("--bridge", choices=REPLAY_BRIDGE_MODES, default="none",
                           help="broker: the claim bridge (SDV_BRIDGE_IMAGE) and the native vss monitor run too; needs --feed vcan")
        if cmd == "exit-test":
            s.add_argument("--feeds", nargs="+", choices=FEEDS + (ROS_FEED,), default=list(FEEDS))
            s.add_argument("--replays", type=int, default=3)
    sub.add_parser("down")
    lv = sub.add_parser("live", help="the stack up on the vcan feed with the bridge while sdv/feeder/live.py drives CARLA (module "
                                     "docstring, LIVE)")
    lv.add_argument("--name", default="live")
    lv.add_argument("--bridge", choices=LIVE_BRIDGE_MODES, required=True)
    lv.add_argument("--feeder-out", required=True, help="the take's directory the feeder will write (it must not exist yet)")
    lv.add_argument("--native", action="store_true", help="the native vss monitor `7160 svc 500`: the one monitor a live run has")
    a = ap.parse_args(argv)
    if a.cmd == "down":
        ros_runs = ros_runs_left()          # read before the sweep: the ros runs whose host check down reads after it
        stop_bridge_and_witness(ros_runs)   # SIGTERM before the sweep's kill: the bridge's summary.json, then the witness's stop record
        remove_stack()
        down_ros(ros_runs)
        return 0
    if a.cmd == "live":
        return live_main(a)
    ros_cli_refusals(a)
    if a.cmd == "up" and a.feed == ROS_FEED:
        return ros_main(a)
    refuse_pc_only(a.cmd)
    bridge = getattr(a, "bridge", None) or "none"
    refuse_bridge_in_twin_control(bridge)          # TWIN CONTROL: before anything is pulled, written or started
    if bridge != "none" and getattr(a, "feed", "vcan") != "vcan":
        raise StackError(BROKER_NEEDS_VCAN)
    connector = bool(getattr(a, "connector", False))
    if connector and a.feed != "vcan":
        raise StackError(CONNECTOR_NEEDS_VCAN)
    app = getattr(a, "app", None) or "stack"
    if app == "external" and a.feed != "vcan":
        raise StackError(APP_EXTERNAL_NEEDS_VCAN)
    kw: Dict[str, Any] = {}
    if connector:
        kw["connector"] = True
    if app != "stack":
        kw["app"] = app
    run_dir = new_run_dir(a.name)
    ctx = Context(run_dir, a.seed, bridge, **kw)
    ctx.prepare(images=a.images)
    print("prepared %s" % run_dir, flush=True)
    if a.cmd == "prepare":
        return 0
    if a.cmd == "up":
        info = up(ctx, a.feed, run_dir / "up", "%s/up" % run_dir.name)
        if app == "external":          # every container but the app: the CAN provider too, once up() has returned
            up_can_provider(ctx, a.feed, run_dir / "up", "%s/up" % run_dir.name, info)
        print(json.dumps(info["listeners"], indent=1))
        print("stack running; stop it with: stack.py down")
        return 0
    if a.cmd == "loadcheck":
        print(json.dumps(loadcheck(ctx, run_dir / "loadcheck"), indent=1)[:4000])
        return 0
    if a.cmd == "ageprobe":
        res = age_probe(ctx, run_dir / "ageprobe")
        print(json.dumps({"server": res["server"], "verdict": res["verdict"]}, indent=1))
        return 0
    if a.cmd == "wheelbaseprobe":
        res = wheelbase_probe(ctx, run_dir / "wheelbaseprobe")
        print(json.dumps({"agrees": res["agrees"], "catalogues": [{k: c.get(k) for k in ("name", "loads", "predicted", "served", "agrees")}
                                                                   for c in res["catalogues"]]}, indent=1))
        return 0 if res["agrees"] else 1
    if a.cmd == "replay":
        r = replay_once(ctx, a.feed, "%s-1" % a.feed)
        print(json.dumps({k: r[k] for k in ("decisions", "lights")}, indent=1))
        print("values ok: recorder %s, witness %s, app %s" % (r["values"]["ok"], r["witness_values"]["ok"], r["app_values"]["ok"]))
        print("C12b: %s" % (r["c12b"],))
        if "bridge" in r:
            print("bridge: %s" % json.dumps({k: r["bridge"].get(k) for k in ("ok", "counters", "identity_holds", "replies", "monitor", "wheelbase")},
                                            indent=1))
        if "connector" in r:
            print("connector: %s" % json.dumps({k: r["connector"].get(k) for k in ("ok", "exit", "exit_means", "events", "counters")},
                                               sort_keys=True))
        gates = replay_gates(r)
        print("gates: %s" % json.dumps(gates, sort_keys=True))
        return 0 if all(gates.values()) else 1
    results = []
    for feed in a.feeds:
        for i in range(1, a.replays + 1):
            r = replay_once(ctx, feed, "%s-%d" % (feed, i))
            results.append(r)
            print("%s-%d: decisions %s lights %s values: recorder %s witness %s app %s" % (
                feed, i, r["decisions"]["ok"], r["lights"]["mock_log"]["ok"], r["values"]["ok"], r["witness_values"]["ok"],
                r["app_values"]["ok"]), flush=True)
    summary: Dict[str, Any] = {
        "run": run_dir.name, "utc_end": utc_now(), "verdicts": [verdict(ctx, results, f, a.replays) for f in a.feeds],
        "same_behaviour_across_feeds": len({json.dumps(r["behaviour_key"], sort_keys=True) for r in results}) == 1,
        "replays": [dict({k: r[k] for k in ("replay", "feed", "feed_wall_s", "decisions", "lights",
                                            "app_decisions_reproduced_offline", "app_inputs_received", "containers")},
                         values_ok={"recorder": r["values"]["ok"], "recorder_exact": r["values"]["exact"],
                                    "witness_exact": r["witness_values"]["ok"], "app_inputs": r["app_values"]["ok"]})
                    for r in results]}
    summary["loadcheck"] = loadcheck(ctx, run_dir / "loadcheck")
    write_json(run_dir / "exit-test.json", summary)
    print(json.dumps(summary["verdicts"], indent=1))
    return 0 if all(v["ok"] for v in summary["verdicts"]) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StackError as exc:
        print("stack.py: %s" % exc, file=sys.stderr)
        sys.exit(1)
