#!/usr/bin/env python3
"""capture.py REC PUB REDACTOR -- build the publishable copy of a run ON the host
that ran it, redacted at capture time.

Why not just pipe every file through redact-aws.sh: its account mask replaces
any standalone 12-digit number, and KVM's nanosecond counters are 12-digit
numbers ("halt_wait_ns" passes 1e11 ns within the hour -- no literal one is
written here, because this file is itself copied into the record's tooling/
and published through the redactor, and would come back with "<account>" in
it, breaking the CAPTURE_SHA256 the same record carries). A rehearsal on the
Orin, 2026-09-22, had the redactor rewrite 98 of 99 arm files -- one of them
in a counter, the rest only by a trailing newline. So:

  *.json   parsed. Every STRING in it (keys and values) goes through the
           redactor; numbers never do, because nothing that writes these files
           reads an AWS identity. If no string changes, the file is copied
           byte-for-byte. If one does, arm files (lat-, kvm-, db-burst) are
           refused outright -- they should hold no host identity at all -- and
           any other JSON (stamp.json) gets those strings replaced in its text,
           after which every number is checked to be unchanged.
  other    text files through the redactor as they are; *.so and the
           .run-start marker are not published.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

if len(sys.argv) != 4:
    sys.exit("usage: capture.py REC PUB REDACTOR")
rec, pub, redactor = sys.argv[1:4]
ARM = ("lat-", "kvm-", "db-burst")

# A capture of nothing must fail, not "succeed" with an empty record: a skipped
# or failed ladder would otherwise be packed and fetched as if it had run.
if not os.path.isdir(rec):
    sys.exit("no run directory %s" % rec)
names = [n for _d, _s, fs in os.walk(rec) for n in fs]
if not any(n.startswith("lat-") and n.endswith(".json") for n in names) or "stamp.json" not in names:
    sys.exit("%s holds no lat-*.json and stamp.json: nothing ran" % rec)
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


verbatim = rewritten = texts = 0
for root, _dirs, files in os.walk(rec):
    for name in sorted(files):
        if name.endswith(".so") or name == ".run-start":
            continue
        src = os.path.join(root, name)
        rel = os.path.relpath(src, rec)
        dst = os.path.join(pub, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if name.endswith(".json"):
            raw = open(src, encoding="utf-8").read()
            doc = json.loads(raw)
            ss = sorted(set(strings(doc)))
            if any("\n" in s for s in ss):
                sys.exit("%s: a string holds a newline; not handled" % rel)
            red = dict(zip(ss, redact_lines(ss))) if ss else {}
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
        else:
            with open(src, "rb") as f, open(dst, "wb") as g:     # a console log is not always UTF-8
                subprocess.run(["bash", BASH_REDACTOR], stdin=f, stdout=g, check=True)
            texts += 1

# The arm files must come through byte-for-byte: a redactor that edits a latency
# sample corrupts data (2026-09-21), and one that edits a counter does too
# (2026-09-22, rehearsal). Checked here, not assumed from the code path above.
for root, _dirs, files in os.walk(rec):
    for name in files:
        if name.endswith(".json") and name.startswith(ARM):
            a = os.path.join(root, name)
            b = os.path.join(pub, os.path.relpath(a, rec))
            if open(a, "rb").read() != open(b, "rb").read():
                sys.exit("%s differs from the run's copy" % os.path.relpath(a, rec))

paths = []
for root, _dirs, files in os.walk(pub):
    for name in files:
        paths.append(os.path.relpath(os.path.join(root, name), pub).replace(os.sep, "/"))
with open(pub + ".sha256", "w", newline="\n") as m:
    for rel in sorted(paths):
        m.write("%s  %s\n" % (hashlib.sha256(open(os.path.join(pub, rel), "rb").read()).hexdigest(), rel))
print("capture: %d JSON verbatim, %d JSON with strings redacted, %d text files redacted" % (verbatim, rewritten, texts))
