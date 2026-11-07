#!/usr/bin/env python3
"""redact.py -- what the twin's account-side tooling prints, and what it copies into a capture directory, goes
through this first (SDV Phase 4 WP4).

WHY
  The account's replies name the account: its id, its endpoint's prefix, the certificate, the chosen names, the
  owner's address. The raw replies stay in the state directory, outside every repository. Anything that leaves it,
  a line on the terminal or a file of a capture, is redacted on the way out, at capture time and not afterwards,
  and the copy is then held to the scanner (scripts/aws/leakscan.py), which refuses what still identifies anything.

THE ORDER (the redaction contract)
  0. a terminal's colour codes (ESC [ ... letter) are taken out, as the scanner takes them out before it looks: one
     glued in front of twelve digits hid an account id from the last step;
  1. the literals, the longest first: the exact local values of the state directory's literals file, each replaced
     by its kind's name in angle brackets. First, so that a chosen name which ends in something a shape would take
     goes whole and under its own kind; the longest first, so that a name which holds another one leaves no rest;
  2. a PEM block, with its body. A first or a last line with no partner is a block cut short: what follows the
     first line, or precedes the last, is key material with nothing to mark its end, so the rest of the text goes;
  3. ARNs, whole: the scanner's pattern is the prefix, here it runs on to the next blank, quote or backslash;
  4. the data endpoint, its host whole: the scanner's match begins at the label next to "iot", so the labels glued
     in front of it go too (in a host with one label more, that is where the account's prefix stands), and a .cn
     after .com; a registry host that starts with an account id; "cert/" and the 64 hex characters after it. Where
     the prefix went as a literal in step 1, what its mask leaves glued to .iot (-ats.iot.<region>...) is the
     scanner's finding too and goes here: <endpoint-prefix><endpoint>;
  5. the scanner's other shapes: an e-mail address, an IAM unique id, an EC2 host name, a resource id, a UUID, an
     address that is not the project's own (the scanner's own keep lists decide);
  6. a standalone 12-digit run, last, by the scanner's own boundary: a run inside a longer token (a sha256, a
     counter, a decimal) is not an account id and stays.
  The pull identity of Phase 6 (WP4) adds no step: the IoT credential provider's host
  (<prefix>.credentials.iot.<region>.amazonaws.com, which `twinctl ecr-config` reads and ecrlogin.py connects to) is a
  form of the endpoint's shape and goes in step 4, its whole host, as <endpoint>; and a role alias's ARN (:rolealias/) is
  an ARN and goes whole as one, in step 3, as <arn>. The alias's own name, sdv-twin-ecr-pull, is a constant of the spec
  and stays.
  Then the result is given to the scanner. While it still finds something the order is applied again, three times
  at the most (a mask can uncover a shape its neighbour hid). What it would flag after that is REFUSED
  (RedactError), never returned: the redactor's output is clean by the scanner, or there is no output. The shapes
  are the scanner's own pattern objects, read from its file, so the two cannot drift apart; a shape the scanner
  knows and this file has no mask for fails at import.

ENCODED TEXT IS REFUSED, NEVER MASKED (the hard review of 2026-10-08)
  Two findings of the scanner have no mask here, by design: "undecoded data", a block of 64 or more base64
  characters, and whatever is found only once a text's percent escapes are decoded. What such text holds is seen by
  no rule above (base64 of a reply that names the endpoint and the account passed the scanner and this file
  unchanged), and a mask in its place would call the copy clean. So the text, the document or the whole copy is
  refused at once, by the finding's name, and nothing is given out: the reply is to be looked at, and the field
  left out of what is copied. One planned reply carries such a field: a function's invoke with its log tail
  (LogResult, base64 of the function's own log). The driver never asks for that field (WP6).

  A sha256 is kept. 64 hex characters after "cert/" are a certificate id; alone they are also a sha256, and a
  capture holds those by the hundred. A bare certificate id, like the S3 canonical user id, has no shape: it goes
  only as a literal.

THE JSON RULE (as scripts/aws/capture.py's)
  A .json file is changed in its STRING TOKENS only, keys included: each is decoded, redacted by the order above
  and written back in place. Every other byte stays: a number is never rewritten (a 12-digit number is a counter
  or a size, and a mask in its place is no longer JSON), nor is the spacing. A document that does not parse is
  refused; so is one in which two keys of an object fall together under redaction, since the copy would then parse
  to one of them. A .jsonl file is the same rule line by line. Anything else is text.

THE LITERALS (state outside every work tree)
  <state directory>/literals.json:  {"v": 1, "literals": {"<kind>": ["<value>", ...], ...}}
  A kind is a short lower-case label (thing, rule, bucket, account, endpoint-prefix, certificate-id,
  notice-address, canonical-user-id, and whatever else the owner adds: names that must never leave this machine go
  here too). Its values are exact strings of 3 characters or more. The file is read from the state directory and
  from NOWHERE INSIDE A WORK TREE: not this repository's tree (found from this file's own place, so a copy without
  .git counts) and not any other checkout (a .git above the file, found by walking up, never by running git). No
  literal lives in a work tree, so a search of the tree for the state's literals has nothing to skip by name.
  A directory with no literals file is refused, not read as "none": a redaction without the list would pass every
  chosen name. Nothing here prints a literal, a kind or the directory.

USE
  import:   lits = load_literals(state_dir);  redact_text(s, lits);  redact_json(s, lits);
            copy_tree(raw_dir, capture_dir, lits);  scan(capture_dir, lits)
  command:  redact.py (--state DIR | --no-literals) filter [--json]     stdin to stdout
            redact.py (--state DIR | --no-literals) copy SRC DST        a file or a directory, all or nothing
            redact.py (--state DIR | --no-literals) scan DIR            the scanner, given the state's literals
  Exit 0; 1 when the scan finds something; 2 when anything is refused, with nothing written to stdout.

A REFUSAL (RedactError) never says where anything lies on this machine: not the state directory, not the source's
or the destination's place, and not the system's own message, which would name one (its reason alone is passed
on). A copy names the file it stops at by its place INSIDE the source (iot/reply.json), which a copy that succeeds
would write into the capture anyway, and only once that name itself passed the redactor; a name the redactor would
change is told as "file N of M". (Where a refusal names a file of this repository, the scanner's or this one, it
is by the name the repository has it under.)

Does not demonstrate: what a real reply holds (no call was ever made; the shapes are the documentation's); that a
name is caught when the literals file lacks it, or when it is written in another case (an upper-cased ARN keeps its
certificate id: `cert/` and a hex literal are read as written), split across a line, or in an encoding the scanner
does not read: a base64 block under 64 characters (an endpoint's host alone is 60), the URL-safe alphabet, hex, text
encoded twice; anything about a JSON number, which is kept even when it equals a literal. A LITERAL IS TAKEN OUT
WHEREVER ITS CHARACTERS STAND, inside a longer word too: a chosen name that is a common word (a rule called
"telemetry") would be cut out of every record that says it, and a short one out of a longer token (twelve digits
inside a digest). Which values may be literals is for whoever writes the file to settle: the driver refuses a
short or common one (WP6); a word boundary here would miss a prefix glued to a name by an underscore. A secret access key and a
session token have no shape, here or in the scanner, and an IAM unique id is known by four prefixes only (a
group's, a policy's or an instance profile's begins otherwise): a reply that holds one passes both unless the
value is a literal, so which replies are ever copied is the driver's to settle (WP6). The masks keep the region
where a literal went first (an endpoint's host without its prefix, a registry host without its account): the
region is not treated as an identifier here. Nothing is shown about time either: pem() is not linear in a text of
many first lines that have no last line (the function says why); no reply is expected to hold one.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Match, Optional, Pattern, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCANNER_FILE = REPO / "scripts" / "aws" / "leakscan.py"

LITERALS_FILE = "literals.json"
LITERALS_VERSION = 1
MIN_LITERAL = 3                 # a shorter literal would shred the text it is taken out of
PASSES = 3                      # how often the order is applied before what the scanner still finds is refused
KIND = re.compile(r"[a-z][a-z0-9-]{0,31}")


class RedactError(Exception):
    """A refusal. Its text never holds a value that was to be redacted, nor where anything lies on this machine: a
    copy names a file by its place inside the source and by nothing else (module docstring, A REFUSAL)."""


class LiteralsError(RedactError):
    """The literals file, or where it lies, is not what it has to be."""


def _scanner() -> Any:
    """The scanner, by its file: its pattern objects and keep lists are the ones used here."""
    spec = importlib.util.spec_from_file_location("_sdv_cloud_leakscan", str(SCANNER_FILE))
    if spec is None or spec.loader is None:
        raise RedactError("the scanner is not where the redactor reads its shapes from (scripts/aws/leakscan.py)")
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    except OSError as e:
        raise RedactError("the scanner cannot be read (scripts/aws/leakscan.py): %s" % (e.strerror or type(e).__name__)) from None
    finally:
        sys.dont_write_bytecode = saved
    return mod


SCANNER = _scanner()

# The scanner's shapes in the order they are masked: (its label, what is written, how far its match is run on so
# the whole identifier goes). The scanner's "arn" is a prefix, its registry host is the account and three labels,
# and its endpoint stops at .com and begins at the label next to "iot" (HEADS); everything else it matches whole.
# "pem block" is not here: a block goes by PEM_BLOCK and pem(), below.
SHAPES: Tuple[Tuple[str, str, str], ...] = (
    ("arn", "<arn>", r"[^\s\"'\\]*"),
    ("iot endpoint", "<endpoint>", r"(?:\.cn(?![A-Za-z0-9-]))?"),
    ("ecr registry host", "<ecr-host>", r"[A-Za-z0-9.-]*"),
    ("certificate id", "cert/<certificate-id>", ""),
    ("e-mail address", "<e-mail>", ""),
    ("iam unique id", "<iam-id>", ""),
    ("ec2 host name", "<host>", ""),
    ("aws resource id", "<resource-id>", ""),
    ("uuid", "<uuid>", ""),
)
# What is taken in FRONT of a scanner's match. An endpoint's host goes whole: the scanner matches from the label next
# to "iot" (or to "credentials" or "jobs"), and a host with one label more between the account's prefix and "iot"
# would keep its prefix in front of the mask. Every label glued to the match is taken, from where the run of host
# characters begins: tried there only, so a long dotted token is read once. That the service has such a host is
# UNVERIFIED (no page was read for it); the wider net costs nothing.
HEADS = {"iot endpoint": r"(?:(?<![A-Za-z0-9.-])[A-Za-z0-9.-]*[A-Za-z0-9-]\.)?"}
PEM_LABEL = "pem block"
PEM_BLOCK = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----.*?-----END \1-----", re.S)
# Every mask this file writes for a shape. A literal that one of them spells could never be taken out of a text.
MASKS = tuple(mask for _label, mask, _tail in SHAPES) + ("<pem>", "<pem-cut>", "<ip>", "<mac>", "<ipv6>", "<account>")


def check_shapes() -> None:
    """Every shape the scanner knows has a mask here, and nothing here names a shape it does not know; nor is there
    a head for anything but a shape of SHAPES (it would be a silent no-op)."""
    theirs = [label for label, _rx in SCANNER.PATTERNS]
    masked = [label for label, _mask, _tail in SHAPES]
    mine = masked + [PEM_LABEL]
    unknown = sorted(set(theirs) - set(mine))
    gone = sorted((set(mine) - set(theirs)) | (set(HEADS) - set(masked)))
    if unknown or gone or len(theirs) != len(set(theirs)):
        raise RedactError("the scanner's shapes and the redactor's masks differ (no mask for: %s; no shape for: %s): "
                          "sdv/cloud/redact.py's SHAPES follows scripts/aws/leakscan.py's PATTERNS"
                          % (", ".join(unknown) or "none", ", ".join(gone) or "none"))


check_shapes()


def _rules() -> List[Tuple[Pattern[str], str]]:
    by_label = dict(SCANNER.PATTERNS)
    out: List[Tuple[Pattern[str], str]] = []
    for label, mask, tail in SHAPES:
        rx, head = by_label[label], HEADS.get(label, "")
        out.append((re.compile(head + rx.pattern + tail, rx.flags) if head or tail else rx, mask))
    return out


RULES = _rules()
PEM_EDGE: Pattern[str] = dict(SCANNER.PATTERNS)[PEM_LABEL]


# ------------------------------------------------------------------------------------------- the literals

class Literals:
    """The exact local values to take out, by kind. Refuses a value that cannot be taken out reliably; no message
    holds a value or a kind (a kind may be a value pasted into the wrong place): each is named by its position."""

    def __init__(self, by_kind: Mapping[str, Sequence[str]]) -> None:
        if not isinstance(by_kind, Mapping):
            raise LiteralsError("the literals are not an object of kinds")
        chosen: Dict[str, str] = {}
        kinds = list(by_kind)
        for k, kind in enumerate(kinds, 1):
            where = "kind %d of %d" % (k, len(kinds))
            if not isinstance(kind, str) or not KIND.fullmatch(kind):
                raise LiteralsError("%s is not a label (a lower-case letter, then at most 31 lower-case letters, digits or hyphens)" % where)
            values = by_kind[kind]
            if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
                raise LiteralsError("%s does not hold a list of values" % where)
            for i, value in enumerate(values, 1):
                at = "value %d of %s" % (i, where)
                if not isinstance(value, str):
                    raise LiteralsError("%s is not a string" % at)
                if len(value) < MIN_LITERAL:
                    raise LiteralsError("%s has %d character(s): a literal has %d or more" % (at, len(value), MIN_LITERAL))
                if value != value.strip() or any(ord(c) < 32 for c in value):
                    raise LiteralsError("%s begins or ends with a blank, or holds a control character: it would never match" % at)
                if kind < chosen.get(value, "~"):                  # under two kinds: the first kind by name, whatever the order
                    chosen[value] = kind
        masks = set(MASKS) | {"<%s>" % kind for kind in kinds}
        for k, kind in enumerate(kinds, 1):
            for i, value in enumerate(by_kind[kind], 1):
                if any(value in mask for mask in masks):
                    raise LiteralsError("value %d of kind %d of %d is spelled by a mask the redactor writes: it could not be told from "
                                        "the mask" % (i, k, len(kinds)))
        ordered = sorted(chosen, key=lambda v: (-len(v), v))
        self.values: Tuple[str, ...] = tuple(ordered)                                  # the longest first
        self.pairs: Tuple[Tuple[str, str], ...] = tuple((v, "<%s>" % chosen[v]) for v in ordered)


NONE = Literals({})


def _same(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and os.path.samefile(str(a), str(b))
    except OSError:
        return False


def in_a_work_tree(path: Path) -> str:
    """Why `path` may not hold a literal ("" when it may): it lies in this repository's tree, or in any work tree.
    Judged twice, on the path as given and on the path its links lead to, and never by running git. The answer
    names no directory."""
    given = Path(os.path.abspath(str(path)))
    forms = [given]
    try:
        forms.append(path.resolve())
    except (OSError, RuntimeError):
        return "inside a work tree, or not to be told from one (its links cannot be followed)"
    roots = [Path(os.path.abspath(str(REPO)))]
    try:
        roots.append(REPO.resolve())
    except (OSError, RuntimeError):
        pass
    for form in forms:
        chain = [form] + list(form.parents)
        norm = os.path.normcase(str(form))
        for root in roots:
            r = os.path.normcase(str(root))
            if norm == r or norm.startswith(r.rstrip(os.sep) + os.sep) or any(_same(a, root) for a in chain):
                return "inside a work tree (this repository's own tree)"
        for n, a in enumerate(chain[1:], 1):
            if os.path.lexists(str(a / ".git")):
                return "inside a work tree (a .git lies %d level(s) above it)" % n
    return ""


def load_literals(state_dir: Any) -> Literals:
    """The literals of <state_dir>/literals.json. Refused, before anything is read, when that file would lie inside
    a work tree; refused when it is not there or is in another form."""
    path = Path(os.path.expanduser(str(state_dir))) / LITERALS_FILE
    why = in_a_work_tree(path)
    if why:
        raise LiteralsError("the state directory's %s would be read from %s: literals live outside every work tree, in the state "
                            "directory (nothing was read)" % (LITERALS_FILE, why))
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise LiteralsError("the state directory holds no readable %s (%s): a redaction without the literals would pass every chosen "
                            "name, so none is made" % (LITERALS_FILE, e.strerror or type(e).__name__)) from None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise LiteralsError("the state directory's %s does not parse as JSON" % LITERALS_FILE) from None
    if not isinstance(doc, dict) or set(doc) != {"v", "literals"}:
        raise LiteralsError('the state directory\'s %s is not {"v": %d, "literals": {...}} and nothing else (a misspelt key must not '
                            'read as "no literals")' % (LITERALS_FILE, LITERALS_VERSION))
    if type(doc["v"]) is not int or doc["v"] != LITERALS_VERSION:
        raise LiteralsError("the state directory's %s is not version %d" % (LITERALS_FILE, LITERALS_VERSION))
    if not isinstance(doc["literals"], dict):
        raise LiteralsError("the state directory's %s does not hold an object of kinds" % LITERALS_FILE)
    return Literals(doc["literals"])


# ------------------------------------------------------------------------------------------- the text rule

def pem(text: str) -> str:
    """Every PEM block replaced whole; then a first or last line left without its partner takes the rest with it.

    Not linear in every text. From each first line that has no last line of its own the block pattern reads on to
    the end of the text, and each last line that has no first line costs one copy of what follows it: a text of k
    such lines and n characters costs about k times n. No reply or capture is expected to hold many, and nothing
    here bounds it."""
    out = PEM_BLOCK.sub("<pem>", text)
    while True:
        m = PEM_EDGE.search(out)
        if m is None:
            return out
        if m.group(0).startswith("-----BEGIN"):
            return out[:m.start()] + "<pem-cut>"
        out = "<pem-cut>" + out[m.end():]


def _ip(m: Match[str]) -> str:
    return m.group(0) if SCANNER.KEEP_IPV4.match(m.group(0)) else "<ip>"


def _mac(m: Match[str]) -> str:
    return m.group(0) if m.group(0).lower() in SCANNER.KEEP_MAC else "<mac>"


def _ipv6(m: Match[str]) -> str:
    tok = m.group(0)
    if ("::" in tok or tok.count(":") >= 5) and tok.lower() not in SCANNER.KEEP_IPV6 and not SCANNER.MAC.fullmatch(tok):
        return "<ipv6>"
    return tok


def _once(text: str, literals: Literals) -> str:
    out = SCANNER.SGR.sub("", text)
    for value, mask in literals.pairs:
        out = out.replace(value, mask)
    out = pem(out)
    for rx, mask in RULES:
        out = rx.sub(mask, out)
    out = SCANNER.IPV4.sub(_ip, out)
    out = SCANNER.MAC.sub(_mac, out)
    out = SCANNER.IPV6.sub(_ipv6, out)
    return SCANNER.ACCOUNT.sub("<account>", out)


_ENCODED = ("the text holds encoded data (%s): refused and not masked, because no rule here sees what it holds; nothing is "
            "given out (look at the reply, and leave that field out of the copy)")


def redact_text(text: str, literals: Literals) -> str:
    """`text` by the order of the module docstring. Raises RedactError, naming shapes and never values, when the
    scanner would still flag the result.

    One pass is the rule. A mask can stand where the character stood that kept a neighbour from being a shape
    (64 hex characters after cert/ with an address glued on are no certificate id until the address is a mask), so
    while the scanner still finds something the pass is made again, PASSES times at the most, before refusing.

    Encoded data is refused, not masked (the module docstring), and it is looked for twice: in the text as it came
    in, and in what each pass leaves."""
    out = text
    # As it came in, before any literal's mask: a literal whose characters a block happens to hold would cut the block
    # in two, each half too short to be seen. A block that lies wholly inside a literal is that literal's business
    # and goes under its kind; a PEM block's body is the block's (pem(): a block cut short at either end too).
    blocks = [b for b in SCANNER.encoded(pem(SCANNER.SGR.sub("", text))) if not any(b in value for value in literals.values)]
    if blocks:
        raise RedactError(_ENCODED % SCANNER.UNDECODED)
    left: List[Tuple[str, str]] = []
    for _ in range(PASSES):
        out = _once(out, literals)
        left = SCANNER.findings(out, False, literals.values)
        if not left:
            return out
        encoded = sorted({label for label, _tok in left if SCANNER.not_masked(label)})
        if encoded:
            raise RedactError(_ENCODED % ", ".join(encoded))
    raise RedactError("the redaction left %d thing(s) the scanner refuses (%s): nothing is given out"
                      % (len(left), ", ".join(sorted({label for label, _tok in left}))))


# ------------------------------------------------------------------------------------------- the JSON rule

JSTR = re.compile(r'"(?:[^"\\]|\\.)*"')         # a string token: outside a string, JSON has no quote


def _repeated_keys(text: str) -> int:
    """How many keys of the document repeat an earlier key of their own object."""
    count = 0

    def pairs(items: List[Tuple[str, Any]]) -> Dict[str, Any]:
        nonlocal count
        count += len(items) - len({k for k, _v in items})
        return dict(items)

    json.loads(text, object_pairs_hook=pairs)
    return count


def redact_json(text: str, literals: Literals) -> str:
    """A JSON document's text with every string token redacted, keys too, and every other byte as it was."""
    try:
        before = _repeated_keys(text)
    except ValueError:
        raise RedactError("a JSON document that does not parse: refused, not copied as text") from None
    done: Dict[str, str] = {}

    def one(m: Match[str]) -> str:
        tok = m.group(0)
        if tok not in done:
            value = json.loads(tok)
            new = redact_text(value, literals)
            done[tok] = tok if new == value else json.dumps(new, ensure_ascii=tok.isascii())
        return done[tok]

    out = JSTR.sub(one, text)
    if out != text and _repeated_keys(out) != before:
        raise RedactError("two keys of one object fall together under redaction: the copy would parse to one of them, so none is made")
    return out


