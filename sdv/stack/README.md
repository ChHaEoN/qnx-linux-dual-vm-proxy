# sdv/stack: the slice's local stack

The PC side of the slice, run from one script in WSL Ubuntu-24.04's Docker Engine: a KUKSA databroker
loaded with the generated VSS catalogue, the CAN provider feeding it from `slice.dbc` and a sigsim
recording, a mock provider serving the hazard-light actuator, a VSS-layer recorder, and the first app
(`sdv/apps/hard-brake-hazard`). No QNX, no board, no cloud.

## What is here

| file | what it is |
|---|---|
| `stack.py` | Prepares a run (reads a sigsim or a CARLA recording by the log its manifest line names, checks the recording against its manifest line and summary, pulls the upstream images by digest and checks their revision labels, builds the local images, or with `--images loaded` only inspects the images an aarch64 host pulled and loaded before the run, stages the exact inputs and the run type's catalogue and vehicle layer (the section "A CARLA recording", below), derives the expected windows, writes and checks the scenario table), starts and stops the stack, replays the recording, checks what happened, and runs the exit test and the catalogue load check. |
| `dbc-sources.json` | For each DBC a recording names by sha256, the commit, path and git blob id it was committed with: what a missing cached DBC is exported from. |
| `images.json` | Every image the stack uses: the upstream images as repo and index digest with their per-arch manifests and revisions, the Python base by digest with its amd64 and arm64 manifests, the pinned source of the recorder, the two local builds, and the arm64 pins (SDV Phase 3 WP0: each local image's `arm64` entry and the top-level `bridge` entry, written by `sdv/arm64/arm64.py build --write-pins`). Its top-level `test_only` entry (SDV Phase 4 WP0) is not the stack's: it pins the local MQTT broker that only the twin connector's opt-in tests run (`sdv/connector/README.md`), and nothing here pulls, starts, loads, bundles or scans it. Its top-level `connector` entry (SDV Phase 4 WP3) pins the twin connector's amd64 and arm64 images in the `bridge` entry's shape, with the labels they were built with (`sdv/connector/build_image.py build --arch all --write-pins`); the stack starts the amd64 one, by the ID `SDV_CONNECTOR_IMAGE` names, only when a run asks for a connector, and no bundle or deploy set holds either. Its top-level `autoware` and `rosvss` entries (SDV Phase 8 WP3d) pin Autoware's image and the ROS->VSS feeder's (the section "The ros feed", below). |
| `attribution.py` | The signal attribution table (writers by name, then by image ID, under a run header) generated from the components' own configurations, and the design's checks on it; and the planning-sim table of a ros run (below). |
| `replaycheck.py` | What a replay is checked against: the windows from the recording's own trip summary, the app's decision function applied to the decoded recording, the recorder's CSV against the decoded recording, the witness's log compared exactly, the app's log mapped onto recording time, the mock provider's writes as the light's gate, the behaviour key (lossless sources only) and the recorder's hazard rows as a reported view. |
| `witness.py` | The value witness: a kuksa.val.v2 subscription with the databroker's largest buffer on the six paths the CAN provider writes, logging every value it receives. Runs in the recorder image. |
| `catalogue_probe.py` | Asks a throwaway databroker what it serves (metadata and values of named paths; optional writes to test a range the catalogue file states). `loadcheck` and `wheelbaseprobe` run it. |
| `ageclock_probe.py` | Asks a throwaway databroker who stamps a datapoint and on which clock (kuksa.val.v1 Set and v2 PublishValue, each with and without an explicit timestamp, read back), and whether a value written again unchanged refreshes the stamp and reaches a v2 subscriber (the kind 4 wire specification 17.1 items 1-2; `stack.py ageprobe`). Runs in the recorder image. |
| `mock/mock.py` | The mock provider's behaviour: the hazard-light actuator only, its current value following its target. Mounted over the image's sample file, which also animates a speed signal the CAN provider owns. |
| `recorder/Dockerfile`, `recorder/requirements.lock`, `recorder/requirements.aarch64.lock` | The recorder image: the csv-provider release's `recorder.py` at the pinned commit, unmodified, fetched and checked at build time into a context outside the repo, on the pinned Python base with kuksa-client from the lock (the same pinned versions and hashes as the app's lock; `tests/test_sdv_stack.py` holds the pins equal). The aarch64 lock is its arm64 twin, staged by `build_local_arm64` (SDV Phase 3 WP0). |
| `wsl-pytest.args` | The `--deselect` list that lets the whole test suite run in WSL without running git on this checkout (below). |
| `step3.py` | Phase 2 step 3 (WP10): the claim bridge in each of its modes (`broker`, `can`, `replay`) against the native vss monitor, or with `--monitor guest` the QNX guest's (SDV Phase 3 WP2), the injected recording of either kind (sigsim or CARLA), its stop realised per mode at its events file's offset, every run ticking through its `run_through_ns`, the scripted injections and pauses, each run judged from its own files, and the comparison across the modes (below). |
| `step3-runs.json` | The step-3 run specs: the recording kind and run, the bridge script's steps and their windows, and the pause sequence expected. Design values only. |
| `bundle.py` | The upload bundle for an aarch64 instance (SDV Phase 3 WP1; below): `build` on the PC, `verify [--loaded]` and `verify-upstream` on the instance, on Python 3.10, before any venv exists. It carries the four recordings of every plan (`PLAN_RECORDINGS`). It also holds the image rules `--images loaded` applies. |

## How

In WSL Ubuntu-24.04, with the sim venv (`sdv/sim/README.md`), the generated contract
(`sdv/vss/README.md`) and a recording (a sigsim one, or a CARLA one: below), from the repo root:

    ~/sdv-sim-venv/bin/python sdv/stack/stack.py prepare
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py replay --feed dumpfile     # or --feed vcan
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py exit-test
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py loadcheck
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py up --feed dumpfile        # leave it running
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py down
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py ageprobe                  # who stamps a datapoint, on which clock
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py wheelbaseprobe            # Wheelbase served with and without a default
    SDV_BRIDGE_IMAGE=<image ID> ~/sdv-sim-venv/bin/python sdv/stack/stack.py replay --feed vcan --bridge broker

Every command except `down` starts a new run directory under `~/sdv-runs/<date>-<name>/`
(`SDV_RUNS` moves the root; it is never inside the repo). `SDV_GEN`, `SDV_RECORDING`, `SDV_CACHE`
and `SDV_SIM_VENV` move the other inputs. No `--seed` is needed: the seed is the recording's, and a
`--seed` that disagrees with it is refused. `SDV_HOST_ROLE` names the host in the run manifest, the run header and
its `run_id`: `pc` (the default), `a1-metal`, `c7g-metal` (AWS c7g.metal, held to what `a1-metal` is held to) or `orin`,
a role and never a hostname; any other value is refused before anything is written.

## Placement on the Orin (SDV Phase 5 WP1)

Two variables place the stack's containers beside the QNX guest (plan 3.7). Both are read by `stack.py` and by
`step3.py`, which builds on it, and each refusal comes before anything is written.

- **`SDV_CONTAINER_CPUSET`**: a CPU list `N[,N...]` of distinct decimal integers. When it is set, every container the
  stack starts gets `--cpuset-cpus <list>` right after the common flags: the databroker, the providers, the recorder,
  the witness, the app, the bridge and the connector, and the throwaway containers of `loadcheck`, `ageprobe` and
  `wheelbaseprobe`. When it is unset, no argument vector changes. It is **required on `orin`** and allowed on any role
  (the PC rehearsal sets it). A list that is empty or malformed, names a CPU twice, or holds core 0, 1, 2 or 4 is
  refused on every role: on the board cores 0-2 are QEMU's and core 4 is the probe's.
- **`SDV_AFTER_START`**: a command line, split with shlex and never given to a shell. It runs after each container the
  run's start path starts (never after the probes' throwaway ones), with the container's name appended as its last
  argument, under a timeout of `AFTER_START_TIMEOUT_S`. Each run's `result.json` (a replay's, and a step-3 run's) keeps
  one record per container under `after_start`, in start order: the container, the exit status, and the last lines of
  its stdout and stderr. A non-zero exit, a timeout or a command that cannot be started stops the run as a failed start
  does, and the refusal names the container. It is **required on `orin` beside either monitor** (`step3.py --monitor
  guest`, and the native one that `stack.py`'s own commands run): the stack knows the board only by its role, and a
  guest may run beside a native-monitor run. It is allowed elsewhere. On the board it is the re-pin of QEMU's threads
  to cores 0-2, which reads them first, so a record says whether a container's start moved them; it exits non-zero when
  no QEMU runs, so there a native-monitor run stops at its first container unless a guest runs. A value that shlex
  cannot split, or that is empty, is refused.
- **The record.** The run manifest's `placement` holds the cpuset and the hook's argv as given, or says that neither
  was set.
- **The PC's probes.** `loadcheck`, `ageprobe` and `wheelbaseprobe` start containers outside the run's start path, and
  `exit-test` ends with `loadcheck`. On `orin` all four are refused before anything is written.
- **Does not demonstrate** that docker kept a container on those CPUs, or that QEMU's pin held: the hook's output is
  the hook's own report.

## The upload bundle and `--images loaded` (SDV Phase 3 WP1)

`bundle.py build` writes what an aarch64 instance needs beyond the repo into one directory outside the repo, each file
under a name the upload accepts (`[A-Za-z0-9._-]`), and `bundle.json` last (the format, the source commit, and per
member its name, role, bytes and sha256):

| member | what it holds |
|---|---|
| `sdv-arm64-images.tar` | `docker save` of the three arm64 images by their pinned IDs (`images.json` `local.*.arm64`, `bridge.arm64`). Its OCI layout is checked against the pins: each ID's manifest blob hashes to it, its config digest is the pinned one, every layer blob hashes to its digest. The tar must be exactly what that save writes: each name once, no link, the legacy `manifest.json` naming the pins' configs and layers and no tag, and no blob that no pinned manifest references. |
| `sdv-gen.tar` | `sdv-out/gen` under `gen/`, refused unless its contract's sha256, its slice.dbc and its catalog digest are the bridge pin's three labels, that slice.dbc is every recording's and the repo's, and its `manifest.json` is the one the bridge image bakes in (`app/sdv-out/gen/manifest.json`): the labels bind three outputs, the baked manifest every one. |
| `rec-<name>.tar` | The four recordings of every plan the suite runs (read, never written): the sigsim pair `20260930-sigsim-1b` and `20261002-sigsim-1b-inj4`, and the CARLA pair `20261019-carla-1` and `20261019-carla-1-inj` (below). Each is checked by the log its manifest line names. |
| `<sha256>.dbc` | The DBC, from `~/sdv-cache/dbc/`. |
| `cpython-3.12-aarch64-install_only.tar.gz` | The host Python pinned in `sdv/sim/python-aarch64.json`, under this name because the asset's own name carries a `+`. |

In WSL, with the commit read in Git Bash (git never runs in WSL on this checkout):

    python3 sdv/stack/bundle.py build --out ~/sdv-bundle/<name> --commit <source commit>
    python3 sdv/stack/bundle.py verify --in ~/sdv-bundle/<name>                       # every member, then each against the pins
    python3 sdv/stack/bundle.py verify --in <dir> --loaded --docker 'sudo -n docker'  # after docker load
    python3 sdv/stack/bundle.py verify-upstream --docker 'sudo -n docker'             # after the four pulls; never pulls

`verify` also names a bundle built from other pin files than the repo's (`bundle.json`'s `pins`: the sha256 of
`images.json` and `python-aarch64.json` at build). It opens each member once and reads its content through the handle
it hashed, so the bytes checked are the bytes `bundle.json` names; a member whose path names another file by the end is
refused.

