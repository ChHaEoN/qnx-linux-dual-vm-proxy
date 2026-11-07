# sdv/inject: the injected recordings of Phase 2 step 3 and their events file

Phase 2 step 3 replays a recording whose frames carry kind 4 reasons
23-27, and stops the provider for 22. sigsim cannot make such frames: its clamp and envelope refuse a speed,
an acceleration or a steering angle beyond the profile's limits and a gear against the direction of travel,
and it computes the yaw rate from v and delta. `inject.py` therefore rewrites the candump frames of an
existing sigsim recording, or of a CARLA recording (Phase 7, below), inside `slice.dbc`'s ranges, into a
**new** recording directory, and writes the events file beside it.

| file | what it is |
|---|---|
| `inject.py` | `rewrite` makes the new recording and its `events.json`; `check` checks one again from its own files. Its module docstring is the full description: the events, the two runs, their placement, how the expected reasons are computed, the files written, a CARLA source (A CARLA SOURCE), the design values. |

## Running it

In WSL, with the sim venv's Python (cantools and python-can, `sdv/sim/requirements.lock`), from the repo
root:

    ~/sdv-sim-venv/bin/python sdv/inject/inject.py rewrite --from ~/sdv-recordings/<source> --name <new name>
    ~/sdv-sim-venv/bin/python sdv/inject/inject.py check ~/sdv-recordings/<new name>

`rewrite` writes `~/sdv-recordings/<new name>/` (`--root` or `--out` put it elsewhere, never inside the
repository) and refuses a directory that exists: no recording is ever modified. The source recording is
only read; every file of it is hashed before and after, and a change refuses. The DBC is
`sdv/vss/slice.dbc` unless `--dbc` names another; it must be the one the source was encoded with (its
manifest line's `dbc_sha256`) and the one the generated contract was made from. `check` holds the
recording to the current contract and DBC, and warns on stderr when the source is gone and its diff
against the source was skipped.

## What it writes

- The log under the source's own name (`sigsim.log` for a sigsim source, `carla.log` for a CARLA one): the
  source's lines, verbatim except the events' frames, which keep the source's line form; its `.sha256`.
- `events.json` (format 2):
  - `events`: the five injected events (23-27), each with its window (`t0_ns`, `t1_ns`: ns from the
    recording's first frame, half open, the injected span widened by the generated pipeline allowance A),
    its injected span, its reason as the offline replay computed it, and the rewrite (slot, VSS path,
    message, signal, value, the limit it is beyond or the condition and margin it holds by, the frames
    changed).
  - `runs`: two runs of the file, each the five events plus two 22 windows from its reference R: a bounded
    first window `[R, R + AGE_MAX + one tick + A)` that must hold the first 22, and the open-ended rest.
    `stop` (windows `stop`, `stop-held`): R is the stop, realised per mode -- `broker` stop the
    can-provider, `can` stop the player, `replay` pause the intake -- never undone. `to_end` (windows
    `end`, `end-held`): R is the file's last frame, nothing is stopped. A run whose stop is not realised
    gets its 22 only after the file's end, so its set lacks `(stop, 22)`. Each run names
    `run_through_ns`, the offset it must keep ticking through.
  - WP10 takes a run's windows with `run_events(doc, run)`, puts them on the run's clock with
    `sdv/bridge/reasonsets.py`'s `shift_windows` (in `replay`, by the run's logged `replay-anchored`
    origin) and compares event-to-reason sets with `reason_set` and `compare`.
  - `rewritten_from`: the source's name, directory and hashes, and a CARLA source's `rtf` (the one the
    new line copies; a sigsim rewrite's has none).
- `summary.json`: the source's trip cut to the fields that still describe the file (segments, message
  counts, periods, duration, seed, the source's params, profile, wheelbase, and a CARLA trip's `rtf`,
  `timestamps` and `gaps`: no frame moves, so the steps where the schedule had no frame stay where they
  were); the fields that describe the drive's values, or a CARLA take and its encoding, are dropped and
  named in `rewrite.trip_fields_dropped`; and the rewrite's provenance.
- `manifest-line.json`, last: the source's line with its own name, path and sha256, and three
  `source.params` entries naming the rewrite (`rewrite_of`, `rewrite_of_sha256`, `rewrite_events_sha256`);
  a CARLA source's `rtf` unchanged. Its path is a scenario entry path (from `~` or `/`, the characters
  `[A-Za-z0-9._/-]`, no `..` segment: `manifest-classes.md` section 9), for a sigsim source too: a
  destination whose path would not be one is refused before it is created. The stack
  (`sdv/stack/stack.py`) reads a sigsim directory like any recording.

## A CARLA source (Phase 7)

