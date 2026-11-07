#!/usr/bin/env python3
"""leakscan.py DIR [LITERAL...] -- refuse to let a fetched capture reach the repo if
anything identifying survived the redaction on the instance.

The redactor masks what it knows; this looks for what should never be there at
all, after the fact, on the operator's machine. UUIDs are checked as well
as addresses and resource ids. Exit 0 when clean, 1 with a list otherwise.

JSON files are scanned in their STRINGS only (keys and values): their numbers are
KVM counters and latencies, and 12-digit counters look exactly like account ids. A
JSON file that does not parse is itself a finding: that is what a redactor that
rewrote a number into "<account>" leaves behind.
JSONL files (2026-10-03) are read the same way line by line, as
capture.py writes them: a line that does not parse is a finding, a blank one holds
nothing. In vss-claim-bridge.log, a line that is dockerd's stamp and then JSON is
read so too, the stamp and every other line as text: the bridge's summary carries a
12-digit anchor that capture.py keeps.
Everything else is scanned as text. LITERALs are exact local values (the key path,
key-pair and security-group names, the PC user name) that must not appear anywhere.

THE TWIN'S SHAPES (plan Phase 4 WP4): six more patterns, for what the
account's replies about the twin can hold. They are in the one list, so they are
read in JSON strings as in text, and in every capture this scans, a bare-metal
session's too.
  iot endpoint       an account's own host of the IoT service: a first label, then
                     .iot.<region>.amazonaws.com, with or without -ats, and the
                     credentials and jobs hosts of the same prefix. The service's
                     own host (iot.<region>...) has no such label and is kept.
                     iot-fips in iot's place is taken too: no page was read for
                     that form, and taking it costs nothing. Any first label
                     counts, so a shared host of the service (data-ats.iot...)
                     is flagged as well, though it names no account. The match
                     begins at that first label and ends at .com: a label more
                     in front of it, and a .cn after .com, are not part of the
                     finding (the twin's redactor takes the whole host).
                     The first label is the whole run of letters, digits and
                     hyphens in front of .iot, from where that run begins: a
                     hyphen may begin it. So a host glued to an option or a
                     diff's minus (-h<host>, --endpoint-<host>, -<host>) is
                     found from the hyphen on; and once a prefix went as a
                     LITERAL, what its mask leaves glued to .iot (-ats.iot...)
                     is a finding of its own, which the twin's redactor masks
                     next (<endpoint-prefix><endpoint>).
  certificate id     "cert/" and 64 hex characters, as a certificate's ARN ends.
                     NOT 64 hex characters alone: that is a sha256 as well, and a
                     vss capture holds one in most of its files. A certificate id
                     or an S3 canonical user id that stands alone is therefore seen
                     only as a LITERAL.
  ecr registry host  <12 digits>.dkr.ecr: the 12-digit rule passes over JSON, where
                     a reply holds this host.
  pem block          a PEM block's first or last line.
  e-mail address     a subscription's reply holds the owner's. A systemd unit's name
                     (getty@tty1.service) has the same form and is kept. Kept with it: an address whose
                     last label is a unit type, if there is one. NOT kept: a git
                     remote in its SSH form (git@<host>:owner/repo.git), which
                     has an address's form. A capture that records one is
                     refused at the fetch, to be looked at; it is no leak.
  iam unique id      AROA, AIDA, ASIA or AKIA and 16 or more capitals and digits: a
                     key's id is 20 characters, a user's or a role's one more.
THE PULL IDENTITY'S TWO SHAPES (plan Phase 6 WP4) need no pattern of their
own: the IoT credential provider's host (<prefix>.credentials.iot.<region>.amazonaws.com,
which `twinctl ecr-config` reads and ecrlogin.py connects to) is a form of the endpoint's
shape, found whole from its prefix on; and a role alias's ARN (:rolealias/) is an ARN and
goes whole as one, here and in the twin's redactor. The alias's own name
(sdv-twin-ecr-pull) is a constant of the spec, which names nobody. A pattern of their
own would count each such host twice and change no verdict.
What these do not see: a name with no shape (a thing's, a rule's, a bucket's), a
bare certificate id, and an account id alone in a JSON string. Those are LITERALs,
which the twin's tooling reads from its state directory (sdv/cloud/redact.py) and
which never lie in the work tree. Nor do they see a secret access key or a session
token, which have no shape, or an IAM unique id that begins with other letters (a
group's, a policy's, an instance profile's): a reply that holds one of those is
not for a capture.

ENCODED TEXT (added 2026-10-08). No shape above sees what
is written in another alphabet, and one planned reply carries exactly that (a
function's log, base64, beside its plain result). Two rules, both REFUSALS: the
twin's redactor masks neither, it gives nothing out, so that the reply is looked
at and the field left out.
  undecoded data     a run of 64 or more characters of the base64 alphabet
                     (letters, digits, + and /), with up to two = after it. NOT
                     taken for one: a run of hex digits alone (a sha256, an
                     image id, a certificate id: those stay what they were); a
                     run with a / in it whose every part between the slashes
                     is hex or at most 32 characters long (a path:
                     /var/lib/docker/overlay2/<64 hex>/merged); and what lies
                     inside a PEM block, which is a finding already.
  percent-encoded X  a text that holds %XX escapes is read a second time with
                     them decoded, and what is found only in that form is
                     named so (percent-encoded arn, percent-encoded e-mail
                     address, a LITERAL too).
Before anything is looked for, terminal colour codes (ESC [ ... letter) are taken
out: one glued in front of twelve digits hid an account id from the 12-digit rule.
What these do not see: a block shorter than 64 characters (base64 of an endpoint's
host alone is 60, of an account id 16); the URL-safe alphabet (- and _), which
every snake_case name would match; a run with slashes that happens to fall into
parts of 32 characters or fewer (rare in a long block, likelier the shorter it
is); text encoded twice, or in any other way (hex, a JSON string inside a JSON
string is read once); and an identifier written in another case or split across
a line.

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
import bisect
import collections
import json
import os
import re
import sys
import urllib.parse

KEEP_IPV4 = re.compile(r"^(192\.168\.100\.\d{1,3}|127\.0\.0\.1|0\.0\.0\.0|255\.255\.255\.255)$")
KEEP_MAC = {"52:54:00:11:11:11"}
# The guest's link-local address, from its fixed MAC; and (2026-10-03) the unspecified and loopback addresses,
# which every host's listener record carries (sshd's [::]:22) and which identify no host.
KEEP_IPV6 = {"fe80::5054:ff:fe11:1111", "::", "::1"}
BRIDGE_LOG = "vss-claim-bridge.log"
STAMPED = re.compile(r"^(\S+ +)([\[{].*)$", re.S)   # `docker logs -t`: dockerd's stamp, then the line
UNIT_TYPE = r"(?:service|socket|target|slice|scope|mount|automount|timer|path|device|swap)"   # systemd's eleven

PATTERNS = [
    ("aws resource id", re.compile(r"(?<![A-Za-z0-9])(?:i|vol|sg|subnet|vpc|eni|snap|r)-[0-9a-f]{8,17}(?![0-9a-f])")),
    ("arn", re.compile(r"arn:aws[a-z-]*:")),
    ("ec2 host name", re.compile(r"\b(?:ip|ec2)-\d{1,3}-\d{1,3}-\d{1,3}-\d{1,3}\b")),
    ("uuid", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    # The twin's shapes (module docstring). tests/test_no_real_identifiers.py spells the first two the same way.
    ("iot endpoint", re.compile(
        r"(?<![A-Za-z0-9-])[A-Za-z0-9-]+(?:\.(?:credentials|jobs))?\.iot(?:-fips)?\.[A-Za-z0-9-]+\.amazonaws\.com", re.I)),
    ("certificate id", re.compile(r"cert/[0-9a-fA-F]{64}(?![0-9a-fA-F])")),
    ("ecr registry host", re.compile(r"(?<![0-9])[0-9]{12}\.dkr\.ecr[.-]")),
    ("pem block", re.compile(r"-----(?:BEGIN|END) [A-Z0-9 ]+-----")),
    # Not a systemd unit's name (UNIT_TYPE below): what follows the @ may not end in a unit type as a whole
    # (getty@tty1.service, name@a.b.service), nor may the match end at one (user@1000.service.d/override.conf).
    # services, with its s, is a domain; a unit type as a first or a middle label is one too.
    ("e-mail address", re.compile(
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@"
        r"(?![A-Za-z0-9.-]*\." + UNIT_TYPE + r"(?![A-Za-z0-9.-]))"
        r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
        r"\.(?!" + UNIT_TYPE + r"(?![A-Za-z0-9-]))[A-Za-z]{2,}(?![A-Za-z0-9-])")),
    ("iam unique id", re.compile(r"(?<![A-Z0-9])(?:AROA|AIDA|ASIA|AKIA)[A-Z0-9]{16,}")),
]
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
MAC = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])")
# 2026-09-27: not after a letter or "_" either -- traceprinter's header ("TRACE_DATE:: ...") and a
# C++ scope ("impl::send") matched as "E::" or "::"; an address is not glued to a word.
IPV6 = re.compile(r"(?<![0-9A-Za-z_:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")
# The same boundary redact-aws.sh masks on: a 12-digit run inside a longer
# word -- a sha256 with twelve decimal digits in it -- is not an account id,
# and the redactor deliberately keeps it, so flagging it here only blocks a
# clean capture with a message that does not print the value.
ACCOUNT = re.compile(r"(?<![0-9A-Za-z_.-])\d{12}(?![0-9A-Za-z_-]|\.\d)")
# Encoded text (module docstring). Each of these is read once from left to right: no pattern here backs up.
ENCODED = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{64,}={0,2}")
HEXRUN = re.compile(r"[0-9A-Fa-f]+")
PATH_PART_MAX = 32          # a design value: a path's part of more letters and digits than this, and not hex, is no word
UNDECODED = "undecoded data"
PERCENT = "percent-encoded "
ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
SGR = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")          # a terminal's colour code and its like
PEM_EDGE = dict(PATTERNS)["pem block"]


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


def not_masked(label):
    """Whether a finding of this name is encoded text: what the twin's redactor refuses outright and has no mask for."""
    return label == UNDECODED or label.startswith(PERCENT)


