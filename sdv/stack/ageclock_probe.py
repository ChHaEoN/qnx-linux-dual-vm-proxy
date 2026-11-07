"""ageclock_probe.py -- who stamps a databroker datapoint, on which clock, and whether an identical value
refreshes the stamp and reaches a v2 subscriber (sdv/stack; SDV Phase 2 WP8).

Project-written. The kind 4 wire specification (the project's local design notes, section 17.1 items 1
and 2; not in this tree) leaves open what a broker-mode claim bridge ages its values against: the
datapoint timestamp, set by the provider or by the databroker on receipt, on CLOCK_REALTIME or
CLOCK_MONOTONIC; and whether a value written again unchanged (a constant gear, a zero steering angle)
refreshes that timestamp and is notified, or ages honestly into reason 22. Run by stack.py (`stack.py
ageprobe`) in the recorder image (kuksa-client 0.6.0's generated kuksa.val.v1 and v2 modules and grpc),
joined to a throwaway databroker's network namespace, so its clocks are the host kernel's:

    python ageclock_probe.py HOST:PORT --float PATH [--float PATH ...] --int8 PATH

Prints one JSON object. Every write goes to a path the throwaway databroker serves and nothing else reads.

CASES
  write   On the first --float path: kuksa.val.v1 Set and kuksa.val.v2 PublishValue, each with no timestamp
          ("untimed") and with an explicit one ("timed": EXPLICIT_OFFSET_S before the call on
          CLOCK_REALTIME, far from any receipt time). Each value is new. After each, the datapoint is read
          back with v1 Get and v2 GetValue, and its timestamp is classified against the probe's own
          CLOCK_REALTIME and CLOCK_MONOTONIC readings taken just before the write and just after the
          read-back (`receipt-realtime`, `explicit`, `monotonic`, or `other`).
  repeat  The same value written REPEATS times, REPEAT_GAP_S apart: by v1 Set untimed -- the call the CAN
          provider 0.5.0 makes for every mapped frame -- on every --float and --int8 path, and by v2
          PublishValue untimed on the first --float path. After each write, the read-back timestamp; after
          the case, the v2 notifications of that value the subscriber received.
  The subscriber is one kuksa.val.v2 Subscribe on every probed path (buffer SUBSCRIBE_BUFFER, as the
  bridge's), started before the first write; each notification is kept with its datapoint timestamp and
  the probe's CLOCK_REALTIME and CLOCK_MONOTONIC at arrival.

VERDICT (in the output's `verdict`; the raw readings are beside it)
  stamped_on_receipt   every read-back timestamp, timed writes included, lies between the realtime readings
                       around its write: the databroker stamps on receipt, and an explicit timestamp is not
                       what it serves back.
  clock                CLOCK_REALTIME when every read-back timestamp is a receipt-realtime one and none
                       falls in its monotonic window.
  repeat_refreshes     every repeated write gave a read-back timestamp later than the one before.
  repeat_notifies_v2   the subscriber received one notification per repeated write, on every repeat case.
  v1_v2_agree          v1 Get and v2 GetValue served the same timestamp after every write.

DESIGN VALUES (of this probe, none a claim): EXPLICIT_OFFSET_S = 3600 s, so an explicit timestamp cannot
be mistaken for a receipt; REPEATS = 3 and REPEAT_GAP_S = 0.2 s, apart enough that two receipt times differ
at the timestamp's resolution; NOTIFY_WAIT_S = 0.5 s for the last notification to arrive.

Does not demonstrate: any timing (the readings order events and bound them; none is a latency), what a
provider other than the calls made here does, or the behaviour of any databroker other than the one probed.
"""
import json
import sys
import threading
import time

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from kuksa.val.v1 import types_pb2 as t1
from kuksa.val.v1 import val_pb2 as v1
from kuksa.val.v1 import val_pb2_grpc as g1
from kuksa.val.v2 import types_pb2 as t2
from kuksa.val.v2 import val_pb2 as v2
from kuksa.val.v2 import val_pb2_grpc as g2

EXPLICIT_OFFSET_S = 3600
REPEATS = 3
REPEAT_GAP_S = 0.2
NOTIFY_WAIT_S = 0.5
SUBSCRIBE_BUFFER = 1000
RPC_TIMEOUT_S = 10


def ts_ns(ts):
    return ts.seconds * 1_000_000_000 + ts.nanos


def stamp(ns):
    t = Timestamp()
    t.seconds, t.nanos = divmod(ns, 1_000_000_000)
    return t


