"""subscribe_probe.py -- what a kuksa.val.v2 Subscribe gives for an actuator's current value, an attribute and
string leaves (sdv/connector/probes; SDV Phase 4 WP0, probe 1).

Run by probe.py (`probe.py databroker`) in the recorder image (kuksa-client
0.6.0's generated kuksa.val.v2 modules and grpc), joined to a throwaway databroker's network namespace; prints
one JSON object.

    python subscribe_probe.py HOST:PORT PLAN.json

WHY
  The twin connector will subscribe, with one kuksa.val.v2 Subscribe, to the paths of its allowlist. Every v2
  subscription on this branch so far is on sensors with numeric values. The allowlist also holds an actuator's
  current value, an attribute and string leaves, and no run here has shown what the databroker's first
  response carries for those, or whether a later write to one arrives. PLAN.json is probe.py's: for each path
  its catalogue type, datatype and default, and the value to write (never the default).

WHAT IT DOES, in this order, against a databroker nothing else writes to
  1. kuksa.val.v2 GetServerInfo, and ListMetadata for each path (the entry type and data type as served).
  2. `first_before`: one Subscribe on every path, before any write; its first response, path by path (whether
     the path is in the response, and the value if it carries one). A catalogue default is the only value a
     path can have at this point.
  3. `write`, `later_write`: for each path in turn, one PublishValue of the plan's value (accepted, or refused
     with its status), then that same subscription read until a response carries the path with that value, or
     WRITE_WAIT_S passes.
  4. `first_after`: a second Subscribe on every path, opened after the writes; its first response, path by path.
  5. `get_value`: GetValue for each path (what a reader that does not subscribe would be served).
  `summary` (summarise): per path, whether its default was in the first response, whether the write was
  accepted, whether it arrived on the open subscription, and whether the later subscription's first response
  and GetValue each carried the current value (the written one, or the default when the write was refused).

DESIGN VALUES (of this probe, none a claim): FIRST_WAIT_S = 10 s for a subscription's first response,
WRITE_WAIT_S = 5 s for a write to arrive, BUFFER_SIZE = 100 (the app's), RPC_TIMEOUT_S = 10 s per unary call.

Does not demonstrate: any timing (the waits bound the probe, they are not latencies); what a provider other
than PublishValue does (the stack's mock provider serves the actuator through kuksa.val.v1); a databroker
other than the one probed; or anything about a subscription that outlives its databroker.
"""
import json
import queue
import sys
import threading

FIRST_WAIT_S = 10.0
WRITE_WAIT_S = 5.0
BUFFER_SIZE = 100
RPC_TIMEOUT_S = 10

# VSS datatype -> the kuksa.val.v2 Value field that carries it.
_FIELDS = {"boolean": "bool", "string": "string", "uint8": "uint32", "uint16": "uint32", "uint32": "uint32",
           "int8": "int32", "int16": "int32", "int32": "int32", "float": "float"}


def value_field(datatype):
    try:
        return _FIELDS[datatype]
    except KeyError:
        raise ValueError("no kuksa.val.v2 value field for datatype %r" % (datatype,)) from None


def summarise(paths):
    """What the databroker did, path by path, from the probe's own records (pure)."""
    out = {"default_in_first_response": {}, "write_accepted": {}, "later_write_arrives": {},
           "first_response_carries_current_value": {}, "get_value_serves_current_value": {}}
    for path, r in paths.items():
        default, write = r["plan"]["default"], r["plan"]["write"]
        if default is not None:          # only a path the catalogue gives a default has a value before any write
            out["default_in_first_response"][path] = bool(r["first_before"]["in_response"]) and r["first_before"]["value"] == default
        accepted = r["write"]["result"] == "accepted"
        current = write if accepted else default
        out["write_accepted"][path] = accepted
        out["later_write_arrives"][path] = bool(r["later_write"]["arrived"])
        out["first_response_carries_current_value"][path] = (
            None if current is None else bool(r["first_after"]["in_response"]) and r["first_after"]["value"] == current)
        out["get_value_serves_current_value"][path] = None if current is None else r["get_value"].get("value") == current
    return out


def _value_of(dp):
    """The value a v2 Datapoint carries, or None when it carries none."""
    fields = dp.value.ListFields()
    return getattr(dp.value, fields[0][0].name) if fields else None


