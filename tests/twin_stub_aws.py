#!/usr/bin/env python3
"""twin_stub_aws.py -- a stand-in for the AWS CLI, for tests/test_sdv_cloud.py (SDV Phase 4 WP6). Standard library
only. It is run as `python twin_stub_aws.py SERVICE OPERATION ARGS...`, which is what
sdv/cloud/twinctl.py does with an executable name that ends in .py.

ONE ACCOUNT IN ONE FILE. STUB_AWS_DIR names a directory; account.json in it is the whole account (the test writes
the first one), and three logs beside it say what arrived:
  log.jsonl       every call that came with the account's profile: its argv, whether it writes, how it ended
  skeleton.jsonl  every call that came with --generate-cli-skeleton: read, never executed, with what the environment
                  held (whether the two credential files were empty, the endpoint, the proxy, the AWS_ variables)
  refused.jsonl   every call that came without the profile: no credential, so nothing is reached (exit 253)
A call the stub does not model is an error of its own (exit 252, unknown.jsonl), so a test cannot pass on a call
nobody wrote a reply for. A listing answers whole: the stub pages nothing, and a test that wants a reply to say
"there is more" plants the marker (reply_extra in account.json). Three states the stub could not produce before are
planted the same way: `versioning` on a bucket (the get-bucket-versioning reply carries a Status), `attributes` on a thing
(describe-thing carries them) and `identity_then`, a list of identities the profile answers as from the NEXT read of the
caller on (a profile repointed between two reads of one command). A call that goes through and whose outcome the driver
cannot know is planted by the call's name: `reply_garbage` (the CLI prints what is no JSON), `reply_dies` (the CLI ends with
an error of its own) and `reply_error` (the service did the work and answers with the error code given, as a 5xx may).
`listing_lags` (by the call's name, a count; the certificates' listing alone) makes that many reads of the listing leave out
the certificate that was made last, as a listing that is behind a create would: nobody has seen whether the real one is.
A read of a certificate answers with the PEM and the ARN the stub makes for it, unless the test plants another for that id:
`pem_of` and `arn_of` (certificate id -> text), as an account holding a certificate of another make or another account's would.

A TEST FIXTURE IS CAPTURE DATA. Nothing here is a real identifier: the account, the endpoint's prefix, the
certificate ids and the canonical id are whatever the test put into account.json or are made from a counter when a
call runs, and the PEM block is put together from a sentence that says it is none.

THE FUNCTION (WP7). `lambda create-function` keeps the zip it was given (function-<name>.zip beside account.json),
and an invoke RUNS THE HANDLER OUT OF THAT ZIP: the module and the function the function's Handler names, as the
runtime finds them. The one thing replaced is the module's `_clients`, the place where the real clients are made:
it gives the handler two fake clients (FakeIot, FakeIotData) that act on this file's own account, record every call
(function-calls.jsonl) and raise the errors a test planted (function_faults in account.json), shaped as botocore's
are: response["Error"]["Code"] and the HTTP status. What the function prints is its log (function-log.jsonl). An
alarm set to ALARM invokes the function as the alarm itself would, with an event in the documented shape of an
alarm's direct invoke. A zip that does not hold the module, or a module without the handler, ends as the runtime
ends it: the invoke answers with a function error, and its payload is the error.
The fake clients are also what tests/test_sdv_breaker.py gives the function, over a small account of its own.

ECR AND THE ROLE ALIAS (Phase 6 WP4). `repositories` (by name: the tags' mutability, the encryption, a policy or none, a
lifecycle policy or none, the images), `registry_policy`, `replication_rules`, `cache_rules`, `scan_type` and
`public_repositories` (ECR Public's, answered only through us-east-1) are what the ECR calls read and write; `role_aliases`
and `credential_endpoint` the IoT credential provider's; `ecr_password` what `ecr get-login-password` prints, as text and not
JSON, as the CLI prints it. An account written before Phase 6 holds none of these keys and reads as holding nothing of them.

AND DOCKER'S (`twin_stub_aws.py --docker ARGS`), for `twinctl push`: `save` writes the blobs of an image of
`docker_images` (by its store ID: {digest: base64 of the blob}) as a tar on stdout; `image inspect` prints the image's
names (`docker_names` by store ID, a test's plant, or one local name; and the tags given since); `tag` and `rmi` keep
`docker_tags` (reference -> store ID); `--config DIR login --username AWS --password-stdin HOST` takes the password from stdin, refuses
it unless it is `ecr_password` and HOST the account's registry, and writes DIR/config.json as docker does; `--config DIR
push REF` refuses without that file's auth for REF's host, and puts the image into the repository by the digest the
registry keeps (`push_digest`, by reference, a test's plant for a registry that keeps another than the store ID). Every
argv goes to docker.jsonl; stdin never does.

WHAT IT IS NOT. Every reply shape, every error code and every refusal below is written from memory of the
service's documentation. It shows that the driver is consistent with that reading, never that the reading is
right: the first contact with the real account is an account-side rehearsal. The same holds for what each call of the
function answers when its work is already done: the fakes answer with success, which nobody has seen.
"""
import base64
import contextlib
import hashlib
import io
import json
import os
import sys
import tarfile
import types
import zipfile
from pathlib import Path

VALUELESS = {"--no-cli-pager", "--no-set-as-active", "--set-as-active", "--actions-enabled", "--no-actions-enabled", "--disable-all-logs",
             "--no-disable-all-logs", "--recursive-delete-option", "--no-recursive-delete-option"}
OUTFILE = {("lambda", "invoke"), ("iot-data", "update-thing-shadow"), ("iot-data", "delete-thing-shadow"), ("iot-data", "get-thing-shadow")}
STAMP = "2026-01-01T00:00:00+00:00"


class Err(Exception):
    def __init__(self, code, message="the stub's reading of the service"):
        super().__init__(message)
        self.code = code
        self.message = message


def parse(service, op, rest):
    """The options and their values, and the output file of the few calls that take one. In those calls every option
    takes one value, so the bare word that is left over is the file, wherever it stands."""
    rest = list(rest)
    takes_file = (service, op) in OUTFILE
    opts, out, i = {}, None, 0
    while i < len(rest):
        tok = rest[i]
        i += 1
        if not tok.startswith("--"):
            if not takes_file or out is not None:
                raise Err("ParamValidation", "an argument with no option before it")
            out = tok
            continue
        values = []
        if tok not in VALUELESS:
            while i < len(rest) and not rest[i].startswith("--") and not (takes_file and values):
                values.append(rest[i])
                i += 1
        opts[tok] = values
    if takes_file and out is None:
        raise Err("ParamValidation", "the following arguments are required: outfile")
    return opts, out


def load(value):
    """An option's value: the file's text for file://, its bytes for fileb://, else the value."""
    if value.startswith("fileb://"):
        return Path(value[len("fileb://"):]).read_bytes()
    if value.startswith("file://"):
        return Path(value[len("file://"):]).read_text(encoding="utf-8")
    return value


def one(opts, name):
    if name not in opts or len(opts[name]) != 1:
        raise Err("ParamValidation", "the following arguments are required, once: %s" % name)
    return load(opts[name][0])


def js(opts, name):
    try:
        return json.loads(one(opts, name))
    except ValueError:
        raise Err("ParamValidation", "%s is not JSON" % name) from None


def arn(a, service, resource, region=None):
    return "arn:aws:%s:%s:%s:%s" % (service, a["region"] if region is None else region, a["account"], resource)


def have(table, name, code="ResourceNotFoundException"):
    if name not in table:
        raise Err(code)
    return table[name]


def fresh(table, name, code="ResourceAlreadyExistsException"):
    if name in table:
        raise Err(code)


def tagged(opts):
    return "--tags" in opts or "--tagging" in opts


# ------------------------------------------------------------------------------------------------ s3

def s3_create_bucket(a, o, out):
    name = one(o, "--bucket")
    fresh(a["buckets"], name, "BucketAlreadyOwnedByYou")
    a["buckets"][name] = {"objects": [], "ownership": o.get("--object-ownership", ["ObjectWriter"])[0],
                          "location": js(o, "--create-bucket-configuration")}
    return {"Location": "http://%s.s3.amazonaws.com/" % name}


def bucket(a, o):
    return have(a["buckets"], one(o, "--bucket"), "NoSuchBucket")


def s3_put(field, option, parse_json=True):
    def run(a, o, out):
        b = bucket(a, o)
        b[field] = js(o, option) if parse_json else one(o, option)
        if field == "policy":
            json.loads(b[field])
        return None
    return run


def s3_get(field, wrap, code):
    def run(a, o, out):
        b = bucket(a, o)
        if b.get(field) is None:
            raise Err(code)
        return wrap(b[field])
    return run


def s3_versioning(a, o, out):
    """The bucket's versioning: `{}` until a test plants `versioning` on the bucket (a bucket that was never versioned
    answers with no Status at all)."""
    status = bucket(a, o).get("versioning")
    return {"Status": status} if status else {}


