"""The leak scanner's twin shapes and the twin's redactor (scripts/aws/leakscan.py, sdv/cloud/redact.py): SDV Phase 4
WP4.

A TEST FIXTURE IS CAPTURE DATA. Every value below is a documentation value, typed by hand or taken from the
vendor's own documentation: the account 123456789012, a data endpoint whose prefix spells "example", a certificate
id that is the hex digits in order, an example.com address, the documentation's EXAMPLE ids. The PEM blocks are
built when a test runs, from a sentence that says it is no certificate, so this file holds none. The values that the
tree-side check (tests/test_no_real_identifiers.py) knows a shape for are on its allowlist; the last section holds
this file to that check.

What is held here
  1. The scanner (what a fetched or copied capture is refused for). Its six new shapes: the data endpoint, with and
     without -ats; cert/ and 64 hex characters, in an ARN too; a registry host that starts with an account id; a PEM
     block's first and last line; an e-mail address; an IAM unique id. A fake capture tree with one of each is
     flagged file by file, under the shape's own name, and the value is never printed. And what must stay unflagged,
     because flagging it would refuse every record: a sha256 that is not after cert/, a systemd unit's name (both
     are in the vss captures fetched so far), the service's own host name. A shape in a JSON key is read as in a
     value. A host glued to a hyphen (an option's value, a diff's minus) is found from where its run begins: the gap
     the endpoint's shape had is closed, and its test holds the forms that were not seen.
     Encoded text (the hard review of 2026-10-08): a block of 64 or more base64 characters is a finding, undecoded
     data, in a JSON string as in text, and a sha256, an image id, a path with one in it and a PEM block's body are
     not; a text with percent escapes is read again decoded, and what only that reading finds is named as
     percent-encoded; a terminal's colour code glued to an account id does not hide it.
  2. The redactor: literals first and the longest first, then ARNs, the endpoint with its whole host, cert/<id> and
     the scanner's other shapes, standalone 12-digit runs last. A JSON document changes in its strings only, every
     other byte kept; a PEM block goes with its body, and one that is cut short takes the rest of the text with
     it. After it the fake capture is clean by the scanner, and a sha256 is still there. What the scanner would
     still flag is refused, not written; encoded text is refused and never masked (what it holds is not seen), on
     the command line and in a copy too. A copy is all or nothing, and a write that fails takes back what was
     written. No refusal says where anything lies on the machine: a file of the source is named by its place
     inside the source, once that name itself passed the redactor, and the system's own message, which carries
     the whole path, is not passed on.
  3. The literals: a file in the state directory, read from there and from nowhere inside a work tree; its form is
     held strictly, because a file that reads as "no literals" lets every chosen name through; no error prints one.
  4. The tree side: the two new shapes are spelled as the scanner spells them, and this file's fixtures pass.
  5. Phase 6 WP4: the pull identity's two shapes, the IoT credential provider's host and a role alias's ARN, are found and
     masked whole in each form the pull side meets them (the credentials' URL, the endpoint's reply, the host's file, the
     alias's reply), by the shapes the scanner had before Phase 6; the alias's constant name stays; both docstrings say so.

Standard library and pytest. No Docker, no network, no AWS call, no credential.

Does not demonstrate: what a real reply of the account holds (no call was ever made: the shapes are the
documentation's); that a name is caught when it is not in the literals file, or is written in another case, or in
an encoding other than the two read here (a base64 block under 64 characters, the URL-safe alphabet, hex, text
encoded twice); anything about a file's name in a fetched capture, which the scanner does not read; anything
about a secret access key or a session token, which have no shape. One test here is skipped on a host that may
refuse a symbolic link (Windows) and fails, not skips, anywhere else: the recipe's skip check does not hold this
file.
"""
import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Set, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LEAKSCAN = REPO / "scripts" / "aws" / "leakscan.py"
REDACT = REPO / "sdv" / "cloud" / "redact.py"
PY = sys.executable

ACCOUNT = "123456789012"
PREFIX = "aexample000000"
ENDPOINT = "aexample000000-ats.iot.us-east-1.amazonaws.com"
ENDPOINT_PLAIN = "aexample000000.iot.us-east-1.amazonaws.com"
ENDPOINT_CRED = "aexample000000.credentials.iot.us-east-1.amazonaws.com"
CERT_ARN = "arn:aws:iot:us-east-1:123456789012:cert/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
CERT_ID = CERT_ARN.rsplit("/", 1)[1]
ECR = "123456789012.dkr.ecr.us-east-1.amazonaws.com"
EMAIL = "owner@example.com"
USER_ID = "AIDACKCEVSQ6C2EXAMPLE"          # the vendor documentation's example ids: a user's, a role's, a key's
ROLE_ID = "AROADBQP57FF2AEXAMPLE"
KEY_ID = "AKIAIOSFODNN7EXAMPLE"
CANONICAL = "fedcba9876543210" * 4         # a canonical user id has a sha256's shape: 64 hex characters
SHA = hashlib.sha256(b"not a certificate").hexdigest()
UUID = "11112222-3333-4444-5555-666677778888"
BUCKET = "example-twin-123456789012-us-east-1"
STREAM = "example-stream-" + UUID
SAID = "EXAMPLE ONLY, built by a test: not a certificate and not a key. "

LITERALS: Dict[str, Any] = {
    "account": [ACCOUNT],
    "certificate-id": [CERT_ID],
    "endpoint-prefix": [PREFIX],
    "notice-address": [EMAIL],
    "canonical-user-id": [CANONICAL],
    "thing": ["example-thing"],
    "rule": ["example_rule"],
    "bucket": [BUCKET],
    "operator": ["example-operator"],
}
# Every documentation value that must be gone from a redacted copy (the account id is checked apart: a JSON
# number may equal it and is kept).
GONE = (PREFIX, CERT_ID, ECR, EMAIL, USER_ID, ROLE_ID, KEY_ID, CANONICAL, "example-thing", "example_rule", BUCKET,
        "example-operator", "arn:aws", UUID)