def clocks():
    return {"realtime_ns": time.clock_gettime_ns(time.CLOCK_REALTIME), "monotonic_ns": time.clock_gettime_ns(time.CLOCK_MONOTONIC)}


def classify(t, before, after, explicit=None):
    """Where a served timestamp t lies: between the realtime readings around the write and its read-back, at
    the explicit timestamp the write carried, or between the monotonic readings."""
    if t is None:
        return "none"
    if before["realtime_ns"] <= t <= after["realtime_ns"]:
        return "receipt-realtime"
    if explicit is not None and t == explicit:
        return "explicit"
    if before["monotonic_ns"] <= t <= after["monotonic_ns"]:
        return "monotonic"
    return "other"


class Probe:
    def __init__(self, target, floats, int8s):
        self.channel = grpc.insecure_channel(target)
        self.s1 = g1.VALStub(self.channel)
        self.s2 = g2.VALStub(self.channel)
        self.kind = dict([(p, "float") for p in floats] + [(p, "int8") for p in int8s])
        self.notes = []
        self.lock = threading.Lock()
        self.subscribed = threading.Event()
        self.call = None

    # -- the subscriber --

    def subscribe(self):
        self.call = self.s2.Subscribe(v2.SubscribeRequest(signal_paths=sorted(self.kind), buffer_size=SUBSCRIBE_BUFFER),
                                      wait_for_ready=True)
        threading.Thread(target=self._drain, daemon=True).start()
        if not self.subscribed.wait(RPC_TIMEOUT_S):
            raise RuntimeError("the v2 subscription gave no first response")

    def _drain(self):
        first = True
        try:
            for resp in self.call:
                c = clocks()
                with self.lock:
                    for path, dp in resp.entries.items():
                        fields = dp.value.ListFields()
                        self.notes.append({"path": path, "value": getattr(dp.value, fields[0][0].name) if fields else None,
                                           "timestamp_ns": ts_ns(dp.timestamp) if dp.HasField("timestamp") else None,
                                           "initial": first, "arrival": c})
                first = False
                self.subscribed.set()
        except grpc.RpcError:
            pass

    def notifications(self, path, value, since_ns):
        with self.lock:
            return [n for n in self.notes if n["path"] == path and n["value"] == value and not n["initial"]
                    and n["arrival"]["realtime_ns"] >= since_ns]

    # -- writes and reads --

    def v1_set(self, path, value, explicit_ns=None):
        dp = t1.Datapoint(**{"float" if self.kind[path] == "float" else "int32": value})
        if explicit_ns is not None:
            dp.timestamp.CopyFrom(stamp(explicit_ns))
        resp = self.s1.Set(v1.SetRequest(updates=[v1.EntryUpdate(entry=t1.DataEntry(path=path, value=dp), fields=[t1.FIELD_VALUE])]),
                           timeout=RPC_TIMEOUT_S)
        errs = [str(e).strip() for e in resp.errors] + ([str(resp.error).strip()] if resp.HasField("error") else [])
        if errs:
            raise RuntimeError("v1 Set %s=%r refused: %s" % (path, value, errs))

    def v2_publish(self, path, value, explicit_ns=None):
        dp = t2.Datapoint(value=t2.Value(**{"float" if self.kind[path] == "float" else "int32": value}))
        if explicit_ns is not None:
            dp.timestamp.CopyFrom(stamp(explicit_ns))
        self.s2.PublishValue(v2.PublishValueRequest(signal_id=t2.SignalID(path=path), data_point=dp), timeout=RPC_TIMEOUT_S)

    def read_back(self, path):
        r1 = self.s1.Get(v1.GetRequest(entries=[v1.EntryRequest(path=path, view=t1.VIEW_CURRENT_VALUE, fields=[t1.FIELD_VALUE])]),
                         timeout=RPC_TIMEOUT_S)
        e = r1.entries[0].value if r1.entries else None
        r2 = self.s2.GetValue(v2.GetValueRequest(signal_id=t2.SignalID(path=path)), timeout=RPC_TIMEOUT_S)
        return {"v1_get_ns": ts_ns(e.timestamp) if e is not None and e.HasField("timestamp") else None,
                "v2_getvalue_ns": ts_ns(r2.data_point.timestamp) if r2.data_point.HasField("timestamp") else None}

    def write_case(self, api, path, value, timed):
        before = clocks()
        explicit = before["realtime_ns"] - EXPLICIT_OFFSET_S * 1_000_000_000 if timed else None
        (self.v1_set if api == "v1-set" else self.v2_publish)(path, value, explicit)
        back = self.read_back(path)
        after = clocks()
        time.sleep(NOTIFY_WAIT_S)
        notes = self.notifications(path, value, before["realtime_ns"])
        return {"case": "%s-%s" % (api, "timed" if timed else "untimed"), "path": path, "value": value, "explicit_ns": explicit,
                "before": before, "after": after, "read_back": back,
                "where": {k: classify(t, before, after, explicit) for k, t in back.items()},
                "notified": [{"timestamp_ns": n["timestamp_ns"], "arrival": n["arrival"],
                              "where": classify(n["timestamp_ns"], before, n["arrival"], explicit)} for n in notes]}

    def repeat_case(self, api, path, value):
        start = clocks()
        writes = []
        for _ in range(REPEATS):
            before = clocks()
            (self.v1_set if api == "v1-set" else self.v2_publish)(path, value)
            back = self.read_back(path)
            after = clocks()
            writes.append({"before": before, "after": after, "read_back": back,
                           "where": {k: classify(t, before, after) for k, t in back.items()}})
            time.sleep(REPEAT_GAP_S)
        time.sleep(NOTIFY_WAIT_S)
        notes = self.notifications(path, value, start["realtime_ns"])
        stamps = [w["read_back"]["v2_getvalue_ns"] for w in writes]
        return {"case": "%s-repeat" % api, "path": path, "kind": self.kind[path], "value": value, "writes": writes,
                "read_back_increasing": all(b is not None and a is not None and b > a for a, b in zip(stamps, stamps[1:])),
                "notifications": len(notes),
                "notified_timestamps_ns": [n["timestamp_ns"] for n in notes]}