def s3_policy_status(a, o, out):
    b = bucket(a, o)
    if b.get("policy") is None:
        raise Err("NoSuchBucketPolicy")
    return {"PolicyStatus": {"IsPublic": bool(b.get("public", False))}}


def s3_delete_bucket(a, o, out):
    b = bucket(a, o)
    if b["objects"]:
        raise Err("BucketNotEmpty")
    del a["buckets"][one(o, "--bucket")]


def s3_list_buckets(a, o, out):
    return {"Buckets": [{"Name": n, "CreationDate": STAMP} for n in sorted(a["buckets"])], "Owner": {"ID": a["canonical"]}}


def s3_list_objects(a, o, out):
    b = bucket(a, o)
    keys = sorted(b["objects"])
    if "--delimiter" in o:
        prefixes = sorted({k.split("/", 1)[0] + "/" for k in keys if "/" in k})
        reply = {"CommonPrefixes": [{"Prefix": p} for p in prefixes], "Contents": [{"Key": k, "Size": 1} for k in keys if "/" not in k]}
        return {k: v for k, v in reply.items() if v} or {"RequestCharged": None}
    if not keys:
        return {"RequestCharged": None}
    return {"Contents": [{"Key": k, "Size": 1, "LastModified": STAMP} for k in keys], "RequestCharged": None}


def s3_delete_objects(a, o, out):
    b = bucket(a, o)
    gone = {x["Key"] for x in js(o, "--delete")["Objects"]}
    b["objects"] = [k for k in b["objects"] if k not in gone]
    return None


def s3control_block(a, o, out):
    late = o.get("--region", [""])[0] in a.get("account_block_not_yet_in", [])       # a regional endpoint that has not heard of it yet
    if one(o, "--account-id") != a["account"] or a.get("account_block") is None or late:
        raise Err("NoSuchPublicAccessBlockConfiguration")
    return {"PublicAccessBlockConfiguration": a["account_block"]}


# ------------------------------------------------------------------------------------------------ logs, firehose

def logs_create_group(a, o, out):
    name = one(o, "--log-group-name")
    fresh(a["log_groups"], name)
    a["log_groups"][name] = {"streams": [], "tags": tagged(o)}


def logs_retention(a, o, out):
    have(a["log_groups"], one(o, "--log-group-name"))["retention"] = int(one(o, "--retention-in-days"))


def logs_create_stream(a, o, out):
    g = have(a["log_groups"], one(o, "--log-group-name"))
    if one(o, "--log-stream-name") in g["streams"]:
        raise Err("ResourceAlreadyExistsException")
    g["streams"].append(one(o, "--log-stream-name"))


def logs_groups(a, o, out):
    prefix = o.get("--log-group-name-prefix", [""])[0]
    groups = []
    for name in sorted(a["log_groups"]):
        if name.startswith(prefix):
            g = {"logGroupName": name, "arn": arn(a, "logs", "log-group:%s:*" % name), "storedBytes": 0}
            if "retention" in a["log_groups"][name]:
                g["retentionInDays"] = a["log_groups"][name]["retention"]
            groups.append(g)
    return {"logGroups": groups}


def logs_streams(a, o, out):
    g = have(a["log_groups"], one(o, "--log-group-name"))
    prefix = o.get("--log-stream-name-prefix", [""])[0]
    return {"logStreams": [{"logStreamName": s} for s in sorted(g["streams"]) if s.startswith(prefix)]}


def logs_delete_group(a, o, out):
    have(a["log_groups"], one(o, "--log-group-name"))
    del a["log_groups"][one(o, "--log-group-name")]


def fh_create(a, o, out):
    name = one(o, "--delivery-stream-name")
    fresh(a["streams"], name, "ResourceInUseException")
    a["streams"][name] = {"type": one(o, "--delivery-stream-type"), "destination": js(o, "--extended-s3-destination-configuration"),
                          "status": a.get("stream_status", "ACTIVE"), "tags": tagged(o)}
    return {"DeliveryStreamARN": arn(a, "firehose", "deliverystream/" + name)}


def fh_describe(a, o, out):
    name = one(o, "--delivery-stream-name")
    s = have(a["streams"], name)
    dest = dict(s["destination"], EncryptionConfiguration={"NoEncryptionConfig": "NoEncryption"}, S3BackupMode="Disabled")
    return {"DeliveryStreamDescription": {
        "DeliveryStreamName": name, "DeliveryStreamARN": arn(a, "firehose", "deliverystream/" + name), "DeliveryStreamStatus": s["status"],
        "DeliveryStreamType": s["type"], "VersionId": "1", "HasMoreDestinations": False,
        "Destinations": [{"DestinationId": "destinationId-000000000001", "ExtendedS3DestinationDescription": dest}]}}


def fh_delete(a, o, out):
    name = one(o, "--delivery-stream-name")
    have(a["streams"], name)
    if a.get("stream_delete_is_slow"):
        a["streams"][name]["status"] = "DELETING"
    else:
        del a["streams"][name]


# ------------------------------------------------------------------------------------------------ iot

def rule_create(a, o, out):
    name = one(o, "--rule-name")
    fresh(a["rules"], name)
    a["rules"][name] = dict(js(o, "--topic-rule-payload"), tags=tagged(o))


def rule_get(a, o, out):
    name = one(o, "--rule-name")
    r = {k: v for k, v in have(a["rules"], name, "UnauthorizedException" if a.get("rule_missing_is_unauthorized") else
                                "ResourceNotFoundException").items() if k != "tags"}
    return {"ruleArn": arn(a, "iot", "rule/" + name), "rule": dict(r, ruleName=name, createdAt=STAMP)}


def rule_set(disabled):
    def run(a, o, out):
        have(a["rules"], one(o, "--rule-name"))["ruleDisabled"] = disabled
    return run


def rule_delete(a, o, out):
    name = one(o, "--rule-name")
    if name not in a["rules"] and a.get("rule_missing_is_unauthorized"):
        raise Err("UnauthorizedException")                       # the read's answer for a rule that is not there, given by the delete too
    a["rules"].pop(name, None)                                   # otherwise a missing rule is answered with success


def thing_create(a, o, out):
    name = one(o, "--thing-name")
    fresh(a["things"], name)
    a["things"][name] = {"shadows": {}, "principals": {}}
    return {"thingName": name, "thingArn": arn(a, "iot", "thing/" + name), "thingId": "00000000-0000-4000-8000-000000000000"}


def thing_describe(a, o, out):
    name = one(o, "--thing-name")
    have(a["things"], name)
    return {"thingName": name, "thingArn": arn(a, "iot", "thing/" + name), "attributes": a["things"][name].get("attributes", {}), "version": 1,
            "defaultClientId": name}


def thing_delete(a, o, out):
    name = one(o, "--thing-name")
    if name in a["things"] and a["things"][name]["principals"]:
        raise Err("InvalidRequestException", "a principal is attached")
    a["things"].pop(name, None)


def stub_pem(cert):
    """A certificate's PEM as the stub gives it: a sentence that says it is none, and the certificate's own id, so that
    each certificate has its own and a read gives back what the create gave."""
    body = base64.b64encode(b"EXAMPLE ONLY, made by a test stub: not a certificate and not a key. " * 2 + cert.encode("ascii")).decode("ascii")
    return "-----BEGIN " + "CERTIFICATE-----\n" + body + "\n-----END " + "CERTIFICATE-----\n"


def cert_create(a, o, out):
    one(o, "--certificate-signing-request")
    a["cert_counter"] = a.get("cert_counter", 0) + 1
    cert = hashlib.sha256(("stub certificate %d" % a["cert_counter"]).encode()).hexdigest()
    pem = stub_pem(cert)
    a["certs"][cert] = {"status": "ACTIVE" if "--set-as-active" in o else "INACTIVE", "policies": []}
    a["cert_last"] = cert
    if "--certificate-pem-outfile" in o:
        Path(one(o, "--certificate-pem-outfile")).write_text(pem, encoding="ascii")
    return {"certificateArn": arn(a, "iot", "cert/" + cert), "certificateId": cert, "certificatePem": pem}


def cert_list(a, o, out):
    """The certificates' listing. A test's plant, `listing_lags` (by the call's name: a count): for that many reads the
    listing does not show yet the certificate that was made last, as a listing that is behind a create would."""
    lags = a.get("listing_lags", {})
    hidden = None
    if lags.get("iot list-certificates", 0) > 0:
        lags["iot list-certificates"] -= 1
        hidden = a.get("cert_last")
    return {"certificates": [{"certificateId": c, "certificateArn": arn(a, "iot", "cert/" + c), "status": x["status"], "creationDate": STAMP}
                             for c, x in sorted(a["certs"].items()) if c != hidden]}


def cert_describe(a, o, out):
    cert = one(o, "--certificate-id")
    c = have(a["certs"], cert)
    return {"certificateDescription": {"certificateArn": a.get("arn_of", {}).get(cert) or arn(a, "iot", "cert/" + cert), "certificateId": cert,
                                       "status": c["status"], "ownedBy": a["account"], "creationDate": STAMP, "certificateMode": "DEFAULT",
                                       "certificatePem": a.get("pem_of", {}).get(cert) or stub_pem(cert)}}


