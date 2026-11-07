# sdv/connector: the twin connector, the device side

SDV Phase 4, the minimal cloud twin. This directory is the device side of
the twin: what runs on a Linux host beside the slice's stack (`sdv/stack`), reads allowlisted VSS paths from
the local databroker and sends them up an authenticated uplink. The account side is `sdv/cloud`.

Labels such as A3 row 13, B2, C9, D8 and the gap letters are the project's internal plan items; they are kept so that
the code and its tests can be read against that plan.

## What it is

After Phase 4 WP3 it holds the whole device side: the connector's packaging, the allowlist (its source list and
the generator of the frozen module), AppState's field whitelist, the connector's logic, the one module that
talks to the SDK, the image and its build, and the probes. `sdv/stack/stack.py --connector` starts the image
beside the slice's stack. Unit tests use fakes; the opt-in tests exercise it beside a local test broker.

| file | what it is |
|---|---|
| `limits.py` | Every design value of the connector in one place: the two rates, the batch and shadow intervals, the limiter's caps, the retry spacing after a shadow publish the uplink failed, the size bounds, the waits, the uplink's settings (port, keep-alive, time-outs, the uplink's own reconnect back-off, the hold on the SDK's reconnect timer), the start spacing and who holds it. No other module holds a design value of its own (what else is a number there is the loop's poll and shortest sleep, the limiter's rounding guard and the time a closing source waits for its thread); the stack's start rule and the threshold derivation read it too. |
| `pathset.py` | The effective path set: what the cloud's `config` may make of the frozen allowlist. Exact, case-sensitive membership in the frozen tuple and nothing else; it can narrow, never widen. |
| `source.py` | The signal source: the latest value of each subscribed path. `KuksaSource` on the local databroker (one kuksa.val.v2 Subscribe on exact leaves, retried when the stream ends), `FakeSource` for the tests. |
| `envelope.py` | The telemetry batch, version 1: one JSON object with the paths named once and positional rows of numbers. |
| `shadowdoc.py` | The `vss` reported document (every allowlisted key, null where absent), its change rule (seq alone drives nothing), the `config` report, and the guards for the service's 8 KB and 8-level limits. |
| `limiter.py` | The hard caps, the last thing before the wire: only the connector's own topics, telemetry at most once a second and 60 times in any 300 s at 16 KiB each, shadow publishes at most 10 times in any 300 s at 4 KB each. The window is closed (a publish exactly 300 s old still counts), and float rounding is taken to the side that keeps the cap. |
| `config.py` | What a desired state of the `config` shadow means here: a rate, a narrowing, and two requests for the spool. A refused value has no effect at all. |
| `spool.py` | The two-field spool record and its write-then-rename: one of the two files the connector writes. |
| `startstamp.py` | The start spacing, held on the device: the time of the last start in `started.json` beside the spool record, and the refusal of a start within 120 s of it. The other file the connector writes, and the only one it reads back. |
| `status.py` | The updater's status record (SDV Phase 6): reads `status.json` in the status directory by the record's rules (exactly its three keys, 256 bytes at the most, no duplicate key, each value of its form) and gives the record or why not, a reason that holds no value. The one file the connector reads that it did not write. |
| `topics.py` | The exact topic strings for a thing and a rule: four to publish to, five to subscribe to, no wildcard. |
| `uplink.py` | The seam to whatever carries the messages (`connect`, `publish`, `subscribe`, `close`) and `FakeUplink`. No SDK import: the one importer is `uplink_aws.py`. |
| `uplink_aws.py` | The seam on the device SDK, and the only module that imports it: one MQTT 3.1.1 connection built with `mtls_from_path`, every setting given and none left to the SDK's default, no re-send and nothing left in the SDK's offline queue to be sent later (below, with what that rests on). |
| `Dockerfile` | The connector image: the pinned base by index digest, the lock installed hash-checked with no resolver and then `pip check`, the modules and the frozen allowlist baked in, a user of its own, one entry point. Nothing of a device is in it. |
| `build_image.py` | Builds that image for amd64 and arm64 with buildx from a context staged outside the repo, after holding the frozen allowlist to a fresh generation; reads the pins back and writes `sdv/stack/images.json`'s `connector` entry; scans the arm64 image's layers with `sdv/arm64`'s scanner. Never pushes. With `--burst` it builds the burst tool's own test-only image instead and writes no pin. |
| `connector.py` | The loop, with a clock passed in, and the entry point, which builds the uplink inside the limiter. |
| `requirements.lock` | The connector image's packages, hash-pinned, wheels only: the app lock's 17 pins unchanged (`sdv/apps/hard-brake-hazard/requirements.lock`: kuksa-client 0.6.0 and its resolution) plus `awsiotsdk` 1.31.0 and `awscrt` 0.36.1. Made with the app lock as constraints, not resolved fresh. The amd64 image is built from it. |
| `requirements.aarch64.lock` | Its arm64 twin: the same 19 names and versions, the `py3-none-any` files with their hashes, the six native wheels (`awscrt`, `grpcio`, `grpcio-tools`, `protobuf`, `wcwidth`, `websockets`) as their manylinux aarch64 files. |
| `sdk-requires.json` | What the pinned `awsiotsdk` wheel declares (its METADATA's `Requires-Dist` and `Requires-Python`), bound to that file by its sha256. The SDK names one exact `awscrt` version; the locks are installed with `--no-deps`, which would not notice another. |
| `lockcheck.py` | Compares a directory of downloaded wheels with a lock (exactly its files, each at its sha256) and the SDK wheel's metadata with `sdk-requires.json`; `pair` checks a lock against the record alone. Standard library, no network. |
| `ca.json` | The real endpoint's root CA, pinned by the URL its file was fetched from over HTTPS (the vendor's `AmazonRootCA1.pem`, Amazon Root CA 1) and that file's sha256, and nothing else. The file itself goes into the device directory as `ca.pem` (the uplink's `ca_filepath`); it is in no image and not in the repo. |
| `twin_allowlist.json` | The allowlist's source list, version 1: the 16 exact VSS leaves that may reach the twin (8 VSS paths and the app's 8 AppState leaves), each with the type, datatype and unit it must have in the generated catalogue and its channels (S: the `vss` named shadow; T: batched telemetry). Its set is `attribution.ALLOWLIST_V1` (`sdv/stack/attribution.py`); a test holds the two equal. |
| `gen_allowlist.py` | Checks the source list against the generated catalogue (`sdv-out/gen/vss-ids.vspec`) and writes the frozen module `sdv-out/twin/twin_allowlist.py`, or refuses and names the entry (below). Run in the vss-tools venv, which has the YAML reader. |
| `appstate.py` | AppState's field whitelist: assembles the leaves of one app's sub-branch into one record, validates it with the keywords the flat schema uses (`sdv/apps/hard-brake-hazard/appstate.schema.json`; the validator `tests/test_sdv_stack.py` held the app's records to, moved here), and checks that the record's `app` derives the sub-branch it came from. Standard library. |
| `probes/probe.py` | The two opt-in probes (`SDV_CONNECTOR_PROBE=1`, WSL Docker), below. |
| `probes/subscribe_probe.py` | Probe 1's client, run inside the recorder image: one kuksa.val.v2 Subscribe on an actuator's current value, an attribute and the eight AppState leaves. |
| `probes/uplink_driver.py` | Drives the image's real uplink one command at a time, for the opt-in broker tests. Mounted into a test's container, never staged into the image: it reaches the uplink without the limiter. |
| `probes/canary_writer.py` | Plants a value in each leaf a test's plan names, or reads them back, for the opt-in canary run. It spells no path. |

**The locks.** `tests/test_sdv_connector.py` holds: each connector lock is the app lock of its architecture,
every shared pin equal in version, sha256 and file, plus exactly the SDK pair; the aarch64 lock is its x86_64
twin with the native wheels swapped; and the lock's `awscrt` is the one version `sdk-requires.json` says the
SDK wheel declares. To re-check the files against PyPI (the only step that needs a network):

    pip download --require-hashes --no-deps --only-binary=:all: -d DIR -r sdv/connector/requirements.lock
    python3 sdv/connector/lockcheck.py wheels DIR

and for arm64 the same with `--platform manylinux2014_aarch64 --python-version 3.12 --implementation cp --abi
cp312 --abi abi3 --abi none`, `requirements.aarch64.lock` and `--arch aarch64`. Delete `DIR` afterwards; no
wheel is kept in the tree.

**The allowlist.** The frozen module is generated, never written by hand and never committed (`sdv-out/` is
ignored), in WSL from the repo root:

    ~/sdv-venv/bin/python sdv/connector/gen_allowlist.py            # writes sdv-out/twin/twin_allowlist.py
    ~/sdv-venv/bin/python sdv/connector/gen_allowlist.py --check    # exit 1 unless it is a fresh generation

It is a second step after `sdv/vss/generate.py`, not one of that run's outputs: the bridge image bakes that
run's manifest in, so a new output there would move a pinned image ID though nothing the bridge runs changed.
The module records the sha256 of the id file it read instead, with the source list's and the schema's, so a
regenerated catalogue, an edited list or an edited schema each make `--check` fail until it is run again.

- **What it refuses**, exit 1 with every problem on stderr and nothing written: an entry that is not a node of
  the catalogue (an exact, case-sensitive match: nothing is trimmed or folded, so a case or whitespace variant
  is simply not there), that is a branch, that holds a wildcard, whose type, datatype or unit differs, that is
  listed twice, that lies in the `Monitor` branch (the node itself or anything under it), or that lies in
  `ControlCommand`. It also refuses the whole run when the excluded prefix names no branch of the catalogue
  with a leaf under it (a renamed branch would otherwise make it refuse nothing), when an AppState sub-branch
  is listed in part or its leaves differ from the schema's `x-vss-leaf` annotations, and an `--out` inside
  the tracked tree.
- **What the module holds:** the version; the ordered path tuple; each path's staticUID; an FNV-1 32 digest over
  those UIDs as u32 little-endian in tuple order (the kind 4 catalogue digest's construction); each path's
  node and channels; the AppState sub-branches and the leaf-to-property map; the three sha256 values. It checks
  its parts against each other at import, so a careless hand edit does not import; a careful one is what
  `--check` is for. It is baked into the connector image (WP3) and never mounted or read from a file at run
  time; the cloud's `config` can only narrow the set, by exact membership in the tuple (WP2).
- **No path of the excluded branch is spelled here.** The generator takes it from `attribution.MONITOR_PREFIX`; the
  tests enumerate its leaves from the generated catalogue and hold that the enumeration is that catalogue's
  branch, not empty, and contains the claim bridge's own write set.
- **AppState.** `appstate.checked(schema, fields, branch, values)` gives the record or `None` with the reasons,
  which name properties and keywords and never a value. The validator is stricter than a Python JSON Schema
  validator in two places: an integer property takes an int and never a float, and a pattern's `$` is the end
  of the input as ECMA-262 has it (Python's also matches before a trailing newline).

`tests/test_twin_allowlist.py` holds all of it (the design's A1, A2, A3, A7's connector half and A11) and, under
the CI recipe, fails instead of skipping when the catalogue, the venv or the frozen module is missing.

**The probes.** Both are refused without `SDV_CONNECTOR_PROBE=1`, write only under `--out` (refused inside
the repo), use containers and a network of their own names (never the stack's) and remove them whatever
happens. Neither publishes a port or runs a privileged container.

- `probe.py databroker`: a throwaway databroker 0.7.1 (the stack's pinned image, `--network none`) loaded with
  the generated catalogue. It records, for the hazard light's current value, Wheelbase and the eight AppState
  leaves, whether a v2 subscription's first response carries each current value and whether a later write
  arrives, with `GetValue` beside it. It pulls and builds nothing.
- `probe.py broker`: `eclipse-mosquitto` 2.0.22, pinned in `sdv/stack/images.json` under `test_only`, pulled
  only by its index digest, on an `--internal` Docker network with no published port. `mosquitto_sub` and
  `mosquitto_pub` inside its container exchange one message on a neutral topic, on each of two exact topics
  beginning `$aws/` (with the placeholders `example_rule` and `example-thing`), and under two wildcard
  subscriptions.

`tests/test_sdv_connector_probe.py` runs both under the same opt-in.

**The connector's logic (WP2).** `connector.py` is the loop; each other module is one piece of it, and
`limits.py` holds every number. All of them are design values, none a measurement.

- **What it reads.** The effective path set: the frozen allowlist, narrowed by `config` through exact membership
  (`pathset.py`). It subscribes to exactly that set, each an exact leaf and never a branch, and keeps nothing
  else the source hands over. On its own tick (1 Hz, or 10 Hz when `config` asks) it takes the latest value of
  each path.
- **Telemetry.** One batch every 60 s at 1 Hz and every 10 s at 10 Hz to the Basic Ingest topic
  (`envelope.py`): `v`, a counter, the paths named once, positional rows (the sample time in Linux-host
  milliseconds, then one number per path; a boolean is 0 or 1; no value is null), and at most one AppState
  record per app. An empty batch is not sent. A change of the path set or of the rate closes and sends the
  open batch first, so no batch mixes two row shapes. It is a sampled view, not an event log.
- **The `vss` shadow.** A reported document when a value other than AppState's `seq` changed, no closer than
  60 s to the previous one, and once at stop (`shadowdoc.py`). Every document carries every allowlisted key,
  null where the path is narrowed out or has no value, so nothing stale is left in a shadow that merges. A
  process's first document waits for the source's first value, 2 s at most.
- **AppState.** All eight leaves as one record that validates, or nothing of it (`appstate.py`).
- **`config`.** Read once per connection with a get, then followed by its delta (`config.py`). Desired keys:
  `rate_hz` (1 or 10), `paths` (a list of exact leaves), `image_id` and `scenario`; any other key is ignored.
  Reported: the effective rate and path set and, when the updater's status record is valid, its `image_id`,
  `scenario` and `result` (below); once per connection and then only when one of them changes. A delta
  repeats every desired attribute that still differs from reported, so a report per delta would loop. A refused
  value changes nothing, causes no publish and is echoed nowhere. A message older than one already applied is
  not applied; when it is the get's answer (a delta overtook it), the get still counts as answered, and what
  that answer said of keys the delta did not name is not taken on this connection. "Once" means once it went
  out: a get or a report that the limiter refused or the uplink failed stays due. It goes when the limiter's
  window allows, or one retry spacing after the failure (below); the get is then answered and applied as at the
  start, and the report is made from the settings then in force.
- **A publish the uplink failed.** Not one the limiter refused: one the uplink raised on, which may have gone
  out or not. It is counted, logged by the error's class, and never sent again as it was; a telemetry batch is
  dropped. After a failed publish to a shadow topic (the get, a `vss` document, a `config` report) nothing is
  tried on a shadow topic for 60 s (`limits.SHADOW_RETRY_S`), the stop's last document alone excepted. The
  limiter counts a failed attempt, so a report tried again at every tick would use up the window's ten in a
  second at 10 Hz (in ten at 1 Hz) and leave none for the documents that follow; at one attempt a spacing an
  uplink that fails every publish is asked at most six times in any closed 300 s. The order in a step is the
  get, the document, the report, and the first that fails ends that step's shadow publishes: a get that alone
  fails every time keeps the document and the report from being tried at all (but the stop's document), a
  document that alone fails every time the report. A report that alone fails every time keeps nothing back;
  its attempts and the documents then share the window's ten.
- **The status record (SDV Phase 6).** The updater writes `status.json` (`image_id`, the config digest of the
  app that runs, or null; `scenario`, the last one accepted, or null; `result`: `applied`, `rolled-back` or
  `refused`, never a cause) into the status directory, which the stack mounts read-only. The connector reads it
  once a tick (`status.py`) and puts a valid one into `config` reported as the record has it; a report goes when
  it changed. Once the shadow shows a status (the process reported one, or the get's answer holds one in
  reported: an earlier process's, since a host's restart clears the record and the updater writes none for a
  request it already processed, or another host's), a status that is gone or refused is reported as three nulls,
  which the service deletes, in the next report and in every later one (each new connection's first among them)
  until a valid status is read, so the shadow keeps no stale image. A refused record is counted
  (`status_refused`, once per change of reason) and logged by its reason; no value of a record, valid or refused,
  reaches the log, and a refused one's reaches no publish; nothing of the get's answer is kept or logged. With no
  valid status ever and none in the shadow, the report is the rate and the path set as before Phase 6.
- **The spool.** A requested image ID or scenario name is written to `desired.json` in the spool directory by
  write-then-rename (`spool.py`), and nowhere else: not into a report, not into the log. The connector checks
  the record's form only; whether the image or the scenario may be used is the updater's check (Phase 6). The
  connector writes two files and no third: this one and the start stamp beside it. A write that failed is
  counted and is not remembered as written: the same request, which the service repeats in every delta, is
  written when it comes again, a second after the failed try at the earliest.
- **The limiter.** Every publish goes through it (`limiter.py`); the entry point builds the uplink inside it
  and the connector refuses to be built on anything else. What it refuses is dropped and counted, never queued.
  One process's worst case in 300 s is 60 telemetry publishes and 983,040 bytes, and 10 shadow publishes.
- **The start spacing.** The limiter's windows are new in every process, and every start and stop costs four
  shadow publishes however short the process lived. So the first thing a start does is read the time of the
  previous start from `started.json` in the spool directory (`startstamp.py`): within 120 s of it the start is
  refused, nothing is opened, the log says `start-refused` with how long is left, and the exit status is 4. A
  refused start leaves the stamp as it is. A stamp from the future (the clock was set back) or a file that is
  no stamp is refused too and written anew, so the refusals end 120 s later; a spool directory that cannot be
  written means no start at all. At most three starts fall into any closed 300 s. This holds for starts on one
  spool directory; starts on different ones (each replay of the stack has its own) are the stack's to refuse
  (WP3). Which of the two should carry the bound alone, if either, is the owner's call (`limits.py`).
- **Stop.** SIGTERM or SIGINT: one last read, the open batch, one last `vss` document, then everything closed.
  When the limiter refuses that batch for its one-second gap, the stop waits the gap out (once, a second and
  a millisecond at the most) and sends it; refused for the window's cap, the batch is dropped and counted.
- **The log.** JSON lines on stdout that never hold the endpoint, the thing's or the rule's name, a topic, a
  file path, or a value that was sent or refused; an error is logged by its class, never its text. The start
  line names the allowlist's version and digest and the first twelve digits of the sha256 of the catalogue the
  frozen module was generated from.
- **No error's text, on either stream.** An error's text can name the endpoint, the thing or the key's path,
  and a container's log is stdout and stderr together. What the connector cannot be put together from (a name,
  the frozen module, the schema, the uplink module or its settings, the databroker client) ends as status 2 and
  one sentence on stderr that was written beforehand (`connector.REFUSALS`). An `UplinkError` at connect or at
  a subscription is `connect-failed` (status 1); at the first get it is a failed publish like any other, and
  the run goes on. An error of any other class, before the loop, while the connection is opened or inside the
  loop, is the log's `error` line: its class and the file and line of each frame, status 3. That includes a
  class that is no `Exception` (a library's `SystemExit`, a `KeyboardInterrupt` raised with a text). One thing
  is passed on: a `KeyboardInterrupt` with no argument, which the interpreter raises for a SIGINT that comes
  before the connector's handlers are installed. It holds no text; Python prints its traceback.
- **Exit status.** 0 after a stop; 1 when the uplink could not be opened; 2 when the connector could not be
  put together; 3 after an error nobody expected; 4 when the start was refused (too soon after the previous
  one, or no start stamp could be kept).
- **Settings** come from the environment (`SDV_TWIN_THING`, `SDV_TWIN_RULE`, `SDV_TWIN_DATABROKER`,
  `SDV_TWIN_SPOOL`, `SDV_TWIN_STATUS` (by default `/run/sdv-local/status/v1`, where the stack mounts the status
  directory), `SDV_TWIN_SCHEMA`; the uplink's `SDV_TWIN_ENDPOINT`, `SDV_TWIN_CERT`, `SDV_TWIN_KEY`,
  `SDV_TWIN_CA`), never the argv.

`tests/test_sdv_connector.py` holds it on fakes (a fake source, a fake uplink, a fake shadow written from our
reading of the service's documentation, a clock the test moves): the design's A4 and A5, and A6 at the fake
uplink with a canary in every leaf of the `Monitor` branch, each with the seeded violations that must fail it.
A6 also holds each publish to the effective set in force when it was made, and runs once on a source that
hands over everything it holds, asked for or not. The limiter's windows are counted in whole milliseconds with
both ends included, from start instants where a float difference alone goes wrong. A resumed connection, a
get the limiter refused, and every way the entry point can fail before its loop (in this process and in a
process of its own, with errors that are no `Exception` among them) are held as well. So is a far end that
fails publishes for a while: a report, a document or a get it failed is tried once a spacing and no more, the
limiter refuses nothing afterwards, the next document and the stop's still go, and the get is asked again. So
is the start spacing: twelve processes a second apart on one spool
directory are one start and eleven refusals, a process begun every second for ten minutes is let in once
every 120 s, and the stamp's two ends (119.999 s refused, 120.000 s let in) are held in whole milliseconds.
So is the status record: every record of the form taken, each refusal by its reason, a status that alone
changed reported once, a vanished or refused one cleared once (also on a new connection after the far end failed
its clearing, and by the next process, on this host after a restart or on another, when its get's answer shows the
shadow holding one, an answer too old to apply included), and no value of a refused one anywhere.

**The uplink (WP3).** `uplink_aws.py` implements the seam on `awsiotsdk` 1.31.0 and `awscrt` 0.36.1. Every
number is `limits.py`'s and a design value.

- **Every setting is given; none is the SDK's default.** Port 8883 (the SDK's: 443 with ALPN), a clean session
  (the SDK's: a persistent one), a 60 s keep-alive (1200 s), a 5 s operation time-out (none: a publish could
  wait without end), a 3 s ping time-out, a 5 s TCP connect time-out, the SDK's own reconnect timer held at
  3600 s at both ends (5 s to 60 s; the uplink never uses a connection the SDK brings back, below), the
  device directory's CA file (the system's trust store), and the SDK's metrics off (on: the SDK's name, version
  and features ride in the CONNECT packet's user name). No user name, no password, no will, no proxy, no
  websocket. The SDK's own logging is never switched on. The builder used here takes no keyword for the TLS
  handshake wait, so aws-c-io's own default for the TLS negotiation applies. `SDK_TLS_NEGOTIATION_S` in
  `limits.py` writes that default out for the connection-budget arithmetic; it is handed to nothing.
- **What the SDK does with a QoS 1 publish that was not acknowledged**, read from its source and seen at the
  local broker. Written to a far end that stays silent: failed after the operation time-out and forgotten (it
  may still have arrived). In flight when the connection is lost: cancelled under a clean session; under the
  SDK's default it is sent again with the DUP flag. Handed to the SDK while its connection is down: queued,
  and sent once the SDK has reconnected by itself, whatever the session.
- **The choice: no offline queue and no re-send.** A publish is handed to the SDK only on a connection that is
  up; with none, `publish` fails at once. A lost connection is given up from the SDK's own callback (it is
  disconnected, which ends the SDK's reconnecting) and never used again, so whatever the SDK still holds for
  it never goes out. When the SDK says nothing about a request in time, its connection is given up the same
  way. The next connection is a new SDK connection that the uplink opens itself, on the connector's thread, at
  the first publish after the back-off (5 s, doubling to 60 s while attempts fail or connections are
  short-lived); its subscriptions are made again, then `on_resumed` is called. So one `publish` is at most
  one PUBLISH packet, and a publish the uplink reported as failed is not sent later (the next point says what
  that rests on). What the limiter
  does not count, because it is no publish: a new connection's CONNECT and its five SUBSCRIBE, at most once
  per back-off wait. The price: while the connection is down it stays down until the connector next has
  something to send, and that publish blocks the loop while the connection is opened.
- **The SDK's own reconnect timer is held, and nothing is handed to a connection that showed no life.** Giving a lost connection up from the SDK's
  callbacks alone is a question of who is first: an SDK that reconnects by itself writes what it queued when
  that reconnect is answered and calls its user only then. With the SDK's default timer (5 s, which the uplink
  handed it before) and the SDK's word of a loss reaching the uplink late, a publish reported as failed went
  out on a connection the uplink never opened (a review's run at the local broker, 2026-10-08; an opt-in
  broker test repeats it). So the SDK is handed `SDK_RECONNECT_HOLD_S`, 3600 s, for both ends of its timer:
  it tries nothing of its own until long after the uplink has given the connection up, by the callback or by
  its own wait for the first publish it handed over. The back-off above is the uplink's own and is unchanged.
  The hold alone left a window: an uplink never told of a loss, and a publish handed over in the hold's last
  seconds, would be written on the SDK's own reconnect. So the uplink hands the SDK nothing on a connection
  that has shown no life for `LINK_LIFE_MAX_S`, 900 s: no connect, publish or subscription of its own that the
  SDK answered. The SDK cannot have noticed a loss before the last answer and tries by itself the hold after
  it noticed; the latest hand-over and the wait for it end before half the hold has gone. So when the SDK does
  come back by itself, it has nothing to send, whenever and whether or not the uplink was told of the loss. A
  connection found without life is given up before the SDK is asked (`stale`); that publish fails and the next
  one after the back-off opens the next connection. An honest connector, with a publish acknowledged every
  batch interval, never comes near it.
  What this rests on, seen of the pinned SDK at the local broker and not read from its native source: its own
  first attempt comes no sooner after a loss than the timer it was given; a disconnect on a connection it is
  keeping for its own reconnect ends that reconnecting, and what it holds for it is never written; a request
  it failed is not written later. And one thing about clocks: the SDK's does not run at twice the uplink's
  rate. The shipped hold and life are not waited out by any test: the stand-in's clock runs them, and the
  opt-in broker tests give the driver's own process a hold and a life of seconds.
  The connector's stop line carries the uplink's counters (`uplink`): `resumed_by_sdk` counts an SDK that came
  back by itself (one CONNECT and one DISCONNECT under the thing's client id); it is a count for the record,
  not what holds the rule.
- **A connect the SDK has not answered when the uplink stops waiting** (10 s) cannot be given up like that: the
  SDK refuses a disconnect while it is still connecting, and goes on. TCP connection, TLS handshake, the
  CONNECT reply and name resolution may outlast the uplink's wait, so the SDK can answer with a connection
  after the uplink reported the connect as failed. The uplink keeps the SDK's answer and watches it: a connection that comes late is disconnected the
  moment the SDK reports it, never used, and counted (`late`); and while a connect is unanswered no other is
  asked for, because a second CONNECT under one client id makes the far end close whichever connection came
  first. An attempt stays at most one CONNECT. The price: an SDK that never answered a connect would leave
  the uplink without a connection for good. The three stages known here each have a time-out (the two the
  uplink sets and the SDK's own for the handshake); that the SDK always answers is not shown.
- **Errors.** Every call raises `UplinkError` and nothing else, without the SDK's text. The SDK's callbacks
  run on its threads and are guarded.
- **Settings.** `SDV_TWIN_ENDPOINT` (a host name or an IPv4 address: no scheme, no port, no path) and the three
  files, by default `device.crt`, `device.key` and `ca.pem` under `/run/sdv-local/device`, where the stack
  mounts the device directory. A missing or malformed setting or file is exit status 2.

**The image (WP3).** Built in WSL from the repo root, for both architectures, and pinned:

    python3 sdv/connector/build_image.py build --arch all --smoke --write-pins --out FILE
    python3 sdv/connector/build_image.py build --burst [--smoke] [--out FILE]
    python3 sdv/connector/build_image.py scan --out FILE

- **The gate before a build.** The frozen allowlist must import, the three sha256 it records must be those of
  the catalogue's id file, the source list and the schema this build reads, and it must be byte for byte what
  `gen_allowlist.py --check` generates from them (run in the vss-tools venv). Nothing at run time repeats
  this, so a stale or hand-edited module is refused here and no image is built from it.
- **What is staged**, in a context outside the repo: the Dockerfile, the architecture's lock, and exactly the
  fifteen modules the entry point imports (`status.py` since Phase 6), `appstate.schema.json` and
  `twin_allowlist.py`, side by side. No
  probe, no generator, no source list, no burst tool, no key, no certificate, no endpoint.
- **What the build checks:** `pip check` after the hash-checked install (`--no-deps` would hide a wrong pair),
  and that no module of `/app` shadows an installed one (the modules' names are plain).
- **Labels and pins.** The image carries the allowlist's version and digest and the catalogue's sha256;
  `sdv/stack/images.json`'s top-level `connector` entry holds both architectures' `{id, config_digest, tag,
  lock}` in the bridge entry's shape and those labels. Built locally with buildx (arm64 under the host's
  qemu registration, no privileged container), `--provenance=false --sbom=false`, never pushed. The entry is in
  no bundle and no deploy set.
- **arm64.** Built and scanned with `sdv/arm64`'s scanner and its gate for a local image; never started.
  Information for Phase 5.
- **The burst tool** of the breaker's test is another program in another image (prep gap y):
  `sdv/cloud/burst`, built by `build_image.py build --burst` as `sdv-local/twin-burst:test-only`, amd64 only,
  from this image's base and x86_64 lock in a context of its own. Nothing of it is staged here and no module
  here imports it; its image is in no pin and no deploy set. `--burst` refuses `--write-pins`,
  `--arch arm64|all`, `--gen` and `--frozen`. Tests hold the staged list, the import graph and the pins.

**In the stack (WP3).** `sdv/stack/stack.py replay|up --feed vcan --connector`, with `SDV_CONNECTOR_IMAGE` (the
image ID) and `SDV_DEVICE_DIR` (a directory outside the repo holding `device.key`, `device.crt`, `ca.pem` and
`connector.env` with `SDV_TWIN_ENDPOINT`, `SDV_TWIN_THING` and `SDV_TWIN_RULE`). The container gets a read-only
root, the host user (never root), every capability dropped, restart policy `no`, the host's network namespace
and three mounts and no other: the spool (read-write), the status (read-only) and the device directory
(read-only). The spool and the status are the replay's own `spool/` and `status/`, or, with `SDV_SPOOL_DIR`
and `SDV_STATUS_DIR` (both or neither; existing directories outside the repo, never made by the stack; taken by
`up --app external --connector` only), the host's, at the same container paths. The endpoint and the names come in by `--env-file`, never on the argv,
and the stack writes none of them into a run directory. Refused: any feed but vcan, the guest monitor mode,
`--images loaded`, and a start within 120 s of the previous one this host's stack made (the stack keeps
`startstamp.py`'s stamp in its state directory, `SDV_STATE`, which outlives the run directories). It is
stopped with SIGTERM before the databroker, so the last flush runs. `sdv/stack/README.md` has the rest.

**The opt-in broker tests (WP3).** `SDV_CONNECTOR_BROKER=1`, in `tests/test_sdv_connector_broker.py`: the pinned
Mosquitto with mutual TLS on an `--internal` Docker network with no published port, a CA made by the test
with `openssl` and gone with it, the connector image by its pinned ID. They leave nothing in the Docker
store: the broker's image declares two volumes, so its containers are removed with `docker rm -v`, and the
teardown holds that none of those volumes is left (as `probes/probe.py` removes its own broker).

- **The image:** every file of its `/app` is the file the build would stage today.
- **The uplink probe** (`probes/uplink_driver.py` mounted into the image): the CONNECT the broker logs is MQTT
  3.1.1, clean, 60 s, with no user name; the handshake fails with a certificate of another CA and with a
  broker certificate of another CA; a publish is acknowledged and the observer reads the exact bytes on each
  exact topic; with the broker paused a publish fails after the time-out and is not sent again; with the
  broker killed and started again, nothing that was reported as failed arrives, no PUBLISH carries DUP, the
  SDK's own connection does not come back (its reconnect timer is 8 s in the driver's own process, so that its
  first two attempts fall inside the test's wait: at the shipped hour the test could not tell the uplink's
  disconnect from the hold), and the next publish opens a new clean connection with its
  subscriptions. With the broker paused across the uplink's wait (shortened to 3 s in the driver's own
  process) and going on inside the SDK's handshake wait, the SDK completes the connect after the uplink
  reported it as failed: no second connect is asked for meanwhile, the late connection is disconnected at
  once, and the broker closes no connection when the next one comes. With the uplink's wait made long, the
  SDK is seen to give a silent handshake up by itself.
  The SDK's own reconnect, three ways (the driver can hand the SDK's word of a loss on late or not within the
  test, from a thread of its own, and can give its own process a hold and a life of seconds). Told 25 s late,
  with a publish handed to the lost connection and the broker paused across the moment the SDK's default
  timer would have tried: no CONNECT the uplink did not open, and the publish never arrives. Never told, with
  a hold of 30 s and a life of 8 s, and a publish made 4 s before the SDK's own attempt with the broker up:
  refused before the SDK is asked, the connection given up, no connection of the SDK's own, and the publish
  never arrives (on the image that had the hold alone, the same test saw it arrive). Left alone, never told
  and nothing handed over, the test checks the configured reconnect timer, the absence of a queued
  publish, and the uplink's disconnect when the SDK reconnects. No measured interval is published here.
  What the uplink's module says of the SDK's three cases for a QoS 1 publish that was not acknowledged, each
  with the uplink never told of the loss: a publish the SDK queued on the lost connection (handed over within
  the life) and the uplink's own wait gave up is not written when the SDK's timer, 30 s, runs out with the
  broker up (the SDK makes no connection of its own; with that give-up taken out it does, and writes the
  publish); a publish in flight at the loss and a publish the SDK timed out are not written when the SDK does
  come back by itself, with a timer of 12 s: it makes its own CONNECT, the uplink disconnects it again, and no
  PUBLISH is on it.
- **The full local slice:** `stack.py replay --feed vcan --connector` beside that broker (the connector reaches
  it at its address on the internal network). Every gate of the stack's own holds; the started container has
  exactly the three mounts and the host's network; every telemetry cell of a CAN-fed path is a value the
  databroker served; the last `vss` document holds the last value of each; a delta reaches the spool; the stop
  flushes one batch and one document; the run directory names nothing of the device.
- **The canary run** (the design's A6 on the pinned databroker): no bridge, and a writer plants a value in
  every leaf of the `Monitor` branch, enumerated from the catalogue. The databroker holds them while the
  connector runs; the far end's raw bytes hold none of them and no path of that branch.
- **The slice with the claim bridge** (only with `SDV_BRIDGE_IMAGE`, the bridge image's ID, beside the
  switch): `stack.py replay --feed vcan --connector --bridge broker`, so the native monitor runs and the
  bridge itself writes its leaves of the `Monitor` branch into the databroker the connector reads. Every gate
  holds, the bridge's and the connector's among them; the far end received allowlisted keys only; and a
  sampler that only reads saw each of the bridge's leaves hold a value while the connector ran. The test is
  skipped unless `SDV_BRIDGE_IMAGE` is set, for instance to the ID of `sdv-local/vss-claim-bridge:0.1.0` in the
  store. The amd64 bridge has no pin (`images.json` holds only the arm64 one), so that ID is held to this
  generation by the image's labels alone.
- **A re-run needs more than the switches.** The stack refuses a connector start within 120 s of the previous
  one in the same `SDV_STATE`: the tests give each run a state directory of its own, and a re-run by hand in
  one directory has to wait. The opt-in tests keep nothing: the stack's log, the connector's log and the
  observer's capture lie in pytest's temporary directory and nothing copies them out, so a record of such a
  run needs a wrapper that does.

**The tests' gate.** `tests/twin_gate.py` is read by every twin test file. A twin test that needs the
generated catalogue or the vss venv asks it: without `SDV_REQUIRE_GEN=1` a missing input skips the test, with
it the test fails. The Phase 4 CI recipe sets the switch and ends with the gate's skip check, which reads
pytest's junit report and fails the run when a test of `tests/test_sdv_connector.py` or
`tests/test_twin_allowlist.py`, or the `Monitor` guard of `tests/test_sdv_vss.py`, was skipped or did not run.
So no opt-in test may live in those two files.

## What it is not

- **Not a cloud-service verification record.** Unit tests use fakes; the opt-in broker tests use a local
  broker. Files here hold placeholders (`example-thing`, `example_rule`, `broker.test`, documentation
  addresses). Live configuration, credentials and run records stay outside every work tree.
- **Not shown against the service.** The tests' shadow is our reading of its documentation: what the real one
  does with a get, an update, a delta or a rejection is first seen in the account. The local broker carries
  bytes on topics: at it nobody answers a `config` get, so the slice's connector runs on its defaults.
- **The uplink's choice is shown at one broker and one SDK pair.** What the service does with a clean session,
  with a client that reconnects, or with a publish its policy refuses (the local broker acknowledges and drops
  one its ACL denies, and keeps the connection) is first seen in the account. The default-port path (443 with
  ALPN) is never taken. The late connect is shown with the uplink's wait shortened in a test's process, not
  with the shipped connect wait, and for
  one way of being late: a handshake that is answered late. That the SDK always answers a connect is taken
  from the time-outs of the three stages known here, not shown.
- **Not the account side.** Creating, checking and removing cloud resources is `sdv/cloud`.
- **Not `scripts/twin/`.** That directory is the old same-image comparison tooling (`sync.sh`,
  `time-kvm-boot.py`), kept under its name; nothing of this twin lives there. The `startup-qemu-virt`
  used for KVM boot is ours, not a QNX-supported configuration; no timing claim attaches to that boot.
- **Never a carrier of the QNX monitor's output** (owner decision S11). The allowlist excludes the whole
  `Monitor` branch, and AppState passes only as a whitelisted record. No file here spells a path of that
  branch: the prefix comes from `sdv/stack/attribution.py` and the leaves from the generated catalogue.
- **The exclusion on the pinned databroker is an opt-in run, not CI.** CI's egress test runs on a fake source;
  the canary run against the pinned databroker image needs Docker and the local broker. There only the sixteen
  counters can hold a distinctive value; the six narrow leaves hold a valid one. Past the frozen module the
  connector has no second list: a module with a leaf forced in would be sent, which is why it is generated,
  compared with a fresh generation at the image build, and never mounted.
- **The limiter bounds one process, the start stamp one spool directory, the stack's stamp one host.** A second
  process has a limiter of its own; on the same spool directory `startstamp.py` refuses it within 120 s of the
  previous start, and the stack refuses a connector start within 120 s of the previous one it made, whatever the
  run directory. A connector started by hand, by another host or with another state directory is seen by
  neither. Two starts at the same instant may both pass, and a wall clock stepped forward lets one start
  through early. Three starts can fall into one closed 300 s, each with its own limiter: the worst case across
  starts is WP5's to derive, and the caps sit under thresholds that are WP5's, on metrics first read in the
  account. Whether the device's stamp, the stack's, or both should carry the spacing is the owner's call.
- **A publish is counted once, and a connection is not counted at all.** The limiter sees publishes. A new
  connection's CONNECT and SUBSCRIBE packets are bounded by the uplink's back-off, not by a window.
- **Nothing at run time checks the frozen module against a catalogue.** The module's own import check holds
  its parts to each other, not to the catalogue: a stale or carefully hand-edited module runs. The gate is
  `gen_allowlist.py --check` at the image build, the stack refuses an image whose labels name another
  generation, and the start line names the generation a run was on.
- **Not a judge of what runs.** The status record is the updater's own report: the connector holds its form and
  reports it, and has no way to see which image runs. What an earlier connector process, or another host's, left
  in the shadow is learnt from the get's answer and from nothing else: on a connection whose get is never
  answered, a process clears only a status it reported itself, so a shadow can keep a stale image then.
- **Not a defence against the Linux side.** The connector, the databroker and the app all run there; the
  allowlist and its tests stop honest mistakes and code-path bugs, not an attacker. An app can still hide a
  bit in a permitted AppState field: the schema cannot see provenance.
- **Not shown to run on the Orin or on an A72.** The arm64 image is built under emulation, pinned and
  scanned; it has never been started. `awscrt`'s run-time dispatch of its ARMv8.2 crypto code is untraced.
- **The root CA's pin is read by nothing.** `ca.json` records where the root CA file came from and its sha256;
  neither the connector nor the stack compares a device directory's `ca.pem` with it, so `ca.pem` is whatever
  its owner puts there, and in the tests it is the test's own CA. The pin rests on one download: its
  certificate's fingerprint was compared with no second published source.
- **The local broker is not the cloud service.** Mosquitto carries bytes on topics. It has no shadow service,
  no rules, no policy language of that service, no quotas and no metrics, and a subscriber can read a topic
  that the real service lets nobody subscribe to.
- **Not a measurement of anything.** The probes' waits bound the probes; no timing figure is taken.
- **Not safety, not real time, not certified.** The twin carries a simulated vehicle's signals and one Linux
  app's state.
