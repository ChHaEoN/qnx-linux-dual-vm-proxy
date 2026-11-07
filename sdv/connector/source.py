"""source.py -- the twin connector's signal source: the latest value of each path it subscribed to (sdv/connector;
SDV Phase 4 WP2).

The standard library only at import; gRPC and kuksa-client's generated kuksa.val.v2
modules are imported inside GrpcStream, when a real databroker is asked for.

THE SEAM, three calls
    subscribe(paths)   from now on, serve exactly these paths and nothing else. Called again with another set, it
                       drops the old subscription and what it had delivered for every path no longer asked for.
    latest()           {path: value} for every subscribed path that has a value now. A path with no value is absent.
    close()            end the subscription.

The connector calls subscribe with its effective set, each an exact leaf, and samples latest() on its own tick. It
never asks for a branch, and that is the first of its two layers: what it does not subscribe to, it never holds.

KuksaSource is the seam on the local databroker: one kuksa.val.v2 Subscribe (the stub and the request of
sdv/stack/witness.py and the bridge's KuksaBroker, on an insecure channel of its own; the first response carries the
databroker's current values), the value of each datapoint taken as the bridge takes it (the one typed field it
carries, or nothing), a path that was not asked for dropped though the databroker sent it, and a stream that ended or
failed opened again after limits.SOURCE_RETRY_S, as the app's subscription is. What a dead stream had delivered is
not kept: "the latest value" means a live subscription, and the next stream's first response carries the current
values again. A new subscription (a narrowing) is not a dead stream: a path that is still asked for keeps its latest
value while the new stream opens. The stream runs on a thread of its own; latest() copies under a lock.

FakeSource is the seam for the tests: a table of values standing for the databroker, scripted updates, a record of
every subscribe call and of every path it ever handed over. Asked for a branch it serves every leaf under it, as the
worst databroker would, so that a connector which subscribed by branch is seen to receive what it must not.

Does not demonstrate: KuksaSource against a databroker (it is driven by a fake stream in CI; the real one is WP3's
local slice), what the databroker does with a path its catalogue lacks, or any timing.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Protocol, Sequence, Set, Tuple

import limits


class Source(Protocol):
    def subscribe(self, paths: Sequence[str]) -> None: ...

    def latest(self) -> Dict[str, Any]: ...

    def close(self) -> None: ...


def value_of(datapoint: Any) -> Any:
    """The value a kuksa.val.v2 Datapoint carries: its one typed field, or None when it carries none."""
    fields = datapoint.value.ListFields()
    if not fields:
        return None
    return getattr(datapoint.value, fields[0][0].name)


class GrpcStream:
    """kuksa.val.v2 Subscribe on an insecure channel to the local databroker. `modules` stands in for (grpc, val_pb2,
    val_pb2_grpc) in the tests; left out, the three are imported here."""

    def __init__(self, target: str, modules: Optional[Tuple[Any, Any, Any]] = None) -> None:
        if modules is None:
            import grpc
            from kuksa.val.v2 import val_pb2, val_pb2_grpc
            modules = (grpc, val_pb2, val_pb2_grpc)
        self._grpc, self._val, stubs = modules
        self._channel = self._grpc.insecure_channel(target)
        self._stub = stubs.VALStub(self._channel)

    def open(self, paths: Sequence[str], buffer_size: int) -> Any:
        """One Subscribe call for exactly `paths`: an iterable of responses with a cancel()."""
        request = self._val.SubscribeRequest(signal_paths=list(paths), buffer_size=buffer_size)
        return self._stub.Subscribe(request, wait_for_ready=True)

    def close(self) -> None:
        self._channel.close()


class KuksaSource:
    """The source on a databroker, through `stream` (a GrpcStream)."""

    def __init__(self, stream: Any, sleep: Callable[[float], None] = time.sleep, retry_s: float = limits.SOURCE_RETRY_S,
                 buffer_size: int = limits.SUBSCRIBE_BUFFER) -> None:
        self._stream = stream
        self._sleep = sleep
        self._retry_s = retry_s
        self._buffer = buffer_size
        self._lock = threading.Lock()
        self._generation = 0
        self._want: FrozenSet[str] = frozenset()
        self._values: Dict[str, Any] = {}
        self._call: Any = None
        self._thread: Optional[threading.Thread] = None
        self.counters: Dict[str, int] = {"opened": 0, "responses": 0, "failed": 0, "ended": 0}
        self.last_error: Optional[str] = None          # the class of the last stream failure, never its text

    def subscribe(self, paths: Sequence[str]) -> None:
        wanted = tuple(paths)
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._want = frozenset(wanted)
            self._values = {p: v for p, v in self._values.items() if p in self._want}
            call, self._call = self._call, None
        if call is not None:
            call.cancel()
        if wanted:
            thread = threading.Thread(target=self._pump, args=(generation, wanted), name="twin-source", daemon=True)
            self._thread = thread
            thread.start()

    def latest(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def close(self) -> None:
        self.subscribe(())
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._stream.close()

    def _current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _pump(self, generation: int, paths: Tuple[str, ...]) -> None:
        """One subscription's life: open the stream, keep the latest value of each wanted path, and when the stream
        ends or fails, forget what it delivered and open it again after the retry interval; until another
        subscription or close() takes over."""
        while self._current(generation):
            try:
                call = self._stream.open(paths, self._buffer)
                with self._lock:
                    if generation != self._generation:
                        call.cancel()
                        return
                    self._call = call
                    self.counters["opened"] += 1
                for response in call:
                    with self._lock:
                        if generation != self._generation:
                            return
                        self.counters["responses"] += 1
                        for path, datapoint in response.entries.items():
                            if path not in self._want:
                                continue          # not asked for: dropped here, whatever the databroker sent
                            value = value_of(datapoint)
                            if value is not None:
                                self._values[path] = value
                outcome = "ended"
                error = None
            except Exception as exc:  # noqa: BLE001 -- any stream failure is counted and the stream opened again
                outcome = "failed"
                error = type(exc).__name__
            with self._lock:
                if generation != self._generation:
                    return          # cancelled by a new subscription or by close(): not a failure
                self.counters[outcome] += 1
                if error is not None:
                    self.last_error = error
                self._values = {}
                self._call = None
            self._sleep(self._retry_s)


class FakeSource:
    """A table of values standing for the databroker. `script(n)`, when given, returns the updates to apply before
    the n-th read (n from 1)."""

    def __init__(self, values: Optional[Mapping[str, Any]] = None, script: Optional[Callable[[int], Mapping[str, Any]]] = None) -> None:
        self.values: Dict[str, Any] = dict(values or {})
        self.script = script
        self.calls: List[Tuple[str, ...]] = []          # every subscribe call, as it was made
        self.handed: Set[str] = set()                   # every path a value was ever handed over for
        self.reads = 0
        self.closed = 0
        self._asked: Tuple[str, ...] = ()

    def set(self, path: str, value: Any) -> None:
        self.values[path] = value

    def subscribe(self, paths: Iterable[str]) -> None:
        self._asked = tuple(paths)
        self.calls.append(self._asked)

    def latest(self) -> Dict[str, Any]:
        self.reads += 1
        if self.script is not None:
            self.values.update(self.script(self.reads))
        out = {}
        for path, value in self.values.items():
            if value is None:
                continue
            if any(path == asked or path.startswith(asked + ".") for asked in self._asked):
                out[path] = value
        self.handed |= set(out)
        return out

    def close(self) -> None:
        self.closed += 1
        self._asked = ()
