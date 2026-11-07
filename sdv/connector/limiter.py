"""limiter.py -- the twin connector's hard caps, the last thing before the wire (sdv/connector; SDV Phase 4 WP2).

Standard library only.

The cloud side's breaker acts minutes after a leak begins, and an IoT policy cannot bound a publish's size or rate.
What bounds the honest connector, and a connector with a bug in its batching or its shadow logic, is this: a wrapper
around the uplink that every publish goes through and that refuses whatever is over a cap. The entry point builds the
uplink inside it, and the connector refuses to be built on anything else (connector.py).

WHAT IT HOLDS (the values are limits.py's; gap s)
    a topic    Only the connector's own four publish topics pass, and only its five subscribe topics (topics.py).
               Anything else is refused, whatever asked for it.
    telemetry  The Basic Ingest topic: at most one publish a second, at most 60 in any 300 s, each of at most 16 KiB.
    shadow     The other three topics together (both shadows' updates and the `config` get): at most 10 in any
               300 s, each of at most 4 KB.
    "In any 300 s" is a closed window: a publish counts until it is MORE than 300 s old, so no interval of 300 s,
    ends included, ever holds more than the cap.

ROUNDING, always to the side that keeps the cap. The clock's readings are floats, and a float can stand a little off
the instant it means: 2222.3 - 1922.3 is 300.0000000000002. Compared as it stands, a publish exactly 300 s old would
count as "more than 300 s old" and one more would pass into the closed window. So a publish leaves the window only
when it is more than 300 s and half a millisecond old (_GUARD_S): rounding can make the window that much longer and
never shorter, and on a clock of whole milliseconds the window is exact. The one-second gap needs no guard: rounding
moves a difference by some 1e-13 s, far less than a step of any clock, so two instants a clock step less than a
second apart still differ by less than 1.0 as floats and no publish passes early. One that comes exactly a second
after the last may be refused, when the difference rounds to just under 1.0; it is dropped like anything else the
limiter refuses.

A refusal raises LimitRefused (an UplinkError, so a caller that knows only the seam still sees a failed publish) with
`why` (topic, payload, bytes, rate or window) and `retry_after_s`: how long until a publish of that class could pass
again, or None when waiting does not help (a payload that is too large stays too large). The connector drops what was
refused, counts it, and does not try that class again before then: nothing is queued here or there.

A publish the uplink itself failed keeps its place in the window: it may have reached the wire. A refused publish
takes none.

ONE PROCESS, AND ONE PUBLISH. The windows are new in every process: what bounds a sequence of starts is the start
spacing (startstamp.py on one spool directory, the stack's rule across them; limits.py says who holds what). And a
publish is counted once, when the uplink is asked to send it: whatever an uplink does underneath is not seen here. An
uplink that sent an unacknowledged QoS 1 publish again after a reconnect, or sent later one it had reported as failed,
would put a message on the wire that no window counted. The SDK does both by default; uplink_aws.py says how it keeps
it from either (a clean session, no publish handed over without a connection, a lost connection given up for good,
the SDK's own reconnect timer held far beyond the uplink's waits, and nothing handed to a connection that has shown
no life for a fraction of that hold) and what that rests on, and the opt-in broker tests hold the real SDK to it.
What a new connection costs below this seam is not a publish and is not counted here: one CONNECT and five SUBSCRIBE,
at most once per reconnect back-off (limits.py).

THE UPLINK'S OWN COUNTERS pass through here to the connector's stop line and to nothing else (below()): the connector
holds the limiter and never the uplink, and a record has to show what the uplink counted (connections opened, lost,
given up and found without life, an SDK that came back by itself). Counts only: an entry that is no int under a plain lower-case name
is left out, so nothing an uplink keeps there can put a name, a topic or a text into the log.

Does not demonstrate: anything about a connector that is not built through the entry point, a second process, an
uplink other than uplink_aws.py, or what the service bills.
"""
from __future__ import annotations

import collections
import re
from typing import Any, Callable, Deque, Dict, Optional

import limits
from uplink import Callback, UplinkError

