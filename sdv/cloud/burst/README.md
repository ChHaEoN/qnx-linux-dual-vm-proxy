# sdv/cloud/burst: the breaker's burst tool (test only)

SDV Phase 4, the minimal cloud twin, the burst-tool contract. This directory is the
account side's one test instrument: the program built to send more than the breaker's thresholds, for the
breaker's three bounded bursts, run by hand on the owner's go and never by anything else.

## What it is

`burst.py` is the breaker's burst tool: the one program of this project built to send MORE than the
breaker's thresholds, past the connector's limiter. Three files:

- `burst.py`: the tool.
- `burst_link.py`: its link: the connector's own uplink, `sdv/connector/uplink_aws.py` (`AwsUplink`), taken
  whole and given the one thing a burst needs and the connector must never have: a hand-over that does not
  wait for its answer (`begin()`, `reopen()`, `give_up()`). No SDK module is imported here; the connector's
  module stays the one place where it is.
- `Dockerfile`: its own image.

It is run only on the owner's go (A4 item 4), by hand, and at the local test broker. It is a TEST
INSTRUMENT: the connector's image later runs on the Orin with the device directory mounted, and a second
entry point there that goes past the limiter would be the switch the limiter exists to prevent.

### The two command lines

```
python /app/burst.py run --kind count|bytes|shadow --thresholds FILE --thresholds-sha256 HEX
    --state DIR --log FILE [--derive FILE]
python /app/burst.py check --thresholds FILE [--thresholds-sha256 HEX] [--derive FILE]
```

- `run` ONE burst of one kind, on a connection opened before it, and then a trickle until the time ceiling
  or a signal. `--thresholds-sha256` is the sha256 of the file the account's alarms were rendered from, as
  `twinctl status` prints it (64 hexadecimal digits, lower case): a file that is not that one is refused
  (decision 6).
- `check` reads the thresholds file as `run` does, for all three kinds, and says whether it is taken; with
  `--thresholds-sha256` it is held to that hash as well, without it to no hash. No connection, no ledger, no
  log.

The names and the settings come from the environment, as the connector's do (the device directory's
environment file): `SDV_TWIN_THING` and `SDV_TWIN_RULE`, which `topics.py` checks, and `SDV_TWIN_ENDPOINT`
with the three files, which are `uplink_aws.py`'s to read. The command line takes a kind, paths and the one
hash, and nothing else: no topic, no count, no size, no endpoint; and no value of the environment moves a
ceiling or a wait. NO SEAM: the tests give the tool their link and their clock as Python arguments, which no
command line and no variable reaches.

Exit status: 0 the burst met its goal inside its 60 s (the run then ended at its time ceiling or by a
signal), or `check` took the file; 1 refused before any connection, by a name (a signal that came before the
claim is one: `stopped-before-start`); 2 the command line cannot be read (a request for help and an option
that is not written out are such lines, and so is a hash that is not 64 hexadecimal digits in lower case:
the refusal's one line names the two command lines, and is all the help there is); 3 the first connection
could not be opened; 4 the burst did not meet its goal; 5 an error no check names, in a run or before one
(said by its class, never by its text); 6 the watchdog.

### The three kinds

- `count`: small publishes on the rule's Basic Ingest topic.
- `bytes`: large publishes on the same topic.
- `shadow`: updates of the `vss` shadow, the one the connector reports to.

Each burst is MORE THAN TWICE its threshold, handed over inside 60 s, so that however a period boundary
splits it, one 5-minute sum is over the threshold. A burst is paced evenly over 40 s; a hand-over that would
come 60 s or more after the burst's start is not made. Its sizes are the thresholds file's own `burst`
object (derive.py wrote it); none is a constant of the tool. Afterwards, every 10 s, one small attempt, the
two topics in turn.

### The hard ceilings (the burst-tool contract; design values, in the code and nowhere else)

- a burst: 2,000 publishes, 8 MiB, 60 shadow updates, whatever the file says;
- a run: 20 minutes from its start (the moment its claim was made, before the first connection is asked
  for);
- the trickle: one attempt every 10 s, so fewer than 120 in a run, 60 on a topic at the most, each small.

A file whose doubled threshold is over a burst ceiling is refused before any connection, whichever kind was
asked for; so is one whose burst is not more than twice its threshold, or whose own ceilings, window or
factor are not these. The run counts for itself as well: a plan that asked for more would be cut off at the
ceiling.

**The 20 minutes.** No hand-over is made and no connection is asked for at or after start + 20 minutes: the
clock is read right before each, in the burst and in the trickle. No connection is asked for in the last
10 s before the ceiling either (the connector's wait for a connection's answer, which is the longest the
link takes over one): its answer could come after the ceiling. Such an attempt of the trickle is logged all
the same, with `connect: ceiling`. A connection that opens at or after the ceiling all the same (a link that
took longer than its wait) is logged as opened, is handed nothing (`refused`), and is closed as the run ends
there. What can still come after the 20 minutes: the wait for the answer to a hand-over made before them
(7 s), the link's close, the last lines.

**The trickle's count.** The tick bounds it: the first attempt comes 10 s after the burst's end and none at
the ceiling, so a run has 119 attempts of the trickle at the most and asks for fewer connections still. The
run counts both as well, 120 of each: a second net behind the tick, as the burst's own counters stand behind
the file's check. No run as built reaches it, so the two words it has in the log (`ceiling trickle`,
`ceiling connects`) are never written; they would say that the pacing itself had failed.

