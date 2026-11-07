# sdv/vss: the VSS contract of the SDV slice

This directory holds the project-written inputs of the slice's VSS contract and the script that
turns them into every generated artefact. The generated files are never committed: they are built
from pinned inputs whenever they are needed, into the ignored `sdv-out/gen/`.

## What is here

| file | what it is |
|---|---|
| `overlay.vspec` | The one overlay on the VSS 6.0 standard catalogue: the project branch `Vehicle.DualVm` (`Motion`, `Monitor`, `AppState`), the two sign conventions VSS 6.0 leaves open (yaw rate; `Vehicle.Speed` is a magnitude, `min: 0`), and the CAN mapping (`dbc2vss`) for `slice.dbc`. |
| `slice.dbc` | The slice's own minimal DBC for a simulated vehicle: the five kind 4 signals in VSS units and ISO 8855 signs. Its periods and factors are the one source for every constant derived from them. |
| `profiles.toml` | The kind 4 profile table (one profile = one source vehicle + one limit set) and the pipeline constants beside it: AGE_MAX, the pipeline allowance A, the simulator step and each envelope's rows. Comments distinguish design values and thresholds from READ configuration values and PROBED source parameters. |
| `uid-baseline.txt` | The committed staticUIDs of the five kind 4 slots and of every node of the project branch, with the catalogue digest. Written by `generate.py --accept-uid-change`, never by hand. It is what a fresh checkout compares a generation against, since no generated file is committed. |
| `generate.py` | The generator (below). |
| `requirements.lock` | vss-tools 6.0.0 and everything pip resolves for it, pinned exactly, with hashes. |
| `overlay-ctl.vspec`, `units-project.yaml`, `quantities-project.yaml` | The `ControlCommand` layer and the units it needs (rad and m/s^3, the quantity jerk; D5). From Phase 8 on `generate.py` loads them for the databroker catalogues and the kind 2 contract only; `vss-ids.vspec` and `vss-can-mapping.json` stay on the overlay and the stock VSS 6.0 unit and quantity files (below). The kind 2 section describes the exports. |
| `profiles-ctl.toml` | The kind 2 profile table and the constants of its rules (Phase 8): rule 11's `dt_max_ms`, rule 17's `tol17`, rules 18 and 19's constants, profile 1 READ from the planning stack's gate and profile 2 the demo profile. Every value is READ (marked so, each naming its parameter) or a design value with its reason; its header lists every refusal. |

## What it generates, and from what

