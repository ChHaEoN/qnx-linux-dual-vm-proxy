"""The breaker function (sdv/cloud/breaker/breaker.py) and its zip (sdv/cloud/twinctl.py, `build-breaker`): SDV Phase 4
WP7.

NO AWS CALL IS MADE HERE, NO CREDENTIAL IS READ, AND NO SDK IS IMPORTED. The function is given its two clients as
Python arguments: the fake clients of tests/twin_stub_aws.py over a small account that is a dict of this file. They
record every call, hold the argument names the service gives (a call with another name fails as a call), and raise
the errors a test plants, shaped as botocore's are: response["Error"]["Code"] and the HTTP status. Where the handler
itself is run, the two SDK modules it imports are stand-ins this file puts into sys.modules; CI's venv has no boto3,
and a test holds that neither the module nor this file needs one.

A TEST FIXTURE IS CAPTURE DATA. The account is the documentation account, the names say "example", and the
certificate ids are the hex digits in order and backwards, put together when the tests run.

What is held here (the breaker contract, and what the package's brief added)
  the event rules   every row of the table in the module's docstring: the manual trip, the manual status, an alarm in
                    ALARM in both shapes (the two fixture files, written from the documentation), a cleanly parsed
                    OK or INSUFFICIENT_DATA (no call), and anything else (the full trip: it fails closed), an event
                    the rules themselves stop on among them (a message nested deeper than the JSON reader goes; an
                    event whose own reading raises): the rules never raise.
  the trip          the calls, their arguments and their order, for one certificate and for two; DeleteConnection
                    after every certificate is INACTIVE; the policy by the environment's name.
  the verdict       the read-backs give it. One step fails: the others run and it raises at the end. A second
                    delivery is harmless, also when the service answers an error for work already done. A cut that
                    is not there raises although every call was accepted; so does a read-back that could not be
                    made, and the record never states what was not read. A write refused as not authorised raises
                    even when the read-back shows the cut.
  DeleteConnection  missing from the client: the others complete and the record says so. Not found: no client
                    connected, no failure. Any other error: a failure.
  the environment   a missing value: every step whose inputs are there is attempted, and it raises at the end. An
                    empty or unusable certificate list likewise. Nothing of the environment is in a raised message
                    or in the returned record; the log record names what was acted on, what invoked it and the
                    request.
  the clients       made in one place, with short time-outs, one attempt each and no endpoint of the environment's;
                    the arithmetic of the largest set the function's time is counted for, with the number of
                    addresses per endpoint name it is counted for in it (the connect time-out is per address), and
                    the words that say what is not held.
  the role          the operations the file calls are exactly the template's iot actions, each on the resource its
                    call names; no enable, attach or activate exists in the file.
  the zip           one entry, a fixed time and mode, the same bytes on every build and on both platforms (a pinned
                    digest of a fixed source); the entry's name and the handler agree; the leak scan finds nothing
                    in it.

Standard library and pytest. Every test here runs everywhere: this file holds no mark that passes a test over.

Does not demonstrate: IAM's evaluation of the role; that an alarm reaches the function; the event's real shape (both
fixtures are written from the documentation); what each API answers when the work is already done; what a live
connection does; anything about the runtime's own SDK. tests/test_sdv_breaker_model.py (opt-in, a dev venv) holds the
calls to the service model. Both alarm fixtures are hand-written from the documentation; they are not captures
from a deployed function. The direct fixture supplies `alarmData.state.value` and `alarmData.alarmName`, with no
`Records` or `manual` field. These tests do not establish what a live alarm delivers.
"""
import ast
import base64
import hashlib
import importlib.util
import io
import json
import re
import sys
import types
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SOURCE = REPO / "sdv" / "cloud" / "breaker" / "breaker.py"
TEMPLATES = REPO / "sdv" / "cloud" / "templates"
FIXTURES = HERE / "fixtures"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


B = _load("sdv_cloud_breaker_under_test", SOURCE)
STUB = _load("twin_stub_aws_for_the_breaker", HERE / "twin_stub_aws.py")
TW = _load("sdv_cloud_twinctl_for_the_breaker", REPO / "sdv" / "cloud" / "twinctl.py")
LS = _load("sdv_cloud_leakscan_for_the_breaker", REPO / "scripts" / "aws" / "leakscan.py")
FAKE_IOT: Any = STUB.FakeIot

ACCOUNT = "123456789012"
REGION = "us-east-1"
RULE = "example_rule"
POLICY = "example-device-policy"
CLIENT = "example-thing"
CLIENT_2 = "example-thing-two"
CERT_1 = "0123456789abcdef" * 4
CERT_2 = "fedcba9876543210" * 4
REQUEST = "an-example-request-id"
ALARM = "example-alarm"                         # the alarm's name in both fixture files
SDK = "9.9.9"


def arn(cert: str) -> str:
    return "arn:aws:iot:%s:%s:cert/%s" % (REGION, ACCOUNT, cert)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def direct(state: Any = "ALARM") -> Dict[str, Any]:
    """An alarm's direct invoke, from the fixture file, in the given state."""
    event = fixture("breaker-event-alarm-direct.json")
    event["alarmData"]["state"]["value"] = state
    return dict(event)


def sns(*states: Any) -> Dict[str, Any]:
    """The same alarm through a topic, from the fixture file: one record per state."""
    event = fixture("breaker-event-alarm-sns.json")
    record, = event["Records"]
    records = []
    for state in states or ("ALARM",):
        message = json.loads(record["Sns"]["Message"])
        message["NewStateValue"] = state
        records.append(dict(record, Sns=dict(record["Sns"], Message=json.dumps(message))))
    return {"Records": records}


def sns_text(*texts: str) -> Dict[str, Any]:
    """Records of a topic's delivery whose Message is the given text as it stands: what is no alarm's message at all."""
    record, = fixture("breaker-event-alarm-sns.json")["Records"]
    return {"Records": [dict(record, Sns=dict(record["Sns"], Message=text)) for text in texts]}


# A JSON text nested deeper than the interpreter's reader goes: json.loads raises RecursionError on it, which is no
# ValueError (WP7-verify-r2's SHOULD 1; 200 KB, under what an event may hold). The depth is far past every limit seen.
DEEP = "[" * 100000 + "]" * 100000


class Rig:
    """A small account, the two fake clients over it, and the function's environment."""

    def __init__(self, certs: Sequence[str] = (CERT_1,), clients: Sequence[str] = (CLIENT,), live: bool = True,
                 connected: Sequence[str] = (), old_sdk: bool = False) -> None:
        self.certs, self.clients = list(certs), list(clients)
        self.account: Dict[str, Any] = {
            "account": ACCOUNT, "region": REGION, "rules": {RULE: {"ruleDisabled": not live}}, "policies": {POLICY: {}},
            "certs": {c: {"status": "ACTIVE" if live else "INACTIVE", "policies": [POLICY] if live else []} for c in certs},
            "connections": list(connected)}
        self.calls: List[List[Any]] = []
        self.faults: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []
        self.iot = STUB.FakeIot(self.account, self.calls, self.faults)
        self.data = (STUB.FakeIotDataOld if old_sdk else STUB.FakeIotData)(self.account, self.calls, self.faults)
        self.env = {"TWIN_CERTIFICATE_ARNS": ",".join(arn(c) for c in certs), "TWIN_CLIENT_IDS": ",".join(clients), "TWIN_RULE": RULE,
                    "TWIN_POLICY": POLICY}

    def run(self, event: Any, **change: Optional[str]) -> Dict[str, Any]:
        env = {k: v for k, v in dict(self.env, **change).items() if v is not None}
        return dict(B.run(event, env, self.iot, self.data, sdk=SDK, request_id=REQUEST, log=self.logs.append))

    def fault(self, op: str, **how: Any) -> None:
        self.faults.append(dict(how, op=op, client="iot-data" if op == "delete_connection" else "iot"))

    def ops(self, since: int = 0) -> List[str]:
        return [c[1] for c in self.calls[since:]]

    def is_cut(self) -> bool:
        a = self.account
        return bool(a["rules"][RULE]["ruleDisabled"]) and all(c == {"status": "INACTIVE", "policies": []} for c in a["certs"].values())


def writes(certs: Sequence[str], clients: Sequence[str] = (CLIENT,)) -> List[List[Any]]:
    out: List[List[Any]] = [["iot", "disable_topic_rule", {"ruleName": RULE}]]
    out += [["iot", "update_certificate", {"certificateId": c, "newStatus": "INACTIVE"}] for c in certs]
    out += [["iot-data", "delete_connection", {"clientId": k}] for k in clients]
    return out + [["iot", "detach_policy", {"policyName": POLICY, "target": arn(c)}] for c in certs]


def reads(certs: Sequence[str]) -> List[List[Any]]:
    out: List[List[Any]] = [["iot", "describe_certificate", {"certificateId": c}] for c in certs]
    return out + [["iot", "list_targets_for_policy", {"policyName": POLICY, "pageSize": 250}], ["iot", "get_topic_rule", {"ruleName": RULE}]]


WRITES = ("disable_topic_rule", "update_certificate", "delete_connection", "detach_policy")
READS = ("describe_certificate", "list_targets_for_policy", "get_topic_rule")
SECRETS = (ACCOUNT, RULE, POLICY, CLIENT, CLIENT_2, CERT_1, CERT_2, REQUEST, ALARM, "example")


def held(text: str) -> List[str]:
    """What of the environment, of the event and of the request stands in `text`."""
    return [s for s in SECRETS if s in text]


def raises(rig: Rig, event: Any, **change: Optional[str]) -> str:
    """The function raises its own error; the message, which holds nothing of the environment."""
    with pytest.raises(B.BreakerError) as e:
        rig.run(event, **change)
    message = str(e.value)
    assert not held(message), message
    assert e.value.__cause__ is None
    return message


# ================================================================================================= the event rules

UNPARSED: List[Any] = [
    None, 7, "trip", '{"manual": "status"}', [], [{"manual": "status"}], {},
    {"manual": "TRIP"}, {"manual": "Status"}, {"manual": ["status"]}, {"manual": None}, {"Manual": "status"},
    {"manual": "status", "extra": 1}, {"manual": "trip", "extra": 1},
    {"alarmData": "ALARM"}, {"alarmData": {"state": "OK"}}, {"alarmData": {"state": {}}}, {"alarmData": {"state": {"value": None}}},
    {"Records": []}, {"Records": "OK"}, {"Records": [{}]}, {"Records": [{"Sns": {}}]},
    {"Records": [{"Sns": {"Message": "not json"}}]}, {"Records": [{"Sns": {"Message": "[]"}}]},
    {"Records": [{"Sns": {"Message": {"NewStateValue": "OK"}}}]}, {"Records": [{"Sns": {"Message": json.dumps({"NewStateValue": "Okay"})}}]},
    {"Records": [{"Sns": {"Message": json.dumps({"OldStateValue": "OK"})}}]},
]