def verdict(writes, repeats):
    every = [w["where"] for w in writes] + [x["where"] for r in repeats for x in r["writes"]]
    backs = [w["read_back"] for w in writes] + [x["read_back"] for r in repeats for x in r["writes"]]
    receipt = all(v == "receipt-realtime" for where in every for v in where.values())
    return {
        "stamped_on_receipt": receipt,
        "explicit_timestamp_served": any(v == "explicit" for where in every for v in where.values()),
        "clock": "CLOCK_REALTIME" if receipt and not any(v == "monotonic" for where in every for v in where.values()) else "undetermined",
        "repeat_refreshes": all(r["read_back_increasing"] for r in repeats),
        "repeat_notifies_v2": all(r["notifications"] == REPEATS for r in repeats),
        "v1_v2_agree": all(b["v1_get_ns"] == b["v2_getvalue_ns"] for b in backs),
    }


def main(argv):
    target, rest = argv[1], list(argv[2:])
    floats, int8s, bad = [], [], len(rest) % 2 != 0
    for flag, path in zip(rest[0::2], rest[1::2]):
        if flag == "--float":
            floats.append(path)
        elif flag == "--int8":
            int8s.append(path)
        else:
            bad = True
    if bad or not floats or not int8s:
        print("usage: ageclock_probe.py HOST:PORT --float PATH [--float PATH ...] --int8 PATH", file=sys.stderr)
        return 2
    p = Probe(target, floats, int8s)
    out = {"target": target, "design_values": {"explicit_offset_s": EXPLICIT_OFFSET_S, "repeats": REPEATS,
                                               "repeat_gap_s": REPEAT_GAP_S, "notify_wait_s": NOTIFY_WAIT_S,
                                               "subscribe_buffer": SUBSCRIBE_BUFFER}}
    info = p.s2.GetServerInfo(v2.GetServerInfoRequest(), timeout=RPC_TIMEOUT_S)
    out["server"] = {"name": info.name, "version": info.version, "commit_hash": info.commit_hash}
    p.subscribe()
    first = floats[0]
    writes = []
    value = 10.5
    for api in ("v1-set", "v2-publish"):
        for timed in (False, True):
            writes.append(p.write_case(api, first, value, timed))
            value += 1.0
    repeats = []
    for path in floats + int8s:
        repeats.append(p.repeat_case("v1-set", path, 2.5 if p.kind[path] == "float" else 3))
    repeats.append(p.repeat_case("v2-publish", first, 7.5))
    out["writes"] = writes
    out["repeats"] = repeats
    out["verdict"] = verdict(writes, repeats)
    p.call.cancel()
    p.channel.close()
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
