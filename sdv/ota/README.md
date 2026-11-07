# sdv/ota: the updater ota-lite

SDV Phase 6 WP1. ota-lite is the updater: the only holder of Docker control on a
host, run as a transient systemd unit (owner decision D3). It acts on app-class entries of the host's manifest only
and never on a platform image, its own unit, the guest's image or the manifest. A spool record from the connector
asks for an image and/or a scenario; the updater decides, acts, and writes one status record back.

## Commands

    ota_lite.py check --manifest M --host-role R --arch A
    ota_lite.py run --manifest M --host-role R --arch A --state DIR [--once] [--cpuset LIST] [--after-start CMD]
                    [--registry-file F] [--spool-dir D] [--status-dir D] [--runtime-dir D] [--docker-config D]
                    [--marker P] [--lock P] [--home D] [--docker PREFIX] [--kuksa HOST:PORT]
    ota_lite.py teardown [--docker PREFIX]
    ota_lite.py reprocess --state DIR
    ota_lite.py unit start (run's arguments) [--cpus LIST] [--python P] | unit stop | unit status

- `check` loads the manifest for `--host-role` and `--arch` and says ok, or why not.
- `run` polls the spool every second and acts on each new record; `--once` reads it once, acts, and exits.
- `teardown` stops and removes every container labelled `sdv.ota.app`, prints how many, and exits 0 only when none
  is left.
- `reprocess` clears the processed mark, so the spool's record is processed again.
- `unit start` makes the four directories of the table below with the owners and modes given there, refuses when a
  unit `ota-lite` is active, and runs
  `sudo -n systemd-run --unit=ota-lite --property=Type=exec --property=NoNewPrivileges=yes
  [--property=AllowedCPUs=<cpus>] --collect <python> -B <ota_lite.py> run ...`. `--cpus` is required on `orin`.
- `unit stop` stops the unit and reads it back inactive.
- `unit status` prints the unit's state.

## Files

Every path is an argument; the defaults are these.

| what | path | rule |
|---|---|---|
| spool | `/run/sdv-local/spool/v1/desired.json` | read only here; owner the login, directory 0755 |
| status | `/run/sdv-local/status/v1/status.json` | written only here; root, directory 0755, file 0644 |
| runtime | `/run/sdv-local/ota/` | root, 0700 |
| credentials | `/run/sdv-local/ota/docker/` | the `DOCKER_CONFIG` of every pull; root, 0700 |
| scenario hand-off | `/run/sdv-local/ota/scenario.json` | nothing in Phase 6 reads it |
| twin-control marker | `/run/sdv-local/twin-control` | its existence is the mode (D11) |
| scenario lock | `/run/lock/sdv-scenario.lock` | never created by the updater; missing, it refuses every scenario request (step 8) |
| state | the directory `--state` | never `/var/lib`, never in the repo, must exist |
| manifest | `--manifest` | outside the repo |
| registry file | `--registry-file` | outside the repo, mode 0600, root-only on a pulling host (D7); read by `run` only |

- The spool: the connector writes it; `sdv/connector/spool.py` is its definition.
- The status: exactly `image_id`, `scenario`, `result` in that order, compact ASCII, at most 256 bytes, written
  through `.status.json.tmp` and a rename. It never carries a cause. None exists before the first record is
  processed. Its `image_id` is read from Docker: the `sdv.ota.image` label of the `sdv-ota-app` that runs, or null
  when none runs. The state is never asked, so a crash between a start and the state's write leaves no false status.
- The credentials directory: no login is made by the updater; whatever put credentials there is outside it.
- The state directory holds `state.json`, `processed` and `ota-lite.jsonl`.
- The manifest's schema is `sdv/ota/manifest.schema.json`: manifest-classes section 9 with the spec's changes. A
  `local-build` pull carries `store_id`, and an `ecr` ref reads `<registry>/sdv-twin/<name>@sha256:...`.
- The registry file is the one `twinctl ecr-config` writes. Its `registry` key is the one place the registry host
  stands on a pulling host (D7). `unit start` runs as the login and never opens it: it refuses a missing file, a
  path inside the repo, a symbolic link, anything but a regular file and a group or other bit, as far as the login
  can look the path up. `run` reads it as root in the unit and refuses before anything starts. So a file the login
  cannot look up is checked only as the unit starts: `unit start` can read the unit back as active before that
  refusal ends it, and `unit status` then says it is not.
- The scenario lock's default is the bridge image's path. The stack's bridge locks its run's own `scenario.lock`,
  bind-mounted there, so `--lock` must name that host file for the lock rule to apply.

## One record

The updater decides in this order, and the first refusal wins:

1. at most 256 bytes;
2. UTF-8 JSON, one object, no duplicate key;
3. the form of `spool.py`;
4. the `image_id` is a container entry of the manifest;
5. the entry is of class `app`;
6. the scenario is defined;
7. the pair is in the `allowed_scenarios` of the new image, or of the image Docker runs;
8. a scenario only with the twin-control marker (D11), and then a free scenario lock.

Then the hour's bound (below). Then the act: get the image (`ecr` pull, `tar` load, or `local-build`); prove its
config digest from a `docker save` stream before the running container is touched; `docker stop -t 10` and remove
the old container; start the new one; run `--after-start` with the container's name appended; check its health; roll
back if the check fails.

- An old container that is still there after the stop and the removal refuses the record at `stop`, and nothing
  is started. If the stop worked and only the removal failed, the old container is left stopped, and the status
  says that none runs.
- A record for the current image that Docker runs is applied with no restart. If Docker runs a container the
  state does not record as current, for example after a crash between a start and the state's write, the
  container is replaced: the requested image is started and checked.
- A scenario's hand-off is written to `.scenario.json.tmp` before anything is touched. If it cannot be written, the
  record is refused at `handoff`. It is renamed into place only when the rest of the record is applied, and a
  rollback or a refusal removes it. If that rename fails after an image passed, the record is still `applied`: the
  status keeps the old scenario and the log says why. This is the one case where `applied` covers less than the
  record asked for.

A record equal in bytes to the last processed one is not processed again.

## The start

    docker run -d --name sdv-ota-app --label sdv.ota.app=<name> --label sdv.ota.image=<image_id>
      <COMMON exactly as stack.COMMON> [--cpuset-cpus <cpuset>]
      --network host --read-only --tmpfs /out:rw,nosuid,nodev,noexec,size=16m
      -e APP_IMAGE_ID=<image_id> -e KUKSA_ADDRESS=127.0.0.1:55555 -e HBH_LOG=/out/hard-brake-hazard.jsonl
      --restart no <proved reference>

`COMMON` is equal to `sdv/stack/stack.py`'s (a test holds it). `--cpuset-cpus` is given exactly when the updater has
a cpuset. No other flag, mount or variable: never `docker.sock`, `--privileged`, a host mount or `--user`. The image
is run by the reference whose config digest was proved, and `APP_IMAGE_ID` is the config digest.

## Health

Within 30 s, at least 3 heartbeats of the started entry's `app`, `app_version` and `image_id`, with `seq` rising
from one to the next. Each is valid against the AppState schema, the last one has the state `running`, and the
container is still running. A container that exits fails at once, and a heartbeat of another `image_id` never
counts. The leaves are read through kuksa-client in `ota_kuksa.py` only; the venv takes kuksa-client 0.6.0 from the
locks of `sdv/apps/hard-brake-hazard`. The client makes no call when it connects, and each read is one call
bounded by `RPC_TIMEOUT_S` (1 s). A databroker that does not answer makes reads with nothing in them, so the
check still ends at its deadline, overshooting by at most one read.

## Rollback

A failed start or check goes back to the rollback target, if it is still an app-class entry: the same flags,
checked again, and the status says `rolled-back`. Otherwise no app container runs and the status carries
`image_id` null.

The rollback target is the image Docker ran as the recorded current one when the switch began. If none ran that
way, the target recorded at an earlier switch is kept. A crashed or unknown image is never a rollback target.

No rollback is started in two cases:

- The failed container could not be removed. The status then names what Docker runs.
- The target's image is no longer in the local store. This is read with `docker image inspect` first, because a
  `docker run` of a missing image would pull it implicitly, outside the one pull per record and without the
  credentials directory.

Remove images only after the updater is stopped (WP6's day, WP7's teardown): the read before a rollback cannot hold
against a removal that races it.

## Bounds

At most 12 container starts in any hour, rollbacks included: a record needs room for its own start and, when
it has a rollback target, a rollback's. One pull per record. No retry: the processed mark is written before the act.

## The log

`ota-lite.jsonl` in the state directory holds each record, each refusal by step and reason, and each pull, load,
proof, stop, start, after-start, check, rollback, hand-off and status. It never holds a registry host, a credential,
docker's error text from a command that names the registry, or a value of the names file. The state keeps an `ecr`
reference with `<registry>` in it. The log is appended to without following a symbolic link. A link, or anything
but a regular file, at its path stops the updater.

## Tests

`tests/test_sdv_ota.py` runs on stand-ins only: Docker, `sudo`, `systemd-run`, `systemctl`, the AppState source and
the clock. In WSL, from the repo root:

    ~/civenv/bin/python -m pytest -q -o addopts= -p no:cacheprovider tests/test_sdv_ota.py

## What it does not demonstrate

- Secure OTA: there is no image signing, no secure boot and no root of trust, and registry access control is not
  signing.
- A platform, firmware or host rollback: only the app container moves.
- Any timing.
- That a heartbeat is a correct app: it is the app's own report.
- Any run against a real Docker, databroker or app: that is WP5 and the drill.