def rows() -> List[Tuple[int, Any, str, str, Optional[str]]]:
    """Every row of the table: (its number, an event, what is done, what invoked it, the alarm's state)."""
    out: List[Tuple[int, Any, str, str, Optional[str]]] = [
        (1, {"manual": "trip"}, "trip", "manual", None),
        (2, {"manual": "status"}, "status", "manual", None),
        (3, direct("ALARM"), "trip", "alarm", "ALARM"),
        (4, direct("OK"), "none", "alarm", "OK"),
        (4, direct("INSUFFICIENT_DATA"), "none", "alarm", "INSUFFICIENT_DATA"),
        (5, sns("ALARM"), "trip", "sns", "ALARM"),
        (5, sns("OK", "ALARM"), "trip", "sns", "ALARM"),
        (5, sns("ALARM", "no state at all"), "trip", "sns", "ALARM"),
        (6, sns("OK"), "none", "sns", "OK"),
        (6, sns("INSUFFICIENT_DATA"), "none", "sns", "INSUFFICIENT_DATA"),
        (6, sns("INSUFFICIENT_DATA", "OK"), "none", "sns", "INSUFFICIENT_DATA"),
    ]
    out += [(7, event, "trip", "unparsed", None) for event in UNPARSED]
    out += [(7, direct(state), "trip", "unparsed", None) for state in ("alarm", "Ok", 7, None, ["OK"], "")]
    out += [(7, dict(direct("OK"), manual="status"), "trip", "unparsed", None), (7, dict(direct("OK"), **sns("OK")), "trip", "unparsed", None),
            (7, dict(sns("OK"), manual="status"), "trip", "unparsed", None), (7, sns("OK", "Okay"), "trip", "unparsed", None),
            (7, {"Records": sns("OK")["Records"] + [{"Sns": {"Message": "not json"}}]}, "trip", "unparsed", None),
            (7, {"Records": sns("OK")["Records"] + ["a record that is no object"]}, "trip", "unparsed", None)]
    # WP7-verify-r2's SHOULD 1: a message the interpreter's JSON reader stops on (RecursionError, no ValueError) is a message
    # that cannot be read, like one that is no JSON: alone or beside a clean OK it is the seventh row, beside an ALARM the fifth
    out += [(7, sns_text(DEEP), "trip", "unparsed", None),
            (7, {"Records": sns("OK")["Records"] + sns_text(DEEP)["Records"]}, "trip", "unparsed", None),
            (7, {"Records": sns_text(DEEP)["Records"] + sns("OK")["Records"]}, "trip", "unparsed", None),
            (5, {"Records": sns_text(DEEP)["Records"] + sns("ALARM")["Records"]}, "trip", "sns", "ALARM")]
    return out


@pytest.mark.parametrize("row,event,mode,invoked_by,state", rows(), ids=lambda v: str(v)[:40] if not isinstance(v, (dict, list)) else None)
def test_every_row_of_the_event_table(row: int, event: Any, mode: str, invoked_by: str, state: Optional[str]) -> None:
    decided = B.decide(event)
    assert (decided[0], decided[1], decided[3]) == (mode, invoked_by, state), decided
    assert decided[2] == (ALARM if invoked_by in ("alarm", "sns") else None)        # the alarm's name, as the event gives it
    # and what the function then does: the full trip, the read-backs alone, or nothing at all
    rig = Rig()
    record = rig.run(event)
    assert rig.calls == {"trip": writes([CERT_1]) + reads([CERT_1]), "status": reads([CERT_1]), "none": []}[mode]
    assert (record["mode"], record["invoked_by"], record["alarm_state"]) == (mode, invoked_by, state)
    assert rig.is_cut() is (mode == "trip") and record["cut"] is {"trip": True, "status": False, "none": None}[mode]
    log, = rig.logs
    assert (log["mode"], log["invoked_by"], log["alarm"], log["request_id"]) == (mode, invoked_by, decided[2], REQUEST)


def test_the_docstrings_table_has_the_rows_that_are_tested() -> None:
    doc = str(B.__doc__)
    table = doc[doc.index("THE EVENT RULES"):doc.index("THE STEPS")]
    numbered = [int(m.group(1)) for m in re.finditer(r"^  ([0-9])  ", table, re.M)]
    assert numbered == [1, 2, 3, 4, 5, 6, 7] and sorted({r[0] for r in rows()}) == numbered
    for word in ('{"manual": "trip"}', '{"manual": "status"}', "alarmData.state.value", "Records[].Sns.Message", "NewStateValue", "ALARM",
                 "INSUFFICIENT_DATA", "anything else"):
        assert word in table, word
    assert "not a captured event" in " ".join(doc.split())


def test_the_two_fixture_files_are_the_documented_shapes_with_documentation_values() -> None:
    one, two = fixture("breaker-event-alarm-direct.json"), fixture("breaker-event-alarm-sns.json")
    assert one["source"] == "aws.cloudwatch" and one["alarmData"]["state"]["value"] == "ALARM" and one["alarmData"]["alarmName"] == ALARM
    record, = two["Records"]
    message = json.loads(record["Sns"]["Message"])
    assert record["EventSource"] == "aws:sns" and (message["NewStateValue"], message["AlarmName"]) == ("ALARM", ALARM)
    # WP8 (the re-check of the documentation, T15): the two spellings and the three fields the fixtures had wrong or lacked. The
    # decoder reads none of them; the fixtures are the documented shapes, and a fixture that is not one says nothing of the decoder.
    assert isinstance(message["AlarmDescription"], str)                                              # the schema says string, not null
    assert "SigningCertURL" in record["Sns"] and "SigningCertUrl" not in record["Sns"]               # the documented sample's spelling
    assert isinstance(one["alarmData"]["previousState"]["reasonData"], str)                          # documented, and the fixture lacked it
    assert isinstance(one["alarmData"]["configuration"]["metrics"][0]["metricStat"]["unit"], str)    # likewise
    for name in ("breaker-event-alarm-direct.json", "breaker-event-alarm-sns.json"):
        raw = (FIXTURES / name).read_bytes()
        assert b"\r" not in raw and raw.endswith(b"\n") and set(re.findall(rb"(?<![0-9a-f-])[0-9]{12}(?![0-9])", raw)) == {ACCOUNT.encode()}, name
        assert b"written by hand" in raw and b"not a captured event" in raw, name


def test_an_event_the_rules_themselves_stop_on_is_the_trip_and_never_an_error_before_the_first_call() -> None:
    """WP7-verify-r2, SHOULD 1 (the event parse rule: it fails closed on an event it cannot parse). A message nested deeper than
    the interpreter's JSON reader goes made json.loads raise RecursionError, which is no ValueError: decide() let it out,
    nothing had been called yet, run() raised "an error no step names", and the twin was NOT cut. Whatever the rules
    cannot do with an event is an event that cannot be parsed: the seventh row, and every step is attempted."""
    with pytest.raises(RecursionError):
        json.loads(DEEP)                        # what this interpreter's reader does with it: the case is what it says it is
    assert B.decide(sns_text(DEEP)) == ("trip", "unparsed", None, None)
    rig = Rig([CERT_1, CERT_2], [CLIENT, CLIENT_2], connected=[CLIENT])
    record = rig.run(sns_text(DEEP))
    assert rig.calls == writes([CERT_1, CERT_2], [CLIENT, CLIENT_2]) + reads([CERT_1, CERT_2]) and rig.is_cut()
    assert (record["mode"], record["invoked_by"], record["cut"], record["counts"]["calls"], record["failures"]) == ("trip", "unparsed", True, 11, [])

    # and not that one error alone: an event whose own reading raises, whatever it raises and wherever in the rules
    class Hostile(dict):                        # an event that raises where the rules look for its shape, with a value in its message
        def __contains__(self, key: Any) -> bool:
            raise RuntimeError("the value %s of an event" % RULE)

    class Sly(dict):                            # ... and one that raises further in, where a field is taken
        def get(self, key: Any, default: Any = None) -> Any:
            raise KeyError(RULE)

    for event in (Hostile(manual="status"), Hostile(direct("OK")), {"alarmData": Sly(state={"value": "OK"})},
                  {"Records": [{"Sns": Sly(Message=json.dumps({"NewStateValue": "OK"}))}]}):
        assert B.decide(event) == ("trip", "unparsed", None, None), type(event).__name__
        rig = Rig(connected=[CLIENT])
        record = rig.run(event)
        assert rig.calls == writes([CERT_1]) + reads([CERT_1]) and rig.is_cut() and record["cut"] is True
        log, = rig.logs
        assert (log["mode"], log["invoked_by"], log["alarm"]) == ("trip", "unparsed", None) and not held(json.dumps(record))
    doc = " ".join(str(B.__doc__).split())
    assert "an event the rules themselves stop on" in doc and "decide() never raises" in doc


# ================================================================================================= the trip

@pytest.mark.parametrize("event,invoked_by", [(direct("ALARM"), "alarm"), (sns("ALARM"), "sns"), ({"manual": "trip"}, "manual"),
                                              ("no event of any shape", "unparsed")], ids=["direct", "through-sns", "manual", "unparsed"])
@pytest.mark.parametrize("certs,clients", [([CERT_1], [CLIENT]), ([CERT_1, CERT_2], [CLIENT]), ([CERT_1, CERT_2], [CLIENT, CLIENT_2])],
                         ids=["one-certificate", "two-certificates", "two-and-two-clients"])
def test_a_trip_makes_these_calls_with_these_arguments_in_this_order(event: Any, invoked_by: str, certs: List[str], clients: List[str]) -> None:
    rig = Rig(certs, clients, connected=clients[:1])
    record = rig.run(event)
    assert rig.calls == writes(certs, clients) + reads(certs)
    assert rig.is_cut() and rig.account["connections"] == []
    assert record == {
        "v": 1, "mode": "trip", "invoked_by": invoked_by, "alarm_state": "ALARM" if invoked_by in ("alarm", "sns") else None,
        "boto3": SDK, "has_delete_connection": True, "rule": {"write": "ok", "state": "disabled"},
        "certificates": [{"write": "ok", "state": "INACTIVE", "detach": "ok", "policy": "detached"} for _c in certs],
        "connections": [{"write": "ok"}] + [{"write": "no-client-connected"} for _k in clients[1:]],
        "counts": {"certificates": len(certs), "client_ids": len(clients), "unusable_certificates": 0, "calls": 3 * len(certs) + len(clients) + 3,
                   "failures": 0},
        "cut": True, "failures": []}
    assert not held(json.dumps(record))
    # the log record, inside the account, names what was acted on, what invoked the function and the request
    log, = rig.logs
    assert log["request_id"] == REQUEST and log["invoked_by"] == invoked_by and log["record"] == record
    assert log["alarm"] == (ALARM if invoked_by in ("alarm", "sns") else None)
    assert log["acts_on"] == {"rule": RULE, "policy": POLICY, "certificates": [arn(c) for c in certs], "client_ids": clients}
    assert [(c["client"], c["op"], c["answer"]) for c in log["calls"]][:1] == [("iot", "disable_topic_rule", "ok")]
    assert len(log["calls"]) == len(rig.calls)


