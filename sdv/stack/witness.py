"""witness.py -- a buffered kuksa.val.v2 subscriber on the CAN-fed paths: every replay's exact value witness (sdv/stack).

Project-written. Run by stack.py in the recorder image -- python:3.12-slim by digest with
kuksa-client 0.6.0 and its resolution, the same pinned versions and hashes as the app's lock
(tests/test_sdv_stack.py holds the pins equal) -- with `--entrypoint python` and this file
mounted read-only, in the databroker's network namespace (--feed dumpfile) or the host's (vcan):

    python witness.py HOST:PORT LOG PATH [PATH ...]

WHAT IT DOES
  One kuksa.val.v2 Subscribe on the given paths (stack.py passes the six the CAN provider writes: the
  five kind 4 slots and Vehicle.Speed) with buffer_size BUFFER_SIZE. Every value that arrives is one
  JSON line {"event": "value", "path", "value", "initial", "t", "t_wall"} in LOG, in arrival order:
  sdv/stack/replaycheck.py compares these, count for count and value for value, with the recording
  decoded by cantools. The first response is the databroker's initial notification (the current
  values; before the provider starts there are none) and its values, if any, are marked initial.
  Other records: start, subscribed (at the first response), subscription-error, stream-ended, and
  stop with the number of values per path, written on SIGTERM or SIGINT (which cancel the stream) and
  on any end. A stream that ends or fails is not retried: a gap would be invisible, so the program
  logs it and exits 1.

DESIGN VALUE
  BUFFER_SIZE = 1000: the largest buffer databroker 0.7.1 accepts for a v2 subscription
  (MAX_SUBSCRIBE_BUFFER_SIZE at the pinned revision; a larger one is refused with InvalidArgument).
  The databroker then queues up to 1001 notifications for this subscriber and drops the oldest only
  beyond that, logging "Slow subscriber with capacity 1001 lagged": at the slice's message rates that
  is many seconds of the whole feed, where the recorder's v1 subscription holds one. A drop would
  show as a count below the recording's and in the databroker's log, never be hidden.

Does not demonstrate: that nothing else wrote these paths (the databroker runs without
authorization), which component wrote a value, or any timing (t and t_wall only order the records).
"""
import json
import signal
import sys
import time

import grpc
from kuksa.val.v2 import val_pb2 as v2
from kuksa.val.v2 import val_pb2_grpc as g2

BUFFER_SIZE = 1000


def value_of(dp):
    """The value a v2 Datapoint carries, or None when it carries none."""
    fields = dp.value.ListFields()
    if not fields:
        return None
    return getattr(dp.value, fields[0][0].name)


def main(argv):
    if len(argv) < 4:
        print("usage: witness.py HOST:PORT LOG PATH [PATH ...]", file=sys.stderr)
        return 2
    target, log_path, paths = argv[1], argv[2], list(argv[3:])
    log = open(log_path, "a", encoding="utf-8", buffering=1)

    def write(record):
        rec = dict(record, t_wall=time.time())
        line = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        log.write(line + "\n")
        if rec["event"] != "value":
            print(line, flush=True)

    counts = {p: 0 for p in paths}
    write({"event": "start", "target": target, "paths": paths, "buffer_size": BUFFER_SIZE, "t": time.monotonic()})
    channel = grpc.insecure_channel(target)
    call = g2.VALStub(channel).Subscribe(v2.SubscribeRequest(signal_paths=paths, buffer_size=BUFFER_SIZE), wait_for_ready=True)
    stopping = []

    def on_signal(signum, _frame):
        stopping.append(signum)
        call.cancel()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    rc = 0
    first = True
    try:
        for resp in call:
            t = time.monotonic()
            if first:
                write({"event": "subscribed", "paths": paths, "t": t})
            for path in sorted(resp.entries):
                value = value_of(resp.entries[path])
                if value is None:
                    continue
                counts[path] = counts.get(path, 0) + 1
                write({"event": "value", "path": path, "value": value, "initial": first, "t": t})
            first = False
        if not stopping:
            write({"event": "stream-ended", "t": time.monotonic()})
            rc = 1
    except grpc.RpcError as exc:
        if not (stopping and exc.code() == grpc.StatusCode.CANCELLED):
            write({"event": "subscription-error", "code": exc.code().name, "error": str(exc.details())[:300], "t": time.monotonic()})
            rc = 1
    write({"event": "stop", "counts": counts, "signal": stopping[0] if stopping else None, "t": time.monotonic()})
    log.close()
    channel.close()
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
