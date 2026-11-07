"""limits.py -- every design value of the twin connector, in one place (sdv/connector; SDV Phase 4 WP2).

No import of another module: every other module of the connector, the stack's start
rule and the threshold derivation read these names and hold no design value of their own. (What else is a number in
those modules is no design value: the loop's poll and shortest sleep, the limiter's rounding guard, the time a
closing source waits for its thread.)

The parameters selected by this project are design values; each has its reason below. The gap letters name
those rules. SDK_TLS_NEGOTIATION_S is the one exception: it is the pinned SDK's own default, written out so that
the connection budget's sum can be read.

  Sampling and batching (gaps f, g)
    RATES_HZ, DEFAULT_RATE_HZ   The connector samples the latest value of each effective path on its own tick, at
                                1 Hz or 10 Hz and at no other rate. 1 Hz unless `config` asks for 10.
    BATCH_INTERVAL_S            One telemetry batch per 60 s at 1 Hz and per 10 s at 10 Hz (the plan's cadence), so
                                a batch holds at most batch_ticks(rate) rows: 60, or 100.

  The `vss` shadow (gap h)
    SHADOW_MIN_INTERVAL_S       A `vss` reported document goes no closer than 60 s to the previous one. The plan's
                                10 s is a minimum; at 10 s the shadow alarm's headroom over normal traffic is too
                                thin. The interval is fixed here and is not a `config` field: a cloud-written
                                interval could push normal traffic over the alarm's threshold.
    FIRST_DOCUMENT_WAIT_S       A process's first `vss` document waits for the source's first value, 2 s at most:
                                a subscription's first response arrives a moment after it is opened, and a first
                                document sent before it would be all null, with the next one a minute away.

  The limiter, the last thing before the wire (gap s): below every breaker threshold, above normal traffic
    LIMITER_WINDOW_S            300 s: the alarms' period. "In any 300 s" is read as a closed window, and float
                                rounding is taken to the side that keeps the cap (limiter.py).
    TELEMETRY_MIN_GAP_S         At most one telemetry publish a second,
    TELEMETRY_MAX_PER_WINDOW    and 60 in any 300 s (normal: 30, at 10 Hz),
    TELEMETRY_MAX_BYTES         each of at most 16 KiB (the largest batch the envelope can build is under it).
    SHADOW_MAX_PER_WINDOW       At most 10 publishes to shadow topics in any 300 s, both shadows together and the
                                `config` get included (normal: 5, one `vss` document a minute),
    SHADOW_MAX_BYTES            each of at most 4 KB: half the service's document limit.
    worst_case()                What ONE PROCESS, honest or broken, can send in 300 s at most: 60 publishes and
                                983,040 bytes of telemetry, 10 shadow publishes. The limiter's windows are new in
                                every process; across starts the bound is the start spacing's, below.

  A shadow publish the uplink failed (gaps h, l, s): the connector's own rule, in front of the limiter
    SHADOW_RETRY_S              After a publish to a shadow topic that the uplink FAILED (the `config` get, a `vss`
                                document, a `config` report: it may have gone out or not, and the limiter counts
                                it as if it had), nothing is tried on a shadow topic for 60 s, the `vss` floor
                                again; the stop's last document alone does not wait. Tried again at every tick, a
                                failed report would be ten attempts in a second at 10 Hz (in ten at 1 Hz) and
                                leave the window none for the documents that follow. At one attempt a spacing, an
                                uplink that fails every publish is asked at most six times in any closed 300 s (at
                                0, 60, ... 300 s), so the retries alone never fill the window's 10.

  The service's own limits, held as guards before a shadow document is sent (aws-map A3.7)
    SHADOW_DOC_LIMIT_BYTES      8 KB for a shadow's state document.
    SHADOW_DOC_MAX_DEPTH        8 levels.

  `config`, the spool and the inbox (gaps l, m)
    CONFIG_GET_WAIT_S           How long the connector waits for the answer to its `config` get before it goes on
                                with the defaults. Until then it samples and sends nothing.
    INBOUND_MAX_BYTES           A message from the uplink larger than this is not parsed: a shadow's get reply is
                                its state (at most 8 KB) and its metadata, comfortably under 32 KiB.
    INBOX_MAX                   Messages kept between two steps of the loop; more than that drops the oldest.
    SPOOL_MAX_BYTES             256 bytes for the spool record (the updater reads at most that; the largest valid
                                record is 148).
    SPOOL_MIN_GAP_S             The spool file is rewritten at most once a second; the last request wins.

  The signal source
    SOURCE_RETRY_S              A subscription that ended or failed is opened again after 1 s (the app's interval).
    SUBSCRIBE_BUFFER            100, the buffer the app and the WP0 probe ask the databroker for.

  The start spacing (gap i): what bounds a sequence of starts, where the limiter bounds one process
    START_SPACING_S             A connector start within 120 s of the previous one is refused. Each start costs a
                                `config` get, a first `vss` document and a `config` report, and each stop a last
                                document: four shadow publishes a cycle however short the process lived, so starts a
                                second apart would pass any one process's cap many times over.
                                WHO HOLDS IT. Two rules, each for the starts it can see:
                                  the connector itself (startstamp.py), for every start on ONE spool directory: a
                                    restart policy, a crash loop, a second run on the same mounts. It keeps the
                                    time of the last start beside the spool record and refuses, before anything is
                                    opened, a start that comes too soon (exit status 4). This is code, and tested.
                                  the stack (sdv/stack/stack.py, start_connector), for starts on DIFFERENT spool
                                    directories, which the connector cannot see (each replay has its own): it
                                    keeps the same stamp, through startstamp.py, in a state directory of the host
                                    that outlives every run directory, and refuses to start a connector within
                                    START_SPACING_S of the previous one it started. Code, and tested; it holds for
                                    the starts that one host's stack makes with one state directory.
                                Whether one of the two should carry it alone is the owner's call. Both are
                                kept until it is made, because neither sees the other's case.
    START_STAMP_MAX_BYTES       64 bytes for the start stamp, read back at the next start (a stamp is 28).
    starts_per_window()         How many starts any closed 300 s can hold at that spacing: 3 (at 0, 120 and 240 s).
                                Each has a limiter of its own, and a process begun before the window may end
                                inside it: the worst case across starts is WP5's to derive from this and from
                                worst_case(), not a number of this file.

  The uplink (gap k): read by uplink_aws.py, which hands each of them to the SDK itself and leaves it no default
    QOS                         1.
    MQTT_PORT, KEEP_ALIVE_S     8883; 60 s.
    RECONNECT_MIN_S, RECONNECT_MAX_S
                                The reconnect back-off, 5 s to 60 s, written out so that what a refused client can
                                cause after a trip is a known rate. It is THE UPLINK'S OWN and is not handed to the
                                SDK: the uplink gives a lost connection up and opens the next one itself, no sooner
                                than RECONNECT_MIN_S after the loss, the wait doubling up to RECONNECT_MAX_S while
                                connections fail or live less than RECONNECT_MAX_S (uplink_aws.py says why).
    SDK_RECONNECT_HOLD_S        3600 s, handed to the SDK for BOTH ends of its own reconnect timer (its default is 5 s
                                to 60 s). The uplink never uses a connection the SDK brings back, so the SDK's timer
                                is of no use to it; and at its default it raced the uplink: an SDK that reconnects by
                                itself writes what it queued when that reconnect is answered and tells its user only
                                then, so a publish the uplink had reported as failed went out (the hard review's wire
                                run, 2026-10-08). The hold keeps the SDK from trying at all until long after the
                                uplink has given the connection up by its own wait: the connector hands the uplink a
                                publish at least once a minute (a batch at 1 Hz, a document), and the uplink waits
                                OPERATION_TIMEOUT_S + UPLINK_WAIT_MARGIN_S for its answer; an hour is more than ten
                                times that and the longest back-off together. One value for both ends, so the SDK's
                                own doubling has nothing to do. A design value, like the rest. The hold alone left a
                                window (an uplink never told of a loss, and a publish handed over in the hold's last
                                seconds): LINK_LIFE_MAX_S closes it.
    LINK_LIFE_MAX_S             900 s. The uplink hands the SDK nothing on a connection that has shown no life for
                                this long: no connect, publish or subscription of its own that the SDK answered. The
                                SDK cannot have noticed a loss before the last answer and makes its own first attempt
                                the hold after it noticed, so the latest hand-over (900 s after the last answer) and
                                the wait for it (OPERATION_TIMEOUT_S + UPLINK_WAIT_MARGIN_S) end before half the hold
                                has gone; the other half is for the SDK's clock and the uplink's not running alike.
                                So the SDK's own reconnect never finds a publish to send, whenever and whether or not
                                the uplink was told of the loss (uplink_aws.py, THE CHOICE, g, which says what that
                                rests on). Three limiter windows, fifteen batch intervals at 1 Hz: an honest
                                connector, which has a publish acknowledged every batch interval, never comes near it.
    OPERATION_TIMEOUT_S         5 s for a QoS 1 publish to be acknowledged once it is written to the socket (the SDK's
                                protocol operation time-out; its own default is none at all, so a publish could wait
                                without end). The loop stands still while it waits, so this is also the longest gap
                                one silent far end puts into the samples.
    UPLINK_WAIT_MARGIN_S        2 s more that the uplink itself waits for the SDK to say what became of a publish or
                                a subscription. When the SDK has said nothing by then, that connection is given up.
    PING_TIMEOUT_S              3 s for the answer to a keep-alive ping (and to the CONNECT) before the SDK takes the
                                connection for lost: the SDK's default, written out.
    TCP_CONNECT_TIMEOUT_S       5 s for the TCP connect: the SDK's default, written out.
    CONNECT_WAIT_S              10 s that the uplink waits for the SDK's answer to a connect; after that it reports the
                                attempt as failed and has no connection. It covers the two waits the uplink sets, the
                                TCP connect's 5 s and the 3 s for the CONNECT's answer. It does NOT cover everything
                                the SDK may take: between those two lies the TLS handshake, with a wait of the SDK's
                                own (below), and a name's resolution comes before all three. So the SDK can answer a
                                connect, with a connection, after the uplink stopped waiting; and while it is still
                                connecting it refuses to be disconnected. What the uplink does about that is not a
                                number: no other connection is asked for while a connect is unanswered, and a late
                                connection is disconnected the moment the SDK reports it (uplink_aws.py, THE CHOICE, f).
    SDK_TLS_NEGOTIATION_S       10 s, the TLS negotiation time-out aws-c-io applies when the caller sets none
                                (aws_tls_connection_options_init_from_ctx sets timeout_ms to 10000: awscrt 0.36.1's
                                crt/aws-c-io/source/tls_channel_handler.c, line 622). The builder used here sets
                                none, so that default applies; the value is written out for the budget's sum and is
                                handed to nothing.
    CLOSE_WAIT_S                2 s for the DISCONNECT to go out when the uplink is closed.

Does not demonstrate: that any of these is right for the service (the thresholds they sit under are WP5's, and the
metrics those count are first read in the account), or anything measured.
"""
from __future__ import annotations