def cert_update(a, o, out):
    have(a["certs"], one(o, "--certificate-id"))["status"] = one(o, "--new-status")


def cert_delete(a, o, out):
    cert = one(o, "--certificate-id")
    c = have(a["certs"], cert)
    if c["status"] == "ACTIVE":
        raise Err("CertificateStateException")
    if c["policies"] or any(arn(a, "iot", "cert/" + cert) in t["principals"] for t in a["things"].values()):
        raise Err("DeleteConflictException")
    del a["certs"][cert]


def cert_of(a, target):
    return have(a["certs"], target.rsplit("/", 1)[-1])


def policy_create(a, o, out):
    name = one(o, "--policy-name")
    fresh(a["policies"], name)
    json.loads(one(o, "--policy-document"))
    a["policies"][name] = {"document": one(o, "--policy-document"), "tags": tagged(o)}
    return {"policyName": name, "policyArn": arn(a, "iot", "policy/" + name), "policyVersionId": "1"}


def policy_get(a, o, out):
    name = one(o, "--policy-name")
    return {"policyName": name, "policyArn": arn(a, "iot", "policy/" + name), "policyDocument": have(a["policies"], name)["document"],
            "defaultVersionId": "1"}


def policy_delete(a, o, out):
    name = one(o, "--policy-name")
    have(a["policies"], name)
    if any(name in c["policies"] for c in a["certs"].values()):
        raise Err("DeleteConflictException")
    del a["policies"][name]


def policy_attach(a, o, out):
    name = one(o, "--policy-name")
    have(a["policies"], name)
    c = cert_of(a, one(o, "--target"))
    if name not in c["policies"]:
        c["policies"].append(name)


def policy_detach(a, o, out):
    c = cert_of(a, one(o, "--target"))
    c["policies"] = [p for p in c["policies"] if p != one(o, "--policy-name")]


def policy_attached(a, o, out):
    target = one(o, "--target")
    c = a["certs"].get(target.rsplit("/", 1)[-1], {"policies": []})
    return {"policies": [{"policyName": p, "policyArn": arn(a, "iot", "policy/" + p)} for p in c["policies"]]}


def policy_targets(a, o, out):
    name = one(o, "--policy-name")
    have(a["policies"], name)
    return {"targets": [arn(a, "iot", "cert/" + cert) for cert, c in sorted(a["certs"].items()) if name in c["policies"]]}


def principal_attach(a, o, out):
    have(a["certs"], one(o, "--principal").rsplit("/", 1)[-1])
    have(a["things"], one(o, "--thing-name"))["principals"][one(o, "--principal")] = o.get("--thing-principal-type", ["NON_EXCLUSIVE_THING"])[0]


def principal_detach(a, o, out):
    have(a["things"], one(o, "--thing-name"))["principals"].pop(one(o, "--principal"), None)


def principals_v2(a, o, out):
    t = have(a["things"], one(o, "--thing-name"))
    return {"thingPrincipalObjects": [{"principal": p, "thingPrincipalType": kind} for p, kind in sorted(t["principals"].items())]}


def logging_set(a, o, out):
    if "--disable-all-logs" in o:
        a["iot_logging"] = dict(a.get("iot_logging") or {}, disableAllLogs=True)
    else:
        a["iot_logging"] = {"roleArn": one(o, "--role-arn"), "defaultLogLevel": one(o, "--default-log-level"), "disableAllLogs": False}


def logging_get(a, o, out):
    if not a.get("iot_logging"):
        raise Err("NotConfiguredException")
    return a["iot_logging"]


def shadows_list(a, o, out):
    return {"results": sorted(have(a["things"], one(o, "--thing-name"))["shadows"]), "timestamp": 1767225600}


def shadow_update(a, o, out):
    doc = js(o, "--payload")
    have(a["things"], one(o, "--thing-name"))["shadows"][one(o, "--shadow-name")] = doc
    Path(out).write_text(json.dumps(doc), encoding="utf-8")


def shadow_delete(a, o, out):
    shadows = have(a["things"], one(o, "--thing-name"))["shadows"]
    have(shadows, one(o, "--shadow-name"))
    del shadows[one(o, "--shadow-name")]
    Path(out).write_text(json.dumps({"version": 1, "timestamp": 1767225600}), encoding="utf-8")


def shadow_get(a, o, out):
    doc = have(have(a["things"], one(o, "--thing-name"))["shadows"], one(o, "--shadow-name"))
    Path(out).write_text(json.dumps(doc), encoding="utf-8")


# ------------------------------------------------------------------------------------------------ glue, athena

def glue_db_create(a, o, out):
    d = js(o, "--database-input")
    fresh(a["glue"], d["Name"], "AlreadyExistsException")
    a["glue"][d["Name"]] = {"input": d, "tables": {}}


def glue_db_get(a, o, out):
    return {"Database": dict(have(a["glue"], one(o, "--name"), "EntityNotFoundException")["input"], CreateTime=STAMP)}


def glue_table_create(a, o, out):
    db = have(a["glue"], one(o, "--database-name"), "EntityNotFoundException")
    t = js(o, "--table-input")
    fresh(db["tables"], t["Name"], "AlreadyExistsException")
    db["tables"][t["Name"]] = t


def glue_table_get(a, o, out):
    db = have(a["glue"], one(o, "--database-name"), "EntityNotFoundException")
    return {"Table": dict(have(db["tables"], one(o, "--name"), "EntityNotFoundException"), DatabaseName=one(o, "--database-name"),
                          CreateTime=STAMP)}


def glue_table_delete(a, o, out):
    db = have(a["glue"], one(o, "--database-name"), "EntityNotFoundException")
    have(db["tables"], one(o, "--name"), "EntityNotFoundException")
    del db["tables"][one(o, "--name")]


def glue_db_delete(a, o, out):
    have(a["glue"], one(o, "--name"), "EntityNotFoundException")
    del a["glue"][one(o, "--name")]


def wg_create(a, o, out):
    name = one(o, "--name")
    fresh(a["workgroups"], name, "InvalidRequestException")
    a["workgroups"][name] = {"configuration": js(o, "--configuration"), "tags": tagged(o)}


def wg_get(a, o, out):
    name = one(o, "--work-group")
    if name not in a["workgroups"]:
        raise Err("InvalidRequestException", "WorkGroup %s is not found." % name)
    return {"WorkGroup": {"Name": name, "State": "ENABLED", "Configuration": a["workgroups"][name]["configuration"], "CreationTime": STAMP}}


def wg_delete(a, o, out):
    name = one(o, "--work-group")
    if name not in a["workgroups"]:
        raise Err("InvalidRequestException", "WorkGroup %s is not found." % name)
    del a["workgroups"][name]


# ------------------------------------------------------------------------------------------------ lambda

def fn_create(a, o, out):
    name = one(o, "--function-name")
    fresh(a["functions"], name, "ResourceConflictException")
    code = one(o, "--zip-file")
    if not isinstance(code, bytes):
        raise Err("ParamValidation", "--zip-file is a blob: fileb://")
    a["functions"][name] = {
        "config": {"FunctionName": name, "FunctionArn": arn(a, "lambda", "function:" + name), "Runtime": one(o, "--runtime"),
                   "Role": one(o, "--role"), "Handler": one(o, "--handler"), "CodeSha256": base64.b64encode(hashlib.sha256(code).digest()).decode(),
                   "Timeout": int(one(o, "--timeout")), "MemorySize": int(one(o, "--memory-size")), "Architectures": o["--architectures"],
                   "Environment": js(o, "--environment"), "State": "Active", "PackageType": "Zip", "Version": "$LATEST"},
        "statements": [], "urls": [], "concurrency": None, "tags": tagged(o)}
    function_zip(os.environ["STUB_AWS_DIR"], name).write_bytes(code)          # an invoke runs the handler out of this zip
    return a["functions"][name]["config"]


def fn(a, o):
    return have(a["functions"], one(o, "--function-name"))


def fn_get(a, o, out):
    f = fn(a, o)
    reply = {"Configuration": f["config"],
             "Code": {"RepositoryType": "S3", "Location": "https://lambda-tasks.s3.%s.amazonaws.com/snapshots/%s/%s?X-Amz-Signature=%s"
                      % (a["region"], a["account"], one(o, "--function-name"), "0" * 64)}}
    if f["concurrency"] is not None:
        reply["Concurrency"] = {"ReservedConcurrentExecutions": f["concurrency"]}
    return reply


def fn_delete(a, o, out):
    fn(a, o)
    del a["functions"][one(o, "--function-name")]
    code = function_zip(os.environ["STUB_AWS_DIR"], one(o, "--function-name"))
    if code.exists():
        code.unlink()


def fn_concurrency_put(a, o, out):
    if a.get("no_reserved_concurrency"):
        raise Err("InvalidParameterValueException")
    fn(a, o)["concurrency"] = int(one(o, "--reserved-concurrent-executions"))
    return {"ReservedConcurrentExecutions": fn(a, o)["concurrency"]}