`stack.py --images loaded` (every command but `down`) and `step3.py run --images loaded` are the instance's path. The
upstream images pulled before the run and the local arm64 images loaded from the bundle are only inspected, by the same
rules: an upstream image's ID is its index digest, its revision label the pinned commit, repo@index-digest is among its
RepoDigests, and it is linux/arm64; each local image is present by its arm64 pin's ID as linux/arm64; the bridge is its
arm64 pin. A missing image is refused, never pulled or built. `--images build`, the default, is the PC's path and is
unchanged. `tests/test_sdv_bundle.py` runs on Python 3.10 as well as CI's Python. Its opt-in part (`SDV_BUNDLE=1`,
`SDV_BUNDLE_COMMIT`) carries the three images through save, remove, load and `verify --loaded` on this PC's own store.
It does not show the carry to the instance's Docker.

## The bridge mode (Phase 2 WP8)

`replay --bridge broker` (and `prepare --bridge broker`) adds the kind 4 claim bridge and the monitor it talks
to. A functional mode, not Phase 2's step-3 runs (those are `step3.py`'s, below): no timing, and the monitor is
the native build of the guest's `monitor.c`, not the guest. Here the bridge is stopped as soon as the player
ends; a step-3 run keeps it ticking.

- **The monitor**: `build-monitor-native.sh` with `MONITOR_EXT_KINDS=0x10`, built at prepare into
  `<run>/bin/monitor-vss` (never the script's default `OUT`), run as `monitor-vss 7160 svc 500` on the host.
  Its stdout is the run's console capture, `monitor.log`.
- **The bridge**: the `vss-claim-bridge` image by the ID `SDV_BRIDGE_IMAGE` names (`sdv/bridge/build_image.py`
  prints it). Prepare refuses an image whose labels (catalogue digest, contract and `slice.dbc` sha256) are not
  this generation's. It runs as `sdv/bridge/Dockerfile` says: the run's `scenario.lock` bind-mounted at the
  designated path, the host user, a read-only root, `--out` on the replay's `bridge/` directory, and the run
  header (`bridge-header.json`) as its configuration. It starts after the app and before the feed, and it is
  stopped as soon as the player ends, so its last frames are still the recording's.
- **Only over vcan.** The dumpfile feed runs the databroker with `--network none` and every container in its
  namespace, where a bridge could reach the databroker but never the monitor on the host's `:7160`. The vcan
  feed puts every container in the host's namespace.
- **The run header** carries the bridge items: `bridge_mode broker`, the scenario entry's `profile_id`
  (`profile_source scenario`), the generated AGE_MAX, no demo-ODD window, and `time_sync.age_clock`. The
  age clock is broker mode's: the databroker stamps every datapoint on receipt on CLOCK_REALTIME (`ageprobe`).
  C3 (every slot has a writer) and C12a are checked at start. At record close, C12b reads its two operands:
  the monitor's `monitor: vss rules:` line and the bridge's connect records. Each must carry the header's
  digest, AGE_MAX and profile. The header's `header_check` then says `ok` or `failed C12b: <items>`.
- **The table**: the bridge writes the eleven `Monitor.VssClaim` leaves (its write-back, labelled as its own
  view), so those rows name it and C8 binds its image ID. Without a bridge the app's two display leaves
  stay unowned.
- **Listeners**: the monitor binds `INADDR_ANY`, as the guest's does, and its bind is never changed. The
  listener check allows that one listener by the PID the stack started and its port only. The same port
  under any other PID, or a run with no listener owners known, is refused.
- **The vehicle layer** (spec 5.6). The bridge reads `Vehicle.Chassis.Wheelbase` from the databroker at start,
  which serves the catalogue's `default` (`sdv/vss/generate.py`'s `vehicle-sigsim.vspec` sets it to the
  profile's L). Prepare predicts what the bridge will read from the catalogue it stages, before anything
  starts:
  - a value other than the profile's L (VSS 6.0's 0 without the layer, or another vehicle's layer): the bridge
    would refuse to start, so prepare refuses it;
  - no value (a catalogue whose node has no `default`): the bridge starts and logs its note, `wheelbase: not
    served by the databroker, checked against the declared source vehicle only`. Prepare starts too and
    records that note in the run manifest's `bridge.wheelbase`; L is then checked only against the declared
    source vehicle (C12a).

  Each replay compares the bridge's own wheelbase record with the prediction (`result.json`'s
  `bridge.wheelbase`; a disagreement fails the replay). `wheelbaseprobe` loads the staged catalogue and a copy
  without Wheelbase's default into databroker 0.7.1 and checks that it serves the default, and nothing
  without one.
