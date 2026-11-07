#!/usr/bin/env python3
"""app.py -- the hard-brake-hazard container's entry point: kuksa-client I/O around hazard.App.

Everything the app decides is in hazard.py; this file only moves
values between the local databroker and that core, and writes the core's log records.

  inputs   one kuksa.val.v2 Subscribe on the two inputs (hazard.INPUTS), with the buffer size of
           hazard.SUBSCRIBE_BUFFER; every update goes to App.on_input.
  monitor  a second, separate v2 Subscribe on the two Monitor leaves the app displays; every update
           goes to App.on_monitor, whose only output is a log record. A failure of this stream is
           logged and retried and never reaches the other streams. It takes its own lock (it touches
           only the display), never the one the inputs, the heartbeat and the actuation share, so no
           burst of Monitor updates can hold up an input or a heartbeat.
  heartbeat  App.on_heartbeat every hazard.HEARTBEAT_S, the first at start; its eight leaves are
           published with v2 PublishValue (kuksa-client's set with try_v2). Its time is read before
           the shared lock is taken: an input or an actuation in flight may delay the publication,
           never move the instant the record's state is judged at (a late read could otherwise judge
           fresh inputs stale and publish degraded).
  actuation  the kuksa.val.v1 target set of Vehicle.Body.Lights.Hazard.IsSignaling. Why v1: the
           pinned mock provider (kuksa-mock-provider 0.4.1, kuksa-client 0.4.3) serves actuators
           through v1 target subscriptions only, and databroker 0.7.1 answers a v2 Actuate for an
           actuator with no v2 provider UNAVAILABLE. Consequence: a v1 target set succeeds whether or
           not anything serves the actuator, so actuate_result is ok or error here and never
           unavailable.

Configuration (environment; nothing else is read):
  APP_IMAGE_ID   required, sha256:<64 hex>: the image ID the starter ran (AppState image_id); the
                 app refuses to start without it.
  KUKSA_ADDRESS  host:port of the databroker, default 127.0.0.1:55555.
  HBH_LOG        the JSON-lines log, default /out/hard-brake-hazard.jsonl.

Every log record carries t_wall (the host's realtime clock, time.time) and t (the monotonic clock
the core runs on). Neither is a timing claim; they order events and let a replay be mapped onto its
recording.
"""
import asyncio
import json
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from kuksa.val.v2 import val_pb2 as val_v2
from kuksa_client.grpc import DataEntry, Datapoint, DataType, EntryUpdate, Field, Metadata, VSSClientError
from kuksa_client.grpc.aio import VSSClient

import hazard

DATATYPES = {"uint8": DataType.UINT8, "uint32": DataType.UINT32, "string": DataType.STRING, "boolean": DataType.BOOLEAN}
RETRY_S = 1.0


class Log:
    def __init__(self, path: str) -> None:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._f = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, record: Dict[str, Any]) -> None:
        rec = dict(record)
        rec["t_wall"] = time.time()
        line = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        self._f.write(line + "\n")
        if rec.get("event") != "input":
            print(line, flush=True)

    def close(self) -> None:
        self._f.close()


def _value(dp: Any) -> Optional[Any]:
    """The value of a v2 Datapoint, or None when it carries none."""
    fields = dp.value.ListFields()
    if not fields:
        return None
    return getattr(dp.value, fields[0][0].name)