_EPSILON_S = 0.001          # past the window's closed end: retry_after_s names a moment at which the publish passes
_GUARD_S = _EPSILON_S / 2   # how far past the window's end a publish still counts: above any float rounding, below _EPSILON_S
_COUNTER = re.compile(r"[a-z][a-z0-9_]{0,39}")          # a counter's name, as below() passes one on


class LimitRefused(UplinkError):
    """The limiter refused a publish or a subscription; nothing reached the uplink."""

    def __init__(self, why: str, retry_after_s: Optional[float] = None) -> None:
        super().__init__("refused by the limiter: %s" % why)
        self.why = why
        self.retry_after_s = retry_after_s


class Limiter:
    """The uplink seam, with the caps in front of `inner`."""

    def __init__(self, inner: Any, topics: Any, clock: Any) -> None:
        self.inner = inner
        self.topics = topics
        self.clock = clock
        self.counters: Dict[str, int] = {}
        self._sent: Dict[str, Deque[float]] = {"telemetry": collections.deque(), "shadow": collections.deque()}

    # --- the seam ---------------------------------------------------------------------------------

    def connect(self, on_resumed: Optional[Callable[[], None]] = None) -> None:
        self.inner.connect(on_resumed)

    def subscribe(self, topic: str, callback: Callback) -> None:
        if topic not in self.topics.subscribe:
            raise self._refuse("topic")
        self.inner.subscribe(topic, callback)

    def close(self) -> None:
        self.inner.close()

    def below(self) -> Dict[str, int]:
        """The uplink's own counters, copied, for the connector's stop line: {} for an uplink that keeps none. Counts
        under plain names and nothing else (the module's docstring says why)."""
        counters = getattr(self.inner, "counters", None)
        if not isinstance(counters, dict):
            return {}
        return {k: v for k, v in counters.items() if isinstance(k, str) and _COUNTER.fullmatch(k) and type(v) is int}

    def publish(self, topic: str, payload: bytes, qos: int = limits.QOS) -> None:
        kind = self.kind(topic)
        if kind is None:
            raise self._refuse("topic")
        if not isinstance(payload, (bytes, bytearray)):
            raise self._refuse("payload")
        cap = limits.TELEMETRY_MAX_BYTES if kind == "telemetry" else limits.SHADOW_MAX_BYTES
        if len(payload) > cap:
            raise self._refuse("bytes")
        now = self.clock.monotonic()
        wait, why = self._wait(kind, now)
        if wait is not None:
            raise self._refuse(why, wait)
        self._sent[kind].append(now)          # before the uplink is asked: a publish it fails may still have gone out
        self.inner.publish(topic, bytes(payload), qos)

    # --- the caps ---------------------------------------------------------------------------------

    def kind(self, topic: Any) -> Optional[str]:
        """telemetry, shadow, or None for a topic that is not one of the connector's four."""
        if not isinstance(topic, str) or topic not in self.topics.publish:
            return None
        return "telemetry" if topic == self.topics.telemetry else "shadow"

    def _wait(self, kind: str, now: float) -> Any:
        """(None, "") when a publish of this class may go now; else (how long until one may, which cap)."""
        sent = self._sent[kind]
        while sent and now - sent[0] > limits.LIMITER_WINDOW_S + _GUARD_S:          # see ROUNDING: exactly 300 s old still counts
            sent.popleft()
        if kind == "telemetry" and sent and now - sent[-1] < limits.TELEMETRY_MIN_GAP_S:
            return limits.TELEMETRY_MIN_GAP_S - (now - sent[-1]), "rate"
        cap = limits.TELEMETRY_MAX_PER_WINDOW if kind == "telemetry" else limits.SHADOW_MAX_PER_WINDOW
        if len(sent) >= cap:
            return sent[len(sent) - cap] + limits.LIMITER_WINDOW_S - now + _EPSILON_S, "window"
        return None, ""

    def _refuse(self, why: str, retry_after_s: Optional[float] = None) -> LimitRefused:
        self.counters["refused_" + why] = self.counters.get("refused_" + why, 0) + 1
        return LimitRefused(why, retry_after_s)