A CARLA recording (`sdv/carla/encode.py`'s, `source.generator` `carla`) is rewritten by the same rules,
events, runs, margins and design values as a sigsim one. What differs:

- The log is the basename of the manifest line's `recording.path`, and must be its generator's:
  `sigsim.log` for `sigsim`, `carla.log` for `carla`, with its `.sha256` beside it, which names no file
  but the log (a bare hash is read, as the stack reads it). Any other name, or another generator, is
  refused, and so is a `recording.path` that is not a scenario entry path (for a sigsim source too). The
  new recording keeps the source's log name.
- A carla source must carry `source.rtf` and a sigsim source must not (`{min, mean, max}`, each a number
  above 0, `min <= mean <= max`: the scenario entry's rule); `summary.json`'s trip rtf, where the trip has
  one, must be the line's. The rtf is copied unchanged into the new line, since the rewrite moves no
  frame, and recorded in `events.json`'s `rewritten_from`; `check` holds the new line's rtf to that record
  always (the run launcher copies it into every run header's `source_rtf`) and to the source's when the
  source is there.
- A CARLA line has five `source.params`; with the rewrite's three that is the scenario entry's cap of eight.
  A source whose params would break the cap, carry a string over 64 characters or a value that is neither
  an integer nor a string (a bool, a float, null, a list, an object), already carry one of the rewrite's
  three entries (a rewrite of a rewrite is not supported), or are not an object at all, is refused before
  anything is written.
- `steps.jsonl` is not copied: the rewritten log cannot be regenerated from the take's steps.
  `summary.json`'s `rewrite.not_copied` says so.
- The judge is the generation's compiled profiles, as for sigsim: a recording under profile 3 (the CARLA
  ego's) is rewritten only once the generation compiles that profile.
- The stack's own checks read the CARLA rewrite by the log its manifest line names;
  `tests/test_sdv_inject.py` checks those readers against a CARLA-shaped source.

## How the reasons are known

They are computed, not assumed: for each run, the rewritten frames go offline through the replay-mode
bridge (`bridge_sources.ReplaySource` on a fake clock, the bridge's `Intake`, `HeldValues` and
`ClaimCore.tick`), the stop run with its intake pause, and every packed frame is judged with
`rules.judge_frame`. The rewrite is refused unless, in each run, every tick inside each injected span is
rejected with the intended reason (at least two ticks per event), every other tick before R is ACCEPTed,
the first 22 comes at most AGE_MAX plus one tick after R (spec 14.1, P9) and only 22 follows it, each 22
window holds at least two rejects, and the hard-brake app's predicted switches on the file are the
source's. `tests/test_sdv_inject.py` repeats the replay with a driver of its own.

## What this does NOT show

Any timing; what a live mode (`can`, `broker`) samples (the windows' allowance is the specification's
pipeline allowance, not a measured delay); that the guest judges as the Python reference does; anything
about a vehicle: the values are injected, not driven. For a CARLA source: that the stack replays it (WP3b),
that a real CARLA recording is rewritten (the tests build a CARLA-shaped source from the sigsim recording,
under profile 1), or anything about CARLA itself.

Neither run can be played through `stack.py replay --bridge broker` (WP8's mode): it plays the whole file
with the player, stops the bridge at the player's end, and cannot stop the player or the can-provider
mid-file, so each run would lack its 22 pairs. WP10's harness, `sdv/stack/step3.py`, plays them: it keeps
the bridge ticking through each run's `run_through_ns`, past the player's end, and makes the stop at its
offset by the mode's realisation (the player or the can-provider stopped by the stack; in `replay` the
bridge's own `Bridge.pause_intake`, a step of its script).

The reference recording (`inj4`) names the SHA-256 of the `inject.py` that made it.
Phase 7's WP3a changed the tool after that recording. `tests/test_sdv_inject.py` holds a sigsim rewrite to
that recording byte for byte in all five files, but for the tool's sha256, the contract's sha256 (the
generation's identity, which `check` holds) and the paths and hashes that follow from them; so the recording
stands, and a change to what a sigsim rewrite writes fails that test. It stands under the contract it was
made with: `check` holds `inj4` to the generation's contract, so under Phase 7's frozen profile 3 (WP2's
generation) it refuses `inj4` ("events.json was made with another contract") until `inj4` is re-made on the
merged tree. A re-made inj4 (which a generation with another contract sha256 needs, since check holds it)
names the tool that re-made it: change `WP10_TOOL_SHA256` in `tests/test_sdv_inject.py` with it, since both
inj4 tests assert it.

## Design values

The generated quantities (the profile's limits, tol, v_tol, the periods, A, AGE_MAX and the two
margins) are read from the contract, never written in `inject.py`. The tick is not generated: it is
the bridge's own design value (`vss_claim_bridge.TICK_NS`, specification 15), imported from the
bridge. The tool's own
values are written there and listed apart in its module docstring (DESIGN VALUES): `MIN_EVENT_TICKS`
(the specification's sampling rule), `INJECT_FACTOR` and `SEPARATION_NS` (free choices), and
`OPEN_END_NS` (a sentinel). The local design notes record them as Phase 2 design decisions s-v.