class Shell:
    def __init__(self, app: hazard.App, client: VSSClient, log: Log) -> None:
        self.app, self.client, self.log = app, client, log
        self.lock = asyncio.Lock()            # the inputs, the heartbeat, the actuation: the App's own state
        self.display_lock = asyncio.Lock()    # the Monitor display only (App.display)

    async def run_actions(self, actions: List[hazard.Action]) -> None:
        for act in actions:
            if isinstance(act, hazard.Note):
                self.log.write(act.record)
            elif isinstance(act, hazard.Publish):
                await self.publish(act)
            elif isinstance(act, hazard.Actuate):
                result = await self.actuate(act)
                await self.run_actions(self.app.on_actuated(act.value, result, time.monotonic()))

    async def publish(self, act: hazard.Publish) -> None:
        updates = [EntryUpdate(DataEntry(path, value=Datapoint(value), metadata=Metadata(data_type=DATATYPES[dt])), (Field.VALUE,))
                   for path, value, dt in act.leaves]
        try:
            await self.client.set(updates=updates, try_v2=True)
        except VSSClientError as exc:
            self.log.write({"event": "publish-error", "error": str(exc)[:300], "t": time.monotonic()})

    async def actuate(self, act: hazard.Actuate) -> str:
        upd = EntryUpdate(DataEntry(act.path, actuator_target=Datapoint(act.value), metadata=Metadata(data_type=DataType.BOOLEAN)),
                          (Field.ACTUATOR_TARGET,))
        try:
            await self.client.set(updates=[upd])
        except VSSClientError as exc:
            self.log.write({"event": "actuate-error", "error": str(exc)[:300], "t": time.monotonic()})
            return "error"
        return "ok"

    async def subscribe(self, paths: List[str], on_first: bool, handler: str, lock: asyncio.Lock) -> None:
        req = val_v2.SubscribeRequest(signal_paths=paths, buffer_size=hazard.SUBSCRIBE_BUFFER)
        first = True
        while True:
            try:
                async for resp in self.client.client_stub_v2.Subscribe(req):
                    t = time.monotonic()
                    async with lock:
                        if first and on_first:
                            await self.run_actions(self.app.on_subscribed(t))
                        first = False
                        for path in sorted(resp.entries):
                            fn = getattr(self.app, handler)
                            await self.run_actions(fn(path, _value(resp.entries[path]), t))
                self.log.write({"event": "subscription-ended", "paths": paths, "t": time.monotonic()})
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- any stream failure is logged and retried
                self.log.write({"event": "subscription-error", "paths": paths, "error": str(exc)[:300], "t": time.monotonic()})
            await asyncio.sleep(RETRY_S)

    async def beat(self) -> None:
        """One heartbeat, judged at the time read before the shared lock is taken."""
        t = time.monotonic()
        async with self.lock:
            await self.run_actions(self.app.on_heartbeat(t))

    async def heartbeat(self) -> None:
        while True:
            await self.beat()
            await asyncio.sleep(hazard.HEARTBEAT_S)


async def main() -> int:
    image_id = os.environ.get("APP_IMAGE_ID", "")
    try:
        app = hazard.App(image_id=image_id)
    except ValueError as exc:
        print("hard-brake-hazard: refusing to start: APP_IMAGE_ID: %s" % exc, file=sys.stderr)
        return 2
    host, _, port = os.environ.get("KUKSA_ADDRESS", "127.0.0.1:55555").rpartition(":")
    log = Log(os.environ.get("HBH_LOG", "/out/hard-brake-hazard.jsonl"))
    log.write({"event": "start", "app": hazard.APP_NAME, "app_version": hazard.APP_VERSION, "image_id": image_id,
               "decel_on": hazard.DECEL_ON_MPS2, "decel_off": hazard.DECEL_OFF_MPS2, "input_deadline_s": hazard.INPUT_DEADLINE_S,
               "heartbeat_s": hazard.HEARTBEAT_S, "actuation": "kuksa.val.v1 target set", "t": time.monotonic()})
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async with VSSClient(host, int(port), ensure_startup_connection=False) as client:
        shell = Shell(app, client, log)
        tasks = [asyncio.create_task(shell.heartbeat()),
                 asyncio.create_task(shell.subscribe(list(hazard.INPUTS), True, "on_input", shell.lock)),
                 asyncio.create_task(shell.subscribe(list(hazard.MONITOR_DISPLAY), False, "on_monitor", shell.display_lock))]
        await stop.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with shell.lock:
            await shell.run_actions(app.on_stop(time.monotonic()))
    log.write({"event": "stop", "t": time.monotonic()})
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
