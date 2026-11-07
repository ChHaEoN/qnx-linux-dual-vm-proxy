# sdv/rosvss: the ROS->VSS feeder

Phase 8 WP3a. The feeder copies what Autoware reports about the vehicle, and what
the kind 2 claim node publishes about its claims, into the databroker's local branches, under the attribution writer
name `ros-vss-feeder`. It is never in the claim path: the kind 2 claim goes from the claim node straight to the QNX
guest's monitor (plan 3.2), and the feeder only reads the claim node's `/qnx_monitor/verdict` messages after the
fact.

| file | what it is |
|---|---|
| `update.py` | The update, one plain record per received message (`topic`, `recv_ns`, `stamp_ns`, `fields`; spec 2.8), built from a message's attributes and checked; the verdict message's JSON object (spec 2.6) parsed and checked. A refusal carries a code and is counted, never written. Standard library only. |
| `mapping.py` | The two run types' write sets and the mapping from an update to VSS paths and values, pure functions: units converted to the catalogue's (Vehicle.Speed the magnitude in km/h, the yaw rate in deg/s, the steering angle in degrees), the gear's name to `CurrentGear`, the verdict's fields to the `ControlCommand` and `Monitor.CtlClaim` leaves. `WRITER = "ros-vss-feeder"`. |
| `vsswriter.py` | The writer path: the bounded queue between the callbacks and the databroker (newest kept, drops counted), the writer that writes inside the run type's write set only, the start check of the databroker's datatypes, and the counts log (JSON lines with no value of any signal). |
| `feeder_node.py` | The process: its command line (`--run-type`, `--databroker`, loopback only), the subscriptions and their QoS, the callbacks that build an update and queue it. rclpy, the message packages and `kuksa_out` are imported inside `main` only. |
| `kuksa_out.py` | The only KUKSA calls (kuksa-client 0.6.0, imported inside its methods): the datatypes at start and the writes, `set(try_v2=True)`, on the claim bridge's write-back pattern. |

## One process

Phase 8 runs Autoware 1.9.0 on Jazzy (D1 under D17). Jazzy's Python is 3.12, and kuksa-client 0.6.0 needs 3.11 or
later, so rclpy and the databroker's client share one Python process in a Jazzy container (D4's Jazzy branch). That
process is never the claim node's: the claim node imports no KUKSA client. WP3d builds the container's image (the
Autoware Jazzy image by its recorded digest, kuksa-client from a hash-pinned lock: "The image", below); nothing here
starts a container.

A slow or failing databroker never blocks a ROS callback: a callback only builds the update and puts it on a bounded
queue that never blocks, and one writer thread makes every databroker call. No update stops that thread (an update
the feeder cannot take is counted); should it end anyway, as when its log's stream fails, the process shuts rclpy
down and exits 1 instead of spinning on with nothing written.

## The write sets

| run type | subscribes to | writes |
|---|---|---|
| `planning-sim` | `/vehicle/status/velocity_status`, `/vehicle/status/steering_status`, `/vehicle/status/gear_status`, `/localization/acceleration` (KEEP_LAST 1), `/qnx_monitor/verdict` (RELIABLE, KEEP_LAST 10) | the five kind 4 slots and `Vehicle.Speed`; every `ControlCommand` leaf and every `Monitor.CtlClaim` leaf |
| `carla-autoware` | `/qnx_monitor/verdict` | the same overlay leaves and no standard signal: the CAN path writes those in that run type |

No run type writes `Vehicle.Body.Lights.Hazard.IsSignaling`, `Vehicle.DualVm.AppState.*`,
`Vehicle.DualVm.Monitor.VssClaim.*` or `Vehicle.Chassis.Wheelbase`. The feeder never subscribes to
`/control/command/control_cmd`: the claim node is its only subscriber, and the verdict message carries the command
values. A value outside the run type's write set is counted and logged once by its path, never written. The
`planning-sim` run type and its ownership rows in `sdv/stack/attribution.py` are WP3b's, as is the
`ControlCommand` layer's place in the generated catalogue (WP1b): until the databroker serves every path of a write
set with its datatype, the feeder refuses to start.

## The image (SDV Phase 8 WP3d)

