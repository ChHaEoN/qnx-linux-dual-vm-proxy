"""The twin connector's two opt-in probes, run for real (sdv/connector/probes/probe.py): SDV Phase 4 WP0.

Skipped unless SDV_CONNECTOR_PROBE=1, on POSIX with docker: both start a container in WSL Ubuntu-24.04's
Docker Engine, and the broker probe pulls one pinned test image (by index digest) the first time. This file is
not one the CI recipe's skip check names (tests/twin_gate.py), which is why the opt-in tests are here and not
in tests/test_sdv_connector.py; once opted in, a missing catalogue still goes through the gate.

  * probe 1: a throwaway pinned databroker 0.7.1 loaded with the generated catalogue; a kuksa.val.v2 Subscribe on
    the hazard light's current value (an actuator), Wheelbase (an attribute) and the eight AppState leaves (five
    strings): what its first response carries, whether a later write arrives, and what GetValue serves;
  * probe 2: the pinned Mosquitto on an --internal network with no published port, carrying one message on a
    neutral topic and on two exact topics beginning $aws/.

What they assert is what the pinned images did when Phase 4 WP0 ran them (the Phase 4 notes hold the records); a
pin that moves has to show the same before a later work package builds on it. Nothing here is a timing, and
nothing here says anything about the cloud service those topics belong to.
"""
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

import twin_gate

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PROBE_FILE = REPO / "sdv" / "connector" / "probes" / "probe.py"

pytestmark = pytest.mark.skipif(
    os.environ.get("SDV_CONNECTOR_PROBE") != "1" or shutil.which("docker") is None or os.name != "posix",
    reason="the connector's probes run only with SDV_CONNECTOR_PROBE=1 (WSL Docker; the broker probe pulls one pinned test image)")


@pytest.fixture(scope="module")
def probe() -> Any:
    spec = importlib.util.spec_from_file_location("sdv_connector_probe_real", str(PROBE_FILE))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


def test_a_v2_subscription_carries_the_actuator_the_attribute_and_the_string_leaves(probe, tmp_path):
    gen = twin_gate.catalogue("vss-databroker.json")
    rec = probe.databroker_probe(gen, tmp_path / "probe1")
    result = rec["result"]
    paths = list(probe.probe_paths())
    assert result["server"]["version"] == rec["databroker_version"] == "0.7.1" and result["order"] == paths
    summary = result["summary"]
    wheelbase = paths[1]
    # before any write: the attribute's catalogue default is served in the first response, and nothing else has a value
    assert summary["default_in_first_response"] == {wheelbase: True}
    assert all(result["paths"][p]["first_before"]["in_response"] for p in paths)
    assert [p for p in paths if result["paths"][p]["first_before"]["value"] is not None] == [wheelbase]
    # every write is accepted and reaches the open subscription; a later subscription's first response and GetValue
    # each carry every current value: the actuator's, the attribute's and the five strings' among them
    for key in ("write_accepted", "later_write_arrives", "first_response_carries_current_value", "get_value_serves_current_value"):
        assert summary[key] == {p: True for p in paths}, key
    strings = [p for p in paths if result["paths"][p]["plan"]["datatype"] == "string"]
    assert len(strings) == 5 and all(isinstance(result["paths"][p]["first_after"]["value"], str) for p in strings)
    assert json.loads((tmp_path / "probe1" / "databroker-probe.json").read_text(encoding="utf-8")) == rec
    assert probe.docker("inspect", probe.DATABROKER_NAME, check=False).returncode != 0          # removed


def test_the_pinned_mosquitto_carries_exact_aws_topics_on_an_internal_network(probe, tmp_path):
    rec = probe.broker_probe(tmp_path / "probe2")
    assert rec["version_running"] == rec["version_pinned"] == "2.0.22"
    assert rec["network_internal"] is True and rec["published_ports"] == [] and rec["local_only_mode"] is True
    assert rec["control_ok"] is True and rec["carries_exact_aws_topics"] is True
    exact = [c for c in rec["cases"] if c["sub_topic"] == c["pub_topic"]]
    assert [c["sub_topic"] for c in exact] == [probe.NEUTRAL_TOPIC] + list(probe.AWS_TOPICS)
    assert all(c["subscribed"] and c["granted_qos"] == 1 and c["pub_rc"] == 0 and c["received"] for c in exact)
    # MQTT: a subscription to # does not match a topic that begins with $; one that names the $aws level does
    assert rec["wildcard_delivers_first_aws_topic"] == {"#": False, "$aws/#": True}
    for name in (probe.BROKER_NAME,):
        assert probe.docker("inspect", name, check=False).returncode != 0          # removed
    assert probe.docker("network", "inspect", probe.NETWORK, check=False).returncode != 0