class _Stream:
    """One v2 subscription, its responses queued by a reader thread so that each can be awaited with a time-out."""

    def __init__(self, stub, v2, grpc, paths):
        self._grpc = grpc
        self.responses = queue.Queue()
        self.call = stub.Subscribe(v2.SubscribeRequest(signal_paths=list(paths), buffer_size=BUFFER_SIZE), wait_for_ready=True)
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        try:
            for resp in self.call:
                self.responses.put({path: _value_of(dp) for path, dp in resp.entries.items()})
            self.responses.put("stream-ended")
        except self._grpc.RpcError as exc:
            self.responses.put("stream-error %s: %s" % (exc.code().name, str(exc.details())[:200]))

    def next(self, timeout):
        """The next response ({path: value or None}), a string when the stream ended or failed, None on time-out."""
        try:
            return self.responses.get(timeout=timeout)
        except queue.Empty:
            return None


def _first(stream, paths):
    resp = stream.next(FIRST_WAIT_S)
    if not isinstance(resp, dict):
        return {p: {"in_response": False, "value": None, "error": resp or "no first response in %g s" % FIRST_WAIT_S} for p in paths}
    return {p: {"in_response": p in resp, "value": resp.get(p)} for p in paths}


def main(argv):
    if len(argv) != 3:
        print("usage: subscribe_probe.py HOST:PORT PLAN.json", file=sys.stderr)
        return 2
    import grpc
    from google.protobuf import json_format
    from kuksa.val.v2 import types_pb2 as t2
    from kuksa.val.v2 import val_pb2 as v2
    from kuksa.val.v2 import val_pb2_grpc as g2

    target = argv[1]
    with open(argv[2], encoding="utf-8") as f:
        plan = json.load(f)
    order = [e["path"] for e in plan]
    stub = g2.VALStub(grpc.insecure_channel(target))
    info = stub.GetServerInfo(v2.GetServerInfoRequest(), timeout=RPC_TIMEOUT_S)
    out = {"target": target, "server": {"name": info.name, "version": info.version, "commit_hash": info.commit_hash},
           "design": {"first_wait_s": FIRST_WAIT_S, "write_wait_s": WRITE_WAIT_S, "buffer_size": BUFFER_SIZE},
           "order": order, "paths": {e["path"]: {"plan": e} for e in plan}}
    paths = out["paths"]
    served = {m.path: m for m in stub.ListMetadata(v2.ListMetadataRequest(root="Vehicle"), timeout=30).metadata}
    out["signals_under_Vehicle"] = len(served)
    for p in order:
        md = json_format.MessageToDict(served[p], preserving_proto_field_name=True) if p in served else None
        paths[p]["metadata"] = {k: v for k, v in md.items() if k not in ("id", "path")} if md is not None else None

    a = _Stream(stub, v2, grpc, order)
    for p, rec in _first(a, order).items():
        paths[p]["first_before"] = rec
    for e in plan:
        p, value = e["path"], e["write"]
        try:
            stub.PublishValue(v2.PublishValueRequest(signal_id=t2.SignalID(path=p),
                                                     data_point=t2.Datapoint(value=t2.Value(**{value_field(e["datatype"]): value}))),
                              timeout=RPC_TIMEOUT_S)
            paths[p]["write"] = {"value": value, "result": "accepted"}
        except grpc.RpcError as exc:
            paths[p]["write"] = {"value": value, "result": "refused %s: %s" % (exc.code().name, exc.details())}
        seen, arrived = [], False
        while paths[p]["write"]["result"] == "accepted":
            resp = a.next(WRITE_WAIT_S)
            if not isinstance(resp, dict):
                seen.append(resp if resp is not None else "no response in %g s" % WRITE_WAIT_S)
                break
            seen.append(resp)
            if p in resp and resp[p] == value and type(resp[p]) is type(value):
                arrived = True
                break
        paths[p]["later_write"] = {"arrived": arrived, "value": value if arrived else None, "responses": seen}
    a.call.cancel()

    b = _Stream(stub, v2, grpc, order)
    for p, rec in _first(b, order).items():
        paths[p]["first_after"] = rec
    b.call.cancel()
    for p in order:
        try:
            got = stub.GetValue(v2.GetValueRequest(signal_id=t2.SignalID(path=p)), timeout=RPC_TIMEOUT_S)
            paths[p]["get_value"] = {"value": _value_of(got.data_point)}
        except grpc.RpcError as exc:
            paths[p]["get_value"] = {"value": None, "error": "%s: %s" % (exc.code().name, exc.details())}
    out["summary"] = summarise(paths)
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
