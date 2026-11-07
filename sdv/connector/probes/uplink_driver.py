"""uplink_driver.py -- the connector's real uplink (uplink_aws.py on the SDK), driven one command at a time, for the
opt-in broker tests (sdv/connector/probes; SDV Phase 4 WP3).

tests/test_sdv_connector_broker.py mounts this file read-only into a container of the
connector IMAGE (its python as the entry point, on the test's --internal Docker network) and talks to it over stdin
and stdout: one JSON command a line in, one JSON answer a line out. So what the tests see is the image's own
uplink_aws.py, limits.py and topics.py on the image's own SDK, against a local broker.

IT IS NEVER STAGED INTO THE IMAGE (sdv/connector/build_image.py stages no file of this directory; a test holds it).
It reaches the uplink without the limiter, which is what the connector's one entry point exists to prevent: a second
program in the image that did so would be the bypass. It is a probe, started by a test, against a throwaway broker.

COMMANDS (each answer: ok, the error's class when not ok and never its text, how long the call took, the uplink's
counters, how often on_resumed was called, how many losses the SDK has reported (sdk_lost; counted only after a
`defer`), and every message received so far as [topic, payload in hex])
    {"op": "build"}                              uplink_aws.from_env on the container's environment (the settings)
    {"op": "connect"}                            connect(on_resumed)
    {"op": "subscribe", "topic": T}              subscribe(T, callback)
    {"op": "publish", "topic": T, "hex": H}      publish(T, bytes.fromhex(H), 1)
    {"op": "state"}                              nothing: the counters and the messages
    {"op": "close"}                              close()
    {"op": "limit", "name": N, "value": V}       set limits.N to V IN THIS PROCESS (N one of TEST_LIMITS): a test's own
                                                 wait, so that it can tell the uplink's wait from the SDK's; or a test's
                                                 own hold and life of seconds, because no test waits the shipped hour
                                                 out (uplink_aws.py, THE CHOICE, c and g). Given before `connect`. The
                                                 image's limits.py is not touched, and the connector has no such switch.
    {"op": "defer", "seconds": S}                A TEST'S OWN RACE, for connections built after it: the SDK's interrupted
                                                 callback is handed to the uplink S seconds late, from a thread of this
                                                 file's. So the SDK knows of a loss and the uplink does not. The SDK's
                                                 own thread is not held up: it returns at once (a sleep inside the
                                                 callback would stop the SDK's event loop, and its reconnecting with
                                                 it). The connector has no such switch.

Does not demonstrate: the connector (its loop and its limiter are not in this path); anything about the cloud service;
any timing (took_s is how long a call blocked here, read by tests only as "it came back").
"""
import json
import os
import sys
import threading
import time
from typing import Any

sys.dont_write_bytecode = True
sys.path.insert(0, "/app")          # the image's own modules, by their plain names

import limits  # noqa: E402
import uplink  # noqa: E402
import uplink_aws  # noqa: E402
from topics import Topics  # noqa: E402

TEST_LIMITS = {"CONNECT_WAIT_S": float, "SDK_RECONNECT_HOLD_S": int, "LINK_LIFE_MAX_S": float}          # what a test may set
#                                            in this process, and nothing else; the SDK takes its timer as whole seconds
DEFER_MAX_S = 120.0                        # the longest a test may hold the SDK's word of a loss back


def defer_losses(seconds: float, sdk_lost: Any) -> None:
    """From now on a connection the uplink builds learns of its loss `seconds` after the SDK said so, on another thread.
    `sdk_lost` is called when the SDK says so."""
    made = uplink_aws.AwsUplink._callbacks

    def callbacks(self: Any, link: Any) -> Any:
        own = made(self, link)
        told = own["on_connection_interrupted"]

        def interrupted(*args: Any, **kwargs: Any) -> None:          # the SDK's thread: back at once
            sdk_lost()
            later = threading.Timer(seconds, told, args, kwargs)
            later.daemon = True
            later.start()

        own["on_connection_interrupted"] = interrupted
        return own

    uplink_aws.AwsUplink._callbacks = callbacks          # type: ignore[method-assign]


def main() -> int:
    topics = Topics(os.environ.get("SDV_TWIN_THING"), os.environ.get("SDV_TWIN_RULE"))
    lock = threading.Lock()
    messages = []
    resumed = [0]
    sdk_lost = [0]
    up: Any = None

    def on_message(topic, payload):
        with lock:
            messages.append([topic, payload.hex(), type(payload).__name__])

    def on_resumed():
        resumed[0] += 1

    def on_sdk_lost():
        with lock:
            sdk_lost[0] += 1

    for line in sys.stdin:
        cmd = json.loads(line)
        op = cmd.get("op")
        out = {"op": op, "ok": True}
        began = time.monotonic()
        try:
            if op == "build":
                up = uplink_aws.from_env(os.environ, topics)
            elif op == "connect":
                up.connect(on_resumed)
            elif op == "subscribe":
                up.subscribe(cmd["topic"], on_message)
            elif op == "publish":
                up.publish(cmd["topic"], bytes.fromhex(cmd["hex"]), 1)
            elif op == "close":
                up.close()
            elif op == "limit":
                value = cmd.get("value")
                if cmd.get("name") not in TEST_LIMITS or isinstance(value, bool) or not isinstance(value, (int, float)):
                    out.update(ok=False, error="no such limit")
                else:
                    setattr(limits, cmd["name"], TEST_LIMITS[cmd["name"]](value))
            elif op == "defer":
                value = cmd.get("seconds")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= DEFER_MAX_S:
                    out.update(ok=False, error="no such delay")
                else:
                    defer_losses(float(value), on_sdk_lost)
            elif op != "state":
                out.update(ok=False, error="unknown command")
        except uplink.UplinkError:
            out.update(ok=False, error="UplinkError")
        except Exception as exc:  # noqa: BLE001 -- its class, never its text
            out.update(ok=False, error=type(exc).__name__)
        out["took_s"] = round(time.monotonic() - began, 2)
        if up is not None:
            out["counters"] = dict(up.counters)
        out["resumed"] = resumed[0]
        with lock:
            out["sdk_lost"] = sdk_lost[0]
            out["messages"] = [list(m) for m in messages]
        sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
