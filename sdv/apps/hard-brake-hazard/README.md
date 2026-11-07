# sdv/apps/hard-brake-hazard: the slice's first app

A containerised app on the local databroker: it switches the hazard lights on when the vehicle brakes
hard and off again when the braking eases, and publishes its heartbeat.

## What is here

| file | what it is |
|---|---|
| `hazard.py` | The pure core: the deceleration along the direction of travel, the decision with its hysteresis, the lifecycle state, the AppState record, the Monitor display. Standard library only; every design value with its reason. |
| `app.py` | The container's entry point: kuksa-client I/O around the core (two kuksa.val.v2 subscriptions, the heartbeat publication, the actuation) and the JSON-lines log. |
| `appstate.schema.json` | The AppState record's schema, version 1, the design's file unchanged. |
| `Dockerfile`, `requirements.lock` | The image: the pinned Python base by digest, kuksa-client and its resolution by exact version and hash. |
| `requirements.aarch64.lock` | The lock's arm64 twin (SDV Phase 3 WP0), staged as the context's `requirements.lock` by `sdv/stack/stack.py`'s `build_local_arm64`; the amd64 build still uses this directory as its context. |

## Inputs and outputs

- **Reads** the signed longitudinal velocity (`Vehicle.DualVm.Motion.LongitudinalVelocity`) and the
  longitudinal acceleration (`Vehicle.Acceleration.Longitudinal`); the deceleration is minus the
  acceleration times the sign of the velocity, so braking in reverse counts and a standing vehicle
  never brakes. It decides only from two present, fresh, finite inputs.
- **Actuates** `Vehicle.Body.Lights.Hazard.IsSignaling` through the kuksa.val.v1 target value: the
  pinned mock provider serves actuators through v1 only, and the databroker answers a v2 Actuate for
  an actuator with no v2 provider as unavailable. So the Actuate outcome it reports is ok or error,
  never unavailable.
- **Publishes** the eight AppState leaves under `Vehicle.DualVm.AppState.HardBrakeHazard`, and
  nothing else.
- **Displays** the last verdict of the Monitor branch in its own log only. No decision, no AppState
  field and no lifecycle state reads the Monitor branch, its value or whether it is fresh; the
  tests drive the core with different Monitor histories and require identical effects. The display
  also has its own lock in the shell, and a heartbeat is judged at the time it fell due, so a burst of
  Monitor updates cannot hold up a heartbeat or make it read its inputs as stale.
- **Logs** every input update, every decision and actuation, every heartbeat and every display line
  as JSON lines with the host clock and the monotonic clock.

## Configuration

`APP_IMAGE_ID` (required: the image ID the starter ran, `sha256:` and hex; the app refuses to start
without it), `KUKSA_ADDRESS` (the databroker, loopback by default), `HBH_LOG` (the log file). Nothing
else is read. `sdv/stack/stack.py` builds the image and starts it by image ID.

## Tests

`tests/test_sdv_stack.py`: the decision at its edges in both directions of travel, at standstill and
on stale or non-finite inputs; the lifecycle; the leaf map against the schema and the generated
catalogue; the records against the schema; the write set; the Monitor independence, with seeded
variants that leak a verdict or its freshness and must fail it; and the shell (`app.py`, with
stand-ins for kuksa-client) under a burst of Monitor updates while an actuation holds the shared
lock.

## What this does not demonstrate

That the lights would switch in any real vehicle, or on time: the thresholds are design values for
the sigsim trip, and nothing here measures a latency. That the Monitor branch cannot leak through
the app's permitted fields on purpose: the schema and the tests stop honest mistakes, not a
malicious app. Anything about the QNX guest.