def test_no_connection_is_deleted_before_every_certificate_is_inactive_and_the_policy_goes_last() -> None:
    rig = Rig([CERT_1, CERT_2], [CLIENT, CLIENT_2])
    rig.run({"manual": "trip"})
    ops = rig.ops()
    last_inactive = max(i for i, op in enumerate(ops) if op == "update_certificate")
    assert ops[0] == "disable_topic_rule" and last_inactive < ops.index("delete_connection")        # so that the client cannot come back
    assert max(i for i, op in enumerate(ops) if op == "delete_connection") < ops.index("detach_policy") < ops.index("describe_certificate")
    assert ops.index("describe_certificate") < ops.index("list_targets_for_policy") < ops.index("get_topic_rule") == len(ops) - 1


def test_the_policy_is_detached_by_the_name_the_environment_gives_and_no_name_stands_in_the_file() -> None:
    rig = Rig()
    other = "another-policy-of-the-account"
    rig.account["policies"][other] = {}
    rig.account["certs"][CERT_1]["policies"] = [POLICY, other]
    rig.run({"manual": "trip"}, TWIN_POLICY=other)
    detach, = [c for c in rig.calls if c[1] == "detach_policy"]
    listing, = [c for c in rig.calls if c[1] == "list_targets_for_policy"]
    assert detach[2] == {"policyName": other, "target": arn(CERT_1)} and listing[2]["policyName"] == other
    assert rig.account["certs"][CERT_1]["policies"] == [POLICY]                 # the one policy, and no other
    source = SOURCE.read_text(encoding="utf-8")
    names = TW.Names({"TWIN_ACCOUNT": ACCOUNT, "TWIN_PROFILE": "example-profile", "TWIN_OPERATOR_ROLE": "example-operator-role",
                      "TWIN_PREFIX": "exampleprefix", "TWIN_THING": "exampleprefix-thing", "TWIN_BUCKET_SUFFIX": "0a1b2c3d4e5f", "TWIN_NOTICE": "0"})
    for derived in (names.policy, names.rule, names.function, names.thing):    # what twinctl derives from a prefix: its endings are not here
        assert derived[len(names.prefix):] not in source, derived[len(names.prefix):]
    assert not re.search(r"arn:aws|[0-9]{12}|[0-9a-f]{32}", source)


# ================================================================================================= the status

def test_the_manual_status_reads_only_and_reports_the_sdk() -> None:
    rig = Rig()                                 # a live twin: nothing is cut, and that is no error of the status
    record = rig.run({"manual": "status"})
    assert rig.calls == reads([CERT_1]) and not [c for c in rig.calls if c[1] in WRITES] and not rig.is_cut()
    assert record == {
        "v": 1, "mode": "status", "invoked_by": "manual", "alarm_state": None, "boto3": SDK, "has_delete_connection": True,
        "rule": {"state": "enabled"}, "certificates": [{"state": "ACTIVE", "policy": "attached"}], "connections": [],
        "counts": {"certificates": 1, "client_ids": 1, "unusable_certificates": 0, "calls": 3, "failures": 0}, "cut": False, "failures": []}
    cut = Rig([CERT_1, CERT_2], live=False)
    record = cut.run({"manual": "status"})
    assert cut.calls == reads([CERT_1, CERT_2]) and record["cut"] is True and record["rule"] == {"state": "disabled"}
    assert record["certificates"] == [{"state": "INACTIVE", "policy": "detached"}] * 2
    # the runtime's SDK without the call: said, and the status is still whole
    old = Rig(old_sdk=True)
    record = old.run({"manual": "status"})
    assert record["has_delete_connection"] is False and record["boto3"] == SDK and old.calls == reads([CERT_1])


@pytest.mark.parametrize("op", READS)
def test_a_status_that_could_not_read_raises_and_states_nothing_it_did_not_read(op: str) -> None:
    rig = Rig(live=False)
    rig.fault(op, code="AccessDeniedException", status=403)
    message = raises(rig, {"manual": "status"})
    assert "could not be read" in message and rig.calls == reads([CERT_1])     # the other reads were made all the same
    record = rig.logs[0]["record"]
    assert record["cut"] is False and record["counts"]["failures"] == 1
    assert (record["rule"]["state"] == "not-read") is (op == "get_topic_rule")
    assert (record["certificates"][0]["state"] == "not-read") is (op == "describe_certificate")
    assert (record["certificates"][0]["policy"] == "not-read") is (op == "list_targets_for_policy")
    assert not [c for c in rig.calls if c[1] in WRITES]


def test_the_status_raises_also_when_every_value_is_there_and_every_state_was_read_but_the_environment_is_not_usable_as_it_stands() -> None:
    """WP7-critic, ledger WP7#10 (critic#1; the critic's own drive, S2 and S3). The docstring said the status "raises only when a
    read-back could not be made or an environment value is missing". It raises also on a list of certificates longer than the
    time is counted for and on an entry that is no certificate's ARN, with no value missing: and makes no write on either."""
    cert_3 = "00112233445566778899aabbccddeeff" * 2
    rig = Rig([CERT_1, CERT_2, cert_3])
    assert len(rig.certs) == B.MAX_CERTIFICATES + 1
    message = raises(rig, {"manual": "status"})
    assert message == ("the status did not complete: 1 failure(s): TWIN_CERTIFICATE_ARNS names 3 certificates, more than the %d the "
                       "function's time is counted for" % B.MAX_CERTIFICATES)
    assert not [c for c in rig.calls if c[1] in WRITES] and rig.logs[0]["mode"] == "status"
    unusable = Rig()
    message = raises(unusable, {"manual": "status"}, TWIN_CERTIFICATE_ARNS=arn(CERT_1) + ",an entry that is no ARN")
    assert message == "the status did not complete: 1 failure(s): 1 of the entries of TWIN_CERTIFICATE_ARNS are no certificate's ARN"
    assert not [c for c in unusable.calls if c[1] in WRITES] and unusable.logs[0]["mode"] == "status"
    doc = " ".join(str(B.__doc__).split())
    assert ("it raises only when a read-back could not be made or the environment is not usable as it stands (a value missing, an "
            "entry that is no certificate's ARN, a list longer than the time is counted for)") in doc
    assert "or an environment value is missing" not in doc


# ================================================================================================= the verdict

@pytest.mark.parametrize("op", WRITES)
@pytest.mark.parametrize("how", [{"code": "InternalFailureException", "status": 500}, {"no_answer": True}], ids=["an-error", "no-answer"])
def test_one_step_fails_the_others_still_run_and_it_raises_at_the_end(op: str, how: Dict[str, Any]) -> None:
    rig = Rig([CERT_1, CERT_2], connected=[CLIENT])
    rig.fault(op, **how)
    message = raises(rig, {"manual": "trip"})
    assert rig.calls == writes([CERT_1, CERT_2]) + reads([CERT_1, CERT_2])     # every step was attempted, the read-backs too
    a = rig.account
    assert a["rules"][RULE]["ruleDisabled"] is (op != "disable_topic_rule")    # what did not fail was done
    assert a["certs"][CERT_2] == {"status": "INACTIVE", "policies": []}
    assert a["certs"][CERT_1] == {"status": "ACTIVE" if op == "update_certificate" else "INACTIVE",
                                  "policies": [POLICY] if op == "detach_policy" else []}
    assert a["connections"] == ([CLIENT] if op == "delete_connection" else [])
    assert "1 failure(s)" in message and len(rig.logs) == 1 and rig.logs[0]["record"]["cut"] is (op == "delete_connection")
    assert rig.logs[0]["record"]["counts"]["failures"] == 1 and not held(json.dumps(rig.logs[0]["record"]))


def test_a_second_delivery_is_harmless_and_leaves_the_same_end_state() -> None:
    rig = Rig([CERT_1, CERT_2], connected=[CLIENT])
    first = rig.run(direct("ALARM"))
    state = json.dumps(rig.account, sort_keys=True)
    second = rig.run(direct("ALARM"))
    assert json.dumps(rig.account, sort_keys=True) == state and rig.is_cut()
    assert len(rig.calls) == 2 * len(writes([CERT_1, CERT_2]) + reads([CERT_1, CERT_2]))
    assert second == dict(first, connections=[{"write": "no-client-connected"}]) and second["cut"] is True and second["failures"] == []


@pytest.mark.parametrize("code,status", [("InvalidRequestException", 400), ("ResourceNotFoundException", 404),
                                         ("ConflictingResourceUpdateException", 409)])
def test_an_error_the_service_answers_for_work_already_done_is_no_failure_when_the_read_back_shows_the_cut(code: str, status: int) -> None:
    """What each API answers when its work is already done is not known (deps-map 4). Whatever it is: the read-backs,
    not the call's error code, give the verdict."""
    rig = Rig(live=False)                       # the twin as it is at A3 rows 17a and 17b: cut already
    for op in ("disable_topic_rule", "update_certificate", "detach_policy"):
        rig.fault(op, code=code, status=status)
    record = rig.run({"manual": "trip"})
    assert rig.calls == writes([CERT_1]) + reads([CERT_1]) and record["cut"] is True and record["failures"] == []
    assert record["rule"] == {"write": "answered:" + code, "state": "disabled"}
    assert record["certificates"] == [{"write": "answered:" + code, "state": "INACTIVE", "detach": "answered:" + code, "policy": "detached"}]
    answers = {c["op"]: (c["answer"], c.get("code"), c.get("http")) for c in rig.logs[0]["calls"]}
    assert answers["disable_topic_rule"] == ("error", code, status)           # the log keeps what the service said, for row 17a
    # the same answers on a twin that is NOT cut: the cut is not there, and it raises
    live = Rig()
    for op in ("disable_topic_rule", "update_certificate", "detach_policy"):
        live.fault(op, code=code, status=status)
    message = raises(live, {"manual": "trip"})
    assert "3 failure(s)" in message and not live.is_cut()


@pytest.mark.parametrize("op", ["disable_topic_rule", "update_certificate", "detach_policy"])
@pytest.mark.parametrize("code,status", [("AccessDeniedException", 403), ("UnauthorizedException", 401), ("SomethingElse", 403),
                                         ("AccessDeniedException", 400), ("NotAuthorizedException", 500),
                                         # WP7-verify-r1#3 (V04, V05, V06): what makes a refusal is the status or the code, each alone,
                                         # and a code is read in any case; a status the error does not carry is None
                                         ("SomethingElse", 401), ("ForbiddenException", None), ("ForbiddenException", 400),
                                         ("accessdeniedexception", None), ("ACCESSDENIEDEXCEPTION", 400), ("unauthorizedexception", None)])
