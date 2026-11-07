#!/usr/bin/env python3
"""burst.py -- the breaker's burst tool: the one program of this project built to send MORE than the breaker's
thresholds, past the connector's limiter (sdv/cloud/burst; SDV Phase 4, the burst-tool contract).

A TEST INSTRUMENT, run by hand on the owner's go and never by anything else: it is no
module of the connector, no connector module imports it, its image is its own (sdv/connector/build_image.py --burst:
never pinned, in no deploy set), and the connector's image holds no file of it. The connector's image later runs on the
Orin with the device directory mounted; a second entry point there that goes past the limiter would be the switch the
limiter exists to prevent.

    python /app/burst.py run --kind count|bytes|shadow --thresholds FILE --thresholds-sha256 HEX
        --state DIR --log FILE [--derive FILE]
    python /app/burst.py check --thresholds FILE [--thresholds-sha256 HEX] [--derive FILE]

run    ONE burst of one kind, on a connection opened before it, and then a trickle until the time ceiling or a signal.
         count   small publishes on the rule's Basic Ingest topic
         bytes   large publishes on the same topic
         shadow  updates of the `vss` shadow, the one the connector reports to
       Each burst is MORE THAN TWICE its threshold, handed over inside 60 s, so that however a period boundary splits
       it, one 5-minute sum is over the threshold. Its sizes are the thresholds file's own `burst` object (derive.py
       wrote it); none is a constant of this file. Afterwards, every 10 s, one small attempt, the two topics in turn.
       --thresholds-sha256 is the sha256 of the file the account's alarms were rendered from, as `twinctl status`
       prints it (64 hexadecimal digits, lower case): a file that is not that one is refused (decision 6).
check  Reads the thresholds file as `run` does, for all three kinds, and says whether it is taken; with
       --thresholds-sha256 it is held to that hash as well, without it to no hash. No connection, no ledger, no log.

The names and the settings come from the environment, as the connector's do (the device directory's environment
file): SDV_TWIN_THING and SDV_TWIN_RULE, which topics.py checks, and SDV_TWIN_ENDPOINT with the three files, which are
uplink_aws.py's to read. The command line takes a kind, paths and the one hash, and nothing else: no topic, no count,
no size, no endpoint; and no value of the environment moves a ceiling or a wait. NO SEAM: the tests give the tool their
link and their clock as Python arguments, which no command line and no variable reaches.

THE HARD CEILINGS (the burst-tool contract; design values, in the code and nowhere else)
    a burst    2,000 publishes, 8 MiB, 60 shadow updates          whatever the file says
    a run      20 minutes from its start (the moment its claim was made, before the first connection is asked for)
    the trickle  one attempt every 10 s, so fewer than 120 in a run, 60 on a topic at the most, each small
  A file whose doubled threshold is over a burst ceiling is refused before any connection, whichever kind was asked
  for; so is one whose burst is not more than twice its threshold, or whose own ceilings, window or factor are not
  these. The run counts for itself as well: a plan that asked for more would be cut off at the ceiling.
  THE 20 MINUTES. No hand-over is made and no connection is asked for at or after start + 20 minutes: the clock is
  read right before each, in the burst and in the trickle. No connection is asked for in the last 10 s before the
  ceiling either (the connector's wait for a connection's answer, which is the longest the link takes over one): its
  answer could come after the ceiling. Such an attempt of the trickle is logged all the same, with `connect:
  ceiling`. A connection that opens at or after the ceiling all the same (a link that took longer than its wait) is
  logged as opened, is handed nothing (`refused`), and is closed as the run ends there. What can still come after
  the 20 minutes: the wait for the answer to a hand-over made before them (7 s), the link's close, the last lines.
  THE TRICKLE'S COUNT. The tick bounds it: the first attempt comes 10 s after the burst's end and none at the ceiling,
  so a run has 119 attempts of the trickle at the most and asks for fewer connections still. The run counts both as
  well, 120 of each: a second net behind the tick, as the burst's own counters stand behind the file's check. No
  run as built reaches it, so the two words it has in the log (`ceiling trickle`, `ceiling connects`) are never
  written; they would say that the pacing itself had failed.
  THE TRICKLE STAYS UNDER EVERY THRESHOLD. One attempt every 10 s, the two topics in turn, is at the most 16 on a topic
  and 31 on both in any 300 s, the alarms' period read as a closed window (the connector's limiter reads it so). A file
  is refused before any connection, whichever kind was asked for (`trickle-over-threshold:count|bytes|shadow`), when
  its shadow threshold is not more than 16, when one of its four count thresholds is not more than 31 (a shadow update
  is a publish as well), or when its bytes threshold is not more than 16 of the trickle's publishes: an alarm acts AT
  its threshold, and a trickle at or over one would move that alarm by itself, in a count or a bytes run the shadow
  alarm's. derive.py holds a threshold above what the connector's limiter lets one process send, which on the shadow
  topics is fewer than this trickle; so the tool holds its own rate here.
  WHAT ONE RUN CAN ATTEMPT AT THE MOST is therefore a burst's ceiling AND the trickle. A count or a bytes run: up to
  2,060 publishes on the rule's topic (the burst's 2,000 and the trickle's 60) and up to 60 shadow updates, 2,120 MQTT
  publishes in all; a shadow run: up to 60 publishes on the rule's topic and 120 shadow updates. These are the counters'
  bounds, 60 attempts on each topic; the tick bounds a run a little under them (119 attempts of the trickle at the most,
  60 on the rule's topic and 59 on the shadow's). A burst's bytes stay under 8 MiB and the trickle's publishes are
  small. Gap y's "60 shadow updates" is held for the burst; the trickle's 60 come on top over the 20 minutes, because a
  trickle that had to fit under the same 60 would stop trying on the shadow topic a minute after a shadow burst, and the
  zero it is there to give a meaning to would have none.

THE DECISIONS (each has its test in tests/test_sdv_burst.py)
 1  THE CEILINGS COUNT WHAT WAS ATTEMPTED. A hand-over is counted before it is made, whatever becomes of it. One
    payload is handed over once: what failed, or got no word, is logged as that and is never tried again. QoS 1, on a
    clean session, through the connector's own settings (burst_link.py): the SDK then fails an unacknowledged publish
    after its operation time-out and does not send it again, cancels what was in flight at a loss, and is handed
    nothing on a connection the link knows to be down. What it may still queue, for a loss the link was not yet told
    of, waits for a reconnect of the SDK's own: its reconnect timer is held at an hour by those settings and a run is
    over, watchdog included, before half of that has gone, so the SDK cannot come back by itself inside a run and
    write something later. (What the SDK does with a QoS 1 publish is uplink_aws.py's reading of the pinned pair,
    seen at the local broker; it is not seen again here.)
 2  TIME IS THE MONOTONIC CLOCK'S (CLOCK_BOOTTIME where the platform has it, so a suspended host is not a longer run).
    The wall clock is written into the log and decides nothing. A burst is paced evenly over 40 s; a hand-over that
    would come 60 s or more after the burst's start is not made: the burst ends there as `window-over`, the log says
    so and the exit status is the burst's. The trickle still runs after a burst that was not met, and every line of
    the run that sums it up (`burst-end`, `stopped`) and the exit status say that it was not: it is never run on as if
    it had been. THE WATCHDOG, a thread of the tool's own, reads the SAME clock once a second and ends the process 30 s
    after the time ceiling, whatever a call is waiting for (exit status 6). It waits between its looks on the
    interpreter's own timer, which counts awake time: a host that slept inside a call that never came back is seen at
    the first look after it woke, so the process ends within a second of awake time and not later by the time slept.
    Its `stopped` line is written by a thread of its own and waited for 1 s at the most: a log that cannot be written
    then (its lock held by a write that does not return, a file system that has stalled) keeps the process from
    ending no longer than that, and gets no last line; the exit status says it.
 3  AFTER ITS CONNECTION IS CUT IT KEEPS TRYING UNTIL THE TIME CEILING, AND HANDS OVER NOTHING. The stop rule's
    "it stops when the broker goes away" is the burst's: a cut ends a burst at once, and no hand-over is ever made to a
    connection
    that is not up. The trickle goes on, because A4 reads a metric's zero only for periods in which the log shows the
    trickle still trying on both topics (gap z): a tool that had stopped would make every zero after a cut mean
    nothing. Each attempt after a cut asks for ONE new connection when the link's own back-off allows it (the
    connector's, 5 s doubling to 60 s) and is logged with what came of that (`refused`: asked and not opened; `held`:
    not asked, the back-off; `unanswered`; `opened`; `ceiling`: not asked, the run's last 10 s). Bounded by the tick:
    fewer than 120 attempts in a run, and fewer connections asked for (THE HARD CEILINGS). A connection that does open
    again is used and logged, which is what a breaker that did not hold looks like.
 4  ONE RUN AT A TIME, AND NO FRESH ALLOWANCE FOR STARTING AGAIN. A start writes a claim into <state>/burst-ledger.jsonl
    and reads the file back: when an earlier claim is less than 20 minutes old, the start is refused, whoever asks,
    whether that run still lives and whatever the wall clock says. On one boot the claims are compared on the
    monotonic clock (a container has its host's); across a boot, or where no boot is named, on the wall clock, and a
    wall clock that went back holds. A ledger that cannot be read refuses. The claim is made after every other check
    and right before the connection, so a first connection that cannot be opened (exit 3) holds the window all the
    same: the next start comes 20 minutes later. Among those checks: the state directory with its ledger, and the
    directory the log is written in, can be written by this user (`state-unwritable`, `log-unwritable`). The system is
    asked (os.access) and nothing is tried, so a start that could not write its log claims no window. WHAT THIS DOES NOT
    HOLD: another state directory, a ledger that was deleted, another host (the run plan gives the tool one state
    directory); and a write that fails where the system had said it could be made (a full disk): that is an error no
    check names (exit status 5, said by its class and never by its text, which names a path), and when it is the log's,
    the claim was made before it.
 5  IT NEVER RESTORES, AND IT TOUCHES TWO TOPICS. No call here enables, attaches or activates anything; the tool
    publishes, and subscribes to nothing. The two topics are topics.py's own (Topics.telemetry, Topics.vss_update),
    built from a thing's and a rule's name that topics.py checked.
 6  THE FILE IS HELD TO derive.py'S OWN READING AT EVERY LOAD, by derive.py's own --check, run as twinctl runs it
    (derive.py beside the file, or --derive). In a container derive.py needs what it reads at the places it looks for
    them (the cost model, the connector's limits.py): the run plan mounts them, and a check that cannot run refuses.
    AND IT IS HELD TO THE FILE THE ALARMS WERE MADE FROM, BY ITS SHA256. derive.py's check passes every file that is
    what derive.py derives for the design the file ITSELF names: a file of another design (other shares, another
    month), or one left over from before a derivation was made again, passes it as well, and a burst sized on it can be
    under the threshold the account's alarm stands on while this log says that the burst met its goal. So `run` takes
    the sha256 of the file the alarms were rendered from (`twinctl status` prints it beside the alarms' lines; the
    run plan copies it from there) and refuses a file whose bytes do not have it (`thresholds-not-the-alarms`), before
    derive.py is run and before anything is opened. The bytes that were hashed are the bytes the plan is read from.
    NOT HELD BY IT: that the alarms in the account still are that file's (`twinctl status` says `as rendered`, or
    how they differ, when it prints the hash), and a hash that was copied from somewhere else. The hash is not
    written into the log: whether a log may hold it is the owner's to say.
    NO COUNT OF THE FILE IS PRINTED, LOGGED OR RETURNED: a refusal names what is wrong and never a number of the file,
    derive.py's refusals are passed on by their names alone, and a burst's end is `met` yes or no with a ratio to two
    places. The number of a burst's `attempt` lines IS its size, though: a log of a run is kept where the thresholds
    file is kept, outside every work tree.
 7  THE LOG'S FORM IS AN INTERFACE (below).
 8  SIGINT AND SIGTERM STOP IT AT ONCE: nothing is handed over after the handler ran, mid-burst too, no last wait is
    made for answers still outstanding (they are logged `no-word`), and the last line says which signal. "At once" is
    the hand-overs': a connection that is being opened when the signal comes is still waited for (the connector's 10 s
    at the most) and the link's close for its 2 s, so the process may end that much later; nothing is sent in between
    (the stop is read again when the connection has come, right before the hand-over).
    THE HANDLERS COME FIRST: main() installs both before it reads its command line and before every check. In its
    image the tool is PID 1 of its container, and for the first process of a PID namespace the kernel drops a signal
    whose handling is the default one: with the handlers installed only where the run begins, a SIGTERM that came
    during the checks (derive.py's own check is a process of its own and can take long) was not delivered at all, and
    the run went on to claim its window and to connect. A signal that comes BEFORE THE CLAIM ends the start as a
    refusal by a name, `stopped-before-start` (exit status 1), which says which signal: nothing was claimed, nothing
    was opened, nothing is sent; derive.py's check is not waited for (it is looked at five times a second and ended).
    BEFORE THE CLAIM is: before the tool's last look at the stop, which stands right ahead of the claim. A signal that
    comes after that look finds a run, and its window is held. THE STOP IS READ ONCE MORE RIGHT BEFORE THE FIRST
    CONNECTION IS ASKED FOR: a signal that landed inside the claim itself, or between the claim and that look, ends the
    run there. No connection is asked for; the log holds `start` and `stopped` (why `signal`) and nothing between
    them; the exit status is 4, a burst that was not met; and the next start inside the 20 minutes is refused as
    `window-held`. A signal that comes later still stops the run as above: a first connection that is being opened
    is waited for, and is handed nothing.
    NOT HELD: a signal in the first moments of the process, before the interpreter has reached main(): as PID 1 the
    tool never sees it. `docker run --init` puts a first process in front of the tool that passes signals on, so that
    one which comes that early ends the tool by the default handling; that is the run plan's to add, a second net.

THE LOG: JSON lines in the file --log names (outside every work tree; a file of an earlier run is refused), one line
per event and per attempt, each written and flushed before the next thing is done. An attempt is logged BEFORE it is
made and again with what became of it. Two ends leave attempt lines WITHOUT an outcome: `stopped` with why `error`
and with why `watchdog`. Such a run did not end by itself: the hand-overs then without an answer, and the attempt
an error came in, get no outcome line, because the tool does not know what became of them. A reader counts each as
possibly on the wire. A log whose last line is no `stopped` line is a run that was killed from outside (SIGKILL, a
signal the tool does not handle such as SIGHUP, the host's end), or one the watchdog ended while its log could not
be written (exit status 6): its attempts without an outcome count the same way, and its window is held all the
same. At every other end each attempt has exactly one outcome.
  every line   v (1), event, t_mono (seconds since the run's start on the monotonic clock, strictly increasing),
               t_wall (UTC, to the millisecond; information only)
  start           kind, ceilings {publishes, bytes, shadow_updates, minutes}, window_s, trickle_s
  connected       connection (1 for the first, 2 for the next the tool opened, ...)
  connect-failed  connection, why (refused)
  burst-start     kind
  attempt         phase (burst | trickle), path (ingest | shadow)
  outcome         of (the t_mono of its attempt line), phase, path, result; and connect, ONLY for a trickle attempt
                  that found no connection and so looked for one (where none was looked for the key is not there:
                  it is never null)
                    result   acked     the broker acknowledged it
                             failed    handed over; the SDK failed it (a time-out, a loss while it was in flight)
                             no-word   handed over; nothing was said of it in time (the connection is then given
                                       up), or the run was stopped first
                             refused   NOT handed over: no connection was up, or the time ceiling or a signal had
                                       come while one was being opened
                    connect  opened      asked for, and opened (its `connected` line stands before the outcome). With
                                         result `refused` it was lost again before the hand-over (its `cut` line
                                         stands between the two), or the time ceiling or a signal had come
                             refused     asked for, and not opened (its `connect-failed` line stands before it); also
                                         written for an answer of the link's that is none of these words: not
                                         opened, as far as the tool can say, and counted as asked for
                             held        not asked for: the link's own back-off
                             unanswered  not asked for: the SDK has not answered the connect before this one
                             ceiling     not asked for: its answer could come at or after the time ceiling (the
                                         run's last 10 s); or, with a `ceiling connects` line before the outcome,
                                         the second net
  cut             connection: the connection in use was lost, as the tool noticed it. Once for a connection: before the
                  attempt that found it lost, or, for one that was opened in an attempt of the trickle and lost
                  before that attempt's hand-over, right after its `connected` line. The tool looks before every
                  attempt; a loss after a run's last look is not seen and has no line
  burst-end       kind, met, inside_window, why (complete | failed | window-over | cut | ceiling | signal), ratio
                  (acknowledged over asked for, to two places, rounded down), span_s (first to last hand-over)
  ceiling         which (publishes | bytes | shadow_updates | minutes | trickle | connects); `trickle` and `connects`
                  are the second net's, which no run as built writes (THE HARD CEILINGS). `minutes` is written once in
                  a run, by whichever reached the time ceiling: the burst (the trickle that follows makes no attempt
                  and writes no second line) or the trickle
  stopped         why (time-ceiling | signal | no-connection | watchdog | error), signal, burst_met, exit
                  With why `signal` right after `start`, no line between the two: the signal came before the first
                  connection was asked for, and none was (decision 8)
No line holds the endpoint, the thing, the rule, a topic or a path: the two topics are `ingest` and `shadow`.
WHAT `failed` AND `no-word` DO NOT SAY. Both say what the tool was told, never what the far end read. A hand-over was
written to the connection before its answer was waited for: a far end that only stalled reads it when it goes on,
late and once (the connector's opt-in broker tests hold that for a publish that timed out at a paused broker), while
one handed to a connection that is lost meanwhile does not arrive. So the far end's count of a burst lies between the
log's acked and its handed-over attempts, and `met` false with why `failed` does not say that the far end received
less than the burst: an alarm can act on a burst this log calls not met.
A `cut` FOLLOWED BY `connected` IS ALSO WHAT A SECOND CLIENT LOOKS LIKE. A far end keeps one connection for a client
id. A connector that still runs under the thing's name, or one that is stopped while the tool runs and sends its last
document on a new connection, takes the id, and the tool's connection is closed: the tool's log then holds `cut`, and
`connected` 2, 3 and so on where the two take the id in turn. The log cannot tell that from a breaker that did not
hold, and the connector's own log says nothing when it loses the id. So that the connector is stopped first is a CHECK
before each start, and not a sentence: its container reads as not running, or is not there, and its log ends with its
`stop` line; and no connector is started again before the tool's `stopped` line. In the trickle a `cut` line is
written at the tool's next look, so the time of a cut reads to one tick, 10 s.
THE LEDGER IS NOT THE LOG. A claim's line of <state>/burst-ledger.jsonl holds the claim's own id, its kind, its
monotonic and its wall time, and the host's boot id, a UUID that the leak scanner flags. It is state: it stays in the
state directory and goes into no capture and no record.

WHAT IT SENDS. On the Basic Ingest topic: a JSON object {"v": 0, "burst": <kind>, "pad": "x..."} of exactly the size
the file gives (64 bytes in the trickle). `v: 0` marks test traffic; the connector sends `v: 1` and queries filter
on it. The rule passes the object on as it passes a batch, so a burst
leaves records in the bucket, and they say that they are no telemetry. On the shadow topic: {"state": {"reported":
{"burst": null}}}, which names one key as null: a key that is not there is deleted, so the document adds no key and
changes no value of the twin's.

Exit status: 0 the burst met its goal inside its 60 s (the run then ended at its time ceiling or by a signal), or
`check` took the file; 1 refused before any connection, by a name (a signal that came before the claim is one:
`stopped-before-start`); 2 the command line cannot be read (a request for help and an option that is not written out
are such lines, and so is a hash that is not 64 hexadecimal digits in lower case: the refusal's one line names the two
command lines, and is all the help there is); 3 the first connection could not be opened; 4 the burst did not meet its
goal; 5 an error no check names, in a run or before one (said by its class, never by its text); 6 the watchdog.

Does not demonstrate: anything about the cloud service. Not that it accepts or counts the shadow document above, what
the rule makes of the filler, or what any metric counts (all first seen in the account, A4); not its quotas (the
pace, the publishes in flight and the 128 KiB a publish may have are design values written from memory of them); not
that a burst trips an alarm or that a breaker cuts; not what a connection the service refuses costs or leaves in its log
(a run asks for fewer than 120 after a cut); not the wire time of a hand-over (the SDK writes what the socket takes);
not the SDK's behaviour (uplink_aws.py's reading of the pinned pair); not that the connector is stopped while the tool
runs (both connect under the thing's name, and a far end keeps one connection for a client id: the run plan stops the
connector first); not that the hash a run is given is the one of the file the account's alarms stand on (the run plan
copies it from `twinctl status`; the tool compares bytes with it); not a host that really slept, nor a file system
that really stalled (the watchdog is held on a clock and a stream the tests move); any timing.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, NoReturn, Optional, Sequence, TextIO

HERE = Path(__file__).resolve().parent
if not (HERE / "topics.py").is_file():          # the tree. In the image the connector's four modules lie beside this file, in /app
    _CONNECTOR = HERE.parent.parent / "connector"
    if _CONNECTOR.is_dir() and str(_CONNECTOR) not in sys.path:
        sys.path.insert(0, str(_CONNECTOR))

import limits  # noqa: E402
import topics  # noqa: E402
from uplink import UplinkError  # noqa: E402

ENV_THING = "SDV_TWIN_THING"
ENV_RULE = "SDV_TWIN_RULE"

KINDS = ("count", "bytes", "shadow")
PATHS = ("ingest", "shadow")
RESULTS = ("acked", "failed", "no-word", "refused")
QOS = limits.QOS

# --- the hard ceilings and the other design values (the docstring says what each is)
CEILINGS = {"publishes": 2000, "bytes": 8 * 1024 * 1024, "shadow_updates": 60, "minutes": 20}
CEILING_S = CEILINGS["minutes"] * 60
WINDOW_S = 60                                   # a burst is handed over inside this
FACTOR = 2                                      # ... and is more than this many times its threshold
BURST_SPREAD_S = 40                             # a burst's hand-overs are paced evenly over this
TRICKLE_INTERVAL_S = 10
TRICKLE_MAX = CEILING_S // TRICKLE_INTERVAL_S   # the second net on a trickle's attempts: the tick itself allows one fewer in a run
CONNECTS_MAX = TRICKLE_MAX                      # ... and on connections asked for after the first: one a tick at the most
CONNECT_ANSWER_S = limits.CONNECT_WAIT_S        # the longest the link waits for a connection's answer (the connector's own)
TRICKLE_PUBLISH_BYTES = 64
MAX_PUBLISH_BYTES = 128 * 1024                  # the broker's message limit (from memory of the service's; derive.py holds the same)
INFLIGHT_MAX_PUBLISHES = 20                     # hand-overs not yet answered: under what the service is remembered to allow
INFLIGHT_MAX_BYTES = 512 * 1024
SETTLE_S = limits.OPERATION_TIMEOUT_S + limits.UPLINK_WAIT_MARGIN_S          # how long a hand-over may stay without a word
PERIOD_S = limits.LIMITER_WINDOW_S              # the alarms' period (derive.py refuses a file whose period is not the limiter's window)
TRICKLE_PERIOD_TOPIC = PERIOD_S // (TRICKLE_INTERVAL_S * len(PATHS)) + 1          # the trickle's attempts on ONE topic in a closed period, at most
TRICKLE_PERIOD_BOTH = PERIOD_S // TRICKLE_INTERVAL_S + 1                           # ... and on both topics together
WATCHDOG_GRACE_S = 30
WATCHDOG_LOOK_S = 1.0                           # how often the watchdog reads the run's clock
WATCHDOG_LINE_S = 1.0                           # the longest its last line is waited for: then the process is ended without it
DERIVE_WAIT_S = 600                             # the longest derive.py's own check is waited for
DERIVE_LOOK_S = 0.2                             # ... and how often the stop is looked at meanwhile
SLICE_S = 0.05                                  # the longest the loop sleeps without looking at the stop and at its answers
SHADOW_KEY = "burst"
SHADOW_DOCUMENT = json.dumps({"state": {"reported": {SHADOW_KEY: None}}}, separators=(",", ":")).encode("ascii")
TEST_TRAFFIC = 0                                # the envelope's `v` for test traffic (gap f): the connector sends 1, and queries filter on it
MIN_PUBLISH_BYTES = len(json.dumps({"v": TEST_TRAFFIC, "burst": "trickle", "pad": ""}, separators=(",", ":")))
LEDGER = "burst-ledger.jsonl"
EXIT = {"ok": 0, "refused": 1, "arguments": 2, "no-connection": 3, "burst-not-met": 4, "error": 5, "watchdog": 6}

# the thresholds file's names (derive.py's): which threshold each kind's burst is more than twice of
COUNT_METRICS = ("Firehose.IncomingRecords", "IoT.RulesExecuted.per_execution", "IoT.RulesExecuted.per_5kb_unit", "IoT.PublishIn.Success")
BYTES_METRIC = "Firehose.IncomingBytes"
SHADOW_METRIC = "IoT.UpdateThingShadow.Accepted"
DESIGN = {"window_s": WINDOW_S, "factor": FACTOR, "ceiling_publishes": CEILINGS["publishes"], "ceiling_bytes": CEILINGS["bytes"],
          "ceiling_shadow_updates": CEILINGS["shadow_updates"], "ceiling_minutes": CEILINGS["minutes"]}
BURST_KEYS = ("count_publishes", "count_publish_bytes", "bytes_publishes", "bytes_per_publish", "bytes_total", "shadow_updates")


class Refused(Exception):
    """A start that is refused before anything is opened: a name, and a sentence that holds no count of the file and no
    value of the environment."""

    def __init__(self, name: str, detail: str) -> None:
        super().__init__("%s: %s" % (name, detail))
        self.name, self.detail = name, detail


def refuse(name: str, detail: str) -> NoReturn:
    raise Refused(name, detail)


def in_a_work_tree(path: Path) -> bool:
    """Whether `path` lies in a git work tree: a `.git` (a directory, or a worktree's file) in it or above it. Looked for
    from the path as it is written AND from where it leads, its symbolic links followed: a state directory, a log or a
    thresholds file that is reached through a link into a work tree lies in one."""
    forms = [Path(os.path.abspath(str(path))), Path(os.path.realpath(str(path)))]
    return any((d / ".git").exists() for p in forms for d in [p] + list(p.parents))


def stopped_before_start(stop: Optional["Stop"]) -> None:
    """A signal that came before a run was started ends the start as a refusal by a name (decision 8)."""
    if stop is not None and stop:
        refuse("stopped-before-start", "%s came before a run was started: nothing was claimed, nothing was opened and nothing is sent" % stop.name)


# --------------------------------------------------------------------------------------------------- the plan, from the file

class Plan(NamedTuple):
    kind: str
    path: str          # ingest | shadow
    sends: int         # how many hand-overs the burst is
    size: int          # the bytes of each


def _whole(obj: Any, key: str, name: str) -> int:
    value = obj.get(key) if isinstance(obj, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        refuse("%s:%s" % (name, key), "the thresholds file holds no whole count there (one or more)")
    return value


def derive_check(path: Path, derive: Optional[Path], stop: Optional["Stop"] = None) -> None:
    """derive.py --check FILE, as twinctl runs it: the file is what derive.py derives today for the design it names. Its
    refusals are passed on by their names; what it prints after a name holds counts and is not. It is a process of its
    own and is waited for in slices: when the stop was raised meanwhile (a signal before the start) it is ended and the
    start is refused as stopped; when it has not ended after DERIVE_WAIT_S it is ended and the check counts as not run."""
    tool = derive if derive is not None else path.parent / "derive.py"
    if not tool.is_file():
        refuse("thresholds-check-unavailable", "derive.py is not beside the thresholds file (or where --derive says): its own check "
               "cannot be run, so nothing is sent")
    stopped_before_start(stop)
    argv = [sys.executable, "-B", str(tool), "--check", str(path)]
    try:
        child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    except OSError:
        refuse("thresholds-check-unavailable", "derive.py could not be run")
    until = time.monotonic() + DERIVE_WAIT_S
    try:
        while True:
            try:
                out, err = child.communicate(timeout=DERIVE_LOOK_S)
                break
            except subprocess.TimeoutExpired:
                if (stop is not None and stop) or time.monotonic() >= until:
                    child.kill()
                    child.communicate()
                    stopped_before_start(stop)
                    refuse("thresholds-check-unavailable", "derive.py could not be run")
    finally:
        if child.poll() is None:                                    # whatever ended the wait: the check is left running by nothing
            child.kill()
    done = subprocess.CompletedProcess(argv, child.returncode, out, err)
    if done.returncode != 0:
        names = sorted(set(re.findall(r"refused: ([A-Za-z0-9_.:-]+):", done.stderr.decode("utf-8", "replace"))))
        refuse("thresholds-check-failed", "derive.py --check does not pass the thresholds file (exit %d; its refusals: %s)"
               % (done.returncode, ", ".join(names) or "none named"))


def read_plans(path: Path, derive: Optional[Path], sha256: Optional[str] = None, stop: Optional["Stop"] = None) -> Dict[str, Plan]:
    """The three bursts of the thresholds file, or Refused. Nothing is opened before this has passed. With `sha256`, the
    file's bytes are held to it first (decision 6): the bytes that were hashed are the bytes the plans are read from."""
    if in_a_work_tree(path):
        refuse("inside-a-work-tree", "the thresholds file stays outside every work tree")
    if not path.is_file():
        refuse("thresholds-missing", "the thresholds file is not there")
    try:
        raw = path.read_bytes()
    except OSError:
        refuse("thresholds-unreadable", "the thresholds file is no thresholds document with its bursts")
    if sha256 is not None and hashlib.sha256(raw).hexdigest() != sha256:
        refuse("thresholds-not-the-alarms", "the thresholds file is not the one whose sha256 was given, the file the account's alarms were "
               "rendered from (`twinctl status` prints that hash): a burst sized on another file says nothing about those alarms. Nothing "
               "was claimed and nothing is sent")
    derive_check(path, derive, stop)
    try:
        doc = json.loads(raw.decode("ascii"))
        b, t = doc["burst"], doc["thresholds"]
        if not isinstance(b, dict) or not isinstance(t, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        refuse("thresholds-unreadable", "the thresholds file is no thresholds document with its bursts")
    for key, value in sorted(DESIGN.items()):                       # the file's own ceilings, window and factor are this tool's
        if type(b.get(key)) is not int or b.get(key) != value:
            refuse("design-differs:" + key, "the thresholds file's burst design is not this tool's (the ceilings, the 60 s, more than twice)")
    v = {key: _whole(b, key, "burst-value") for key in BURST_KEYS}
    counts = [_whole(t, name, "thresholds-value") for name in COUNT_METRICS]
    thresholds = {"count": max(counts), "bytes": _whole(t, BYTES_METRIC, "thresholds-value"), "shadow": _whole(t, SHADOW_METRIC, "thresholds-value")}
    amounts = {"count": v["count_publishes"], "bytes": v["bytes_total"], "shadow": v["shadow_updates"]}
    ceilings = {"count": CEILINGS["publishes"], "bytes": CEILINGS["bytes"], "shadow": CEILINGS["shadow_updates"]}
    said = {"count": "2,000 publishes", "bytes": "8 MiB", "shadow": "60 shadow updates"}
    for kind in KINDS:
        if FACTOR * thresholds[kind] + 1 > ceilings[kind] or amounts[kind] > ceilings[kind]:
            refuse("over-ceiling:" + kind, "more than twice this threshold is over the tool's hard ceiling of %s: nothing is sent, whichever "
                   "kind was asked for" % said[kind])
        if amounts[kind] <= FACTOR * thresholds[kind]:
            refuse("not-over-twice:" + kind, "the file's burst is not more than twice its threshold: it would not be the burst the plan asks for")
    if v["bytes_total"] != v["bytes_publishes"] * v["bytes_per_publish"] or v["bytes_per_publish"] > MAX_PUBLISH_BYTES \
            or v["bytes_per_publish"] < MIN_PUBLISH_BYTES or v["bytes_publishes"] > CEILINGS["publishes"]:
        refuse("burst-inconsistent:bytes", "the bytes burst is not whole publishes, each within the broker's 128 KiB")
    if not MIN_PUBLISH_BYTES <= v["count_publish_bytes"] <= MAX_PUBLISH_BYTES or v["count_publishes"] * v["count_publish_bytes"] > CEILINGS["bytes"]:
        refuse("burst-inconsistent:count", "the count burst's publishes are not small publishes under the bytes ceiling")
    # the trickle's own attempts of one period stay under every threshold they add to: an alarm acts AT its threshold
    trickle = {"count": TRICKLE_PERIOD_BOTH, "bytes": TRICKLE_PERIOD_TOPIC * TRICKLE_PUBLISH_BYTES, "shadow": TRICKLE_PERIOD_TOPIC}
    least = {"count": min(counts), "bytes": thresholds["bytes"], "shadow": thresholds["shadow"]}
    for kind in KINDS:
        if least[kind] <= trickle[kind]:
            refuse("trickle-over-threshold:" + kind, "the tool's own trickle (one small attempt every 10 s, the two topics in turn) would not "
                   "stay under this threshold in one period of the alarms: it would move the alarm by itself, whichever kind was asked for. "
                   "Nothing is sent")
    return {"count": Plan("count", "ingest", v["count_publishes"], v["count_publish_bytes"]),
            "bytes": Plan("bytes", "ingest", v["bytes_publishes"], v["bytes_per_publish"]),
            "shadow": Plan("shadow", "shadow", v["shadow_updates"], len(SHADOW_DOCUMENT))}


def load_plan(kind: str, path: Path, derive: Optional[Path], sha256: Optional[str] = None, stop: Optional["Stop"] = None) -> Plan:
    if kind not in KINDS:
        refuse("kind-unknown", "a burst is by count, by bytes or by shadow")
    return read_plans(Path(path), Path(derive) if derive is not None else None, sha256, stop)[kind]


def filler(kind: str, size: int) -> bytes:
    """A JSON object of exactly `size` bytes that says what it is and holds nothing else."""
    base = len(json.dumps({"v": TEST_TRAFFIC, "burst": kind, "pad": ""}, separators=(",", ":")))
    if size < base:
        refuse("burst-inconsistent:size", "a publish that small cannot say what it is")
    return json.dumps({"v": TEST_TRAFFIC, "burst": kind, "pad": "x" * (size - base)}, separators=(",", ":")).encode("ascii")


# --------------------------------------------------------------------------------------------------- the clock, the stop, the log

class SystemClock:
    """The system's clocks. monotonic() never goes back and, where the platform has such a clock, goes on while the host
    is suspended (CLOCK_BOOTTIME: one clock for every process and container of a boot)."""

    def monotonic(self) -> float:
        boottime = getattr(time, "CLOCK_BOOTTIME", None)
        if boottime is not None:
            try:
                return float(time.clock_gettime(boottime))
            except OSError:
                pass
        return float(time.monotonic())

    def wall(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def boot(self) -> Optional[str]:
        try:
            text = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        except (OSError, ValueError):
            return None
        return text if re.fullmatch(r"[0-9a-f-]{8,64}", text) else None


class Stop:
    """Raised by a signal's handler, read before every hand-over and in every wait."""

    def __init__(self) -> None:
        self.name: Optional[str] = None

    def set(self, name: str) -> None:
        if self.name is None:
            self.name = name

    def __bool__(self) -> bool:
        return self.name is not None


class Log:
    """The run's log: one JSON line per event, written and flushed before the next thing is done. t_mono counts from the
    moment the log was made and is strictly increasing, so a line can be named by it."""

    def __init__(self, stream: TextIO, clock: Any) -> None:
        self._stream, self._clock = stream, clock
        self._zero = clock.monotonic()
        self._last = -1
        self._lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> float:
        with self._lock:
            micros = max(int(round((self._clock.monotonic() - self._zero) * 1e6)), self._last + 1)
            self._last = micros
            wall = datetime.datetime.fromtimestamp(self._clock.wall(), datetime.timezone.utc)
            stamp = wall.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (wall.microsecond // 1000)
            record = dict(fields, v=1, event=event, t_mono=micros / 1e6, t_wall=stamp)
            self._stream.write(json.dumps(record, sort_keys=True) + "\n")
            self._stream.flush()
            return micros / 1e6


# --------------------------------------------------------------------------------------------------- one run at a time

def _finite(value: Any) -> bool:
    """Whether a time of the ledger is a number a comparison can use: not NaN, not an infinity, not an integer too large for
    a float. (json.loads reads NaN and Infinity; a claim whose time is one holds no window, whatever the clock says.)"""
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


class Ledger:
    """<state>/burst-ledger.jsonl: one claim per start. A start inside the window of an earlier claim is refused."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        try:
            for line in self.path.read_text(encoding="utf-8").split("\n"):
                if not line:
                    continue
                entry = json.loads(line)
                claim = isinstance(entry, dict) and isinstance(entry.get("claim"), str) and all(
                    isinstance(entry.get(k), (int, float)) and not isinstance(entry.get(k), bool) for k in ("mono", "wall")) \
                    and all(_finite(entry[k]) for k in ("mono", "wall")) \
                    and (entry.get("boot") is None or isinstance(entry.get("boot"), str))
                if not claim and not (isinstance(entry, dict) and isinstance(entry.get("refused"), str)):
                    raise ValueError
                out.append(entry)
        except (OSError, ValueError):
            refuse("ledger-unreadable", "the state directory's ledger of starts cannot be read: nothing is sent, and it is not written over. "
                   "It is looked at by hand")
        return out

    def claim(self, clock: Any, kind: str) -> None:
        """Claim the window for this start, or Refused. The claim is written first and the file read back, so of two starts
        at once only the one whose line came first goes on."""
        self._read()                                                # a ledger that cannot be read is not written to
        nonce = os.urandom(8).hex()
        mine = {"claim": nonce, "boot": clock.boot(), "mono": clock.monotonic(), "wall": clock.wall(), "kind": kind}
        self._append(mine)
        entries = self._read()
        refused = {e["refused"] for e in entries if "refused" in e}
        for entry in entries:
            if entry.get("claim") == nonce:
                return
            if "claim" not in entry or entry["claim"] in refused:
                continue
            same_boot = entry.get("boot") is not None and entry.get("boot") == mine["boot"]
            age = mine["mono"] - entry["mono"] if same_boot else mine["wall"] - entry["wall"]
            if age < CEILING_S:
                self._append({"refused": nonce})
                refuse("window-held", "an earlier start of the burst tool holds this state directory's window (20 minutes from its start, "
                       "whether it still runs or not): a second start gets no allowance of its own. Nothing was opened")
        refuse("ledger-unreadable", "the state directory's ledger did not keep this start's claim: nothing is sent")

    def _append(self, entry: Dict[str, Any]) -> None:
        with open(str(self.path), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())


# --------------------------------------------------------------------------------------------------- the run

class _Open(NamedTuple):
    stamp: float          # the t_mono of its attempt line
    began: float          # the clock when it was handed over
    phase: str
    path: str
    size: int
    handle: Any


class Run:
    """One burst and its trickle on a link that is connected. Everything it uses is an argument: the plan, the link, the
    topics, the clock, the log, the stop."""

    def __init__(self, plan: Plan, link: Any, names: Any, clock: Any, log: Log, stop: Stop, started: Optional[float] = None) -> None:
        self.plan, self.link, self.clock, self.log, self.stop = plan, link, clock, log, stop
        self.topic = {"ingest": names.telemetry, "shadow": names.vss_update}          # topics.py's own two, and no other
        self.deadline = (clock.monotonic() if started is None else started) + CEILING_S
        self.connection = 1
        self.was_up = True
        self.open: List[_Open] = []
        self.attempted = {"publishes": 0, "bytes": 0, "shadow_updates": 0}          # of the burst: counted BEFORE each hand-over
        self.connects = 0
        self.acked = 0
        self.burst_met = False
        self.minutes_said = False

    # --- what both phases use
    def _at_the_time_ceiling(self) -> None:
        """The `ceiling minutes` line, once in a run: by the burst when it was the one that reached the ceiling (the
        trickle that follows it makes no attempt and writes no second line), else by the trickle."""
        if not self.minutes_said:
            self.minutes_said = True
            self.log.write("ceiling", which="minutes")

    def _look(self) -> bool:
        """Whether a connection is up. A connection that was up and is not any more is logged as cut, once."""
        up = bool(self.link.up())
        if self.was_up and not up:
            self.log.write("cut", connection=self.connection)
        self.was_up = up
        return up

    def _reap(self, everything: bool = False) -> None:
        """Log what became of the hand-overs that have an answer; one that has had none for SETTLE_S is `no-word`, and its
        connection is given up, so that what the SDK may still hold for it is never written."""
        left = []
        for item in self.open:
            word = item.handle.state()
            if word is None and (everything or self.clock.monotonic() - item.began > SETTLE_S):
                word = "no-word"
                if not everything:
                    self.link.give_up()
            if word is None:
                left.append(item)
                continue
            if word == "acked" and item.phase == "burst":
                self.acked += 1
            self.log.write("outcome", of=item.stamp, phase=item.phase, path=item.path, result=word if word in RESULTS else "failed")
        self.open = left

    def _hand_over(self, phase: str, path: str, payload: bytes, stamp: float) -> None:
        try:
            handle = self.link.begin(self.topic[path], payload)
        except UplinkError:                                         # not handed over: no connection was up after all
            self.log.write("outcome", of=stamp, phase=phase, path=path, result="refused")
            return
        self.open.append(_Open(stamp, self.clock.monotonic(), phase, path, len(payload), handle))

    def _sleep_until(self, until: float) -> None:
        """Sleep to `until` in slices, looking at the answers; returns early when the stop was raised."""
        while not self.stop:
            self._reap()
            left = until - self.clock.monotonic()
            if left <= 0:
                return
            self.clock.sleep(min(SLICE_S, left))

    # --- the burst
    def _over(self, size: int) -> Optional[str]:
        """Which ceiling one more hand-over of the burst would pass, or None."""
        if self.plan.path == "shadow":
            return "shadow_updates" if self.attempted["shadow_updates"] + 1 > CEILINGS["shadow_updates"] else None
        if self.attempted["publishes"] + 1 > CEILINGS["publishes"]:
            return "publishes"
        return "bytes" if self.attempted["bytes"] + size > CEILINGS["bytes"] else None

    def _full(self, size: int) -> bool:
        """Whether one more hand-over of `size` bytes would be more than the tool lets wait for an answer at once."""
        return len(self.open) >= INFLIGHT_MAX_PUBLISHES or (bool(self.open) and sum(o.size for o in self.open) + size > INFLIGHT_MAX_BYTES)

    def burst(self) -> None:
        plan = self.plan
        payload = SHADOW_DOCUMENT if plan.path == "shadow" else filler(plan.kind, plan.size)
        begun = self.clock.monotonic()
        self.log.write("burst-start", kind=plan.kind)
        gap = float(BURST_SPREAD_S) / plan.sends
        handed, last, why = 0, begun, "complete"
        for i in range(plan.sends):
            self._sleep_until(begun + i * gap)
            # the tool's own window of hand-overs without an answer: while it is full nothing more is handed over
            while self._full(len(payload)) and not self.stop and self._look() and self.clock.monotonic() - begun < WINDOW_S:
                self.clock.sleep(SLICE_S)
                self._reap()
            now = self.clock.monotonic()
            over = self._over(len(payload))
            if self.stop:
                why = "signal"
            elif not self._look():
                why = "cut"
            elif now >= self.deadline:
                why = "ceiling"
                self._at_the_time_ceiling()
            elif now - begun >= WINDOW_S:
                why = "window-over"
            elif over is not None:
                why = "ceiling"
                self.log.write("ceiling", which=over)
            if why != "complete":
                break
            if plan.path == "shadow":                               # counted before it is made, whatever becomes of it
                self.attempted["shadow_updates"] += 1
            else:
                self.attempted["publishes"] += 1
                self.attempted["bytes"] += len(payload)
            stamp = self.log.write("attempt", phase="burst", path=plan.path)
            self._hand_over("burst", plan.path, payload, stamp)
            handed, last = handed + 1, now
        settle = self.clock.monotonic() + SETTLE_S + SLICE_S
        while self.open and not self.stop and self.clock.monotonic() < settle:          # the answers still outstanding
            self._reap()
            if self.open:
                self.clock.sleep(SLICE_S)
        self._reap(everything=bool(self.stop))
        if self.stop:
            why = "signal"
        elif why == "complete" and not self._look() and self.acked < plan.sends:
            why = "cut"
        elif why == "complete" and self.acked < plan.sends:
            why = "failed"
        inside = handed == plan.sends and last - begun < WINDOW_S
        self.burst_met = why == "complete" and inside and self.acked == plan.sends
        self.log.write("burst-end", kind=plan.kind, met=self.burst_met, inside_window=inside, why=why,
                       ratio=(self.acked * 100 // plan.sends) / 100.0, span_s=round(last - begun, 3))

    # --- the trickle
    def _tick(self, path: str) -> None:
        up = self._look()                                           # a cut is said before the attempt that found it
        stamp = self.log.write("attempt", phase="trickle", path=path)
        word: Optional[str] = None
        if not up:
            if self.connects >= CONNECTS_MAX:                       # the second net: the tick allows fewer in a run
                word = "ceiling"
                self.log.write("ceiling", which="connects")
            elif self.deadline - self.clock.monotonic() <= CONNECT_ANSWER_S:          # its answer could come at or after the time ceiling
                word = "ceiling"
            else:
                word = str(self.link.reopen())
                if word not in ("opened", "held", "unanswered"):    # `refused`, and any answer the form has no word for: not opened,
                    word = "refused"                                # as far as the tool can say, and counted as asked for
                if word in ("opened", "refused"):                   # a connection was asked for
                    self.connects += 1
                if word == "opened":
                    self.connection += 1
                    self.log.write("connected", connection=self.connection)
                elif word == "refused":
                    self.log.write("connect-failed", connection=self.connection + 1, why="refused")
        fields = {"connect": word} if word is not None else {}      # named only when a connection was looked for: never null
        up = bool(self.link.up())
        if word == "opened" and not up:                             # opened a moment ago and lost before the hand-over: that loss
            self.log.write("cut", connection=self.connection)       # is said as every other is, at once (the next look finds no change)
        if not up or word not in (None, "opened"):                  # nothing goes to a connection the tool neither found up nor opened
            self.log.write("outcome", of=stamp, phase="trickle", path=path, result="refused", **fields)
            return
        self.was_up = True
        # The stop and the clock are read again right before the hand-over: a connection takes up to the link's wait to
        # open, and one that opened after a signal, or at or after the time ceiling, is handed nothing.
        if self.stop or self.clock.monotonic() >= self.deadline:
            self.log.write("outcome", of=stamp, phase="trickle", path=path, result="refused", **fields)
            return
        payload = SHADOW_DOCUMENT if path == "shadow" else filler("trickle", TRICKLE_PUBLISH_BYTES)
        try:
            handle = self.link.begin(self.topic[path], payload)
        except UplinkError:
            self.log.write("outcome", of=stamp, phase="trickle", path=path, result="refused", **fields)
            return
        began = self.clock.monotonic()
        result = handle.state()
        while result is None and not self.stop and self.clock.monotonic() - began <= SETTLE_S:
            self.clock.sleep(SLICE_S)
            result = handle.state()
        if result is None:
            result = "no-word"
            if not self.stop:
                self.link.give_up()
        self.log.write("outcome", of=stamp, phase="trickle", path=path, result=result if result in RESULTS else "failed", **fields)

    def trickle(self) -> str:
        """One attempt every TRICKLE_INTERVAL_S, the two topics in turn, until the time ceiling or the stop. Returns why it
        ended."""
        ticks = 0
        due = self.clock.monotonic() + TRICKLE_INTERVAL_S
        while True:
            self._sleep_until(min(due, self.deadline))
            if self.stop:
                return "signal"
            started = self.clock.monotonic()
            if started >= self.deadline:
                self._at_the_time_ceiling()
                return "time-ceiling"
            if ticks >= TRICKLE_MAX:
                self.log.write("ceiling", which="trickle")
                return "time-ceiling"
            self._tick(PATHS[ticks % len(PATHS)])
            ticks += 1
            due = max(started + TRICKLE_INTERVAL_S, self.clock.monotonic())

    def go(self) -> int:
        self.burst()
        why = "signal" if self.stop else self.trickle()
        self._reap(everything=True)
        try:
            self.link.close()
        except Exception:  # noqa: BLE001 -- a link that cannot be closed stops nothing: the process ends
            pass
        code = EXIT["ok"] if self.burst_met else EXIT["burst-not-met"]
        self.log.write("stopped", why=why, signal=self.stop.name, burst_met=self.burst_met, exit=code)
        return code


# --------------------------------------------------------------------------------------------------- the watchdog

def _hard_stop(log: Log) -> None:
    """End the process with the watchdog's status. Its `stopped` line is written by a thread of its own and waited for
    WATCHDOG_LINE_S at the most: a log that cannot be written now (its lock is held by a write that does not return, or
    this write does not return) keeps the process from ending no longer than that."""
    try:
        line = threading.Thread(target=log.write, args=("stopped",), daemon=True,
                                kwargs={"why": "watchdog", "signal": None, "burst_met": False, "exit": EXIT["watchdog"]})
        line.start()
        line.join(WATCHDOG_LINE_S)
    finally:
        os._exit(EXIT["watchdog"])


class Watchdog(threading.Thread):
    """The last net of the time ceiling: a thread of the tool's own that ends the process when a call into the SDK never
    came back. It reads the RUN'S clock (CLOCK_BOOTTIME where there is one) every WATCHDOG_LOOK_S and ends the process
    once that clock is WATCHDOG_GRACE_S past the time ceiling. The wait between two looks is the interpreter's own,
    which counts awake time only: a host that slept is seen at the first look after it woke."""

    def __init__(self, log: Log, clock: Any, started: float) -> None:
        super().__init__(name="burst-watchdog", daemon=True)
        self._log, self._clock = log, clock
        self.until = started + CEILING_S + WATCHDOG_GRACE_S
        self._cancelled = threading.Event()

    def run(self) -> None:
        while not self._cancelled.wait(WATCHDOG_LOOK_S):
            if self._clock.monotonic() >= self.until:
                _hard_stop(self._log)
                return                                              # reached only where a test stands in for os._exit

    def cancel(self) -> None:
        self._cancelled.set()


def arm_watchdog(log: Log, clock: Any, started: float) -> Watchdog:
    """Start the watchdog for a run that began at `started` on `clock`. Cancelled by a run that ended by itself."""
    watchdog = Watchdog(log, clock, started)
    watchdog.start()
    return watchdog


# --------------------------------------------------------------------------------------------------- the command line

class _Unreadable(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _Unreadable(message)


def _plain(make: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """A parser with no option of argparse's own and none taken by a prefix of its name: `--help` would print a usage
    and end with status 0, which is a burst that met its goal; the refusal's one line names the two command lines."""
    return make(*args, add_help=False, allow_abbrev=False, **kwargs)


def _sha256(text: str) -> str:
    """A sha256 as `twinctl status` prints it: 64 hexadecimal digits, lower case. Anything else is no hash, and its
    command line cannot be read."""
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise argparse.ArgumentTypeError("no sha256")
    return text


def parser() -> argparse.ArgumentParser:
    ap: argparse.ArgumentParser = _plain(_Parser, prog="burst.py")
    sub = ap.add_subparsers(dest="command", required=True, parser_class=_Parser)
    run = _plain(sub.add_parser, "run")
    run.add_argument("--kind", required=True, choices=list(KINDS))
    for a, needed in ((run, True), (_plain(sub.add_parser, "check"), False)):
        a.add_argument("--thresholds", required=True, help="the thresholds file derive.py wrote")
        a.add_argument("--thresholds-sha256", dest="thresholds_sha256", required=needed, default=None, type=_sha256,
                       help="the sha256 of the file the alarms were rendered from, as `twinctl status` prints it")
        a.add_argument("--derive", default=None, help="derive.py, when it is not beside the thresholds file")
    run.add_argument("--state", required=True, help="the tool's state directory (the ledger of starts), outside every work tree")
    run.add_argument("--log", required=True, help="the run's log, a new file outside every work tree")
    return ap


def _default_link(env: Mapping[str, str], names: Any) -> Any:
    import burst_link          # the tool's link on the device SDK: imported here, so that `check` and the tests need no SDK
    return burst_link.from_env(env, names)


def _writable(directory: Path, file: Path) -> bool:
    """Whether the system says that this user can make and write `file` in `directory`. Asked (os.access), not tried:
    a start that is refused has written nothing. What the system cannot say beforehand (a full disk) is not held."""
    return os.access(str(directory), os.W_OK | os.X_OK) and (not file.exists() or os.access(str(file), os.W_OK))


def _start(args: argparse.Namespace, env: Mapping[str, str], make_link: Optional[Callable[..., Any]], clock: Any, stop: Stop) -> int:
    log_path, state = Path(args.log), Path(args.state)
    for path, what in ((state, "the state directory"), (log_path, "the log")):
        if in_a_work_tree(path):
            refuse("inside-a-work-tree", "%s would lie inside a work tree: a run's state and its log stay outside every one" % what)
    if not state.is_dir():
        refuse("state-missing", "the state directory is not there: it is made by hand, once, outside every work tree")
    if not _writable(state, state / LEDGER):
        refuse("state-unwritable", "the state directory, or the ledger of starts in it, cannot be written by this user: a start writes its "
               "claim there. Nothing was claimed and nothing is sent")
    if log_path.exists() and (not log_path.is_file() or log_path.stat().st_size > 0):
        refuse("log-exists", "the log's file is there already: every run writes a log of its own")
    if not log_path.parent.is_dir():
        refuse("log-missing", "the directory the log is to be written in is not there")
    if not _writable(log_path.parent, log_path):
        refuse("log-unwritable", "the directory the log is to be written in, or the empty file that is there for it, cannot be written by "
               "this user: a run that could not write its log claims no window. Nothing was claimed and nothing is sent")
    plan = load_plan(args.kind, Path(args.thresholds), Path(args.derive) if args.derive else None, args.thresholds_sha256, stop)
    try:
        names = topics.Topics(env.get(ENV_THING), env.get(ENV_RULE))
    except topics.TopicsError:
        refuse("names", "%s or %s is missing or is no name topics.py takes: the two topics are built from checked names only" % (ENV_THING, ENV_RULE))
    try:
        link = (make_link or _default_link)(env, names)
    except UplinkError:
        refuse("settings", "the link's settings are missing or malformed (the endpoint, the device directory's three files)")
    except ImportError:
        refuse("sdk", "the device SDK is not installed here: the tool runs in its own image")
    stopped_before_start(stop)                                      # a signal that came during the checks: nothing is claimed
    Ledger(state / LEDGER).claim(clock, plan.kind)                  # the last check, right before the connection
    started = clock.monotonic()
    watchdog: Any = None
    with open(str(log_path), "a", encoding="utf-8", newline="\n") as stream:
        log = Log(stream, clock)
        try:
            if isinstance(clock, SystemClock):
                watchdog = arm_watchdog(log, clock, started)
            log.write("start", kind=plan.kind, ceilings=dict(CEILINGS), window_s=WINDOW_S, trickle_s=TRICKLE_INTERVAL_S)
            if stop:
                # THE STOP ONCE MORE, right before the first connection is asked for (decision 8): a signal that landed inside
                # the claim, or since, finds a run whose window is held. It ends here: no connection is asked for.
                log.write("stopped", why="signal", signal=stop.name, burst_met=False, exit=EXIT["burst-not-met"])
                return EXIT["burst-not-met"]
            try:
                link.connect()
            except UplinkError:
                log.write("connect-failed", connection=1, why="refused")
                log.write("stopped", why="no-connection", signal=stop.name, burst_met=False, exit=EXIT["no-connection"])
                return EXIT["no-connection"]
            log.write("connected", connection=1)
            return Run(plan, link, names, clock, log, stop, started=started).go()
        except Exception as error:  # noqa: BLE001 -- by its class, never its text: a link's error may name the endpoint
            try:
                link.close()
            except Exception:  # noqa: BLE001
                pass
            log.write("stopped", why="error", signal=stop.name, burst_met=False, exit=EXIT["error"])
            print("burst: stopped on an error no check names (%s); the log says how far it came" % type(error).__name__, file=sys.stderr)
            return EXIT["error"]
        finally:
            if watchdog is not None:
                watchdog.cancel()


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None, make_link: Optional[Callable[..., Any]] = None,
         clock: Any = None, stop: Optional[Stop] = None) -> int:
    own_stop = stop is None
    flag = Stop() if stop is None else stop
    previous: Dict[int, Any] = {}
    try:
        # THE HANDLERS COME FIRST (decision 8): before the command line is read and before every check. In its image the
        # tool is PID 1, for which the kernel drops a signal that has only its default handling.
        if own_stop:
            for number in (signal.SIGINT, signal.SIGTERM):
                previous[number] = signal.signal(number, lambda signum, _frame: flag.set(signal.Signals(signum).name))
        try:
            args = parser().parse_args(argv)
        except _Unreadable:
            print("burst: refused: arguments-invalid: the command line cannot be read: run --kind count|bytes|shadow --thresholds FILE "
                  "--thresholds-sha256 HEX --state DIR --log FILE [--derive FILE], or check --thresholds FILE [--thresholds-sha256 HEX] "
                  "[--derive FILE]", file=sys.stderr)
            return EXIT["arguments"]
        if args.command == "check":
            read_plans(Path(args.thresholds), Path(args.derive) if args.derive else None, args.thresholds_sha256, flag)
            stopped_before_start(flag)
            print("burst: the thresholds file is taken for all three kinds%s; nothing was sent"
                  % (", and it is the file whose sha256 was given" if args.thresholds_sha256 is not None else ""))
            return EXIT["ok"]
        return _start(args, os.environ if env is None else env, make_link, SystemClock() if clock is None else clock, flag)
    except Refused as refused:
        print("burst: refused: %s: %s" % (refused.name, refused.detail), file=sys.stderr)
        return EXIT["refused"]
    except Exception as error:  # noqa: BLE001 -- by its class, never its text: an error of the system's names a path
        # Outside a run's own handling: a write the system had said could be made (the ledger's, the log's), or the log's
        # last line after an error. Status 1 is a refusal by a name and nothing else, so this is not left to a traceback.
        print("burst: stopped on an error no check names (%s); where a log was begun, it says how far the run came" % type(error).__name__,
              file=sys.stderr)
        return EXIT["error"]
    finally:
        for restored, handler in previous.items():
            if handler is not None:
                signal.signal(restored, handler)


if __name__ == "__main__":
    sys.exit(main())