def fn_concurrency_get(a, o, out):
    c = fn(a, o)["concurrency"]
    return {} if c is None else {"ReservedConcurrentExecutions": c}


def fn_concurrency_delete(a, o, out):
    fn(a, o)["concurrency"] = None


def fn_permission_add(a, o, out):
    f = fn(a, o)
    sid = one(o, "--statement-id")
    if any(s["Sid"] == sid for s in f["statements"]):
        raise Err("ResourceConflictException")
    st = {"Sid": sid, "Effect": "Allow", "Principal": {"Service": one(o, "--principal")}, "Action": one(o, "--action"),
          "Resource": f["config"]["FunctionArn"], "Condition": {"StringEquals": {"AWS:SourceAccount": one(o, "--source-account")},
                                                                "ArnLike": {"AWS:SourceArn": one(o, "--source-arn")}}}
    f["statements"].append(st)
    return {"Statement": json.dumps(st)}


def fn_permission_remove(a, o, out):
    f = fn(a, o)
    sid = one(o, "--statement-id")
    if not any(s["Sid"] == sid for s in f["statements"]):
        raise Err("ResourceNotFoundException")
    f["statements"] = [s for s in f["statements"] if s["Sid"] != sid]


def fn_policy(a, o, out):
    f = fn(a, o)
    if not f["statements"]:
        raise Err("ResourceNotFoundException")
    return {"Policy": json.dumps({"Version": "2012-10-17", "Id": "default", "Statement": f["statements"]}), "RevisionId": "1"}


# --- the function's own clients: what its handler is given in place of the SDK's (the module docstring, THE FUNCTION)

class ClientError(Exception):
    """An error the service answered, shaped as botocore's ClientError is."""

    def __init__(self, code, status=400, operation="", message="the stub's reading of the service"):
        super().__init__("An error occurred (%s) when calling the %s operation: %s" % (code, operation, message))
        self.response = {"Error": {"Code": code, "Message": message}, "ResponseMetadata": {"HTTPStatusCode": status}}
        self.operation_name = operation


class NoAnswer(Exception):
    """A call the service did not answer: a time-out, a connection that failed. It carries no response."""


class _Fake:
    """One client. Every call is recorded before anything else happens to it: [client, operation, arguments]. A fault a
    test planted for the operation is taken once per `times`: `code` (with `status`) is the service's own error,
    `no_answer` a call that got none, `ignored` a call that is accepted and changes nothing, `more` a listing that
    says it goes on."""

    def __init__(self, account, calls, faults, name):
        self._a, self._calls, self._faults, self._name = account, calls, faults, name

    def _begin(self, op, kwargs):
        self._calls.append([self._name, op, dict(kwargs)])
        for f in self._faults:
            if f.get("client", "iot") == self._name and f["op"] == op and f.get("times", 1) > 0:
                f["times"] = f.get("times", 1) - 1
                if f.get("no_answer"):
                    raise NoAnswer("the call got no answer")
                if f.get("ignored") or f.get("more"):
                    return f
                raise ClientError(f["code"], f.get("status", 400), op)
        return {}

    def _have(self, table, name, op):
        if name not in self._a[table]:
            raise ClientError("ResourceNotFoundException", 404, op)
        return self._a[table][name]


class FakeIot(_Fake):
    """The control plane's seven calls the function makes, each with the argument names the service gives them. There
    is no other method: a call that enables, attaches or activates has nothing to land on."""

    def __init__(self, account, calls, faults):
        super().__init__(account, calls, faults, "iot")

    def disable_topic_rule(self, *, ruleName):
        if not self._begin("disable_topic_rule", {"ruleName": ruleName}).get("ignored"):
            self._have("rules", ruleName, "disable_topic_rule")["ruleDisabled"] = True
        return {}

    def update_certificate(self, *, certificateId, newStatus):
        if not self._begin("update_certificate", {"certificateId": certificateId, "newStatus": newStatus}).get("ignored"):
            self._have("certs", certificateId, "update_certificate")["status"] = newStatus
        return {}

    def detach_policy(self, *, policyName, target):
        if not self._begin("detach_policy", {"policyName": policyName, "target": target}).get("ignored"):
            c = self._have("certs", target.rsplit("/", 1)[-1], "detach_policy")
            c["policies"] = [p for p in c["policies"] if p != policyName]
        return {}

    def describe_certificate(self, *, certificateId):
        self._begin("describe_certificate", {"certificateId": certificateId})
        c = self._have("certs", certificateId, "describe_certificate")
        return {"certificateDescription": {"certificateArn": arn(self._a, "iot", "cert/" + certificateId), "certificateId": certificateId,
                                           "status": c["status"], "ownedBy": self._a["account"]}}

    def list_targets_for_policy(self, *, policyName, pageSize=None, marker=None):
        kwargs = {"policyName": policyName}
        kwargs.update({k: v for k, v in (("pageSize", pageSize), ("marker", marker)) if v is not None})
        more = self._begin("list_targets_for_policy", kwargs).get("more")
        self._have("policies", policyName, "list_targets_for_policy")
        reply = {"targets": [arn(self._a, "iot", "cert/" + cert) for cert, c in sorted(self._a["certs"].items()) if policyName in c["policies"]]}
        if more:
            reply["nextMarker"] = "more"
        return reply

    def get_topic_rule(self, *, ruleName):
        self._begin("get_topic_rule", {"ruleName": ruleName})
        r = self._have("rules", ruleName, "get_topic_rule")
        return {"ruleArn": arn(self._a, "iot", "rule/" + ruleName), "rule": {"ruleName": ruleName, "ruleDisabled": bool(r.get("ruleDisabled"))}}


class FakeIotData(_Fake):
    """The data plane: the one call. A client that is not connected is answered as not found."""

    def __init__(self, account, calls, faults):
        super().__init__(account, calls, faults, "iot-data")

    def delete_connection(self, *, clientId):
        if not self._begin("delete_connection", {"clientId": clientId}).get("ignored"):
            connected = self._a.setdefault("connections", [])
            if clientId not in connected:
                raise ClientError("ResourceNotFoundException", 404, "delete_connection")
            connected.remove(clientId)
        return {}


class FakeIotDataOld(_Fake):
    """The data plane of a runtime whose SDK is older than the call: it is not there."""

    def __init__(self, account, calls, faults):
        super().__init__(account, calls, faults, "iot-data")

    def get_thing_shadow(self, *, thingName):
        raise ClientError("ResourceNotFoundException", 404, "get_thing_shadow")


class FunctionFailed(Exception):
    """The function did not get as far as its handler: what the runtime answers in its place."""


class Context:
    def __init__(self, request_id):
        self.aws_request_id = request_id
        self.function_name = "the-stub"

    def get_remaining_time_in_millis(self):
        return 30000


def load_function(code, handler):
    """The module and the handler a function's zip holds, as the runtime finds them: <module>.<function>, the module
    being the entry <module>.py."""
    module, _dot, name = handler.partition(".")
    try:
        with zipfile.ZipFile(io.BytesIO(code)) as z:
            source = z.read(module + ".py")
    except (KeyError, zipfile.BadZipFile):
        raise FunctionFailed("Runtime.ImportModuleError") from None
    mod = types.ModuleType(module)
    mod.__file__ = "/var/task/%s.py" % module
    try:
        exec(compile(source, mod.__file__, "exec"), mod.__dict__)
    except Exception:
        raise FunctionFailed("Runtime.ImportModuleError") from None
    if not callable(getattr(mod, name, None)):
        raise FunctionFailed("Runtime.HandlerNotFound")
    return mod, getattr(mod, name)


def function_zip(d, name):
    return Path(d) / ("function-%s.zip" % name)


def run_function(a, d, name, event):
    """One invoke: (the payload, None) or (the error's payload, "Unhandled"). The handler runs with the function's own
    environment and nothing else of this process's TWIN_ variables."""
    f = a["functions"][name]
    a["invokes"] = a.get("invokes", 0) + 1
    request = "00000000-0000-4000-8000-%012d" % a["invokes"]
    calls, out, error = [], io.StringIO(), None
    saved = dict(os.environ)
    try:
        if a.get("function_error"):                              # a test's plant: the function fails before its first line
            raise FunctionFailed("Runtime.ImportModuleError")
        mod, handler = load_function(function_zip(d, name).read_bytes(), f["config"]["Handler"])
        faults = a.setdefault("function_faults", [])
        data = (FakeIotDataOld if a.get("no_delete_connection") else FakeIotData)(a, calls, faults)
        clients = (FakeIot(a, calls, faults), data, a.get("runtime_boto3", "1.40.0"))
        mod._clients = lambda: clients
        for key in [k for k in os.environ if k.startswith("TWIN_")]:
            del os.environ[key]
        os.environ.update(f["config"]["Environment"]["Variables"])
        with contextlib.redirect_stdout(out):
            record = handler(event, Context(request))
    except FunctionFailed as e:
        record, error = {"errorMessage": "the function could not be loaded", "errorType": str(e), "requestId": request, "stackTrace": []}, "Unhandled"
    except Exception as e:
        record, error = {"errorMessage": str(e), "errorType": type(e).__name__, "requestId": request, "stackTrace": []}, "Unhandled"
    finally:
        os.environ.clear()
        os.environ.update(saved)
    if any(c[1] == "disable_topic_rule" for c in calls):
        a["trips"] = a.get("trips", 0) + 1
    if error:
        a["function_errors"] = a.get("function_errors", 0) + 1
    note(Path(d), "function-calls.jsonl", {"request": request, "error": error, "calls": calls})
    for line in out.getvalue().split("\n"):
        if line.strip():
            note_line(Path(d), "function-log.jsonl", line)
    return record, error


