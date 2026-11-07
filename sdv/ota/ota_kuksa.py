"""ota_kuksa.py -- the health check's AppState source through kuksa-client (sdv/ota; SDV Phase 6 WP1).

The only module of sdv/ota that imports kuksa-client, and no module imports this one
at its top: ota_lite imports it in one place, when a run's first health check needs a source, so `check`, `teardown`,
`reprocess`, the unit launcher and every test run without kuksa-client. The updater's venv takes kuksa-client 0.6.0
from the app's own locks (sdv/apps/hard-brake-hazard/requirements*.lock); there is no lock of its own.

    KuksaSource(address).read(paths) -> {path: the current value, or None when the databroker has none}

It reads the current values of the leaves it is given, nothing else, and writes nothing. The databroker keeps a
signal's last value after its provider is gone, so a value here proves nothing alone: ota_health counts only rising
heartbeats of the started image.

NO CALL WITHOUT A DEADLINE  kuksa-client 0.6.0's sync VSSClient makes a gRPC call with no deadline unless it is given
  one: connect() calls get_server_info() when ensure_startup_connection is true (its default), and every call takes
  grpc's `timeout` through **rpc_kwargs (both read in the extracted 0.6.0 wheel). So the client is made with
  ensure_startup_connection=False, connect() only opens the channel, and each read is one call bounded by
  RPC_TIMEOUT_S. A databroker that is down or never answers makes a read raise within that bound, which the health
  check counts as a read with nothing in it; its deadline then holds within one read.

Does not demonstrate: that this call works against the pinned databroker (no test reaches one; WP5 and the drill do),
or any timing.
"""
from __future__ import annotations

from typing import Any, Dict, Sequence

from kuksa_client.grpc import VSSClient

RPC_TIMEOUT_S = 1.0     # a design bound: a hung databroker costs a read at most this


class KuksaSource:
    def __init__(self, address: str) -> None:
        host, _sep, port = address.rpartition(":")
        self._client = VSSClient(host, int(port), ensure_startup_connection=False)
        self._client.connect()

    def read(self, paths: Sequence[str]) -> Dict[str, Any]:
        got = self._client.get_current_values(list(paths), timeout=RPC_TIMEOUT_S)
        return {p: (getattr(got.get(p), "value", None) if got.get(p) is not None else None) for p in paths}

    def close(self) -> None:
        self._client.disconnect()