`generate.py` takes the VSS v6.0 **source-tag archive** (GitHub's archive of the tag, never the
release's attachments), checks it against its pinned sha256 and against the commit its own pax
header records, extracts only its `spec/` tree, and runs vss-tools 6.0.0 under `--strict` with
`overlay.vspec` on top, then a generated vehicle layer: the `sigsim` run type's for the main
catalogue, and once more with each other run type's layer for that run type's own databroker
catalogue. The databroker catalogues and the kind 2 contract come from the same exports with the
`ControlCommand` layer between the overlay and the vehicle layer (below). From one run it writes, all
or nothing:

| output | for |
|---|---|
| `vss-ids.vspec` | the id exporter's output: every node with its staticUID (case-insensitive, vss-tools' default), without the `ControlCommand` layer |
| `vss-can-mapping.json` | the JSON catalogue with the `dbc2vss` mapping: the CAN provider's mapping file, without the `ControlCommand` layer |
| `vss-databroker.json` | the same catalogue with the `ControlCommand` layer and without `dbc2vss`: the databroker's `--vss` catalogue for run type `sigsim` (the stack's). The stack starts the databroker on this file (`sdv/stack/stack.py`, `--vss`); the CAN mapping no longer serves the same nodes (it carries no `ControlCommand`), so it is not interchangeable with it |
| `vss-databroker-carla.json` | the databroker catalogue exported with run type `carla`'s vehicle layer instead: `vss-databroker.json` but for the Wheelbase default. Nothing loads it yet (the stack's CARLA runs are Phase 7's later work) |
| `vss-databroker-planning-sim.json`, `vss-databroker-carla-autoware.json` | the same for run types `planning-sim` (Autoware's planning simulator; the stack's `ros` feed, Phase 8 WP3d) and `carla-autoware` (the CARLA 0.10.0 closed loop, Phase 8.5): `vss-databroker.json` but for the Wheelbase default. Nothing loads either yet |
| `vehicle-sigsim.vspec`, `vehicle-carla.vspec`, `vehicle-planning-sim.vspec`, `vehicle-carla-autoware.vspec` | the per-vehicle layers (kind 4 wire specification 5.6 and 14.5; Phase 2 design decision g), one per run type with a live default: one node, `Vehicle.Chassis.Wheelbase` with its catalogue `default:` set to the L of that run type's live-default profile in `profiles.toml`, loaded after the overlay. VSS 6.0's default is 0, and the databroker serves an attribute's catalogue default, so without the layer a broker-mode claim bridge reads 0 and refuses to start. A databroker serves one Wheelbase, so each layer has its own catalogue. Generated, never written by hand: the value is the profile's, so it is no literal anywhere. `default` is not a staticUID input, and the generator checks, on each layer's own exports, that the node keeps the stock tree's staticUID and that the default reached the JSON |
| `vss_contract.h` | the monitor's contract: the five kind 4 slots' staticUIDs, the catalogue digest, AGE_MAX, the conversion constants |
| `vss_profiles.h` | the compiled profiles as an X-macro table (profiles with stand-in values stay out) |
| `vss_contract.py` | the same for Python, plus A, the step, the envelope rows and every derived constant: the simulator feeder's pacing interval and repeat cap, the gap onset and honest-22 real-time factors, the rule-26 spread thresholds, each profile's rule-26 budget and attribution spread |
| `vss_ctl.h` | the kind 2 contract for the monitor's ctl build (`MONITOR_EXT_KINDS=0x14`, `make ctl`): the seven kind 2 slots' staticUIDs, their digest, the constants of rules 11 and 17-19, the compiled kind 2 profiles as an X-macro table |
| `vss_ctl.py` | the same for Python (`sdv/ctl` loads it by path), with every kind 2 profile and its run window |
| `manifest.json` | the inputs' and outputs' sha256, the pins, the options and the checks that ran; `vehicle_layer` (the sigsim layer's object, which the stack reads, as when a generation had one layer), `vehicle_layers` (each run type's, same keys) and `databroker_catalogues` (each run type's catalogue file); `vss_tools.overlays` names the main catalogue's two layers, every other run type's exports' layer is in `commands`; `vss_tools.ctl_layer` says which outputs the `ControlCommand` layer is loaded for, and `ctl_contract` holds the kind 2 contract's format, digest, files and the sha256 of `profiles-ctl.toml` |

The **catalogue digest** is FNV-1 32 over the five slots' staticUIDs as little-endian u32 in slot
order, the hash function vss-tools itself uses for staticUIDs. It binds the slots' names, units,
datatypes and bounds; it does not bind the profile table, AGE_MAX or the frame layout.

## How

In WSL Ubuntu-24.04, once:

    python3 -m venv ~/sdv-venv
    ~/sdv-venv/bin/pip install --require-hashes --no-deps -r sdv/vss/requirements.lock

Then, from the repo root:

    ~/sdv-venv/bin/python sdv/vss/generate.py

The first run fetches the archive into `~/sdv-cache/`; later runs reuse it and check it again.
Useful options: `--out DIR`, `--archive FILE` (a local copy, still checked), `--overlay`,
`--profiles`, `--dbc`, `--overlay-ctl`, `--units-project`, `--quantities-project`, `--profiles-ctl`
(other inputs, for tests), `--project-branch NAME`, `--previous-ids FILE` or `--no-previous`,
`--uid-baseline FILE`, `--accept-uid-change`.

**Against the previous generation.** When `--out` already holds a `vss-ids.vspec`, the new id output
is compared with it path by path, and vss-tools' own `--validate-static-uid` runs as a cross-check.
The path-by-path diff decides: vss-tools matches by UID first and exits 0 on a breaking change, so it
cannot be the only judge. A staticUID that changed or disappeared is refused unless
`--accept-uid-change` says it is intended (renaming the project branch, or giving a slot a unit, min
or max, moves the digest and needs a new guest image). Added nodes are reported, not refused.

**Against the committed baseline.** In a fresh checkout there is no previous generation, so every run
is also compared with `uid-baseline.txt`: the five slots' staticUIDs, every node of the project
branch, and the digest. A changed, removed or new node, or a moved digest, is refused; a missing
baseline is refused. `--accept-uid-change` accepts the drift and then rewrites (or creates) the
baseline, only after every output was written, so a refusal leaves the tree untouched. Commit the
rewritten file with the change that caused it: the drift is a decision, and it needs a new guest image.

**It refuses** (exit 1, nothing written, the reason on stderr) on: an archive whose sha256 or
embedded commit differs from the pin; any `.fidl` file among the inputs; a venv that differs from
`requirements.lock`; any vss-tools error or warning under `--strict`; a malformed staticUID; a slot
that is missing or of another datatype; a standard node whose staticUID differs from an
overlay-free build (`Vehicle.Speed` excepted) or a node added outside the project branch; a
`Vehicle.Speed` that is not a sensor, a float, in km/h, with min 0; an overlay entry that does not
reach the catalogue as written; a `dbc2vss` signal `slice.dbc` does not define; a vehicle layer
whose run type has no single live-default profile, whose profile's L is a stand-in (a stand-in
`delta_max` alone keeps the layer, which carries L only), whose source vehicle
has two wheelbases in the profile file, whose node moved its staticUID or is not an attribute in mm, or
whose default did not reach the JSON; a run type that `profiles.toml` gives a live-default profile and
`generate.py` no layer (`VEHICLE_RUN_TYPES`); a moved staticUID against the previous generation or the
baseline (above); a digest of all zeros or all ones; a
profile file that is not TOML or breaks an invariant (checked right after the archive, before the venv
and any vss-tools run, so a refused file costs no export); a derived constant that is undefined; a rule-26 budget that keeps less
than its envelope's `margin_target` over tol (checked after the exports: it needs the slots' DBC
signals from the generated mapping); a compiled profile on an envelope that holds a stand-in row, an
envelope's `stand_in` that names anything but its own rows, a `skew_ms` row on an envelope that is
not a planning-sim one (`SKEW_ROW_ENVELOPES`), on one whose budget is not rows-summed, or that is not a
positive whole ms, and a profile on a planning-sim envelope that is the live default of a run type
outside `SKEW_ROW_RUN_TYPES`, or a run type of those whose live default is on another envelope (all with
the profile file's invariants). The bounds the profile file is checked
against are constants of `generate.py`, each with its spec reference, and not settings of
`profiles.toml`: a `profiles.toml` that carries an `[invariants]` table is refused. For kind 2 it
also refuses a `profiles-ctl.toml` that breaks one of its rules (its header lists them; checked with
`profiles.toml`'s, before the venv), a `ControlCommand` layer that adds anything but its own entries,
changes another node, carries a `dbc2vss` block or does not reach the catalogue as written, a kind 2
slot that is missing or of another datatype, and a kind 2 digest of all zeros or all ones.

## The kind 2 contract (Phase 8 WP1b)

`overlay-ctl.vspec` is loaded after `overlay.vspec` and before the vehicle layer, with
`units-project.yaml` and `quantities-project.yaml` after the stock unit and quantity files, in one id
export and one JSON export per run type. Those JSON exports, less `dbc2vss`, are the databroker
catalogues, so every catalogue serves the eleven `ControlCommand` nodes (the branch and its ten leaves)
in the units the layer writes (rad, rad/s, m/s^3: vss-tools refuses the layer without the project
unit files). `vss-ids.vspec` and `vss-can-mapping.json` are still the exports without the layer, byte
for byte what the tree generated before it: the twin connector's image pins the id file's sha256 (its
`sdv.twin.catalogue_sha256` label in `sdv/stack/images.json`), the twin allowlist's tests hold that
the id file carries no `ControlCommand` node, and no CAN signal maps to one. The generator checks that
the layer adds exactly its own entries under `Vehicle.DualVm.ControlCommand`, moves no other node and
that each databroker catalogue is the CAN mapping, without `dbc2vss`, but for that branch.

The seven kind 2 slots (`ControlCommand.Velocity`, `Acceleration`, `Jerk`, `SteeringTireAngle`,
`SteeringTireRotationRate`, `Motion.LongitudinalVelocity`, `ControlCommand.StampInterval`, in that
order) take their staticUIDs from the id export with the layer, as kind 4's slots take theirs from
`vss-ids.vspec`. The **kind 2 digest** `VSS_CTL_DIGEST` is FNV-1 32 over those seven as little-endian
u32 in slot order, the catalogue digest's construction, refused when all zeros or all ones; the monitor
refuses to serve when it is not the digest of its compiled UIDs. `uid-baseline.txt` lists the layer's
eleven nodes beside the project branch's others; every line it held before is unchanged, and the kind 4
digest does not move.

`profiles-ctl.toml` holds the constants of rules 11 and 17-19 and the kind 2 profiles: profile 1 from
the planning stack's command gate (its nominal filter's loosest cells and the vehicle's wheelbase, each
`READ` and held once more in `tests/test_sdv_vss_ctl.py`'s `READ`, so a re-read changes those two
places and regenerates), profile 2 the demo profile under the planner's top speed with its bounded run
window. Both are compiled. A profile with stand-in values is never compiled: it stays in `vss_ctl.py`
only. The kind 4 outputs and the kind 4 digest do not depend on any kind 2 input:
`vss_contract.h`, the vehicle layers, `vss-can-mapping.json` and `vss-ids.vspec` are byte for byte what
the tree generated before the layer joined, and `vss_profiles.h` and `vss_contract.py` are what the
last kind 4 profile change wrote (profiles 4 and 5, below); a test holds each one's sha256. `make ctl`
(the monitor's Makefile) and `build-monitor-native.sh` with `MONITOR_EXT_KINDS=0x14` build the ctl
monitor from these headers; `make ctl` stops on a generation whose `vss_profiles.h` holds no profile 4
row, which this one holds.

It does not show that any kind 2 limit is right for a run (WP4b judges real traffic against it), that
the databroker serves the `ControlCommand` nodes or that anything writes them, or that a guest image
built from this generation exists.

## Profile 3, frozen (Phase 7)

Profile 3 is the CARLA ego's (`carla-ego`, the `carla` envelope, run type `carla`'s live default).
Until Phase 7 it held stand-in values and stayed Python-only. The freeze (Phase 7 WP2)
changed:

- it is **compiled**: `vss_profiles.h` and `COMPILED_PROFILE_IDS` hold it, so a guest image built from
  this generation judges under it (the CARLA guest image is Phase 7's own; images built before the
  freeze answer it with reason 8), and the carla vehicle layer carries its L;
- its L and `delta_max`, and the `carla` envelope's four rows (the three its rule-26 budget rests on
  and the launch acceleration `v_tol` covers), are marked `PROBED` in `profiles.toml`. The envelope
  rows were fitted locally; the readings are not published. Each row is the smallest one-decimal
  value at least 1.1 times its largest fitting input. Each is held only on its line there and once in
  `tests/test_sdv_vss.py`'s `PROBED`, and a re-read changes those two places and regenerates. The
  understeer row was read only below the a_y bound; the joint grid extrapolates it linearly up to the
  bound;
