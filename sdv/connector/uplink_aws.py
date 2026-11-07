"""uplink_aws.py -- the twin connector's uplink on the device SDK: the one module that imports it (sdv/connector; SDV
Phase 4 WP3).

It implements the seam of uplink.py (connect, publish, subscribe, close) and nothing
else, on one MQTT 3.1.1 connection built with awsiot.mqtt_connection_builder.mtls_from_path. No other module of the
connector imports awscrt or awsiot (a test holds it), and the connector's entry point puts the limiter in front of
this (connector.build). No identifier is in this file: the endpoint and the three files come from the environment
(the device directory's environment file), the client id from topics.py.

EVERY SETTING IS GIVEN TO THE SDK HERE; none is left to its default (prep gap k). The values are limits.py's.
    what                       given                       the SDK's default (awsiotsdk 1.31.0, awscrt 0.36.1)
    port                       8883                        443 with ALPN where ALPN is available
    clean_session              True                        False, a persistent session
    keep_alive_secs            60                          1200
    protocol_operation_timeout 5 s                         0: a QoS 1 publish waits without limit
    ping_timeout_ms            3 s                         3 s
    tcp_connect_timeout_ms     5 s                         5 s
    the SDK's reconnect timer  3600 s at both ends         5 s to 60 s: the SDK's own reconnecting, which this
                                                           module never uses (THE CHOICE, c, e and g)
    ca_filepath                the device directory's CA   the system's trust store
    enable_metrics_collection  False                       True: the SDK's name, version and features ride in the
                                                           CONNECT packet's user name
    client_id                  the thing's name            none (the builder refuses to build without one)
No user name, no password, no will, no proxy, no websocket, no ALPN list (the builder sets one for port 443 only).
The SDK's own logging is never switched on (awscrt.io.init_logging is not called anywhere).
THE TLS HANDSHAKE has no wait keyword in the builder used here, so aws-c-io's own default for the negotiation
applies; limits.SDK_TLS_NEGOTIATION_S writes that default out for the connection-budget arithmetic and is handed to
nothing.
THE CHOICE, f, is what this module does about a connect that outlasts its own wait.

WHAT THE SDK DOES WITH A QoS 1 PUBLISH THAT WAS NOT ACKNOWLEDGED, and what this module does about it. Read from the
pinned SDK's source and seen at the pinned local broker (the opt-in broker tests repeat each of these):
    1. Written to a far end that stays silent: the SDK fails it after the protocol operation time-out and forgets
       it. It is not sent again. It may have arrived: the far end can still read it later.
    2. In flight when the connection is lost, under clean_session=True: the SDK cancels it, fails it, and does not
       send it again after its reconnect. Under the SDK's default (clean_session=False) it IS sent again, with the
       DUP flag set: a second packet for one publish, which no window of the limiter counted.
    3. Handed to the SDK while the connection is down: the SDK QUEUES it and sends it once the connection is back,
       whatever clean_session says ("If the device is offline, the PUBLISH packet will be sent once the connection
       resumes", awscrt/mqtt.py). A caller that stopped waiting and reported a failure would see it go out later.
THE CHOICE, so that a publish this module reported as failed is never SENT later, and nothing is sent twice.
("Sent" is what this module and the SDK do. A publish the SDK wrote to the socket and then failed, case 1, was sent
when it was asked; the far end may still read it later. That is arrival, and it is no later send.)
    a. clean_session=True, for case 2.
    b. A publish is handed to the SDK only on a connection that is up. With no connection, publish() raises at once
       and the SDK is not asked: nothing reaches its offline queue.
    c. A LOST CONNECTION IS GIVEN UP, AT ONCE, AND NEVER USED AGAIN. The SDK's interrupted callback disconnects that
       SDK connection, which ends the SDK's own reconnecting: whatever the SDK still holds for it (a publish that
       slipped in between the loss and the callback is the case) stays in a connection that never connects again.
       THE SDK'S OWN RECONNECT TIMER IS HELD AT limits.SDK_RECONNECT_HOLD_S, an hour, at both ends, so that the SDK
       tries nothing of its own in the meantime. c needs that, because giving up from the SDK's callbacks
       alone is a question of who is first: the SDK writes its queue when its own reconnect is answered and calls
       on_connection_resumed only AFTER that. With the SDK's default timer (5 s, which this module handed it before)
       and the word of a loss reaching this module late, a publish that had been reported as failed went out on the
       SDK's own reconnected connection (the hard review's wire run, 2026-10-08; the broker tests repeat it). That
       connection has no subscriptions either: one more reason it is never used.
       A connection the SDK brings back by itself all the same is disconnected again, and counted (resumed_by_sdk).
       c alone is not what the invariant rests on: with the hold and nothing else, a module that was never told of
       a loss and handed a publish over in the last seconds of the hold would see it written on the SDK's own
       reconnect. g closes that.
    d. When the SDK has said nothing about a publish or a subscription within the operation time-out and the
       margin, what it holds is unknown: that connection is given up in the same way, and the call fails.
    e. The next connection is a NEW SDK connection, opened by this module on the caller's thread: at the first
       publish that comes RECONNECT_MIN_S after the loss or later. The wait doubles up to RECONNECT_MAX_S while
       attempts fail or connections live less than RECONNECT_MAX_S, and starts again at RECONNECT_MIN_S after a
       connection that lived that long. A new connection has no session: the subscriptions are made again, then
       on_resumed() is called, and then the publish that opened it goes out on it.
    f. A CONNECT THE SDK HAS NOT ANSWERED when this module stops waiting for it (CONNECT_WAIT_S) cannot be given up
       as c and d give a connection up: the SDK refuses a disconnect while it is still connecting, and goes on
       (seen at the pinned pair). Its own waits add up to more than CONNECT_WAIT_S (limits.py), so it can still
       answer with a connection, under the thing's client id, that this module knows nothing of. So the answer is
       kept and watched. When it is a connection, that connection is disconnected the moment the SDK reports it:
       never taken into use, no subscription and no publish on it, counted as `late`. And while a connect is
       unanswered no other is asked for, by connect() or by a publish: a second CONNECT under one client id makes
       the far end close whichever connection came first, which could be the one in use.
    g. NOTHING IS HANDED TO A CONNECTION THAT HAS SHOWN NO LIFE FOR limits.LINK_LIFE_MAX_S. This is what makes "a
       publish that raised is never sent later" hold WHENEVER, and WHETHER OR NOT, the SDK's word of a loss reaches
       this module. A connection's life is the latest moment at which this module began something that the SDK then
       ANSWERED on it: the connect, a publish or a subscription that was acknowledged (one the SDK failed is no
       sign of life). The argument, on what was seen of the SDK (below):
         - the SDK cannot have noticed a loss before that moment, and it makes its own first reconnect attempt no
           sooner than SDK_RECONNECT_HOLD_S after it noticed;
         - a request is handed over only within LINK_LIFE_MAX_S of that moment, and this module's wait for its
           answer ends OPERATION_TIMEOUT_S + UPLINK_WAIT_MARGIN_S later at the most: before half the hold has gone
           (limits.py's test holds the sum), so before the SDK's first own attempt;
         - by then the request was acknowledged; or the SDK failed it and has forgotten it (cases 1 and 2); or the
           SDK said nothing and the connection was given up (d), which ends the SDK's reconnecting for good.
       So when the SDK does reconnect by itself, its queue holds nothing this module reported as failed. A
       connection that is up as far as this module knows and has shown no life for that long is given up at the
       next publish or subscription, before the SDK is asked (counted as `stale`); that call fails, and the next
       publish after the back-off opens the next connection (e). An honest connector never comes near it: it has
       a publish acknowledged every batch interval.
       WHAT g RESTS ON. Three things seen of the pinned SDK at the local broker (the opt-in broker tests repeat
       them), and one about clocks: (1) the SDK's own first reconnect attempt comes no sooner after a loss than
       the timer it was given; (2) a disconnect on a connection the SDK is keeping for its own reconnect ends that
       reconnecting, and what the SDK holds for it is never written; (3) a request the SDK failed is not written
       later; (4) the SDK's clock does not run at twice the rate of this module's (the half of the hold that is
       left over). Both are clocks of one host that never go back; which one the SDK's native code reads was not
       examined. One that counts the time a host is suspended would run ahead of time.monotonic, so this module
       reads the clock that counts it too where there is one (_clock: CLOCK_BOOTTIME on Linux, where the connector
       runs): whichever the SDK reads, this module's is then not the slower of the two.
       Nothing here was read from the SDK's native source, which the wheel does not carry.
       resumed_by_sdk IS A COUNT FOR THE RECORD, not what holds the invariant: an SDK that came back by itself did
       so with an empty queue, and cost one CONNECT and one DISCONNECT under the thing's client id.
    So there is no re-send, and nothing reaches the SDK's offline queue to be sent later: one publish() is at most
    one PUBLISH packet, and a publish that raised is not sent later. What the connector does with a failed publish
    (drop a batch, try the shadow topics again a spacing later, with what is then due) is connector.py's, and every
    such try passes the limiter again.
    WHAT THE LIMITER DOES NOT COUNT, because it is no publish: a new connection's one CONNECT and its SUBSCRIBE
    packets (five, the connector's reply topics). They are bounded by e and f: at most one connection attempt per
    back-off wait, one at a time, and only when the connector has something to send. An attempt is at most one
    CONNECT whether the SDK answers in time or late; a late connection costs that CONNECT and a DISCONNECT and
    nothing else. A new connection also makes the connector read its `config` again and report once more
    (on_resumed): shadow publishes, inside the limiter's window.
    THE PRICE of e: while the connection is down nothing arrives either, and it stays down until the connector next
    publishes after the wait (a batch every 60 s at 1 Hz, sooner at 10 Hz); and that publish() blocks the
    connector's loop while the new connection is opened (CONNECT_WAIT_S at the most, then the subscriptions).
    THE PRICE of f: an SDK that never answered a connect at all would leave this module without a connection for
    good (every publish fails at once, counted as not_connected). The three stages of a connect that are known
    here each have a time-out (the TCP connect's and the one for the CONNECT's answer are set above, the
    handshake's is the SDK's own); that the SDK always answers is not shown here.
    THE PRICE of g: a connection on which nothing was acknowledged for LINK_LIFE_MAX_S is given up although it may
    be sound (a connector that had nothing to send for a quarter of an hour; a far end that acknowledged nothing for
    that long), and the publish that finds it so fails like any other: a batch is dropped, a shadow publish is tried
    again a spacing later. One more connection in a quarter of an hour at the most, inside e's back-off.

WHAT A CALL RAISES. uplink.UplinkError and nothing else, whatever the SDK raised or returned; the text of an SDK
error is never passed on. (An error that is no Exception at all, raised while the SDK was asked, gives the
connection up and is passed on as it is: the connector logs its class.) The SDK's callbacks run on its own threads:
each is guarded, so none of them raises there.

THE SETTINGS, from the environment (the device directory's environment file; never the argv):
    SDV_TWIN_ENDPOINT   the host name to connect to. A host name or an IPv4 address: no scheme, no port, no path.
    SDV_TWIN_CERT       the device certificate, default /run/sdv-local/device/device.crt
    SDV_TWIN_KEY        its private key,        default /run/sdv-local/device/device.key
    SDV_TWIN_CA         the CA file the far end's certificate must chain to, default /run/sdv-local/device/ca.pem
The thing's and the rule's names are read by connector.py (topics.py checks them). A setting that is missing or
malformed, or a file that is not there, is an UplinkError from from_env; an SDK that is not installed is the
ImportError itself. The entry point answers either with a sentence of its own and status 2.

Does not demonstrate: anything about the cloud service (the broker tests run against a local broker that carries
bytes on topics: no shadow service, no rule, no policy, no certificate status, no quota); that the choice above is
needed or enough against that service; the default-port path (443 with ALPN is never taken); what the SDK does on
a platform or in a version other than the pinned pair; f with the shipped CONNECT_WAIT_S (the broker test shortens
the wait in its own process, because the shipped one and the SDK's handshake wait end together at a paused broker);
c and g with the SHIPPED hold and life run out (no test waits an hour: the stand-in's clock runs the shipped values,
and the broker tests give the driver's own process a hold and a life of seconds, at which the SDK's own attempt is
seen to come when its timer says and not before); what g rests on beyond those runs (the four points under g); any
timing.
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Tuple

import limits
from uplink import Callback, UplinkError

ENV_ENDPOINT = "SDV_TWIN_ENDPOINT"
ENV_CERT = "SDV_TWIN_CERT"
ENV_KEY = "SDV_TWIN_KEY"
ENV_CA = "SDV_TWIN_CA"
DEVICE_DIR = "/run/sdv-local/device"          # where the stack mounts the device directory, read-only
DEFAULT_FILES = {ENV_CERT: DEVICE_DIR + "/device.crt", ENV_KEY: DEVICE_DIR + "/device.key", ENV_CA: DEVICE_DIR + "/ca.pem"}

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST = re.compile(r"%s(?:\.%s)*" % (_LABEL, _LABEL))
_HOST_MAX = 253

COUNTERS = ("opened", "lost", "given_up", "undone", "stale", "late", "resumed_by_sdk", "callback_errors", "messages", "not_connected")


class Settings(NamedTuple):
    endpoint: str
    cert: str
    key: str
    ca: str


def settings_from(env: Mapping[str, str]) -> Settings:
    """The uplink's settings from the environment, or UplinkError. The text names the variable, never its value."""
    endpoint = env.get(ENV_ENDPOINT)
    if not isinstance(endpoint, str) or len(endpoint) > _HOST_MAX or not _HOST.fullmatch(endpoint):
        raise UplinkError("%s is missing or is no host name (no scheme, no port, no path)" % ENV_ENDPOINT)
    files = {}
    for name, default in DEFAULT_FILES.items():
        path = env.get(name) or default
        if not os.path.isabs(path) or not os.path.isfile(path) or not os.access(path, os.R_OK):
            raise UplinkError("%s names no file that can be read (by default a file of the device directory)" % name)
        files[name] = path
    return Settings(endpoint, files[ENV_CERT], files[ENV_KEY], files[ENV_CA])