def undecoded(tok):
    """Whether a run of base64 characters is taken for encoded data (module docstring, ENCODED TEXT)."""
    body = tok.rstrip("=")
    if body != tok:
        return True
    parts = body.split("/")
    if len(parts) == 1:
        return HEXRUN.fullmatch(body) is None
    return any(len(p) > PATH_PART_MAX and HEXRUN.fullmatch(p) is None for p in parts)


def pem_spans(text):
    """Where the bodies of PEM blocks lie: from each first line to the next last line, or to the end of the text when
    none follows (a block cut short). One pass over the edges."""
    starts, ends, start = [], [], None
    for m in PEM_EDGE.finditer(text):
        if m.group(0).startswith("-----BEGIN"):
            if start is None:
                start = m.end()
        elif start is not None:
            starts.append(start)
            ends.append(m.start())
            start = None
    if start is not None:
        starts.append(start)
        ends.append(len(text))
    return starts, ends


def encoded(text):
    """Every run of `text` that is taken for encoded data and lies in no PEM block."""
    starts, ends = pem_spans(text)
    out = []
    for m in ENCODED.finditer(text):
        i = bisect.bisect_right(starts, m.start()) - 1
        if not (i >= 0 and m.start() < ends[i]) and undecoded(m.group(0)):
            out.append(m.group(0))
    return out