**The trickle stays under every threshold.** One attempt every 10 s, the two topics in turn, is at the most
16 on a topic and 31 on both in any 300 s, the alarms' period read as a closed window (the connector's
limiter reads it so). A file is refused before any connection, whichever kind was asked for
(`trickle-over-threshold:count|bytes|shadow`), when its shadow threshold is not more than 16, when one of
its four count thresholds is not more than 31 (a shadow update is a publish as well), or when its bytes
threshold is not more than 16 of the trickle's publishes: an alarm acts AT its threshold, and a trickle at
or over one would move that alarm by itself, in a count or a bytes run the shadow alarm's. derive.py holds a
threshold above what the connector's limiter lets one process send, which on the shadow topics is fewer than
this trickle; so the tool holds its own rate here.

WHAT ONE RUN CAN ATTEMPT AT THE MOST is therefore a burst's ceiling AND the trickle. A count or a bytes run:
up to 2,060 publishes on the rule's topic (the burst's 2,000 and the trickle's 60) and up to 60 shadow
updates, 2,120 MQTT publishes in all; a shadow run: up to 60 publishes on the rule's topic and 120 shadow
updates. These are the counters' bounds, 60 attempts on each topic; the tick bounds a run a little under
them (119 attempts of the trickle at the most, 60 on the rule's topic and 59 on the shadow's). A burst's
bytes stay under 8 MiB and the trickle's publishes are small. Gap y's "60 shadow updates" is held for the
burst; the trickle's 60 come on top over the 20 minutes, because a trickle that had to fit under the same 60
would stop trying on the shadow topic a minute after a shadow burst, and the zero it is there to give a
meaning to would have none. The trickle's own bound on top of gap y's is this package's decision, and the
owner confirmed it as it stands (the A4 answers of 2026-10-16, question 4: no further bound).

### The eight decisions (each has its test in `tests/test_sdv_burst.py`)

1. **The ceilings count what was attempted.** A hand-over is counted before it is made, whatever becomes of
   it. One payload is handed over once: what failed, or got no word, is logged as that and is never tried
   again.
2. **Time is the monotonic clock's.** The wall clock is written into the log and decides nothing. A burst is
   paced evenly over 40 s; a hand-over that would come 60 s or more after the burst's start is not made: the
   burst ends there as `window-over`, the log says so and the exit status is the burst's. THE WATCHDOG, a
   thread of the tool's own, reads the SAME clock once a second and ends the process 30 s after the time
   ceiling, whatever a call is waiting for (exit status 6). It waits between its looks on the interpreter's
   own timer, which counts awake time: a host that slept inside a call that never came back is seen at the
   first look after it woke, so the process ends within a second of awake time and not later by the time
   slept. Its `stopped` line is written by a thread of its own and waited for 1 s at the most: a log that
   cannot be written then (its lock held by a write that does not return, a file system that has stalled)
   keeps the process from ending no longer than that, and gets no last line; the exit status says it.
3. **After its connection is cut it keeps trying until the time ceiling, and hands over nothing.** A cut
   ends a burst at once, and no hand-over is ever made to a connection that is not up. The trickle goes on,
   because A4 reads a metric's zero only for periods in which the log shows the trickle still trying on both
   topics (gap z). Each attempt after a cut asks for one new connection when the link's own back-off allows
   it, and not in the run's last 10 s (above).