def connection_options(settings: Settings, client_id: str) -> Dict[str, Any]:
    """Every keyword the builder is given beside the certificate, the key and the callbacks: the table of the module's
    docstring. Nothing here is left for the SDK to choose."""
    return {
        "endpoint": settings.endpoint,
        "port": limits.MQTT_PORT,
        "client_id": client_id,
        "clean_session": True,
        "keep_alive_secs": limits.KEEP_ALIVE_S,
        "ping_timeout_ms": limits.PING_TIMEOUT_S * 1000,
        "protocol_operation_timeout_ms": limits.OPERATION_TIMEOUT_S * 1000,
        "tcp_connect_timeout_ms": limits.TCP_CONNECT_TIMEOUT_S * 1000,
        "reconnect_min_timeout_secs": limits.SDK_RECONNECT_HOLD_S,          # the SDK's own timer, held: THE CHOICE, c.
        "reconnect_max_timeout_secs": limits.SDK_RECONNECT_HOLD_S,          # The uplink's back-off is its own (e).
        "ca_filepath": settings.ca,
        "enable_metrics_collection": False,
    }


def load_sdk() -> Tuple[Any, Any]:
    """The SDK's two modules this file uses. The one place they are imported: an SDK that is not installed is an
    ImportError here, which the entry point answers with its `sdk` sentence."""
    from awscrt import mqtt
    from awsiot import mqtt_connection_builder
    return mqtt, mqtt_connection_builder