def redact_jsonl(text: str, literals: Literals) -> str:
    """JSON lines by the JSON rule, line by line; a blank line holds nothing and stays."""
    lines = text.split("\n")
    out = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            out.append(line)
            continue
        try:
            out.append(redact_json(line, literals))
        except RedactError as e:
            raise RedactError("line %d: %s" % (n, e)) from None
    return "\n".join(out)


def redact_named(name: str, data: bytes, literals: Literals) -> bytes:
    """A file's bytes by the rule its name asks for: .json, .jsonl, or text. UTF-8 or nothing."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RedactError("not UTF-8: what the redactor cannot read, it does not copy") from None
    if name.endswith(".json"):
        out = redact_json(text, literals)
    elif name.endswith(".jsonl"):
        out = redact_jsonl(text, literals)
    else:
        out = redact_text(text, literals)
    return utf8(out)


def utf8(text: str) -> bytes:
    """`text` as the bytes that are written. A JSON string may spell a lone surrogate as an escape; when such a string
    changes beside a character that is not ASCII it is written anew unescaped, and no UTF-8 file can hold it."""
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        raise RedactError("the redacted text cannot be written as UTF-8 (a lone surrogate, spelled as an escape in a string that "
                          "changed): refused, not copied") from None


# ------------------------------------------------------------------------------------------- copies and the scan

def _plan(src: Path, literals: Literals) -> List[Tuple[str, bytes, bool]]:
    """(relative name, redacted bytes, whether they differ) for the file `src` or every file under the directory.

    A refusal names the file it stops at by that relative name, its place inside the source, and by nothing else of
    the machine: the name was redacted first and is refused, unprinted, if that changes it, and of the system's
    message for a file that cannot be read only the reason is passed on (the message itself carries the path)."""
    if src.is_file():
        files = [(src.name, src)]
    elif src.is_dir():
        files = sorted((str(p.relative_to(src)).replace(os.sep, "/"), p) for p in src.rglob("*") if p.is_file())
    else:
        raise RedactError("the source is neither a file nor a directory")
    out = []
    for n, (rel, p) in enumerate(files, 1):
        if redact_text(rel, literals) != rel:
            raise RedactError("file %d of %d has an identifier in its own name (the name is not printed): rename the source" % (n, len(files)))
        try:
            data = p.read_bytes()
            new = redact_named(p.name, data, literals)
        except OSError as e:
            raise RedactError("%s: cannot be read (%s)" % (rel, e.strerror or type(e).__name__)) from None
        except RedactError as e:
            raise RedactError("%s: %s" % (rel, e)) from None
        out.append((rel, new, new != data))
    return out


def copy_tree(src: Any, dst: Any, literals: Literals) -> List[Tuple[str, bool]]:
    """Every file under the directory `src` into the directory `dst`, redacted; [(relative name, changed)]. All or
    nothing: every file is redacted before the first is written, `dst` must be absent or empty, and a write the file
    system refuses takes back what was written (_write)."""
    s, d = Path(src), Path(dst)
    if not s.is_dir():
        raise RedactError("the source is not a directory")
    if d.exists() and (not d.is_dir() or any(d.iterdir())):
        raise RedactError("the destination is not an empty directory: captures are not mixed")
    plan = _plan(s, literals)
    _write([(d / rel, data) for rel, data, _changed in plan], d)
    return [(rel, changed) for rel, _data, changed in plan]


def _write(files: Sequence[Tuple[Path, bytes]], top: Optional[Path]) -> None:
    """Each file written, its directories made first, and `top` made even when no file lies in it. When the file
    system refuses one of them, the files this call wrote and the directories it made are taken back, as far as the
    file system lets them be, and the refusal is a RedactError that names no path: a capture is whole or it is not
    there, and the system's own message would print where it lies."""
    made: List[Path] = []
    written: List[Path] = []

    def mkdirs(path: Path) -> None:
        missing = []
        a = path
        while not a.exists() and a.parent != a:
            missing.append(a)
            a = a.parent
        made.extend(reversed(missing))                  # noted before they are made: a failure may leave some of them
        path.mkdir(parents=True, exist_ok=True)

    try:
        for target, data in files:
            mkdirs(target.parent)
            written.append(target)
            target.write_bytes(data)
        if top is not None:
            mkdirs(top)
    except OSError as e:
        for target in reversed(written):
            try:
                target.unlink()
            except OSError:
                pass
        for a in reversed(made):                        # the deepest first; one that holds something stays
            try:
                a.rmdir()
            except OSError:
                pass
        raise RedactError("the destination cannot be written (%s): what this copy had written was taken back"
                          % (e.strerror or type(e).__name__)) from None