| file | what it is |
|---|---|
| `Dockerfile` | The feeder's image, `ros-vss-feeder`: `FROM` Autoware's Jazzy 1.9.0 image by its amd64 manifest digest (`sdv/stack/images.json`'s `autoware.amd64.manifest_digest`, never a tag); `sdv/aw/aw-entrypoint.sh` copied in as its `ENTRYPOINT`; a venv made with `--system-site-packages`; the lock installed into it; the five modules under `/app/sdv/rosvss/`; `USER aw`; the command `feeder_node.py` under the venv's Python. |
| `requirements.lock` | kuksa-client 0.6.0 and its resolution: exactly the app lock's 17 pins (`sdv/apps/hard-brake-hazard/requirements.lock`), the slice's for CPython 3.12 on Linux x86_64, every one hashed. |
| `build_image.py` | Builds the image on the bridge's pattern and prints its record and its `images.json` pin. |

    python3 sdv/rosvss/build_image.py [--smoke]          # in WSL, from the repo root

- **The base and amd64 only.** Autoware's image holds ROS 2 Jazzy, Autoware's message packages and Python 3.12.3. No
  planned run puts the feeder on an arm64 host (the edge runs the claim node and the guest; the feeder sits on the PC),
  so no arm64 image is built until a run needs one.
- **The entrypoint.** The base's own `/docker-entrypoint.sh` sets the host's loopback multicast flag and three kernel
  network settings whenever a container may (the Phase 8 specification's 2.12). The image's `ENTRYPOINT` is
  `sdv/aw/aw-entrypoint.sh` instead, which sources ROS 2's and Autoware's setup files and execs its command, so the
  base's never runs. The image runs as `aw` (uid 1000), and the entrypoint refuses root.
- **The venv.** The base's Python is externally managed and has no pip. A venv made with `--system-site-packages` has
  pip (from `ensurepip`), sees the ROS packages through the `PYTHONPATH` the setup files set, and keeps the system's
  Python packages they import. `requirements.lock` goes into it with `pip install --require-hashes --no-deps
  --only-binary=:all:`, so pip installs those wheels and nothing else.
- **The build.** `build_image.py` stages a context outside the repo (`~/sdv-cache/rosvss-build/`, removed after) with
  the Dockerfile, the lock, the entrypoint and the five modules. It refuses a Dockerfile whose one `FROM` is not the
  pinned digest before docker runs, reading the keyword as docker does (any case, after leading whitespace), so a second
  stage is never missed. It reads the host check (`sdv/aw/hostcheck.sh`) before the build and after it, and fails on any
  difference with the setting named; a build that fails reads it after all the same and adds what it says to the
  failure. It builds with `docker build -q --provenance=false --sbom=false` (no attestation, no `--privileged` builder,
  no buildx) and labels the image with three build arguments: the base digest, the lock's sha256, and
  `sdv.rosvss.sources_sha256` (the sha256 of `sha256sum`'s lines for the five modules and the entrypoint). It reads the
  config digest from a `docker save` stream of the image's ID, the manifest and the config each checked against its
  digest and the config's platform linux/amd64, and refuses a config whose entrypoint is not `/sdv-aw/aw-entrypoint.sh`
  or whose user is not `aw` before anything is smoked or pinned. The record's `pin` is the `rosvss` entry of
  `images.json`, entered by hand. `--smoke` runs the image once, under 2.12 (`--network none`, `--user aw`, every
  capability dropped, `no-new-privileges`, removed after), importing rclpy, the message packages, kuksa-client and the
  modules through the image's own entrypoint.
- **Pinned.** `images.json`'s `rosvss` entry holds the image's ID, config digest, tag (`sdv-rosvss:local`) and lock, and
  the three labels. `tests/test_sdv_rosvss_image.py` holds the labels to this tree, so a changed module, entrypoint or
  lock without a rebuild and a new pin fails there. `stack.py up --feed ros` runs the image by that ID only after
  checking its ID, labels, entrypoint, user, architecture and tag (`sdv/stack/README.md`, "The ros feed").
- **Does not demonstrate** that the feeder runs right in the image with Autoware's publishers and a databroker (WP4b's
  runs), anything on an arm64 host, or any timing. The smoke shows only that the imports resolve.

## Tests

`tests/test_sdv_rosvss.py`, with stand-ins for rclpy, the message packages, kuksa-client and the databroker; nothing
needs ROS installed. `tests/test_sdv_rosvss_image.py` reads the Dockerfile and the lock as text and runs
`build_image.py` on stand-ins for docker and the host check; it builds nothing and starts no container. The standard
paths' datatypes and units are compared with the generated catalogue in `sdv-out/gen`, which `sdv/vss/generate.py`
writes.

## What this does not demonstrate

- That VSS makes the monitor more independent: the feeder, the databroker and every reader of these branches sit on
  the untrusted Linux side, and the monitor's verdicts reach the databroker only as the claim node reported them.
- Any timing: the queue's bound is a design value, not a measured rate.
- That the feeder runs with the real rclpy, message packages and kuksa-client 0.6.0, or what Autoware's publishers'
  QoS, rates and `GearReport` constants are at 1.9.0 (WP4a reads them; WP4b runs the feeder).
- That Autoware's heading rate is positive to the left: the mapping takes it so, as the overlay does (INFERRED).