def test_a_write_refused_as_not_authorised_raises_even_when_the_read_back_shows_the_cut(op: str, code: str, status: Optional[int]) -> None:
    """At row 17a the rule is disabled and the certificate INACTIVE already. A function that may not write is no
    breaker, and the dry trip must not pass on a twin that only happens to be cut."""
    rig = Rig(live=False)
    rig.fault(op, code=code, status=status)
    message = raises(rig, {"manual": "trip"})
    assert "not authorised" in message and "1 failure(s)" in message and rig.calls == writes([CERT_1]) + reads([CERT_1])
    record = rig.logs[0]["record"]
    assert "refused" in (record["rule"]["write"], record["certificates"][0]["write"], record["certificates"][0]["detach"])
    # and a call that got no answer at all is a failure too, whatever the read-back shows
    silent = Rig(live=False)
    silent.fault(op, no_answer=True)
    assert "got no answer" in raises(silent, {"manual": "trip"})


@pytest.mark.parametrize("op", ["disable_topic_rule", "update_certificate", "detach_policy"])
def test_a_write_the_client_has_no_method_for_is_a_failure_even_when_the_read_back_shows_the_cut(op: str) -> None:
    """WP7-verify-r1#3 (V03). A control client of a runtime whose SDK lacks the call is nothing that could have cut: on a
    twin that is cut already the read-back shows the cut all the same, and the dry trip must not pass on that."""
    rig = Rig(live=False)
    setattr(rig.iot, op, None)                  # the instance's attribute hides the method: the client has none to call
    message = raises(rig, {"manual": "trip"})
    assert "got no answer" in message and "1 failure(s)" in message
    assert rig.calls == [c for c in writes([CERT_1]) + reads([CERT_1]) if c[1] != op]       # nothing was sent for it; the rest was made
    record = rig.logs[0]["record"]
    assert "unavailable" in (record["rule"]["write"], record["certificates"][0]["write"], record["certificates"][0]["detach"])
    assert record["counts"]["calls"] == len(rig.calls) and record["counts"]["failures"] == 1
    # on a twin that is NOT cut it is the same one failure: the cut that did not happen is not said on top of it
    live = Rig()
    setattr(live.iot, op, None)
    assert "1 failure(s)" in raises(live, {"manual": "trip"}) and not live.is_cut()


@pytest.mark.parametrize("op,says", [("disable_topic_rule", "the rule is not disabled"), ("update_certificate", "is not INACTIVE"),
                                     ("detach_policy", "the policy is still attached")])
def test_a_cut_that_is_not_there_raises_although_every_call_was_accepted(op: str, says: str) -> None:
    rig = Rig()
    rig.fault(op, ignored=True)                 # the call is accepted and changes nothing
    message = raises(rig, {"manual": "trip"})
    assert says in message and "1 failure(s)" in message and rig.calls == writes([CERT_1]) + reads([CERT_1])
    record = rig.logs[0]["record"]
    assert record["cut"] is False
    assert (record["rule"]["write"], record["certificates"][0]["write"], record["certificates"][0]["detach"]) == ("ok",) * 3


@pytest.mark.parametrize("op", READS)
@pytest.mark.parametrize("how", [{"code": "AccessDeniedException", "status": 403}, {"no_answer": True},
                                 {"code": "ResourceNotFoundException", "status": 404}], ids=["denied", "no-answer", "not-found"])
def test_a_read_back_that_could_not_be_made_raises_and_the_record_never_states_what_it_did_not_read(op: str, how: Dict[str, Any]) -> None:
    rig = Rig()
    rig.fault(op, **how)
    message = raises(rig, {"manual": "trip"})
    assert "could not be read" in message and rig.is_cut() and rig.calls == writes([CERT_1]) + reads([CERT_1])
    record = rig.logs[0]["record"]
    assert record["cut"] is False
    assert record["rule"]["state"] == ("not-read" if op == "get_topic_rule" else "disabled")
    assert record["certificates"][0]["state"] == ("not-read" if op == "describe_certificate" else "INACTIVE")
    assert record["certificates"][0]["policy"] == ("not-read" if op == "list_targets_for_policy" else "detached")


def test_a_listing_of_the_policys_targets_that_goes_on_is_no_read_and_a_reply_of_another_shape_is_none_either() -> None:
    rig = Rig()
    rig.fault("list_targets_for_policy", more=True)
    assert "could not be read" in raises(rig, {"manual": "trip"}) and rig.logs[0]["record"]["certificates"][0]["policy"] == "not-read"

    class Odd(FAKE_IOT):                        # replies that are not the documented shapes: read as nothing
        def describe_certificate(self, *, certificateId: str) -> Any:
            super().describe_certificate(certificateId=certificateId)
            return {"certificateDescription": {"status": 7}}

        def get_topic_rule(self, *, ruleName: str) -> Any:
            super().get_topic_rule(ruleName=ruleName)
            return {"rule": {"ruleDisabled": "true"}}

        def list_targets_for_policy(self, *, policyName: str, pageSize: Any = None, marker: Any = None) -> Any:
            super().list_targets_for_policy(policyName=policyName, pageSize=pageSize)
            return {"targets": "none"}

    odd = Rig()
    odd.iot = Odd(odd.account, odd.calls, odd.faults)
    message = raises(odd, {"manual": "trip"})
    record = odd.logs[0]["record"]
    assert "3 failure(s)" in message
    assert (record["rule"]["state"], record["certificates"][0]["state"], record["certificates"][0]["policy"]) == ("not-read",) * 3
    # a certificate in a state that is neither: said as it is not INACTIVE, never as a cut
    other = Rig()
    other.fault("update_certificate", ignored=True)
    other.account["certs"][CERT_1]["status"] = "REVOKED"
    assert "is not INACTIVE" in raises(other, {"manual": "trip"}) and other.logs[0]["record"]["certificates"][0]["state"] == "REVOKED"
    other.account["certs"][CERT_1]["status"] = "a state with words in it, %s" % RULE
    other.fault("update_certificate", ignored=True)
    assert "is not INACTIVE" in raises(other, {"manual": "trip"}) and other.logs[1]["record"]["certificates"][0]["state"] == "other"


# ================================================================================================= DeleteConnection

def test_delete_connection_missing_from_the_client_is_a_step_unavailable_and_the_others_complete() -> None:
    rig = Rig([CERT_1, CERT_2], old_sdk=True)
    record = rig.run(direct("ALARM"))
    assert rig.calls == [c for c in writes([CERT_1, CERT_2]) if c[1] != "delete_connection"] + reads([CERT_1, CERT_2])
    assert rig.is_cut() and record["cut"] is True and record["failures"] == [] and record["has_delete_connection"] is False
    assert record["connections"] == [{"write": "unavailable"}] and record["counts"]["calls"] == 9 == len(rig.calls)
    # and no data-plane client at all (it could not be made): the others complete, and that IS said as a failure
    none = Rig()
    with pytest.raises(B.BreakerError) as e:
        B.run({"manual": "trip"}, none.env, none.iot, None, sdk=SDK, request_id=REQUEST, log=none.logs.append)
    assert none.is_cut() and "1 failure(s)" in str(e.value) and none.logs[0]["record"]["connections"] == [{"write": "failed"}]


def test_delete_connection_answering_not_found_is_no_client_connected_and_no_failure() -> None:
    for how in ({"code": "ResourceNotFoundException", "status": 404}, {"code": "SomeOtherWord", "status": 404},
                {"code": "ResourceNotFoundException", "status": 400}):
        rig = Rig(connected=[CLIENT])
        rig.fault("delete_connection", **how)
        record = rig.run({"manual": "trip"})
        assert record["connections"] == [{"write": "no-client-connected"}] and record["cut"] is True and record["failures"] == [], how
    rig = Rig()                                 # the normal case: an alarm fires minutes after the device was last connected
    assert rig.run(sns("ALARM"))["connections"] == [{"write": "no-client-connected"}]


@pytest.mark.parametrize("how", [{"code": "AccessDeniedException", "status": 403}, {"code": "ForbiddenException", "status": 403},
                                 {"code": "ThrottlingException", "status": 429}, {"code": "InternalFailureException", "status": 500},
                                 {"code": "UnauthorizedException", "status": 401}, {"no_answer": True}])
def test_any_other_error_of_delete_connection_is_a_failure_and_never_no_client(how: Dict[str, Any]) -> None:
    rig = Rig([CERT_1], [CLIENT, CLIENT_2], connected=[CLIENT, CLIENT_2])
    rig.fault("delete_connection", **how)
    message = raises(rig, {"manual": "trip"})
    assert "1 failure(s)" in message and "connection" in message and rig.calls == writes([CERT_1], [CLIENT, CLIENT_2]) + reads([CERT_1])
    connections = rig.logs[0]["record"]["connections"]
    assert connections[0]["write"] != "no-client-connected" and connections[1] == {"write": "ok"} and rig.account["connections"] == [CLIENT]
    assert rig.logs[0]["record"]["cut"] is True                                 # the three cuts are there; the step that failed has no read-back


# ================================================================================================= the environment

@pytest.mark.parametrize("missing,made", [
    ("TWIN_RULE", ["update_certificate", "delete_connection", "detach_policy", "describe_certificate", "list_targets_for_policy"]),
    ("TWIN_POLICY", ["disable_topic_rule", "update_certificate", "delete_connection", "describe_certificate", "get_topic_rule"]),
    ("TWIN_CLIENT_IDS", ["disable_topic_rule", "update_certificate", "detach_policy", "describe_certificate", "list_targets_for_policy",
                         "get_topic_rule"]),
    ("TWIN_CERTIFICATE_ARNS", ["disable_topic_rule", "delete_connection", "get_topic_rule"]),
])
@pytest.mark.parametrize("value", [None, "", "  "], ids=["unset", "empty", "blank"])
def test_a_missing_environment_value_stops_no_step_whose_inputs_are_there_and_it_raises_at_the_end(missing: str, made: List[str],
                                                                                                   value: Optional[str]) -> None:
    rig = Rig(connected=[CLIENT])
    message = raises(rig, direct("ALARM"), **{missing: value})
    assert rig.ops() == made, rig.ops()         # raising before any call would fail open
    assert missing in message and "1 failure(s)" in message
    assert rig.logs[0]["record"]["cut"] is (missing == "TWIN_CLIENT_IDS")       # `cut` is what the three read-backs show, and only that
    a = rig.account
    assert a["rules"][RULE]["ruleDisabled"] is (missing != "TWIN_RULE")
    assert a["certs"][CERT_1]["status"] == ("ACTIVE" if missing == "TWIN_CERTIFICATE_ARNS" else "INACTIVE")


