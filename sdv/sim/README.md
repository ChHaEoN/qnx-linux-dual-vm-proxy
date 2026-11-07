# sdv/sim: the slice's signal simulator

`sigsim.py` is the slice's seeded signal source: a kinematic single-track (bicycle) model of the
sigsim design car drives one scripted trip -- start, cruise, turn, brake, stop, reverse -- and its
five kind 4 signals are encoded with cantools through `sdv/vss/slice.dbc`, at that file's message
periods, into a candump log. The same seed gives the same log, byte for byte, on the platform
`requirements.lock` pins: the model's `tan` is libm's, so another interpreter or libm is not shown to
give the same bytes (and `verify`, which compares a log with a regeneration, would then fail).

## What is here

| file | what it is |
|---|---|
| `sigsim.py` | The model, the trip script, the envelope clamp and check, the candump writer, and the read-back verification (python-can's reader, cantools' decoder, the kind 4 reference rules). |
| `carla_iso.py` | The conversion of one CARLA step to the five kind 4 values in the ISO 8855 signs `slice.dbc` carries (Phase 7 spec 2.7), the one place it is written; the feeder in `sdv/carla` uses it. Each CARLA convention is stated as Phase 7's WP0 read it (READ or LIB, with its source); the delta source (the front wheels' physics angle) and the sign of the wheel steer angle are the values WP0's probes settled, one constant each (PROBED), and the wheel source would be refused again were its sign put back as pending. |
| `requirements.lock` | cantools and python-can and everything pip resolves for them, pinned exactly, with hashes. |
| `requirements.aarch64.lock` | Its arm64 twin (SDV Phase 3 WP0): the same names and versions, the none-any wheels' hashes unchanged, bitstruct and wrapt as their manylinux aarch64 wheels; for the stack's host side on an aarch64 host. |
| `python-aarch64.json` | The host Python for that lock on an aarch64 instance (SDV Phase 3 WP1): a python-build-standalone CPython 3.12 `install_only` build for `aarch64-unknown-linux-gnu`, by release, asset name, sha256 and size, checked against the release's published `SHA256SUMS` (its URL and sha256 are pinned too), and the name it travels under in the upload bundle (`sdv/stack/bundle.py`). |

## Where its numbers come from

Nothing here copies a generated value. The wheelbase is the generated profile table's (the live
default profile for the sigsim run type); the message periods and signal names are `slice.dbc`'s,
through the generated contract and cross-checked against cantools; the envelope rows the trip must
stay inside are the generated contract's. The trip script's own values are sigsim's design values,
each with its reason in `sigsim.py`. The contract is `sdv-out/gen/vss_contract.py`
(`sdv/vss/README.md` says how to generate it); `SDV_GEN` names another generation directory.

## How

In WSL Ubuntu-24.04, once, a venv of its own (the vss-tools venv is described exactly by its own
lock and gets nothing else):

    python3 -m venv ~/sdv-sim-venv
    ~/sdv-sim-venv/bin/pip install --require-hashes --no-deps -r sdv/sim/requirements.lock

Then, from the repo root:

    ~/sdv-sim-venv/bin/python sdv/sim/sigsim.py summary --seed N     # the trip's timeline; standard library only
    ~/sdv-sim-venv/bin/python sdv/sim/sigsim.py dbc [--dbc PATH]     # slice.dbc (or PATH) through cantools
    ~/sdv-sim-venv/bin/python sdv/sim/sigsim.py record --seed N [--suffix S]   # ~/sdv-recordings/<date>-sigsim-<seed>[S]/
    ~/sdv-sim-venv/bin/python sdv/sim/sigsim.py verify LOG --seed N
    ~/sdv-sim-venv/bin/python sdv/sim/sigsim.py live --seed N --check

`record` writes, outside the repo, a directory holding the log (`sigsim.log`), its sha256 in
`sha256sum` form, the verification summary, and -- only when the verification passed -- one manifest
line shaped like a host-manifest scenario entry (the signal-ownership table is Phase 1 step 6's, the
provider run, to add). A recording that fails verification is renamed `<name>.failed` and has no
manifest line, and so is one that stops for any other reason once its directory exists (a failed
write of the log or its sha256, `verify` raising, an interrupt, a failed write of the manifest line
or the summary), with the error re-raised; `summary.json` is written for either verdict, but not when
`verify` itself raises. `record` refuses a directory that already exists, and leaves it alone: a
recording is never rewritten. A re-record of a seed on the same day goes to a directory of its own
with `--suffix S` (`[a-z][a-z0-9]{0,7}`: a letter first, so a suffix never extends the seed into
another seed's name), which makes the name `<date>-sigsim-<seed>S`, for example `20260930-sigsim-1b`.
The whole name must stay `[a-z0-9][a-z0-9-]{0,47}`, which only a very long seed can break, and
`--date` must be a calendar date in ASCII digits. A recording under `~/sdv-recordings` keeps that `~`
form of the path in the manifest line, however its directory was named (`--root ~/sdv-recordings`
expanded by the shell included); one anywhere else keeps the path it was written to.
`--out` and `--root` are refused when they point inside the repository, except under `sdv-out/`,
which git ignores: a recording belongs outside the tree.

`verify` passes only when every term it reports under `ok_terms` holds: the log is this module's
text for the seed, per-message counts and periods are right, cantools decodes it to within half an
LSB of the model, every decoded gear equals the model's, every decoded sample is accepted by the
reference rules, and the trip's clamp counters are all zero.

`live --check` receives on a second socket, and keeps reading until `CHECK_TAIL_S` (a constant of
`sigsim.py`) after the last frame sent. It exits 1 if a frame sent was not received unchanged (id, frame type
and data, in order), if no frame was sent (for example `--seconds` leaves none), or if any other
frame appears on the channel up to that time: the channel must carry no other traffic during
`--check`, and a frame of somebody else's that comes later than the tail is not seen.

`live` sends the trip onto a SocketCAN channel at the log's pace. vcan0 does not survive a WSL
shutdown; create it with

    sudo -n modprobe vcan
    sudo -n ip link add dev vcan0 type vcan
    sudo -n ip link set up vcan0

## The log

Written in candump `-l`'s documented form, one frame per line, `(seconds.microseconds) vcan0 ID#DATA`.
The timestamps are simulation time counted from zero, not wall time; at equal timestamps the dynamics
message, the lower CAN id, comes first. python-can's writer produces the `-L` form instead (an
unpadded timestamp and a direction flag), so this module writes the text itself and reads it back
with python-can's reader and cantools to check it.