def fn_invoke(a, o, out):
    fn(a, o)
    payload = js(o, "--payload")
    record, error = run_function(a, os.environ["STUB_AWS_DIR"], one(o, "--function-name"), payload)
    if isinstance(record, dict):
        record.update(a.get("record_extra", {}))
    Path(out).write_text(json.dumps(record), encoding="utf-8")
    reply = {"StatusCode": 200, "ExecutedVersion": "$LATEST"}
    if error:
        reply["FunctionError"] = error
    if "--log-type" in o:
        reply["LogResult"] = base64.b64encode(b"START the function's own log, which names what the breaker acts on\n" * 2).decode()
    if a.get("invoke_log_result"):
        reply["LogResult"] = a["invoke_log_result"]
    return reply


# ------------------------------------------------------------------------------------------------ sns, cloudwatch, iam, the rest

def topic_create(a, o, out):
    t = arn(a, "sns", one(o, "--name"))
    default = json.dumps({"Version": "2008-10-17", "Statement": [{"Sid": "__default_statement_ID", "Effect": "Allow", "Principal": {"AWS": "*"},
                                                                 "Action": ["SNS:Publish", "SNS:Subscribe"], "Resource": t,
                                                                 "Condition": {"StringEquals": {"AWS:SourceOwner": a["account"]}}}]})
    a["topics"].setdefault(t, {"policy": default, "subscriptions": [], "tags": tagged(o)})
    return {"TopicArn": t}


def topic(a, o):
    return have(a["topics"], one(o, "--topic-arn"), "NotFound")


def topic_set(a, o, out):
    if one(o, "--attribute-name") != "Policy":
        raise Err("InvalidParameter")
    json.loads(one(o, "--attribute-value"))
    topic(a, o)["policy"] = one(o, "--attribute-value")


def topic_get(a, o, out):
    t = topic(a, o)
    return {"Attributes": {"Policy": t["policy"], "TopicArn": one(o, "--topic-arn"), "Owner": a["account"],
                           "SubscriptionsConfirmed": str(sum(1 for s in t["subscriptions"] if s["confirmed"])),
                           "SubscriptionsPending": str(sum(1 for s in t["subscriptions"] if not s["confirmed"]))}}


def topic_subscribe(a, o, out):
    topic(a, o)["subscriptions"].append({"protocol": one(o, "--protocol"), "endpoint": one(o, "--notification-endpoint"),
                                         "confirmed": bool(a.get("subscriptions_confirm_at_once"))})
    return {"SubscriptionArn": "pending confirmation"}


def topic_subscriptions(a, o, out):
    t = topic(a, o)
    return {"Subscriptions": [{"SubscriptionArn": (one(o, "--topic-arn") + ":00000000-0000-4000-8000-00000000000%d" % i) if s["confirmed"]
                               else "PendingConfirmation", "Protocol": s["protocol"], "Endpoint": s["endpoint"],
                               "TopicArn": one(o, "--topic-arn"), "Owner": a["account"]} for i, s in enumerate(t["subscriptions"])]}


def topic_delete(a, o, out):
    a["topics"].pop(one(o, "--topic-arn"), None)                 # deleting a topic that is not there succeeds


def alarm_put(a, o, out):
    name = one(o, "--alarm-name")
    old = a["alarms"].get(name, {})
    a["alarms"][name] = {
        "AlarmName": name, "AlarmArn": arn(a, "cloudwatch", "alarm:" + name), "Namespace": one(o, "--namespace"),
        "MetricName": one(o, "--metric-name"), "Dimensions": js(o, "--dimensions"), "Statistic": one(o, "--statistic"),
        "Period": int(one(o, "--period")), "EvaluationPeriods": int(one(o, "--evaluation-periods")),
        "DatapointsToAlarm": int(one(o, "--datapoints-to-alarm")), "ComparisonOperator": one(o, "--comparison-operator"),
        "Threshold": float(one(o, "--threshold")), "TreatMissingData": one(o, "--treat-missing-data"),
        "ActionsEnabled": "--no-actions-enabled" not in o, "AlarmActions": list(o.get("--alarm-actions", [])), "OKActions": [],
        "InsufficientDataActions": [], "StateValue": old.get("StateValue", "INSUFFICIENT_DATA"), "tags": tagged(o)}


def alarm_describe(a, o, out):
    names = o.get("--alarm-names")
    alarms = [{k: v for k, v in x.items() if k != "tags"} for n, x in sorted(a["alarms"].items()) if names is None or n in names]
    return {"MetricAlarms": alarms, "CompositeAlarms": []}


def alarm_delete(a, o, out):
    for name in o.get("--alarm-names", []):
        a["alarms"].pop(name, None)                              # a name that is not there is no error


def alarm_set_state(a, o, out):
    x = have(a["alarms"], one(o, "--alarm-name"), "ResourceNotFound")
    reason, before = one(o, "--state-reason"), x["StateValue"]
    x["StateValue"] = one(o, "--state-value")
    if x["StateValue"] == "ALARM" and x["ActionsEnabled"]:
        for action in x["AlarmActions"]:
            for name, f in sorted(a["functions"].items()):
                granted = any(s["Condition"]["ArnLike"]["AWS:SourceArn"] == x["AlarmArn"] for s in f["statements"])
                if f["config"]["FunctionArn"] == action and granted:
                    # the alarm's own invoke: asynchronous, so what the function answers reaches nobody here. The event is
                    # the documented shape of an alarm's direct invoke, written from the documentation
                    stamp = "2026-01-01T00:00:00.000+0000"
                    event = {"source": "aws.cloudwatch", "alarmArn": x["AlarmArn"], "accountId": a["account"], "time": stamp, "region": a["region"],
                             "alarmData": {"alarmName": x["AlarmName"], "state": {"value": "ALARM", "reason": reason, "timestamp": stamp},
                                           "previousState": {"value": before, "reason": "the stub's", "timestamp": stamp},
                                           "configuration": {"metrics": [{"id": "m1", "metricStat": {
                                               "metric": {"namespace": x["Namespace"], "name": x["MetricName"]}, "period": x["Period"],
                                               "stat": x["Statistic"]}, "returnData": True}]}}}
                    run_function(a, os.environ["STUB_AWS_DIR"], name, event)
                    a["alarm_invokes"] = a.get("alarm_invokes", 0) + 1
    if not a.get("alarms_stay"):
        x["StateValue"] = "OK"                                   # the next evaluation, with no data: not breaching


def role_get(a, o, out):
    name = one(o, "--role-name")
    r = have(a["roles"], name, "NoSuchEntity")
    return {"Role": {"RoleName": name, "Arn": "arn:aws:iam::%s:role/%s" % (a["account"], name), "AssumeRolePolicyDocument": r["trust"],
                     "CreateDate": STAMP, "Path": "/"}}


def role_policy(a, o, out):
    r = have(a["roles"], one(o, "--role-name"), "NoSuchEntity")
    return {"RoleName": one(o, "--role-name"), "PolicyName": one(o, "--policy-name"),
            "PolicyDocument": have(r["policies"], one(o, "--policy-name"), "NoSuchEntity")}


def tag_query(a, o, out):
    one(o, "--tag-filters")
    found = []
    for table, form in (("buckets", "arn:aws:s3:::%s"), ("log_groups", "log-group:%s"), ("streams", "deliverystream/%s"), ("rules", "rule/%s"),
                        ("policies", "policy/%s"), ("workgroups", "workgroup/%s"), ("functions", "function:%s"), ("topics", "%s"),
                        ("alarms", "alarm:%s")):
        for name, x in sorted(a[table].items()):
            if x.get("tags") or x.get("tagging"):
                found.append({"ResourceARN": form % name, "Tags": []})
    for name, x in sorted(a.get("repositories", {}).items()):
        if x.get("tags"):
            found.append({"ResourceARN": arn(a, "ecr", "repository/" + name), "Tags": []})
    for name in a.get("tagged_only", []):                        # a tagged resource of a kind no listing of the driver holds
        found.append({"ResourceARN": name, "Tags": []})
    return {"PaginationToken": "", "ResourceTagMappingList": found}      # the token is there and empty when nothing follows


# ------------------------------------------------------------------------------------------------ ecr, ecr-public, the role alias