- its a_y bound is the owner's value, which the rule in its comment narrows only as far as the
  joint-grid budget needs to keep the envelope's `margin_target` (on the probed rows it needs no
  narrowing); tol, the window, `v_max`, `a_max` and `v_tol` did not move, and the generator now
  refuses any profile whose budget keeps less than its envelope's margin;
- outputs: `vss_profiles.h`, `vss_contract.py` and `manifest.json` changed, `vehicle-carla.vspec` and
  `vss-databroker-carla.json` are new; `vss-ids.vspec`, `vss-can-mapping.json`,
  `vss-databroker.json`, `vehicle-sigsim.vspec`, `vss_contract.h`, `uid-baseline.txt` and the digest
  are byte for byte what the tree generated before it (a test holds their sha256).

It does not show that any profile-3 value is right for the CARLA vehicle beyond the one controlled
drive the probes read, that a CARLA recording passes under it, or that a guest or a bridge image built
from this generation exists.

## Profiles 4 and 5, run types planning-sim and carla-autoware (Phase 8 WP3b)

Four run types now have a live default, each with its vehicle layer and its databroker catalogue:
`sigsim` (profile 1) and `carla` (profile 3) as before, `planning-sim` (profile 4: Autoware's planning
simulator, whose standard signals the stack's `ros` feeder writes) and `carla-autoware` (profile 5: the
CARLA 0.10.0 closed loop, whose standard signals come from the CAN path). Each new layer carries its
profile's L, so its catalogue is `vss-databroker.json` but for the Wheelbase default.

