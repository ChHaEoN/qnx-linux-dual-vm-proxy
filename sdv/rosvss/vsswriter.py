"""vsswriter.py -- the ROS->VSS feeder's writer path: the bounded queue between the subscription callbacks and the
databroker, the writer that maps each update and writes inside its run type's write set only, the start check, and
the counts log (sdv/rosvss; Phase 8 WP3a). Standard library only.

Local branch only (decision 15). One process (spec 2.8; D4's Jazzy branch): the callbacks run in rclpy's executor and
only build an update and put it on a LatestQueue, which never blocks; the writer runs in a thread of its own and is the
only caller of the sink (kuksa_out.KuksaOut, or a test's stand-in). So a slow or failing databroker never blocks a ROS
callback: the queue keeps the newest QUEUE_MAX updates and counts the ones it drops.

THE WRITER
  Each update is checked (update.check) and mapped (mapping.map_update); a refusal is counted by its code and logged
  once per code (a callback's refusal is counted at once and logged by the writer's thread: a callback does no I/O).
  An exception of any other type from the check or the mapping is a fault of the feeder's own, not of the update: it
  is counted under the refusal code ERROR_CODE, logged once per exception type by its type name only, and the writer
  goes on (no update can stop it). Each mapped path outside the run type's write set is counted (outside_write_set)
  and logged once by path; the rest are written in one sink call per update, with mapping.DATATYPES. A sink call
  that raises is counted per path (write_failed) and logged once per exception type, by its type name only; the
  writer goes on.
THE WRITER'S END
  run() returns when stop is set, after its last counts line. An exception that still escapes its loop (the log's
  own stream failing, as a closed stdout does) ends the thread instead: run() keeps the exception's type name in
  `died`, logs nothing further (the log may be what failed), calls on_failure (feeder_node gives rclpy.try_shutdown,
  which ends spin) and returns, so no traceback, whose text could quote a value, is printed; feeder_node then names
  the type on stderr and exits 1.
THE LOG (JSON lines; the caller gives the sink of the lines, the command line's is stdout)
  Counts, paths, refusal codes and exception type names only, never a value of any signal (a databroker's error text
  can quote one, so it is not logged): {"event": "refused", "code"}, {"event": "error", "error"},
  {"event": "outside-write-set", "path"}, {"event": "write-failed", "error", "paths"}, and {"event": "counts",
  "updates", "refused": {code: n}, "written": {path: n}, "outside_write_set": {path: n}, "write_failed": {path: n},
  "dropped", "queued", "final"} every COUNTS_PERIOD_S and once more when the writer stops. Each line carries mono_ns
  (CLOCK_MONOTONIC), a time, not a value.
THE START CHECK
  start_problems: every path of the run type's write set must be served by the databroker with mapping.DATATYPES'
  datatype (the claim bridge's start check, sdv/bridge/bridge_sources.py); a problem refuses the start.

DESIGN VALUES (none is generated)
  QUEUE_MAX = 512: five topics at up to 50 Hz each (a design rate, above the 30 ms control period of the single source;
    WP4a reads the real rates) over one write's longest wait (kuksa_out.WRITE_RPC_TIMEOUT_S = 2 s) is 500 updates, so
    one stalled write drops nothing at those rates. Past it the oldest go first, and a dropped update's values stay out
    of the databroker until a later update writes the same paths: its topic's next update for a vehicle topic, and
    for the verdict's counters and IsConnected (every verdict message writes them; the counters are cumulative); the
    next frame's message for the command leaves; the next replied frame's for Verdict, Reason and LastSeq. A value is
    lost for good only when no later update writes its path; `dropped` counts the updates dropped.
  COUNTS_PERIOD_S = 10 s: a reader of the container's log sees a stall within ten seconds, and the log stays a few
    lines a minute.
  POLL_S = 0.2 s: the writer's longest wait for an update, so a stop ends it within that (plus a write in flight).

DOES NOT DEMONSTRATE: any timing (the queue's bound is a design value, not a measured rate); that the databroker took
a value it was sent beyond the sink call returning.
"""
from __future__ import annotations

import collections
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import mapping  # noqa: E402
import update as upd  # noqa: E402

QUEUE_MAX = 512
COUNTS_PERIOD_S = 10.0
POLL_S = 0.2
ERROR_CODE = "error"           # the refusal code of an update the check or the mapping raised on with no Refused