def test_with_no_environment_at_all_nothing_can_be_called_and_it_raises() -> None:
    rig = Rig()
    with pytest.raises(B.BreakerError) as e:
        B.run({"manual": "trip"}, {}, rig.iot, rig.data, sdk=SDK, request_id=REQUEST, log=rig.logs.append)
    assert rig.calls == [] and "4 failure(s)" in str(e.value) and sorted(re.findall(r"TWIN_[A-Z_]+", str(e.value))) == sorted(B.ENV)
    assert B.ENV == ("TWIN_CERTIFICATE_ARNS", "TWIN_CLIENT_IDS", "TWIN_RULE", "TWIN_POLICY")
    template = json.loads((TEMPLATES / "function-environment.json").read_text(encoding="ascii"))
    assert sorted(template["Variables"]) == sorted(B.ENV)                      # the driver's template and the function read the same four


@pytest.mark.parametrize("listed,usable,unusable", [
    ("not-an-arn", 0, 1), (",,", 0, 0), ("%(one)s,not-an-arn", 1, 1), ("%(one)s,%(short)s", 1, 1), ("%(one)s,%(one)s", 1, 0),
    (" %(one)s , %(two)s ", 2, 0), ("%(policy)s", 0, 1), ("%(upper)s", 0, 1), ("%(one)s %(two)s", 0, 1),
    # WP7-verify-r1#3 (V19, V20): the id in upper-case hex alone, and an ARN with no region, no account, or neither
    ("%(idupper)s", 0, 1), ("%(noboth)s", 0, 1), ("%(noregion)s", 0, 1), ("%(noaccount)s", 0, 1)])
def test_an_empty_or_unusable_certificate_list_raises_after_every_step_that_can_still_be_attempted(listed: str, usable: int, unusable: int) -> None:
    rig = Rig([CERT_1, CERT_2], connected=[CLIENT])
    value = listed % {"one": arn(CERT_1), "two": arn(CERT_2), "short": arn(CERT_1)[:-1], "upper": arn(CERT_1).upper(),
                      "policy": "arn:aws:iot:%s:%s:policy/%s" % (REGION, ACCOUNT, POLICY),
                      "idupper": "arn:aws:iot:%s:%s:cert/%s" % (REGION, ACCOUNT, CERT_1.upper()), "noboth": "arn:aws:iot:::cert/" + CERT_1,
                      "noregion": "arn:aws:iot::%s:cert/%s" % (ACCOUNT, CERT_1), "noaccount": "arn:aws:iot:%s::cert/%s" % (REGION, CERT_1)}
    if usable and not unusable:                 # every entry is a certificate's ARN (one named twice is one): no failure
        record = rig.run({"manual": "trip"}, TWIN_CERTIFICATE_ARNS=value)
        assert record["cut"] is True and record["counts"]["certificates"] == usable and rig.calls == writes([CERT_1, CERT_2][:usable]) + reads(
            [CERT_1, CERT_2][:usable])
        return
    message = raises(rig, {"manual": "trip"}, TWIN_CERTIFICATE_ARNS=value)
    certs = [CERT_1][:usable]
    expect = writes(certs) + reads(certs)
    if not certs:
        expect = [c for c in expect if c[1] != "list_targets_for_policy"]      # no certificate to look for among the targets
    assert rig.calls == expect and rig.account["rules"][RULE]["ruleDisabled"] is True and rig.account["connections"] == []
    counts = rig.logs[0]["record"]["counts"]
    assert (counts["certificates"], counts["unusable_certificates"]) == (usable, unusable) and "TWIN_CERTIFICATE_ARNS" in message
    assert rig.account["certs"][CERT_2]["status"] == "ACTIVE"                   # it was not named: the function does not guess
    # WP7-verify-r2#2 (B05). The list is ONE failure, said once: with no usable certificate the unusable entries are counted in the
    # sentence that says so, not in a second one beside it
    assert "1 failure(s)" in message and counts["failures"] == 1 and len(rig.logs[0]["record"]["failures"]) == 1


def test_a_client_id_given_twice_is_one_connection_deleted_once() -> None:
    """WP7-verify-r1#3 (V07). One id named twice is one id: one DeleteConnection, one entry in the record, and it does not
    count against the largest set the function's time is counted for."""
    rig = Rig(connected=[CLIENT])
    record = rig.run({"manual": "trip"}, TWIN_CLIENT_IDS=" %s , %s,%s " % (CLIENT, CLIENT, CLIENT))
    assert rig.calls == writes([CERT_1]) + reads([CERT_1]) and sum(1 for c in rig.calls if c[1] == "delete_connection") == 1
    assert record["connections"] == [{"write": "ok"}] and record["counts"]["client_ids"] == 1 and record["failures"] == []
    assert record["cut"] is True and rig.account["connections"] == []
    both = Rig([CERT_1], [CLIENT, CLIENT_2], connected=[CLIENT, CLIENT_2])          # two ids, one of them named again: two calls, in order
    record = both.run({"manual": "trip"}, TWIN_CLIENT_IDS="%s,%s,%s" % (CLIENT, CLIENT_2, CLIENT))
    assert both.calls == writes([CERT_1], [CLIENT, CLIENT_2]) + reads([CERT_1]) and record["counts"]["client_ids"] == 2 and record["failures"] == []


def test_the_rule_and_the_policy_go_into_the_calls_without_the_blanks_around_them() -> None:
    """WP7-verify-r1#3 (V16). A name with a blank or a tab around it (a value typed into a console) is the name: the calls
    carry the trimmed rule and policy, not a name no rule has."""
    rig = Rig(connected=[CLIENT])
    record = rig.run({"manual": "trip"}, TWIN_RULE="  %s\t" % RULE, TWIN_POLICY="\t%s \n" % POLICY)
    assert rig.calls == writes([CERT_1]) + reads([CERT_1]) and rig.is_cut() and record["cut"] is True and record["failures"] == []
    assert [c[2]["ruleName"] for c in rig.calls if "ruleName" in c[2]] == [RULE] * 2        # the disable and the read-back
    assert [c[2]["policyName"] for c in rig.calls if "policyName" in c[2]] == [POLICY] * 2  # the detach and the listing of the targets


def test_more_certificates_than_the_time_is_counted_for_are_all_acted_on_and_it_raises() -> None:
    certs = [CERT_1, CERT_2, "0f1e2d3c4b5a6978" * 4]
    assert len(certs) == B.MAX_CERTIFICATES + 1
    rig = Rig(certs)
    message = raises(rig, {"manual": "trip"})
    assert rig.calls == writes(certs) + reads(certs) and rig.is_cut() and "more than the %d" % B.MAX_CERTIFICATES in message
    clients = [CLIENT, CLIENT_2, "example-thing-three"]
    rig = Rig([CERT_1], clients)
    message = raises(rig, {"manual": "trip"})
    assert rig.calls == writes([CERT_1], clients) + reads([CERT_1]) and rig.is_cut() and "more than the %d" % B.MAX_CLIENT_IDS in message


def test_nothing_of_the_environment_is_in_a_raised_message_or_in_the_returned_record() -> None:
    """The payload lands in the driver's state directory and `trip --capture` copies it; an unhandled error's message
    comes back in the payload as well. States and counts only."""
    seen = []
    for op in WRITES + READS:
        for how in ({"code": "AccessDeniedException", "status": 403}, {"no_answer": True}, {"code": "x" * 80 + RULE, "status": 400},
                    {"code": "arn:aws:iot:" + ACCOUNT, "status": 404}):
            for event in ({"manual": "trip"}, {"manual": "status"}, direct("ALARM"), sns("ALARM")):
                rig = Rig([CERT_1, CERT_2], [CLIENT, CLIENT_2], connected=[CLIENT])
                rig.fault(op, **how)
                try:
                    seen.append(json.dumps(rig.run(event)))
                except B.BreakerError as e:
                    seen += [str(e), repr(e), json.dumps(rig.logs[0]["record"])]
                assert len(rig.logs) == 1
    for value in (None, "not-an-arn," + RULE):
        rig = Rig()
        seen.append(raises(rig, {"manual": "trip"}, TWIN_CERTIFICATE_ARNS=value))
        seen.append(json.dumps(rig.logs[0]["record"]))
    rig = Rig()                                 # and the SDK's version is given back in the form a version has, or not at all
    seen.append(json.dumps(B.run({"manual": "status"}, rig.env, rig.iot, rig.data, sdk="9.9 for %s" % RULE, request_id=REQUEST, log=rig.logs.append)))
    assert rig.logs[0]["record"]["boto3"] == "unknown"
    assert len(seen) > 150 and not [s for s in seen if held(s)]
    assert not [s for s in seen if LS.findings(s, False, list(SECRETS))]       # and no shape the scanner knows
    # the log record is the one place that names them
    rig = Rig()
    rig.run(direct("ALARM"))
    assert set(held(json.dumps(rig.logs[0]))) >= {ACCOUNT, RULE, POLICY, CLIENT, CERT_1, REQUEST, ALARM}


def test_an_error_no_step_names_is_raised_by_its_kind_alone_and_a_log_that_fails_stops_nothing() -> None:
    class Hostile(dict):                        # an environment that raises with a value in its message
        def get(self, key: Any, default: Any = None) -> Any:
            raise RuntimeError("the value %s of the environment" % RULE)

    rig = Rig()
    with pytest.raises(B.BreakerError) as e:
        B.run({"manual": "trip"}, Hostile(), rig.iot, rig.data, sdk=SDK, request_id=REQUEST, log=rig.logs.append)
    assert "RuntimeError" in str(e.value) and not held(str(e.value)) and e.value.__cause__ is None and e.value.__suppress_context__ is True

    def broken(record: Any) -> None:
        raise OSError("the log could not be written for %s" % RULE)

    rig = Rig()
    record = B.run({"manual": "trip"}, rig.env, rig.iot, rig.data, sdk=SDK, request_id=REQUEST, log=broken)
    assert record["cut"] is True and rig.is_cut()
    rig = Rig()
    rig.fault("detach_policy", ignored=True)
    with pytest.raises(B.BreakerError) as e:
        B.run({"manual": "trip"}, rig.env, rig.iot, rig.data, sdk=SDK, request_id=REQUEST, log=broken)
    assert "the policy is still attached" in str(e.value) and not held(str(e.value))