def _load(name: str, path: Path) -> Any:
    """A module by its file, no bytecode written beside it."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, path
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


LS = _load("wp4_leakscan", LEAKSCAN)


@pytest.fixture(scope="module")
def rd() -> Any:
    return _load("sdv_cloud_redact", REDACT)


def pem(label: str = "CERTIFICATE") -> str:
    """A PEM block in form only: its body is base64 of a sentence that says what it is not."""
    body = base64.encodebytes((SAID * 5).encode("ascii")).decode("ascii")
    return "-----BEGIN %s-----\n%s-----END %s-----\n" % (label, body, label)


def pem_body_line() -> str:
    return base64.encodebytes((SAID * 5).encode("ascii")).decode("ascii").split("\n")[0]


def labels(text: str, is_json: bool = False, literals: Tuple[str, ...] = ()) -> Set[str]:
    return {label for label, _tok in LS.findings(text, is_json, literals)}


def _leakscan(d: Path, *literals: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run([PY, str(LEAKSCAN), str(d), *literals], capture_output=True, text=True, timeout=120)


def _leaks(stdout: str) -> Dict[str, Set[str]]:
    """{file: the shapes the scanner named in it}, from its LEAK lines."""
    out: Dict[str, Set[str]] = {}
    for line in stdout.splitlines():
        m = re.fullmatch(r"LEAK (.+?): (.+) \((\d+) chars\)", line)
        if m:
            out.setdefault(m.group(1), set()).add(m.group(2))
    return out


def raw_capture(root: Path) -> Dict[str, Set[str]]:
    """A fake tree of the account's replies, as they would lie in the state directory before redaction: one
    documentation value per new shape. Returns {file: the shapes the scanner must name in it with no literal given}."""
    files: Dict[str, Tuple[str, Set[str]]] = {
        "iot/describe-endpoint.json": (json.dumps({"endpointAddress": ENDPOINT}, indent=4) + "\n", {"iot endpoint"}),
        "iot/endpoint-plain.txt": ("mqtt to %s:8883 refused\n" % ENDPOINT_PLAIN, {"iot endpoint"}),
        "iot/endpoint-credentials.txt": ("https://%s/role-aliases\n" % ENDPOINT_CRED, {"iot endpoint"}),
        "iot/describe-certificate.json": (json.dumps({"certificateDescription": {
            "certificateArn": CERT_ARN, "certificateId": CERT_ID, "status": "INACTIVE", "ownedBy": ACCOUNT,
            "certificatePem": pem(), "creationDate": 1759600000.123}}, indent=4) + "\n", {"arn", "certificate id", "pem block"}),
        "iot/policy-targets.txt": ("target cert/%s of example_rule\n" % CERT_ID, {"certificate id"}),
        "ecr/describe-repositories.json": (json.dumps({"repositories": [
            {"repositoryUri": ECR + "/example", "registryId": ACCOUNT, "imageCount": 123456789012}]}) + "\n", {"ecr registry host"}),
        "device/key.txt": (pem("RSA PRIVATE KEY"), {"pem block"}),
        "sns/list-subscriptions.json": (json.dumps({"Subscriptions": [
            {"Protocol": "email", "Endpoint": EMAIL, "Owner": ACCOUNT}]}) + "\n", {"e-mail address"}),
        "sts/get-caller-identity.json": (json.dumps({
            "UserId": ROLE_ID + ":example-session", "Account": ACCOUNT,
            "Arn": "arn:aws:sts::123456789012:assumed-role/example-operator/example-session"}, indent=4) + "\n", {"iam unique id", "arn"}),
        "iam/ids.txt": ("user %s key %s\n" % (USER_ID, KEY_ID), {"iam unique id"}),
        "s3/owner.json": (json.dumps({"Owner": {"ID": CANONICAL}, "Buckets": [{"Name": BUCKET}]}) + "\n", set()),
        "shadow/vss.jsonl": ('{"thing": "example-thing", "version": 3}\n\n{"clientToken": "%s", "timestamp": 1759600000}\n' % UUID, {"uuid"}),
        "manifest.sha256": ("%s  iot/describe-endpoint.json\nsha256:%s\n" % (SHA, SHA), set()),
        "images.json": (json.dumps({"image_id": "sha256:" + SHA, "blob": "blobs/sha256/" + SHA}) + "\n", set()),
    }
    for rel, (text, _labels) in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    return {rel: shapes for rel, (_text, shapes) in files.items()}


def state_dir(tmp_path: Path, literals: Any = None, name: str = "state") -> Path:
    """A state directory outside every work tree, holding the literals file."""
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "literals.json").write_text(json.dumps({"v": 1, "literals": LITERALS if literals is None else literals}), encoding="utf-8")
    return d


# ============================================================ 1. the scanner's six new shapes

def test_each_new_shape_is_flagged_file_by_file_under_its_own_name_and_never_printed(tmp_path):
    want = raw_capture(tmp_path / "raw")
    r = _leakscan(tmp_path / "raw")
    assert r.returncode == 1 and "NOT publishable" in r.stdout, r.stdout
    assert _leaks(r.stdout) == {rel: shapes for rel, shapes in want.items() if shapes}
    for value in GONE + (ACCOUNT, pem_body_line()):
        assert value not in r.stdout, "the scanner printed a value"


def test_with_the_literals_every_file_that_holds_a_bare_id_is_flagged_too(tmp_path):
    """A bare certificate id, a canonical user id and an account id inside a JSON string have no shape of their own:
    the scanner names them only when it is given them."""
    raw_capture(tmp_path / "raw")
    before = _leaks(_leakscan(tmp_path / "raw").stdout)
    assert "s3/owner.json" not in before and "local literal" not in set().union(*before.values())
    values = [v for vs in LITERALS.values() for v in vs]
    r = _leakscan(tmp_path / "raw", *values)
    got = _leaks(r.stdout)
    for rel in ("s3/owner.json", "iot/describe-certificate.json", "sns/list-subscriptions.json", "sts/get-caller-identity.json",
                "ecr/describe-repositories.json", "iot/policy-targets.txt", "shadow/vss.jsonl"):
        assert "local literal" in got[rel], rel
    assert "manifest.sha256" not in got and "images.json" not in got
    assert not any(v in r.stdout for v in values)


FLAGGED = [
    ("iot endpoint", ENDPOINT),
    ("iot endpoint", ENDPOINT_PLAIN),
    ("iot endpoint", ENDPOINT_CRED),
    ("iot endpoint", ENDPOINT.upper()),
    ("iot endpoint", "wss://%s:443/mqtt" % ENDPOINT),
    ("iot endpoint", ENDPOINT_PLAIN.replace(".iot.", ".jobs.iot.")),
    ("iot endpoint", ENDPOINT.replace(".iot.", ".iot-fips.")),          # a form no page was read for: the wider net
    ("iot endpoint", ENDPOINT + ".cn"),
    ("iot endpoint", "-" + ENDPOINT),                                    # glued to a hyphen: a diff's minus, an option's value
    ("iot endpoint", "curl -h" + ENDPOINT_CRED),
    ("iot endpoint", "--endpoint-" + ENDPOINT_PLAIN),
    ("iot endpoint", "<endpoint-prefix>" + ENDPOINT[len(PREFIX):]),      # what a literal's mask leaves glued to .iot
    ("certificate id", "cert/" + CERT_ID),
    ("certificate id", CERT_ARN),
    ("certificate id", '"principal": "%s",' % CERT_ARN),
    ("certificate id", "cert/" + CERT_ID.upper()),
    ("ecr registry host", ECR + "/example:latest"),
    ("ecr registry host", "123456789012.dkr.ecr-fips.us-east-1.amazonaws.com"),
    ("pem block", "-----BEGIN CERTIFICATE-----"),
    ("pem block", "-----END RSA PRIVATE KEY-----"),
    ("pem block", pem("PRIVATE KEY").replace("\n", "\\n")),
    ("e-mail address", EMAIL),
    ("e-mail address", "write to first.last+tag@mail.example.org."),
    ("e-mail address", "<%s>" % EMAIL),
    ("e-mail address", "\\n%s\\n" % EMAIL),
    ("e-mail address", "unit@host.services.example.net"),
    ("e-mail address", "first@mail.service.example.com"),          # a unit type as a middle label is a domain
    ("e-mail address", "first@service.example.com."),
    ("e-mail address", "origin git@example.com:owner/repo.git (fetch)"),     # a git remote in its SSH form reads as one
    ("iam unique id", USER_ID),
    ("iam unique id", ROLE_ID + ":example-session"),
    ("iam unique id", KEY_ID),
    ("iam unique id", "ASIA" + KEY_ID[4:]),
]


@pytest.mark.parametrize("shape, text", FLAGGED, ids=["%s-%d" % (s.replace(" ", "-"), i) for i, (s, _t) in enumerate(FLAGGED)])
def test_the_scanner_names_the_shape(shape, text):
    assert shape in labels(text) and shape in labels(text, is_json=True)


KEPT = [
    SHA,                                              # a bare sha256: 64 hex characters, as a certificate id is
    "sha256:" + SHA,
    "%s  pub/vss-suite/run.log" % SHA,
    "blobs/sha256/" + SHA,
    "certs/" + SHA,                                   # not cert/
    "cert/" + SHA[:63],                               # 63 hex characters
    "cert/" + SHA + "0",                              # 65
    CERT_ID,                                          # the id with no cert/ before it: a literal's business
    CANONICAL,
    "getty@tty1.service",                             # the fetched vss captures hold these two, in apt's log
    "serial-getty@ttyS0.service",
    "user@1000.service and user@1000.service.d/override.conf",
    "blockdev@dev-nvme0n1p1.target dbus@1.socket user@1000.slice",
    "openvpn-client@my.vpn.service started, dhcpcd@eth0.100.service too.",     # an instance's name may hold a dot
    "ubuntu@host ran it",                             # no domain
    "iot.us-east-1.amazonaws.com",                    # the service's own host: no account's prefix
    "https://iot.us-east-1.amazonaws.com/things",
    "s3.us-east-1.amazonaws.com",
    "-iot.us-east-1.amazonaws.com",                   # the service's own host behind a hyphen is still no account's
    "--endpoint-url https://iot.us-east-1.amazonaws.com",
    "<endpoint-prefix>" + ENDPOINT_PLAIN[len(PREFIX):],     # after a literal's mask the plain form is the service's own host
    KEY_ID[:19],                                      # one character short
    KEY_ID.lower(),
    "X" + KEY_ID,                                     # inside a longer word
    "-----BEGIN-----",
    "----- BEGIN CERTIFICATE -----",
    ACCOUNT[:11] + ".dkr.ecr.us-east-1.example",      # 11 digits
    "1" + ACCOUNT + ".dkr.ecr.us-east-1.example",     # 13
]


@pytest.mark.parametrize("text", KEPT, ids=range(len(KEPT)))
def test_the_scanner_keeps_what_only_looks_like_a_twin_shape(text):
    assert LS.findings(text, False, ()) == [] and LS.findings(text, True, ()) == []


def test_a_capture_of_nothing_but_sha256_sums_and_unit_names_is_clean(tmp_path):
    """The false positive that would refuse every record: the vss captures fetched so far hold a sha256 in most of
    their files and systemd units' names in apt's log."""
    d = tmp_path / "d"
    d.mkdir()
    (d / "pub.sha256").write_text("".join("%s  f%d\n" % (hashlib.sha256(b"%d" % i).hexdigest(), i) for i in range(40)), encoding="utf-8")
    (d / "apt.log").write_text("Created symlink getty@tty1.service\nserial-getty@ttyS0.service is a disabled or a static unit\n", encoding="utf-8")
    (d / "images.json").write_text(json.dumps({"image_id": "sha256:" + SHA, "repo_digest": "example@sha256:" + SHA}), encoding="utf-8")
    r = _leakscan(d)
    assert r.returncode == 0 and "leakscan: clean" in r.stdout, r.stdout


def test_an_endpoint_is_one_finding_from_its_prefix_on_in_each_form_the_scanner_knows():
    """The finding is the host from the account's prefix on, through the credentials or the jobs label where there is
    one: the tree side lists whole hosts by it, and the length the scanner prints is the host's."""
    for host in (ENDPOINT, ENDPOINT_PLAIN, ENDPOINT_CRED, ENDPOINT_PLAIN.replace(".iot.", ".jobs.iot."),
                 ENDPOINT.replace(".iot.", ".iot-fips."), ENDPOINT_CRED.replace(".iot.", ".iot-fips.")):
        for is_json in (False, True):
            assert LS.findings("mqtts://%s:8883/" % host, is_json, ()) == [("iot endpoint", host)], host[14:]


def test_a_certificate_id_inside_an_arn_is_named_as_one_and_not_only_as_an_arn():
    for text in (CERT_ARN, "x:" + CERT_ARN, "arn:aws-cn:iot:cn-north-1:123456789012:cert/" + CERT_ID):
        found = LS.findings(text, True, ())
        assert sorted(label for label, _tok in found) == ["arn", "certificate id"], text
        assert ("certificate id", "cert/" + CERT_ID) in found


def test_a_host_glued_to_a_hyphen_is_found_from_where_its_run_begins_and_goes_whole(rd):
    """The gap the endpoint's shape had, closed (WP4-verify-2's SHOULD, carried by the hard review). The first label
    was read from a letter or digit that follows no letter, digit or hyphen, so ANY run of letters, digits and hyphens
    that began with a hyphen and ended at the host hid it: a diff's minus, a short option glued to its value, a long
    option's name. The first label is now the whole run, from where it begins. Each form is one finding that holds the
    whole host, the redactor leaves nothing of the prefix, and with the prefix a literal what the mask leaves glued
    to .iot is a finding of its own and is masked next."""
    lits = rd.Literals({"endpoint-prefix": [PREFIX]})
    fronts = ("-", "--", "=-", "\n-", "-h", "--endpoint-", "-x-", " -p8883-", "x-", "- ", "-x.", "+", "---")
    for front in fronts:
        for host in (ENDPOINT, ENDPOINT_PLAIN, ENDPOINT_CRED, ENDPOINT.upper()):
            text = front + host
            found = LS.findings(text, False, ())
            assert [label for label, _tok in found] == ["iot endpoint"], (front, host[14:])
            assert found[0][1].lower().endswith(host.lower()) and LS.findings(text, True, ()) == found, (front, host[14:])
            out = rd.redact_text(text, rd.NONE)
            assert PREFIX not in out.lower() and "amazonaws" not in out.lower() and out.endswith("<endpoint>"), (front, out)
            assert LS.findings(out, False, (PREFIX,)) == [], (front, out)
            with_literal = rd.redact_text(text, lits)
            assert PREFIX not in with_literal.lower() and LS.findings(with_literal, False, (PREFIX,)) == [], (front, with_literal)
    # the finding begins where the run of letters, digits and hyphens begins, and the redactor takes what is glued on
    assert LS.findings("curl -h" + ENDPOINT, False, ()) == [("iot endpoint", "-h" + ENDPOINT)]
    assert rd.redact_text("curl -h%s -p 8883" % ENDPOINT, rd.NONE) == "curl <endpoint> -p 8883"
    assert rd.redact_text("--- a/x\n-%s\n+other" % ENDPOINT, rd.NONE) == "--- a/x\n<endpoint>\n+other"
    # with the prefix a literal, what is left glued to .iot is itself a finding, and the redactor masks it next
    assert LS.findings("<endpoint-prefix>" + ENDPOINT[len(PREFIX):], False, ()) == [("iot endpoint", ENDPOINT[len(PREFIX):])]
    assert rd.redact_text("-h" + ENDPOINT, lits) == "-h<endpoint-prefix><endpoint>"
    # the gap is not stated any more, anywhere it was
    assert "KNOWN GAP" not in LS.__doc__ and "hyphen may begin it" in LS.__doc__