class Text(str):
    """A reply the CLI prints as text, not as JSON: `ecr get-login-password`'s."""


def repository(a, name):
    return have(a.get("repositories", {}), name, "RepositoryNotFoundException")


def repo_reply(a, name, r):
    return {"repositoryArn": arn(a, "ecr", "repository/" + name), "registryId": a["account"], "repositoryName": name,
            "repositoryUri": "%s.dkr.ecr.%s.amazonaws.com/%s" % (a["account"], a["region"], name), "createdAt": 1767225600.0,
            "imageTagMutability": r["mutability"], "imageScanningConfiguration": {"scanOnPush": False},
            "encryptionConfiguration": r["encryption"]}


def ecr_create(a, o, out):
    name = one(o, "--repository-name")
    fresh(a.setdefault("repositories", {}), name, "RepositoryAlreadyExistsException")
    encryption = js(o, "--encryption-configuration") if "--encryption-configuration" in o else {"encryptionType": "AES256"}
    a["repositories"][name] = {"mutability": o.get("--image-tag-mutability", ["MUTABLE"])[0], "encryption": encryption, "policy": None,
                               "lifecycle": None, "images": [], "tags": tagged(o)}
    return {"repository": repo_reply(a, name, a["repositories"][name])}


def ecr_describe(a, o, out):
    names_ = o.get("--repository-names") or sorted(a.get("repositories", {}))
    return {"repositories": [repo_reply(a, n, repository(a, n)) for n in names_]}


def ecr_policy(a, o, out):
    r = repository(a, one(o, "--repository-name"))
    if r["policy"] is None:
        raise Err("RepositoryPolicyNotFoundException")
    return {"registryId": a["account"], "repositoryName": one(o, "--repository-name"), "policyText": r["policy"]}


def ecr_delete(a, o, out):
    name = one(o, "--repository-name")
    if repository(a, name)["images"] and "--force" not in o:
        raise Err("RepositoryNotEmptyException")
    del a["repositories"][name]
    return {"repository": {"repositoryName": name}}


def ecr_lifecycle_put(a, o, out):
    r = repository(a, one(o, "--repository-name"))
    r["lifecycle"] = one(o, "--lifecycle-policy-text")
    json.loads(r["lifecycle"])
    return {"registryId": a["account"], "repositoryName": one(o, "--repository-name"), "lifecyclePolicyText": r["lifecycle"]}


def ecr_lifecycle_get(a, o, out):
    r = repository(a, one(o, "--repository-name"))
    if r["lifecycle"] is None:
        raise Err("LifecyclePolicyNotFoundException")
    return {"registryId": a["account"], "repositoryName": one(o, "--repository-name"), "lifecyclePolicyText": r["lifecycle"],
            "lastEvaluatedAt": 1767225600.0}


def ecr_lifecycle_delete(a, o, out):
    r = repository(a, one(o, "--repository-name"))
    if r["lifecycle"] is None:
        raise Err("LifecyclePolicyNotFoundException")
    r["lifecycle"] = None


def ecr_images(a, o, out):
    r = repository(a, one(o, "--repository-name"))
    return {"imageIds": [dict({"imageDigest": i["imageDigest"]}, **({"imageTag": t} if t else {})) for i in r["images"]
                         for t in (i["imageTags"] or [None])]}


def ecr_image_details(a, o, out):
    r = repository(a, one(o, "--repository-name"))
    want = one(o, "--image-ids")
    if not want.startswith("imageTag="):
        raise Err("ParamValidation", "--image-ids is imageTag=TAG here")
    found = [i for i in r["images"] if want[len("imageTag="):] in i["imageTags"]]
    if not found:
        raise Err("ImageNotFoundException")
    return {"imageDetails": [dict(found[0], registryId=a["account"], repositoryName=one(o, "--repository-name"))]}


def ecr_registry_policy(a, o, out):
    if a.get("registry_policy") is None:
        raise Err("RegistryPolicyNotFoundException")
    return {"registryId": a["account"], "policyText": a["registry_policy"]}


def ecr_public(a, o, out):
    if o.get("--region") != ["us-east-1"]:
        raise Err("UnrecognizedClientException", "ECR Public answers in us-east-1 only")
    return {"repositories": a.get("public_repositories", [])}


def alias_create(a, o, out):
    name = one(o, "--role-alias")
    fresh(a.setdefault("role_aliases", {}), name)
    a["role_aliases"][name] = {"roleArn": one(o, "--role-arn"), "credentialDurationSeconds": int(one(o, "--credential-duration-seconds"))}
    return {"roleAlias": name, "roleAliasArn": arn(a, "iot", "rolealias/" + name)}


def alias_describe(a, o, out):
    name = one(o, "--role-alias")
    x = have(a.get("role_aliases", {}), name)
    return {"roleAliasDescription": {"roleAlias": name, "roleAliasArn": arn(a, "iot", "rolealias/" + name), "roleArn": x["roleArn"],
                                     "owner": a["account"], "credentialDurationSeconds": x["credentialDurationSeconds"],
                                     "creationDate": STAMP, "lastModifiedDate": STAMP}}


def alias_delete(a, o, out):
    name = one(o, "--role-alias")
    have(a.get("role_aliases", {}), name)
    del a["role_aliases"][name]


def endpoint(a, o, out):
    kind = o.get("--endpoint-type", ["iot:Data-ATS"])[0]
    if kind == "iot:CredentialProvider":
        return {"endpointAddress": a.get("credential_endpoint", "")}
    return {"endpointAddress": a["endpoint"]}


def names(table, key, field):
    return lambda a, o, out: {key: [{field: n} for n in sorted(a[table])]}


def caller(a, o, out):
    """Who the profile answers for. A test that plants `identity_then` (a list of identities) has the READ AFTER this one
    answer as the first of them, and so on: a profile repointed between two reads of one command."""
    now = dict(a["identity"])
    if a.get("identity_then"):
        a["identity"] = a["identity_then"].pop(0)
    return dict(now, Account=now.get("Account", a["account"]))


