# sdv/drill: the OTA drill

SDV Phase 6 WP3. The drill moves the app container of a running stack through three
versions and two refusals, by the updater (`sdv/ota`), and records what the updater's status says after each step.
The same six steps run on every host; `compare` holds the hosts' sequences against each other. Functional only.

## Commands

    drill.py manifest --host-role R --arch amd64|arm64 --transport local-build|tar|ecr --stack-run DIR --out FILE
                      [--pins FILE] [--store-ids FILE] [--tar FILE] [--recording DIR]
    drill.py run      --manifest FILE --state DIR --record DIR --stack-run DIR --sim-python PY --ota-python PY
                      [--via spool|twin] [--cpuset LIST] [--registry-file F] [--docker-config D] [--home D]
                      [--spool-dir D] [--status-dir D] [--sudo PREFIX] [--docker PREFIX] [--step-timeout-s N]
    drill.py compare  --host ROLE=DIR [--host ROLE=DIR ...] --out DIR

    build_drill.py build --arch arm64 [--write-pins] [--out FILE] [--docker PREFIX]
    build_drill.py build --arch amd64 --store-ids FILE [--out FILE] [--docker PREFIX]
    REPO_COMMIT=<commit> build_drill.py save --out DIR/sdv-drill.tar [--docker PREFIX]

Exit status of `drill.py`: 0 when the run's verdict is ok (or the hosts compare equal), 1 when it ran and the verdict
is not ok (or they differ), 2 for a refusal: nothing started, or what started was undone. `manifest` ends with the
status of the updater's `ota_lite.py check` on the file it wrote. Both tools are standard library only (the hosts'
Python 3.12); `drill.py` also loads the connector's `spool.py`, and `build_drill.py` sdv/arm64's `a64scan.py`.

- `manifest` writes one host's manifest: the three versions of `hard-brake-hazard` (class app, each allowed the
  drill's one scenario only), the claim bridge (class platform, by its config digest; the updater never starts it) and
  the stack run's scenario (its staged `in/sigsim.log` and its `ownership.json`, each by path and sha256). arm64's
  images come from `--pins` (default `sdv/drill/drill-images.json`) and the bridge's from images.json's `bridge.arm64`;
  amd64's, the bridge's included, from `--store-ids`, on local-build only. Each app entry's pull is its store ID
  (local-build), its own tar (tar) or `<registry>/sdv-twin/hard-brake-hazard@<manifest digest>` (ecr: the placeholder,
  never a registry host; the digest is the pin's `ecr_manifest_digest` where the pins file holds one, its store ID
  otherwise). The host roles are stack.py's `HOST_ROLES`, read at run time; the updater's check judges. A session's
  manifest and tars are never overwritten: an existing `--out`, or a tar already in `drill-tars/`, is refused; so is a
  tar transport whose `--out` directory has a character outside the manifest's path form (`[A-Za-z0-9._/-]`), before any
  tar is written.
- `run` drives the six steps against a stack already up (`stack.py up --feed vcan --app external`: the caller's, never
  started or stopped here). It starts the updater with `ota_lite.py unit start` (`--cpus` is `--cpuset`; what the
  launcher says is printed line by line to the drill's output, so a refusal has its reason there, and never enters the
  record), plays the stack's staged recording on vcan0 in a loop with the sim venv's `python -m can.player`, writes each
  step's spool record (`--via spool`) or `next-step.json` for the connector to bring through the twin (`--via twin`),
  waits for the updater's answer and reads the status. At the end, whatever happened: the player stopped, `unit stop`,
  `teardown`, and the updater's log and state copied into the record. A player each of whose starts exited non-zero
  never played the recording: that is a problem, and the verdict is not ok.
- `compare` writes `compare.json` from each host's `drill-result.json`: equal only when every host holds the six steps,
  each answered, with the same key. A step missing on a host (a run refused or cut short) or without an answer is a
  difference at that step, even when every host lacks it alike; a record whose steps are not steps 1 to k in order (k
  at most six) is refused.
- `build_drill.py build` makes v2 and v3 on v1, proves each, scans the arm64 ones, and writes the pins (arm64) or the
  store IDs (amd64). `save` writes the save of the three arm64 IDs and its sum file for the bare-metal session.

## The six steps

| n | asks | expected status after it | refusal step in the log |
|---|---|---|---|
| 1 | image v1 | 1.0.0, scenario null, `applied` | none |
| 2 | image v2 | 1.1.0, null, `applied` | none |
| 3 | image v3 | 1.1.0, null, `rolled-back` | none (a `rollback` event) |
| 4 | the bridge's image (class platform) | 1.1.0, null, `refused` | 5 |
| 5 | an image ID in no entry (a documentation value) | 1.1.0, null, `refused` | 4 |
| 6 | the drill's scenario, no image, no marker | 1.1.0, null, `refused` | 8 |