def test_the_endpoint_shape_reads_a_long_run_once(rd):
    """Guard against repeated reads of a token from each hyphen. The synthetic inputs are built to exercise
    backtracking, and a test deadline stops a pathological pattern before larger inputs can hang the run.
    The input size and deadline are test parameters; no measured runtime or scaling ratio is published here."""
    for text in ("a-" * 20000 + ".iot", "-" * 40000, "a-" * 20000 + ".iot.us-east-1.amazonaws.co",
                 ("a" * 50 + ".") * 800 + "iot.us-east-1.amazonaws.co", "-a" * 20000 + ENDPOINT[len(PREFIX):]):
        began = time.monotonic()
        found = LS.findings(text, False, ())
        took = time.monotonic() - began
        assert took < 2.0, "the scanner read %d kB built to back up for %.1f s: a pattern reads a run more than once" % (len(text) // 1000, took)
        assert len(found) <= 1
        began = time.monotonic()
        out = rd.redact_text(text, rd.NONE)
        took = time.monotonic() - began
        assert took < 4.0 and PREFIX not in out, "the redactor took %.1f s over %d kB built to back up" % (took, len(text) // 1000)


def test_a_registry_host_in_a_json_string_is_flagged_though_its_twelve_digits_alone_are_not(tmp_path):
    """The 12-digit rule passes over JSON (its numbers are counters), so in a reply the account id is seen only
    where a shape holds it; alone in a string it is a literal's business, and as a number it is a number."""
    assert labels(ECR, is_json=True) == {"ecr registry host"}
    assert labels(ACCOUNT, is_json=True) == set() and labels(ACCOUNT, is_json=True, literals=(ACCOUNT,)) == {"local literal"}
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.json").write_text(json.dumps({"n": 123456789012, "registryId": ACCOUNT}), encoding="utf-8")
    assert _leakscan(d).returncode == 0
    (d / "b.json").write_text(json.dumps({"uri": ECR + "/example"}), encoding="utf-8")
    r = _leakscan(d)
    assert r.returncode == 1 and _leaks(r.stdout) == {"b.json": {"ecr registry host"}}


def test_a_shape_in_a_json_key_is_read_as_in_a_value(tmp_path):
    """A reply may be keyed by what identifies (a map by endpoint, by address). The scanner reads a document's keys as
    it reads its values, nested ones too, in a .json file and in each line of a .jsonl file."""
    d = tmp_path / "d"
    d.mkdir()
    (d / "by-key.json").write_text(json.dumps({"targets": [{ENDPOINT: {"connected": True}}]}), encoding="utf-8")
    (d / "by-key.jsonl").write_text(json.dumps({"n": 1}) + "\n" + json.dumps({"seen": {EMAIL: 2}}) + "\n", encoding="utf-8")
    (d / "values.json").write_text(json.dumps({"connected": True, "n": 123456789012}), encoding="utf-8")
    r = _leakscan(d)
    assert r.returncode == 1 and _leaks(r.stdout) == {"by-key.json": {"iot endpoint"}, "by-key.jsonl": {"e-mail address"}}, r.stdout


def test_an_iam_unique_id_is_twenty_characters_or_more():
    """A key id is its four letters and 16 more; a user's or a role's unique id, as the documentation prints them,
    is one longer. Both are one finding, whole."""
    for value in (KEY_ID, USER_ID, ROLE_ID):
        assert LS.findings("id %s." % value, False, ()) == [("iam unique id", value)]
    assert len(KEY_ID) == 20 and len(USER_ID) == 21 and len(ROLE_ID) == 21


# ============================================================ 1b. encoded text (the hard review, 2026-10-08)

def encoded_reply() -> str:
    """base64 of a reply that names the endpoint and the account: what a function's log tail is handed back as."""
    return base64.b64encode(json.dumps({"endpointAddress": ENDPOINT, "account": ACCOUNT}).encode("ascii")).decode("ascii")


def test_a_block_of_base64_is_a_finding_in_a_json_string_and_in_text_and_a_sha256_and_an_image_id_are_not(tmp_path):
    """The counterexample: base64 of a reply that names the endpoint and the account gave no shape finding and no
    literal finding, and the redactor returned it unchanged. A planned capture carries exactly this (LogResult, a
    function's own log, beside the plain Payload). Now such a block is a finding of its own in a .json, a .jsonl and
    a text file; a file of sums and image ids beside it stays clean; and the block is never printed."""
    block = encoded_reply()
    values = [v for vs in LITERALS.values() for v in vs]
    assert len(block) >= 64 and not [v for v in values if v in block] and not [1 for label, rx in LS.PATTERNS if rx.search(block)]
    d = tmp_path / "raw"
    (d / "lambda").mkdir(parents=True)
    (d / "lambda" / "invoke.json").write_text(json.dumps({"StatusCode": 200, "LogResult": block, "ExecutedVersion": "$LATEST"}), encoding="utf-8")
    (d / "lambda" / "invoke.txt").write_text("LogResult: %s\nStatusCode: 200\n" % block, encoding="utf-8")
    (d / "lambda" / "tail.jsonl").write_text('{"n": 1}\n{"%s": "as a key"}\n' % block, encoding="utf-8")
    (d / "sums.sha256").write_text("%s  lambda/invoke.json\nsha256:%s\n%s\n" % (SHA, SHA, SHA[:12]), encoding="utf-8")
    (d / "inspect.json").write_text(json.dumps({
        "Id": "sha256:" + SHA, "Image": SHA, "RepoDigests": ["example@sha256:" + SHA], "sha512": SHA + SHA,
        "GraphDriver": {"Data": {"MergedDir": "/var/lib/docker/overlay2/%s/merged" % SHA, "UpperDir": "/var/lib/docker/overlay2/%s/diff" % SHA}},
        "LogPath": "/var/lib/docker/containers/%s/%s-json.log" % (SHA, SHA), "CodeSha256": base64.b64encode(bytes(range(32))).decode("ascii")}),
        encoding="utf-8")
    r = _leakscan(d, *values)
    assert r.returncode == 1, r.stdout
    assert _leaks(r.stdout) == {"lambda/invoke.json": {"undecoded data"}, "lambda/invoke.txt": {"undecoded data"},
                                "lambda/tail.jsonl": {"undecoded data"}}, r.stdout
    assert block not in r.stdout and block[:20] not in r.stdout and "(%d chars)" % len(block) in r.stdout


ENCODED = [
    "x" * 64,                                         # 64 letters in a row are no word and no hex
    "QUJD" * 16,                                      # the shortest block that counts: 64 characters, no padding
    "QUJD" * 20 + "QQ==",                             # padded
    "0123456789abcdef" * 4 + "==",                    # hex digits alone, but padded: no sum is written so
    "Q" * 40 + "/" + "z" * 40,                        # a slash in it, and a part of more than 32 characters that is no hex
    "Ab1/" * 20 + "Q=",                               # short parts, but padded
    "x=" + "QUJD" * 16 + ";",                         # after a = and before a ;
    "/9j/" + "4AAQSkZJRgABAQ" * 8,                    # a block that begins with a slash, as base64 of an image does
]
NOT_ENCODED = [
    "x" * 63,                                         # one short
    SHA, SHA.upper(), SHA + SHA, "0" * 200,           # hex alone, however long: a sum, an id, a run of zeros
    "sha256:" + SHA, "blobs/sha256/" + SHA,
    "/var/lib/docker/overlay2/%s/merged" % SHA,       # a path with an image's layer in it: every part is hex or a word
    "/var/lib/docker/overlay2/%s/diff/usr/share/zoneinfo/right/America/Argentina/ComodRivadavia" % SHA,
    "/sys/devices/platform/soc/subsystem/devices/platform/soc/subsystem/devices/platform",          # 64 and more, all short parts
    "A" * 40 + "/" + "b" * 40,                        # parts of more than 32 characters, each of hex digits alone
    "Q" * 32 + "/" + "z" * 32,                        # parts of exactly 32
    base64.b64encode(bytes(range(32))).decode("ascii"),          # a sha256 in base64, as a function's CodeSha256: 44 characters
    "QUJD" * 15 + "QUJ-" + "QUJD" * 15,               # the URL-safe alphabet breaks a run: not seen (stated in the scanner)
    "snake_case_names_" * 8,
]


@pytest.mark.parametrize("text", ENCODED, ids=range(len(ENCODED)))
def test_the_scanner_names_a_run_of_base64_as_undecoded_data(text):
    for is_json in (False, True):
        found = LS.findings(text, is_json, ())
        assert [label for label, _tok in found] == ["undecoded data"] and found[0][1] in text and len(found[0][1]) >= 64


@pytest.mark.parametrize("text", NOT_ENCODED, ids=range(len(NOT_ENCODED)))
def test_the_scanner_keeps_what_only_looks_like_encoded_data(text):
    assert LS.findings(text, False, ()) == [] and LS.findings(text, True, ()) == []


def test_a_pem_blocks_body_is_no_undecoded_data_and_a_body_without_its_first_line_is(rd):
    """A PEM block is a finding by its edges and goes whole; naming its body again would only double the count. A
    block cut short at its end is read the same way (what follows the first line is its body); a body whose first
    line is missing is base64 with nothing to say what it is, and is named."""
    body = pem_body_line()
    assert len(body) >= 64
    assert labels(pem()) == {"pem block"} and labels("x\n" + pem() + "y\n" + pem("RSA PRIVATE KEY")) == {"pem block"}
    assert labels(pem().replace("\n", "\\n")) == {"pem block"}                       # a reply saved as text, newlines still escaped
    assert labels("-----BEGIN CERTIFICATE-----\n%s\n%s\n" % (body, body)) == {"pem block"}
    assert labels("%s\n-----END CERTIFICATE-----\n" % body) == {"pem block", "undecoded data"}
    assert labels(pem() + body + "\n") == {"pem block", "undecoded data"}             # after a whole block: outside it
    assert rd.redact_text("a\n" + pem() + "b\n", rd.NONE) == "a\n<pem>\nb\n"
    assert rd.redact_text("%s\n-----END CERTIFICATE-----\nafter\n" % body, rd.NONE) == "<pem-cut>\nafter\n"


def test_the_redactor_refuses_encoded_text_and_masks_nothing_of_it(rd, tmp_path):
    """A refusal, not a mask: what a block holds is not seen by any rule, and a mask in its place would call the copy
    clean. Nothing is given out, in a text, in a JSON document, in a copy (which names the file by its place inside
    the source and writes none) or on the command line; and no refusal repeats the block."""
    block = encoded_reply()
    state = state_dir(tmp_path)
    lits = rd.load_literals(state)
    for call in (lambda: rd.redact_text("LogResult: %s" % block, lits), lambda: rd.redact_text(block, rd.NONE),
                 lambda: rd.redact_json(json.dumps({"LogResult": block}), lits),
                 lambda: rd.redact_json(json.dumps({block: 1}), lits),
                 lambda: rd.redact_jsonl('{"a": 1}\n{"LogResult": "%s"}\n' % block, lits),
                 lambda: rd.redact_named("invoke.json", json.dumps({"LogResult": block}).encode("ascii"), lits)):
        with pytest.raises(rd.RedactError) as e:
            call()
        assert "undecoded data" in str(e.value) and "not masked" in str(e.value) and block[:16] not in str(e.value)
    # the Payload beside it, plain, goes through; and so does a reply whose only long run is a sum
    assert rd.redact_json(json.dumps({"StatusCode": 200, "Payload": {"account": ACCOUNT}}), lits) == json.dumps(
        {"StatusCode": 200, "Payload": {"account": "<account>"}})
    assert rd.redact_text("CodeSha256 %s image sha256:%s" % (base64.b64encode(bytes(range(32))).decode("ascii"), SHA), lits).endswith(SHA)
    raw, cap = tmp_path / "raw", tmp_path / "cap"
    raw_capture(raw)
    (raw / "lambda").mkdir()
    (raw / "lambda" / "invoke.json").write_text(json.dumps({"StatusCode": 200, "LogResult": block}), encoding="utf-8")
    with pytest.raises(rd.RedactError) as e:
        rd.copy_tree(raw, cap, lits)
    assert str(e.value).startswith("lambda/invoke.json: ") and "undecoded data" in str(e.value) and not cap.exists()
    r = _cli("--state", str(state), "filter", data=("LogResult: %s\n" % block).encode("ascii"))
    assert r.returncode == 2 and r.stdout == b"" and b"undecoded data" in r.stderr and block[:16].encode("ascii") not in r.stderr
    assert r.stderr.startswith(b"redact: ") and len(r.stderr.splitlines()) == 1
    r = _cli("--state", str(state), "copy", str(raw), str(cap))
    assert r.returncode == 2 and r.stdout == b"" and not cap.exists() and b"lambda/invoke.json" in r.stderr
    r = _cli("--state", str(state), "scan", str(raw))
    assert r.returncode == 1 and b"LEAK lambda/invoke.json: undecoded data" in r.stdout


def test_a_block_is_refused_as_it_came_in_before_a_literals_mask_could_cut_it_in_two(rd):
    """Literals go first. A block that happens to hold a literal's characters would be cut by the mask into two runs,
    each under 64 characters, and the scanner would see neither: the block would go out with a mask in its middle. So
    encoded data is looked for in the text as it came in. A block that lies wholly inside a literal is that literal
    and goes under its kind."""
    half = "QUJD" * 12
    block = half + "Zm9v" + half
    lits = rd.Literals({"thing": ["Zm9v"]})
    assert labels(block) == {"undecoded data"} and labels(block.replace("Zm9v", "<thing>")) == set()          # what the mask would leave
    for text in (block, "LogResult: %s." % block, "\x1b[0m" + block):
        with pytest.raises(rd.RedactError) as e:
            rd.redact_text(text, lits)
        assert "undecoded data" in str(e.value) and "QUJD" not in str(e.value)
    with pytest.raises(rd.RedactError):
        rd.redact_json(json.dumps({"LogResult": block}), lits)
    assert rd.redact_text("a thing called Zm9v", lits) == "a thing called <thing>"
    whole = rd.Literals({"token": [block], "session": ["x-" + block + "-y"]})
    assert rd.redact_text("token %s." % block, whole) == "token <token>."
    assert rd.redact_text("session x-%s-y." % block, whole) == "session <session>."
    with pytest.raises(rd.RedactError):
        rd.redact_text("token %s." % (block + "QUJD"), whole)          # longer than the literal: not that literal


def test_what_only_a_reading_with_percent_escapes_decoded_finds_is_named_so_and_refused(rd):
    """Percent-encoded identifiers had no shape: an ARN written with %3A and %2F gave no finding at all, an address
    written with %40 none either. A text that holds escapes is now read a second time decoded; what the plain
    reading found is not said twice; and the redactor refuses what only the decoded reading shows."""
    arn = urllib.parse.quote(CERT_ARN, safe="")
    mail = EMAIL.replace("@", "%40")
    assert "%3A" in arn and "%2F" in arn and "%40" in mail
    assert labels(arn) == {"percent-encoded arn", "percent-encoded certificate id", "percent-encoded 12-digit number"}
    assert LS.shapes(arn, False, ()) == [] and LS.shapes(mail, False, (EMAIL,)) == []          # the plain reading sees neither
    assert labels(arn, is_json=True) == {"percent-encoded arn", "percent-encoded certificate id"}
    assert labels("notify " + mail) == {"percent-encoded e-mail address"}
    assert labels("notify " + mail, literals=(EMAIL,)) == {"percent-encoded e-mail address", "percent-encoded local literal"}
    # (an escape's two hex digits are letters and digits too: glued to the host they are part of the plain reading's
    # finding, and the decoded reading finds the host itself)
    assert labels(urllib.parse.quote("https://%s/things" % ENDPOINT, safe="")) == {"iot endpoint", "percent-encoded iot endpoint"}
    assert Counter(label for label, _tok in LS.findings("to%20" + ENDPOINT, False, ())) == {"iot endpoint": 1, "percent-encoded iot endpoint": 1}
    # beside the same thing written plainly: each reading's own findings, none twice
    both = Counter(label for label, _tok in LS.findings("%s and %s" % (CERT_ARN, arn), False, ()))
    assert both == {"arn": 1, "certificate id": 1, "12-digit number": 1, "percent-encoded arn": 1,
                    "percent-encoded certificate id": 1, "percent-encoded 12-digit number": 1}
    # a percent sign that is no escape, and escapes with nothing behind them, change nothing
    for kept in ("100% done", "50%25 of 20%20files, a%2Fb", "p50 is 12%; %zz and %4", "GET /things?name=a%20b%2Fc"):
        assert LS.findings(kept, False, ()) == [] and rd.redact_text(kept, rd.NONE) == kept
    for text in ("policy " + arn, "notify " + mail, "%s and %s" % (CERT_ARN, arn)):
        with pytest.raises(rd.RedactError) as e:
            rd.redact_text(text, rd.NONE)
        assert "percent-encoded" in str(e.value) and "not masked" in str(e.value) and "example" not in str(e.value)
    with pytest.raises(rd.RedactError):
        rd.redact_json(json.dumps({"PolicyDocument": arn}), rd.NONE)


def test_a_terminals_colour_code_does_not_hide_an_account_id(rd):
    """A colour code glued in front of twelve digits ended in a letter, and the 12-digit rule took the run for part
    of a word. The codes are taken out before anything is looked for, by the scanner and by the redactor."""
    green, off = "\x1b[32m", "\x1b[0m"
    assert labels(green + ACCOUNT + off) == {"12-digit number"}
    assert LS.findings("%s%s%s done" % (green, ECR, off), False, ()) == LS.findings(ECR + " done", False, ()) != []
    assert rd.redact_text("owner %s%s%s\n" % (green, ACCOUNT, off), rd.NONE) == "owner <account>\n"
    assert rd.redact_text("\x1b[1;31m%s\x1b[0m" % ENDPOINT, rd.NONE) == "<endpoint>"
    doc = json.dumps({"line": "%s%s%s" % (green, ACCOUNT, off), "n": 123456789012})
    assert rd.redact_json(doc, rd.NONE) == json.dumps({"line": "<account>", "n": 123456789012})
    plain = "no code here: [32m is five characters, and 0.100123456789 a number"
    assert rd.redact_text(plain, rd.NONE) == plain and LS.findings(plain, False, ()) == []


def test_a_literal_goes_wherever_its_characters_stand_because_a_word_boundary_would_keep_a_prefix_glued_by_an_underscore(rd):
    """The hard review's NIT, and the choice made for it. A literal is taken out as a substring, by the scanner and by
    the redactor: a chosen name that is a common word is cut out of every record that says it, and a short one out
    of a longer token. The review offered a word boundary for short literals ((?<![A-Za-z0-9_])lit(?![A-Za-z0-9_])).
    It is NOT taken: the names of one deployment are made from one prefix, glued on with an underscore or a letter,
    and behind such a boundary the prefix would stay in every one of them that is not itself a literal. A value kept
    by mistake is a leak; a record cut too much is a nuisance that shows. Which values may be literals is settled where
    the file is written (the driver, WP6: it refuses a short or a common one); redact.py's docstring says both."""
    prefix = "exampletwin"                                   # a chosen prefix: 11 characters, under the review's 12
    lits = rd.Literals({"prefix": [prefix]})
    made_from_it = "rule %s_telemetry role %sOperator bucket %s-archive stream x%s9" % (prefix, prefix, prefix, prefix)
    assert rd.redact_text(made_from_it, lits) == "rule <prefix>_telemetry role <prefix>Operator bucket <prefix>-archive stream x<prefix>9"
    assert [label for label, _tok in LS.findings(made_from_it, False, (prefix,))] == ["local literal"]
    assert LS.findings("the scanner sees it in a JSON string too: %s_rule" % prefix, True, (prefix,)) == [("local literal", prefix)]
    # the boundary the review offered keeps the prefix in three of those four names: what is not taken, and why
    bounded = re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(prefix))
    assert bounded.sub("<prefix>", made_from_it).count(prefix) == 3
    # THE PRICE, as the docstring has it: a common word that is a literal is cut out of every record that says it ...
    common = rd.Literals({"rule": ["telemetry"]})
    line = '{"event":"batch","what":"telemetry","rows":60}'
    assert rd.redact_json(line, common) == '{"event":"batch","what":"<rule>","rows":60}'
    assert labels(line, is_json=True, literals=("telemetry",)) == {"local literal"}          # and the unredacted log is flagged
    # ... and twelve digits that are a literal out of a digest that happens to hold them
    digest = "sha256:a3f%s4bc0de" % ACCOUNT
    assert rd.redact_text(digest, rd.Literals({"account": [ACCOUNT]})) == "sha256:a3f<account>4bc0de"
    assert rd.redact_text(digest, rd.NONE) == digest and labels(digest) == set()          # by its shape alone it is no account id
    doc = " ".join(rd.__doc__.split())
    assert "A LITERAL IS TAKEN OUT WHEREVER ITS CHARACTERS STAND" in doc and "a word boundary here would miss a prefix glued" in doc
    assert "the driver refuses a short or common one (WP6)" in doc


# ============================================================ 2. the redactor

def test_the_redactor_is_standard_library_only_and_reads_the_scanners_own_patterns(rd):
    import ast
    tree = ast.parse(REDACT.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= set(sys.stdlib_module_names) | {"__future__"}, names
    assert Path(rd.SCANNER.__file__).resolve() == LEAKSCAN.resolve()
    assert [label for label, _rx in rd.SCANNER.PATTERNS] == [label for label, _rx in LS.PATTERNS]


def test_literals_go_first_and_the_longest_first(rd):
    lits = rd.Literals({"thing": ["example-thing", "example-thing-2"], "account": [ACCOUNT], "bucket": [BUCKET],
                        "notice-address": [EMAIL], "stream": [STREAM]})
    assert rd.redact_text("thing example-thing-2 and example-thing", lits) == "thing <thing> and <thing>"
    # a bucket named after the account: the longer literal wins, so nothing of the name is left around the id
    assert rd.redact_text("s3://%s/twin/ owned by %s" % (BUCKET, ACCOUNT), lits) == "s3://<bucket>/twin/ owned by <account>"
    # a chosen name that ends in something a shape would take: masked whole, by its own kind
    assert rd.redact_text("stream %s ACTIVE" % STREAM, lits) == "stream <stream> ACTIVE"
    assert rd.redact_text("notify %s" % EMAIL, lits) == "notify <notice-address>"
    assert rd.redact_text("notify %s" % EMAIL, rd.NONE) == "notify <e-mail>"


def test_then_arns_the_endpoint_the_certificate_and_the_other_shapes(rd):
    lits = rd.Literals({"thing": ["example-thing"]})
    assert rd.redact_text(CERT_ARN, rd.NONE) == "<arn>"
    assert rd.redact_text('"Resource": ["%s", "arn:aws:iot:us-east-1:123456789012:thing/example-thing"] and example-thing' % CERT_ARN,
                          lits) == '"Resource": ["<arn>", "<arn>"] and <thing>'
    assert rd.redact_text("wss://%s:443/mqtt" % ENDPOINT, rd.NONE) == "wss://<endpoint>:443/mqtt"
    assert rd.redact_text("%s %s" % (ENDPOINT_PLAIN, ENDPOINT_CRED), rd.NONE) == "<endpoint> <endpoint>"
    # the prefix goes with the host in every form: nothing of it is left in front of the mask
    for host in (ENDPOINT_PLAIN.replace(".iot.", ".jobs.iot."), ENDPOINT.replace(".iot.", ".iot-fips."),
                 ENDPOINT_CRED.replace(".iot.", ".iot-fips."), ENDPOINT.upper()):
        assert rd.redact_text("to %s:8883" % host, rd.NONE) == "to <endpoint>:8883", host[14:]
    # and the host goes whole, whatever of it the scanner's match leaves out: labels in front of the label next to
    # iot (a host with one label more leaves the prefix there), and a .cn after .com
    for host in (ENDPOINT_PLAIN.replace(".iot.", ".ats.iot."), ENDPOINT_PLAIN.replace(".iot.", ".ats.iot.") + ".cn", ENDPOINT + ".cn",
                 "a.b." + ENDPOINT, ENDPOINT_CRED.upper() + ".CN"):
        assert rd.redact_text("to %s:8883, then to %s." % (host, host), rd.NONE) == "to <endpoint>:8883, then to <endpoint>.", host[14:]
    assert rd.redact_text("to %s.cnx and %s.cn-east" % (ENDPOINT, ENDPOINT), rd.NONE) == "to <endpoint>.cnx and <endpoint>.cn-east"
    assert rd.redact_text("principal cert/%s attached" % CERT_ID, rd.NONE) == "principal cert/<certificate-id> attached"
    assert rd.redact_text("%s/example:latest" % ECR, rd.NONE) == "<ecr-host>/example:latest"
    assert rd.redact_text("UserId %s:example-session, key %s" % (ROLE_ID, KEY_ID), rd.NONE) == "UserId <iam-id>:example-session, key <iam-id>"
    # an address goes whole, its tag too; a git remote in its SSH form has an address's form and loses its host
    assert rd.redact_text("write to first.last+tag@mail.example.org.", rd.NONE) == "write to <e-mail>."
    assert rd.redact_text("origin git@example.com:owner/repo.git (fetch)", rd.NONE) == "origin <e-mail>:owner/repo.git (fetch)"
    assert rd.redact_text("i-0123456789abcdef0 at 203.0.113.7 req %s mac 0a:1b:2c:3d:4e:5f v6 2001:db8::1 host ip-10-0-0-5" % UUID,
                          rd.NONE) == "<resource-id> at <ip> req <uuid> mac <mac> v6 <ipv6> host <host>"
    kept = "192.168.100.10 127.0.0.1 52:54:00:11:11:11 fe80::5054:ff:fe11:1111 at 13:20:34 on 6.2.0 from ami-02153ae97d7504246"
    assert rd.redact_text(kept, rd.NONE) == kept


def test_with_the_endpoints_prefix_a_literal_the_prefix_is_what_goes(rd):
    lits = rd.Literals({"endpoint-prefix": [PREFIX]})
    out = rd.redact_text("endpoint %s" % ENDPOINT, lits)
    assert out == "endpoint <endpoint-prefix><endpoint>" and LS.findings(out, False, (PREFIX,)) == []
    # the credentials host is an endpoint from that label on: its mask stands after the prefix's, the dot between them
    assert rd.redact_text("https://%s/role-aliases" % ENDPOINT_CRED, lits) == "https://<endpoint-prefix>.<endpoint>/role-aliases"
    # the plain form keeps what the service's own host of that region is: the region is no identifier here
    plain = rd.redact_text("mqtt to %s:8883" % ENDPOINT_PLAIN, lits)
    assert plain == "mqtt to <endpoint-prefix>%s:8883" % ENDPOINT_PLAIN[len(PREFIX):] and LS.findings(plain, False, (PREFIX,)) == []


def test_standalone_twelve_digit_runs_go_last_and_a_run_inside_a_longer_token_stays(rd):
    assert rd.redact_text("the account is 123456789012.", rd.NONE) == "the account is <account>."
    assert rd.redact_text("owner (444455556666) and 111122223333, then", rd.NONE) == "owner (<account>) and <account>, then"
    for kept in ("p50 0.100123456789", "value 123456789012.75 ms", "x000000000000000000000000", "n 123456789012123456789012,",
                 "ab123456789012cd", SHA):
        assert rd.redact_text(kept, rd.NONE) == kept
    # last: the registry host goes whole, where the 12-digit rule first would leave a host with a mask in front of it
    assert rd.redact_text("pull %s/example" % ECR, rd.NONE) == "pull <ecr-host>/example"


def test_a_sha256_that_is_not_after_cert_is_kept_and_a_bare_certificate_id_goes_only_as_a_literal(rd):
    text = "%s  pub/run.log\nimage sha256:%s\nid %s\nowner %s\n" % (SHA, SHA, CERT_ID, CANONICAL)
    assert rd.redact_text(text, rd.NONE) == text
    doc = json.dumps({"image_id": "sha256:" + SHA, "certificateId": CERT_ID})
    assert rd.redact_json(doc, rd.NONE) == doc
    lits = rd.Literals({"certificate-id": [CERT_ID], "canonical-user-id": [CANONICAL]})
    assert rd.redact_text(text, lits) == "%s  pub/run.log\nimage sha256:%s\nid <certificate-id>\nowner <canonical-user-id>\n" % (SHA, SHA)
    assert rd.redact_json(doc, lits) == json.dumps({"image_id": "sha256:" + SHA, "certificateId": "<certificate-id>"})


def test_a_pem_block_goes_with_its_body(rd):
    body = pem_body_line()
    assert len(body) > 60
    out = rd.redact_text("before\n%safter\n" % pem(), rd.NONE)
    assert out == "before\n<pem>\nafter\n" and body not in out
    two = rd.redact_text(pem() + "between\n" + pem("RSA PRIVATE KEY"), rd.NONE)
    assert two == "<pem>\nbetween\n<pem>\n"
    # as a reply holds it, inside a JSON string; and that reply saved as text, its newlines still escaped
    doc = json.dumps({"certificatePem": pem(), "status": "ACTIVE"})
    assert rd.redact_json(doc, rd.NONE) == json.dumps({"certificatePem": "<pem>\n", "status": "ACTIVE"})
    assert rd.redact_text(doc, rd.NONE) == '{"certificatePem": "<pem>\\n", "status": "ACTIVE"}'


def test_a_pem_block_cut_short_takes_the_rest_with_it(rd):
    """A first line with no last line: what follows is key material with nothing to mark its end, so all of it goes.
    A last line with no first line: the same, for what comes before it."""
    body = pem_body_line()
    cut = "before\n-----BEGIN RSA PRIVATE KEY-----\n%s\n%s\n" % (body, body)
    assert rd.redact_text(cut, rd.NONE) == "before\n<pem-cut>"
    tail = "%s\n%s\n-----END CERTIFICATE-----\nafter\n" % (body, body)
    assert rd.redact_text(tail, rd.NONE) == "<pem-cut>\nafter\n"
    crossed = "a\n-----BEGIN CERTIFICATE-----\n%s\n-----END RSA PRIVATE KEY-----\nb\n" % body
    out = rd.redact_text(crossed, rd.NONE)
    assert body not in out and "-----" not in out and out.startswith("a\n")
    mixed = rd.redact_text("x\n%s%s\n-----END CERTIFICATE-----\ny\n" % (pem(), body), rd.NONE)
    assert mixed == "<pem-cut>\ny\n"


def test_a_json_document_changes_in_its_strings_only(rd):
    lits = rd.Literals({"account": [ACCOUNT], "thing": ["example-thing"]})
    text = ('{\n    "n": 123456789012,\n    "f": 0.100123456789,\n    "big": 1.0e3,\n\t"s": "account 123456789012",\n'
            '    "arn:aws:iot:us-east-1:123456789012:thing/example-thing": [1, 2.50, true, null, "444455556666"],\n'
            '    "\u540d": "\u503c example-thing",\n    "esc": "\\u540d example-thing \\" \\\\ \\n"\n}\n')
    want = ('{\n    "n": 123456789012,\n    "f": 0.100123456789,\n    "big": 1.0e3,\n\t"s": "account <account>",\n'
            '    "<arn>": [1, 2.50, true, null, "<account>"],\n'
            '    "\u540d": "\u503c <thing>",\n    "esc": "\\u540d <thing> \\" \\\\ \\n"\n}\n')
    assert rd.redact_json(text, lits) == want
    counters = json.dumps({"halt_wait_ns": 666677778888, "t_ns": 912345678901, "x": [123456789012, 1.5]})
    assert rd.redact_json(counters, lits) == counters           # a number that equals the account id is a number
    # a string with nothing to redact keeps its own spelling, escapes and all; one that changes is written anew
    spelled = '{"path": "a\\/b", "\\u0041": "\\u00e9t\\u00e9 \\ud83d\\ude00", "t": "\\u0041 example-thing"}'
    assert rd.redact_json(spelled, lits) == '{"path": "a\\/b", "\\u0041": "\\u00e9t\\u00e9 \\ud83d\\ude00", "t": "A <thing>"}'


def test_a_json_document_that_does_not_parse_or_whose_keys_fall_together_is_refused(rd):
    with pytest.raises(rd.RedactError) as e:
        rd.redact_json('{"thing": "example-thing", <account>}', rd.NONE)
    assert "example-thing" not in str(e.value)
    two = json.dumps({"arn:aws:iot:us-east-1:123456789012:thing/a": 1, "arn:aws:iot:us-east-1:123456789012:thing/b": 2})
    with pytest.raises(rd.RedactError) as e:
        rd.redact_json(two, rd.NONE)
    assert "key" in str(e.value) and "thing/a" not in str(e.value)
    already = '{"a": 1, "a": 2, "t": "example-thing"}'          # a key the reply itself repeats is not the redactor's doing
    assert rd.redact_json(already, rd.Literals({"thing": ["example-thing"]})) == '{"a": 1, "a": 2, "t": "<thing>"}'


def test_a_string_no_utf8_file_can_hold_is_refused_not_a_crash(rd):
    """A lone surrogate, spelled as an escape beside a character that is not ASCII: once the string changes it is
    written anew, unescaped as its neighbour was, and that cannot be encoded. Refused like anything else that cannot
    be copied; left alone, the token keeps its own spelling and the document goes through."""
    lits = rd.Literals({"thing": ["example-thing"]})
    odd = '{"k": "\\ud800 é example-thing"}'
    with pytest.raises(rd.RedactError) as e:
        rd.redact_named("reply.json", odd.encode("utf-8"), lits)
    assert "example-thing" not in str(e.value) and "UTF-8" in str(e.value)
    kept = '{"k": "\\ud800 é nothing of it"}'
    assert rd.redact_named("reply.json", kept.encode("utf-8"), lits) == kept.encode("utf-8")
    ascii_only = '{"k": "\\ud800 example-thing"}'
    assert rd.redact_named("reply.json", ascii_only.encode("utf-8"), lits) == b'{"k": "\\ud800 <thing>"}'


def test_jsonl_is_the_json_rule_line_by_line(rd):
    lits = rd.Literals({"thing": ["example-thing"]})
    text = '{"thing": "example-thing", "n": 123456789012}\n\n{"clientToken": "%s"}\n' % UUID
    assert rd.redact_jsonl(text, lits) == '{"thing": "<thing>", "n": 123456789012}\n\n{"clientToken": "<uuid>"}\n'
    assert rd.redact_jsonl('{"a": 1}', lits) == '{"a": 1}'                       # no newline at the end: none added
    with pytest.raises(rd.RedactError) as e:
        rd.redact_jsonl('{"a": 1}\n{"thing": "example-thing"\n', lits)
    assert "line 2" in str(e.value) and "example-thing" not in str(e.value)


SAMPLES = {
    "aws resource id": "vol-0abcdef1234567890",
    "arn": CERT_ARN,
    "ec2 host name": "ip-10-0-0-5",
    "uuid": UUID,
    "iot endpoint": ENDPOINT,
    "certificate id": "cert/" + CERT_ID,
    "ecr registry host": ECR,
    "pem block": pem().rstrip("\n"),
    "e-mail address": EMAIL,
    "iam unique id": USER_ID,
}


def test_every_shape_the_scanner_knows_is_masked(rd):
    """One sample per shape of the scanner's list, and the list is held whole: a shape added to the scanner with no
    sample here fails, as it fails the redactor's own check below."""
    assert set(SAMPLES) == {label for label, _rx in LS.PATTERNS}
    for shape, sample in SAMPLES.items():
        text = "before %s after" % sample
        assert shape in labels(text), shape
        out = rd.redact_text(text, rd.NONE)
        assert LS.findings(out, False, ()) == [], shape
        assert out.startswith(("before <", "before cert/<")) and out.endswith("> after"), shape


def test_a_shape_that_a_mask_uncovers_is_masked_in_a_further_pass(rd):
    """64 hex characters after cert/ with a key id glued on are no certificate id (a 65th hex character follows) until
    the key id is a mask. One pass would leave what the scanner then refuses; the order is applied again."""
    glued = "cert/%s%s" % (CERT_ID, "203.0.113.7")          # (glued to an address: its first digit is a 65th hex character)
    assert labels(glued) == {"ipv4"}
    assert labels(rd._once(glued, rd.NONE)) == {"certificate id"}
    assert rd.redact_text(glued, rd.NONE) == "cert/<certificate-id><ip>"
    # Glued to a key id instead, the 64 hex characters and the id are one run of 84 letters and digits: encoded data to
    # the scanner. The redactor refuses that as it came in, before a mask could take the run apart.
    run = "cert/%s%s" % (CERT_ID, KEY_ID)
    assert labels(run) == {"iam unique id", "undecoded data"}
    with pytest.raises(rd.RedactError) as e:
        rd.redact_text(run, rd.NONE)
    assert "undecoded data" in str(e.value) and KEY_ID not in str(e.value)
    assert rd.redact_text("a\r\nthe account is 123456789012\r\n", rd.NONE) == "a\r\nthe account is <account>\r\n"


def test_a_shape_the_redactor_has_no_mask_for_is_refused_not_passed(rd, monkeypatch):
    rd.check_shapes()
    for stray in ("no such shape", "pem block"):  # a head for anything but a masked shape would be a silent no-op
        with monkeypatch.context() as m:
            m.setitem(rd.HEADS, stray, "")
            with pytest.raises(rd.RedactError) as e:
                rd.check_shapes()
            assert stray in str(e.value)
    rd.check_shapes()
    assert set(rd.HEADS) == {"iot endpoint"}
    monkeypatch.setattr(rd.SCANNER, "PATTERNS", list(rd.SCANNER.PATTERNS) + [("a new shape", re.compile(r"ZZ[0-9]{6}"))])
    with pytest.raises(rd.RedactError) as e:
        rd.check_shapes()
    assert "a new shape" in str(e.value)
    with pytest.raises(rd.RedactError) as e:
        rd.redact_text("id ZZ123456 here", rd.NONE)
    assert "a new shape" in str(e.value) and "ZZ123456" not in str(e.value)
    assert rd.redact_text("nothing of it here", rd.NONE) == "nothing of it here"


def test_the_fake_capture_is_clean_after_the_redactor_and_its_sums_are_still_there(rd, tmp_path):
    raw, cap = tmp_path / "raw", tmp_path / "cap"
    raw_capture(raw)
    lits = rd.load_literals(state_dir(tmp_path))
    assert _leakscan(raw, *lits.values).returncode == 1
    done = rd.copy_tree(raw, cap, lits)
    rels = sorted(str(p.relative_to(raw)).replace(os.sep, "/") for p in raw.rglob("*") if p.is_file())
    copied = sorted(str(p.relative_to(cap)).replace(os.sep, "/") for p in cap.rglob("*") if p.is_file())
    assert sorted(rel for rel, _changed in done) == rels == copied
    assert {rel for rel, changed in done if not changed} == {"manifest.sha256", "images.json"}
    for rel in ("manifest.sha256", "images.json"):
        assert (cap / rel).read_bytes() == (raw / rel).read_bytes()
    assert rd.scan(cap, lits) == []
    r = _leakscan(cap, *lits.values)
    assert r.returncode == 0 and "leakscan: clean" in r.stdout, r.stdout
    body = pem_body_line()
    for p in cap.rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            assert not [v for v in GONE + (body, "-----BEGIN", "-----END") if v in text], p.name
            if p.suffix == ".json":
                json.loads(text)
    # the account id is gone from every string; the one number that equals it is still a number
    assert ACCOUNT not in "".join(p.read_text(encoding="utf-8") for p in cap.rglob("*") if p.is_file() and p.name != "describe-repositories.json")
    assert json.loads((cap / "ecr/describe-repositories.json").read_text(encoding="utf-8")) == {
        "repositories": [{"repositoryUri": "<account>.dkr.ecr.us-east-1.amazonaws.com/example", "registryId": "<account>",
                          "imageCount": 123456789012}]}       # the literal went first: the host is left without its account
    assert json.loads((cap / "sts/get-caller-identity.json").read_text(encoding="utf-8")) == {
        "UserId": "<iam-id>:example-session", "Account": "<account>", "Arn": "<arn>"}
    assert json.loads((cap / "iot/describe-certificate.json").read_text(encoding="utf-8"))["certificateDescription"] == {
        "certificateArn": "<arn>", "certificateId": "<certificate-id>", "status": "INACTIVE", "ownedBy": "<account>",
        "certificatePem": "<pem>\n", "creationDate": 1759600000.123}
    assert (cap / "iot/policy-targets.txt").read_text(encoding="utf-8") == "target cert/<certificate-id> of <rule>\n"
    assert (cap / "device/key.txt").read_text(encoding="utf-8") == "<pem>\n"


def test_a_copy_is_all_or_nothing(rd, tmp_path):
    """A destination that holds something, a file that is not UTF-8, a JSON file that does not parse and a file whose
    own name holds an identifier each refuse the copy, and nothing is written."""
    lits = rd.Literals({"thing": ["example-thing"]})
    raw = tmp_path / "raw"
    (raw / "sub").mkdir(parents=True)
    (raw / "a.txt").write_bytes(b"thing example-thing\n")
    used = tmp_path / "used"
    used.mkdir()
    (used / "old.txt").write_text("old", encoding="utf-8")
    with pytest.raises(rd.RedactError):
        rd.copy_tree(raw, used, lits)
    assert sorted(p.name for p in used.iterdir()) == ["old.txt"]
    cases = {"sub/bad.bin.txt": b"thing \xff\xfe example-thing", "sub/cut.json": b'{"thing": "example-thing"',
             "sub/example-thing.txt": b"named after the thing\n"}
    for n, (rel, data) in enumerate(cases.items()):
        (raw / rel).write_bytes(data)
        with pytest.raises(rd.RedactError) as e:
            rd.copy_tree(raw, tmp_path / ("cap%d" % n), lits)
        assert "example-thing" not in str(e.value)
        assert not (tmp_path / ("cap%d" % n)).exists()
        (raw / rel).unlink()
    assert rd.copy_tree(raw, tmp_path / "ok", lits) == [("a.txt", True)]
    assert (tmp_path / "ok" / "a.txt").read_bytes() == b"thing <thing>\n"
    # a source that holds no file is copied too: the destination is made, and is empty
    (raw / "a.txt").unlink()
    assert rd.copy_tree(raw, tmp_path / "of-nothing", lits) == [] and list((tmp_path / "of-nothing").iterdir()) == []


def test_a_refused_copy_names_the_file_by_its_place_inside_the_source_and_nothing_of_the_machine(rd, tmp_path, monkeypatch):
    """What a copy's refusal may say of a file: its place inside the source, which a copy that succeeds would write
    into the capture anyway, and only once that name itself passed the redactor (a name that would change is "file N
    of M"). Never where the source, the destination or the state directory lies, and never the system's own message,
    which carries the whole path. Each text is held whole, so nothing else can be in it."""
    lits = rd.Literals({"thing": ["example-thing"]})
    raw = tmp_path / "raw-replies"
    (raw / "sub").mkdir(parents=True)
    cases = {
        "sub/cut.json": (b'{"thing": "example-thing"', "a JSON document that does not parse: refused, not copied as text"),
        "sub/lines.jsonl": (b'{"a": 1}\n{"thing": "example-thing"\n', "line 2: a JSON document that does not parse: refused, not copied as text"),
        "sub/bin.dat": (b"thing \xff\xfe example-thing", "not UTF-8: what the redactor cannot read, it does not copy"),
        "sub/locked.txt": (b"thing example-thing\n", "cannot be read (Permission denied)"),
    }
    real = Path.read_bytes

    def locked(self):
        if self.name == "locked.txt":
            raise OSError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    for n, (rel, (data, why)) in enumerate(cases.items()):
        (raw / rel).write_bytes(data)
        for copy, src, named in ((rd.copy_tree, raw, rel), (rd.copy_file, raw / rel, rel.split("/")[1])):
            dst = tmp_path / ("cap%d-%s" % (n, copy.__name__))
            with pytest.raises(rd.RedactError) as e:
                copy(src, dst, lits)
            assert str(e.value) == "%s: %s" % (named, why)
            assert not dst.exists()
        (raw / rel).unlink()
    monkeypatch.undo()
    # a name the redactor would change is not printed at all: the file is told by its number
    (raw / "a.txt").write_bytes(b"nothing of it here\n")
    (raw / "sub" / "example-thing.txt").write_bytes(b"named after the thing\n")
    with pytest.raises(rd.RedactError) as e:
        rd.copy_tree(raw, tmp_path / "cap-name", lits)
    assert str(e.value) == "file 2 of 2 has an identifier in its own name (the name is not printed): rename the source"
    (raw / "sub" / "example-thing.txt").unlink()
    # at the command line: one line, exit 2, nothing on stdout, nothing written
    (raw / "sub" / "cut.json").write_bytes(b'{"thing": "example-thing"')
    r = _cli("--state", str(state_dir(tmp_path)), "copy", str(raw), str(tmp_path / "cap-cli"))
    assert r.returncode == 2 and r.stdout == b"" and not (tmp_path / "cap-cli").exists()
    assert r.stderr.decode("utf-8").splitlines() == ["redact: sub/cut.json: a JSON document that does not parse: refused, not copied as text"]


def test_a_copy_the_file_system_stops_part_way_takes_back_what_it_wrote(rd, tmp_path, monkeypatch):
    """A capture is whole or it is not there: after a write that fails, the files already written and the
    directories made for them are gone, a destination that was there before is empty again, and the refusal gives the
    system's reason without the path its own message carries."""
    lits = rd.Literals({"thing": ["example-thing"]})
    raw = tmp_path / "raw"
    (raw / "sub" / "deep").mkdir(parents=True)
    for rel in ("a.txt", "sub/b.txt", "sub/deep/c.txt"):
        (raw / rel).write_bytes(b"thing example-thing\n")
    real = Path.write_bytes
    calls = []

    def full_at_c(self, data):
        calls.append(self.name)
        if self.name == "c.txt":
            raise OSError(28, "No space left on device", str(self))
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", full_at_c)
    for cap, there_before in ((tmp_path / "cap", False), (tmp_path / "empty", True)):
        if there_before:
            cap.mkdir()
        del calls[:]
        with pytest.raises(rd.RedactError) as e:
            rd.copy_tree(raw, cap, lits)
        assert calls == ["a.txt", "b.txt", "c.txt"]
        assert "No space left" in str(e.value) and str(tmp_path) not in str(e.value) and "c.txt" not in str(e.value)
        assert cap.exists() is there_before and (not there_before or list(cap.iterdir()) == [])
    with pytest.raises(rd.RedactError):
        rd.copy_file(raw / "sub" / "deep" / "c.txt", tmp_path / "one" / "x" / "c.txt", lits)
    assert not (tmp_path / "one").exists()
    monkeypatch.undo()
    assert [rel for rel, _changed in rd.copy_tree(raw, tmp_path / "empty", lits)] == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    assert (tmp_path / "empty" / "sub" / "deep" / "c.txt").read_bytes() == b"thing <thing>\n"


def test_a_file_is_redacted_by_the_rule_its_name_asks_for(rd, tmp_path):
    """.json and .jsonl keep their numbers, a 12-digit one too; the same bytes under another name are text, and
    there a standalone 12-digit run goes. Held for a copied tree and for one copied file."""
    lits = rd.Literals({"thing": ["example-thing"]})
    line = b'{"n": 123456789012, "thing": "example-thing", "s": "of 444455556666"}\n'
    as_json = b'{"n": 123456789012, "thing": "<thing>", "s": "of <account>"}\n'
    as_text = b'{"n": <account>, "thing": "<thing>", "s": "of <account>"}\n'
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("reply.json", "lines.jsonl", "reply.json.txt", "lines.log"):
        (raw / name).write_bytes(line * (1 if name.startswith("reply") else 2))
    (raw / "same.txt").write_bytes(b"nothing of it here\n")
    want = {"reply.json": as_json, "lines.jsonl": as_json * 2, "reply.json.txt": as_text, "lines.log": as_text * 2,
            "same.txt": b"nothing of it here\n"}
    assert rd.copy_tree(raw, tmp_path / "cap", lits) == [(name, name != "same.txt") for name in sorted(want)]
    for name, data in want.items():
        assert (tmp_path / "cap" / name).read_bytes() == data, name
        assert rd.redact_named(name, (raw / name).read_bytes(), lits) == data, name
        assert rd.copy_file(raw / name, tmp_path / "one" / "sub" / name, lits) is (name != "same.txt"), name
        assert (tmp_path / "one" / "sub" / name).read_bytes() == data, name
    assert rd.scan(tmp_path / "cap", lits) == [] and rd.scan(tmp_path / "one", lits) == []


def test_one_file_is_never_copied_over_another_and_a_directory_is_not_a_file(rd, tmp_path):
    lits = rd.Literals({"thing": ["example-thing"]})
    src = tmp_path / "raw.txt"
    src.write_bytes(b"thing example-thing\n")
    dst = tmp_path / "cap" / "raw.txt"
    assert rd.copy_file(src, dst, lits) is True and dst.read_bytes() == b"thing <thing>\n"
    src.write_bytes(b"another example-thing\n")
    with pytest.raises(rd.RedactError) as e:
        rd.copy_file(src, dst, lits)
    assert dst.read_bytes() == b"thing <thing>\n" and "example-thing" not in str(e.value) and str(tmp_path) not in str(e.value)
    for bad_src, bad_dst in ((tmp_path / "cap", tmp_path / "new"), (tmp_path / "absent.txt", tmp_path / "new")):
        with pytest.raises(rd.RedactError):
            rd.copy_file(bad_src, bad_dst, lits)
        assert not (tmp_path / "new").exists()
    with pytest.raises(rd.RedactError):
        rd.copy_tree(src, tmp_path / "new", lits)              # and a file is not a directory
    assert not (tmp_path / "new").exists()
    named = tmp_path / "example-thing.txt"
    named.write_bytes(b"named after the thing\n")
    with pytest.raises(rd.RedactError) as e:
        rd.copy_file(named, tmp_path / "new", lits)
    assert not (tmp_path / "new").exists() and "example-thing" not in str(e.value)


def test_the_scan_takes_the_states_literals_and_gives_shapes_never_values(rd, tmp_path):
    d = tmp_path / "cap"
    d.mkdir()
    (d / "reply.json").write_text(json.dumps({"certificateId": CERT_ID, "thing": "example-thing"}), encoding="utf-8")
    assert rd.scan(d, rd.NONE) == []
    lits = rd.load_literals(state_dir(tmp_path))
    assert sorted(rd.scan(d, lits)) == [("reply.json", "local literal", len("example-thing")), ("reply.json", "local literal", 64)]


def test_a_capture_the_scan_cannot_read_is_a_refusal_that_names_no_path(rd, tmp_path, monkeypatch):
    d = tmp_path / "cap"
    d.mkdir()

    def unreadable(root, literals=()):
        raise OSError(13, "Permission denied", str(d / "reply.json"))

    monkeypatch.setattr(rd.SCANNER, "scan", unreadable)
    with pytest.raises(rd.RedactError) as e:
        rd.scan(d, rd.NONE)
    assert "Permission denied" in str(e.value) and str(tmp_path) not in str(e.value) and "reply.json" not in str(e.value)


def test_a_capture_that_is_not_there_is_refused_not_called_clean(rd, tmp_path):
    """The scanner walks a directory that is not there, or a file, and finds nothing in it: without the refusal a
    mistyped capture directory would read as clean."""
    a_file = tmp_path / "capture.txt"
    a_file.write_bytes(b"nothing of it here\n")
    for not_a_directory in (tmp_path / "absent", a_file):
        with pytest.raises(rd.RedactError) as e:
            rd.scan(not_a_directory, rd.NONE)
        assert str(tmp_path) not in str(e.value) and not_a_directory.name not in str(e.value)
        r = _cli("--no-literals", "scan", str(not_a_directory))
        assert r.returncode == 2 and r.stdout == b"" and b"clean" not in r.stderr, r.stderr
        assert str(tmp_path).encode() not in r.stderr and len(r.stderr.splitlines()) == 1


# ============================================================ 3. the literals

def test_the_literals_come_from_the_state_directorys_file(rd, tmp_path):
    lits = rd.load_literals(state_dir(tmp_path))
    assert set(lits.values) == {v for vs in LITERALS.values() for v in vs}
    assert list(lits.values) == sorted(lits.values, key=lambda v: (-len(v), v))            # the longest first
    assert dict(lits.pairs)[CERT_ID] == "<certificate-id>" and dict(lits.pairs)["example_rule"] == "<rule>"
    assert rd.NONE.values == () and rd.LITERALS_FILE == "literals.json"


def test_a_state_directory_with_no_literals_file_is_refused_not_read_as_none(rd, tmp_path):
    (tmp_path / "empty").mkdir()
    for d in (tmp_path / "empty", tmp_path / "absent"):
        with pytest.raises(rd.LiteralsError) as e:
            rd.load_literals(d)
        assert "literals.json" in str(e.value) and str(tmp_path) not in str(e.value)


def test_the_literals_file_is_refused_inside_this_repositorys_tree(rd, tmp_path, monkeypatch):
    """Gap b: no literal lives in the work tree. The tree is where this module lies, whether or not it holds a .git
    (a copy of the tree has none)."""
    with pytest.raises(rd.LiteralsError) as e:
        rd.load_literals(REPO / "sdv" / "cloud")               # holds no such file: the refusal comes before any read
    assert "work tree" in str(e.value) and "nothing was read" in str(e.value) and str(REPO) not in str(e.value)
    tree = tmp_path / "tree"
    inside = state_dir(tree / "sdv" / "cloud", name="state")
    assert rd.load_literals(inside).values                     # outside the tree: read
    monkeypatch.setattr(rd, "REPO", tree)
    for d in (inside, tree):
        with pytest.raises(rd.LiteralsError) as e:
            rd.load_literals(d)
        assert "work tree" in str(e.value) and str(tmp_path) not in str(e.value)
    assert rd.load_literals(state_dir(tmp_path, name="outside")).values


@pytest.mark.parametrize("marker", ["file", "directory"])
def test_the_literals_file_is_refused_inside_any_work_tree(rd, tmp_path, marker):
    """Another checkout is a work tree too (the main one is public): a .git above the file, a file or a directory,
    found by walking up and never by running git."""
    wt = tmp_path / "checkout"
    inside = state_dir(wt / "local", name="state")
    assert rd.load_literals(inside).values
    if marker == "file":
        (wt / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    else:
        (wt / ".git").mkdir()
    with pytest.raises(rd.LiteralsError) as e:
        rd.load_literals(inside)
    assert "work tree" in str(e.value) and str(tmp_path) not in str(e.value)
    assert rd.load_literals(state_dir(tmp_path, name="outside")).values
    # a state directory that is a checkout's top itself: the .git lies beside the literals file
    top = state_dir(tmp_path, name="a-checkout-itself")
    assert rd.load_literals(top).values
    if marker == "file":
        (top / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    else:
        (top / ".git").mkdir()
    with pytest.raises(rd.LiteralsError) as e:
        rd.load_literals(top)
    assert "work tree" in str(e.value) and str(tmp_path) not in str(e.value)


def _link(target: Path, link: Path, may_skip: bool = os.name == "nt") -> None:
    """A symbolic link to a directory, for a test. Where the host may refuse one to an ordinary user (Windows) the
    test is skipped. Anywhere else a refusal is an error: the Phase 4 recipe runs in WSL and its skip check
    (tests/twin_gate.py) does not hold this file, so a skip there would be seen by nobody."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        if not may_skip:
            raise
        pytest.skip("this host does not let the test make a symbolic link")


def test_a_link_does_not_carry_the_literals_file_out_of_or_into_a_work_tree(rd, tmp_path):
    wt = tmp_path / "checkout"
    (wt / ".git").mkdir(parents=True)
    real_in = state_dir(wt, name="state-in-tree")
    real_out = state_dir(tmp_path, name="state-outside")
    _link(real_in, tmp_path / "link-to-inside")
    _link(real_out, wt / "link-to-outside")
    for d in (tmp_path / "link-to-inside", wt / "link-to-outside"):
        with pytest.raises(rd.LiteralsError) as e:
            rd.load_literals(d)
        assert "work tree" in str(e.value)


def test_the_link_test_is_skipped_only_where_a_link_may_be_refused(tmp_path, monkeypatch):
    def refused(*args, **kwargs):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(os, "symlink", refused)
    with pytest.raises(OSError):
        try:
            _link(tmp_path / "a", tmp_path / "b", may_skip=False)
        except pytest.skip.Exception:              # a skip here would skip this test too, and read as a pass
            raise AssertionError("a refused link was skipped where a refusal is an error") from None
    with pytest.raises(pytest.skip.Exception):
        _link(tmp_path / "a", tmp_path / "b", may_skip=True)
    assert _link.__defaults__ == (os.name == "nt",)


def test_a_literals_file_whose_place_cannot_be_judged_is_refused_and_not_read(rd, tmp_path, monkeypatch):
    """Links that cannot be followed (a loop, as the system reports it or as Python does): the file is well formed and
    lies where one may lie as far as its path says, and it is not read, because where it really lies was not told."""
    state = state_dir(tmp_path)
    assert rd.load_literals(state).values
    real = Path.resolve
    for failure in (OSError(40, "Too many levels of symbolic links", str(state)), RuntimeError("Symlink loop from %s" % state)):

        def lost(self, *args, _failure=failure, **kwargs):
            if self.name == rd.LITERALS_FILE:
                raise _failure
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", lost)
        with pytest.raises(rd.LiteralsError) as e:
            rd.load_literals(state)
        assert "work tree" in str(e.value) and "nothing was read" in str(e.value) and str(tmp_path) not in str(e.value)


BAD_FILES = [
    ("not json", "{"),
    ("a list", "[]"),
    ("no version", json.dumps({"literals": {}})),
    ("another version", json.dumps({"v": 2, "literals": {}})),
    ("true is not 1", json.dumps({"v": True, "literals": {}})),
    ("no literals", json.dumps({"v": 1})),
    ("a misspelt key reads as none", json.dumps({"v": 1, "literal": {"thing": ["example-thing"]}, "literals": {}})),
    ("literals a list", json.dumps({"v": 1, "literals": ["example-thing"]})),
    ("a kind's values a string", json.dumps({"v": 1, "literals": {"thing": "example-thing"}})),
    ("a value not a string", json.dumps({"v": 1, "literals": {"account": [123456789012]}})),
    ("a kind not a label", json.dumps({"v": 1, "literals": {"Thing Name": ["example-thing"]}})),
    ("an empty value", json.dumps({"v": 1, "literals": {"thing": [""]}})),
    ("a short value", json.dumps({"v": 1, "literals": {"thing": ["ab"]}})),
    ("a padded value", json.dumps({"v": 1, "literals": {"thing": ["example-thing\n"]}})),
    ("a value a mask spells", json.dumps({"v": 1, "literals": {"thing": ["certificate-id"]}})),
    ("a value its own kind's mask spells", json.dumps({"v": 1, "literals": {"example-kind": ["example-kind"]}})),
]


@pytest.mark.parametrize("why, text", BAD_FILES, ids=[w.replace(" ", "-") for w, _t in BAD_FILES])
def test_a_literals_file_in_another_form_is_refused(rd, tmp_path, why, text):
    d = tmp_path / "state"
    d.mkdir()
    (d / "literals.json").write_text(text, encoding="utf-8")
    with pytest.raises(rd.LiteralsError) as e:
        rd.load_literals(d)
    for value in ("example-thing", "certificate-id", "example-kind", "Thing Name", "123456789012", str(tmp_path)):
        assert value not in str(e.value), why            # no error prints a value, a kind or the directory


def test_an_empty_kind_and_a_value_under_two_kinds_are_read(rd, tmp_path):
    """A value under two kinds goes under the first of them by name, whichever the file lists first."""
    for n, kinds in enumerate((("rule", "function"), ("function", "rule"))):
        d = state_dir(tmp_path, dict([("thing", [])] + [(kind, ["example-name"]) for kind in kinds]), name="state%d" % n)
        lits = rd.load_literals(d)
        assert lits.values == ("example-name",) and lits.pairs == (("example-name", "<function>"),), kinds


# ============================================================ the command line

def _cli(*args: str, data: bytes = b"") -> "subprocess.CompletedProcess[bytes]":
    return subprocess.run([PY, str(REDACT), *args], input=data, capture_output=True, timeout=120)


def test_the_command_line_filters_copies_and_scans_with_the_states_literals(tmp_path):
    state = state_dir(tmp_path)
    r = _cli("--state", str(state), "filter", data=("thing example-thing at %s\n" % CERT_ARN).encode("utf-8"))
    assert r.returncode == 0 and r.stdout == b"thing <thing> at <arn>\n", r.stderr
    doc = json.dumps({"n": 123456789012, "Account": ACCOUNT}).encode("utf-8")
    r = _cli("--state", str(state), "filter", "--json", data=doc)
    assert r.returncode == 0 and r.stdout == json.dumps({"n": 123456789012, "Account": "<account>"}).encode("utf-8"), r.stderr
    raw, cap = tmp_path / "raw", tmp_path / "cap"
    raw_capture(raw)
    r = _cli("--state", str(state), "scan", str(raw))
    assert r.returncode == 1 and b"LEAK " in r.stdout and b"finding(s)" in r.stdout
    assert not [v for v in GONE + (ACCOUNT,) if v.encode("ascii") in r.stdout + r.stderr]
    r = _cli("--state", str(state), "copy", str(raw), str(cap))
    assert r.returncode == 0, r.stderr
    r = _cli("--state", str(state), "scan", str(cap))
    assert r.returncode == 0 and b"clean" in r.stdout, r.stdout
    # one file: by its name's rule, to a new file, and never over one that is there
    one = tmp_path / "one" / "describe-endpoint.json"
    for want in (0, 2):
        r = _cli("--state", str(state), "copy", str(raw / "iot" / "describe-endpoint.json"), str(one))
        assert r.returncode == want and (want == 0 or r.stdout == b""), r.stderr
        assert json.loads(one.read_text(encoding="utf-8")) == {"endpointAddress": "<endpoint-prefix><endpoint>"}
    assert not [v for v in GONE + (str(tmp_path),) if v.encode("utf-8") in r.stdout + r.stderr]


def test_a_scan_that_finds_more_than_it_lists_says_how_many_of_every_shape(tmp_path):
    """WP8's capture rehearsal (item 4). Both scan commands list the first 50 findings, in the order of the files' names,
    so a finding of the kind a copy refuses outright (encoded data, a document that does not parse) could lie past the
    cut with only the total to say that anything was there. Past 50 they add one line that counts every shape; at 50
    and under, nothing is added."""
    raw = tmp_path / "raw"
    raw.mkdir()
    for n in range(LS.LISTED):
        (raw / ("a-%03d.txt" % n)).write_text("ask %s\n" % EMAIL, encoding="utf-8")
    listed = ["LEAK a-%03d.txt: e-mail address (%d chars)" % (n, len(EMAIL)) for n in range(LS.LISTED)]
    r = _leakscan(raw)
    assert r.returncode == 1 and r.stdout.splitlines() == listed + ["leakscan: 50 finding(s) -- NOT publishable"], r.stdout
    c = _cli("--no-literals", "scan", str(raw))
    assert c.returncode == 1 and c.stdout.decode("utf-8").splitlines() == listed + ["redact: 50 finding(s): not to leave this machine"]
    # past the cut, in the files' own order: a document that does not parse, and a block of encoded text
    (raw / "z-broken.json").write_text('{"thing": ', encoding="utf-8")
    (raw / "z-encoded.txt").write_text("LogResult %s\n" % base64.b64encode(b"what a function logged, " * 4).decode("ascii"), encoding="utf-8")
    r = _leakscan(raw)
    lines = r.stdout.splitlines()
    assert r.returncode == 1 and lines[:50] == listed and lines[-1] == "leakscan: 52 finding(s) -- NOT publishable" and len(lines) == 52
    assert lines[50].startswith("only the first 50 are listed; of all 52, by shape: ") and "e-mail address 50" in lines[50]
    shapes = dict(part.rsplit(" ", 1) for part in lines[50].split("by shape: ")[1].split(", "))
    assert sorted(shapes) == sorted(["e-mail address", LS.UNDECODED] + [k for k in shapes if "json" in k]) and len(shapes) == 3
    assert shapes[LS.UNDECODED] == "1" and "z-broken" not in r.stdout and "z-encoded" not in r.stdout          # which is why the line is there
    c = _cli("--no-literals", "scan", str(raw))
    assert c.returncode == 1 and c.stdout.decode("utf-8").splitlines() == listed + [
        "redact: " + lines[50], "redact: 52 finding(s): not to leave this machine"], c.stdout
    assert LS.tally(["b", "a", "b"]) == "only the first 50 are listed; of all 3, by shape: a 1, b 2" and LS.LISTED == 50
    assert EMAIL not in r.stdout and EMAIL.encode("ascii") not in c.stdout


def test_the_command_line_never_runs_without_literals_unless_told_so(tmp_path):
    r = _cli("filter", data=b"thing example-thing\n")
    assert r.returncode == 2 and r.stdout == b""
    r = _cli("--no-literals", "filter", data=("id %s\n" % USER_ID).encode("ascii"))
    assert r.returncode == 0 and r.stdout == b"id <iam-id>\n"
    (tmp_path / "empty").mkdir()
    r = _cli("--state", str(tmp_path / "empty"), "filter", data=b"thing example-thing\n")
    assert r.returncode == 2 and r.stdout == b"" and b"literals.json" in r.stderr and str(tmp_path).encode() not in r.stderr


def test_the_command_line_refuses_a_state_directory_inside_the_work_tree_and_prints_no_path(tmp_path):
    r = _cli("--state", str(REPO / "sdv" / "cloud"), "filter", data=b"thing example-thing\n")
    assert r.returncode == 2 and r.stdout == b"" and b"work tree" in r.stderr
    assert str(REPO).encode() not in r.stderr
    wt = tmp_path / "checkout"
    (wt / ".git").mkdir(parents=True)
    r = _cli("--state", str(state_dir(wt)), "filter", data=b"thing example-thing\n")
    assert r.returncode == 2 and r.stdout == b"" and b"work tree" in r.stderr and str(tmp_path).encode() not in r.stderr


def test_what_the_redactor_refuses_reaches_no_output(tmp_path):
    state = state_dir(tmp_path)
    r = _cli("--state", str(state), "filter", "--json", data=b'{"thing": "example-thing"')
    assert r.returncode == 2 and r.stdout == b"" and b"example-thing" not in r.stderr
    r = _cli("--state", str(state), "filter", data=b"thing \xff example-thing")
    assert r.returncode == 2 and r.stdout == b"" and b"example-thing" not in r.stderr
    r = _cli("--state", str(state), "filter", "--json", data='{"k": "\\ud800 é example-thing"}'.encode("utf-8"))
    assert r.returncode == 2 and r.stdout == b"" and b"example-thing" not in r.stderr and b"Traceback" not in r.stderr, r.stderr
    assert r.stderr.startswith(b"redact: ") and len(r.stderr.splitlines()) == 1


def test_a_copy_the_file_system_refuses_is_a_refusal_with_no_path_and_no_traceback(tmp_path):
    """Exit 1 is the scan's "found something"; a destination that cannot be written is exit 2 like every other
    refusal, and the system's own message, which names the path, is not passed on."""
    state = state_dir(tmp_path)
    src = tmp_path / "reply.txt"
    src.write_bytes(b"thing example-thing\n")
    in_the_way = tmp_path / "a-file"
    in_the_way.write_bytes(b"not a directory\n")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "reply.txt").write_bytes(b"thing example-thing\n")
    for source in (src, raw):
        r = _cli("--state", str(state), "copy", str(source), str(in_the_way / "sub" / "copy.txt"))
        assert r.returncode == 2 and r.stdout == b"", r.stderr
        assert r.stderr.startswith(b"redact: ") and b"Traceback" not in r.stderr and len(r.stderr.splitlines()) == 1, r.stderr
        for value in (str(tmp_path), tmp_path.name, "example-thing"):
            assert value.encode("utf-8") not in r.stderr
    assert in_the_way.read_bytes() == b"not a directory\n"


def test_what_no_rule_foresaw_is_a_refusal_too_and_gives_its_kind_only(rd, monkeypatch, capsys):
    """The command line's last net: stdin going away is no rule's business, and the system's message for it may name
    a path. Exit 2, as every refusal (1 is the scan's "found something"), and the exception's kind alone."""

    class Gone:
        class buffer:
            @staticmethod
            def read():
                raise OSError(5, "Input/output error", "/somewhere/a-place")

    monkeypatch.setattr(sys, "stdin", Gone())
    assert rd.main(["--no-literals", "filter"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and err == "redact: refused (OSError)\n"


# ============================================================ 4. the tree side

def test_the_tree_side_spells_the_two_new_shapes_as_the_scanner_does():
    import test_no_real_identifiers as tree_side              # tests/ is on sys.path under pytest
    scanner = dict(LS.PATTERNS)
    for name, shape in (("ENDPOINT", "iot endpoint"), ("CERT", "certificate id")):
        mine, theirs = getattr(tree_side, name), scanner[shape]
        assert (mine.pattern, mine.flags) == (theirs.pattern, theirs.flags), shape


def test_this_files_fixtures_pass_the_tree_side_check_and_the_check_reads_this_file():
    import test_no_real_identifiers as tree_side
    me = Path(__file__).resolve()
    assert str(me) in {str(Path(p).resolve()) for p in tree_side._files()}
    text = me.read_text(encoding="utf-8")
    assert tree_side.unlisted(text) == []
    # and it is not passing for want of looking: the fixtures' values are there, and are on the list by name
    for value in (ENDPOINT, ENDPOINT_PLAIN, ENDPOINT_CRED, "cert/" + CERT_ID, ACCOUNT):
        assert value in text and value in tree_side.ALLOWED, value[:8]


def test_no_file_of_this_package_spells_a_path_of_the_excluded_branch():
    """Prep gap d, for the files WP4 adds or changes: the excluded prefix is read from the stack's attribution.py."""
    m = re.search(r'^MONITOR_PREFIX = "(.+)"$', (REPO / "sdv" / "stack" / "attribution.py").read_text(encoding="utf-8"), re.M)
    assert m is not None
    prefix = m.group(1).rstrip(".").lower()
    files = [REDACT, LEAKSCAN, Path(__file__).resolve(), HERE / "test_no_real_identifiers.py", REPO / "sdv" / "cloud" / "README.md",
             REPO / "scripts" / "aws" / "README.md"]
    assert len({p.resolve() for p in files}) == 6 and all(p.is_file() for p in files)
    for p in files:
        assert prefix not in p.read_text(encoding="utf-8", errors="replace").lower(), p.name


# ------------------------------------------------------------------------------------------- Phase 6 WP4: the pull identity's two shapes

ALIAS_ARN = "arn:aws:iot:us-east-1:123456789012:rolealias/sdv-twin-ecr-pull"
CRED_URL = "https://%s/role-aliases/sdv-twin-ecr-pull/credentials" % ENDPOINT_CRED


def test_the_credential_providers_host_is_found_and_masked_whole_in_each_form_the_pull_side_meets_it(rd):
    """Phase 6 spec section 5, item 10. The host twinctl ecr-config reads (describe-endpoint for iot:CredentialProvider) and
    ecrlogin.py connects to, <prefix>.credentials.iot.<region>.amazonaws.com: in the URL of the credentials' request, in the
    reply that names it and in the pulling host's file, the scanner finds it whole, under the endpoint's shape, and the redactor
    leaves none of it. It was a form of the endpoint's shape before Phase 6 (the credentials label), and this test holds it so."""
    file_ = json.dumps({"credential_endpoint": ENDPOINT_CRED, "role_alias": "sdv-twin-ecr-pull", "region": "us-east-1", "registry": ECR})
    for text, is_json in ((CRED_URL, False), (json.dumps({"endpointAddress": ENDPOINT_CRED}), True), (file_, True)):
        assert ("iot endpoint", ENDPOINT_CRED) in LS.findings(text, is_json, ()), text[:20]
    assert rd.redact_text(CRED_URL, rd.NONE) == "https://<endpoint>/role-aliases/sdv-twin-ecr-pull/credentials"
    assert json.loads(rd.redact_json(json.dumps({"endpointAddress": ENDPOINT_CRED}), rd.NONE)) == {"endpointAddress": "<endpoint>"}
    assert json.loads(rd.redact_json(file_, rd.NONE)) == {"credential_endpoint": "<endpoint>", "role_alias": "sdv-twin-ecr-pull",
                                                          "region": "us-east-1", "registry": "<ecr-host>"}
    lits = rd.Literals({"endpoint-prefix": [PREFIX]})
    assert rd.redact_text(CRED_URL, lits) == "https://<endpoint-prefix>.<endpoint>/role-aliases/sdv-twin-ecr-pull/credentials"


def test_the_role_aliass_arn_is_found_and_masked_whole_and_its_constant_name_alone_is_no_identifier(rd):
    """Item 10's other shape: a role alias's ARN (`:rolealias/`) holds the region and the account, and goes whole, as every ARN
    does; the alias's own name is the spec's constant (sdv-twin-ecr-pull), which names nobody, and stays."""
    reply = json.dumps({"roleAliasDescription": {"roleAlias": "sdv-twin-ecr-pull", "roleAliasArn": ALIAS_ARN, "owner": ACCOUNT,
                                                 "credentialDurationSeconds": 3600}})
    assert [label for label, _tok in LS.findings(reply, True, ())] == ["arn"]
    assert "12-digit number" in labels("owner " + ACCOUNT)
    assert json.loads(rd.redact_json(reply, rd.NONE)) == {"roleAliasDescription": {
        "roleAlias": "sdv-twin-ecr-pull", "roleAliasArn": "<arn>", "owner": "<account>", "credentialDurationSeconds": 3600}}
    assert rd.redact_text("iot:AssumeRoleWithCertificate on " + ALIAS_ARN + ".", rd.NONE) == "iot:AssumeRoleWithCertificate on <arn>"
    assert LS.findings("the alias sdv-twin-ecr-pull", False, ()) == []


def test_the_scanners_and_the_redactors_docstrings_name_the_pull_identitys_two_shapes(rd):
    def fold(text):
        return " ".join(str(text).replace("`", "").split())

    scanner, redactor = fold(LS.__doc__), fold(rd.__doc__)
    for doc in (scanner, redactor):
        assert ("the IoT credential provider's host (<prefix>.credentials.iot.<region>.amazonaws.com, which twinctl ecr-config reads and "
                "ecrlogin.py connects to) is a form of the endpoint's shape") in doc
        assert "a role alias's ARN (:rolealias/) is an ARN and goes whole as one" in doc
