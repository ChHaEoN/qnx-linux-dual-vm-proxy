"""canary_writer.py -- plant a value in each leaf a plan names, or read each of them back (sdv/connector/probes; SDV
Phase 4 WP3, the canary run: design twin-allowlist.md A6 on the pinned databroker).

Run by tests/test_sdv_connector_broker.py in the recorder image (kuksa-client 0.6.0's
generated kuksa.val.v2 modules and grpc), in the host's network namespace beside a running stack, against the stack's
own databroker on 127.0.0.1; prints one JSON object.

    python canary_writer.py HOST:PORT PLAN.json plant|read

PLAN.json is the test's: [{"path", "datatype", "value"}], one entry per leaf of the branch the twin excludes,
enumerated by the test from the generated catalogue (this file spells no path). `plant` writes each value with one
kuksa.val.v2 PublishValue (the databroker runs without authorisation, so any local client can) and says which were
accepted; `read` asks GetValue for each and says what the databroker holds. The test plants before the connector
starts and reads while it runs: a leaf that then still holds its canary held it while the connector read.

Does not demonstrate: anything by itself. What the connector sent is read at the far end, by the test's observer.
"""
import json
import sys

RPC_TIMEOUT_S = 10
# VSS datatype -> the kuksa.val.v2 Value field that carries it.
_FIELDS = {"boolean": "bool", "string": "string", "uint8": "uint32", "uint16": "uint32", "uint32": "uint32", "int8": "int32",
           "int16": "int32", "int32": "int32", "float": "float", "double": "double", "uint64": "uint64", "int64": "int64"}


def _value_of(dp):
    fields = dp.value.ListFields()
    return getattr(dp.value, fields[0][0].name) if fields else None


def main(argv):
    if len(argv) != 4 or argv[3] not in ("plant", "read"):
        print("usage: canary_writer.py HOST:PORT PLAN.json plant|read", file=sys.stderr)
        return 2
    import grpc
    from kuksa.val.v2 import types_pb2 as t2
    from kuksa.val.v2 import val_pb2 as v2
    from kuksa.val.v2 import val_pb2_grpc as g2

    with open(argv[2], encoding="utf-8") as f:
        plan = json.load(f)
    stub = g2.VALStub(grpc.insecure_channel(argv[1]))
    out = {"mode": argv[3], "entries": len(plan), "accepted": [], "refused": {}, "held": {}}
    for e in plan:
        path = e["path"]
        try:
            if argv[3] == "plant":
                stub.PublishValue(v2.PublishValueRequest(signal_id=t2.SignalID(path=path),
                                                         data_point=t2.Datapoint(value=t2.Value(**{_FIELDS[e["datatype"]]: e["value"]}))),
                                  timeout=RPC_TIMEOUT_S)
                out["accepted"].append(path)
            else:
                got = stub.GetValue(v2.GetValueRequest(signal_id=t2.SignalID(path=path)), timeout=RPC_TIMEOUT_S)
                out["held"][path] = _value_of(got.data_point)
        except grpc.RpcError as exc:
            out["refused"][path] = "%s: %s" % (exc.code().name, str(exc.details())[:200])
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
