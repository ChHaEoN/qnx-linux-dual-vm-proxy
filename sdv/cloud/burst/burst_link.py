"""burst_link.py -- the burst tool's link on the device SDK (sdv/cloud/burst; SDV Phase 4, the burst-tool contract).

It is the connector's own uplink, sdv/connector/uplink_aws.py, taken whole and given
the one thing a burst needs and the connector must never have: a hand-over that does not wait for its answer. No SDK
module is imported here; the connector's module stays the one place where it is (uplink_aws.load_sdk). Nothing of the
connector is changed by this, and no connector module imports this file.

WHAT IS THE CONNECTOR'S, UNCHANGED (uplink_aws.py says why each is as it is)
    the settings   one MQTT 3.1.1 connection with mtls_from_path, port 8883, a clean session, the keep-alive, the
                   operation time-out, SDK metrics off, the device directory's CA, the thing's name as the client id,
                   and the SDK's own reconnect timer held at an hour at both ends;
    a loss         a connection the SDK lost is given up at once and never used again (its own reconnecting ends with
                   it); one the SDK brings back by itself all the same is disconnected again;
    a connect      the wait for it, what is done about one the SDK has not answered, and the back-off before the next
                   (5 s, doubling to 60 s): reopen() asks for a connection only when that back-off allows it.

WHAT IS THIS TOOL'S
    begin()        hands ONE QoS 1 publish to the SDK on the connection in use and returns at once; state() of what
                   it returns says later whether it was acknowledged or failed. With no connection in use it raises
                   and the SDK is not asked: nothing reaches the SDK's offline queue. It never opens a connection.
    reopen()       one new connection, when the tool asks for it: opened | refused | held | unanswered | up.
    give_up()      the connection in use is never used again (the tool calls it when a hand-over got no word in time).
  The connector's waiting publish() and its subscribe() raise here: the tool waits for no single publish and
  subscribes to nothing.

WHY NOTHING IS SENT LATER (the connector's rule: a publish reported as failed is never sent later). The connector's
uplink holds it for a process that lives for days, by never handing anything to a connection without a sign of life.
Here it rests on less: the session is clean, so the SDK cancels what was in flight at a loss; a hand-over is refused
while this module knows the connection to be down; a lost connection is disconnected, which ends the SDK's
reconnecting; and for a loss this module was never told of, the SDK's own first reconnect comes no sooner than its
held timer, an hour, while the tool's run ends within 20 minutes and its watchdog 30 s later (burst.py holds the sum
under half the hold, in a test). What the SDK may still hold when the process ends is never written.

IT RESTS ON uplink_aws.py'S INSIDE: the names _in_use, _open, _give_up, _unanswered, _retry_at, _lock, _link, _mqtt,
_monotonic, _closed, _opened and counters, and a link's conn and life. A change there breaks tests/test_sdv_burst.py,
which drives this file on the stand-in for the SDK that the connector's own tests hold the uplink to.

Does not demonstrate: the SDK (the tests' stand-in is the connector's model of it; the opt-in broker tests run the real
one against a local broker); anything about the cloud service; any timing.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

import uplink_aws
from uplink import Callback, UplinkError


class Handle:
    """One hand-over. state(): None while the SDK has said nothing, then acked or failed, for good."""

    def __init__(self, link: Any, future: Any, began: float, word: Optional[str] = None) -> None:
        self._link, self._future, self._began, self._word = link, future, began, word

    def state(self) -> Optional[str]:
        if self._word is None and self._future is not None and self._future.done():
            try:
                failed = self._future.cancelled() or self._future.exception() is not None
            except BaseException:  # noqa: BLE001 -- whatever the SDK's answer raises when it is looked at: no acknowledgement
                failed = True
            self._word = "failed" if failed else "acked"
            if not failed:          # an answer is the connection's sign of life, as of the moment the request was begun
                self._link.life = max(self._link.life, self._began)
        return self._word


class BurstLink(uplink_aws.AwsUplink):
    """The connector's uplink with a hand-over that does not wait. Built by from_env()."""

    def up(self) -> bool:
        """Whether a connection is in use: the SDK said it is connected and nothing since said otherwise."""
        return self._in_use() is not None

    def begin(self, topic: str, payload: bytes) -> Handle:
        link = self._in_use()
        if link is None:
            self.counters["not_connected"] += 1
            raise UplinkError("not connected")
        began = self._monotonic()
        try:
            future = link.conn.publish(topic, bytes(payload), self._mqtt.QoS.AT_LEAST_ONCE)[0]
        except Exception:  # noqa: BLE001 -- the SDK's own class: whether it took the publish is not known, so it counts as handed over
            return Handle(link, None, began, "failed")
        except BaseException:
            self._give_up(link)
            raise
        return Handle(link, future, began)

    def reopen(self) -> str:
        """Ask for one new connection, when there is none and the connector's own back-off allows it."""
        if self._in_use() is not None:
            return "up"
        if self._closed or not self._opened:
            return "refused"
        if self._unanswered():
            return "unanswered"
        with self._lock:
            retry_at = self._retry_at
        if retry_at is not None and self._monotonic() < retry_at:
            return "held"
        try:
            self._open()
        except UplinkError:
            return "refused"
        return "opened"

    def give_up(self) -> None:
        with self._lock:
            link = self._link
        if link is not None:
            self._give_up(link)

    def publish(self, topic: str, payload: bytes, qos: int = uplink_aws.limits.QOS) -> None:
        raise UplinkError("the burst tool hands a publish over with begin() and waits for no single one")

    def subscribe(self, topic: str, callback: Callback) -> None:
        raise UplinkError("the burst tool subscribes to nothing")


def from_env(env: Mapping[str, str], topics: Any, sdk: Optional[Tuple[Any, Any]] = None) -> BurstLink:
    """The link from the environment's settings, read as the connector reads them: UplinkError for a setting or a file,
    ImportError when the SDK is not installed. Nothing is opened here."""
    settings = uplink_aws.settings_from(env)
    return BurstLink(settings, topics.client_id, sdk if sdk is not None else uplink_aws.load_sdk())
