"""The breaker's calls against the SDK's own service model (sdv/cloud/breaker/breaker.py): SDV Phase 4 WP7's second
tier.

OPT-IN, OFF BY DEFAULT, AND NO PART OF THE CI RECIPE. It needs boto3, which CI's venv does not have and never gets.
SDV_BREAKER_MODEL names the one dev venv (in WSL, outside every work tree) that was installed from
sdv/cloud/breaker/requirements-dev.lock; this file puts that venv's packages on the path for its own tests, holds
them to the lock's pins, and takes them off again. It lives in a file of its own because a test that is passed over
by default must not sit in a file the recipe's gate reads (tests/twin_gate.py).

WHY. tests/test_sdv_breaker.py gives the function hand-written clients. Those hold the argument names by their own
signatures, which are one author's reading. Here botocore's own clients stand in, each with a Stubber in front:
every call the function makes is validated against the pinned service model (the operation exists, the argument
names and types are the model's, a number is in its range), every stubbed reply is validated against the model's
output shape, and an error is botocore's own ClientError, so the function reads the real exception's shape.

NO AWS CALL, NO CREDENTIAL, NO SOCKET. Every client is made with a region and made-up keys as explicit arguments;
the two files AWS_CONFIG_FILE and AWS_SHARED_CREDENTIALS_FILE name are empty; instance metadata is off; no AWS_
variable of the caller is left; a Stubber is activated before the first call; and connecting a socket or looking a
name up is replaced by a function that records the attempt and raises, with the record checked after every test.

Does not demonstrate: anything about the account or the service. The Stubber does not check a value against an
enumeration (the model's own list is read here instead), does not know IAM, the endpoint, a throttle or a time-out,
and its error codes are the ones this file gives it. The pinned SDK is not the runtime's: which boto3 the function
finds in the account, and whether that one knows DeleteConnection, is first said by the status invoke (the function
status check).
"""
import importlib
import importlib.util
import json
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SOURCE = REPO / "sdv" / "cloud" / "breaker" / "breaker.py"
LOCK = REPO / "sdv" / "cloud" / "breaker" / "requirements-dev.lock"
OPT_IN = "SDV_BREAKER_MODEL"

pytestmark = pytest.mark.skipif(not os.environ.get(OPT_IN), reason="opt-in: %s=<the dev venv made from sdv/cloud/breaker/requirements-dev.lock>; "
                                                                   "offline, no AWS call, no credential" % OPT_IN)

REGION = "us-east-1"
ACCOUNT = "123456789012"
RULE = "example_rule"
POLICY = "example-device-policy"
CLIENT = "example-thing"
CERT_1 = "0123456789abcdef" * 4
CERT_2 = "fedcba9876543210" * 4
PACKAGES = ("boto3", "botocore", "s3transfer", "jmespath", "dateutil", "six", "urllib3")
KEYS = {"aws_access_key_id": "made-up-not-a-key", "aws_secret_access_key": "made-up-not-a-secret"}


def arn(cert: str) -> str:
    return "arn:aws:iot:%s:%s:cert/%s" % (REGION, ACCOUNT, cert)


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


def pins() -> Dict[str, str]:
    return dict(re.findall(r"^([a-z0-9-]+)==(\S+) \\$", LOCK.read_text(encoding="ascii"), re.M))


class Sdk:
    def __init__(self, site: Path) -> None:
        self.site = site
        self.boto3 = importlib.import_module("boto3")
        self.botocore = importlib.import_module("botocore")
        self.Config = importlib.import_module("botocore.config").Config
        self.Stubber = importlib.import_module("botocore.stub").Stubber
        self.exceptions = importlib.import_module("botocore.exceptions")