def _clock(clocks: Any = time) -> float:
    """Seconds on a clock that never goes back and, where the platform has one, goes on while the host is suspended:
    CLOCK_BOOTTIME on Linux, time.monotonic elsewhere. THE CHOICE, g, needs this module's clock not to fall behind
    the SDK's own, and time.monotonic stands still through a suspend."""
    boottime = getattr(clocks, "CLOCK_BOOTTIME", None)
    if boottime is not None:
        try:
            return float(clocks.clock_gettime(boottime))
        except OSError:
            pass
    return float(clocks.monotonic())


class _Link:
    """One SDK connection and what the uplink knows of it. It serves one connection's life and is never used again."""

    def __init__(self) -> None:
        self.conn: Any = None
        self.up = False                # the SDK said it is connected, and nothing since said otherwise
        self.given_up = False          # disconnected by the uplink, for good
        self.since = 0.0               # when it came up, on the uplink's clock
        self.life = 0.0                # the latest moment this module began something the SDK then answered on it (g)


class AwsUplink:
    """The seam of uplink.py on the device SDK. Built by from_env(); connector.build() wraps it in the limiter."""

    def __init__(self, settings: Settings, client_id: str, sdk: Tuple[Any, Any], monotonic: Callable[[], float] = _clock) -> None:
        self._settings = settings
        self._client_id = client_id
        self._mqtt, self._builder = sdk
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._link: Optional[_Link] = None                 # the connection in use; None while there is none
        self._subs: List[Tuple[str, Callback]] = []
        self._on_resumed: Optional[Callable[[], None]] = None
        self._opened = False                               # connect() succeeded once
        self._closed = False
        self._connecting: Any = None                       # the SDK's answer to the last connect asked of it (a future)
        self._backoff = float(limits.RECONNECT_MIN_S)      # how long after the next loss or failed attempt the one after it may come
        self._retry_at: Optional[float] = None             # no new connection is tried before this moment
        self.counters: Dict[str, int] = dict.fromkeys(COUNTERS, 0)

    # --- the seam -------------------------------------------------------------------------------------

    def connect(self, on_resumed: Optional[Callable[[], None]] = None) -> None:
        """Open the connection. UplinkError when it cannot be opened within CONNECT_WAIT_S, or when the SDK has not
        answered an earlier connect yet (THE CHOICE, f)."""
        if self._closed:
            raise UplinkError("the uplink is closed")
        if self._unanswered():
            self.counters["not_connected"] += 1
            raise UplinkError("not connected: an earlier connect is unanswered")
        self._on_resumed = on_resumed
        self._open()
        self._opened = True

    def publish(self, topic: str, payload: bytes, qos: int = limits.QOS) -> None:
        """One QoS 1 publish: returns when it was acknowledged, raises UplinkError when it failed, timed out or could
        not be handed over. A publish that raised is never sent later (the module's docstring, THE CHOICE)."""
        if qos != limits.QOS:
            raise UplinkError("the uplink sends QoS %d and nothing else" % limits.QOS)
        link = self._usable()
        self._ask(link, lambda: link.conn.publish(topic, bytes(payload), self._mqtt.QoS.AT_LEAST_ONCE)[0], "publish")

    def subscribe(self, topic: str, callback: Callback) -> None:
        """Deliver every message on exactly `topic` as callback(topic, payload), payload bytes, from an SDK thread."""
        link = self._in_use()
        if link is None:
            self.counters["not_connected"] += 1
            raise UplinkError("not connected")
        self._subscribe(link, topic, callback)
        self._subs.append((topic, callback))

    def close(self) -> None:
        """End the connection; safe on an uplink that was never connected, and safe to repeat. Never raises."""
        self._closed = True
        with self._lock:
            link = self._link
        if link is not None:
            self._give_up(link, wait_s=limits.CLOSE_WAIT_S)

    # --- one connection ---------------------------------------------------------------------------------

    def _open(self) -> _Link:
        """A new SDK connection, connected; or UplinkError, with whatever was built given up. When the wait ends and the
        SDK has not answered, it is still connecting and takes no disconnect: its answer is kept (_connecting, which
        holds the next connect back) and watched (_answered, which disconnects a connection that comes too late)."""
        link = _Link()
        try:
            options = connection_options(self._settings, self._client_id)
            options.update(self._callbacks(link))
            link.conn = self._builder.mtls_from_path(cert_filepath=self._settings.cert, pri_key_filepath=self._settings.key, **options)
            began = self._monotonic()
            answer = link.conn.connect()
            with self._lock:
                self._connecting = answer
            answer.add_done_callback(lambda done: self._answered(link, done))
            answer.result(limits.CONNECT_WAIT_S)
        except Exception:  # noqa: BLE001 -- the SDK's own class, a time-out, a refused handshake: its text stops here
            self._give_up(link)
            self._later()
            raise UplinkError("the connection could not be opened") from None
        except BaseException:
            self._give_up(link)
            raise
        with self._lock:
            if link.given_up or self._closed:          # lost again before it was taken into use, or closed meanwhile
                ok = False
            else:
                link.up, link.since, link.life, self._link, ok = True, self._monotonic(), began, link, True
        if not ok:
            self._give_up(link)
            self._later()
            raise UplinkError("the connection was lost as it was opened")
        self.counters["opened"] += 1
        return link

    def _callbacks(self, link: _Link) -> Dict[str, Any]:
        """The SDK's connection callbacks for one link. They run on the SDK's threads and never raise there."""

        def interrupted(*_args: Any, **_kwargs: Any) -> None:          # the connection was lost: THE CHOICE, c
            try:
                self.counters["lost"] += 1
                self._give_up(link)
            except BaseException:  # noqa: BLE001 -- an SDK thread: nothing may leave it
                self.counters["callback_errors"] += 1

        def resumed(*_args: Any, **_kwargs: Any) -> None:              # the SDK brought it back by itself: never used again.
            # The SDK writes its queue BEFORE this call, so this give-up protects nothing that was queued: g is what
            # keeps that queue empty. Counted for the record.
            try:
                self.counters["resumed_by_sdk"] += 1
                self._give_up(link)
            except BaseException:  # noqa: BLE001
                self.counters["callback_errors"] += 1

        return {"on_connection_interrupted": interrupted, "on_connection_resumed": resumed}

    def _answered(self, link: _Link, done: Any) -> None:
        """The SDK answered a connect: on its own thread, or on the caller's when it had answered before it was asked
        to tell. An answer that is a connection, for a link the uplink gave up while it was unanswered (the wait
        ended, or an error that is no Exception ended it), is a connection nobody uses under the thing's client id:
        it is disconnected here, at once, and counted (THE CHOICE, f). An answer that is an error, or one for a link
        that was not given up, asks for nothing."""
        try:
            if done.cancelled() or done.exception() is not None:
                return
            with self._lock:
                late = link.given_up
            if late:
                self.counters["late"] += 1
                self._disconnect(link)
        except BaseException:  # noqa: BLE001 -- an SDK thread: nothing may leave it
            self.counters["callback_errors"] += 1

    def _unanswered(self) -> bool:
        """Whether the SDK is still working on a connect it was asked for. Then no other is asked for."""
        with self._lock:
            answer = self._connecting
        return answer is not None and not answer.done()

    def _give_up(self, link: _Link, wait_s: float = 0.0) -> None:
        """This link is never used again: it is marked, taken out of use, and the SDK is asked to disconnect its
        connection. On a connection that is up or that the SDK is reconnecting, that ends it and the SDK's own
        reconnecting, and whatever the SDK still holds for it never goes out. While the SDK is still CONNECTING it
        refuses the disconnect and goes on: that case is _answered's. Never raises."""
        with self._lock:
            first = not link.given_up
            was_up, link.up, link.given_up = link.up, False, True
            if self._link is link:
                self._link = None
                if was_up and self._monotonic() - link.since >= limits.RECONNECT_MAX_S:
                    self._backoff = float(limits.RECONNECT_MIN_S)          # it lived: the next wait is the shortest again
                self._later_locked()
        if first:
            self.counters["given_up"] += 1
        self._disconnect(link, wait_s)

    def _disconnect(self, link: _Link, wait_s: float = 0.0) -> None:
        """Ask the SDK to disconnect this link's connection, and wait for it when told to. Best effort: never raises."""
        if link.conn is None:
            return
        try:
            future = link.conn.disconnect()
            if wait_s > 0:
                future.result(wait_s)
        except Exception:  # noqa: BLE001 -- refused (not connected, still connecting) or not done in time: out of use either way
            pass

    def _later(self) -> None:
        with self._lock:
            self._later_locked()

    def _later_locked(self) -> None:
        """No new connection before the back-off is over; the wait after the next loss or failure is twice as long."""
        self._retry_at = self._monotonic() + self._backoff
        self._backoff = min(self._backoff * 2, float(limits.RECONNECT_MAX_S))

    def _in_use(self) -> Optional[_Link]:
        """The link that is up and has shown life within LINK_LIFE_MAX_S, or None. One that is up as far as this module
        knows and has shown none for that long is given up here, before the SDK is asked for anything on it (THE
        CHOICE, g): the SDK may be keeping it for a reconnect of its own, whose queue nothing may be put into."""
        with self._lock:
            link = self._link
        if link is None or not link.up:
            return None
        if self._monotonic() - link.life > limits.LINK_LIFE_MAX_S:
            self.counters["stale"] += 1
            self._give_up(link)
            return None
        return link

    def _usable(self) -> _Link:
        """The link in use. With none, a new connection is opened here when its time has come (THE CHOICE, e) and
        the SDK is not still working on an earlier connect (f); else UplinkError, and the SDK is not asked for anything."""
        link = self._in_use()
        if link is not None:
            return link
        with self._lock:
            retry_at = self._retry_at
        if self._closed or not self._opened or (retry_at is not None and self._monotonic() < retry_at) or self._unanswered():
            self.counters["not_connected"] += 1
            raise UplinkError("not connected")
        link = self._open()
        try:
            for topic, callback in self._subs:
                self._subscribe(link, topic, callback)
        except UplinkError:
            self._give_up(link)          # a connection without its subscriptions is not the connector's connection
            raise
        resumed = self._on_resumed
        if resumed is not None:
            resumed()
        return link

    def _subscribe(self, link: _Link, topic: str, callback: Callback) -> None:
        def deliver(topic: str, payload: Any, *_args: Any, **_kwargs: Any) -> None:          # an SDK thread
            try:
                if not link.given_up:
                    self.counters["messages"] += 1
                    callback(topic, bytes(payload))
            except BaseException:  # noqa: BLE001 -- nothing may leave an SDK thread
                self.counters["callback_errors"] += 1

        self._ask(link, lambda: link.conn.subscribe(topic, self._mqtt.QoS.AT_LEAST_ONCE, deliver)[0], "subscribe")

    def _ask(self, link: _Link, call: Callable[[], Any], what: str) -> Any:
        """One request to the SDK on `link`, waited for. The SDK failed it: UplinkError (the SDK has forgotten it). The
        SDK said nothing in time: the link is given up, so that what the SDK may still hold never goes out (THE
        CHOICE, d), and UplinkError. An answer that is no failure is the link's sign of life, as of the moment the
        request was begun (g): the SDK cannot have noticed a loss before it."""
        began = self._monotonic()
        try:
            answer = call().result(limits.OPERATION_TIMEOUT_S + limits.UPLINK_WAIT_MARGIN_S)
        except concurrent.futures.TimeoutError:
            self.counters["undone"] += 1
            self._give_up(link)
            raise UplinkError("%s: the SDK did not say what became of it" % what) from None
        except Exception:  # noqa: BLE001 -- the SDK's own class: its text stops here
            raise UplinkError("%s failed" % what) from None
        except BaseException:
            self._give_up(link)
            raise
        link.life = max(link.life, began)
        return answer


def from_env(env: Mapping[str, str], topics: Any, sdk: Optional[Tuple[Any, Any]] = None) -> AwsUplink:
    """The uplink from the environment's settings: UplinkError for a setting or a file, ImportError when the SDK is
    not installed. Nothing is opened here."""
    settings = settings_from(env)
    return AwsUplink(settings, topics.client_id, sdk if sdk is not None else load_sdk())