class LatestQueue:
    """A bounded queue that never blocks a put: when full, the oldest item is dropped and counted."""

    def __init__(self, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self.maxsize = maxsize
        self._items: Deque[Any] = collections.deque()
        self._cond = threading.Condition()
        self.dropped = 0

    def put(self, item: Any) -> None:
        with self._cond:
            if len(self._items) >= self.maxsize:
                self._items.popleft()
                self.dropped += 1
            self._items.append(item)
            self._cond.notify()

    def get(self, timeout: float) -> Any:
        """The oldest item, or None after timeout seconds with none."""
        with self._cond:
            if not self._items:
                self._cond.wait(timeout)
            return self._items.popleft() if self._items else None

    def __len__(self) -> int:
        with self._cond:
            return len(self._items)


def start_problems(served: Mapping[str, Optional[str]], run_type: str) -> List[str]:
    """What keeps the feeder from starting: each write-set path the databroker does not serve, or serves with another
    datatype than mapping.DATATYPES'. served: {path: datatype, lower case}."""
    problems = []
    for path in sorted(mapping.write_set(run_type)):
        got = served.get(path)
        if got is None:
            problems.append("the databroker serves no %s" % path)
        elif got != mapping.DATATYPES[path]:
            problems.append("the databroker serves %s as %s, not %s" % (path, got, mapping.DATATYPES[path]))
    return problems


class Writer:
    """The writer path (module docstring). handle(), run() and the log run in the writer's thread; refuse() may be
    called from the callbacks' thread and only counts; the counters' lock is never held during a sink call.
    on_failure: called once by run() when an exception ends the thread (THE WRITER'S END); `died` is then the
    exception's type name, and None until then."""

    def __init__(self, run_type: str, sink: Any, log: Callable[[Dict[str, Any]], None],
                 clock: Callable[[], int] = time.monotonic_ns, on_failure: Optional[Callable[[], None]] = None) -> None:
        self.run_type = run_type
        self.write_set = mapping.write_set(run_type)
        self.sink = sink
        self._log = log
        self.clock = clock
        self.on_failure = on_failure
        self.died: Optional[str] = None
        self._lock = threading.Lock()
        self._queue: Any = None
        self.updates = 0
        self.refused: Dict[str, int] = {}
        self.written: Dict[str, int] = {}
        self.outside: Dict[str, int] = {}
        self.failed: Dict[str, int] = {}
        self._failed_types: Set[str] = set()
        self._error_types: Set[str] = set()
        self._unlogged: List[str] = []

    def log(self, event: str, **kw: Any) -> None:
        rec: Dict[str, Any] = {"event": event, "mono_ns": int(self.clock())}
        rec.update(kw)
        self._log(rec)

    def refuse(self, code: str) -> None:
        """Count a refusal by its code (any thread, no I/O); the writer's thread logs the code the first time."""
        with self._lock:
            n = self.refused.get(code, 0)
            self.refused[code] = n + 1
            if n == 0:
                self._unlogged.append(code)

    def flush_refusals(self) -> None:
        """Log each refusal code counted for the first time since the last flush (the writer's thread)."""
        with self._lock:
            codes, self._unlogged = self._unlogged, []
        for code in codes:
            self.log("refused", code=code)

    def handle(self, update: Dict[str, Any]) -> None:
        with self._lock:
            self.updates += 1
        try:
            upd.check(update)
            items = mapping.map_update(update)
        except upd.Refused as err:
            self.refuse(err.code)
            self.flush_refusals()
            return
        except Exception as fault:  # noqa: BLE001 -- the feeder's own fault, not the update's: counted, never fatal
            kind = type(fault).__name__
            self.refuse(ERROR_CODE)
            with self._lock:
                first_kind = kind not in self._error_types
                self._error_types.add(kind)
            self.flush_refusals()
            if first_kind:
                self.log("error", error=kind)
            return
        inside: List[Tuple[str, Any, str]] = []
        first_outside = []
        with self._lock:
            for path, value in items:
                if path not in self.write_set:
                    n = self.outside.get(path, 0)
                    self.outside[path] = n + 1
                    if n == 0:
                        first_outside.append(path)
                    continue
                inside.append((path, value, mapping.DATATYPES[path]))
        for path in first_outside:
            self.log("outside-write-set", path=path)
        if not inside:
            return
        paths = [p for p, _v, _t in inside]
        try:
            self.sink.publish(inside)
        except Exception as err:  # noqa: BLE001 -- a failing databroker is counted, never fatal
            name = type(err).__name__
            with self._lock:
                for p in paths:
                    self.failed[p] = self.failed.get(p, 0) + 1
                first = name not in self._failed_types
                self._failed_types.add(name)
            if first:
                self.log("write-failed", error=name, paths=paths)
            return
        with self._lock:
            for p in paths:
                self.written[p] = self.written.get(p, 0) + 1

    def counts(self) -> Dict[str, Any]:
        q = self._queue
        with self._lock:
            return {"updates": self.updates, "refused": dict(sorted(self.refused.items())),
                    "written": dict(sorted(self.written.items())), "outside_write_set": dict(sorted(self.outside.items())),
                    "write_failed": dict(sorted(self.failed.items())),
                    "dropped": int(q.dropped) if q is not None else 0, "queued": len(q) if q is not None else 0}

    def log_counts(self, final: bool) -> None:
        self.flush_refusals()
        self.log("counts", final=final, **self.counts())

    def run(self, queue: Any, stop: threading.Event) -> None:
        """Take updates from queue until stop is set; a counts line every COUNTS_PERIOD_S and one at the end. An
        exception that escapes ends the thread as THE WRITER'S END says, with no traceback."""
        try:
            self._run(queue, stop)
        except Exception as end:  # noqa: BLE001 -- reported by feeder_node, by the type name only
            self.died = type(end).__name__
            if self.on_failure is not None:
                try:
                    self.on_failure()
                except Exception:  # noqa: BLE001 -- the end being reported is the writer's, not this one's
                    pass

    def _run(self, queue: Any, stop: threading.Event) -> None:
        self._queue = queue
        period = int(COUNTS_PERIOD_S * 1_000_000_000)
        next_counts = self.clock() + period
        while not stop.is_set():
            item = queue.get(POLL_S)
            if item is not None:
                self.handle(item)
            self.flush_refusals()
            now = self.clock()
            if now >= next_counts:
                self.log_counts(final=False)
                next_counts = now + period
        self.log_counts(final=True)


class JsonLog:
    """A log sink: one compact JSON object per line on a text stream, flushed."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self._lock = threading.Lock()

    def __call__(self, rec: Dict[str, Any]) -> None:
        line = json.dumps(rec, separators=(",", ":"), sort_keys=True)
        with self._lock:
            self.stream.write(line + "\n")
            self.stream.flush()
