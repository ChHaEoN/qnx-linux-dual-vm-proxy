#!/usr/bin/env python3
"""capture.py REC PUB REDACTOR -- build the publishable copy of a run ON the host
that ran it, redacted at capture time.

The text redactor's account rule also matches numeric data, including KVM
counters. JSON therefore separates strings from numbers:

  *.json   parsed. Every STRING in it (keys and values) goes through the
           redactor; numbers never do, because nothing that writes these files
           reads an AWS identity. If no string changes, the file is copied
           byte-for-byte. If one does, arm files (lat-, kvm-, db-burst, ex-) are
           refused outright -- they should hold no host identity at all -- and
           any other JSON (stamp.json) gets those strings replaced in its text,
           after which every number is checked to be unchanged.
  *.jsonl  (2026-10-03) the same JSON rule, line by line: every
           line parsed, the file's unique strings redacted in ONE redactor call
           (shared across the file), numbers never touched. Monotonic timestamps
           may have the account mask's shape. A last line with
           no newline that does not parse, or does not decode (cut inside a
           multi-byte character), is a torn write: dropped and noted. Any other
           line that does not parse or decode refuses the capture (in a vss stem
           that did not end whole, see below).
  JSON and JSONL strings also lose every IPv6 address but "::", "::1" and the
           guest's link-local one, by leakscan.py's own pattern. The redactor
           masks IPv6 by the same rule since 2026-10-08, so this pass comes
           second and finds nothing left; it stays, whichever redactor a
           session carries. Every host's listener record carries sshd's.
  other    text files through the redactor as they are; *.so and the
           .run-start marker are not published.

A VSS RECORD (plan Phase 3 WP3i) is a
REC with a top-level vss-* directory, or ota-drill (run-ota-drill.sh's, SDV
Phase 6 WP6), or aw-setup or aw-suite (run-aw-setup.sh's and run-aw-suite.sh's,
SDV Phase 8 WP6 9.2), or aw-g1 (run-aw-g1.sh's, SDV Phase 8 WP8), which only
the harness phase's vss harnesses make. For it:

  - the evidence is a vss stem whose status file's last status= line is DONE
    and that has its own result file (raw/setup.json, raw/suite.json,
    ota-drill's raw/drill.json, aw-setup's raw/setup.json, aw-suite's
    raw/suite.json, aw-g1's raw/g1.json); or one
    whose last line is TIMEOUT or FAILED, with or without a result file: a stem
    that stopped before its end is packed as it stands, for its diagnostics,
    marked by that line and in this report, a missing result file noted; or one
    with no done that CAPTURE_INCOMPLETE names. The capture phase names a stem
    so only past wait-run's give-up point; a stem with no done that it does not
    name refuses the capture, as its harness may still be running;
  - a whitelist replaces the whole-tree walk (VSS_WHITELIST below). Nothing
    under an in/ or bin/ directory, no scenario.lock, *.so or .run-start, and
    nothing unlisted is published, and each file left out is named here;
  - vss-claim-bridge.log's lines that are dockerd's stamp and then JSON get the
    JSON rule for that JSON (the bridge's summary carries a 12-digit anchor),
    the stamp and every other line the text rule;
  - a JSON string holding a newline is redacted line by line instead of
    refusing the capture;
  - in a stem that did not end whole (TIMEOUT, FAILED, INCOMPLETE, NO STATUS) a
    JSON or JSONL file that does not parse is left out and named: a cap, a kill
    or a harness still writing may have cut it short. In a DONE stem, or in
    tooling/, it refuses the capture, as in an A6 record;
  - each file is read once, and what is published is the bytes that were read
    and checked; a file the walk listed and the read cannot open (removed
    meanwhile by a harness still running, or unreadable) is left out and named;
  - a text file (the bridge log's stamps and other lines too) also loses every
    IPv6 address after the redactor, by the JSON strings' rule above: an
    instance address in apt's or a harness's error text would otherwise reach
    PUB, and the fetch's leakscan refuses the record (2026-10-04);
  - a text file that did not end in a newline is published without one: awk's
    print adds it, and an INCOMPLETE stem's run.log cut inside a line would
    read as whole;
  - every substitution is counted here, per file: the 12-digit ones the
    redactor made in each other text file, the IPv6 ones in each text file,
    and in each JSON or JSONL file, and the bridge log's JSON, every mask the
    redactor or the IPv6 rule wrote into a string, by kind. A mask written into
    data (a 12-digit run inside a longer one once lost its last 12 digits that
    way) is then visible in the record and not only by a diff with a copy that
    died with the instance;
  - a FAILED stem's line quotes the harness's own last status line beside the
    detached runner's "status=FAILED rc=N", so it says where the run failed;
  - this report goes into PUB as capture.log, so the fetched record says what
    was left out and how each stem ended.

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
import concurrent.futures
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

if len(sys.argv) != 4:
    sys.exit("usage: capture.py REC PUB REDACTOR")
rec, pub, redactor = sys.argv[1:4]
ARM = ("lat-", "kvm-", "db-burst", "ex-")   # ex-: run-bellrobust.sh's exchange sets, the same probe's output

# A capture of nothing must fail, not "succeed" with an empty record: a skipped
# or failed ladder would otherwise be packed and fetched as if it had run. The check is
# over the whole session directory: somewhere in it a stamp.json, and somewhere a probe's
# output (lat-*.json, or ex-*.json from run-bellrobust.sh, which keeps no lat-*.json,
# 2026-09-29) or an exchange-set line in run-bellrobust.sh's scenarios.log. The probe
# writes no ex- file for a set it aborts (a non-zero exit), so a run in which every set
# that ran was aborted has only those lines, and it must still be captured: it is a
# result. A session in which nothing anywhere ran is refused.
EXSET = re.compile(r"^\S+ rc=\d+ t0=\d+ t1=\d+$", re.M)


def ran_sets():
    for d, _s, fs in os.walk(rec):
        if "scenarios.log" in fs:
            with open(os.path.join(d, "scenarios.log"), encoding="utf-8", errors="replace") as f:
                if EXSET.search(f.read()):
                    return True
    return False


# --- a vss record (plan Phase 3 WP3i) ------------------------------------------------------------
VSS_STEM = re.compile(r"^(vss-[A-Za-z0-9._-]+|ota-drill|aw-setup|aw-suite|aw-g1)$")
# A stem's own result file under raw/: a vss harness's is named after its stem (setup.json, suite.json), run-ota-drill.sh's
# is drill.json (SDV Phase 6 WP6), and the aw harnesses' are setup.json and suite.json (SDV Phase 8 WP6 9.2).
RESULT_FILE = {"ota-drill": "drill.json", "aw-setup": "setup.json", "aw-suite": "suite.json", "aw-g1": "g1.json"}
# Every path a vss record publishes, relative to REC, one fnmatch pattern per path component
# (each stem's detach.log is the detached runner's own output). "*" never crosses a "/".
VSS_WHITELIST = (
    "host-facts.txt", "quiesce.txt", "tooling/*",
    "vss-*/host-before.txt", "vss-*/host-after.txt", "vss-*/run.log", "vss-*/status", "vss-*/detach.log",
    "vss-setup/raw/setup.json", "vss-setup/raw/net-*.txt", "vss-setup/raw/docker-facts.txt",
    "vss-setup/raw/probes.json", "vss-setup/raw/venv.txt", "vss-setup/raw/smoke-*.txt", "vss-setup/raw/df.txt",
    "vss-setup/raw/apt.log", "vss-setup/raw/guest/*",
    "vss-suite/raw/suite.json", "vss-suite/raw/guest/*",
    "vss-suite/raw/runs/*/manifest.json", "vss-suite/raw/runs/*/ownership.json", "vss-suite/raw/runs/*/step3.json",
    "vss-suite/raw/runs/*compare*/compare.json",
    # run-ota-drill.sh (SDV Phase 6 WP6): the stem's run.log, status, host-before.txt
    # and host-after.txt, and its record; never its detach.log
    "ota-drill/host-before.txt", "ota-drill/host-after.txt", "ota-drill/run.log", "ota-drill/status",
    "ota-drill/raw/drill.json", "ota-drill/raw/drill-result.json", "ota-drill/raw/ota-lite.jsonl", "ota-drill/raw/state.json",
    "ota-drill/raw/status*.json", "ota-drill/raw/manifest.json", "ota-drill/raw/venv.txt",
    # run-aw-setup.sh and run-aw-suite.sh (SDV Phase 8 WP6 9.2): each stem's run.log, status,
    # host-before.txt and host-after.txt (the host check in both), and its record; never its detach.log, never a ROS
    # log directory, a bag directory or ~/.ros
    "aw-setup/host-before.txt", "aw-setup/host-after.txt", "aw-setup/run.log", "aw-setup/status",
    "aw-setup/raw/setup.json", "aw-setup/raw/inputs.txt",
    "aw-suite/host-before.txt", "aw-suite/host-after.txt", "aw-suite/run.log", "aw-suite/status",
    "aw-suite/raw/suite.json", "aw-suite/raw/*/replies.jsonl", "aw-suite/raw/*/claim-node.log",
    "aw-suite/raw/*/scenario.jsonl", "aw-suite/raw/*/guest-console.log", "aw-suite/raw/*/export.jsonl",
    "aw-suite/raw/*/unit.json",
    # run-aw-g1.sh, the rehearsal of gate G1 (SDV Phase 8 WP8): the stem's four files and its record, and the kill
    # unit's under raw/kill; never its detach.log, never a ROS log directory (its working directory holds those, outside the record)
    "aw-g1/host-before.txt", "aw-g1/host-after.txt", "aw-g1/run.log", "aw-g1/status",
    "aw-g1/raw/*", "aw-g1/raw/*/*", "aw-g1/raw/*/*/*", "aw-g1/raw/kill/*/*/*",
) + tuple("vss-suite/raw/runs/*/*/" + p for p in (                  # each step-3 run's own directory
    "plan.json", "bridge-script.json", "bridge-header.json", "bridge/*", "guest-console.log", "listeners.json",
    "attribution.json", "player.log", "*.log", "result.json", "vss-recorder.csv", "*.jsonl"))
NEVER_DIRS = {"in", "bin"}     # a step-3 run's staged inputs and the native monitor's build: never, at any depth
NEVER_FILES = {"scenario.lock", ".run-start"}
BRIDGE_LOG = "vss-claim-bridge.log"
STAMPED = re.compile(r"^(\S+ +)([\[{].*)$", re.S)   # `docker logs -t`: dockerd's stamp, then the line


def vss_excluded(relp):
    """Why a vss record leaves this file out ("" when it is published)."""
    parts = relp.split("/")
    if NEVER_DIRS.intersection(parts[:-1]):
        return "in/ and bin/ are never captured"
    if parts[-1] in NEVER_FILES or parts[-1].endswith(".so"):
        return "never captured"
    for pat in VSS_WHITELIST:
        pp = pat.split("/")
        if len(pp) == len(parts) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts, pp)):
            return ""
    return "not on the vss whitelist"


RUNNER_FAILED = re.compile(r"^status=FAILED rc=\d+$")    # what remote-ladder.sh's detached runner appends


def status_lines(d):
    try:
        with open(os.path.join(d, "status"), encoding="utf-8", errors="replace") as f:
            return [ln.rstrip("\r\n") for ln in f if ln.startswith("status=")]
    except OSError:
        return []


def last_status(d):
    lines = status_lines(d)
    return lines[-1] if lines else ""


def terminal(last):
    """DONE, TIMEOUT or FAILED for a terminal status line, as remote-ladder.sh's detached runner and capture phase
    read one; "" otherwise."""
    if last == "status=DONE":
        return "DONE"
    for kind in ("TIMEOUT", "FAILED"):
        if last == "status=" + kind or last.startswith("status=%s " % kind):
            return kind
    return ""


def result_file(stem):
    """The stem's own result file's name under raw/."""
    return RESULT_FILE.get(stem, stem[len("vss-"):] + ".json")


def vss_state(stem, incomplete):
    """(state, evidence, detail) of one vss stem; a stem with no done that the capture phase did not name refuses."""
    d = os.path.join(rec, stem)
    last = last_status(d)
    result = "raw/" + result_file(stem)
    has_result = os.path.isfile(os.path.join(d, "raw", result_file(stem)))
    if not os.path.exists(os.path.join(d, "done")):
        if stem not in incomplete:
            sys.exit("%s has no done: its harness may still be running (the capture phase packs such a stem, as "
                     "INCOMPLETE, only past wait-run's give-up point)" % stem)
        return ("INCOMPLETE", True, "no done when the capture ran, past wait-run's give-up point: a partial record "
                "packed as it stands; last status line: %s" % (last or "none"))
    kind = terminal(last)
    if not kind:
        return "NO STATUS", False, "done, but no terminal status line (last: %s): not evidence" % (last or "none")
    if kind == "FAILED":
        # The runner's line says only that the harness failed; the harness's own last line, when it wrote one, says
        # where (status=FAILED at=pulls).
        own = [ln for ln in status_lines(d) if not RUNNER_FAILED.match(ln)]
        where = ", after the harness's own %s" % own[-1] if RUNNER_FAILED.match(last) and own else ""
        return ("FAILED", True, "%s%s: a partial record, packed for its diagnostics%s"
                % (last, where, "" if has_result else "; no " + result))
    if kind == "TIMEOUT" and not has_result:
        # A stop before the end, as a FAILED stem's is: packed as it stands, the missing result file noted. A cap's
        # TERM may land before the harness writes it, and the record must not die with the instance.
        return "TIMEOUT", True, "%s, but no %s: a stop before the end, packed as it stands" % (last, result)
    if not has_result:
        return kind, False, "%s, but no %s: not evidence" % (last, result)
    return kind, True, "%s, with %s" % (last, result)


if not os.path.isdir(rec):
    sys.exit("no run directory %s" % rec)
report = []     # a vss record's report: printed (the capture phase's capture.log), and published as PUB/capture.log


def note(line):
    print(line, flush=True)
    report.append(line)


stems = sorted(n for n in os.listdir(rec) if VSS_STEM.match(n) and os.path.isdir(os.path.join(rec, n)))
vss = bool(stems)
stem_state = {}     # a vss record's stems: DONE, TIMEOUT, FAILED, INCOMPLETE or NO STATUS
if vss:
    incomplete = os.environ.get("CAPTURE_INCOMPLETE", "").split()
    for s in incomplete:
        if s not in stems:
            sys.exit("CAPTURE_INCOMPLETE names %r, which is not a vss stem of %s" % (s, rec))
    note("capture: a vss record (%s)" % " ".join(stems))
    evidence = False
    for s in stems:
        state, ok, detail = vss_state(s, incomplete)
        stem_state[s] = state
        note("%s: %s (%s)" % (s, state, detail))
        evidence = evidence or ok
    if not evidence:
        sys.exit("%s holds no vss stem with a DONE status line and its result file, no TIMEOUT or FAILED stem and no "
                 "INCOMPLETE one: nothing ran" % rec)
else:
    names = [n for _d, _s, fs in os.walk(rec) for n in fs]
    if "stamp.json" not in names or not (any(n.startswith(("lat-", "ex-")) and n.endswith(".json") for n in names)
                                         or ran_sets()):
        sys.exit("%s holds no stamp.json with lat-*.json, ex-*.json or an exchange set in scenarios.log: nothing ran" % rec)
if os.path.isdir(pub) and os.listdir(pub):
    sys.exit("%s is not empty; refusing to mix captures" % pub)
if not os.path.isfile(redactor):
    sys.exit("no redactor at %s" % redactor)

# Forward slashes for the bash argument: when a native Windows process starts an
# MSYS bash, the child re-parses the command line with MSYS quoting rules and
# eats every backslash, so E:\p\redact-aws.sh arrives as E:predact-aws.sh and the
# redaction silently never runs. Git Bash reads E:/p/redact-aws.sh fine.
BASH_REDACTOR = redactor.replace("\\", "/") if os.name == "nt" else redactor


def redact_lines(lines):
    text = "\n".join(lines) + "\n"
    out = subprocess.run(["bash", BASH_REDACTOR], input=text, capture_output=True, text=True, check=True).stdout
    got = out.split("\n")[:-1]
    if len(got) != len(lines):
        sys.exit("redactor changed the line count (%d -> %d)" % (len(lines), len(got)))
    return got


def redact_bytes_lines(lines):
    """Lines (none holding a newline) through ONE redactor process, as bytes both ways: a CR inside a line and the
    platform's newline translation then cannot change the line count."""
    if not lines:
        return []
    try:
        data = "".join(x + "\n" for x in lines).encode("utf-8", "surrogateescape")
    except UnicodeEncodeError as e:
        sys.exit("a string the redactor cannot be given: %s" % e)
    try:
        out = subprocess.run(["bash", BASH_REDACTOR], input=data, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        sys.exit("the redactor failed (%s)" % e)
    got = out.decode("utf-8", "surrogateescape").split("\n")
    if got[-1] != "" or len(got) - 1 != len(lines):
        sys.exit("redactor changed the line count (%d -> %d)" % (len(lines), len(got) - 1))
    return got[:-1]


# leakscan.py's IPv6 rule, kept in step with it (a test holds the two to one pattern): a real address has "::" or
# at least five colons, is not glued to a word, and is not a MAC.
IPV6 = re.compile(r"(?<![0-9A-Za-z_:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")
MAC = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
KEEP_IPV6 = {"::", "::1", "fe80::5054:ff:fe11:1111"}   # unspecified, loopback, the guest's link-local (its fixed MAC)


def mask_ipv6(s):
    def one(m):
        tok = m.group(0)
        if ("::" in tok or tok.count(":") >= 5) and tok.lower() not in KEEP_IPV6 and not MAC.fullmatch(tok):
            return "<ipv6>"
        return tok
    return IPV6.sub(one, s)


def strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def numbers(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from numbers(v, path + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from numbers(v, "%s[%d]" % (path, i))
    elif isinstance(o, bool) or o is None:
        return
    elif isinstance(o, (int, float)):
        yield (path, o)


# The JSON rule by string TOKEN (SDV): every string token of the raw text is found by this pattern (outside a
# string, JSON has no quote), redacted, and replaced where it changed; every other character, numbers included,
# stays as it was. Taken from the raw text, a duplicate key's shadowed value is redacted too.
JSTR = re.compile(r'"(?:[^"\\]|\\.)*"')


def changed_tokens(texts, rel):
    """{raw string token: its replacement} for every token of these JSON texts that the redactor (one call for all
    of them, a string holding a newline line by line) or the IPv6 mask changes; and how many strings held a newline."""
    vals = {}
    for t in texts:
        for tok in set(JSTR.findall(t)):
            if tok not in vals:
                vals[tok] = json.loads(tok)
    uniq = sorted(set(vals.values()))
    lines, spans = [], []
    for s in uniq:
        parts = s.split("\n")
        spans.append((len(lines), len(parts)))
        lines.extend(parts)
    got = redact_bytes_lines(lines)
    red = {s: "\n".join(mask_ipv6(x) for x in got[i:i + n]) for s, (i, n) in zip(uniq, spans)}
    toks = {tok: json.dumps(red[s], ensure_ascii=tok.isascii()) for tok, s in vals.items() if red[s] != s}
    return toks, sum(1 for s in uniq if "\n" in s)


def rewritten_json(text, doc, toks, where):
    """text with its changed string tokens replaced, checked to parse to the same numbers."""
    new = JSTR.sub(lambda m: toks.get(m.group(0), m.group(0)), text)
    if new != text:
        def nums(o):
            return [(p, repr(v)) for p, v in numbers(o)]
        if nums(json.loads(new)) != nums(doc):
            sys.exit("%s: rewriting strings changed a number" % where)
    return new


# What the redactor and the IPv6 rule write in place of what they mask. A vss record's report names, per file, how
# many of each were written into its JSON strings: the JSON rule keeps every number, but a
# string is data too, and a mask written into one (a reply frame's trailing zeros) was invisible in the record.
MASKS = ("<account>", "<arn>", "<eni-id>", "<host>", "<instance-id>", "<ip>", "<ipv6>", "<mac>", "<sg-id>",
         "<snapshot-id>", "<subnet-id>", "<user>", "<volume-id>", "<vpc-id>")
in_strings: "dict[str, dict[str, int]]" = {}     # a vss record's JSON strings: rel -> {mask: times written}


def kinds(counts):
    return ", ".join("%s %d" % (m, counts[m]) for m in sorted(counts))


def note_strings(rel, texts, toks):
    """In a vss record, name every mask written into a string of these JSON texts: each occurrence of a token that
    toks replaces, by kind."""
    if not (vss and toks):
        return
    got = {}
    for t in texts:
        for tok in JSTR.findall(t):
            new = toks.get(tok)
            if new is None:
                continue
            for m in MASKS:
                n = new.count(m) - tok.count(m)
                if n > 0:
                    got[m] = got.get(m, 0) + n
    if got:
        in_strings[rel] = got
        note("string substitutions in %s: %s" % (rel, kinds(got)))


def read_bytes(src):
    with open(src, "rb") as f:
        return f.read()


def write_bytes(dst, data):
    with open(dst, "wb") as f:
        f.write(data)


def write_text(dst, text):
    write_bytes(dst, text.encode("utf-8", "surrogateescape"))


# The vss rules below publish the bytes they read and checked, never a second read of the source: an INCOMPLETE
# stem's harness may still be writing, and what it appended after the check would go out unredacted. Each takes the
# file's bytes, read once by the loop further down.

def json_tokens_file(raw, dst, rel, name, partial):
    """A vss record's *.json by the token rule: "verbatim", "rewritten", or "" when it was left out (a file of a stem
    that did not end whole -- TIMEOUT, FAILED, INCOMPLETE or NO STATUS, which partial names -- that does not parse: a
    write a cap, a kill or the capture cut short). Anywhere else a JSON file that does not parse refuses the capture,
    as in an A6 record."""
    try:
        text = raw.decode("utf-8")
        doc = json.loads(text)
    except ValueError as e:                       # UnicodeDecodeError is a ValueError
        if partial:
            note("excluded: %s (does not parse, in a %s stem: %s)" % (rel, partial, str(e)[:80]))
            return ""
        sys.exit("%s: does not parse (%s)" % (rel, e))
    toks, multi = changed_tokens([text], rel)
    if multi:
        note("%s: %d string(s) holding a newline redacted line by line" % (rel, multi))
    if not toks:
        write_bytes(dst, raw)
        return "verbatim"
    if name.startswith(ARM):
        sys.exit("%s: arm file holds strings the redactor changes" % rel)
    note_strings(rel, [text], toks)
    write_text(dst, rewritten_json(text, doc, toks, rel))
    return "rewritten"


def json_line(ln):
    """One JSONL line (decoded with surrogateescape) as JSON; ValueError when it does not parse or holds a byte that
    is not UTF-8."""
    try:
        ln.encode("utf-8")        # a byte that is not UTF-8 came back as a lone surrogate, which strict encoding refuses
    except UnicodeEncodeError:
        raise ValueError("not UTF-8") from None
    return json.loads(ln)


def jsonl_file(raw, dst, rel, name, partial):
    """*.jsonl by the JSON rule, line by line: True when strings were redacted or a torn last line dropped, False when
    published as it was, None when left out. The last line is judged first: with no newline, one that does not parse
    or decode (a write cut short, inside a multi-byte character too) is torn, dropped and noted, in any stem. Any other
    line that does not parse or decode refuses the capture, except in a stem that did not end whole (partial names its
    state), where the file is left out and named, as json_tokens_file leaves out such a stem's JSON."""
    lines = raw.decode("utf-8", "surrogateescape").split("\n")
    last = lines.pop()        # "" when the file ends with a newline
    docs = {}
    end_nl, torn = True, False
    if last.strip():
        try:
            docs[len(lines)] = json_line(last)
        except ValueError:
            torn = True
            note("torn last line dropped: %s (%d characters, no newline, does not parse)" % (rel, len(last)))
        else:
            lines.append(last)
            end_nl = False
    elif last:
        lines.append(last)
        end_nl = False
    for i, ln in enumerate(lines):
        if i in docs or not ln.strip():
            continue          # the last line, judged above; a blank line holds nothing
        try:
            docs[i] = json_line(ln)
        except ValueError as e:
            if partial:
                note("excluded: %s (a line that does not parse, in a %s stem: line %d: %s)"
                     % (rel, partial, i + 1, str(e)[:80]))
                return None
            sys.exit("%s:%d: a line that does not parse, and not a torn last one (%s): refused" % (rel, i + 1, e))
    toks, multi = changed_tokens([lines[i] for i in docs], rel)
    if multi:
        note("%s: %d string(s) holding a newline redacted line by line" % (rel, multi))
    if not toks and not torn:
        write_bytes(dst, raw)
        return False
    if toks and name.startswith(ARM):
        sys.exit("%s: arm file holds strings the redactor changes" % rel)
    note_strings(rel, [lines[i] for i in docs], toks)
    out = [rewritten_json(ln, docs[i], toks, "%s:%d" % (rel, i + 1)) if i in docs and toks else ln
           for i, ln in enumerate(lines)]
    write_text(dst, "\n".join(out) + ("\n" if end_nl and out else ""))
    return True


def bridge_log_file(raw, dst, rel):
    """vss-claim-bridge.log: the JSON after dockerd's stamp by the JSON rule, the stamp and every other line through
    the redactor and the IPv6 rule as text. Returns the 12-digit and the IPv6 substitutions made in the text."""
    parts = raw.decode("utf-8", "surrogateescape").split("\n")
    js = {}                  # line index -> (stamp, JSON text, its document)
    for i, p in enumerate(parts):
        m = STAMPED.match(p)
        if m:
            try:
                js[i] = (m.group(1), m.group(2), json.loads(m.group(2)))
            except ValueError:
                pass
    toks, multi = changed_tokens([j for _s, j, _d in js.values()], rel)
    if multi:
        note("%s: %d string(s) holding a newline redacted line by line" % (rel, multi))
    note_strings(rel, [j for _s, j, _d in js.values()], toks)
    texts = [js[i][0] if i in js else p for i, p in enumerate(parts)]
    red = [mask_ipv6(x) for x in redact_bytes_lines(texts)]
    subs = sum(b.count("<account>") - a.count("<account>") for a, b in zip(texts, red))
    if subs:
        note("12-digit substitutions in %s: %d" % (rel, subs))
    v6 = sum(b.count("<ipv6>") - a.count("<ipv6>") for a, b in zip(texts, red))
    if v6:
        note("IPv6 substitutions in %s: %d" % (rel, v6))
    new = "\n".join(red[i] + rewritten_json(js[i][1], js[i][2], toks, "%s:%d" % (rel, i + 1)) if i in js else red[i]
                    for i in range(len(parts)))
    if new == "\n".join(parts):
        write_bytes(dst, raw)
    else:
        write_text(dst, new)
    return subs, v6


verbatim = rewritten = texts = 0
text_jobs = []      # an A6 record's text files, (src, dst): redacted in parallel below, one redactor process per file
vss_texts = []      # a vss record's, (the bytes read, dst, rel): the same, from the bytes the loop read
arm_read = {}       # a vss record's arm files published: rel -> the bytes read, for the byte-for-byte check below
entries = [(root, name) for root, _dirs, files in os.walk(rec) for name in sorted(files)]
if vss:
    entries.sort(key=lambda e: os.path.relpath(os.path.join(*e), rec).replace(os.sep, "/"))
twelve = {}         # a vss record's text files: rel -> the 12-digit substitutions the redactor made
ipv6 = {}           # and rel -> the IPv6 substitutions the IPv6 rule made
for root, name in entries:
    src = os.path.join(root, name)
    rel = os.path.relpath(src, rec)
    relp = rel.replace(os.sep, "/")
    if vss:
        why = vss_excluded(relp)
        if why:
            note("excluded: %s (%s)" % (relp, why))
            continue
        try:
            data = read_bytes(src)
        except OSError as e:
            # Listed by the walk, gone or unreadable at the read: a harness still running may remove a file (the
            # bridge unlinks an empty bridge.jsonl on a refused start). Left out and named, never a traceback that
            # loses the session's record.
            note("excluded: %s (cannot be read: %s)" % (relp, e.strerror or type(e).__name__))
            continue
        dst = os.path.join(pub, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        state = stem_state.get(relp.split("/", 1)[0], "")
        partial = "" if state in ("", "DONE") else state     # a stem that did not end whole, or ""
        if name.endswith(".json"):
            how = json_tokens_file(data, dst, relp, name, partial)
            if how == "rewritten":
                rewritten += 1
            elif how == "verbatim":
                verbatim += 1
                if name.startswith(ARM):
                    arm_read[relp] = data
        elif name.endswith(".jsonl"):
            got = jsonl_file(data, dst, relp, name, partial)
            if got:
                rewritten += 1
            elif got is False:
                verbatim += 1
        elif name == BRIDGE_LOG:
            n12, n6 = bridge_log_file(data, dst, relp)
            texts += 1
            if n12:
                twelve[relp] = n12
            if n6:
                ipv6[relp] = n6
        else:
            vss_texts.append((data, dst, relp))
            texts += 1
        continue
    if name.endswith(".so") or name == ".run-start":
        continue
    dst = os.path.join(pub, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if name.endswith(".json"):
        raw = open(src, encoding="utf-8").read()
        doc = json.loads(raw)
        ss = sorted(set(strings(doc)))
        if any("\n" in s for s in ss):
            sys.exit("%s: a string holds a newline; not handled" % rel)
        red = dict(zip(ss, [mask_ipv6(x) for x in redact_lines(ss)])) if ss else {}
        changed = {a: b for a, b in red.items() if a != b}
        if not changed:
            shutil.copyfile(src, dst)
            verbatim += 1
            continue
        if name.startswith(ARM):
            sys.exit("%s: arm file holds strings the redactor changes: %r" % (rel, sorted(changed)[:5]))
        new = raw
        for a in sorted(changed, key=len, reverse=True):
            ea, eb = json.dumps(a)[1:-1], json.dumps(changed[a])[1:-1]
            if ea not in new:
                sys.exit("%s: cannot locate string %r in the raw text" % (rel, a))
            new = new.replace(ea, eb)
        if list(numbers(json.loads(new))) != list(numbers(doc)):
            sys.exit("%s: rewriting strings changed a number" % rel)
        open(dst, "w", encoding="utf-8").write(new)
        rewritten += 1
    elif name.endswith(".jsonl"):
        if jsonl_file(read_bytes(src), dst, relp, name, ""):
            rewritten += 1
        else:
            verbatim += 1
    else:
        text_jobs.append((src, dst))
        texts += 1


def redact_file(job):
    src, dst = job
    with open(src, "rb") as f, open(dst, "wb") as g:     # a console log is not always UTF-8
        subprocess.run(["bash", BASH_REDACTOR], stdin=f, stdout=g, check=True)


def redact_read(job):
    """A vss record's text file, as the loop read it, through one redactor process and then the IPv6 rule into dst.
    The redactor masked IPv4 only when this was written (an instance's link-local address in run.log
    went out, and leakscan refused the record); it masks IPv6 by the same rule now, and this pass stays as the second
    one. awk's print ends the last line in a newline: a file that had none is published without
    one, so a line cut short still reads as cut."""
    data, dst, _rel = job
    out = subprocess.run(["bash", BASH_REDACTOR], input=data, stdout=subprocess.PIPE, check=True).stdout
    if data and not data.endswith(b"\n") and out.endswith(b"\n"):
        out = out[:-1]
    write_text(dst, mask_ipv6(out.decode("utf-8", "surrogateescape")))


# Redact files in parallel, one process per file; any failure still stops
# the capture.
with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 1)) as pool:
    for job, fut in [(j, pool.submit(redact_file, j)) for j in text_jobs]:
        try:
            fut.result()
        except subprocess.CalledProcessError as e:
            sys.exit("%s: the redactor failed (%s)" % (os.path.relpath(job[0], rec), e))
    for vjob, fut in [(j, pool.submit(redact_read, j)) for j in vss_texts]:
        try:
            fut.result()
        except subprocess.CalledProcessError as e:
            sys.exit("%s: the redactor failed (%s)" % (vjob[2], e))

if vss:
    # The redactor's account mask rewrites any standalone 12-digit number. In a text file that may be data (a
    # recorder CSV's value field) and not an id: the count per file makes each such rewrite visible.
    for data, dst, relp in vss_texts:
        out = read_bytes(dst)
        n = out.count(b"<account>") - data.count(b"<account>")
        if n:
            twelve[relp] = n
            note("12-digit substitutions in %s: %d" % (relp, n))
        n = out.count(b"<ipv6>") - data.count(b"<ipv6>")
        if n:
            ipv6[relp] = n
            note("IPv6 substitutions in %s: %d" % (relp, n))
    note("12-digit substitutions in text files: %d, in %d file(s)" % (sum(twelve.values()), len(twelve)))
    note("IPv6 substitutions in text files: %d, in %d file(s)" % (sum(ipv6.values()), len(ipv6)))
    # Every mask written into a JSON string, which the JSON rule's byte-for-byte check cannot see (it compares
    # numbers and the bytes outside strings), totalled by kind.
    total: "dict[str, int]" = {}
    for by_kind in in_strings.values():
        for mask_kind, times in by_kind.items():
            total[mask_kind] = total.get(mask_kind, 0) + times
    note("string substitutions in JSON strings: %d, in %d file(s)%s"
         % (sum(total.values()), len(in_strings), " (%s)" % kinds(total) if total else ""))

# The arm files must come through byte-for-byte: a redactor that edits a latency
# sample corrupts data (2026-09-21), and one that edits a counter does too
# (2026-09-22, rehearsal). Checked here, not assumed from the code path above.
if vss:
    for relp, data in sorted(arm_read.items()):     # the bytes read once (a vss record's file may be gone by now)
        if read_bytes(os.path.join(pub, relp)) != data:
            sys.exit("%s differs from the run's copy" % relp)
else:
    for root, _dirs, files in os.walk(rec):
        for name in files:
            if name.endswith(".json") and name.startswith(ARM):
                a = os.path.join(root, name)
                b = os.path.join(pub, os.path.relpath(a, rec))
                if open(a, "rb").read() != open(b, "rb").read():
                    sys.exit("%s differs from the run's copy" % os.path.relpath(a, rec))

summary = "capture: %d JSON verbatim, %d JSON with strings redacted, %d text files redacted" % (verbatim, rewritten, texts)
if vss:
    # The report itself goes through the redactor and the IPv6 rule too: nothing reaches PUB that did not.
    write_text(os.path.join(pub, "capture.log"),
               "".join(mask_ipv6(x) + "\n" for x in redact_bytes_lines(report + [summary])))
paths = []
for root, _dirs, files in os.walk(pub):
    for name in files:
        paths.append(os.path.relpath(os.path.join(root, name), pub).replace(os.sep, "/"))
with open(pub + ".sha256", "w", newline="\n") as m:
    for rel in sorted(paths):
        m.write("%s  %s\n" % (hashlib.sha256(open(os.path.join(pub, rel), "rb").read()).hexdigest(), rel))
print(summary)