def test_the_log_record_of_an_error_no_step_names_holds_the_request_and_the_kind_and_nothing_else() -> None:
    """WP7-verify-r1#3 (V10). The one place that tells which run stopped on an error nobody named is the log record: it
    holds the request's id and the error's kind, and nothing of the error's own text (that could hold a value)."""
    class Hostile(dict):                        # an environment that raises with a value in its message
        def get(self, key: Any, default: Any = None) -> Any:
            raise RuntimeError("the value %s of the environment" % RULE)

    rig = Rig()
    with pytest.raises(B.BreakerError):
        B.run({"manual": "trip"}, Hostile(), rig.iot, rig.data, sdk=SDK, request_id=REQUEST, log=rig.logs.append)
    assert rig.logs == [{"breaker": 1, "request_id": REQUEST, "error": "RuntimeError"}] and rig.calls == []
    assert RULE not in json.dumps(rig.logs)


def test_a_failed_status_and_a_failed_trip_each_say_which_of_the_two_did_not_complete() -> None:
    """WP7-verify-r1#3 (V18). The text that is raised is what the dry trip and the status print: `the status did not
    complete` of a status, `the trip did not complete` of a trip."""
    status = Rig(live=False)
    status.fault("get_topic_rule", code="AccessDeniedException", status=403)
    assert raises(status, {"manual": "status"}).startswith("the status did not complete: 1 failure(s): ")
    trip = Rig()
    trip.fault("disable_topic_rule", ignored=True)
    assert raises(trip, {"manual": "trip"}).startswith("the trip did not complete: 1 failure(s): ")
    alarm = Rig()
    alarm.fault("update_certificate", ignored=True)
    assert raises(alarm, direct("ALARM")).startswith("the trip did not complete: 1 failure(s): ")
    unset = Rig()
    assert raises(unset, {"manual": "status"}, TWIN_RULE=None).startswith("the status did not complete: 1 failure(s): ")


@pytest.mark.parametrize("sdk", [123, None, 9.9, ["1.2.3"], b"1.2.3", True], ids=lambda v: type(v).__name__)
def test_an_sdk_version_that_is_no_text_keeps_no_step_from_being_attempted(sdk: Any) -> None:
    """WP7-verify-r1, NIT 7. The record's head was built before the cut, and a version that is no text ended the function
    there on a TypeError: no call was made, and the twin was not cut. The cut does not wait on bookkeeping."""
    rig = Rig(connected=[CLIENT])
    record = B.run({"manual": "trip"}, rig.env, rig.iot, rig.data, sdk=sdk, request_id=REQUEST, log=rig.logs.append)
    assert rig.calls == writes([CERT_1]) + reads([CERT_1]) and rig.is_cut() and record["cut"] is True
    assert record["boto3"] == "unknown" and rig.logs[0]["record"]["boto3"] == "unknown" and not held(json.dumps(record))


# ================================================================================================= guards for inputs the real SDK does not give
# Regression guards for inputs the real SDK, the runtime or an unedited environment does not give, and for what the record
# says of a step that was not attempted. Each case below holds the one thing it changes.

@pytest.mark.parametrize("op", WRITES)
def test_an_error_whose_status_is_true_and_that_has_no_code_is_no_answer_of_the_service(op: str) -> None:
    """WP7-verify-r2#2 (B03). `True` is an int in Python: an error whose HTTP status is True and that carries no code is no
    answer of the service, and on a twin that is cut already the read-back must not make it one. It is a call that got no
    answer, said so, whatever the read-back shows."""
    rig = Rig(live=False)
    rig.fault(op, code=None, status=True)
    message = raises(rig, {"manual": "trip"})
    assert "got no answer" in message and "1 failure(s)" in message and rig.calls == writes([CERT_1]) + reads([CERT_1])
    answer = [c for c in rig.logs[0]["calls"] if c["op"] == op]
    assert [c["answer"] for c in answer] == ["no-answer"] and "http" not in answer[0] and "code" not in answer[0]
    assert rig.logs[0]["record"]["counts"]["failures"] == 1


@pytest.mark.parametrize("status", [None, 500], ids=["no-status", "status-500"])
def test_an_error_whose_code_is_a_number_is_read_as_no_code_and_stops_no_step(status: Optional[int]) -> None:
    """WP7-verify-r2#2 (B04). A code that is no text is no code. The first write failing with one must not end the function
    on an error of its own: the other six calls are still made, and it raises at the end."""
    rig = Rig(connected=[CLIENT])
    rig.fault("disable_topic_rule", code=7, status=status)
    message = raises(rig, {"manual": "trip"})
    assert rig.calls == writes([CERT_1]) + reads([CERT_1]), rig.calls          # all seven calls were made
    assert "1 failure(s)" in message and "stopped on an error no step names" not in message
    first = rig.logs[0]["calls"][0]
    assert first["op"] == "disable_topic_rule" and rig.logs[0]["record"]["counts"]["calls"] == 7
    if status is None:                                                        # no code and no status: no answer
        assert "the rule: its disable call got no answer" in message and first["answer"] == "no-answer"
        assert rig.logs[0]["record"]["rule"]["write"] == "failed"
    else:                                                                     # an answer with no code: judged by the read-back
        assert "the rule is not disabled" in message and (first["answer"], first["code"], first["http"]) == ("error", "", 500)
        assert rig.logs[0]["record"]["rule"]["write"] == "answered"
    assert rig.is_cut() is False and rig.account["certs"][CERT_1] == {"status": "INACTIVE", "policies": []}     # the other steps were done


@pytest.mark.parametrize("op", [("update_certificate", "describe_certificate"), ("disable_topic_rule", "get_topic_rule"),
                                ("detach_policy", "list_targets_for_policy")], ids=lambda p: p[0])
@pytest.mark.parametrize("how,says", [({"code": "AccessDeniedException", "status": 403}, "was refused as not authorised"),
                                      ({"no_answer": True}, "got no answer")], ids=["refused", "no-answer"])
def test_a_write_that_failed_is_said_to_have_failed_also_when_its_read_back_could_not_be_made(op: Tuple[str, str], how: Dict[str, Any],
                                                                                              says: str) -> None:
    """WP7-verify-r2#2 (B09). A write that was refused, or got no answer, is a failure whatever was read back, and it is
    said so: not as a state that could not be read (which is what a read-back that also failed would otherwise make it)."""
    write, read = op
    rig = Rig()
    rig.fault(write, **how)
    rig.fault(read, no_answer=True)
    message = raises(rig, {"manual": "trip"})
    assert "1 failure(s)" in message and says in message and "could not be read" not in message, message
    assert rig.calls == writes([CERT_1]) + reads([CERT_1])


def test_targets_that_are_no_texts_are_no_read_of_the_listing_and_the_log_record_is_written() -> None:
    """WP7-verify-r2#2 (B07). A listing of the policy's targets whose items are not texts is not the documented shape: it is
    no read. Taken for one, the check of which certificate is attached stops on a TypeError, and the run ends on an error
    no step names, with no record of the cut that was made."""
    class Odd(FAKE_IOT):
        listed: List[Any] = []

        def list_targets_for_policy(self, *, policyName: str, pageSize: Any = None, marker: Any = None) -> Any:
            super().list_targets_for_policy(policyName=policyName, pageSize=pageSize)
            return {"targets": list(self.listed)}

    for targets in ([7], [None], [CERT_1, 7], [{"arn": 1}]):
        rig = Rig()
        odd = Odd(rig.account, rig.calls, rig.faults)
        odd.listed = list(targets)
        rig.iot = odd
        message = raises(rig, {"manual": "trip"})
        assert "the policy's targets could not be read" in message and "1 failure(s)" in message, (targets, message)
        assert "stopped on an error no step names" not in message and rig.is_cut() and rig.calls == writes([CERT_1]) + reads([CERT_1])
        assert len(rig.logs) == 1 and "error" not in rig.logs[0] and rig.logs[0]["record"]["certificates"][0]["policy"] == "not-read"
        assert rig.logs[0]["record"]["cut"] is False


@pytest.mark.parametrize("certs", [[CERT_1], [CERT_1, CERT_2]], ids=["one-certificate", "two-certificates"])
def test_a_write_that_was_never_attempted_is_said_not_attempted_in_the_record_and_never_ok(certs: List[str]) -> None:
    """WP7-verify-r2#2 (B10, B16). With no rule named the rule's disable is not attempted; with no policy named no detach
    is. The log's record says `not-attempted` of each, and never `ok`: nothing of it was done."""
    no_rule = Rig(certs, connected=[CLIENT])
    assert "TWIN_RULE is not set" in raises(no_rule, {"manual": "trip"}, TWIN_RULE=None)
    record = no_rule.logs[0]["record"]
    assert record["rule"] == {"write": "not-attempted", "state": "not-read"}
    assert [(c["write"], c["detach"]) for c in record["certificates"]] == [("ok", "ok")] * len(certs)
    no_policy = Rig(certs, connected=[CLIENT])
    assert "TWIN_POLICY is not set" in raises(no_policy, {"manual": "trip"}, TWIN_POLICY=None)
    record = no_policy.logs[0]["record"]
    assert record["rule"] == {"write": "ok", "state": "disabled"}
    assert record["certificates"] == [{"write": "ok", "state": "INACTIVE", "detach": "not-attempted", "policy": "not-read"}] * len(certs)
    assert not [c for c in no_policy.calls if c[1] in ("detach_policy", "list_targets_for_policy")]


@pytest.mark.parametrize("shape", ["direct", "sns"])
def test_an_alarms_name_longer_than_the_log_keeps_is_not_kept_and_the_trip_does_not_depend_on_it(shape: str) -> None:
    """WP7-verify-r2#2 (B15). The alarm's name goes into the log record as the event gives it, up to 256 characters; a longer
    one, an empty one and one that is no text are not kept. The trip is the same in every case."""
    def event(name: Any) -> Dict[str, Any]:
        if shape == "direct":
            out = direct("ALARM")
            out["alarmData"]["alarmName"] = name
            return out
        out = sns("ALARM")
        record = out["Records"][0]
        message = json.loads(record["Sns"]["Message"])
        message["AlarmName"] = name
        record["Sns"]["Message"] = json.dumps(message)
        return out

    for name, kept in (("a" * 256, True), ("a" * 257, False), ("a" * 5000, False), ("", False), (7, False), (None, False)):
        rig = Rig(connected=[CLIENT])
        record = rig.run(event(name))
        assert rig.logs[0]["alarm"] == (name if kept else None), (shape, str(name)[:8], len(str(name)))
        assert record["cut"] is True and rig.is_cut() and rig.logs[0]["mode"] == "trip"


@pytest.mark.parametrize("event", [direct("OK"), direct("INSUFFICIENT_DATA"), sns("OK"), sns("OK", "INSUFFICIENT_DATA")],
                         ids=["direct-ok", "direct-insufficient", "sns-ok", "sns-ok-and-insufficient"])
