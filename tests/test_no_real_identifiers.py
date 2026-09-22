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

Scope is the three places a session's identifiers pass through. The rest of the
repo is not covered: run records under results/ carry 12-digit KVM counters that
look exactly like account ids, which is why leakscan.py reads JSON numbers as
numbers and why a tree-wide version of this check would be noise.
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
]

# AWS's own documentation account ids, RFC 5737 TEST-NET addresses, and resource
# ids whose body is plainly typed by hand rather than allocated.
ALLOWED = {
    # account ids: AWS's documentation uses the first two; the rest are this
    # repo's stubs, including the one in capture.py's docstring that the
    # redactor must NOT rewrite when capture.py is copied through it.
    "123456789012", "111122223333", "444455556666", "666677778888", "912345678901",
    "113645786915",
    # resource ids
    "i-0123456789abcdef0", "vol-0abcdef1234567890", "sg-0123abcd", "sg-0123abcd4567ef890",
    "subnet-0aaaaaaaaaaaaaaa1", "i-0aaaaaaaaaaaaaaaa", "ami-0abcdef1234567890",
    "sg-0123456789abcdef0",
    # the public Ubuntu arm64 AMI drive-metal.sh launches: a published image id,
    # not a resource belonging to this account.
    "ami-02153ae97d7504246",
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


@pytest.mark.parametrize("path", sorted(_files()), ids=lambda p: os.path.relpath(p, REPO).replace(os.sep, "/"))
def test_only_allowlisted_identifiers(path):
    text = _read(path)
    bad = []
    for rx in (RESOURCE, ACCOUNT):
        bad += [m.group(0) for m in rx.finditer(text) if m.group(0) not in ALLOWED]
    for m in IPV4.finditer(text):
        v = m.group(0)
        if not DOC_OR_PRIVATE.match(v) and all(0 <= int(o) <= 255 for o in v.split(".")):
            bad.append(v)
    rel = os.path.relpath(path, REPO).replace(os.sep, "/")
    # Report the shape, never the value: the value may be the leak, and this
    # message ends up in a public CI log.
    assert not bad, "%s carries %d identifier(s) not on the allowlist: %s" % (
        rel, len(bad), ", ".join(sorted({"%s[%d chars]" % (v[:4], len(v)) for v in bad})))