- **The exit status**: `replay` exits 0 only when every gate of `replay_gates()` holds: the values, decisions
  and lights, all three listener snapshots, the bus frames for vcan, C12b, and the bridge's own result.
- **Without a bridge** `time_sync.age_clock` is null, as `profile_id`, `profile_source` and `age_max_ms` are:
  nothing reads an age. That is this stack's reading; attribution-table 3.1 defines `age_clock` only as the
  clock the bridge reads on.

## Phase 2 step 3 (WP10): `step3.py`

    SDV_BRIDGE_IMAGE=<image ID> SDV_RECORDING=<recording> ~/sdv-sim-venv/bin/python sdv/stack/step3.py run --mode MODE --spec SPEC [SPEC ...] [--repeat N] [--name NAME]
    ~/sdv-sim-venv/bin/python sdv/stack/step3.py plan --mode MODE --spec SPEC      # the plan only
    ~/sdv-sim-venv/bin/python sdv/stack/step3.py compare --name NAME DIR [DIR ...] [--modes MODE ...]

One invocation is one bridge mode and a run directory; each spec (and each `--repeat`) is one run in it.
`--monitor guest` (below) takes one spec, run once.

- **The modes.** `broker`: the whole stack over the vcan feed, as WP8, with the bridge's write-back; `can`: vcan0,
  the bridge's SocketCAN adapter and the player, no databroker; `replay`: the bridge reads the staged recording
  itself, no databroker and no bus. Each with the native vss monitor `monitor-vss 7160 svc 500`, and the bridge
  image in the host's namespace with a script of control calls (`sdv/bridge`, SCRIPT) written from the spec and
  the events file.