def test_a_cleanly_read_ok_needs_no_environment_and_neither_raises_nor_calls_anything(event: Dict[str, Any]) -> None:
    """WP7-verify-r2#2 (B17). An alarm that went back to OK (or lost its data) is row 4: nothing is done, so a missing value
    of the environment is nothing to fail on. The function returns; it does not raise for inputs it has no use for."""
    rig = Rig()
    record = B.run(event, {}, rig.iot, rig.data, sdk=SDK, request_id=REQUEST, log=rig.logs.append)
    assert rig.calls == [] and record["mode"] == "none" and record["failures"] == [] and record["cut"] is None
    assert record["counts"] == {"certificates": 0, "client_ids": 0, "unusable_certificates": 0, "calls": 0, "failures": 0}
    assert len(rig.logs) == 1 and rig.logs[0]["record"] == record and rig.logs[0]["mode"] == "none"


# ================================================================================================= the handler and its clients

class Context:
    aws_request_id = REQUEST


def fake_sdk(monkeypatch: pytest.MonkeyPatch, rig: Rig, broken: Sequence[str] = ()) -> List[Any]:
    """Stand-ins for the two SDK modules the handler imports, in sys.modules: they hand out the rig's fake clients and
    record how each was asked for."""
    made: List[Any] = []

    class Config:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    def client(service: str, **kwargs: Any) -> Any:
        made.append((service, kwargs))
        if service in broken:
            raise RuntimeError("the client for %s could not be made for %s" % (service, RULE))
        return {"iot": rig.iot, "iot-data": rig.data}[service]

    sdk, core, config = types.ModuleType("boto3"), types.ModuleType("botocore"), types.ModuleType("botocore.config")
    sdk.__version__, sdk.client = SDK, client                      # type: ignore[attr-defined]
    config.Config, core.config = Config, config                    # type: ignore[attr-defined]
    for name, mod in (("boto3", sdk), ("botocore", core), ("botocore.config", config)):
        monkeypatch.setitem(sys.modules, name, mod)
    return made


def set_env(monkeypatch: pytest.MonkeyPatch, rig: Rig) -> None:
    for key, value in rig.env.items():
        monkeypatch.setenv(key, value)