OPS = {
    ("sts", "get-caller-identity"): (caller, False),
    ("s3api", "create-bucket"): (s3_create_bucket, True),
    ("s3api", "put-public-access-block"): (s3_put("block", "--public-access-block-configuration"), True),
    ("s3api", "put-bucket-encryption"): (s3_put("encryption", "--server-side-encryption-configuration"), True),
    ("s3api", "put-bucket-lifecycle-configuration"): (s3_put("lifecycle", "--lifecycle-configuration"), True),
    ("s3api", "put-bucket-policy"): (s3_put("policy", "--policy", parse_json=False), True),
    ("s3api", "put-bucket-tagging"): (s3_put("tagging", "--tagging"), True),
    ("s3api", "get-bucket-versioning"): (s3_versioning, False),
    ("s3api", "get-public-access-block"): (s3_get("block", lambda v: {"PublicAccessBlockConfiguration": v},
                                                  "NoSuchPublicAccessBlockConfiguration"), False),
    ("s3api", "get-bucket-ownership-controls"): (s3_get("ownership", lambda v: {"OwnershipControls": {"Rules": [{"ObjectOwnership": v}]}},
                                                        "OwnershipControlsNotFoundError"), False),
    ("s3api", "get-bucket-encryption"): (s3_get("encryption", lambda v: {"ServerSideEncryptionConfiguration": v},
                                                "ServerSideEncryptionConfigurationNotFoundError"), False),
    ("s3api", "get-bucket-lifecycle-configuration"): (
        s3_get("lifecycle", lambda v: dict(v, TransitionDefaultMinimumObjectSize="all_storage_classes_128K"), "NoSuchLifecycleConfiguration"),
        False),
    ("s3api", "get-bucket-policy"): (s3_get("policy", lambda v: {"Policy": v}, "NoSuchBucketPolicy"), False),
    ("s3api", "get-bucket-policy-status"): (s3_policy_status, False),
    ("s3api", "delete-bucket"): (s3_delete_bucket, True),
    ("s3api", "list-buckets"): (s3_list_buckets, False),
    ("s3api", "list-objects-v2"): (s3_list_objects, False),
    ("s3api", "delete-objects"): (s3_delete_objects, True),
    ("s3control", "get-public-access-block"): (s3control_block, False),
    ("logs", "create-log-group"): (logs_create_group, True),
    ("logs", "put-retention-policy"): (logs_retention, True),
    ("logs", "create-log-stream"): (logs_create_stream, True),
    ("logs", "describe-log-groups"): (logs_groups, False),
    ("logs", "describe-log-streams"): (logs_streams, False),
    ("logs", "delete-log-group"): (logs_delete_group, True),
    ("firehose", "create-delivery-stream"): (fh_create, True),
    ("firehose", "describe-delivery-stream"): (fh_describe, False),
    ("firehose", "delete-delivery-stream"): (fh_delete, True),
    ("firehose", "list-delivery-streams"): (lambda a, o, out: {"DeliveryStreamNames": sorted(a["streams"]), "HasMoreDeliveryStreams": False}, False),
    ("iot", "create-topic-rule"): (rule_create, True),
    ("iot", "get-topic-rule"): (rule_get, False),
    ("iot", "delete-topic-rule"): (rule_delete, True),
    ("iot", "enable-topic-rule"): (rule_set(False), True),
    ("iot", "disable-topic-rule"): (rule_set(True), True),
    ("iot", "list-topic-rules"): (names("rules", "rules", "ruleName"), False),
    ("iot", "create-thing"): (thing_create, True),
    ("iot", "describe-thing"): (thing_describe, False),
    ("iot", "delete-thing"): (thing_delete, True),
    ("iot", "list-things"): (names("things", "things", "thingName"), False),
    ("iot", "create-certificate-from-csr"): (cert_create, True),
    ("iot", "describe-certificate"): (cert_describe, False),
    ("iot", "update-certificate"): (cert_update, True),
    ("iot", "delete-certificate"): (cert_delete, True),
    ("iot", "list-certificates"): (cert_list, False),
    ("iot", "create-policy"): (policy_create, True),
    ("iot", "get-policy"): (policy_get, False),
    ("iot", "delete-policy"): (policy_delete, True),
    ("iot", "list-policies"): (names("policies", "policies", "policyName"), False),
    ("iot", "attach-policy"): (policy_attach, True),
    ("iot", "detach-policy"): (policy_detach, True),
    ("iot", "list-attached-policies"): (policy_attached, False),
    ("iot", "list-targets-for-policy"): (policy_targets, False),
    ("iot", "attach-thing-principal"): (principal_attach, True),
    ("iot", "detach-thing-principal"): (principal_detach, True),
    ("iot", "list-thing-principals-v2"): (principals_v2, False),
    ("iot", "set-v2-logging-options"): (logging_set, True),
    ("iot", "get-v2-logging-options"): (logging_get, False),
    ("iot", "describe-endpoint"): (endpoint, False),
    ("iot", "create-role-alias"): (alias_create, True),
    ("iot", "describe-role-alias"): (alias_describe, False),
    ("iot", "delete-role-alias"): (alias_delete, True),
    ("iot", "list-role-aliases"): (lambda a, o, out: {"roleAliases": sorted(a.get("role_aliases", {}))}, False),
    ("ecr", "create-repository"): (ecr_create, True),
    ("ecr", "describe-repositories"): (ecr_describe, False),
    ("ecr", "get-repository-policy"): (ecr_policy, False),
    ("ecr", "delete-repository"): (ecr_delete, True),
    ("ecr", "put-lifecycle-policy"): (ecr_lifecycle_put, True),
    ("ecr", "get-lifecycle-policy"): (ecr_lifecycle_get, False),
    ("ecr", "delete-lifecycle-policy"): (ecr_lifecycle_delete, True),
    ("ecr", "list-images"): (ecr_images, False),
    ("ecr", "describe-images"): (ecr_image_details, False),
    ("ecr", "get-login-password"): (lambda a, o, out: Text(a["ecr_password"]), False),
    ("ecr", "describe-registry"): (lambda a, o, out: {"registryId": a["account"],
                                                      "replicationConfiguration": {"rules": a.get("replication_rules", [])}}, False),
    ("ecr", "get-registry-policy"): (ecr_registry_policy, False),
    ("ecr", "describe-pull-through-cache-rules"): (lambda a, o, out: {"pullThroughCacheRules": a.get("cache_rules", [])}, False),
    ("ecr", "get-registry-scanning-configuration"): (lambda a, o, out: {"registryId": a["account"], "scanningConfiguration": {
        "scanType": a.get("scan_type", "BASIC"), "rules": []}}, False),
    ("ecr-public", "describe-repositories"): (ecr_public, False),
    ("iot", "list-authorizers"): (lambda a, o, out: {"authorizers": a.get("authorizers", [])}, False),
    ("iot", "list-domain-configurations"): (lambda a, o, out: {"domainConfigurations": a.get("domains", [])}, False),
    ("iot-data", "list-named-shadows-for-thing"): (shadows_list, False),
    ("iot-data", "update-thing-shadow"): (shadow_update, True),
    ("iot-data", "delete-thing-shadow"): (shadow_delete, True),
    ("iot-data", "get-thing-shadow"): (shadow_get, False),
    # one of the stop's four calls by hand: `plan` gives it to the CLI to read; no command of the driver sends it
    ("iot-data", "delete-connection"): (lambda a, o, out: one(o, "--client-id") and None, True),
    ("glue", "create-database"): (glue_db_create, True),
    ("glue", "get-database"): (glue_db_get, False),
    ("glue", "create-table"): (glue_table_create, True),
    ("glue", "get-table"): (glue_table_get, False),
    ("glue", "delete-table"): (glue_table_delete, True),
    ("glue", "delete-database"): (glue_db_delete, True),
    ("glue", "get-databases"): (lambda a, o, out: {"DatabaseList": [{"Name": n} for n in sorted(a["glue"])]}, False),
    ("athena", "create-work-group"): (wg_create, True),
    ("athena", "get-work-group"): (wg_get, False),
    ("athena", "delete-work-group"): (wg_delete, True),
    ("athena", "list-work-groups"): (lambda a, o, out: {"WorkGroups": [{"Name": n, "State": "ENABLED"} for n in sorted(a["workgroups"])]}, False),
    ("lambda", "create-function"): (fn_create, True),
    ("lambda", "get-function"): (fn_get, False),
    ("lambda", "delete-function"): (fn_delete, True),
    ("lambda", "list-functions"): (names("functions", "Functions", "FunctionName"), False),
    ("lambda", "put-function-concurrency"): (fn_concurrency_put, True),
    ("lambda", "get-function-concurrency"): (fn_concurrency_get, False),
    ("lambda", "delete-function-concurrency"): (fn_concurrency_delete, True),
    ("lambda", "list-function-url-configs"): (lambda a, o, out: {"FunctionUrlConfigs": fn(a, o)["urls"]}, False),
    ("lambda", "add-permission"): (fn_permission_add, True),
    ("lambda", "remove-permission"): (fn_permission_remove, True),
    ("lambda", "get-policy"): (fn_policy, False),
    ("lambda", "invoke"): (fn_invoke, True),
    ("sns", "create-topic"): (topic_create, True),
    ("sns", "set-topic-attributes"): (topic_set, True),
    ("sns", "get-topic-attributes"): (topic_get, False),
    ("sns", "subscribe"): (topic_subscribe, True),
    ("sns", "list-subscriptions-by-topic"): (topic_subscriptions, False),
    ("sns", "delete-topic"): (topic_delete, True),
    ("sns", "list-topics"): (lambda a, o, out: {"Topics": [{"TopicArn": t} for t in sorted(a["topics"])]}, False),
    ("cloudwatch", "put-metric-alarm"): (alarm_put, True),
    ("cloudwatch", "describe-alarms"): (alarm_describe, False),
    ("cloudwatch", "delete-alarms"): (alarm_delete, True),
    ("cloudwatch", "set-alarm-state"): (alarm_set_state, True),
    ("iam", "get-role"): (role_get, False),
    ("iam", "get-role-policy"): (role_policy, False),
    ("resourcegroupstaggingapi", "get-resources"): (tag_query, False),
    ("ec2", "describe-security-groups"): (lambda a, o, out: {"SecurityGroups": a.get("security_groups", [])}, False),
    ("cognito-identity", "list-identity-pools"): (lambda a, o, out: {"IdentityPools": a.get("pools", [])}, False),
    ("apigateway", "get-rest-apis"): (lambda a, o, out: {"items": a.get("rest_apis", [])}, False),
    ("apigatewayv2", "get-apis"): (lambda a, o, out: {"Items": a.get("http_apis", [])}, False),
}


SAMPLE_FAILS = {
    ("iam", "get-role"): "Invalid length for parameter Role.RoleId, value: 6, valid min length: 16\n"
                         "Invalid value for parameter Role.MaxSessionDuration, value: 0, valid min value: 3600",
    ("lambda", "list-functions"): "Invalid value for parameter Functions[0].Timeout, value: 0, valid min value: 1",
    ("cloudwatch", "describe-alarms"): "Invalid value for parameter MetricAlarms[0].Period, value: 0, valid min value: 1",
    ("iot", "list-certificates"): "Invalid length for parameter certificates[0].certificateId, value: 13, valid min length: 64",
    ("firehose", "describe-delivery-stream"):
        "Invalid value for parameter DeliveryStreamDescription.Destinations[0].S3DestinationDescription.BufferingHints.SizeInMBs, value: 0, "
        "valid min value: 1",
}


def note(d, name, entry):
    note_line(d, name, json.dumps(entry, sort_keys=True))


def note_line(d, name, line):
    with open(str(Path(d) / name), "a", encoding="utf-8", newline="\n") as f:
        f.write(line.rstrip("\n") + "\n")


def empty(path):
    return bool(path) and os.path.isfile(path) and os.path.getsize(path) == 0