- **The windows.** An injected recording's `events.json` (sdv/inject, WP9; checked against the recording, its
  manifest line, the contract, the DBC and the bridge's tick) gives the injected events and, per run, its two 22
  windows, `run_through_ns` and the stop's realisation. An honest recording has only its `to_end` run, derived
  with inject.py's own functions. A spec adds its scripted events' windows. Each window is moved onto the run's
  clock by its origin: the recording's (replay: the run's grid anchor; can and broker: the vcan capture's receive
  time of the recording's first frame) or the script's (the bridge's logged script origin).
- **The stop** (the `stop` run): at the events file's offset S, never a literal here, by the mode's one
  realisation, never undone: replay, a `pause_intake` script step half a tick before S (between the grid's two
  deliveries the events file names); can, the player stopped at the same instant; broker, the can-provider's
  process killed then (by its PID, not through the docker daemon), the player playing on.
- **Run-through.** The script's last step ends the run one tick past the first instant of the tick grid at or past
  the run's `run_through_ns`, one tick after it when it lies on the grid: replay reads a grid instant about half a
  tick after it, so for a `run_through_ns` off the grid (between two grid instants) an end
  one tick after it can come before the next grid instant is read. The harness
  never stops the bridge at the player's end; it waits for it to end itself, and stops it (a failed gate) only
  `END_SLACK_S` past the script's end step.
- **Per run**: `plan.json`, `bridge-script.json`, `bridge-header.json`, the bridge's directory (`replies.jsonl`,
  each reply with the frame sent; `bridge.jsonl`; `summary.json`; `source.json`), `monitor.log`, `listeners.json`,
  `attribution.json` (C10, C12a, C8 for broker, C12b), `player.log` for the live modes, the containers' logs and
  `result.json`, whose `gates` are the run's verdict: the event-to-reason set equal to the plan's
  (`reasonsets.reason_set` on the moved windows), ticked through, the stop made as planned (or none; the
  realisation the stack's call names, at its instant), the script done and the bridge ending itself with exit 0,
  the accounting identity, drop = 0 and lost = 0 in every run, the pause runs included (the plan's exit asks it
  of every actual run; the paths with a drop or a loss are pytest's; the bridge's drops are reported by their
  why, and a `paused` one is a finding like any other), no fatal, no uninjected 21, the console (no MISS,
  RESTORED or `client closed:` before the bridge's last session ends; a pause run's spec 14.4 sequence instead),
  the start checks, all three listener snapshots, C12b, and for live runs the bus (the log's frames in order,
  whole or, for a stopped player, a prefix ending inside the tick before S).
- **Compare**: every `result.json` under the given directories, grouped by recording and spec; every run in a
  group was judged and passed its own gates (a `result.json` an aborted run left, with no reason set, fails its
  group by name), every mode of `--modes` (default all three) has a run and every set equals every other
  (`reasonsets.compare_modes`), and two replay runs of a group are compared frame by frame apart from the tstamp;
  never across modes. A run of a mode `--modes` does not list is left out and named (`left_out`). `compare.json`
  in a run directory of its own. The directories go before `--modes`, or after `--`.
- **Does not demonstrate** any timing (the windows carry the specification's allowance A), bus timing, or anything
  about the guest in native mode; `can` and `replay` bypass the VSS API.

### Guest mode (SDV Phase 3 WP2): `--monitor guest`

    step3.py run --mode MODE --spec SPEC --monitor guest --guest-console FILE --guest-image FILE [--guest-host ADDR] [--images loaded]

The run is judged by the QNX guest's vss monitor, which `ifs-vss.build` starts as `qnx-safety-monitor 7160 svc 500`.
A functional mode: judged by the guest over br0, no timing.

- **The monitor.** Nothing is built or started for it. The bridge's `--host` is `--guest-host` (default
  `192.168.100.10`, the guest's address on br0); an address that is not IPv4, or is loopback, is refused, and so is one
  of this host's own addresses unless `SDV_HOST_ROLE` is `pc` (where the stand-in guest is this host). The run
  manifest's component `vss-monitor-guest` is the image's file name and sha256, the host and `host_local` (whether it is
  this host's own; null when the addresses cannot be read), port 7160 and `7160 svc 500`. The listener check allows
  nothing: the stack starts no listener of its own.
- **One fresh boot per run.** `--repeat` above 1 and more than one spec are refused.
- **The console** is the guest's serial console file (QEMU's log, with NUL bytes and CR in it). It must exist and pass
  the freshness gate when the call starts and again when the run starts: no `LIVENESS` line, no `client closed:`, and
  no `client done:` with seen above 0, anywhere in a line (the five instances share the console, and their lines can
  interleave). The launch probe's and the readiness check's `seen=0` lines pass only when each probe closes within the
  guest's 500 ms deadline: a probe whose socket stays open past it (a descriptor left open, a stalled close) leaves
  `client closed: no complete frame` before its `seen=0`, and the gate refuses the console, saying so. So a readiness
  check opens and closes its connection in one step. The run's judged console begins at the end of the last whole line
  at the run's gate.
- **After the run** step3 waits, bounded (`CONSOLE_END_S`, 5 s), for as many `client done:` lines with seen above 0
  after that offset as the bridge had sessions (its connect records, at least one: a pause run's first session ends
  before its last); the `console_end` gate fails unless exactly that many came, and names a surplus (a client that was
  not the bridge judged claims on :7160). The last one's seen is recorded beside the bridge's reply count, not gated.
  The console is then read once, NUL and CR removed. The whole goes to the run directory as `guest-console.log`, which
  C12b reads (the `vss rules:` lines come at boot; `c12b_lines` counts those that parse, `c12b_expected` is five, and
  `c12b_note` notes another count, which fails nothing unless it is 0: then C12b fails for want of a line, which says
  as much about the console as about the guest). `result.json`'s `console_file` records the raw file's path, bytes and
  sha256. The console gate and the pause sequences judge only what follows the offset: the guest runs on, and the
  probe's `seen=0` line before it would otherwise stand for the bridge's last session end. There the split is the last
  clean `client done:` with seen above 0 (a later `seen=0` line is a probe's, counted as `seen_0`). The gates match
  their markers at line start, so a judged line that holds `LIVENESS`, `client closed:` or `client done:` anywhere but
  as its own start is garbled (another writer's bytes inside it) and fails the console gate, named in
  `console.problems`. A console that cannot be read is a refusal naming it.
- **On the PC** the opt-in test (`SDV_STEP3_GUEST=1`, `SDV_BRIDGE_IMAGE`, `SDV_RECORDING` an honest recording) stands
  the native vss monitor in for the guest: `7160 svc 500` bound to `INADDR_ANY`, its stdout relayed into a console
  file salted with NUL bytes and CRLF, reached at WSL's eth0 IPv4; then `compare --modes replay`. It skips without a
  non-loopback IPv4 on eth0.
- **Does not demonstrate** any timing; that the guest's monitor saw every frame the bridge sent (seen is recorded,
  not compared); the guest's boot, io-sock or the image beyond its sha256. On the PC, nothing about the guest at all:
  the stand-in is the native build, and WSL's eth0 is not br0.

## The twin connector (SDV Phase 4 WP3): `--connector`

    SDV_CONNECTOR_IMAGE=<image ID> SDV_DEVICE_DIR=<directory> ~/sdv-sim-venv/bin/python sdv/stack/stack.py replay --feed vcan --connector

`replay` and `up` take `--connector`: the twin connector's image (`sdv/connector`) runs beside the stack, reads
allowlisted paths from the databroker on 127.0.0.1 and sends them up its uplink. It is the one container of the
stack with a way out of the host. It is a reader, not a writer, so it has no row in the attribution table; it is
a member of `CONTAINERS` and not of the six of Phase 1, so the listener rule covers it.

- **What it needs.** `SDV_CONNECTOR_IMAGE`, the image ID `sdv/connector/build_image.py` prints: its labels must
  name the allowlist version this stack runs on and the sha256 of this generation's `vss-ids.vspec`, and its own
  user must not be root. `SDV_DEVICE_DIR`, an absolute path outside the repo holding the device's key,
  certificate and CA file and `connector.env` (`SDV_TWIN_ENDPOINT`, `SDV_TWIN_THING`, `SDV_TWIN_RULE`, one
  `NAME=value` a line).
- **How it runs.** A read-only root, every capability dropped, the host user (the stack refuses to start it as
  root), restart policy `no`, the host's network namespace, no published port, and three mounts and no other:
  the spool read-write at `/run/sdv-local/spool/v1`, the status (the updater's record) read-only at
  `/run/sdv-local/status/v1`, the device directory read-only at `/run/sdv-local/device`. The spool and the status
  are the replay's own `spool/` and `status/`, or the host's (`SDV_SPOOL_DIR`, `SDV_STATUS_DIR`, below). The
  endpoint and the two names reach it through `--env-file`; none is on the argument vector, and the stack writes
  none of them, nor the device directory's path, into a run directory.
- **When.** Started after the app (and the bridge), before the listener snapshot; it counts as started once its
  log holds its start line. Stopped with SIGTERM after the app and before the databroker, with a grace of 30 s,
  so its last read and its last flush run.
- **What is refused,** before anything is started or written: a feed other than vcan (the dumpfile feed's
  namespace has loopback only); the guest monitor mode (owner decision S11: nothing the QNX monitor produces
  goes to the cloud; Phase 5 lifts this with its own evidence); `--images loaded`; a missing image, device
  directory or `connector.env`; and a start within 120 s of the previous connector start this host's stack
  made. That last rule is the start spacing (`sdv/connector/limits.py`): each start costs shadow publishes
  whatever the run's length, and each run has a limiter of its own. The connector's own stamp lies in its spool
  directory, and each replay has a new one, so the stack keeps the same stamp (`sdv/connector/startstamp.py`) in
  its state directory, `SDV_STATE` (by default `~/.local/state/sdv-local/twin`, never inside the repo).
- **What a replay records of it.** `result.json`'s `connector`: its exit status and what that status means, its
  events by kind, its start line's allowlist version, digest and catalogue, and its own counters; `ok` when it
  exited 0 with a start line first and a stop line last. `replay`'s exit status takes it as one more gate. The
  counters are the connector's own counts of what it tried and what its uplink took. `uplink` is the uplink's
  own: connections opened, lost, given up and found without life (`stale`), and `resumed_by_sdk`, an SDK that
  came back by itself, which it does with nothing to send (`sdv/connector/README.md` says why). Recorded, not gated.
- **Does not demonstrate** anything about the far end: what arrived is the far end's to say. The opt-in tests
  (`tests/test_sdv_connector_broker.py`, `SDV_CONNECTOR_BROKER=1`) run the slice beside a local test broker and
  read it there. Nor that the start spacing holds across hosts, state directories or connectors started by hand.

## SDV Phase 6 (WP2): the app's image ID, `--app external`, the host's spool and status, the marker

    ~/sdv-sim-venv/bin/python sdv/stack/stack.py up --feed vcan --app external [--connector]

- **`APP_IMAGE_ID` is the app's config digest** (the Phase 6 spec's one meaning of "image ID", which the spool,
  AppState and the updater's status record share). The app still runs by its store ID, the ID docker reports
  (under the containerd image store a built or loaded image's manifest digest). `--images build` proves the
  config digest after the build from a `docker save` stream of the store ID, the manifest and the config each
  checked against its digest by `sdv/arm64/a64scan.py`'s reader, and refuses a store ID that names an index;
  `--images loaded` takes the arm64 pin's `config_digest`. The run manifest's app component records
  `config_digest` beside its store `image_id`; a start with no proved config digest is refused before docker is
  asked. This changed the app's argument vector on every role, deliberately; every other container's is as it
  was, and a test writes each one out.
- **`up --app external`** starts every container but the app, the CAN provider included, and waits for no app:
  whatever starts the app (the updater, `sdv/ota`) does so outside the stack, with its own flags. The CAN provider
  comes last, once the rest of the stack serves, started as `live` starts it (the run's `<run>/up` label, its ready
  line waited for), so the vcan0 player of the updater's drill (`drill.py run`) reaches the databroker;
  `up/listeners.json` holds `up`'s listener record, the snapshot taken with it running among them. One that does not
  start or never logs its ready line takes the stack down (`down`'s teardown), and `up` fails with the reason. `up`
  with the stack's own app starts what it started before, and no CAN provider. The vcan feed only (such an app runs
  in the host's network namespace and reaches the databroker on 127.0.0.1, which only the vcan feed puts there); not
  on `replay` or `exit-test`, whose gates read the app. The run manifest's `app` is `external` (else `stack`).
- **`SDV_SPOOL_DIR` and `SDV_STATUS_DIR`**, both or neither: host directories the connector mounts at its two
  paths in place of the replay's `spool/` and `status/` (the drill's `/run/sdv-local/spool/v1` and
  `/run/sdv-local/status/v1`, which the updater's launcher makes). Each must be named by an absolute path, exist,
  be a directory and lie outside the repo; the stack never makes either. Taken only by `up --app external
  --connector`: the host's spool hands the twin's requests to the updater, which starts its own app, so `replay
  --connector` and `up --connector` (the stack's own app) are refused while either is set, before anything is
  written. A run with no connector does not read them, so the drill's shell, which exports both before the
  launcher has made the directories, refuses nothing there (`exit-test`, `step3.py`, a replay or an `up` without
  `--connector`). Refusals name the variable and never its value; `twin.spool_status` in the run manifest says
  which pair a run had and holds no path.
- **The twin-control marker** (`SDV_TWIN_CONTROL_MARKER`, by default `/run/sdv-local/twin-control`; owner decision
  D11). Its existence is the mode: while any entry is at that path (or the path cannot be looked at) no bridge
  starts, so the updater may take scenario requests. `replay --bridge` and `prepare --bridge` are refused before
  anything is written, so is every `step3.py run` (each starts a bridge) and every context with a bridge, and the
  bridge's own start refuses first thing. A run with no bridge does not look.
- **Does not demonstrate** anything about an external app (this run neither starts nor reads it), that no bridge
  starts by another way while the marker exists, or that one started before the marker stops.

## A CARLA recording (SDV Phase 7 WP3b)

The stack, `step3.py`, the bundle and the instance's suite replay a CARLA recording as they replay a sigsim one. A CARLA
recording is a file Phase 7's encoder wrote from a recorded CARLA take (`sdv/carla`); the stack replays the file and
starts nothing of CARLA.

- **The recording kinds.** A recording's run type is its manifest line's `source.generator`. Its log is the basename of
  the line's `recording.path`, and must be the generator's: `sigsim.log` for `sigsim`, `carla.log` for `carla`
  (`sdv/inject/inject.py`'s `LOG_NAMES`; `bundle.py` keeps a copy and `stack.py` reads that one, held equal by a test).
  Any other pair, another name or another generator is refused, and the refusal names both the generator and the log.
  The log must hash to the line's sha256 and to `<log>.sha256`'s, which names no file but the log. The stack,
  `step3.py`, the bundle and setup apply this one rule (`bundle.py`'s `log_name_of`) and none of them reads the form of
  the path: `inject.py` checks a scenario entry path for the recordings it writes, and a sigsim recording that
  `sigsim.py record` wrote under a relative `--out` runs as it did before Phase 7.
- **Staging.** The log is staged in the run's `in/` under its own name. The dumpfile feed, replay mode's `--log`, the
  player, the bus check and every record name it by that name.
- **The run type's generation pair.** A sigsim run uses exactly what it used before: `manifest.json`'s `vehicle_layer`
  and `vss-databroker.json`, whatever else the generation holds. A carla run uses `vehicle_layers.carla` and
  `databroker_catalogues.carla` (`vss-databroker-carla.json`, whose Wheelbase default is profile 3's L), each checked
  against the manifest's outputs. The catalogue is staged as `in/vss-databroker.json`, so the containers' arguments do
  not change. The vehicle layer is the one the scenario table's Wheelbase row and the run manifest's catalogue name. A
  generation without `vehicle_layers`, made before Phase 7's freeze, refuses a CARLA recording before anything is
  written.
- **The run header.** `run_type` is the generator and `feed` is `recording`. The profile is the line's: profile 3,
  `LIVE_DEFAULT_PROFILE["carla"]`, for a CARLA recording. `source_rtf` is the line's `source.rtf` for carla and null
  for sigsim. The scenario entry's `source` is the line's, `rtf` included, so C12a holds; `attribution.py` is unchanged.
- **The records name what the run used.** The CAN provider's rows of the scenario table name the run type's upstream
  (attribution-table section 4): `sigsim seed N` for sigsim, as `attribution.py` writes it, and for a CARLA run the
  feeder, `carla-feeder (<version>, <town>, seed N, <vehicle>)`, from the line; every other column is
  `attribution.py`'s. `loadcheck`, and so the exit test's last step, also loads a CARLA run's staged catalogue, beside
  the generation's sigsim one. In guest mode the run manifest's `vss-monitor-guest` component names the build file of
  the image that ran: `ifs-vss.build` for `ifs-vss.bin`, `ifs-vss-carla.build` for `ifs-vss-carla.bin`, `ifs-ctl.build`
  for `ifs-ctl.bin` (Phase 8 WP5: its :7160 runs the ctl build, which judges kind 4 as the vss build does), and for
  any other image no build file of this tree.
- **Provenance.** For a sigsim recording, whether the current `sdv/sim/sigsim.py` made it. For a CARLA recording,
  whether the current `sdv/carla` modules and `sdv/sim/carla_iso.py` are the ones its trip's `encoder_sha256` names. An
  injected rewrite's trip names none. Both are reported, never required.
- **The oracle.** The trip's one `hard brake` segment and the vehicle moving after it, as before. A CARLA trip's route
  drive and reverse segments meet it unchanged. A trip that does not meet it is refused before anything starts.
- **`step3.py`.** The events file and an honest recording's derived `to_end` run come from the log the line names, and
  an events file must name that log. An honest CARLA recording has only its `to_end` run. `compare` groups by the
  recording's sha256, as before.
- **The plans.** `v1` and `v2` replay the sigsim pair on `ifs-vss.bin`. `carla` gives `v2`'s units and compares over
  the CARLA pair on `ifs-vss-carla.bin`, whose `vss rules:` lines list profile 3. `bundle.py` and
  `orin-native/gpu-concurrency/vss_suite.py` each hold the table, and a test holds the two equal. The bundle carries all
  four recordings, so one bundle serves every plan.
- **The suite and setup.** `run-vss-setup.sh` stages each `rec-*.tar` by the log its manifest line names
  (`vss_setup.py log`), and its rules facts record the profile list the guest's `vss rules:` lines agree on.
  `run-vss-suite.sh` takes `PLAN=carla`. At its preflight it refuses the plan unless each recording's own log is staged
  and setup's recorded profiles list the recording's profile. `v1` and `v2` plan, stage and record as before.
- **Does not demonstrate** anything about CARLA, the drive or vehicle dynamics (a recorded file is replayed), that a
  host replays the CARLA pair (Phase 7's WP5b, WP6 and WP7), the live path (WP3c), or any timing.

## The ros feed (SDV Phase 8 WP3d): `up --feed ros`

    ~/sdv-sim-venv/bin/python sdv/stack/stack.py up --feed ros --run-type planning-sim                  # no kind 4
    SDV_BRIDGE_IMAGE=<image ID> ~/sdv-sim-venv/bin/python sdv/stack/stack.py up --feed ros --run-type planning-sim --bridge broker
    ~/sdv-sim-venv/bin/python sdv/stack/stack.py down

A planning-sim run plays no recording. Autoware's planning simulator, which the stack does not start (WP4b's runbook
starts it, the claim node and the scenario driver), is the source; the ROS->VSS feeder (`sdv/rosvss`, the container
`ros-vss-feeder`) is the feed. Every container takes the host's network namespace, where the feeder's DDS runs on `lo`
and the databroker listens on 127.0.0.1.

- **What it starts, in order.** The databroker on the generation's planning-sim catalogue
  (`vss-databroker-planning-sim.json`, staged as `in/vss-databroker.json`); the witness, on the paths the table gives a
  writer; with `--bridge broker`, first the native vss monitor (`7160 svc 500`, as `replay --bridge broker` builds and
  starts it) and then the claim bridge on profile 4, the planning-sim live default (`profile_source` live-default); and
  the feeder last, as the feed. Never the CAN provider, the mock provider, the recorder, vcan0 or an app. Only the
  databroker is pulled, and only the recorder image built (the witness runs in it).
- **The feeder's container.** By `images.json`'s `rosvss.amd64` ID, after `docker image inspect` shows that ID,
  linux/amd64, the pin's three labels, the entrypoint `/sdv-aw/aw-entrypoint.sh` (the project's, so the image's own
  never runs), the user `aw`, and a tag that names no other image. Its command is the image's venv Python with
  `feeder_node.py --run-type planning-sim --databroker 127.0.0.1:55555`. It gets the stack's common flags (every
  capability dropped, `no-new-privileges`), `--network host`, `--user aw`, `sdv/aw/ros-env.json`'s domain (73) and
  middleware, its single-host XML staged as `in/cyclonedds.xml` and named by `CYCLONEDDS_URI`, and `ROS_LOG_DIR` in the
  run's `up/ros-log` (never captured). It is never privileged, never given a capability, and gets no `/proc` or `/sys`
  mount, no mount of the host's root or the docker socket, none of the host's pid, ipc, user, uts or cgroup namespaces,
  and no X11 socket or display: `aw_argv_problems` refuses each before docker runs, reading every option in each form
  docker takes (`-u root`, `-uroot`, `-v/proc:/x`, `--user=root` alike). The feeder counts as started once it has
  logged its start record and still runs 3 s later (`FEEDER_SETTLE_S`): `feeder_node.py` logs that record before
  rclpy, its node and its subscriptions come up, so a feeder whose ROS side fails exits just after it, and the run then
  fails with the feeder's last log lines.
- **`--monitor guest`** (with `--bridge broker`, and `--guest-host`, `--guest-console`, `--guest-image` as `step3.py`
  takes them): the stack starts no monitor and the bridge reaches one at `--guest-host`. On the PC that may be this
  host's own non-loopback address, so a native ctl monitor started outside the stack on :7160 can judge kind 4 there.
- **Refused before anything is written:** another run type or none (a `carla-autoware` drive's standard signals come
  from the CAN path, and there the feeder writes only the overlay); `--run-type`, `--bridge` or the monitor options on
  another feed's `up`; `replay` and `exit-test` with the ros feed; `--app`, `--connector`, `--seed` and `--images
  loaded` with it; any host role but `pc` (the feeder's image is amd64 only); the monitor options without `--bridge
  broker`; `--guest-host`, `--guest-console` or `--guest-image` without `--monitor guest` (they are guest mode's, never
  the native monitor's); a ros run that is still up (`stack.py down` first: see `down` below). **Then, before any
  container starts:** a generation without the planning-sim pair; `--bridge broker` while profile 4 is not compiled
  (every frame would get reason 8); a feeder image that is not `images.json`'s; a host user whose uid is not the image's
  `aw` (1000: the run's `up/ros-log` is the host user's directory, and `aw` writes it); a run header that fails C12a; a
  host check that cannot be read.
- **The host check** (the Phase 8 specification's 2.12). `sdv/aw/hostcheck.sh` is read into `host-before.txt` in the
  run directory before the first container starts, and into `host-after.txt` after the sweep; `hostcheck.sh --compare`
  then compares the two (`host-check.json`). Any difference fails the run with the setting named, and nothing reverts
  it. A start that fails is swept at once (the native monitor stopped, every container of the stack removed) and the
  host check read after it. Otherwise `up` leaves the stack running and returns.
- **`down`** closes every ros run still up: those whose feeder carries the label `sdv.stack.ros-run=<run directory>`,
  and those whose directory under `SDV_RUNS` is still open (a ros run's manifest, `host-before.txt`, no
  `host-check.json`). It removes every container of the stack (the feeder with the rest), stops the native monitor each
  run left (its pid in `up/monitor.json`, signalled only while `/proc` says that pid runs the monitor's binary), reads
  the host check and fails on a difference. Before the removal, `down` gives each such run's claim bridge and then its
  witness `docker stop -t 10`, each only while it runs with that run's own label
  (`sdv.stack.run=<run directory's name>/up`): the bridge drains and writes its `stop` event and
  `up/bridge/summary.json` while its monitor still runs (a native one, which `down` stops only after the sweep, or the
  guest's), and the witness then writes its stop record; the feeder and the databroker are removed with no stop first,
  and no container of another start is stopped. A `down` with no ros run does what it did before. **Run `down` after a
  ros run and before any other start.** Every other start (`up` on the other feeds, `replay`, `exit-test`, `live` and
  the probes) removes the stack's containers first, as it did before, and so the feeder; it neither stops the native
  monitor the ros run left, which still holds :7160 (a broker-mode start then fails at its monitor's bind), nor reads
  that run's host check. The run stays open by its directory: the next ros `up` is refused, and `down` still closes it,
  its host check read only then.
- **The records.** The run manifest records `run_type` planning-sim and `feed` ros, the feeder's image ID, config digest
  and base digest, the catalogue's sha256, `ros-env.json`'s values, the witness's paths, and the publishers of the
  feeder's topics as W4 read them (the planning simulator's: RELIABLE, KEEP_LAST 1, VOLATILE; the claim node's verdict:
  RELIABLE, KEEP_LAST 10, VOLATILE), which the feeder's subscriptions match (a test holds them to
  `sdv/rosvss/feeder_node.py`, unchanged). The scenario table is `attribution.py`'s planning-sim table: the feeder for
  the five kind 4 slots, `Vehicle.Speed` and every `ControlCommand` and `Monitor.CtlClaim` leaf; the claim bridge for
  its `Monitor.VssClaim` leaves in broker mode, every one unowned otherwise; `catalogue:vehicle-planning-sim.vspec` for
  the Wheelbase; nothing else. Its checks hold the feeder's configured write set (`sdv/rosvss/mapping.py`'s) and the
  bridge's to the table, one writer per signal, and the witness to its owned paths. `up/attribution.json` adds C8 once
  the feeder runs; the feeder's image is taken for C8 only while it runs (an exited container still names its image).
- **`images.json`'s two Phase 8 entries.** `autoware`: Autoware's Jazzy 1.9.0 image by the digests WP4a's first pull
  read from the index (trust on first use), its ID under the containerd store the index digest; the stack never pulls,
  bundles, deploys or scans it, and its own entrypoint never runs. `rosvss`: the feeder's image in the `bridge` entry's
  shape, amd64 only, built FROM `autoware`'s amd64 manifest digest by `sdv/rosvss/build_image.py`
  (`sdv/rosvss/README.md`).
- **Does not demonstrate** that the feeder writes anything, or runs right with the real rclpy and kuksa-client (WP4b's
  R6 run shows it or not); that a feeder still running 3 s after its start record has made its subscriptions (only that
  it has not exited); that the planning simulator runs at all; that a host setting did not change and change back
  between the two readings of the host check, or, for a ros run another start swept, which of the two starts changed a
  setting (that run's second reading comes only with `down`); any timing.

## Where the expectations come from

Only from the recording directory, which the stack reads and never writes:

- `manifest-line.json` gives the recording's sha256, the seed, the DBC's sha256, the run type and, for
  a sigsim recording, the sha256 of the `sigsim.py` that made it. The log it names (`sigsim.log`, or a
  CARLA recording's `carla.log`) must hash to the line's value and to `<log>.sha256`'s.
- `summary.json`, which sigsim wrote with the recording, gives the trip's segments. The hard brake the
  windows are derived from is its `trip.segments` entry. Its name, seed and frame count per message
  must be the manifest line's and the decoded log's, or the run is refused. The live trip script is
  never run: the run manifest records summary.json's path and sha256, the manifest line, and whether
  the current `sdv/sim/sigsim.py` is still the file that made the recording (reported, not required).
- The DBC is staged only from `~/sdv-cache/dbc/<sha256>.dbc`, checked against the line's sha256 and
  the git blob id in `dbc-sources.json`. The working copy of `slice.dbc` is never staged: others edit
  it, and its hash and comment-free body are only reported. When the cached copy is missing, the run
  is refused with the exact Windows command that exports it: a read-only `git -C <main checkout> show
  <commit>:sdv/vss/slice.dbc` under `cmd /c`, its output redirected into the cache through
  `\\wsl.localhost\<distribution>\`. Run it in PowerShell or cmd; in Git Bash use `cmd //c` with the
  argument in single quotes (Git Bash rewrites `/c`, and inside double quotes bash would also
  collapse the `\\` that starts `\\wsl.localhost` to one backslash, so cmd could not find the path
  and nothing would be written). cmd's redirection keeps the bytes; PowerShell 5.1's `>` re-encodes
  them and would change the hash. A sha256 that `dbc-sources.json` does not know is refused with the
  commands that find its commit: the stack never picks one.
- The recording is the directory `SDV_RECORDING` names (default: the first sigsim recording under
  `~/sdv-recordings`). Point a run at another one with that variable, for the pure tests too: two
  of them read the real recording directory, read-only, and skip without it.

## The rules it keeps

- **Images by digest.** Upstream images are pulled and run only as `repo@sha256:<index digest>`, and
  each image's revision label must equal the pin. The local images are built from the Python base by
  digest and run by image ID. Under Docker Engine's containerd image store a pulled image's local ID is
  its index digest. The app's `APP_IMAGE_ID` is its config digest (SDV Phase 6, above).
- **Loopback only.** The databroker binds `127.0.0.1` (the flag and the environment variable, over
  the image's all-interfaces default) and runs without TLS or authorization (`--insecure`). With
  `--feed dumpfile` the databroker has its own network namespace with no interface but loopback and
  every other container joins it, so nothing of the stack is reachable from the host. With
  `--feed vcan` every container uses the host's namespace, because the SocketCAN interface lives
  there. Before every replay, and three times during it (once the stack is up, a few seconds into
  the feed, and just before the stop), the host's listeners are recorded with their owners, and the
  databroker's namespace's too; a replay fails (`replay`'s exit status, the exit test's verdict) if the
  stack added a listener outside loopback in any of them. Listeners of processes outside the stack are recorded, not held against it. The one allowance
  is the bridge mode's native monitor, by its PID and port (above).
- **No privilege.** Every container drops all capabilities, cannot gain new ones, has a memory cap
  equal to its swap cap and a bounded log; none runs privileged or sees the Docker socket.
- **One writer per signal.** The attribution table is generated from the CAN provider's mapping, the
  mock's behaviour file and the app's write list, then checked (the design's C1 to C12); a failed
  check refuses the run. It is written into the run's directory with the image ID of every writer.
- **A fresh stack per replay.** The databroker keeps last values; nothing from one replay reaches the
  next.

## The exit test

Three replays with the provider's in-process replay (`--dumpfile`), three with the recording played
onto `vcan0` by python-can's player while a capture socket checks the bus carries the log's frames.
For each: the app's decisions and the mock provider's own writes of the hazard light (its log, which
must hold no line above INFO) against the
windows the recording's trip summary gives for the hard brake; the values written into the databroker
against the recording decoded by cantools, three ways; the listeners; the behaviour key compared
across the three: the app's decisions, the targets the app itself requested (value and the outcome it
logged), the lights as the mock provider wrote them, and the app's state sequence. Then the catalogue
load check: the generated catalogue (with and without the CAN mapping) and the VSS 6.1 plus overlay
catalogue of the S2 check, each loaded into the pinned databroker and probed, every enum node of the
6.1 file among the probed paths.

**The key and the window gate read lossless sources only**: the app's own log and the mock
provider's own. The recorder's hazard rows are a kuksa.val.v1 subscription of one buffered update,
which the databroker lets drop an update when it lags, so a dropped one must not make two identical
behaviours differ, or fail a window. They stay in a replay's `result.json` as `lights.recorder`, the
databroker's v1 view of the light, with a consistency check: its current rows against the mock's
writes and its target rows against the app's actuations, each a subsequence of them with no more rows
missing than the capacity-1 lags the databroker logged (less those the recorder's CAN-fed rows
already account for). That check is reported, and the verdict only counts it
(`recorder_lights_consistent_replays`); it is not a gate.

**What the mock provider's log says, and what the gate does with it.** The gate reads the mock's
`Feeding '<path>' with value X` lines, and they are written *before* the write they name. This is the
r4 critic's reading of the pinned image's source (`/mock/mockservice.py` and `kuksa_client/grpc/` in
the mock image `bc61857a...`; not re-read for this README): the mock logs the line, then
calls the databroker; the image's kuksa-client turns every failed call into an exception that the
mock's own handler for gRPC errors never catches. So a failed write leaves its `Feeding` line and then
an error: a traceback after it (an `ERROR` line from the mock's loop, which also ends the loop), or
`Exception in thread databroker-connector` for the initial write. Reading the `Feeding` lines alone
would pass such a replay, so the gate also wants the log clean (`rc.mock_log_clean`): after dockerd's
stamp, every line an `INFO:<logger>:` record. A traceback and each of its lines, an `ERROR`, `WARNING`
or `DEBUG` line, an empty line and a line with no stamp each fail it, and a replay's `result.json`
names them (`lights.mock_log.offending_lines`, the first 50, and `offending_total`). A clean log with
three right lines says the mock logged no failure; it does not say the databroker accepted each write,
and the databroker's own value of the light is seen only by the recorder, whose rows are reported and
not gated.

The three value checks, all required:

- **The witness** (`witness.py`, kuksa.val.v2, a buffer of the databroker's maximum): every value of
  the six CAN-fed paths, count for count, equal to the decoded value rounded to float32, with no
  allowance, no value in the initial notification, no stream that ended or failed, its own stop
  record agreeing with its log, and no lag the databroker logged for it. A comparison in which
  nothing was compared is not a pass. Each of these is a gate of its own in a replay's
  `result.json` (`witness_values.gates`), so a failed witness says which, and the tests hold every
  gate one by one. This is what lets every replay be judged on every value.
- **The recorder** (the csv-provider's `recorder.py`, kuksa.val.v1): the design's VSS-layer witness,
  kept as its CSV. The databroker gives a v1 subscriber a buffer of one and drops an update when it
  lags, so its rows are aligned against the decoded values, within half an LSB, and the values it
  did not record are bounded by the misses the databroker logged for subscribers of that capacity.
  The recorder and the mock provider share that count, so it cannot say whose update was missed.
- **The app's own subscription** of its two inputs, exactly.

A record without the witness leaves any value the recorder missed unverified at the VSS layer.
The record's own gates determine its coverage; the recorder alone cannot establish it.

## What this does not demonstrate

Any timing: the replays are paced by wall clock, and every window carries a mapping allowance of one
dynamics period. CAN arbitration, error frames or bus timing: vcan has none and `--dumpfile` never
touches a bus. Anything about the QNX guest: no claim bridge runs, and the Monitor branch stays
empty. That the one-writer rule held while a run went: the databroker runs without authorization, so
the table is a checked declaration, not an enforcement; the witness sees values, not who wrote them.
That the databroker accepted each write the mock provider made: the gate reads the mock's own log,
written just before each write, and only the recorder's lossy rows come from the databroker's side.
Whether the witness held every value in a given run is that run's record.

## Local CI in WSL without git on this checkout

This worktree's `.git` names a Windows path, so WSL's git cannot read it, and no git is to run in
WSL on it at all. The tests whose code runs git against the checkout are therefore deselected there
by `wsl-pytest.args`, one `--deselect` per line, which pytest reads with `@`:

    # from the checkout's root in WSL
    PYTHONDONTWRITEBYTECODE=1 ~/civenv/bin/python -m pytest -q -o addopts= -p no:cacheprovider @sdv/stack/wsl-pytest.args

`-o addopts=` drops pyproject's own `-q`: with both, pytest runs at `-qq` and prints no totals line,
so the passed, skipped and deselected counts could not be read off the output.

The list is every test that takes the `rig` fixture in `tests/test_aws_tooling.py` or in
`tests/test_aws_noble.py`, which takes the same fixture (each runs
`scripts/aws/drive-metal.sh`'s main, whose `outside_repo` runs `git -C scripts/aws rev-parse`, and
`upload` also runs `git get-tar-commit-id` in the checkout) and
`tests/test_claims_lib.py::test_repo_slug_from_git_remote` (`git remote get-url` on the repo root),
and the one test of `tests/test_sdv_cloud.py` that runs git at all: the twin driver's `branch-scan`
searches this checkout by default, and its test, on a fixture repository, runs from Windows with
the others (plan Phase 4 WP6).
It was found by searching the tests, and every script and module they run, for a git invocation.
The rest use a throwaway fixture repository under the temporary directory
(`tests/test_results_guard.py`), a copy of a script outside the checkout, or no git at all.
`tests/test_sdv_stack.py` checks that the file lists exactly these. The deselected tests run from
Windows instead, where git reads the checkout: in Git Bash, from the worktree's root,

    PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -o addopts= -p no:cacheprovider tests/test_aws_tooling.py tests/test_aws_noble.py tests/test_claims_lib.py::test_repo_slug_from_git_remote tests/test_sdv_cloud.py::test_branch_scan_finds_a_literal_one_commit_adds_and_the_next_removes_and_one_only_in_a_commit_message

(`-o addopts=` for the same reason.) Never export `GIT_DIR` or `GIT_WORK_TREE` around either run.

From SDV Phase 4 on, the WSL run also sets `SDV_REQUIRE_GEN=1`, writes a junit report (`--junitxml`) and ends
with `python tests/twin_gate.py <report>`: a twin test that lacks the generated catalogue or the vss venv then
fails instead of skipping, and the run fails when a twin test or the `Monitor` guard of
`tests/test_sdv_vss.py` was skipped or did not run (`sdv/connector/README.md`, `tests/twin_gate.py`).

## No per-host manifest from the stack

The design's local manifest (`~/.local/share/sdv-local/manifest.json`, one per host) is not written,
and each run's `manifest.json` stands in for it, for three reasons:

- **Its image IDs are the updater's to hold.** The design defines `image_id` as the config digest, the
  pin that is the same after a registry pull and after `docker load`; under Docker Engine's containerd
  image store, which this host uses, the ID Docker reports is the store's (a pulled image's index
  digest, a built or loaded one's manifest digest). Phase 6 settled that meaning (the config digest
  everywhere, with the store ID beside it), and the file is the updater's (`sdv/ota`), not this stack's.
- **It is a deploy-time access list, read by the updater.** The dev loop writes it by hand, after
  verifying each entry, and the updater loads it. A file that `prepare` rewrote on every run would be a
  run artifact dressed as a vetted list.
- **Its scenario entry needs outcomes of a run.** `ownership` points at the scenario table beside the
  recording, and `allowed_scenarios` means "tested with". Here the scenario table is written into the
  run directory so the recording directory stays untouched, and the testing is the run itself.

The run manifest records what Phase 1's checks need: every component with its image ID and how it
was pulled or built, the catalogue, the recording with its manifest line and summary.json by
sha256, the DBC and the scenario table.