4. **One run at a time, and no fresh allowance for starting again.** A start writes a claim into
   `<state>/burst-ledger.jsonl` and reads the file back: when an earlier claim is less than 20 minutes old,
   the start is refused, whoever asks, whether that run still lives and whatever the wall clock says. The
   claim is made after every other check and right before the connection, so a first connection that cannot
   be opened (exit 3) holds the window all the same: the next start comes 20 minutes later. Among those
   checks: the state directory with its ledger, and the directory the log is written in, can be written by
   this user (`state-unwritable`, `log-unwritable`); the system is asked and nothing is tried, so a start
   that could not write its log claims no window.
5. **It never restores, and it touches two topics.** No call here enables, attaches or activates anything;
   the tool publishes, and subscribes to nothing. The two topics are `topics.py`'s own (`Topics.telemetry`,
   `Topics.vss_update`), built from a thing's and a rule's name that `topics.py` checked.
6. **The file is held to derive.py's own reading at every load,** by derive.py's own `--check`, run as
   twinctl runs it. No count of the file is printed, logged or returned: a refusal names what is wrong and
   never a number of the file, and a burst's end is `met` yes or no with a ratio to two places.
   AND IT IS HELD TO THE FILE THE ALARMS WERE MADE FROM, BY ITS SHA256. derive.py's check passes every file
   that is what derive.py derives for the design the file ITSELF names: a file of another design (other
   shares, another month), or one left over from before a derivation was made again, passes it as well, and a
   burst sized on it can be under the threshold the account's alarm stands on while this log says that the
   burst met its goal. So `run` takes the sha256 of the file the alarms were rendered from (`twinctl status`
   prints it beside the alarms' lines; the run plan copies it from there) and refuses a file whose bytes do
   not have it (`thresholds-not-the-alarms`), before derive.py is run and before anything is opened. The
   bytes that were hashed are the bytes the plan is read from. NOT HELD BY IT: that the alarms in the account
   still are that file's (`twinctl status` says `as rendered`, or how they differ, when it prints the hash),
   and a hash that was copied from somewhere else. The hash is not written into the log: whether a log may
   hold it is the owner's to say.
7. **The log's form is an interface** (below).
8. **SIGINT and SIGTERM stop it at once:** nothing is handed over after the handler ran, mid-burst too, no
   last wait is made for answers still outstanding (they are logged `no-word`), and the last line says which
   signal. A connection that is being opened when the signal comes is still waited for, and is handed
   nothing: the stop is read again right before the hand-over.
   THE HANDLERS COME FIRST: main() installs both before it reads its command line and before every check. In
   its image the tool is PID 1 of its container, and for the first process of a PID namespace the kernel
   drops a signal whose handling is the default one: with the handlers installed only where the run begins, a
   SIGTERM that came during the checks (derive.py's own check is a process of its own and can take long) was
   not delivered at all, and the run went on to claim its window and to connect. A signal that comes BEFORE
   THE CLAIM ends the start as a refusal by a name, `stopped-before-start` (exit status 1), which says which
   signal: nothing was claimed, nothing was opened, nothing is sent; derive.py's check is not waited for (it
   is looked at five times a second and ended). BEFORE THE CLAIM is: before the tool's last look at the
   stop, which stands right ahead of the claim. A signal that comes after that look finds a run, and its
   window is held. THE STOP IS READ ONCE MORE RIGHT BEFORE THE FIRST CONNECTION IS ASKED FOR: a signal that
   landed inside the claim itself, or between the claim and that look, ends the run there. No connection is
   asked for; the log holds `start` and `stopped` (why `signal`) and nothing between them; the exit status
   is 4, a burst that was not met; and the next start inside the 20 minutes is refused as `window-held`. A
   signal that comes later still stops the run as above: a first connection that is being opened is waited
   for, and is handed nothing. NOT HELD: a signal in the first moments of the process, before
   the interpreter has reached main(): as PID 1 the tool never sees it. `docker run --init` puts a first
   process in front of the tool that passes signals on, so that one which comes that early ends the tool by
   the default handling; that is the run plan's to add, a second net. A4's run plan adds it (the owner's A4
   answers of 2026-10-16, question 3): PID 1 is then docker-init, which passes SIGINT and SIGTERM on, and the
   tool is its child.

### The log

JSON lines in the file `--log` names (outside every work tree; a file of an earlier run is refused), one
line per event and per attempt, each written and flushed before the next thing is done. An attempt is logged
BEFORE it is made and again with what became of it. Two ends leave attempt lines WITHOUT an outcome:
`stopped` with why `error` and with why `watchdog`. Such a run did not end by itself: the hand-overs then
without an answer, and the attempt an error came in, get no outcome line, because the tool does not know
what became of them. A reader counts each as possibly on the wire. A log whose last line is no `stopped`
line is a run that was killed from outside (SIGKILL, a signal the tool does not handle such as SIGHUP, the
host's end), or one the watchdog ended while its log could not be written (exit status 6): its attempts
without an outcome count the same way, and its window is held all the same. At every other end each attempt
has exactly one outcome.

```
every line      v (1), event, t_mono (seconds since the run's start on the monotonic clock, strictly
                increasing), t_wall (UTC, to the millisecond; information only)
start           kind, ceilings {publishes, bytes, shadow_updates, minutes}, window_s, trickle_s
connected       connection (1 for the first, 2 for the next the tool opened, ...)
connect-failed  connection, why (refused)
burst-start     kind
attempt         phase (burst | trickle), path (ingest | shadow)
outcome         of (the t_mono of its attempt line), phase, path, result; and connect, ONLY for a trickle
                attempt that found no connection and so looked for one (where none was looked for the key
                is not there: it is never null)
                  result   acked     the broker acknowledged it
                           failed    handed over; the SDK failed it (a time-out, a loss while it was in
                                     flight)
                           no-word   handed over; nothing was said of it in time (the connection is then
                                     given up), or the run was stopped first
                           refused   NOT handed over: no connection was up, or the time ceiling or a signal
                                     had come while one was being opened
                  connect  opened      asked for, and opened (its `connected` line stands before the
                                       outcome). With result `refused` it was lost again before the
                                       hand-over (its `cut` line stands between the two), or the time
                                       ceiling or a signal had come
                           refused     asked for, and not opened (its `connect-failed` line stands before
                                       it); also written for an answer of the link's that is none of
                                       these words: not opened, as far as the tool can say, and counted
                                       as asked for
                           held        not asked for: the link's own back-off
                           unanswered  not asked for: the SDK has not answered the connect before this one
                           ceiling     not asked for: its answer could come at or after the time ceiling
                                       (the run's last 10 s); or, with a `ceiling connects` line before the
                                       outcome, the second net
cut             connection: the connection in use was lost, as the tool noticed it. Once for a connection:
                before the attempt that found it lost, or, for one that was opened in an attempt of the
                trickle and lost before that attempt's hand-over, right after its `connected` line. The
                tool looks before every attempt; a loss after a run's last look is not seen and has no line
burst-end       kind, met, inside_window, why (complete | failed | window-over | cut | ceiling | signal),
                ratio (acknowledged over asked for, to two places, rounded down), span_s (first to last
                hand-over)
ceiling         which (publishes | bytes | shadow_updates | minutes | trickle | connects); `trickle` and
                `connects` are the second net's, which no run as built writes (the hard ceilings).
                `minutes` is written once in a run, by whichever reached the time ceiling: the burst (the
                trickle that follows makes no attempt and writes no second line) or the trickle
stopped         why (time-ceiling | signal | no-connection | watchdog | error), signal, burst_met, exit
                With why `signal` right after `start`, no line between the two: the signal came before the
                first connection was asked for, and none was (decision 8)
```

No line holds the endpoint, the thing, the rule, a topic or a path: the two topics are `ingest` and
`shadow`. The number of a burst's `attempt` lines IS its size, though: a log of a run is kept where the
thresholds file is kept, outside every work tree.

WHAT `failed` AND `no-word` DO NOT SAY. Both say what the tool was told, never what the far end read. A
hand-over was written to the connection before its answer was waited for: a far end that only stalled
reads it when it goes on, late and once (the connector's opt-in broker tests hold that for a publish that
timed out at a paused broker), while one handed to a connection that is lost meanwhile does not arrive. So
the far end's count of a burst lies between the log's acked and its handed-over attempts, and `met` false
with why `failed` does not say that the far end received less than the burst: an alarm can act on a burst
this log calls not met.

A `cut` FOLLOWED BY `connected` IS ALSO WHAT A SECOND CLIENT LOOKS LIKE. A far end keeps one connection for
a client id. A connector that still runs under the thing's name, or one that is stopped while the tool runs
and sends its last document on a new connection, takes the id, and the tool's connection is closed: the
tool's log then holds `cut`, and `connected` 2, 3 and so on where the two take the id in turn. The log
cannot tell that from a breaker that did not hold, and the connector's own log says nothing when it loses
the id. So that the connector is stopped first is a CHECK before each start, and not a sentence (the run
section, below). In the trickle a `cut` line is written at the tool's next look, so the time of a cut reads
to one tick, 10 s.

A PROCESS THAT WAS FROZEN AND RELEASED READS AS A GAP. A `ceiling minutes` line (the `ceiling` event, which
`minutes`) whose t_mono is later than 1,200 s by more than a moment says that the process did not run
meanwhile, and the stretch without lines before it is a stretch in which nothing tried: a reader who counts
a metric's zero for periods in which the trickle tried leaves that stretch out. The run's own look at the
clock ends such a run with its burst's status.

THE LEDGER IS NOT THE LOG. A claim's line of `<state>/burst-ledger.jsonl` holds the claim's own id, its kind,
its monotonic and its wall time, and the host's boot id, a UUID that the leak scanner flags. It is state: it
stays in the state directory and goes into no capture and no record.

### What it sends

On the Basic Ingest topic: a JSON object `{"v": 0, "burst": <kind>, "pad": "x..."}` of exactly the size the
file gives (64 bytes in the trickle). `v: 0` marks test traffic; the connector sends `v: 1` and queries
filter on it. The rule passes the object on as it passes a batch, so a
burst leaves records in the bucket, and they say that they are no telemetry. On the shadow topic:
`{"state":{"reported":{"burst":null}}}`, which names one key as null: a key that is not there is deleted, so
the document adds no key and changes no value of the twin's. Both are first seen in the account (A4).

### The image

```
python3 sdv/connector/build_image.py build --burst [--smoke] [--out FILE]
```

Tag `sdv-local/twin-burst:test-only`: six files in `/app` (the tool's two and the four modules of the
connector they import by name: `limits.py`, `topics.py`, `uplink.py`, `uplink_aws.py`), the same base by the
same index digest and the same x86_64 lock as the connector's image, hash-checked, in a context of its own
outside the repo. `--burst` refuses `--write-pins`, `--arch arm64|all`, `--gen` and `--frozen` (exit status
2), and a Dockerfile on another base than the connector's. The connector's image holds no file of this
directory.

### How a run is started in a container

The PC runs the image by the ID its build printed, on the owner's go, with:

- the device directory read-only at `/run/sdv-local/device`, and its environment file as `--env-file`; the
  environment file given is the device directory's own and names no other certificate, key or CA path; the
  three default to the mounted device directory;
- the thresholds directory read-only, with derive.py beside the thresholds file, and on the command line
  the sha256 that `twinctl status` printed for that file (`--thresholds-sha256`); in the same output the
  alarms' steps read `as rendered` when the account's alarms are that file's;
- one state directory and a log directory, read-write for the user the container runs as (the image's own
  is uid 10001; the opt-in tests run it under the caller's, with `--user`): a directory that user cannot
  write is refused as `state-unwritable` or `log-unwritable`, before the window is claimed;
- an internal network, with the local test broker as the far end.

In a container derive.py needs what it reads at the places it looks for them (the cost model, the
connector's `limits.py`): the run plan mounts them (three read-only mounts), and a check that cannot run
refuses. THE THREE MOUNTS GO WHERE derive.py'S OWN DEFAULTS LOOK FOR THEM, relative to its own directory,
which is the thresholds directory: the cost model's directory (`cost_model.py` and `prices.json`)
and the connector's `limits.py`. derive.py and its defaults live beside the thresholds file,
outside every work tree, and so do the run plan's three `--mount type=bind,...,readonly` lines.
The thresholds directory is mounted at `/run/sdv-local/thresholds` (where the opt-in tests put it).

The `limits.py` mounted is the one the image was built from. With one of the three missing, `check` and
`run` refuse (`thresholds-check-failed`).

THE STATE DIRECTORY AND ITS LEDGER NEVER GO INTO A CAPTURE OR A RECORD (the owner's A4 answers of 2026-10-16,
question 9): the ledger holds the host's kernel boot id, which the leak scan flags as a uuid. Nor does a run's
log (question 8): it stays beside the thresholds file, and a record holds a burst's outcomes only.

The run plan gives the tool one state directory, and stops the connector first: both connect under
the thing's name, and a far end keeps one connection for a client id. STOPPED IS A CHECK, of an exited
container: before each start of the tool `docker inspect -f '{{.State.Running}}'` of the connector says
`false`, or names no such container, and the connector's log ends with its `stop` line; and no connector is
started again before the tool's `stopped` line.

Without `--init` the tool is PID 1 of its container; A4's run plan starts it with `--init` (the owner's A4
answers of 2026-10-16), so PID 1 is docker-init and the tool its child. The tool installs its two signal
handlers before anything else (decision 8),
so a `docker kill -s TERM` or a `docker stop` reaches it from main() on: before the claim it ends as the
refusal `stopped-before-start`, afterwards as a run that was stopped (one that the signal met before its
first connection was asked for has asked for none). What it cannot see is a signal in the
first moments of the process, before the interpreter has reached main(). `docker run --init` is the second
net for that, and is the run plan's to add: nothing here starts the container.

A GO IS WITHDRAWN WITH `docker stop -t 20`, or with `docker kill -s TERM` and a wait for the container's exit,
and never with a bare `docker stop`. A bare one gives the tool 10 s before its KILL, and the tool's own waits
are longer: a first connection that is being opened at a far end that accepts and says nothing is waited for
as long as the connector's wait for a connection's answer (10 s), and the link's close takes up to 2 s more.
The tool can then end by itself only a moment before the KILL, or not before it; and a KILL leaves a log with
no `stopped` line and a held window.

### The tests

- `tests/test_sdv_burst.py`: CI, on fakes; no test in it skips.
- `tests/test_sdv_burst_broker.py`: opt-in, at the pinned local test broker, in the tool's own image.
- The image's own test, and what holds the tool out of the connector (the staged list, the import graph, the
  pins), are in `tests/test_sdv_connector.py`.

The opt-in tests' broker takes a packet of 131,072 bytes at the most (`max_packet_size`), which is less
than the tool's largest publish, 128 KiB of payload, with its header: no opt-in test sends a publish of that
size, so the tool's largest publish has not met that broker. The service's own page (AWS IoT Core endpoints
and quotas, https://docs.aws.amazon.com/general/latest/gr/iot-core.html, read 2026-10-16) gives the limit as
the PAYLOAD's: 'MQTT payload size', 128 KB, not adjustable, publishes and connects above it rejected; and
beside it a whole MQTT5 packet of 146 KB. The page does not say whether its KB is 1,000 or 1,024 bytes. The
tool's ceiling alone does not settle which reading a service uses; the thresholds document remains outside
every work tree.

The opt-in tests run after `build --burst`, as:

```
SDV_BURST_BROKER=1 ~/civenv/bin/python -m pytest -q -o addopts= tests/test_sdv_burst_broker.py
```

## What it is not

- **Not a module of the connector.** No connector module imports it, and the connector's image holds no file
  of it.
- **Not part of any pin or deploy set.** Its image is never pinned in `sdv/stack/images.json`, is in no
  deploy set or bundle, is never built for arm64 and is never pushed.
- **Not a restore.** It never restores, and it subscribes to nothing.
- **Not for the Orin.**
- **Not held: another state directory, a ledger that was deleted, another host.** The ledger of starts
  covers one state directory; the run plan gives the tool one. Nor a write that fails where the system had
  said it could be made (a full disk): that is an error no check names (exit status 5), and when it is the
  log's, the claim was made before it.

Does not demonstrate: anything about the cloud service. Not that it accepts or counts the shadow document
above, what the rule makes of the filler, or what any metric counts (all first seen in the account, A4); not
its quotas (the pace and the publishes in flight are design values written from memory of them; the 128 KiB is
the payload's by the service's page, read 2026-10-16); not that a burst trips an alarm or that a breaker cuts;
not what a connection the service refuses costs or leaves in its log (a run asks for fewer than 120 after a
cut); not the wire time of a hand-over (the SDK writes what the socket takes); not the SDK's behaviour
(uplink_aws.py's reading of the pinned pair); not that the connector is stopped while the tool runs (both
connect under the thing's name, and a far end keeps one connection for a client id: the run plan stops the
connector first); not that the hash a run is given is the one of the file the account's alarms stand on (the
run plan copies it from `twinctl status`; the tool compares bytes with it); not a host that really slept, nor
a file system that really stalled (the watchdog is held on a clock and a stream the tests move); any timing.
