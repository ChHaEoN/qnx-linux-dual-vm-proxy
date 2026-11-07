"""catalogue_probe.py -- ask a running databroker what catalogue it serves (sdv/stack).

Project-written. Run by stack.py inside the recorder image (it has kuksa-client 0.6.0 and grpc),
joined to a throwaway databroker's network namespace; prints one JSON object. kuksa.val.v2
GetServerInfo, ListMetadata and GetValue; with --write, one PublishValue per PATH=UINT (a uint8
sensor), to see whether the databroker enforces a range the catalogue file states.

    python catalogue_probe.py HOST:PORT [--write PATH=UINT ...] PATH [PATH ...]

For each PATH: whether the databroker knows it, its metadata (data type, entry type, unit, allowed
values, min and max as the databroker reports them) and its current value, if any.
"""
import json
import sys

import grpc
from google.protobuf import json_format
from kuksa.val.v2 import types_pb2 as t2
from kuksa.val.v2 import val_pb2 as v2
from kuksa.val.v2 import val_pb2_grpc as g2


def main(argv):
    target, rest = argv[1], list(argv[2:])
    writes = []
    while "--write" in rest:
        i = rest.index("--write")
        writes.append(rest[i + 1])
        del rest[i:i + 2]
    paths = rest
    stub = g2.VALStub(grpc.insecure_channel(target))
    out = {"target": target, "writes": {}}
    for w in writes:
        path, _, val = w.partition("=")
        try:
            stub.PublishValue(v2.PublishValueRequest(signal_id=t2.SignalID(path=path),
                                                     data_point=t2.Datapoint(value=t2.Value(uint32=int(val)))), timeout=10)
            out["writes"][w] = "accepted"
        except grpc.RpcError as exc:
            out["writes"][w] = "refused %s: %s" % (exc.code().name, exc.details())
    info = stub.GetServerInfo(v2.GetServerInfoRequest(), timeout=10)
    out["server"] = {"name": info.name, "version": info.version, "commit_hash": info.commit_hash}
    md = stub.ListMetadata(v2.ListMetadataRequest(root="Vehicle"), timeout=30)
    out["signals_under_Vehicle"] = len(md.metadata)
    by_path = {m.path: m for m in md.metadata}
    out["paths"] = {}
    for p in paths:
        m = by_path.get(p)
        if m is None:
            out["paths"][p] = {"known": False}
            continue
        entry = {"known": True, "metadata": json_format.MessageToDict(m, preserving_proto_field_name=True)}
        entry["metadata"].pop("id", None)
        try:
            val = stub.GetValue(v2.GetValueRequest(signal_id=t2.SignalID(path=p)), timeout=10)
            entry["value"] = json_format.MessageToDict(val.data_point.value) if val.data_point.HasField("value") else None
        except grpc.RpcError as exc:
            entry["value_error"] = "%s: %s" % (exc.code().name, exc.details())
        out["paths"][p] = entry
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
