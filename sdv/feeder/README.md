# sdv/feeder: the live CARLA feed and F2 (Phase 7)

The live path of the CARLA feeder (SDV plan Phase 7 WP3c): WP1's take
(`sdv/carla/carla_capture.py`) driven from WSL against the CARLA server on Windows, each simulation step
sent onto `vcan0` as it becomes current, while `sdv/stack/stack.py live` runs the stack on that feed with
the claim bridge and the native vss monitor; then F2 (the kind 4 specification's test 16.4: freeze the
simulator, expect reason 22 within a bound) judged from the run's records. The hosts never run this path:
they replay recordings (`sdv/carla/encode.py`'s).

## What is here

| file | what it is |
|---|---|
| `live.py` | The live feeder: the refusals, the take with the per-step hook, the sender (the 20 ms and 50 ms timers, the repeat cap, no catch-up) on python-can's SocketCAN, the freeze, `live.json`. |
| `f2check.py` | F2's verdict over a live run's records and the take's `live.json`: writes `f2.json`. |
| `requirements-live.lock` | The feeder's venv: the carla 0.9.16 cp312 manylinux wheel by its PyPI sha256, and cantools and python-can with their resolution exactly as `sdv/sim/requirements.lock` pins them. Nothing else. |

## The venv

In WSL Ubuntu-24.04 (CPython 3.12, x86_64), from the repo root:

    python3 -m venv ~/sdv-carla-venv
    ~/sdv-carla-venv/bin/pip install --require-hashes --no-deps -r sdv/feeder/requirements-live.lock

`--require-hashes --no-deps` makes the lock the whole resolution. No container: the manifest classes'
platform class `carla-feeder` is not built in this phase, since the feeder runs on the PC only.

## How

Three steps, in this order, each in its own WSL shell, from the repo root:

    SDV_BRIDGE_IMAGE=<image ID> ~/sdv-sim-venv/bin/python sdv/stack/stack.py live [--name N] --bridge broker|can --feeder-out DIR [--native]
    ~/sdv-carla-venv/bin/python sdv/feeder/live.py run --name N --seed S --host GATEWAY --out DIR [--freeze-at-s T]
    ~/sdv-sim-venv/bin/python sdv/feeder/f2check.py RUN_DIR

1. `stack.py live` brings the stack up on the vcan feed (which makes `vcan0`), with the bridge in the
   given mode and the native monitor `7160 svc 500`, and prints when to start the feeder. It plays no
   recording. Its run header says run type `carla`, feed `live`, profile source `live-default` (profile
   3), and `source_rtf` null until record close, when it is filled from the take's `capture.json`
   (C12b). It waits for that `capture.json` to read completed (or the take to end, or a timeout), then
   closes the run; the run's `live-1/` holds the bridge's per-frame verdicts and every frame it saw on
   `vcan0` with its receive time (`sdv/stack/stack.py`'s docstring, LIVE). `--name N` names the run's
   directory (`<date>-N` under the stack's runs directory; the default is `live`): a second run on one day,
   in the other bridge mode say, needs another name, since an existing run directory is refused.
2. `live.py run` drives WP1's take (the route drive, `drive.py`'s values) against the server at
   `GATEWAY`, port 2000, and writes it to `DIR` (whose last component is the name `N`), with
   `live.json` beside the take's four files. With `--freeze-at-s T` it stops ticking the server for
   `FREEZE_S` once the take's simulated time passes `T`, then ends the take.
3. `f2check.py` reads the run's records and `DIR/live.json` and writes `RUN_DIR/f2.json`.

The firewall comes first: every CARLA server start is preceded by `fwcheck --for wsl` on Windows
(`sdv/carla/README.md`), and `live.py` runs the same predicate itself before it connects.

## The refusals

`live.py run` refuses before connecting, and then writes nothing and sends nothing (exit 2): a name that
is not `<yyyymmdd>-carla-<seed>[suffix]`; a `DIR` that is not named by it, that exists or that lies inside
a git work tree; a `--freeze-at-s` that is not a number above 0; no generated contract, or one without
profile 3 compiled; `fwcheck --for wsl` not passing (PowerShell's read through WSL's interop, the same
predicate, P4 included); a `--host` that is not the gateway of the default route (read from
`/proc/net/route` at run time; the address is never written to any file or printed); no `vcan0`, or one
that is not a CAN interface or not up; slice.dbc not loadable with cantools; the SocketCAN bus not
opening; no carla client. After connecting, the take refuses what WP1's take refuses (another
`fixed_delta_seconds`, asynchronous mode, other versions), and nothing is sent.

`stack.py live` refuses before anything is written: any role but the PC's, a `--feeder-out` that exists
or lies inside the repo, a bridge mode other than broker or can, the twin-control marker, a generation
without the carla vehicle layer or with profile 3 not compiled.

There is no Traffic Manager anywhere on this path and no listener: the feeder is a client of the server
and a sender on `vcan0`, so the stack's listener gate is unchanged and allows nothing for it.

The server's address is never written: LibCarla's errors name the endpoint the client was connected to,
and the take records an error's text, so `live.py` writes the take's `capture.json` and its own
`live.json` with every occurrence of the address replaced by `<gateway>`. LibCarla's own messages on
stderr are not masked: do not keep the feeder's stderr in a file unredacted.

## The sender

Both messages on wall-clock timers from the moment step 0 became current (SliceDynamics every 20 ms,
SliceGear every 50 ms), each frame from the step current at its instant (the latest step that became
current at or before it, as `sendpolicy.schedule` has it), and only while that step has been current for
no longer than the repeat cap there (`FEEDER_REPEAT_CAP_MS` of the generated contract). The take
announces a step only after it became current and its row was written, so at an instant one pacing
interval or more after the latest step announced (a newer step may already be current there) the sender
waits for the announcement, up to `LATE_HOOK_GUARD_MS` (5 ms) after the instant: a frame goes out at its
instant or at most that much later. An announcement later than that, for a step current at an instant
already sent, is counted as stale in `live.json`. A sender that wakes late sends each message's latest
instant and counts the ones it passed, never catching up. The frames are encoded as `encode.py` encodes a
recording's. A step with a value outside slice.dbc's range sends no frame and is logged in `live.json`,
never clamped.

## The files

- `live.json`: the policy; every send as `[message, instant, step, t_ns, t_real_ns]` (the take's clock
  from step 0, and CLOCK_REALTIME, the clock the bridge ages on); counts, capped and missed instants per
  message; the refused steps; the send errors; the guard, and the stale instants per message with the
  first of them; the gaps; the freeze (its point, `FREEZE_S`, the frozen step, its start and end, the last
  frame sent); the sha256 of slice.dbc, of the contract and of `live.py`; fwcheck's line; the take's exit
  code.
- `f2.json`: per run, so per mode: the last frame on `vcan0` and its receive time, the first reply with
  reason 22 after it and its delay against AGE_MAX plus one tick (`TICK_MS`), that reply's own age and
  the age-source time it implies for the oldest value it packed (information only), whether every reply
  before the freeze was ACCEPT, the MISS lines in the monitor's console before the bridge's last session
  ended (its last `client done:`; the MISS the monitor prints after the bridge is stopped, as it outlives
  it, is counted apart), whether the bridge answered until after the freeze's end, the take's exit code
  and the send errors, and the run's own gates from `result.json` by name; `ok` only when all of that
  holds with a freeze of `FREEZE_S`. A `result.json` without gates is refused (exit 2).

## Design values

`FREEZE_S` (2.0 s): at least AGE_MAX plus one tick plus the repeat cap, so the first 22 falls inside
the freeze whatever the tick's phase, and four of the monitor's 500 ms deadlines, so a bridge that stopped
sending would show a MISS. `TICK_MS` (100): the bridge's tick, the "one tick" of the bound.
`LATE_HOOK_GUARD_MS` (5): a design allowance for the take's announcement after a step becomes
current. It stays a quarter of the shortest message period (20 ms); it is no measured scheduling bound.

## What it does not demonstrate

It does not demonstrate CAN timing (vcan has no arbitration, error frames or bus timing), any timing (the
sender keeps a wall-clock schedule on a general-purpose kernel; F2 is functional: one 22 within a bound,
no MISS), or vehicle dynamics (CARLA's physics and the scripted drive are not a vehicle). In broker mode
the age source is the databroker's datapoint timestamp, which no record holds for the last frame:
`f2check.py` uses the frame's receive time on `vcan0`, a lower bound of it, so its delay is an upper
bound; the datapoint timestamp it records is the oldest packed value's at the first 22, never later than
the last frame's. Nothing here runs off the PC.