def test_the_handler_makes_its_two_clients_in_one_place_with_short_time_outs_and_no_endpoint_of_the_environments(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(connected=[CLIENT])
    made = fake_sdk(monkeypatch, rig)
    set_env(monkeypatch, rig)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://example.invalid/")          # what an environment could hold: the clients are told to ignore it
    record = B.handler(direct("ALARM"), Context())
    assert rig.calls == writes([CERT_1]) + reads([CERT_1]) and rig.is_cut() and record["cut"] is True and record["boto3"] == SDK
    assert [service for service, _kw in made] == ["iot", "iot-data"]
    for _service, kwargs in made:
        assert list(kwargs) == ["config"]                                       # no endpoint, no region, no credential: the runtime's own
        assert kwargs["config"].kwargs == {"connect_timeout": B.CONNECT_TIMEOUT_S, "read_timeout": B.READ_TIMEOUT_S,
                                           "retries": {"total_max_attempts": B.ATTEMPTS, "mode": "standard"},
                                           "ignore_configured_endpoint_urls": True}
    out = capsys.readouterr().out
    line, = [ln for ln in out.split("\n") if ln.strip()]                        # one log record, one line
    log = json.loads(line)
    assert log["request_id"] == REQUEST and log["invoked_by"] == "alarm" and log["alarm"] == ALARM and log["record"] == record
    # the time the function has, counted: every call of the largest set it takes, each as long as a silent endpoint lets it
    # last when its name resolves to the number of addresses the file names (the connect time-out is per address)
    calls = 3 * B.MAX_CERTIFICATES + B.MAX_CLIENT_IDS + 3
    largest = Rig([CERT_1, CERT_2][:B.MAX_CERTIFICATES], [CLIENT, CLIENT_2][:B.MAX_CLIENT_IDS])
    largest.run({"manual": "trip"})
    assert len(largest.calls) == calls
    assert counted(B.ADDRESSES) == calls * B.ATTEMPTS * (B.ADDRESSES * B.CONNECT_TIMEOUT_S + B.READ_TIMEOUT_S) + B.RESERVE_S <= B.FUNCTION_TIMEOUT_S
    assert B.ATTEMPTS == 1 and B.CONNECT_TIMEOUT_S > 0 and B.READ_TIMEOUT_S > 0 and B.RESERVE_S >= 5 and B.MAX_CERTIFICATES >= 2
    driver = (REPO / "sdv" / "cloud" / "twinctl.py").read_text(encoding="utf-8")
    assert '"--timeout", "%d"' % B.FUNCTION_TIMEOUT_S in driver and '"Timeout": %d' % B.FUNCTION_TIMEOUT_S in driver
    assert TW.HANDLER == "breaker.handler" and callable(B.handler)


def test_the_log_record_is_one_json_line_with_exactly_one_line_end(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """WP7-critic, ledger WP7#2 (WP7-verify-final's VB07). The docstring says "one JSON line on standard output". After one run
    of the handler the output is that line and its line end, once: a record written without its end would run into the
    runtime's next line of the log, and the whole file passed with the end taken out."""
    rig = Rig(connected=[CLIENT])
    fake_sdk(monkeypatch, rig)
    set_env(monkeypatch, rig)
    record = B.handler(direct("ALARM"), Context())
    out = capsys.readouterr().out
    assert out.endswith("\n") and not out.endswith("\n\n") and out.count("\n") == 1
    assert out.split("\n")[1:] == [""] and len(out.splitlines()) == 1
    assert json.loads(out.split("\n")[0])["record"] == record


def test_a_failed_calls_journal_entry_keeps_the_errors_class_beside_what_the_service_said() -> None:
    """WP7-critic, ledger WP7#3 (WP7-verify-final's VB12). For a call that got no answer the class of the error raised is the
    only thing in the log record that tells a time-out from a refused connection; for an answered one it is kept beside the
    code and the status. An accepted call carries none."""
    rig = Rig([CERT_1, CERT_2], connected=[CLIENT])
    rig.fault("update_certificate", no_answer=True)
    rig.fault("detach_policy", code="InternalFailureException", status=500)
    rig.fault("describe_certificate", code="ThrottlingException", status=429)
    raises(rig, {"manual": "trip"})
    log, = rig.logs
    by_op: Dict[str, List[Dict[str, Any]]] = {}
    for entry in log["calls"]:
        by_op.setdefault(entry["op"], []).append(entry)
    silent = by_op["update_certificate"][0]
    assert (silent["answer"], silent["type"]) == ("no-answer", STUB.NoAnswer.__name__) and "code" not in silent and "http" not in silent
    answered = by_op["detach_policy"][0]
    assert (answered["answer"], answered["code"], answered["http"], answered["type"]) == ("error", "InternalFailureException", 500,
                                                                                       STUB.ClientError.__name__)
    read = by_op["describe_certificate"][0]
    assert (read["answer"], read["code"], read["http"], read["type"]) == ("error", "ThrottlingException", 429, STUB.ClientError.__name__)
    assert [e for e in log["calls"] if e["answer"] == "ok"] and not [e for e in log["calls"] if e["answer"] == "ok" and "type" in e]


def counted(addresses: int, certificates: Optional[int] = None, client_ids: Optional[int] = None) -> int:
    """THE TIME IT HAS, as the module's docstring counts it: every call of a trip, each as long as an endpoint that answers
    nothing lets it last when its name resolves to `addresses` addresses (the connect time-out once per address, the read
    time-out once), and the reserve. For the largest set the time is counted for, unless another is given."""
    c = B.MAX_CERTIFICATES if certificates is None else certificates
    k = B.MAX_CLIENT_IDS if client_ids is None else client_ids
    return int((3 * c + k + 3) * B.ATTEMPTS * (addresses * B.CONNECT_TIMEOUT_S + B.READ_TIMEOUT_S) + B.RESERVE_S)


def test_the_time_is_counted_for_the_addresses_the_file_names_and_no_call_is_said_to_be_bounded() -> None:
    """The hard review of WP7 (fable-wp7), SHOULD 1. The file counted its time on "one call ends within 2 s of waiting on a
    socket whatever its endpoint does". The SDK's HTTP layer tries EVERY address an endpoint's name resolves to, each
    with the whole connect time-out, so a silent endpoint costs one call N seconds of connecting, and the runtime then
    ends the function before its later steps. The count is made for the number of addresses the file names, the words
    say what is not held, and nothing says that a call is bounded."""
    assert isinstance(B.ADDRESSES, int) and not isinstance(B.ADDRESSES, bool) and B.ADDRESSES >= 1
    # it holds for the number the file names and for not one more: the constant is the largest the function's time covers
    assert counted(B.ADDRESSES) <= B.FUNCTION_TIMEOUT_S < counted(B.ADDRESSES + 1)
    assert counted(B.ADDRESSES, 1, 1) <= B.FUNCTION_TIMEOUT_S         # the twin as decided: one certificate, one client id
    doc = " ".join(str(B.__doc__).split())
    time = doc[doc.index("THE TIME IT HAS"):doc.index("WHAT IT RETURNS, RAISES AND LOGS")]
    for gone in ("whatever its endpoint does", "one call ends within 2 s"):
        assert gone not in doc, gone
    for said in ("per ADDRESS", "ADDRESSES = %d" % B.ADDRESSES, "per read of the socket", "the runtime ends the function", "Errors metric",
                 "A3 row 13"):
        assert said in time, said
    readme = " ".join((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8").split())
    its_time = readme[readme.index("**Its time is counted"):readme.index("**What it returns and raises")]
    assert "a silent endpoint cannot take the function's whole time" not in readme
    for said in ("per address", "the runtime ends the function", "the function-status reading"):
        assert said in its_time, said


def test_a_client_that_cannot_be_made_stops_no_step_of_the_other_client(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(connected=[CLIENT])
    fake_sdk(monkeypatch, rig, broken=["iot-data"])
    set_env(monkeypatch, rig)
    with pytest.raises(B.BreakerError) as e:
        B.handler({"manual": "trip"}, Context())
    assert rig.is_cut() and "1 failure(s)" in str(e.value) and not held(str(e.value)) and rig.account["connections"] == [CLIENT]
    rig = Rig(connected=[CLIENT])
    fake_sdk(monkeypatch, rig, broken=["iot"])
    set_env(monkeypatch, rig)
    with pytest.raises(B.BreakerError) as e:
        B.handler({"manual": "trip"}, Context())
    assert rig.ops() == ["delete_connection"] and rig.account["connections"] == [] and not rig.is_cut() and not held(str(e.value))
    capsys.readouterr()


def test_the_module_and_this_file_need_no_sdk(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name.split(".")[0] for n in top if isinstance(n, ast.Import) for a in n.names} | {
        str(n.module).split(".")[0] for n in top if isinstance(n, ast.ImportFrom)}
    assert names <= {"json", "os", "re", "sys", "__future__", "typing"}, names   # the standard library, at the module's top
    inner = [n for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) for n in ast.walk(f) if isinstance(n, (ast.Import, ast.ImportFrom))]
    where = {f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) for n in ast.walk(f) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert where == {"_clients"} and len(inner) == 2                            # the SDK is imported where the real clients are made, only
    mine = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(mine) if isinstance(n, ast.Import) for a in n.names} | {
        str(n.module).split(".")[0] for n in ast.walk(mine) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"boto3", "botocore"}
    text = Path(__file__).read_text(encoding="utf-8")
    for word in ("sk" + "ip", "xf" + "ail"):                                   # no mark that passes a test over
        assert word not in text, word
    # with no SDK to import, the module still loads, and the handler raises by the error's kind
    for name in ("boto3", "botocore", "botocore.config"):
        monkeypatch.setitem(sys.modules, name, None)
    again = _load("sdv_cloud_breaker_without_an_sdk", SOURCE)
    rig = Rig()
    set_env(monkeypatch, rig)
    with pytest.raises(again.BreakerError) as e:
        again.handler({"manual": "trip"}, Context())
    assert rig.calls == [] and not held(str(e.value)) and "4 failure(s)" in str(e.value)
    assert json.loads(capsys.readouterr().out.strip())["record"]["boto3"] == "unknown"


# ================================================================================================= the role, and what the file can do

def sends(tree: ast.AST) -> List[Tuple[str, str, ast.Call]]:
    """Every call the file makes to a client: _send(journal, PLANE, client, OPERATION, ...), by its two constants."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_send":
            plane, op = node.args[1], node.args[3]
            assert isinstance(plane, ast.Constant) and isinstance(op, ast.Constant), "an operation that is no constant of the file"
            out.append((str(plane.value), str(op.value), node))
    return out


def test_the_operations_the_file_calls_are_exactly_the_roles_iot_actions_each_on_the_resource_its_call_names() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    calls = sends(tree)
    ops = {(plane, op) for plane, op, _node in calls}
    assert ops == {("iot", "disable_topic_rule"), ("iot", "update_certificate"), ("iot-data", "delete_connection"), ("iot", "detach_policy"),
                   ("iot", "describe_certificate"), ("iot", "list_targets_for_policy"), ("iot", "get_topic_rule")}
    actions = {"iot:" + "".join(w.capitalize() for w in op.split("_")) for _plane, op in ops}
    template = json.loads((TEMPLATES / "breaker-role-policy.json").read_text(encoding="ascii"))
    resource = {a: st["Resource"] for st in template["Statement"] for a in TW._listed(st["Action"])}
    assert actions == {a for a in resource if a.startswith("iot:")} == {a for a in TW.ALLOWS["breaker-role-policy"] if a.startswith("iot:")}
    assert set(resource) - actions == {"logs:CreateLogStream", "logs:PutLogEvents"} == set(TW.ALLOWS["breaker-role-policy"]) - actions
    assert resource["logs:PutLogEvents"] == "@@BREAKER_LOG_GROUP_ARN@@:log-stream:*"
    # each call names one resource, by one argument; the role's statement is on that resource's form (IAM scopes the detach
    # to its target, the certificate, never to the policy)
    named = {"disable_topic_rule": ("ruleName", "@@RULE_ARN@@"), "get_topic_rule": ("ruleName", "@@RULE_ARN@@"),
             "update_certificate": ("certificateId", "@@CERT_ARN@@"), "describe_certificate": ("certificateId", "@@CERT_ARN@@"),
             "detach_policy": ("target", "@@CERT_ARN@@"), "delete_connection": ("clientId", "@@CLIENT_ARN@@"),
             "list_targets_for_policy": ("policyName", "@@POLICY_ARN@@")}
    for _plane, op, node in calls:
        argument, form = named[op]
        assert argument in {k.arg for k in node.keywords}, op
        assert resource["iot:" + "".join(w.capitalize() for w in op.split("_"))] == form, op
    env = json.loads((TEMPLATES / "function-environment.json").read_text(encoding="ascii"))["Variables"]
    assert env == {"TWIN_CERTIFICATE_ARNS": "@@CERT_ARN@@", "TWIN_CLIENT_IDS": "@@THING@@", "TWIN_RULE": "@@RULE@@", "TWIN_POLICY": "@@POLICY@@"}


def test_no_enable_attach_or_activate_exists_in_the_file() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = sends(tree)
    more = ("enable", "attach", "create", "put", "set", "update_")
    assert not [op for _plane, op, _node in calls if op.startswith(more) and op != "update_certificate"]
    status = [k.value for _plane, _op, node in calls for k in node.keywords if k.arg == "newStatus"]
    assert len(status) == 1 and isinstance(status[0], ast.Constant) and status[0].value == "INACTIVE"
    # a client is only ever handed to _send: nothing is called on one directly, and no operation's name is put together
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert node.value.id not in ("iot", "iot_data", "client", "data"), "an attribute of a client at line %d" % node.lineno
    getattrs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "getattr"]
    assert len(getattrs) == 4                   # in _send the operation and an error's response; the data plane's call looked for; the request's id
    assert sum(1 for g in getattrs if isinstance(g.args[1], ast.Constant)) == 3
    assert [g.args[1].id for g in getattrs if isinstance(g.args[1], ast.Name)] == ["op"]      # the one name that is no constant: _send's own
    for word in ("enable_topic_rule", "attach_policy", "attach_thing_principal", "set_as_active", '"ACTIVE"', "'ACTIVE'"):
        assert word not in source, word
    # and the fake it is tested on has no such call to land on either
    assert sorted(m for m in vars(STUB.FakeIot) if not m.startswith("_")) == sorted(op for plane, op, _n in calls if plane == "iot")


def test_the_words_on_what_the_role_can_and_cannot_do_are_what_the_policy_and_the_code_hold() -> None:
    """WP7-verify-r1#6. The file and the README said that the role "allows none" of enabling, attaching and activating. The
    role holds iot:UpdateCertificate (it must, to deactivate), and IAM cannot narrow the new status to INACTIVE, so the role
    CAN activate: that the function never does is held by this code (the one literal INACTIVE, the test above). The words
    say that, and the policy holds the premise they state."""
    said = ("Its role allows no enabling and no attaching; it must hold iot:UpdateCertificate to deactivate, which IAM cannot narrow to "
            "INACTIVE, so that the function never activates is held by this code (the one literal INACTIVE) and by a test.")
    readme = " ".join((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8").split())
    docstring = " ".join(str(B.__doc__).split())
    assert said in docstring and said in readme
    assert "allows none" not in docstring and "allows none" not in readme
    template = json.loads((TEMPLATES / "breaker-role-policy.json").read_text(encoding="ascii"))
    actions = {a for st in template["Statement"] for a in TW._listed(st["Action"])}
    assert "iot:UpdateCertificate" in actions                   # the premise: the role can update a certificate, to any status
    assert not [a for a in actions if a.startswith("iot:") and a.split(":")[1].startswith(("Enable", "Attach", "Create", "Register", "Set", "Put"))]


# ================================================================================================= the zip

FIXED_SOURCE = b"def handler(event, context):\n    return None\n"
FIXED_DIGEST = "4b03cc2df9b6b3a6c356de5aada7697208f61557cd72e2db278ebd602204881a"


def test_two_builds_give_the_same_bytes_and_the_bytes_are_the_same_on_every_platform() -> None:
    source = SOURCE.read_bytes()
    one, two = TW.zip_bytes(source), TW.zip_bytes(source)
    assert one == two and hashlib.sha256(one).hexdigest() == hashlib.sha256(two).hexdigest()
    # a fixed source has one digest, pinned here: WSL's Python and Windows Python both have to arrive at it
    assert hashlib.sha256(TW.zip_bytes(FIXED_SOURCE)).hexdigest() == FIXED_DIGEST
    assert TW.zip_bytes(FIXED_SOURCE + b"\n") != TW.zip_bytes(FIXED_SOURCE)
    assert b"\r" not in source
    with pytest.raises(TW.TwinError) as e:
        TW.zip_bytes(source.replace(b"\n", b"\r\n"))
    assert e.value.name == "source-has-a-carriage-return"


def test_the_zip_has_one_entry_with_a_fixed_time_and_mode_and_its_name_is_the_handlers_module() -> None:
    source = SOURCE.read_bytes()
    data = TW.zip_bytes(source)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info, = z.infolist()
        assert z.testzip() is None and z.read(info) == source and z.comment == b""
    module, function = TW.HANDLER.split(".")
    assert info.filename == module + ".py" == TW.ZIP_ENTRY and info.date_time == (1980, 1, 1, 0, 0, 0)
    assert info.compress_type == zipfile.ZIP_STORED and info.create_system == 3 and info.external_attr == 0o100644 << 16
    assert info.extra == b"" and info.comment == b"" and info.file_size == info.compress_size == len(source)
    assert len(data) == 30 + len(info.filename) + len(source) + 46 + len(info.filename) + 22     # the three records, and nothing else
    # the runtime finds the handler the function is created with; with another entry's name it would be created and fail at
    # its first invoke
    mod, handler = STUB.load_function(data, TW.HANDLER)
    assert callable(handler) and handler.__name__ == function and mod.ENV == B.ENV
    with pytest.raises(STUB.FunctionFailed):
        STUB.load_function(TW.zip_bytes(source, "another.py"), TW.HANDLER)
    with pytest.raises(STUB.FunctionFailed):
        STUB.load_function(TW.zip_bytes(FIXED_SOURCE.replace(b"handler", b"another")), TW.HANDLER)
    assert base64.b64decode(TW.code_sha256(hashlib.sha256(data).hexdigest())) == hashlib.sha256(data).digest()


def test_the_leak_scan_finds_nothing_in_the_zip_or_in_the_source(tmp_path: Path) -> None:
    source = SOURCE.read_bytes()
    data = TW.zip_bytes(source)
    (tmp_path / "zip").mkdir()
    (tmp_path / "zip" / "breaker.zip.txt").write_bytes(data)                    # stored, not compressed: the scanner reads the source in it
    (tmp_path / "zip" / "breaker.py").write_bytes(source)
    assert LS.scan(str(tmp_path / "zip"), []) == []
    assert LS.findings(source.decode("utf-8"), False, []) == [] and source in data
    # the scan is not blind to such a file: one identifier in the source and both are findings
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "breaker.zip.txt").write_bytes(TW.zip_bytes(source + b"# " + arn(CERT_1).encode() + b"\n"))
    assert {label for _rel, label, _tok in LS.scan(str(tmp_path / "bad"), [])} >= {"arn", "certificate id"}