**UNVERIFIED:** that can-utils' `canplayer -I sigsim.log` replays this log onto vcan0. The unit checks
do not establish this integration.
Closed by running `canplayer -I sigsim.log` onto vcan0 and comparing what arrives with `candump -l`,
frame by frame (plan: Phase 5 step 4, or whenever can-utils is available).

**UNVERIFIED:** that the CAN provider's `--dumpfile` accepts a log whose timestamps count from zero.
Closed by running the provider's `--dumpfile` on this log (plan: Phase 1 step 6, and the Phase 1
exit test).

The reader checks alone do not establish either integration.

## The envelope

Every integration step is checked against every sigsim envelope row after it is integrated,
independently of the clamp that limits the script's commands before integration. The clamp counts
each row it acts on; the scripted trip is designed so that it never acts, `summary` and `record`
report the counts, and `verify` and `record` fail if any counter (`stalled` included) is not zero.

## Tests

`tests/test_sdv_sim.py`. The model, the envelope, determinism, the whole trip through the kind 4
codec and reference rules, the exit codes and pacing of `live --check` and the files `record`
writes and renames (against a stand-in for python-can's module and stubs for the cantools-dependent
steps), `verify`'s wiring of each term of `ok` (against a stand-in for cantools' database), and the
CARLA sign tests run with the standard library. The cantools and python-can tests run `sigsim.py`
in the venv above and skip cleanly without it: they include logs that differ from the model's text,
each failing with the named terms of `ok` it breaks, and a DBC that disagrees with the contract.

## What this does not demonstrate

The kinematic model is not vehicle dynamics: no tyres, no slip, no understeer. The DBC describes no
real vehicle. vcan has no arbitration, no error frames, no bus timing and no IRQ, and a live send
makes no timing claim. That every sample passes the reference rules shows the signals agree with
the rules' own kinematic model, not that the rules are right.

## CARLA 0.10.0 (Phase 8 WP9b)

`carla010_iso.py` is the one place the conversion is written for CARLA 0.10.0 (UE 5.5), the simulator of
Phase 8's closed loop; `carla_iso.py` stays Phase 7's, for 0.9.16, and the new module imports nothing of
it (standard library only). `sdv/carla/encode010.py` runs every step of a 0.10.0 take through it
(`sdv/carla/README.md`, its 0.10.0 section). Each convention is named with the Phase 8 WP9a fact it
rests on (READ, LIB or INFERRED): left-handed axes with steer and yaw
positive right (E17, E18), the angular velocity in degrees/s for the actor and the snapshot alike
(E19, E20), the velocity world-frame (E21), commanded steer as the delta source, and the steering
curve read as the client class's default points before the vehicle's own (E11).

- v and a_x are the world vectors' components along the forward vector; psi_dot is -w[2], unscaled.
- delta is -(C x s x |s|), s the applied steer: never s x max_steer_angle and never a wheel angle (E7,
  E10). C is PROBED (E9: from WP9a's wheelbase reading and its curvature over steer x |steer| on the
  flattened curve), one constant in the module and once more in the test's `PROBED`. The law itself is
  INFERRED (tan(delta) = L x kappa); its error against the measured arcs lands in profile 5's
  understeer row when WP3c freezes the envelope. It is read on the interface's flattened steering curve
  only, whose points the module also holds (the take is refused on any other).
- The gear is `get_control()`'s by Phase 7's rule: reverse set exactly when it is -1; a forward gear
  number passes as `slice.dbc`'s CurrentGear carries it.

This does not demonstrate that the law holds beyond the drives WP9a read it on (the taxi, Town 10, the
flattened curve), its mechanism, or any Ackermann geometry: 0.10.0 reports no wheel angle. Its tests are
in `tests/test_sdv_carla010.py`.
