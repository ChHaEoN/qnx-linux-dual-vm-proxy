#!/usr/bin/env python3
"""leakscan.py DIR [LITERAL...] -- refuse to let a fetched capture reach the repo if
anything identifying survived the redaction on the instance.

The redactor masks what it knows; this looks for what should never be there at
all, after the fact, on the operator's machine. It is the check the 2026-09-22
session ran by hand ("scanned after the fetch"), and it caught one thing the
redactor had passed (a root PARTUUID). Exit 0 when clean, 1 with a list otherwise.

JSON files are scanned in their STRINGS only (keys and values): their numbers are
KVM counters and latencies, and 12-digit counters look exactly like account ids. A
JSON file that does not parse is itself a finding: that is what a redactor that
rewrote a number into "<account>" leaves behind.
Everything else is scanned as text. LITERALs are exact local values (the key path,
key-pair and security-group names, the PC user name) that must not appear anywhere.
"""
import json
import os
import re
import sys

KEEP_IPV4 = re.compile(r"^(192\.168\.100\.\d{1,3}|127\.0\.0\.1|0\.0\.0\.0|255\.255\.255\.255)$")
KEEP_MAC = {"52:54:00:11:11:11"}
KEEP_IPV6 = {"fe80::5054:ff:fe11:1111"}   # the guest's link-local address, from its fixed MAC

PATTERNS = [
    ("aws resource id", re.compile(r"(?<![A-Za-z0-9])(?:i|vol|sg|subnet|vpc|eni|snap|r)-[0-9a-f]{8,17}(?![0-9a-f])")),
    ("arn", re.compile(r"arn:aws[a-z-]*:")),
    ("ec2 host name", re.compile(r"\b(?:ip|ec2)-\d{1,3}-\d{1,3}-\d{1,3}-\d{1,3}\b")),
    ("uuid", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
]
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
MAC = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])")
IPV6 = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")
# The same boundary redact-aws.sh masks on: a 12-digit run inside a longer
# word -- a sha256 with twelve decimal digits in it -- is not an account id,
# and the redactor deliberately keeps it, so flagging it here only blocks a
# clean capture with a message that does not print the value.
ACCOUNT = re.compile(r"(?<![0-9A-Za-z_.-])\d{12}(?![0-9A-Za-z_-]|\.\d)")


def json_strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from json_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from json_strings(v)
    elif isinstance(o, str):
        yield o


def findings(text, is_json, literals):
    out = []
    for label, rx in PATTERNS:
        out += [(label, m.group(0)) for m in rx.finditer(text)]
    out += [("ipv4", m.group(0)) for m in IPV4.finditer(text) if not KEEP_IPV4.match(m.group(0))]
    out += [("mac", m.group(0)) for m in MAC.finditer(text) if m.group(0).lower() not in KEEP_MAC]
    for m in IPV6.finditer(text):
        tok = m.group(0)
        # A real IPv6 address has "::" or at least five colons; this keeps
        # clock times (13:20:34) and version strings out.
        if ("::" in tok or tok.count(":") >= 5) and tok.lower() not in KEEP_IPV6 and not MAC.fullmatch(tok):
            out.append(("ipv6", tok))
    if not is_json:
        out += [("12-digit number", m.group(0)) for m in ACCOUNT.finditer(text)]
    out += [("local literal", lit) for lit in literals if lit and lit in text]
    return out


def scan(root, literals=()):
    problems = []
    for d, _dirs, files in os.walk(root):
        for name in sorted(files):
            p = os.path.join(d, name)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            raw = open(p, "rb").read()
            if name.endswith(".json"):
                try:
                    text = "\n".join(json_strings(json.loads(raw.decode("utf-8"))))
                except (UnicodeDecodeError, ValueError) as e:
                    problems.append((rel, "unparseable json", str(e)[:60]))
                    continue
                is_json = True
            else:
                text, is_json = raw.decode("utf-8", errors="replace"), False
            problems += [(rel, label, tok) for label, tok in findings(text, is_json, literals)]
    return problems


def main(argv):
    if len(argv) < 2 or not os.path.isdir(argv[1]):
        print("usage: leakscan.py DIR [LITERAL...]", file=sys.stderr)
        return 2
    problems = scan(argv[1], [a for a in argv[2:] if a])
    for rel, label, tok in problems[:50]:
        # The token itself may be the leak: print its shape, not its value.
        print("LEAK %s: %s (%d chars)" % (rel, label, len(tok)))
    if problems:
        print("leakscan: %d finding(s) -- NOT publishable" % len(problems))
        return 1
    print("leakscan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