from typing import Dict

RATES_HZ = (1, 10)
DEFAULT_RATE_HZ = 1
BATCH_INTERVAL_S = {1: 60, 10: 10}

SHADOW_MIN_INTERVAL_S = 60
FIRST_DOCUMENT_WAIT_S = 2.0

LIMITER_WINDOW_S = 300
TELEMETRY_MIN_GAP_S = 1.0
TELEMETRY_MAX_PER_WINDOW = 60
TELEMETRY_MAX_BYTES = 16 * 1024
SHADOW_MAX_PER_WINDOW = 10
SHADOW_MAX_BYTES = 4096
SHADOW_RETRY_S = 60

SHADOW_DOC_LIMIT_BYTES = 8192
SHADOW_DOC_MAX_DEPTH = 8

CONFIG_GET_WAIT_S = 5.0
INBOUND_MAX_BYTES = 32 * 1024
INBOX_MAX = 32
SPOOL_MAX_BYTES = 256
SPOOL_MIN_GAP_S = 1.0

SOURCE_RETRY_S = 1.0
SUBSCRIBE_BUFFER = 100

QOS = 1
MQTT_PORT = 8883
KEEP_ALIVE_S = 60
RECONNECT_MIN_S = 5
RECONNECT_MAX_S = 60
SDK_RECONNECT_HOLD_S = 3600         # both ends of the SDK's own reconnect timer: it is not to try before the uplink gave up
LINK_LIFE_MAX_S = 900               # nothing is handed to a connection that showed no life for this long (uplink_aws.py, g)
OPERATION_TIMEOUT_S = 5
UPLINK_WAIT_MARGIN_S = 2.0
PING_TIMEOUT_S = 3
TCP_CONNECT_TIMEOUT_S = 5
CONNECT_WAIT_S = 10.0
SDK_TLS_NEGOTIATION_S = 10          # aws-c-io's own default, written out for the sum; nothing reads it but the tests
CLOSE_WAIT_S = 2.0

START_SPACING_S = 120
START_STAMP_MAX_BYTES = 64


def batch_ticks(rate_hz: int) -> int:
    """How many ticks, so at most how many rows, one batch spans at this rate."""
    return rate_hz * BATCH_INTERVAL_S[rate_hz]


def starts_per_window() -> int:
    """How many starts any closed window can hold when each comes START_SPACING_S after the previous one at the least."""
    return LIMITER_WINDOW_S // START_SPACING_S + 1


def worst_case() -> Dict[str, int]:
    """The most one process's limiter lets through in one window, whatever the connector behind it does."""
    return {
        "window_s": LIMITER_WINDOW_S,
        "telemetry_publishes": TELEMETRY_MAX_PER_WINDOW,
        "telemetry_bytes": TELEMETRY_MAX_PER_WINDOW * TELEMETRY_MAX_BYTES,
        "shadow_publishes": SHADOW_MAX_PER_WINDOW,
        "shadow_bytes": SHADOW_MAX_PER_WINDOW * SHADOW_MAX_BYTES,
    }