@pytest.fixture(scope="module")
def sdk() -> Iterator[Sdk]:
    """The dev venv's packages, on the path for this module's tests only."""
    venv = Path(os.environ[OPT_IN]).expanduser().resolve()
    assert REPO not in venv.parents and venv != REPO and not [p for p in [venv] + list(venv.parents) if (p / ".git").exists()], \
        "the dev venv lies inside a work tree"
    site, = sorted(venv.glob("lib/python*/site-packages"))
    assert not [m for m in PACKAGES if m in sys.modules], "an SDK module was imported before this file put the dev venv on the path"
    sys.path.insert(0, str(site))
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield Sdk(site)
    finally:
        sys.dont_write_bytecode = saved
        sys.path.remove(str(site))
        for name in [m for m in sys.modules if m.split(".")[0] in PACKAGES]:
            del sys.modules[name]


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[List[str]]:
    """No credential and no network for the test that follows; a socket that connects fails it."""
    for key in [k for k in os.environ if k.upper().startswith("AWS_") or k.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")]:
        monkeypatch.delenv(key)
    for name, key in (("config", "AWS_CONFIG_FILE"), ("credentials", "AWS_SHARED_CREDENTIALS_FILE")):
        (tmp_path / name).write_bytes(b"")
        monkeypatch.setenv(key, str(tmp_path / name))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    tried: List[str] = []

    def refuse(what: str) -> Any:
        def guard(*args: Any, **kwargs: Any) -> Any:
            tried.append(what)
            raise AssertionError("a test of this file reached for the network (%s)" % what)
        return guard

    monkeypatch.setattr(socket.socket, "connect", refuse("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", refuse("connect_ex"))
    monkeypatch.setattr(socket, "create_connection", refuse("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))
    yield tried
    assert tried == [], "the network was reached for: %s" % ", ".join(tried)


@pytest.fixture(scope="module")
def breaker() -> Any:
    return _load("sdv_cloud_breaker_for_the_model", SOURCE)


def config(sdk: Sdk, breaker: Any) -> Any:
    """The configuration the function gives its clients, written out again here."""
    return sdk.Config(connect_timeout=breaker.CONNECT_TIMEOUT_S, read_timeout=breaker.READ_TIMEOUT_S,
                      retries={"total_max_attempts": breaker.ATTEMPTS, "mode": "standard"}, ignore_configured_endpoint_urls=True)


def clients(sdk: Sdk, breaker: Any) -> Tuple[Any, Any]:
    made = [sdk.boto3.client(service, region_name=REGION, config=config(sdk, breaker), **KEYS) for service in ("iot", "iot-data")]
    return made[0], made[1]


def env(certs: List[str]) -> Dict[str, str]:
    return {"TWIN_CERTIFICATE_ARNS": ",".join(arn(c) for c in certs), "TWIN_CLIENT_IDS": CLIENT, "TWIN_RULE": RULE, "TWIN_POLICY": POLICY}


def description(cert: str, status: str) -> Dict[str, Any]:
    return {"certificateDescription": {"certificateArn": arn(cert), "certificateId": cert, "status": status, "ownedBy": ACCOUNT}}


def script(stub: Any, data_stub: Any, certs: List[str], connected: bool = False) -> None:
    """A whole trip as the function makes it, each call with the arguments it has to carry and a reply of the model's shape."""
    stub.add_response("disable_topic_rule", {}, {"ruleName": RULE})
    for cert in certs:
        stub.add_response("update_certificate", {}, {"certificateId": cert, "newStatus": "INACTIVE"})
    if connected:
        data_stub.add_response("delete_connection", {}, {"clientId": CLIENT})
    else:
        data_stub.add_client_error("delete_connection", service_error_code="ResourceNotFoundException", http_status_code=404,
                                   expected_params={"clientId": CLIENT})
    for cert in certs:
        stub.add_response("detach_policy", {}, {"policyName": POLICY, "target": arn(cert)})
    for cert in certs:
        stub.add_response("describe_certificate", description(cert, "INACTIVE"), {"certificateId": cert})
    stub.add_response("list_targets_for_policy", {"targets": []}, {"policyName": POLICY, "pageSize": breaker_page()})
    stub.add_response("get_topic_rule", {"rule": {"ruleName": RULE, "ruleDisabled": True}}, {"ruleName": RULE})


def breaker_page() -> int:
    return int(_load("sdv_cloud_breaker_for_the_page", SOURCE).PAGE)


def test_the_sdk_is_the_dev_venvs_and_is_the_locks_pins(sdk: Sdk) -> None:
    locked = pins()
    assert sorted(locked) == ["boto3", "botocore", "jmespath", "python-dateutil", "s3transfer", "six", "urllib3"]
    assert sdk.boto3.__version__ == locked["boto3"] and sdk.botocore.__version__ == locked["botocore"]
    for mod in (sdk.boto3, sdk.botocore):
        assert sdk.site in Path(str(mod.__file__)).resolve().parents, mod.__name__
    text = LOCK.read_text(encoding="ascii")
    hashes = re.findall(r"^    --hash=sha256:[0-9a-f]{64}$", text, re.M)
    wheels = re.findall(r"^    # \S+-py[23](?:\.py3)?-none-any\.whl$", text, re.M)
    assert len(hashes) == len(locked) == len(wheels)
    print("the pinned SDK: boto3 %s, botocore %s, from the dev venv" % (sdk.boto3.__version__, sdk.botocore.__version__))


def test_the_model_knows_every_operation_and_argument_the_function_uses(sdk: Sdk, breaker: Any) -> None:
    iot, data = clients(sdk, breaker)
    used = {("iot", "DisableTopicRule"): {"ruleName"}, ("iot", "UpdateCertificate"): {"certificateId", "newStatus"},
            ("iot-data", "DeleteConnection"): {"clientId"}, ("iot", "DetachPolicy"): {"policyName", "target"},
            ("iot", "DescribeCertificate"): {"certificateId"}, ("iot", "ListTargetsForPolicy"): {"policyName", "pageSize"},
            ("iot", "GetTopicRule"): {"ruleName"}}
    for (plane, operation), arguments in sorted(used.items()):
        client = iot if plane == "iot" else data
        assert operation in client.meta.service_model.operation_names, operation
        shape = client.meta.service_model.operation_model(operation).input_shape
        assert arguments <= set(shape.members), (operation, sorted(shape.members))
        assert set(shape.required_members) <= arguments, (operation, shape.required_members)     # nothing the service requires is left out
        print("%s %s: arguments %s, required %s" % (plane, operation, sorted(shape.members), sorted(shape.required_members)))
    assert callable(getattr(data, "delete_connection", None))                  # the pinned SDK has the data plane's call
    update = iot.meta.service_model.operation_model("UpdateCertificate").input_shape.members["newStatus"]
    assert "INACTIVE" in update.enum                                           # an enumeration's value: the Stubber would not have said
    page = iot.meta.service_model.operation_model("ListTargetsForPolicy").input_shape.members["pageSize"]
    assert page.metadata.get("max") == breaker.PAGE, page.metadata
    listing = iot.meta.service_model.operation_model("ListTargetsForPolicy").output_shape.members
    assert {"targets", "nextMarker"} <= set(listing)
    description_ = iot.meta.service_model.operation_model("DescribeCertificate").output_shape.members["certificateDescription"].members
    assert {"status", "certificateId", "certificateArn", "certificatePem"} <= set(description_)
    assert "ruleDisabled" in iot.meta.service_model.operation_model("GetTopicRule").output_shape.members["rule"].members
    # the file's own calls, read from its source, are these seven and no other
    tree = __import__("ast").parse(SOURCE.read_text(encoding="utf-8"))
    ops = {(n.args[1].value, n.args[3].value) for n in __import__("ast").walk(tree)
           if isinstance(n, __import__("ast").Call) and getattr(n.func, "id", "") == "_send"}
    assert {(plane, "".join(w.capitalize() for w in op.split("_"))) for plane, op in ops} == set(used)


@pytest.mark.parametrize("certs,connected", [([CERT_1], False), ([CERT_1, CERT_2], False), ([CERT_1], True)],
                         ids=["one-certificate", "two-certificates", "a-client-connected"])
def test_a_whole_trip_passes_the_stubber_call_by_call(sdk: Sdk, breaker: Any, certs: List[str], connected: bool) -> None:
    iot, data = clients(sdk, breaker)
    logs: List[Dict[str, Any]] = []
    with sdk.Stubber(iot) as stub, sdk.Stubber(data) as data_stub:
        script(stub, data_stub, certs, connected)
        record = breaker.run({"manual": "trip"}, env(certs), iot, data, sdk=sdk.boto3.__version__, request_id="a-request", log=logs.append)
        stub.assert_no_pending_responses()
        data_stub.assert_no_pending_responses()
    assert record["cut"] is True and record["failures"] == [] and record["boto3"] == sdk.boto3.__version__
    assert record["has_delete_connection"] is True and record["connections"] == [{"write": "ok" if connected else "no-client-connected"}]
    assert record["counts"]["calls"] == 3 * len(certs) + 1 + 3
    assert [c["answer"] for c in logs[0]["calls"] if c["op"] != "delete_connection"] == ["ok"] * (3 * len(certs) + 3)
    if not connected:                                                          # the real exception's shape, read as the fake one's is
        call, = [c for c in logs[0]["calls"] if c["op"] == "delete_connection"]
        # botocore raises a class of the error's own name for a code the service model knows (a subclass of ClientError); the
        # function reads the response it carries, never the class
        assert (call["answer"], call["code"], call["http"]) == ("error", "ResourceNotFoundException", 404)
        assert call["type"] in ("ClientError", "ResourceNotFoundException")


def test_the_status_passes_the_stubber_and_reads_the_models_replies(sdk: Sdk, breaker: Any) -> None:
    iot, data = clients(sdk, breaker)
    with sdk.Stubber(iot) as stub, sdk.Stubber(data) as data_stub:
        stub.add_response("describe_certificate", description(CERT_1, "ACTIVE"), {"certificateId": CERT_1})
        stub.add_response("list_targets_for_policy", {"targets": [arn(CERT_1)]}, {"policyName": POLICY, "pageSize": breaker.PAGE})
        stub.add_response("get_topic_rule", {"rule": {"ruleName": RULE, "ruleDisabled": False}}, {"ruleName": RULE})
        record = breaker.run({"manual": "status"}, env([CERT_1]), iot, data, sdk=sdk.boto3.__version__, log=lambda entry: None)
        stub.assert_no_pending_responses()
        data_stub.assert_no_pending_responses()                                # nothing was asked of the data plane
    assert record["cut"] is False and record["rule"] == {"state": "enabled"} and record["certificates"] == [{"state": "ACTIVE", "policy": "attached"}]


@pytest.mark.parametrize("code,status,says", [("AccessDeniedException", 403, "not authorised"), ("UnauthorizedException", 401, "not authorised"),
                                              ("InternalFailureException", 500, "is not INACTIVE")])
def test_a_real_client_error_is_read_as_the_fake_one_is(sdk: Sdk, breaker: Any, code: str, status: int, says: str) -> None:
    iot, data = clients(sdk, breaker)
    logs: List[Dict[str, Any]] = []
    with sdk.Stubber(iot) as stub, sdk.Stubber(data) as data_stub:
        stub.add_response("disable_topic_rule", {}, {"ruleName": RULE})
        stub.add_client_error("update_certificate", service_error_code=code, http_status_code=status,
                              expected_params={"certificateId": CERT_1, "newStatus": "INACTIVE"})
        data_stub.add_client_error("delete_connection", service_error_code="ResourceNotFoundException", http_status_code=404)
        stub.add_response("detach_policy", {}, {"policyName": POLICY, "target": arn(CERT_1)})
        stub.add_response("describe_certificate", description(CERT_1, "ACTIVE"), {"certificateId": CERT_1})
        stub.add_response("list_targets_for_policy", {"targets": []}, {"policyName": POLICY, "pageSize": breaker.PAGE})
        stub.add_response("get_topic_rule", {"rule": {"ruleDisabled": True}}, {"ruleName": RULE})
        with pytest.raises(breaker.BreakerError) as e:
            breaker.run({"manual": "trip"}, env([CERT_1]), iot, data, sdk=sdk.boto3.__version__, log=logs.append)
        stub.assert_no_pending_responses()                                     # every later step was attempted all the same
    assert says in str(e.value) and "1 failure(s)" in str(e.value) and CERT_1 not in str(e.value) and RULE not in str(e.value)
    call, = [c for c in logs[0]["calls"] if c["op"] == "update_certificate"]
    assert (call["code"], call["http"]) == (code, status) and call["type"] in ("ClientError", code)


def test_the_stubber_refuses_what_a_wrong_argument_name_or_type_would_send(sdk: Sdk, breaker: Any) -> None:
    """What this tier is for: the model, not one author's fake, says what a call may carry."""
    iot, data = clients(sdk, breaker)
    with sdk.Stubber(iot) as stub, sdk.Stubber(data) as data_stub:
        stub.add_response("disable_topic_rule", {})                            # a call the model refuses does not take its reply
        for wrong in ({"rulename": RULE}, {"ruleName": 7}, {"ruleName": RULE, "force": True}, {}):
            with pytest.raises(sdk.exceptions.ParamValidationError):
                iot.disable_topic_rule(**wrong)
        iot.disable_topic_rule(ruleName=RULE)
        data_stub.add_response("delete_connection", {})
        with pytest.raises(sdk.exceptions.ParamValidationError):
            data.delete_connection(clientID=CLIENT)
        stub.add_response("list_targets_for_policy", {"targets": []})
        with pytest.raises(sdk.exceptions.ParamValidationError):
            iot.list_targets_for_policy(policyName=POLICY, pageSize=0)         # a number under the model's least
        # ... but NOT one over the model's most: botocore checks a number's lower bound only, so the page size is held to
        # the model's own figure by the test above, not by the Stubber
        iot.list_targets_for_policy(policyName=POLICY, pageSize=breaker.PAGE + 1)
        with pytest.raises(sdk.exceptions.ParamValidationError):               # and a reply that is not the model's shape is refused as well
            stub.add_response("get_topic_rule", {"rule": {"ruleDisabled": "true"}})
    # and through the function: a copy of its source with one argument's name misspelt fails that step, and says so
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count("certificateId=certificate, newStatus=") == 1
    wrong_source = HERE.parent / "sdv" / "cloud" / "breaker" / "breaker.py"
    module = type(sys)("a_breaker_with_a_misspelt_argument")
    misspelt = text.replace("certificateId=certificate, newStatus=", "certificateID=certificate, newStatus=")
    exec(compile(misspelt, str(wrong_source), "exec"), module.__dict__)
    logs: List[Dict[str, Any]] = []
    with sdk.Stubber(iot) as stub, sdk.Stubber(data) as data_stub:
        stub.add_response("disable_topic_rule", {}, {"ruleName": RULE})
        stub.add_response("update_certificate", {})
        data_stub.add_client_error("delete_connection", service_error_code="ResourceNotFoundException", http_status_code=404)
        stub.add_response("detach_policy", {}, {"policyName": POLICY, "target": arn(CERT_1)})
        stub.add_response("describe_certificate", description(CERT_1, "INACTIVE"), {"certificateId": CERT_1})
        stub.add_response("list_targets_for_policy", {"targets": []}, {"policyName": POLICY, "pageSize": breaker.PAGE})
        stub.add_response("get_topic_rule", {"rule": {"ruleDisabled": True}}, {"ruleName": RULE})
        with pytest.raises(module.BreakerError) as e:
            module.run({"manual": "trip"}, env([CERT_1]), iot, data, log=logs.append)
    call, = [c for c in logs[0]["calls"] if c["op"] == "update_certificate"]
    assert call["answer"] == "no-answer" and call["type"] == "ParamValidationError" and "got no answer" in str(e.value)


def test_the_functions_own_clients_have_its_time_outs_one_attempt_and_no_endpoint_of_the_environments(
        sdk: Sdk, breaker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    real = sdk.boto3.client
    asked: List[Tuple[str, List[str]]] = []

    def client(service: str, **kwargs: Any) -> Any:                           # what the runtime gives by itself, given here as arguments
        asked.append((service, sorted(kwargs)))
        return real(service, region_name=REGION, **dict(KEYS, **kwargs))

    monkeypatch.setattr(sdk.boto3, "client", client)
    for key in ("AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_IOT", "AWS_ENDPOINT_URL_IOT_DATA_PLANE"):
        monkeypatch.setenv(key, "https://example.invalid")
    iot, data, version = breaker._clients()
    assert asked == [("iot", ["config"]), ("iot-data", ["config"])] and version == sdk.boto3.__version__
    for made in (iot, data):
        c = made.meta.config
        assert (c.connect_timeout, c.read_timeout) == (breaker.CONNECT_TIMEOUT_S, breaker.READ_TIMEOUT_S)
        assert c.retries == {"total_max_attempts": breaker.ATTEMPTS, "mode": "standard"}
        # the client's own merged configuration does not carry the option that ignores a configured endpoint: the endpoint
        # it was made with is what shows that the option was taken
        assert "example.invalid" not in made.meta.endpoint_url and made.meta.endpoint_url.endswith(".%s.amazonaws.com" % REGION)
        print("%s: the endpoint the pinned SDK takes by itself for %s is %s" % (made.meta.service_model.service_name, REGION, made.meta.endpoint_url))
    # the seam is real, and the option is what closes it: without it the environment's endpoint is taken
    open_ = real("iot", region_name=REGION, config=sdk.Config(), **KEYS)
    assert "example.invalid" in open_.meta.endpoint_url
    # the two clients are usable as made: a whole trip passes the Stubber on them
    with sdk.Stubber(iot) as stub, sdk.Stubber(data) as data_stub:
        script(stub, data_stub, [CERT_1])
        record = breaker.run({"manual": "trip"}, env([CERT_1]), iot, data, sdk=version, log=lambda entry: None)
        stub.assert_no_pending_responses()
    assert record["cut"] is True and json.dumps(record)