def copy_file(src: Any, dst: Any, literals: Literals) -> bool:
    """The file `src` to the new file `dst`, redacted by the rule `src`'s name asks for; whether it changed."""
    s, d = Path(src), Path(dst)
    if not s.is_file():
        raise RedactError("the source is not a file")
    if d.exists():
        raise RedactError("the destination exists: a capture's file is not overwritten")
    (_rel, data, changed), = _plan(s, literals)
    _write([(d, data)], None)
    return changed


def scan(root: Any, literals: Literals) -> List[Tuple[str, str, int]]:
    """The scanner over a capture directory, given the literals: [(file, shape, how long the finding is)]. Never
    the finding itself."""
    if not Path(root).is_dir():
        raise RedactError("the directory to scan is not a directory")
    try:
        found = SCANNER.scan(str(root), list(literals.values))
    except OSError as e:
        raise RedactError("a file of the directory to scan cannot be read (%s): a capture that was not read whole is not "
                          "called clean" % (e.strerror or type(e).__name__)) from None
    return [(rel, label, len(tok)) for rel, label, tok in found]


# ------------------------------------------------------------------------------------------- the command line

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="redact.py", description="Redact what leaves the twin's state directory, and scan what left it.")
    lit = ap.add_mutually_exclusive_group(required=True)
    lit.add_argument("--state", metavar="DIR", help="the state directory, outside every work tree; its literals.json is read")
    lit.add_argument("--no-literals", action="store_true", help="shapes only: said aloud, never the default")
    sub = ap.add_subparsers(dest="command", required=True)
    f = sub.add_parser("filter", help="stdin to stdout")
    f.add_argument("--json", action="store_true", help="stdin is one JSON document: strings only")
    c = sub.add_parser("copy", help="a file or a directory into a capture, all or nothing")
    c.add_argument("src")
    c.add_argument("dst")
    s = sub.add_parser("scan", help="the scanner over a capture directory, with the state's literals")
    s.add_argument("dir")
    args = ap.parse_args(argv)
    try:
        literals = NONE if args.no_literals else load_literals(args.state)
        if args.command == "filter":
            try:
                text = sys.stdin.buffer.read().decode("utf-8")
            except UnicodeDecodeError:
                raise RedactError("stdin is not UTF-8: what the redactor cannot read, it does not pass on") from None
            out = redact_json(text, literals) if args.json else redact_text(text, literals)
            sys.stdout.buffer.write(utf8(out))
            sys.stdout.buffer.flush()
            return 0
        if args.command == "copy":
            if Path(args.src).is_dir():
                done = copy_tree(args.src, args.dst, literals)
            else:
                done = [(Path(args.src).name, copy_file(args.src, args.dst, literals))]
            print("redact: %d file(s) copied, %d of them changed" % (len(done), sum(1 for _rel, changed in done if changed)))
            return 0
        found = scan(args.dir, literals)
        for rel, label, length in found[:SCANNER.LISTED]:
            print("LEAK %s: %s (%d chars)" % (rel, label, length))
        if len(found) > SCANNER.LISTED:                 # every shape is said, also one whose findings lie past the listed ones
            print("redact: " + SCANNER.tally([label for _rel, label, _length in found]))
        if found:
            print("redact: %d finding(s): not to leave this machine" % len(found))
            return 1
        print("redact: clean")
        return 0
    except RedactError as e:
        print("redact: %s" % e, file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        # What no rule above foresaw (stdin or stdout going away). Its own message may name a path or quote the
        # text, so only its kind is passed on; and exit 1 stays the scan's "found something".
        print("redact: refused (%s)" % type(e).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
