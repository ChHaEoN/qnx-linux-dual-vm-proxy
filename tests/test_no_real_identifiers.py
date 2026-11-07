"""The tooling that handles AWS identifiers may only contain FAKE ones.

On 2026-09-22 the selftest of `redact-aws.sh` -- the redactor itself -- asserted
against the real account id, instance id, volume id and public address of the
session it was written in, and went public for a day. The redactor worked; its
fixture was the leak, because a redaction test reads as test code rather than as
captured data. It is captured data.

So this is an allowlist, not a pattern match: every AWS-shaped identifier in the
directories that handle them has to be a value someone deliberately put on the
list below. A new placeholder fails here until it is added, which is the point --
adding it is a line of code, and getting it wrong is a history rewrite.

Scope is the five places a session's identifiers pass through: the bare-metal
session tooling, the harnesses, the tests, and (plan Phase 4 WP4) the
twin's device side and its account side, sdv/connector and sdv/cloud. The rest
of the repo is not covered: run records under results/ carry 12-digit KVM
counters that look exactly like account ids, which is why leakscan.py reads JSON
numbers as numbers and why a tree-wide version of this check would be noise.

The twin adds three shapes (WP4). A data endpoint, with or without -ats: its
first label is the account's own prefix, read from where the run of letters,
digits and hyphens in front of .iot begins (a hyphen may begin it, so a host
glued to an option or to a diff's minus is found). `cert/` and 64 hex characters, as a
certificate's ARN ends: the 64 characters alone are also a sha256, which every
lock file here holds by the dozen, so only the pair is a shape. And a PEM block
with a body: no certificate and no key is ever on the list, so a fixture builds
its block when the test runs. A registry host that starts with an account id
needs no shape of its own: its twelve digits are an account id to the rule
above. An e-mail address and an IAM unique id have a shape in leakscan.py only.

What this does not see: a name. A thing's, a rule's or a bucket's name has no
shape, and neither has a certificate id or a canonical user id standing alone;
those are searched for as literals, from the state directory, by the account
side's own tooling (sdv/cloud/redact.py).

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

DIRS = [
    os.path.join(REPO, "scripts", "aws"),
    os.path.join(REPO, "orin-native", "gpu-concurrency"),
    HERE,
    os.path.join(REPO, "sdv", "connector"),
    os.path.join(REPO, "sdv", "cloud"),
]

# AWS's own documentation account ids, RFC 5737 TEST-NET addresses, and resource
# ids whose body is plainly typed by hand rather than allocated.
ALLOWED = {
    # account ids: AWS's documentation uses the first two; the rest are this
    # repo's stubs, including the one in capture.py's docstring that the
    # redactor must NOT rewrite when capture.py is copied through it.
    "123456789012", "111122223333", "444455556666", "666677778888", "912345678901",
    # resource ids
    "i-0123456789abcdef0", "vol-0abcdef1234567890", "sg-0123abcd", "sg-0123abcd4567ef890",
    "subnet-0aaaaaaaaaaaaaaa1", "i-0aaaaaaaaaaaaaaaa", "ami-0abcdef1234567890",
    "sg-0123456789abcdef0",
    # the public Ubuntu arm64 AMI drive-metal.sh launches: a published image id,
    # not a resource belonging to this account.
    "ami-0d9429f78b33241cd",
    # the public Ubuntu arm64 AMI it launched until 2026-10-08, kept while a fixture
    # names it (leakscan must go on passing a held record's image id).
    "ami-02153ae97d7504246",
    # the twin's documentation values (WP4). A real endpoint prefix is 14
    # characters nobody chose; this one spells "example" and ends in zeros. The
    # three hosts are one prefix in the endpoint's three forms.
    "aexample000000-ats.iot.us-east-1.amazonaws.com",
    "aexample000000.iot.us-east-1.amazonaws.com",
    "aexample000000.credentials.iot.us-east-1.amazonaws.com",
    # a certificate id that is the hex digits in order, four times
    "cert/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
}

RESOURCE = re.compile(r"(?<![A-Za-z0-9])(?:i|vol|sg|subnet|vpc|eni|snap|ami)-[0-9a-f]{8,17}(?![0-9a-f])")
# The boundary redact-aws.sh masks on, so this sees what the redactor would.
ACCOUNT = re.compile(r"(?<![0-9A-Za-z_.-])\d{12}(?![0-9A-Za-z_-]|\.\d)")
# A public address that is not in a documentation range. RFC 5737 (192.0.2.0/24,
# 198.51.100.0/24, 203.0.113.0/24) and RFC 1918 are fine; anything else routable
# is somebody's machine.
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
DOC_OR_PRIVATE = re.compile(
    r"^(?:192\.0\.2\.|198\.51\.100\.|203\.0\.113\."          # RFC 5737
    r"|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\."          # RFC 1918
    r"|127\.|0\.0\.0\.0|255\.255\.255\.255"
    r"|169\.254\.)")                                         # link-local, incl. the EC2 metadata address
# The twin's two shapes, spelled as leakscan.py spells them (tests/test_sdv_cloud_redact.py holds the two copies
# to one pattern). The service's own host, which has no first label of an account's, is not an endpoint.
ENDPOINT = re.compile(
    r"(?<![A-Za-z0-9-])[A-Za-z0-9-]+(?:\.(?:credentials|jobs))?\.iot(?:-fips)?\.[A-Za-z0-9-]+\.amazonaws\.com", re.I)
CERT = re.compile(r"cert/[0-9a-fA-F]{64}(?![0-9a-fA-F])")
# A PEM block's first line with a body after it, the line break real or still escaped: 20 base64 characters in a
# row are no sentence. The first line alone is a mention, and is what a test builds its block from.
PEM = re.compile(r"-----BEGIN [A-Z0-9 ]+-----(?:\\[rn]|\s)*[A-Za-z0-9+/]{20,}")


def _files():
    for d in DIRS:
        for root, dirs, names in os.walk(d):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", ".pytest_cache")]
            for n in sorted(names):
                if n.endswith((".pyc", ".png", ".gz", ".bin")):
                    continue
                yield os.path.join(root, n)


def _read(p):
    with open(p, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def unlisted(text, allowed=None):
    """Every identifier-shaped token of `text` that is not on the allowlist, as (what a report may show of it, the
    token): the first four characters for the older shapes, as before, and the shape's name for the twin's."""
    allowed = ALLOWED if allowed is None else allowed
    bad = []
    for rx in (RESOURCE, ACCOUNT):
        bad += [(m.group(0)[:4], m.group(0)) for m in rx.finditer(text) if m.group(0) not in allowed]
    for m in IPV4.finditer(text):
        v = m.group(0)
        if not DOC_OR_PRIVATE.match(v) and all(0 <= int(o) <= 255 for o in v.split(".")):
            bad.append((v[:4], v))
    for shape, rx in (("endpoint", ENDPOINT), ("cert/", CERT)):
        bad += [(shape, m.group(0)) for m in rx.finditer(text) if m.group(0) not in allowed]
    bad += [("pem", m.group(0)) for m in PEM.finditer(text)]           # no block is ever on the list
    return bad


def _unlisted(text, allowed):
    """Use the same identifier checks with an explicit allowlist for the AMI pin tests."""
    return [token for _shape, token in unlisted(text, allowed)]


@pytest.mark.parametrize("path", sorted(_files()), ids=lambda p: os.path.relpath(p, REPO).replace(os.sep, "/"))
def test_only_allowlisted_identifiers(path):
    bad = unlisted(_read(path))
    rel = os.path.relpath(path, REPO).replace(os.sep, "/")
    # Report the shape, never the value: the value may be the leak, and this
    # message ends up in a public CI log.
    assert not bad, "%s carries %d identifier(s) not on the allowlist: %s" % (
        rel, len(bad), ", ".join(sorted({"%s[%d chars]" % (shown, len(v)) for shown, v in bad})))


# --- the check itself (WP4). Every value below is put together when the test runs: written out, it would be a
# --- finding of the test above in this very file.

HEX = "0123456789abcdef"


def test_the_twins_two_directories_are_read():
    rels = {os.path.relpath(p, REPO).replace(os.sep, "/") for p in _files()}
    for rel in ("sdv/cloud/redact.py", "sdv/cloud/README.md", "sdv/connector/topics.py", "sdv/connector/probes/probe.py",
                "scripts/aws/leakscan.py", "tests/test_no_real_identifiers.py"):
        assert rel in rels, rel
    assert not [r for r in rels if "__pycache__" in r]


def test_an_endpoint_that_is_not_on_the_list_is_found():
    host = "." + "iot.eu-central-1.amazonaws.com"
    for label in ("b1c2d3e4f5g6h7-ats", "b1c2d3e4f5g6h7", "B1C2D3E4F5G6H7-ATS", "b1c2d3e4f5g6h7.credentials", "data-ats"):
        found = unlisted("mqtts://%s%s:8883" % (label, host))
        assert found == [("endpoint", label + host)], label
    # glued to a hyphen (a diff's minus, an option's value, an option's name): found from where the run begins
    for front in ("-", "--", "-h", "--endpoint-", "-x-"):
        assert unlisted("curl %sb1c2d3e4f5g6h7-ats%s:8883" % (front, host)) == [("endpoint", front + "b1c2d3e4f5g6h7-ats" + host)], front
    # a listed host with something glued in front of it is another token, and is not on the list
    glued = "-h" + "aexample000000-ats.iot.us-east-1.amazonaws.com"
    assert unlisted("curl " + glued) == [("endpoint", glued)]
    # the documentation prefix in another region is another host: the list holds hosts, not prefixes
    assert [shown for shown, _v in unlisted("aexample000000-ats" + host)] == ["endpoint"]
    assert unlisted("https://iot.eu-central-1.amazonaws.com/things and s3.eu-central-1.amazonaws.com") == []
    assert unlisted("aexample000000-ats.iot.us-east-1.amazonaws.com aexample000000.iot.us-east-1.amazonaws.com") == []


def test_a_certificate_id_after_cert_is_found_in_an_arn_too_and_a_bare_sha256_is_not():
    other = HEX[::-1] * 4
    assert unlisted("cert/" + other) == [("cert/", "cert/" + other)]
    assert unlisted("arn:aws:iot:us-east-1:123456789012:" + "cert/" + other) == [("cert/", "cert/" + other)]
    assert unlisted("cert/" + other.upper()) == [("cert/", "cert/" + other.upper())]
    for kept in (other, "sha256:" + other, "--hash=sha256:" + other, "blobs/sha256/" + other, "cert/" + other[:63], "cert/" + other + "0"):
        assert unlisted(kept) == [], "a sha256 is not a certificate id"
    assert unlisted("arn:aws:iot:us-east-1:123456789012:" + "cert/" + HEX * 4) == []          # the one on the list


def test_a_pem_block_with_a_body_is_found_and_never_allowed(monkeypatch):
    first, last = "-----BEGIN " + "CERTIFICATE-----", "-----END " + "CERTIFICATE-----"
    body = "TUlJRXhhbXBsZU9ubHlOb3RBQ2VydGlmaWNhdGU" * 2
    for sep in ("\n", "\r\n", "\\n", ""):
        found = unlisted("x = " + first + sep + body + sep + last)
        assert [shown for shown, _v in found] == ["pem"], repr(sep)
        # never allowed: the very token that was found, put on the list, is found all the same
        with monkeypatch.context() as m:
            m.setitem(globals(), "ALLOWED", ALLOWED | {v for _shown, v in found})
            assert unlisted("x = " + first + sep + body + sep + last) == found, repr(sep)
    assert [shown for shown, _v in unlisted("-----BEGIN " + "RSA PRIVATE KEY-----\n" + body)] == ["pem"]
    assert unlisted("a block starts with " + first + " and a key's with its own first line") == []
    assert unlisted('header = "' + first + '\\n" + body') == []


def test_a_registry_host_is_found_by_its_account_id():
    assert unlisted("2" * 12 + ".dkr.ecr.us-east-1.amazonaws.com/example") == [("2222", "2" * 12)]
    assert unlisted("123456789012.dkr.ecr.us-east-1.amazonaws.com/example") == []


DRIVER = os.path.join(REPO, "scripts", "aws", "drive-metal.sh")
LAUNCH_AMI = re.compile(r'^AMI="\$\{METAL_AMI:-(ami-[0-9a-f]+)\}"', re.M)


def test_the_image_the_driver_launches_is_on_the_list_and_is_caught_without_it():
    """The image id drive-metal.sh launches by default is the one AWS-shaped value in the tooling
    that is not typed by hand, so a new pin is the likeliest way for this check to meet a value
    nobody listed. With the id on the list the driver is clean; with it taken off, the check
    names it. Both halves, so the list is shown to be what lets the id through."""
    driver = _read(DRIVER)
    m = LAUNCH_AMI.search(driver)
    assert m, "drive-metal.sh no longer sets its default image in the form this test reads"
    ami = m.group(1)
    assert ami in ALLOWED, "the image the driver launches is not on the allowlist (%s[%d chars])" % (ami[:4], len(ami))
    assert _unlisted(driver, ALLOWED) == []
    assert set(_unlisted(driver, ALLOWED - {ami})) == {ami}


def test_every_listed_image_id_is_still_named_by_something():
    """An image id stays on the list while the tooling or a fixture names it, and goes when the
    last of them does: a list that keeps what nothing uses is how a real value comes to look
    like a placeholder. This file is the list, so it does not count."""
    here = os.path.abspath(__file__)
    texts = [_read(p) for p in _files() if os.path.abspath(p) != here]
    unused = sorted(v for v in ALLOWED if v.startswith("ami-") and not any(v in t for t in texts))
    assert not unused, "on the allowlist, and named by nothing: %s" % ", ".join("%s[%d chars]" % (v[:4], len(v)) for v in unused)
