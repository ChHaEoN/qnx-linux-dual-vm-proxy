"""breaker.py -- the twin's breaker: the function an alarm invokes to cut the twin's traffic (SDV Phase 4 WP7).
Owner decision S10: it disables, deactivates and detaches, and it NEVER RESTORES. No call
that enables a rule, attaches a policy or activates a certificate exists in this file. Its role allows no enabling and no
attaching; it must hold iot:UpdateCertificate to deactivate, which IAM cannot narrow to INACTIVE, so that the function never
activates is held by this code (the one literal INACTIVE) and by a test. The role is
sdv/cloud/templates/breaker-role-policy.json. Restoring is the owner's, by hand (sdv/cloud/README.md).

WHAT IT IS
  One file: the standard library, and the runtime's own boto3, imported in one place (_clients) so that the module
  loads where no SDK is installed. python3.12 on arm64, 128 MB, 30 s (design values; the driver's create call holds
  them). handler(event, context) makes the two clients and hands them to run(event, env, iot, iot_data): the event,
  the environment and the clients are arguments, which is how the tests give the function theirs. The zip is this
  one file under the name the handler `breaker.handler` asks for; sdv/cloud/twinctl.py builds it.

  What it acts on comes from four environment variables, set when the function is created, and from nowhere else:
    TWIN_CERTIFICATE_ARNS   the twin's certificates, as ARNs, comma-separated; the id each call needs is taken from
                            the ARN's end
    TWIN_CLIENT_IDS         the MQTT client ids whose connections are deleted, comma-separated (the thing's name)
    TWIN_RULE               the topic rule
    TWIN_POLICY             the device policy. No chosen name stands in this file: IAM scopes the detach to the
                            certificate, never to the policy, so THIS CODE selects the policy, by this name alone.

THE EVENT RULES (one table; tests/test_sdv_breaker.py tests every row)
     the event                                                               what invoked it   what is done
  1  exactly {"manual": "trip"}                                              manual            the trip
  2  exactly {"manual": "status"}                                            manual            the read-backs only
  3  an alarm's own invoke: alarmData.state.value is ALARM                   alarm             the trip
  4  the same shape, with OK or INSUFFICIENT_DATA                            alarm             nothing: no call
  5  through a topic: Records[].Sns.Message, each a JSON text with a
     NewStateValue, and one of them says ALARM                               sns               the trip
  6  the same shape, every message with OK or INSUFFICIENT_DATA              sns               nothing: no call
  7  anything else: no object; `manual` with another value or another key
     beside it; both shapes at once; a state that is none of the three
     words; no record, or a record or a message that cannot be read; an
     event the rules themselves stop on                                      unparsed          the trip
  IT FAILS CLOSED (the event parse rule): a trip is reversible and a missed trip is not, so only a cleanly parsed OK or
  INSUFFICIENT_DATA does nothing. So decide() never raises: an error of the rules' own, whatever it is, is an event
  that cannot be parsed (a message nested deeper than the interpreter's JSON reader goes ends in RecursionError, which
  is no ValueError; let out, it ended the function before its first call). It acts on every certificate it is given
  whatever the alarm's name is: no metric says which thing leaked.
  BOTH SHAPES ARE WRITTEN FROM THE DOCUMENTATION; each fixture is not a captured event (tests/fixtures/breaker-event-*.json
  are examples written by hand). Row 3 is the path the twin has: each breaker alarm invokes the function itself.
  Rows 5 and 6 are kept as the plan has them, but as built nothing leads from the notice topic to the function: its
  one subscription is the owner's e-mail, and the function's resource policy names the alarms only.

THE STEPS of a trip, in this order
  1  DisableTopicRule                                  the paid path stops
  2  UpdateCertificate to INACTIVE, each certificate   no new connection
  3  DeleteConnection, each client id                  the connection that stands is closed; after 2, so that the
                                                       client cannot come back
  4  DetachPolicy, the one policy, each certificate    the slowest cut, kept as depth
  5  the read-backs: DescribeCertificate for each certificate, ListTargetsForPolicy on the one policy, GetTopicRule
  6  one log record of the end state
  EVERY STEP IS ATTEMPTED WHATEVER HAPPENED TO THE OTHERS, and the function raises at the end if anything failed.
  A missing environment value stops no step whose own inputs are there (raising before the first call would fail
  open): with no rule's name the certificates are still deactivated, with no usable certificate the rule is still
  disabled and the connections deleted. An entry of TWIN_CERTIFICATE_ARNS that is no certificate's ARN is a failure
  and is never guessed at. A not-found answer of DeleteConnection is "no client connected" and no failure: an alarm
  fires minutes after the device was last connected, so that is the normal case. DeleteConnection missing from the
  runtime's SDK is "unavailable" and no failure either: steps 2 and 4 are what keep the client out.

THE VERDICT: THE READ-BACKS GIVE IT, NOT A CALL'S ERROR CODE
  What each call answers when its work is already done (a rule already disabled, a certificate already INACTIVE,
  a policy already detached) is not known, and a second delivery of the same alarm is normal. So:
    - a cut step counts as done when its read-back shows the cut, also when its write was ANSWERED with an error by
      the service: the record then says `answered:<the code>`, which is how the first dry trip shows what each API
      says of work already done;
    - a write that was refused as NOT AUTHORISED (HTTP 401 or 403, or a code that says so), or that got no answer
      of the service at all, is a failure whatever the read-back shows: a function that may not write is no
      breaker, and it must not pass on a twin that only happens to be cut already (the dry-trip contract);
    - a cut whose read-back does not show it is a failure although every call was accepted, and so is a read-back
      that could not be made: the record says `not-read`, never a state nobody read;
    - DeleteConnection has no read-back: any answer but success and not-found is a failure.
  The status (row 2) makes no write and judges no cut: it raises only when a read-back could not be made or the
  environment is not usable as it stands (a value missing, an entry that is no certificate's ARN, a list longer than
  the time is counted for).

THE TIME IT HAS (design values, counted here; nothing was measured)
  botocore's defaults would let one silent endpoint take the whole 30 s before a later step is attempted. Each
  client is made with connect_timeout 1 s, read_timeout 1 s and ONE attempt. THAT BOUNDS NO CALL BY ITSELF. The
  connect time-out is per ADDRESS: the SDK's HTTP layer (urllib3, as read in the dev venv's pin) tries every address
  the endpoint's name resolves to in turn, each with the whole second, so an endpoint that drops every packet costs
  one call N s of connecting when its name resolves to N addresses. And the read time-out is per read of the
  socket, not per reply.
  THE COUNT IS MADE FOR ONE ADDRESS PER NAME (ADDRESSES = 1) and a reply that comes in one read: a call then ends
  within 2 s. A trip over C certificates and K client ids makes 3C + K + 3 calls. Counted for C = 2 and K = 2 at
  most: 11 calls, 22 s, which leaves 8 s of the 30 for the cold start and the log record. For the twin as decided
  (one of each) it is 7 calls, 14 s. A longer list is still acted on, writes first, and is a failure.
  WHAT IS NOT HELD. With N addresses behind a name a call may wait N s to connect and 1 s to read, and the same
  count is (3C + K + 3) * (N + 1) s and the reserve: over the 30 s from N = 2 on for the largest set, from N = 3 on
  for the twin as decided. There the runtime ends the function at its 30 s: the steps it had not begun are NOT
  attempted, no log record of the end state is written, and the signs that are left are the function's Errors
  metric (a time-out counts in it, from memory; with the notice topic its alarm notifies the owner) and the
  runtime's own line in the log. No write could have landed on an endpoint that answers on no address either. How
  many addresses the two endpoints' names resolve to inside the runtime is not established: A3 row 13's notes
  record what they resolve to, and for the count to hold for more than one the function's time-out is raised with
  ADDRESSES (here, and in the driver's create call and its read-back; a test holds the inequality).
  Retries are not the SDK's: a failed trip raises, the asynchronous invoke of an alarm is retried by the service
  (twice by default, from memory), and a second run is harmless.
  Not bounded by this either: the name lookup, and the processor time of a cold start at 128 MB.

WHAT IT RETURNS, RAISES AND LOGS
  The RETURNED record and every RAISED message hold states and counts, never a value of the environment, of the
  event or of the request: the driver keeps the payload in its state directory, `trip --capture` copies it, and an
  error's message comes back in the payload too. Fields: v, mode (trip | status | none), invoked_by, alarm_state,
  boto3 (the runtime's version), has_delete_connection, rule {write, state}, certificates [{write, state, detach,
  policy}], connections [{write}], counts {certificates, client_ids, unusable_certificates, calls, failures}, cut
  (what the three read-backs show, and only that), failures.
  The LOG record, one JSON line on standard output, stays inside the account and names what was acted on: the
  request's id, what invoked the function (and the alarm's name as the event gives it), the rule, the policy, the
  certificates, the client ids, every call with the service's own error code and HTTP status, and the record.

NO SEAM. Nothing an event or an environment variable holds changes what the function acts on, where its calls go,
or whether it acts, beyond the table and the four variables above: no dry-run switch, no endpoint, no override. The
clients are told to ignore an endpoint the environment configures. The tests pass their fake clients as Python
arguments, and a stand-in for the runtime replaces _clients, which no event and no variable reaches.

Does not demonstrate: IAM's evaluation of the role; that an alarm reaches the function; the event's real shape;
what each API answers when the work is already done; what a live connection does when its policy goes; the
runtime's own boto3 (its version, whether it knows DeleteConnection and the client option used here: A3 row 13's
status invoke is the first to say); any timing. A3 rows 13, 17a and 17b are the first contact.
Not established either: whether ListTargetsForPolicy still lists a certificate for a while after an accepted
DetachPolicy. The detach is judged by that listing at once, so if the listing lags, a first trip raises "the policy
is still attached" although the cut is under way. Row 17a's first dry trip is where that shows: read its record for
it, and decide the verdict on the detach then (the write's own answer, or a later read inside the counted time).
Nor how many addresses the control plane's and the data plane's endpoint names resolve to inside the runtime, on
which the counted time rests (THE TIME IT HAS): row 13's notes record what they resolve to.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

ENV = ("TWIN_CERTIFICATE_ARNS", "TWIN_CLIENT_IDS", "TWIN_RULE", "TWIN_POLICY")
FUNCTION_TIMEOUT_S = 30                         # the driver's create call: --timeout
CONNECT_TIMEOUT_S = 1
READ_TIMEOUT_S = 1
ATTEMPTS = 1                                    # no retry inside the SDK: the time is counted on it
ADDRESSES = 1                                   # per endpoint name: the connect time-out is spent once per address it resolves to
RESERVE_S = 8                                   # the cold start and the log record
MAX_CERTIFICATES = 2                            # (3 * 2 + 2 + 3) calls * (1 + 1) s + 8 s = 30 s
MAX_CLIENT_IDS = 2
PAGE = 250                                      # the policy's targets in one page; a listing that goes on is no read

STATES = ("ALARM", "OK", "INSUFFICIENT_DATA")
_CERTIFICATE = re.compile(r"arn:[a-z-]+:iot:[a-z0-9-]+:[0-9]+:cert/([0-9a-f]{64})")
_DENIED = re.compile(r"AccessDenied|Unauthori[sz]ed|Forbidden|NotAuthori[sz]ed", re.I)
_CODE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")
_WORD = re.compile(r"[A-Z][A-Z_]{0,31}")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,39}")

Sent = Tuple[str, str, bool, Any]               # (how it ended, the word for the record, whether it was "not found", the reply)


class BreakerError(Exception):
    """The function did not complete. Its text holds states and counts, never a value of the environment."""


# --------------------------------------------------------------------------------------------------- the event rules

def _name(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None


def _message(record: Any) -> Optional[Tuple[Optional[str], str]]:
    """One record of a topic's delivery: (the alarm's name, its state), or None when it cannot be read."""
    sns = record.get("Sns") if isinstance(record, dict) else None
    text = sns.get("Message") if isinstance(sns, dict) else None
    if not isinstance(text, str):
        return None
    try:
        message = json.loads(text)
    except (ValueError, RecursionError):                             # no JSON; or JSON nested deeper than the reader goes
        return None
    if not isinstance(message, dict) or not isinstance(message.get("NewStateValue"), str) or message["NewStateValue"] not in STATES:
        return None
    return _name(message.get("AlarmName")), message["NewStateValue"]


def decide(event: Any) -> Tuple[str, str, Optional[str], Optional[str]]:
    """THE EVENT RULES: (what is done: trip | status | none, what invoked the function, the alarm's name as the event
    gives it, the alarm's state). Whatever is not one of the table's first six rows is the seventh: the trip. IT NEVER
    RAISES: whatever the rules cannot do with an event is an event that cannot be parsed, and nothing has been called
    yet when they are read, so an error let out here would be a trip that was missed."""
    try:
        return _rows(event)
    except Exception:                                                # noqa: BLE001 - it fails closed
        return ("trip", "unparsed", None, None)


def _rows(event: Any) -> Tuple[str, str, Optional[str], Optional[str]]:
    """The table, row by row. Only decide() calls it."""
    unparsed = ("trip", "unparsed", None, None)
    if not isinstance(event, dict):
        return unparsed
    if "manual" in event:
        if event == {"manual": "trip"}:
            return ("trip", "manual", None, None)
        if event == {"manual": "status"}:
            return ("status", "manual", None, None)
        return unparsed
    if ("alarmData" in event) is ("Records" in event):               # neither shape, or both at once
        return unparsed
    if "alarmData" in event:
        alarm = event["alarmData"]
        state = alarm.get("state") if isinstance(alarm, dict) else None
        value = state.get("value") if isinstance(state, dict) else None
        if not isinstance(value, str) or value not in STATES:
            return unparsed
        return ("trip" if value == "ALARM" else "none", "alarm", _name(alarm.get("alarmName")), value)
    records = event["Records"]
    if not isinstance(records, list) or not records:
        return unparsed
    read = [_message(record) for record in records]
    for message in read:
        if message is not None and message[1] == "ALARM":
            return ("trip", "sns", message[0], "ALARM")
    if read[0] is None or None in read:
        return unparsed
    return ("none", "sns", read[0][0], read[0][1])


# --------------------------------------------------------------------------------------------------- one call

def _send(journal: List[Dict[str, Any]], plane: str, client: Any, op: str, **kwargs: Any) -> Sent:
    """ONE CALL of a client, and the one place a client is used. How it ended:
      ok        the service accepted it; the reply is the fourth item
      answered  the service answered with an error that is no refusal for want of authorisation
      refused   HTTP 401 or 403, or an error code that says so
      failed    no answer of the service at all: a time-out, a connection, an argument the SDK refused; or no client
      missing   the client has no such call (the runtime's SDK is older than it): nothing was sent
    The journal entry, for the log record, keeps the service's own code and status. The word for the returned record
    holds a code only in the form an error code has."""
    entry: Dict[str, Any] = {"client": plane, "op": op}
    journal.append(entry)
    if client is None:
        entry["answer"] = "no-client"
        return ("failed", "failed", False, None)
    call = getattr(client, op, None)
    if not callable(call):
        entry["answer"] = "unavailable"
        return ("missing", "unavailable", False, None)
    try:
        reply = call(**kwargs)
    except Exception as error:                                       # noqa: BLE001 - every step is attempted whatever happened to the others
        response = getattr(error, "response", None)
        said = response.get("Error") if isinstance(response, dict) else None
        meta = response.get("ResponseMetadata") if isinstance(response, dict) else None
        code = said.get("Code") if isinstance(said, dict) else None
        http = meta.get("HTTPStatusCode") if isinstance(meta, dict) else None
        code = code if isinstance(code, str) and code else None
        http = http if isinstance(http, int) and not isinstance(http, bool) else None
        entry["type"] = type(error).__name__
        if code is None and http is None:
            entry["answer"] = "no-answer"
            return ("failed", "failed", False, None)
        entry.update(answer="error", code=(code or "")[:128], http=http)
        if http in (401, 403) or (code is not None and _DENIED.search(code)):
            return ("refused", "refused", False, None)
        word = "answered:" + code if code is not None and _CODE.fullmatch(code) else "answered"
        return ("answered", word, http == 404 or code == "ResourceNotFoundException", None)
    entry["answer"] = "ok"
    return ("ok", "ok", False, reply)


def _made(journal: List[Dict[str, Any]]) -> int:
    return sum(1 for entry in journal if entry.get("answer") not in ("no-client", "unavailable"))


# --------------------------------------------------------------------------------------------------- what it acts on

class _Inputs:
    """The four environment values, read once. A value that is unset, empty or blank is missing."""

    def __init__(self, env: Mapping[str, str]) -> None:
        def value(key: str) -> Optional[str]:
            got = env.get(key)
            return got.strip() if isinstance(got, str) and got.strip() else None

        self.rule = value("TWIN_RULE")
        self.policy = value("TWIN_POLICY")
        self.clients: List[str] = []
        for entry in (value("TWIN_CLIENT_IDS") or "").split(","):
            if entry.strip() and entry.strip() not in self.clients:
                self.clients.append(entry.strip())
        self.certificates: List[Tuple[str, str]] = []                # (the ARN as given, the id its end holds)
        self.unusable = 0
        for entry in (value("TWIN_CERTIFICATE_ARNS") or "").split(","):
            entry = entry.strip()
            match = _CERTIFICATE.fullmatch(entry)
            if not entry:
                continue
            if match is None:
                self.unusable += 1                                   # never guessed at, never passed to a call
            elif (entry, match.group(1)) not in self.certificates:
                self.certificates.append((entry, match.group(1)))

    def failures(self) -> List[str]:
        out = []
        if self.rule is None:
            out.append("TWIN_RULE is not set")
        if self.policy is None:
            out.append("TWIN_POLICY is not set")
        if not self.clients:
            out.append("TWIN_CLIENT_IDS is not set")
        elif len(self.clients) > MAX_CLIENT_IDS:
            out.append("TWIN_CLIENT_IDS names %d client ids, more than the %d the function's time is counted for"
                       % (len(self.clients), MAX_CLIENT_IDS))
        if not self.certificates:
            out.append("TWIN_CERTIFICATE_ARNS names no certificate (%d of its entries are no certificate's ARN)" % self.unusable)
        elif self.unusable:
            out.append("%d of the entries of TWIN_CERTIFICATE_ARNS are no certificate's ARN" % self.unusable)
        elif len(self.certificates) > MAX_CERTIFICATES:
            out.append("TWIN_CERTIFICATE_ARNS names %d certificates, more than the %d the function's time is counted for"
                       % (len(self.certificates), MAX_CERTIFICATES))
        return out


# --------------------------------------------------------------------------------------------------- the steps

def _cut(journal: List[Dict[str, Any]], inputs: _Inputs, iot: Any, iot_data: Any) -> Dict[str, Any]:
    """Steps 1 to 4, each attempted whatever happened to the others. A step whose own input is missing is not attempted."""
    out: Dict[str, Any] = {"rule": None, "certificates": [], "connections": [], "detach": []}
    if inputs.rule is not None:
        out["rule"] = _send(journal, "iot", iot, "disable_topic_rule", ruleName=inputs.rule)
    for _arn, certificate in inputs.certificates:
        out["certificates"].append(_send(journal, "iot", iot, "update_certificate", certificateId=certificate, newStatus="INACTIVE"))
    for client_id in inputs.clients:
        out["connections"].append(_send(journal, "iot-data", iot_data, "delete_connection", clientId=client_id))
    for arn, _certificate in inputs.certificates:
        out["detach"].append(_send(journal, "iot", iot, "detach_policy", policyName=inputs.policy, target=arn) if inputs.policy is not None else None)
    return out


def _read_back(journal: List[Dict[str, Any]], inputs: _Inputs, iot: Any) -> Dict[str, Any]:
    """Step 5. What could not be read is None, and stays so: nothing here is taken from a call that did not answer."""
    out: Dict[str, Any] = {"certificates": [], "targets": None, "disabled": None}
    for _arn, certificate in inputs.certificates:
        how, _word, _gone, reply = _send(journal, "iot", iot, "describe_certificate", certificateId=certificate)
        described = reply.get("certificateDescription") if how == "ok" and isinstance(reply, dict) else None
        status = described.get("status") if isinstance(described, dict) else None
        out["certificates"].append(status if isinstance(status, str) and status else None)
    if inputs.policy is not None and inputs.certificates:
        how, _word, _gone, reply = _send(journal, "iot", iot, "list_targets_for_policy", policyName=inputs.policy, pageSize=PAGE)
        targets = reply.get("targets") if how == "ok" and isinstance(reply, dict) else None
        whole = isinstance(reply, dict) and not reply.get("nextMarker")          # a listing that goes on is not judged
        if whole and isinstance(targets, list) and all(isinstance(target, str) for target in targets):
            out["targets"] = list(targets)
    if inputs.rule is not None:
        how, _word, _gone, reply = _send(journal, "iot", iot, "get_topic_rule", ruleName=inputs.rule)
        rule = reply.get("rule") if how == "ok" and isinstance(reply, dict) else None
        disabled = rule.get("ruleDisabled") if isinstance(rule, dict) else None
        out["disabled"] = disabled if isinstance(disabled, bool) else None
    return out


def _judge(sent: Optional[Sent], read: bool, shown: bool) -> Optional[str]:
    """THE VERDICT on one cut step: why it is a failure, or None. A write that was refused, or that got no answer, is
    a failure whatever was read back; what was not read is no cut; and what is read back and is not the cut is none."""
    if sent is not None and sent[0] == "refused":
        return "refused"
    if sent is not None and sent[0] in ("failed", "missing"):
        return "failed"
    if not read:
        return "unread"
    return None if shown else "uncut"


_WHY = {"refused": "was refused as not authorised", "failed": "got no answer"}


def _attached(targets: Optional[List[str]], certificate: str) -> Optional[bool]:
    """Whether the policy's targets hold this certificate: by its id, wherever it stands in a target's text, so that
    another spelling of the same ARN is not read as "detached"."""
    return None if targets is None else any(certificate in target for target in targets)


def _state_word(status: Optional[str]) -> str:
    if status is None:
        return "not-read"
    return status if _WORD.fullmatch(status) else "other"


def _assemble(mode: str, inputs: _Inputs, sent: Optional[Dict[str, Any]], back: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """The record's three parts and the failures, as sentences of states and counts."""
    trip = sent is not None
    failures = inputs.failures()
    n = len(inputs.certificates)
    disabled = back["disabled"]
    rule: Dict[str, Any] = {"state": "not-read" if disabled is None else ("disabled" if disabled else "enabled")}
    if trip and sent is not None:
        rule = dict(write=sent["rule"][1] if sent["rule"] is not None else "not-attempted", **rule)
    if inputs.rule is not None:
        why = _judge(sent["rule"] if sent is not None else None, disabled is not None, disabled is True or not trip)
        if why in _WHY:
            failures.append("the rule: its disable call %s" % _WHY[why])
        elif why == "unread":
            failures.append("the rule's state could not be read")
        elif why == "uncut":
            failures.append("the rule is not disabled")
    certificates = []
    unread_targets = False
    for i, (_arn, certificate) in enumerate(inputs.certificates):
        status = back["certificates"][i]
        attached = _attached(back["targets"], certificate)
        entry: Dict[str, Any] = {"state": _state_word(status), "policy": "not-read" if attached is None else ("attached" if attached else "detached")}
        write = sent["certificates"][i] if sent is not None else None
        detach = sent["detach"][i] if sent is not None else None
        if trip:
            entry = {"write": write[1] if write is not None else "not-attempted", "state": entry["state"],
                     "detach": detach[1] if detach is not None else "not-attempted", "policy": entry["policy"]}
        certificates.append(entry)
        why = _judge(write, status is not None, status == "INACTIVE" or not trip)
        if why in _WHY:
            failures.append("certificate %d of %d: the call that deactivates it %s" % (i + 1, n, _WHY[why]))
        elif why == "unread":
            failures.append("certificate %d of %d: its state could not be read" % (i + 1, n))
        elif why == "uncut":
            failures.append("certificate %d of %d is not INACTIVE" % (i + 1, n))
        if inputs.policy is None:
            continue                                                 # said once, as the missing value
        why = _judge(detach, attached is not None, attached is False or not trip)
        if why in _WHY:
            failures.append("certificate %d of %d: the call that detaches the policy %s" % (i + 1, n, _WHY[why]))
        elif why == "unread":
            unread_targets = True
        elif why == "uncut":
            failures.append("certificate %d of %d: the policy is still attached" % (i + 1, n))
    if unread_targets:
        failures.append("the policy's targets could not be read")
    connections = []
    for i, done in enumerate(sent["connections"] if sent is not None else []):
        how, _word, gone, _reply = done
        if how == "ok":
            connections.append({"write": "ok"})
        elif how == "answered" and gone:
            connections.append({"write": "no-client-connected"})
        elif how == "missing":
            connections.append({"write": "unavailable"})            # the other steps are what keep the client out
        else:
            connections.append({"write": done[1]})
            failures.append("client %d of %d: the call that deletes its connection %s"
                            % (i + 1, len(inputs.clients), _WHY.get(how, "was answered with an error")))
    cut = bool(inputs.certificates) and disabled is True and back["targets"] is not None and all(
        back["certificates"][i] == "INACTIVE" and _attached(back["targets"], c) is False for i, (_a, c) in enumerate(inputs.certificates))
    return {"rule": rule, "certificates": certificates, "connections": connections, "cut": cut}, failures


def _work(event: Any, env: Mapping[str, str], iot: Any, iot_data: Any, sdk: str, request_id: str) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    mode, invoked_by, alarm, alarm_state = decide(event)
    inputs = _Inputs(env)
    journal: List[Dict[str, Any]] = []
    # a version that is no text is "unknown" like one that is not in a version's form: the cut does not wait on bookkeeping
    record: Dict[str, Any] = {
        "v": 1, "mode": mode, "invoked_by": invoked_by, "alarm_state": alarm_state,
        "boto3": sdk if isinstance(sdk, str) and _VERSION.fullmatch(sdk) else "unknown",
        "has_delete_connection": callable(getattr(iot_data, "delete_connection", None)), "rule": None, "certificates": [], "connections": [],
        "cut": None}
    failures: List[str] = []
    if mode != "none":
        sent = _cut(journal, inputs, iot, iot_data) if mode == "trip" else None
        parts, failures = _assemble(mode, inputs, sent, _read_back(journal, inputs, iot))
        record.update(parts)
    record["counts"] = {"certificates": len(inputs.certificates), "client_ids": len(inputs.clients), "unusable_certificates": inputs.unusable,
                        "calls": _made(journal), "failures": len(failures)}
    record["failures"] = list(failures)
    entry = {"breaker": 1, "request_id": request_id, "invoked_by": invoked_by, "alarm": alarm, "alarm_state": alarm_state, "mode": mode,
             "acts_on": {"rule": inputs.rule, "policy": inputs.policy, "certificates": [arn for arn, _c in inputs.certificates],
                         "client_ids": list(inputs.clients)},
             "calls": journal, "record": record}
    return record, entry, failures


def _emit(log: Optional[Callable[[Dict[str, Any]], None]], entry: Dict[str, Any]) -> None:
    """The one log record. A log that cannot be written stops nothing: the cut and the raise matter more."""
    try:
        (log or _print)(entry)
    except Exception:                                                # noqa: BLE001
        pass


def _print(entry: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
    sys.stdout.flush()


def run(event: Any, env: Mapping[str, str], iot: Any, iot_data: Any, sdk: str = "unknown", request_id: str = "",
        log: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """The function, with everything it uses as an argument. Returns the record; raises BreakerError, after the log
    record was written, when anything failed. No other error leaves it: one no step names is raised by its kind
    alone, since its text could hold a value of the environment."""
    try:
        record, entry, failures = _work(event, env, iot, iot_data, sdk, request_id)
    except Exception as error:                                       # noqa: BLE001
        _emit(log, {"breaker": 1, "request_id": request_id, "error": type(error).__name__})
        raise BreakerError("the breaker stopped on an error no step names (%s): look at the state by hand" % type(error).__name__) from None
    _emit(log, entry)
    if failures:
        raise BreakerError("the %s did not complete: %d failure(s): %s" % ("status" if record["mode"] == "status" else "trip", len(failures),
                                                                           "; ".join(failures)))
    return record


# --------------------------------------------------------------------------------------------------- the runtime's side

def _clients() -> Tuple[Any, Any, str]:
    """THE ONE PLACE the real clients are made, and the one place the SDK is imported: (the control plane's client,
    the data plane's, the SDK's version). Short time-outs and one attempt (THE TIME IT HAS); no endpoint, no region
    and no credential of this file's: the runtime's own, with an endpoint the environment configures ignored. A
    client that cannot be made is None: its steps fail, and the other client's are attempted all the same."""
    try:
        import boto3
        from botocore.config import Config
        version = str(boto3.__version__)
    except Exception:                                                # noqa: BLE001
        return None, None, "unknown"
    made: List[Any] = []
    for service in ("iot", "iot-data"):
        try:
            config = Config(connect_timeout=CONNECT_TIMEOUT_S, read_timeout=READ_TIMEOUT_S,
                            retries={"total_max_attempts": ATTEMPTS, "mode": "standard"}, ignore_configured_endpoint_urls=True)
            made.append(boto3.client(service, config=config))
        except Exception:                                            # noqa: BLE001
            made.append(None)
    return made[0], made[1], version


def handler(event: Any, context: Any) -> Dict[str, Any]:
    iot, iot_data, sdk = _clients()
    return run(event, os.environ, iot, iot_data, sdk=sdk, request_id=str(getattr(context, "aws_request_id", "")))