- **Profile 4** (`autoware-sample-vehicle`, the `planning-sim` envelope) is **compiled**:
  `vss_profiles.h` holds its row (the row `make ctl` needs) and `COMPILED_PROFILE_IDS` its id, which
  was reserved for it until now. Its L, `delta_max` and `v26_hi`, and the envelope's rows that bound
  Autoware's commands as its command gate limits them, are READ from the planning stack's own
  configuration (WP4a), each marked `READ` in `profiles.toml` and held once more in
  `tests/test_sdv_vss.py`'s `READ`; the three rows no read bounds are design values with their reasons.
  It has no a_y bound: the simulator's vehicle model is a kinematic bicycle without slip (its source,
  read for this package). The envelope is rows-summed with sigsim's margin, and its `skew_ms` row (the
  simulator publishes the three rule-26 inputs on one timer) replaces `slice.dbc`'s period for this
  envelope alone; tol26 is the smallest one-decimal value that keeps the margin over the summed rows.
- **Profile 5** (`carla010-taxi`, the `carla010` envelope) is **not compiled**: it is in
  `vss_contract.py` only, and a guest built from this generation answers it with reason 8. Its own
  values hold no stand-in (its L and `delta_max` are `PROBED` from WP9a's CARLA 0.10.0 reads, the rest
  are profile 3's), so the carla-autoware layer carries its L; but the four rows of its joint-grid
  envelope are **stand-ins**, the `carla` envelope's values, listed in the envelope's `stand_in` and
  marked `STAND-IN`. Its budget's margin is computed and held on them, so it says nothing yet about the
  taxi. WP3c's freeze sets each row from WP9's first honest drives, by the `carla` rows' rule, empties
  `stand_in`, applies the a_y narrowing rule again and compiles the profile (a new pin of the bridge).
- New refusals: a compiled profile on an envelope that holds a stand-in row; a `skew_ms` row on any
  envelope but a planning-sim one; a profile on a planning-sim envelope that is the live default of any
  run type but a planning-sim one, and a planning-sim run type whose live default is on another
  envelope (`SKEW_ROW_RUN_TYPES`: the skew row describes the run type whose rule-26 inputs come from the
  simulator's one timer, so a `live_default_for` list cannot part the two). The sigsim and carla budgets
  are unchanged.
- Outputs: `vss_profiles.h`, `vss_contract.py` and `manifest.json` changed; the two layers and two
  catalogues above are new; every sigsim and carla output, `vss_ctl.h`, `vss_ctl.py`,
  `uid-baseline.txt` and the kind 4 digest are byte for byte what the tree generated before (a test
  holds their sha256). The claim bridge's image bakes in `vss_contract.py`, so its pin in
  `sdv/stack/images.json` was rebuilt and re-pinned with this generation.

It does not show that a planning-sim run passes under profile 4 (WP4b's honest runs judge that; an
honest reject there is a finding, never a moved row), that the simulator's response to a gated command
stays inside the gate's limits (inferred for a first-order lag), that the summed rows bound the
honest error at large steering angles (the rows-summed method takes the delta-skew row at a straight
wheel), or anything about the 0.10.0 taxi's envelope.

Two runs over the same inputs are byte-identical: no output carries a timestamp, an absolute path
or run state.

## Tests

`tests/test_sdv_vss.py`. The pure checks (FNV-1 vectors, the DBC reader, the profile invariants and
their constants, the derived constants and the margin refusal, profile 3's freeze and its `PROBED`
values, profiles 4 and 5 with their `READ`, `PROBED` and stand-in values, the planning-sim skew and the
two refusals beside it, the per-run-type layers, the sha256, commit, `.fidl` and early profile-file refusals, the
forbidden digests, the venv check on a fake venv, the drift rules and `uid-baseline.txt` itself) run
anywhere with Python 3.11 or later (the fake venv's python is a `#!/bin/sh` shim, so those tests need a
POSIX shell and skip on Windows). The generation tests need the venv above and skip cleanly without it;
none of them may rewrite the committed baseline, and each run that accepts a change is given a copy.
`tests/test_sdv_vss_ctl.py` holds the kind 2 contract (its table, refusals, digest, renderers, the
generated files against WP2's loader and the monitor, the unchanged set but for `vss_contract.py` and
`vss_profiles.h`, which `tests/test_sdv_vss.py` holds because a kind 4 profile change moves them), and
`tests/test_make_ctl.py` `make ctl`.

## Changing a pin

The VSS archive, its commit and vss-tools' version are pinned in `generate.py`; the venv in
`requirements.lock`. A change to any of them is deliberate: record why, regenerate the lock with
`pip download --no-deps` of the new resolution and the sha256 of each file, rebuild the venv from it,
and expect the previous-generation check to report what moved.

## What this does not demonstrate

That the databroker or the CAN provider load these files, that any value reaches the QNX guest, or
that any limit is right. The digest makes two builds agree on one catalogue; it stops an honest
mismatch only, never a dishonest writer on the Linux side; the kind 2 digest does the same for the
`ControlCommand` slots and nothing more. VSS is a data model, not a safety mechanism.
