"""kuksa_out.py -- the ROS->VSS feeder's only KUKSA calls: the databroker's datatypes at start and the writes (sdv/rosvss;
Phase 8 WP3a).

Local branch only (decision 15). kuksa-client 0.6.0 (the slice's pin, sdv/bridge/requirements.lock) is imported inside
the class's methods, never at module level, and no other module of the package imports it; feeder_node.main imports
this module itself only when it starts. The calls are the claim bridge's write-back pattern
(sdv/bridge/bridge_sources.py, KuksaBroker; read, never imported): VSSClient with ensure_startup_connection=False and
connect(), get_value_types for the datatypes, and set(updates, try_v2=True) (kuksa.val.v2's PublishValue) with each
value's datatype given.

DESIGN VALUES (the bridge's, for the same calls)
  START_TIMEOUT_S = 10 s: how long the start check waits for the databroker's datatypes before refusing (the bridge's
    BROKER_TIMEOUT_S).
  WRITE_RPC_TIMEOUT_S = 2 s: one write's wait for the databroker, in the writer's thread, never a callback's (the
    bridge's WRITEBACK_RPC_TIMEOUT_S).

DOES NOT DEMONSTRATE: that kuksa-client 0.6.0 and the databroker behave as the tests' stand-in does (WP4b runs them).
"""
from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple

START_TIMEOUT_S = 10.0
WRITE_RPC_TIMEOUT_S = 2.0


class KuksaOutError(RuntimeError):
    """The databroker did not give what the start needs."""


class KuksaOut:
    """The writer's sink over kuksa-client's VSSClient: publish([(path, value, datatype)]) and close()."""

    def __init__(self, host: str, port: int, timeout_s: float = START_TIMEOUT_S) -> None:
        from kuksa_client.grpc import VSSClient
        self._timeout = timeout_s
        self._client = VSSClient("[%s]" % host if ":" in host else host, int(port), ensure_startup_connection=False)
        self._client.connect()

    def value_types(self, paths: Sequence[str]) -> Dict[str, str]:
        """{path: datatype, lower case} as the databroker serves them; a KuksaOutError when it gives none."""
        try:
            got = self._client.get_value_types(list(paths), timeout=self._timeout, wait_for_ready=True)
        except Exception as err:  # noqa: BLE001 -- kuksa-client's and grpc's errors alike refuse the start
            raise KuksaOutError("the databroker gave no datatypes for the %d write-set paths: %s %s"
                                % (len(paths), type(err).__name__, str(err)[:300])) from err
        return {p: t.name.lower() for p, t in got.items()}

    def publish(self, items: Sequence[Tuple[str, Any, str]]) -> None:
        from kuksa_client.grpc import DataEntry, Datapoint, DataType, EntryUpdate, Field, Metadata
        updates = [EntryUpdate(DataEntry(path, value=Datapoint(value), metadata=Metadata(data_type=DataType[dtype.upper()])), (Field.VALUE,))
                   for path, value, dtype in items]
        self._client.set(updates=updates, try_v2=True, timeout=WRITE_RPC_TIMEOUT_S)

    def close(self) -> None:
        self._client.disconnect()