def findings(text, is_json, literals):
    """Everything in `text` that must not leave: (the shape's name, the token). Colour codes are taken out first; a
    text with %XX escapes is read again decoded, and what only that reading finds is named as percent-encoded."""
    text = SGR.sub("", text)
    out = shapes(text, is_json, literals)
    if ESCAPE.search(text):
        have = collections.Counter(out)
        for item in shapes(urllib.parse.unquote(text), is_json, literals):
            if have[item] > 0:
                have[item] -= 1
            else:
                out.append((PERCENT + item[0], item[1]))
    return out


def shapes(text, is_json, literals):
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
    out += [(UNDECODED, tok) for tok in encoded(text)]
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
            elif name.endswith(".jsonl"):
                text, bad = jsonl_strings(raw.decode("utf-8", errors="replace"))
                problems += [(rel, "unparseable jsonl line", "line %d" % n) for n in bad]
                is_json = True
            elif name == BRIDGE_LOG:
                text, rest = bridge_log_parts(raw.decode("utf-8", errors="replace"))
                problems += [(rel, label, tok) for label, tok in findings(rest, False, literals)]
                is_json = True
            else:
                text, is_json = raw.decode("utf-8", errors="replace"), False
            problems += [(rel, label, tok) for label, tok in findings(text, is_json, literals)]
    return problems


def jsonl_strings(text):
    """The strings of every JSONL line, and the numbers of the lines that do not parse (a blank one holds nothing)."""
    out, bad = [], []
    for n, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            out += list(json_strings(json.loads(line)))
        except ValueError:
            bad.append(n)
    return "\n".join(out), bad


def bridge_log_parts(text):
    """vss-claim-bridge.log: (the strings of the JSON after dockerd's stamp, every other part as text)."""
    js, rest = [], []
    for line in text.split("\n"):
        m = STAMPED.match(line)
        if m:
            try:
                js += list(json_strings(json.loads(m.group(2))))
                rest.append(m.group(1))
                continue
            except ValueError:
                pass
        rest.append(line)
    return "\n".join(js), "\n".join(rest)


LISTED = 50     # how many findings a scan command lists one by one, in the order of the files' names


def tally(labels):
    """One line for a scan that found more than it lists: how many findings there are of EVERY shape. The list is cut in
    the order of the files' names, so a finding of a kind that a copy refuses outright (encoded data, a document that
    does not parse) can lie past the cut, where only the total said that anything was there. Shapes and counts, no value."""
    count = {}
    for label in labels:
        count[label] = count.get(label, 0) + 1
    return "only the first %d are listed; of all %d, by shape: %s" % (
        LISTED, len(labels), ", ".join("%s %d" % (label, count[label]) for label in sorted(count)))


def main(argv):
    if len(argv) < 2 or not os.path.isdir(argv[1]):
        print("usage: leakscan.py DIR [LITERAL...]", file=sys.stderr)
        return 2
    problems = scan(argv[1], [a for a in argv[2:] if a])
    for rel, label, tok in problems[:LISTED]:
        # The token itself may be the leak: print its shape, not its value.
        print("LEAK %s: %s (%d chars)" % (rel, label, len(tok)))
    if len(problems) > LISTED:
        print(tally([label for _rel, label, _tok in problems]))
    if problems:
        print("leakscan: %d finding(s) -- NOT publishable" % len(problems))
        return 1
    print("leakscan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
