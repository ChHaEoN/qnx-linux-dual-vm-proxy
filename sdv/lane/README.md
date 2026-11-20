# sdv/lane: the kind 6 lane claim

C2b's claim kind 6, `lane`: one lane found in a camera frame by a lane model on the Compute side, made into a
claim of its own and judged by the QNX guest's monitor against the vehicle's own speed carried in the same claim.
Each port's monitor is a process of its own and shares no state with another, so the vehicle values ride in the
claim's own bytes. The monitor is advisory: a reject is a console line and a reply, never a steer, a brake or a
stop, and no claim feeds back into Autoware.

| file | what it is |
|---|---|
| `laneframe.py` | The kind 6 frame inside the repo's 64-byte frame (`ipc-test/common/frame.h`): its offsets and flags, the reasons and their order, the profile table `PROFILES` (the mirror of monitor.c's `LANE_PROFILE_TABLE`) and `table_errors` (the twin of the monitor's startup self-check), `encode` (an honest claim), `pack_bits` (each slot's exact binary32 bits, for injection), `layout_errors`, `decode_request` and `decode_reply` (every layout fault refused). |
| `lanerules.py` | The Python reference judge of the rules below (`judge(frame)`, first failure wins), with the same sin polynomial as monitor.c's. The oracle the C monitor is compared with; a client never needs it. |
| `laneclient.py` | The kind 6 claim's client: reads a file of lane estimates (JSON Lines) and sends one claim per estimate, packed by `encode`, to a monitor on loopback or an RFC 1918 address, on kind 2's connection rules, and logs every reply in `replies.jsonl`; `check` prints what would be sent. The section "The client" below says more. |

Standard library only; nothing here imports another `sdv/` package. The monitor side is `monitor.c` built with
`MONITOR_EXT_KINDS=0x50` (vss and lane) or `0x54` (ctl and lane): kind 6 (mask bit 0x40) reuses kind 4's helpers,
so it is only ever built with 0x10. `orin-native/gpu-concurrency/build-monitor-native.sh` builds either for the PC.
The guest's build is `make lane` (0x54), whose binary `ipc-test/qnx-safety-monitor/ifs-lane.build` stages to serve
kind 6 on :7170 `svc 500` and :7171 `stamp`; `make lane` refuses a generation without kind 4's profile 5, which WP3c F-c
compiled. The build file stages the binary produced by `make lane`.

## The frame

Kind 6 owns p[0..5] and p[25..47], 29 bytes; p[6..7] are the monitor's verdict and reason, p[8..23] zero in a
request, p[24] the kind. Little-endian, f32 binary32, LEFT positive.

| bytes | field |
|---|---|
| p[0] | flags: b0 LANE (a lane found: both boundaries), b1 VEH (vehicle values present); b2..b7 zero |
| p[1] | confidence, 0..100 |
| p[2..5] | f32 offset of the vehicle's centre from the lane centre, m |
| p[25..28] | f32 heading of the vehicle relative to the lane, rad |
| p[29..32] | f32 lane curvature ahead, 1/m |
| p[33..36] | f32 lane width, m |
| p[37..40] | f32 vehicle speed at the frame, m/s |
| p[41..44] | f32 vehicle yaw rate at the frame, rad/s (judged only for finiteness) |
| p[45..46] | u16 the claim's age against the frame's time, ms, saturating (carried, not judged) |
| p[47] | profile id |

With LANE clear, p[1..5] and p[25..36] are all zero bytes (a "no lane" claim); with VEH clear, p[37..44] are.
-0.0 is not zero bytes.

## The rules

Stateless; the first failure wins; every comparison strict, so a value exactly at a limit is accepted.

1. **10 flags-invalid**: a flag bit b2..b7, a byte of p[8..23], or a byte of a slot the flags say is absent.
2. **9 field-not-finite**: a present f32 that is an infinity or a NaN.
3. **8 profile-unbound**: p[47] names no profile of the table.
4. LANE clear: accepted, a "no lane" claim.
5. **28 lane-conf-low**: the confidence under the profile's minimum, or over 100.
6. **29 lane-implausible**: the width outside the profile's window, or |curvature| or |heading| over its limit.
7. **30 lane-departure**: |offset| over half the width less half the vehicle's width.
8. **31 lane-departure-imminent**: VEH set, the speed over the profile's minimum, the vehicle moving toward the
   nearer line, and the time to reach it (the free margin over speed times the sine of the heading) under the
   profile's minimum, judged as a multiplication. The sine is the odd Taylor polynomial to x^9, the same in C and
   Python; rule 29 keeps |heading| inside its domain.

Profile 1, the only one, holds design values from road design ranges and the CARLA taxi: confidence at least 50,
width 2.5 to 4.5 m, |curvature| at most 0.1 1/m, |heading| at most 0.5 rad, half the vehicle's width 0.95 m, rule
31 judged over 1 m/s with a least time to the line of one second. They were not fitted to any run. They live in
monitor.c's `LANE_PROFILE_TABLE`, mirrored by `laneframe.PROFILES`; the tests hold the two equal.

## The client

`laneclient.py` (standard library only) turns a file of lane estimates into kind 6 claims, one per estimate, and logs
the monitor's reply to each. It runs no model: a lane model writes the file elsewhere.

    python laneclient.py run --estimates FILE --port N [--host 127.0.0.1] [--profile 1] --out replies.jsonl
                             [--reply-timeout-ms 500] [--expect-judge]
    python laneclient.py check --estimates FILE