def main(argv):
    d = Path(os.environ["STUB_AWS_DIR"])
    if len(argv) < 2:
        sys.stderr.write("stub: usage: SERVICE OPERATION ...\n")
        return 252
    service, op = argv[0], argv[1]
    try:
        opts, out = parse(service, op, argv[2:])
    except Err as e:
        sys.stderr.write("stub: %s\n" % e.message)
        return 252
    if (service, op) not in OPS:
        note(d, "unknown.jsonl", {"argv": argv})
        sys.stderr.write("aws: error: argument operation: Invalid choice (the stub models no such call)\n")
        return 252
    if "--generate-cli-skeleton" in opts:
        # Three things the real CLI was seen to do (2.35.1, offline): it knows no skeleton for a command that takes an
        # output file; it names a required option that is missing; and for some reads its own sample reply fails its own
        # validation, after the arguments were read, in the words it has for a bad argument.
        if (service, op) in OUTFILE or (service, op) == ("ecr", "get-login-password"):     # the latter a customization of the CLI's
            sys.stderr.write("usage: aws [options] <command> <subcommand> [<subcommand> ...] [parameters]\n\n"
                             "aws: [ERROR]: Unknown options: --generate-cli-skeleton, output\n")
            return 252
        planted = json.loads((d / "account.json").read_text(encoding="utf-8")).get("skeleton_says", {}).get("%s %s" % (service, op))
        if planted:
            sys.stderr.write(planted + "\n")
            return 252
        if (service, op) in SAMPLE_FAILS:
            note(d, "skeleton.jsonl", {"argv": argv, "env": None})
            sys.stderr.write("aws: [ERROR]: An error occurred (ParamValidation): Parameter validation failed:\n" + SAMPLE_FAILS[(service, op)] + "\n")
            return 252
        try:
            for values in opts.values():
                for v in values:
                    load(v)
        except OSError:
            sys.stderr.write("Error parsing parameter: Unable to load paramfile\n")
            return 252
        env = os.environ
        note(d, "skeleton.jsonl", {"argv": argv, "env": {
            "credentials_empty": empty(env.get("AWS_SHARED_CREDENTIALS_FILE", "")), "config_empty": empty(env.get("AWS_CONFIG_FILE", "")),
            "metadata_disabled": env.get("AWS_EC2_METADATA_DISABLED") == "true", "proxy": env.get("HTTPS_PROXY", ""),
            "aws_variables": sorted(k for k in env if k.upper().startswith("AWS_"))}})
        sys.stdout.write("{}\n")
        return 0
    account = json.loads((d / "account.json").read_text(encoding="utf-8"))
    before = json.dumps(account, sort_keys=True)
    if opts.get("--profile") != [account["profile"]] and not account.get("accept_without_profile"):
        note(d, "refused.jsonl", {"argv": argv})
        sys.stderr.write("\nUnable to locate credentials. You can configure credentials by running \"aws configure\".\n")
        return 253
    handler, writes = OPS[(service, op)]
    entry = {"argv": argv, "w": writes, "rc": 0, "code": ""}
    try:
        for fault in account.get("faults", []):
            if fault["service"] == service and fault["op"] == op and fault.get("times", 1) > 0:
                fault["times"] = fault.get("times", 1) - 1
                (d / "account.json").write_text(json.dumps(account, indent=1, sort_keys=True), encoding="utf-8")
                raise Err(fault["code"], "a fault the test planted")
        reply = handler(account, opts, out)
    except Err as e:
        entry.update(rc=252 if e.code == "ParamValidation" else 254, code=e.code)
        note(d, "log.jsonl", entry)
        sys.stderr.write("\nAn error occurred (%s) when calling the %s operation: %s\n"
                         % (e.code, "".join(p.capitalize() for p in op.split("-")), e.message))
        return entry["rc"]
    except OSError:
        sys.stderr.write("\nError parsing parameter: Unable to load paramfile\n")
        return 252
    if json.dumps(account, sort_keys=True) != before:            # a call that changed nothing writes nothing: `push` runs two at once
        (d / "account.json").write_text(json.dumps(account, indent=1, sort_keys=True), encoding="utf-8")
    late = account.get("reply_error", {}).get("%s %s" % (service, op))           # a test's plant: the service did the work and ANSWERS with an error
    if late:
        entry.update(rc=254, code=late)
        note(d, "log.jsonl", entry)
        sys.stderr.write("\nAn error occurred (%s) when calling the %s operation: the stub's words for an error that came after the work\n"
                         % (late, "".join(p.capitalize() for p in op.split("-"))))
        return 254
    note(d, "log.jsonl", entry)
    garbage = account.get("reply_garbage", {}).get("%s %s" % (service, op))      # a test's plant: the call went through, its reply is lost
    if garbage:
        sys.stdout.write(garbage + "\n")
        return 0
    dies = account.get("reply_dies", {}).get("%s %s" % (service, op))            # ... or the CLI ends with an error of its own after it
    if dies:
        sys.stderr.write("\nRead timeout on endpoint URL: the stub's words for a reply that never came\n")
        return int(dies)
    extra = account.get("reply_extra", {}).get("%s %s" % (service, op))          # what a test plants on a reply: a marker that says "more"
    if extra:
        reply = dict(reply or {}, **extra)
    if isinstance(reply, Text):
        sys.stdout.write(str(reply) + "\n")
    elif reply is not None:
        sys.stdout.write(json.dumps(reply, indent=4) + "\n")
    return 0


# ------------------------------------------------------------------------------------------------ docker, for `twinctl push`

def docker(argv):
    """Docker's stand-in (module docstring, AND DOCKER'S): exit 0 with what the command prints, or 1 with docker's kind of words."""
    d = Path(os.environ["STUB_AWS_DIR"])
    note(d, "docker.jsonl", {"argv": argv})
    account = json.loads((d / "account.json").read_text(encoding="utf-8"))
    before = json.dumps(account, sort_keys=True)
    config = None
    if argv[:1] == ["--config"]:
        config, argv = Path(argv[1]), argv[2:]
    registry = "%s.dkr.ecr.%s.amazonaws.com" % (account["account"], account["region"])
    tags = account.setdefault("docker_tags", {})
    images = account.get("docker_images", {})
    command = argv[0] if argv else ""
    if command == "save" and len(argv) == 2 and argv[1] in images:
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tf:
            for digest, blob in sorted(images[argv[1]].items()):
                data = base64.b64decode(blob)
                info = tarfile.TarInfo("blobs/sha256/" + digest.split(":", 1)[1])
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return 0
    if argv[:2] == ["image", "inspect"] and len(argv) == 3 and argv[2] in images:
        # docker's inspect of an image: its names (`docker_names`, by store ID, a test's plant; a local name otherwise) and the tags
        # `tag` gave it since
        named = list(account.get("docker_names", {}).get(argv[2], ["sdv-local/an-image:built-here"]))
        named += sorted(ref for ref, store in tags.items() if store == argv[2] and ref not in named)
        sys.stdout.write(json.dumps([{"Id": argv[2], "RepoTags": named, "Architecture": "arm64", "Os": "linux"}], indent=4) + "\n")
        return 0
    if command == "tag" and len(argv) == 3 and argv[1] in images:
        tags[argv[2]] = argv[1]
    elif command == "rmi" and len(argv) == 2 and argv[1] in tags:
        del tags[argv[1]]
    elif command == "login" and argv[1:] == ["--username", "AWS", "--password-stdin", registry] and config is not None:
        if sys.stdin.read().strip() != account["ecr_password"]:
            sys.stderr.write("Error response from daemon: login attempt failed: unauthorized\n")
            return 1
        auth = base64.b64encode(("AWS:" + account["ecr_password"]).encode()).decode()
        (config / "config.json").write_text(json.dumps({"auths": {registry: {"auth": auth}}}), encoding="utf-8")
        sys.stdout.write("Login Succeeded\n")
    elif command == "push" and len(argv) == 2 and argv[1] in tags and config is not None:
        ref = argv[1]
        try:
            auths = json.loads((config / "config.json").read_text(encoding="utf-8"))["auths"]
        except (OSError, ValueError, KeyError):
            auths = {}
        host, _slash, rest = ref.partition("/")
        name, _colon, tag = rest.rpartition(":")
        if host != registry or host not in auths:
            sys.stderr.write("denied: no basic auth credentials\n")
            return 1
        r = account.get("repositories", {}).get(name)
        if r is None or any(tag in i["imageTags"] for i in r["images"]):
            sys.stderr.write("name unknown, or tag invalid: the tag is already there and the repository is immutable\n")
            return 1
        r["images"].append({"imageDigest": account.get("push_digest", {}).get(ref, tags[ref]), "imageTags": [tag]})
        sys.stdout.write("%s: digest: pushed\n" % tag)
    else:
        sys.stderr.write("Error: the stand-in models no such docker command, or no such image\n")
        return 1
    if json.dumps(account, sort_keys=True) != before:
        (d / "account.json").write_text(json.dumps(account, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(docker(sys.argv[2:]) if sys.argv[1:2] == ["--docker"] else main(sys.argv[1:]))