A step's answer is the first `status` event in the updater's log after the `record` event of that step's record (the
sha256 of its bytes); only then is the status file read. Steps 4 to 6 write the same status bytes, and their events
tell them apart. A step with no answer within `--step-timeout-s` is a problem, and the next step runs.

## Refused before anything starts

A stack run that is not up by stack.py's own record of it (its run manifest saying `app: external` and the manifest's
host role, its `up/` directory, its staged recording, its databroker running under its `sdv.stack.run` label); a stack
whose CAN provider is not running (the recording on vcan0 reaches the databroker only through it, and an app without
fresh inputs is degraded, so no health check could pass); no vcan0; a QEMU that runs (D6: no guest); an `sdv-ota-app`
container; an active unit `ota-lite`; the twin-control marker; a record directory that exists; a state directory with
anything in it; a record already in the spool; a manifest that is not a drill's; `REPO_COMMIT` set to anything but a
commit; a `--sim-python` or `--ota-python` that is not an executable file; what `ota_lite.py unit start` would refuse
only once the record directory is made (an ecr manifest without `--registry-file`, the orin without `--cpuset`); a
`--sudo` prefix that cannot run `cat -- /dev/null` (the updater's log and state are read through it, so every step
would otherwise wait its whole timeout).

## The record

`--record` holds:

- `drill-result.json` (format 1): `host_role`, `arch`, `transport`, `via`, `repo_commit` (`REPO_COMMIT` or null),
  `manifest_sha256`; per step `n`, `asks`, `image_id` (information: it differs by architecture), `app_version` (the
  manifest's for the status's `image_id`; null when null), `scenario`, `result`, `refused_step`, `rollback`,
  `waited_s` (information, never judged), `timed_out`; then `player`, `end`, `verdict` (`ok` when every step equals
  the table and nothing else went wrong) and `problems`.
- `status-<n>.json`: the status file's bytes after step n.
- `ota-lite.jsonl` and `state.json`: the updater's own, read through `--sudo` (they are root's, mode 0600).
- with `--via twin`, `next-step.json`: the last step's number and the record it expected.

It holds no registry host, no credential and no host path.

## The images

- v1: arm64 is images.json's `local.hard-brake-hazard.arm64` pin; amd64 is the PC's own build (`stack.py prepare`).
- v2: v1 plus one layer, `/app/hazard.py` replaced by the app's own file edited on a staged copy in two constants:
  `APP_VERSION` 1.1.0, and `DECEL_OFF_MPS2` 2.5 for 3.0 (the hazard lights stay on until the deceleration falls below
  2.5). Each old text must stand once. Label `org.opencontainers.image.version=1.1.0`. Tag
  `sdv-drill/hard-brake-hazard:1.1.0` (`-arm64` for arm64).
- v3: v2's image with only its entrypoint changed, to one that exits non-zero at once: a new config and manifest over
  v2's layers, loaded with `docker load` (tag `...:1.2.0`). No layer, and its config differs from v2's in the
  entrypoint alone. Its manifest entry says 1.2.0; it never publishes a heartbeat.
- `drill-images.json` pins the arm64 v1 (a copy of images.json's pin, held equal by a test), v2 and v3, each with the
  pair it was made on. The amd64 images are never pinned. A version may also carry `ecr_manifest_digest`, the digest
  the registry reports after `twinctl push` (WP4), which the orchestrator adds when it is not the store's ID; `manifest
  --transport ecr` then pulls by it (`build_drill.py build --write-pins` writes none).
- `save` writes `docker save` of the three arm64 IDs and `<tar>.sha256` beside it: `<64 hex>  sdv-drill.tar` and
  `commit <REPO_COMMIT>`. For tar transport `manifest` splits that save into one tar per version beside `--out`
  (`drill-tars/`), since the updater's tar transport loads a tar of one image. The Orin's images go to ECR by
  `twinctl push` (WP4), one call per version.

## What it does not demonstrate

Anything on a real stack, updater or host by itself (the tests run on stand-ins); secure OTA (no signing, no secure
boot, no root of trust); a platform or host rollback; that a heartbeat is a correct app (it is the app's own report);
that v2's change shows on the bus or in the twin; with `--via twin`, anything about the twin beyond the connector
having written the record; any timing (`waited_s` is information only).