- **What it reads.** JSON Lines in time order, one estimate per camera frame: `t_ms`, `lane_found`, `conf` (0..100),
  the lane's `offset_m`, `heading_rad`, `curvature_1pm` and `lane_width_m` (with a lane; absent or null without),
  `v_mps` and `yaw_rps` (both numbers, or both null), `age_ms`. A line that does not parse, a key missing, unknown or
  given twice, a field of the wrong type or range, a value binary32 cannot carry, or a `t_ms` below the line before it
  refuses the whole file before any connection, and the message names the line. A value outside the profile's limits
  is sent: the monitor judges it.
- **What it sends.** One frame per estimate by `laneframe.encode`: seq from 1, the tstamp the client's monotonic clock
  at packing, LANE exactly when `lane_found`, VEH exactly when the vehicle values are numbers, the age saturated at
  u16. Each estimate is packed at its `t_ms` after the first one's. The target is loopback by default; `--host` takes
  only an IPv4 literal in 127.0.0.0/8 or RFC 1918 (the bridged guest), and no name. The connection follows kind 2's
  client (`sdv/ctl/ctlclient.py`): connect at the first frame, reconnect lazily with back-off, a peer-closed check
  before each send, one request outstanding, a 1-deep queue whose replaced frame is a drop, and the reply timeout,
  after which the frame is lost and the connection closed. At the end it makes no new connection, but lets one in
  progress complete, so a file's last estimate is not a drop for its connect alone.
- **What it logs.** `replies.jsonl`, never overwritten and never inside a git work tree: a header (the estimates
  file's sha256, the port, the profile, the reply timeout), one line per frame (seq, `t_ms`, the outcome, the verdict,
  the reason and its name, the reply's layout check by `laneframe.decode_reply`, the frame) and a summary (the
  counters, verdicts by reason, and `packed = replied + drop + lost_on_reconnect`). A reply that fails the check, or
  carries another seq, is not taken: its frame is lost and the connection closed. So the client takes only a reply with
  nothing but p[6] and p[7] written, as a monitor's plain TCP mode (`PORT`) and its svc mode (`PORT svc`) reply, and a
  stamp port (`PORT stamp`, as `ifs-lane.build`'s :7171) is no target: the stamp mode, the one mode that writes more,
  puts t_in and t_out at p[8..23] in every reply, so each is `reply_invalid` and its frame logged as lost (without
  `--expect-judge` such a run still exits 0, as the identity holds).
- **`check`** prints what a run would send, frame by frame, and connects nowhere. **`--expect-judge`** is for tests:
  each reply is compared with `lanerules.judge` of its frame, and each difference is counted and named in the summary
  (the exit code is then 1, as it is when no reply came and nothing was compared). The client imports `lanerules` only
  for it.

What the client does not show: that the estimates are true or a lane model good (it takes the file as written); any
timing (the tstamp is the client's own clock, and nothing it logs is a measurement); that the monitor is in any
control loop (it judges claims beside the vehicle and never steers, brakes or stops it); anything about the guest
beyond its replies. Its tests are `tests/test_sdv_laneclient.py` (a fake monitor written in the test) and
`tests/test_sdv_laneclient_contract.py` (the native 0x50 build serving `PORT svc 300`).

## The live source

`python laneclient.py run --estimates - --port N ... --out replies.jsonl` reads the estimates from stdin, as a producer
writes them, instead of from a file.

- **What a line must be.** Each line is held to the file's rules (the same keys, types, ranges and binary32 check), its
  `t_ms` to the line before it, and it must end in a newline and be at most 4096 bytes with it.
- **When it is sent.** Each estimate is packed and offered when its line is complete, and sent then unless a frame is
  outstanding (the queue rules above). Nothing is paced by `t_ms`, which is the file mode's pacing. While a line is awaited the client still serves its connection, with one select over
  stdin and the socket, so a reply or a close is taken while the producer is silent.
- **Where it ends.** The first bad line ends the source: nothing after it is read or packed, the run ends as at EOF
  (the drain), the summary names the line and why, and the exit code is 1. Exit 2 stays a refusal before any
  connection and any file. EOF ends the source too: a tail without a newline is a bad line, and a stream with no line
  holds no estimate, as an empty file does (exit 1).
- **What it logs.** The header says the source is stdin, with no sha256 and no count. The summary adds the sha256 of
  the lines taken (each with its newline) and their count, the refused line not among them, and
  `packed = replied + drop + lost_on_reconnect` holds as in the file mode.
- **A slow producer.** A monitor in svc mode closes a connection that brings no frame within its deadline, so a
  producer slower than that makes the client reconnect at each line, by the same rules, and each reconnect is counted.
- **Where it runs.** POSIX only: on Windows `-` refuses with exit 2. `check --estimates -` refuses because `check`
  reads a file. A file named `-` is reached as `./-`.

Its tests are `tests/test_sdv_laneclient.py` (an os.pipe producer and the fake monitor) and
`tests/test_sdv_laneclient_contract.py` (a producer subprocess into the native 0x50 and 0x54 builds serving
`PORT svc 500`). What the live source does not show: any timing, and whether a producer's estimates are true.

## What this does not demonstrate

- That a lane model finds lanes well: nothing here runs a model, a camera or CARLA, and the rules check a claim's
  plausibility, not its truth.
- A lane-keeping or lane-departure function: the monitor judges claims beside the vehicle, never in its control
  loop, and its limits are not a validated warning.
- Guest operation: `make lane` and `ifs-lane.build` define the guest build and its ports. The native tests use gcc
  for the PC; they do not build, boot or serve the guest image.
- Any real-time property or timing, any isolation, and any safety or certification claim.
