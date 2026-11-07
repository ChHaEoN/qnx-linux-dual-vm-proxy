"""uplink.py -- the seam between the twin connector's logic and whatever carries its messages (sdv/connector; SDV
Phase 4 WP2).

Standard library only. This module imports no SDK, and neither does any module of
the connector's logic: the one importer is uplink_aws.py (WP3), which implements this seam and nothing else.

THE SEAM, four calls
    connect(on_resumed=None)        open the connection. `on_resumed`, when given, is called (from any thread, with
                                    no argument) each time the connection comes back after it was lost: a session
                                    starts clean, so that is a new connection as far as the shadows are concerned.
    publish(topic, payload, qos)    send `payload` (bytes) to exactly `topic`; return when the uplink has taken it
                                    (QoS 1: acknowledged), raise UplinkError when it failed or timed out.
    subscribe(topic, callback)      deliver every message on exactly `topic` as callback(topic, payload), from any
                                    thread.
    close()                         end the connection.

An UplinkError's text may name the endpoint, a topic or a file: the connector logs the error's class and never its
text, wherever it is raised: while the uplink is built from its settings (the entry point answers with a sentence of
its own and status 2), while the connection is opened, or at a publish. An implementation should raise nothing else.
If one does (an SDK's own class, not wrapped), the connector treats it as an error nobody expected: its class and
where it was raised, never its text, and no traceback (connector.py).

FakeUplink is the seam for the tests and for a run with no broker: it records every publish with the time its clock
gave, keeps the subscriptions so that a test can deliver a message as the service would, and fails on demand.

Does not demonstrate: anything about a real connection: TLS, the SDK's behaviour, a reconnect, a time-out.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, NamedTuple, Optional, Protocol

Callback = Callable[[str, bytes], None]


class UplinkError(Exception):
    """The uplink could not do what it was asked."""


class Uplink(Protocol):
    def connect(self, on_resumed: Optional[Callable[[], None]] = None) -> None: ...

    def publish(self, topic: str, payload: bytes, qos: int = 1) -> None: ...

    def subscribe(self, topic: str, callback: Callback) -> None: ...

    def close(self) -> None: ...


class Published(NamedTuple):
    topic: str
    payload: bytes
    qos: int
    t: Optional[float]          # the fake's clock at the publish, when it was given one


class FakeUplink:
    """An uplink that goes nowhere and remembers everything."""

    def __init__(self, clock: Any = None) -> None:
        self.clock = clock
        self.published: List[Published] = []
        self.subscriptions: Dict[str, Callback] = {}
        self.connected = False
        self.connects = 0
        self.closes = 0
        self.fail_connect: Optional[str] = None          # a text: connect() raises UplinkError with it
        self.fail_publish: Optional[Callable[[str, bytes], Optional[str]]] = None          # returns a text to fail that publish
        self.on_publish: Optional[Callable[[str, bytes], None]] = None          # the far side, called after each publish
        self._on_resumed: Optional[Callable[[], None]] = None

    def connect(self, on_resumed: Optional[Callable[[], None]] = None) -> None:
        if self.fail_connect is not None:
            raise UplinkError(self.fail_connect)
        self.connected = True
        self.connects += 1
        self._on_resumed = on_resumed

    def publish(self, topic: str, payload: bytes, qos: int = 1) -> None:
        if not self.connected:
            raise UplinkError("not connected")
        if self.fail_publish is not None:
            why = self.fail_publish(topic, payload)
            if why is not None:
                raise UplinkError(why)
        self.published.append(Published(topic, payload, qos, self.clock.monotonic() if self.clock is not None else None))
        if self.on_publish is not None:
            self.on_publish(topic, payload)

    def subscribe(self, topic: str, callback: Callback) -> None:
        if not self.connected:
            raise UplinkError("not connected")
        self.subscriptions[topic] = callback

    def close(self) -> None:
        self.connected = False
        self.closes += 1

    def deliver(self, topic: str, payload: bytes) -> bool:
        """A message arrives on `topic`: handed to its subscriber, if there is one for exactly that topic."""
        callback = self.subscriptions.get(topic)
        if callback is None:
            return False
        callback(topic, payload)
        return True

    def resume(self) -> None:
        """The connection was lost and is back."""
        if self._on_resumed is not None:
            self._on_resumed()
