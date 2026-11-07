# sdv/bridge: the kind 4 claim bridge (vss_claim_bridge): its core, its source adapters and its image

The kind 4 wire specification's bridge (section 14, the design values of
section 15): one claim per 10 Hz tick, packed from the latest held VSS values and sent to the QNX guest's
monitor on `:7160` (svc, 500 ms deadline), or on `:7161` (stamp) for pre-registered timing runs only.

| file | what it is |
|---|---|
| `vss_claim_bridge.py` | The core and a small command line. Held values with their age-source timestamps, never cleared by age; the intake loop and the tick, each pausable on its own; the 1-deep queue with `seq` assigned at packing; the accounting; the connection (lazy connect and reconnect, the backoff, the peer-closed check before every send, the 500 ms reply timeout); the scenario lock; reason 21; injection; the demo-ODD window; the bounded write-back queue. Standard library only. |
| `reasonsets.py` | Phase 2 step 3's comparison: event-to-reason sets from the reply logs (identical sets pass, a missing or extra pair fails), the comparison of one recording across the three modes (`compare_modes`: every mode present, every set equal), and frame-by-frame comparison, offered only between two `replay` runs, on the frames the reply logs carry (`reply_frames`). It also says how each mode's event windows reach a run's `src_now_ns` clock: offsets on the recording plus an origin, in `replay` the grid origin the run logs (`replay_anchor`, `shift_windows`), in `can` and `broker` the player's first frame on CLOCK_REALTIME, which the stack records (`sdv/stack/step3.py`). |
| `bridge_sources.py` | The source adapters and the command line with a real source (the image's entry point). `broker`: one kuksa.val.v2 Subscribe on the five generated slot paths, the datapoint timestamp as the age source, the start checks of the slots' datatypes and of the served `Vehicle.Chassis.Wheelbase` (spec 5.6). `can`: python-can's SocketCAN bus, filtered in the kernel to the slot messages' ids, decoded with cantools through slice.dbc (scaled), the receive time as the age source. `replay`: the candump file read here and scheduled by its recorded timestamps on the tick grid, whose per-run origin is logged (`replay-anchored`; `anchor_ns` in `source.json`). `MonitorWriteBack`, the write-back sink (`set(try_v2=True)`, only the `Monitor.VssClaim` leaves). `check`: the container's smoke. grpc, kuksa-client, python-can and cantools are imported lazily, inside the code that uses them. |
| `Dockerfile` | The image `vss-claim-bridge`: the stack's pinned Python 3.12 base (by index digest), packages from `requirements.lock` only, the code and the generated contract baked in, run as uid 10001. It sets `SDV_SCENARIO_LOCK_MUST_EXIST=1` and leaves `/run/lock` writable by root only, so the scenario lock must be the host's file, bind-mounted at `/run/lock/sdv-scenario.lock`: the bridge then takes no other lock (below); its header says how to run it. |
| `requirements.lock` | The image's packages, hash-pinned, wheels only: the union of the app's lock and the sim's (every shared pin equal), with kuksa-client 0.6.0, python-can and cantools. |
| `requirements.aarch64.lock` | Its arm64 twin (SDV Phase 3 WP0): the union of the app's and the sim's aarch64 locks, staged by `build_image.py --arch arm64`. |
| `build_image.py` | Stages the build context outside the repo, checks slice.dbc against the generation manifest, builds with `--provenance=false --sbom=false`, labels the image with the catalogue digest and the sha256 of the contract and of slice.dbc, and prints the build record (the image ID, every staged file's sha256); `--smoke` runs the image's `check`. `--arch arm64` (SDV Phase 3 WP0) builds the linux/arm64 image with buildx and the aarch64 lock, tagged `...-arm64`; its emulated smoke is `sdv/arm64/arm64.py smoke`'s. |

The packing is `sdv/frame/vssframe.py`'s and the rule-26 arithmetic `sdv/frame/rules.py`'s. The digest,
AGE_MAX, the profile table, the generated run window of the demo-ODD profile and the two spread thresholds
come from the generated contract (`sdv-out/gen/vss_contract.py`; `SDV_GEN` or `--gen` names another
directory); none is copied here. The source adapters (`broker`, `can`, `replay`) are `bridge_sources.py`'s
and import kuksa-client, python-can and cantools lazily; the core (`vss_claim_bridge.py`) imports no gRPC.

## The rules it keeps

- **Threads (Phase 2 design decision c).** The intake writes the held values and the claim thread reads
  them through one lock, held only to copy (a locked snapshot); the intake never waits on its stream with
  that lock held. The claim thread runs the tick and the socket in one `select()` loop and never waits on
  the intake or on the write-back: the write-back to the `Monitor` branch is a bounded queue, and a full
  queue drops the record and counts it. While it runs it is the event log's only file writer (other
  threads' records are appended in memory and written at its next pass), so it never waits on another
  thread's file I/O. A stalled stream therefore shows on the guest as ageing values (22), never as a
  silent bridge (MISS).
- **Accounting (spec 14.2).** `packed = replied + drop + lost_on_reconnect`, `ticks = packed + ticks_empty`,
  and the replied, dropped and lost seqs partition `1..packed`. At a stop the queued frame is sent at once
  if nothing is outstanding, the connection is open and the tick is not paused, and every outstanding
  frame gets its reply or the reply timeout (no reconnect, no tick); whatever is left is counted, so the
  identity holds when a run ends. A tick is counted with its frame or as empty, never before the pack. A
  frame's age is its age at packing; a queued frame is sent, if at all, before the next tick replaces it
  (the stop's drain apart). Every send checks the pause first: while the tick is paused, the frame queued before the
  pause is dropped (`drop`, why `paused`) at the claim thread's first pass after it, whether a paused
  tick, the outstanding frame's reply, the backoff's end or the stop wakes it, so no frame packed before
  a pause is sent inside it with a stale age (only a send already past that check when the flag is set
  completes, at the pause; Phase 2's exit wants drop = 0 in every actual run, a pause run included, so such a
  drop there is a finding, and the paths with a drop are pytest's). Also
  counted, with the seq logged: `age_negative`, `age_over_max` (with the slot that set the age),
  `spread_exceeded`, `r26_skip_window`, `r26_skip_ay`; every 26 is logged with its spread and whether the
  profile's attribution spread covers it.
- **Connection (spec 14.3).** Connect at the first frame; reconnect only when the next frame is to be
  sent; a failed connect (refused, or not completed within the 500 ms connect timeout) backs off from one
  tick, doubling, to 2 s. A non-blocking `recv(MSG_PEEK)` before every send. A frame unanswered when the
  connection drops, or for 500 ms (the reply timeout, design decision b; the bridge then closes the
  connection itself), is `lost_on_reconnect`. Lost means unanswered, not unjudged: a monitor that resumes
  may still judge a frame given up after the reply timeout, so its console totals can exceed the reply log
  by at most `lost_on_reconnect`; reason sets come from the reply log.
- **Scenario lock (owner, 2026-10-01: held while connected).** An `flock` on
  `/run/lock/sdv-scenario.lock`. A path that cannot be opened, or that is not a regular file (`/dev/null`, a
  FIFO), is refused at start. By default the file is created if absent and `SDV_SCENARIO_LOCK` or `--lock`
  moves it. With `SDV_SCENARIO_LOCK_MUST_EXIST=1`, as the image sets it, the bridge takes no lock but the
  host's file: `--lock` and `SDV_SCENARIO_LOCK` may name no other path, the file is never created, and it must
  be a mount point (`/proc/self/mountinfo`), so a missing file, another path, `/dev/null` mounted there or a
  file made inside the container is refused at start, and a container started without the mount can never take
  a private lock (only `SDV_SCENARIO_LOCK_MUST_EXIST=0` as root, or another file mounted there, defeats it). The
  lock is taken when a connect completes and released at the close: the bridge is connected
  exactly while it holds the lock, and holds none while a connect is pending. The lock gates the bridge's
  state and its sending, not the TCP connection the guest sees, which is open and unlocked from the end
  of the handshake until the lock is taken. A lock held elsewhere closes the new connection unused and
  backs off like a failed connect (the next attempt waits out the backoff); each such attempt leaves a
  `client done: seen=0` line on the guest's console.
  `updater_check()` is the double of the updater's non-blocking check (the updater is Phase 6's).
- **Reason 21 (owner, 2026-10-01: keep sending).** Logged once, counted every time; an uninjected 21 fails
  the run's exit condition.
- **Injection** (`nan`, `reserved`, `digest`, `profile0`) and the two pauses exist for demos and tests, and
  are refused when the target port is `:7161` (`stamp=False` with `:7161` is refused at start).
- **Script (Phase 2 WP10).** `--script FILE` (or `Bridge(script=...)`): those control calls and `end`, each at
  an offset from the script's origin on the source's own clock, made by a script thread. The origin is the
  source's own when it has one (`replay`: the grid anchor, so an offset is a recording offset; the clock then
  the raw CLOCK_MONOTONIC before the grid, so a step can land between a delivery and the tick), else the first
  held update's age-source timestamp (`can`, `broker`). `end` ends the run as `--seconds` would. A script is
  checked whole at start, and one with any control call is refused on a stamp target. The origin and every step
  (its due and done instants) are logged, and the summary carries the script's state. `sdv/stack/step3.py` writes
  the scripts of Phase 2 step 3's runs: replay's stop (an intake pause) and every run's end past its
  `run_through_ns`, and the specs' injections and pauses.
- **Demo-ODD window.** The run header's `{profile_id, start_s, duration_s}`, from the first packed frame;
  refused when longer than the profile's generated `run_window_max_ms`; first and last seq logged.
- **Refusals at start.** A bridge mode other than `broker`, `can` or `replay`; profile id 0, one not in
  the generated table, or one generated but not compiled into the guest; a declared source vehicle whose
  wheelbase is not the profile's L (spec 5.6, every mode); a run header whose `age_max_ms` is not the
  generated AGE_MAX; a scenario lock path the rules above refuse. Then the mode's own (`bridge_sources.py`):
  in `broker` the slots' datatypes and the served `Wheelbase` (a value that is not L is refused, the
  catalogue default 0 included; none served starts with the note `wheelbase: not served by the databroker,
  checked against the declared source vehicle only`); in `can` and `replay` the DBC is the one the contract
  was generated from, with the contract's units and periods; `replay` refuses a file that is not candump
  `-l` standard data frames in time order.

## How

In WSL, from the repo root, a run against a source supplied in-process (a test, a demo driver):

    import vss_claim_bridge as vb
    vb.main(["run", "--port", "7160", "--header", "run-header.json", "--name", "demo"], source=my_source)

From a shell, a run with a real source is `bridge_sources.py run` (the same run flags, plus `--broker`,
`--writeback`, `--channel`, `--log` and `--dbc` by mode); it adds `source.json` (the source's counts) to the
run directory. `vss_claim_bridge.py run` from a shell has no source and refuses with exit 2, naming
`bridge_sources.py run`. In the image the entry point is `bridge_sources.py`: `run ...`, or `check` (the
smoke: the adapters' modules import, the contract and the DBC load). Build it with
`python3 sdv/bridge/build_image.py --smoke` in WSL and run it by image ID as the Dockerfile's header says
(the host's lock file bind-mounted with `--mount`, `--user` the host user, `--out` on a mounted directory).
A run ends at `--seconds`, SIGTERM or SIGINT (a signal ends a run given `--seconds` too, with its drain
and summary: `docker stop` sends SIGTERM), or a fatal in the claim thread (exit 1). A start refused after
the run directory was opened leaves no empty run directory behind. Output goes to
`~/sdv-runs/<date>-<name>/` (`SDV_RUNS` moves the root) or `--out`, never inside the repo or under
`~/sdv-recordings`: `bridge.jsonl` (start, connect, close, losses, drops, the counters' events, the signal
that ended the run, in `replay` the grid's origin, and a script's origin and steps), `replies.jsonl` (one line
per reply, with the 64 bytes sent as `frame`: the evidence Phase 2 step 3 compares) and `summary.json`.

Tests: `tests/test_sdv_bridge.py` (kind4-spec 16.2 P1-P8, P10, P11, P13, P15-P18) and
`tests/test_sdv_bridge_sources.py` (P4, P9, P12, P13's replay windows, P14, the broker intake's pause, the
lock and the Dockerfile, with a fake databroker client and a fake bus; the real cantools and python-can
paths when the sim venv `~/sdv-sim-venv` exists; the image when `SDV_BRIDGE_IMAGE` names a built one and
Docker is present), against the native vss monitor where the guest's answer matters; they need the
generated contract and, for the native ones, gcc on Linux. The script and the step-3 comparison are
`tests/test_sdv_step3.py`'s (with Phase 2 step 3's harness, `sdv/stack/step3.py`).

## Design values

From the specification (section 15), none generated: the 10 Hz tick, the 500 ms reply timeout, the backoff,
`:7161`. The core's own, rows of section 15 since (Phase 2's design decisions h-k): the connect timeout (500
ms, with no lock held), the write-back queue (one second of replies; each record carries the cumulative
counters), the stop's drain bound (two reply timeouts) and the signal poll (50 ms: a SIGTERM or SIGINT
handler only sets a flag, which the command line's wait looks at). `bridge_sources.py`'s own: the
subscription buffer (witness.py's, the largest databroker 0.7.1 accepts), the start checks' wait for the
databroker, one write-back's wait, and the CAN intake's longest wait per receive (its module docstring,
DESIGN VALUES). The image's own: uid 10001 and `SDV_SCENARIO_LOCK_MUST_EXIST=1`. The script reuses the signal poll
as its thread's longest single wait.

## What this does not demonstrate

Any timing; what any source delivers (the adapters' tests use a fake databroker client and a fake bus;
a real databroker and a real SocketCAN interface are Phase 2 WP8's); anything about the guest beyond its
replies. Replay's frame-for-frame determinism only while every tick reads the clock within half a tick of
its schedule (`bridge_sources.py`, replay). The `Monitor` write-back is the bridge's own view, labelled
as such. A thread keeps the tick off the gRPC side but does not meet plan:209's letter (a KUKSA client
never in the claim process), which only a separate process would (Phase 2 design decision c). Nor a quiet
process beside the claim thread: the command line's wait wakes at 20 Hz (the signal poll) and briefly takes
the GIL, in every run, those aimed at `:7161` included.
