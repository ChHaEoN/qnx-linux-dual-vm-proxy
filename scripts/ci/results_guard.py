#!/usr/bin/env python3
"""results_guard.py -- keep measured and functional results out of the public tree.

    usage: python scripts/ci/results_guard.py [--repo .] [--rev HEAD] [--base REV]
                                              [--commits SPEC] [--audit]

    --base REV     flag every figure the tree at --rev adds, against REV, in the
                   guarded text (a harness's "WHAT IS KNOWN." section, docs/,
                   and every README below the root)
    --commits SPEC flag every figure in the messages of `git rev-list SPEC`,
                   e.g. "BASE..HEAD" or "SHA --not --remotes=origin"
    --audit        list every figure in the guarded text, new or not

Exit 0 if every check passes, 1 otherwise. Every finding is printed with its
path and line.

WHY. Clause 4.6(i) of the QNX Development License Agreement (Non-Commercial/
Academic Licence Class, v7) bars making the results of any performance or
functional evaluation of the software available to any third party without
BlackBerry's prior written approval. On 2026-09-27 the owner decided that
measurement results stay local, and on 2026-09-28 the public tree was scrubbed.
The scrub found that results had reached main by routes nobody was checking:
the "what is known" sections of pre-registration headers, the docs, and commit
messages. claims_gate.py covers README.md; this covers the rest.

WHAT IT CHECKS, all hard:
  1. PATHS    -- a file in the tree where the tooling writes evaluation output:
                 run records, the IPC CSVs, sample-boot logs, collector reports.
                 .gitignore keeps them out; `git add -f` would not. Whole tree,
                 every run.
  2. KNOWN    -- (with --base) a figure a harness's "WHAT IS KNOWN." section
                 gains. That section cites held records by name, never quotes them.
  3. DOCS     -- (with --base) a figure docs/**/*.md or a README below the root
                 gains.
  4. COMMITS  -- (with --commits) a figure in a commit message.

WHY A RATCHET FOR 2 AND 3. The scrubbed tree still carries figures that are not
results -- 2 ms spacing, 8 GB of RAM, a kernel's HZ, a vendor's latency target --
and they were reviewed one by one in the scrub. Listing them all would make the
allowlist the largest file here and teach everyone to paste into it. So the
reviewed tree is the baseline, and only a figure a change ADDS is questioned.
A figure that is genuinely a design value goes into figure-allowlist.txt with
its reason; everything else is rewritten to name the record instead. --audit
prints the whole baseline for review at any time.

A FIGURE is a number with a unit (us, ms, s, %, x, MHz, W, GB, ...) that is not
glued to a word: "2 ms spacing" is one, "t2ms" and "0x5A" are not.

WHAT IT DOES NOT DO. It cannot tell a result from a design value by itself: the
allowlist and the reviewer carry that judgement. A result written without a unit
("18 of 18") passes. It reads text only and never runs anything.
"""

import argparse
import collections
import fnmatch
import os
import re
import shlex
import subprocess
import sys

FIGURE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(ms|us|µs|ns|s|%|x|×|MB|GB|KB|MiB|GiB|MHz|GHz|mW|W)(?!\w)",
    re.I,
)

# Where the tooling writes evaluation output. A tracked file here is a result.
FORBIDDEN = [
    re.compile(r"^results/orin-native-port/\d{8}T-[^/]+/"),
    re.compile(r"^logs/sample-boot/[^/]+\.(log|txt)$"),
    re.compile(r"^results/(cloud|hw)/[^/]*-latest\.csv$"),
    re.compile(r"^results/gicv3-nisv-debug/"),
]

KNOWN_START = re.compile(r"^\s*#\s*WHAT IS KNOWN\b")
# A section ends at a blank comment line, at a line that is not a comment, or at
# the next capitalised heading ("THE RUN.", "FEASIBILITY,", "CHANGED AFTER ...").
KNOWN_END = re.compile(r"^\s*#\s*$|^\s*#\s*[A-Z]{3,}[A-Z0-9 ()'/-]*[.:,](\s|$)")
HARNESS_GLOBS = ("*.sh", "*.py")
DOC_GLOBS = ("docs/*.md", "docs/**/*.md", "*/README.md", "*/**/README.md")

HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWLIST = os.path.join(HERE, "figure-allowlist.txt")


def git(repo, *args, stdin=None):
    return subprocess.run(["git", "-C", repo, *args], input=stdin, capture_output=True, check=True).stdout


def tree_paths(repo, rev):
    out = git(repo, "ls-tree", "-r", "--name-only", rev).decode("utf-8", "replace")
    return [p for p in out.splitlines() if p]


def read_blobs(repo, rev, paths):
    """{path: text} through one `git cat-file --batch`; a path missing at rev is left out."""
    if not paths:
        return {}
    req = "".join("%s:%s\n" % (rev, p) for p in paths).encode("utf-8")
    out = git(repo, "cat-file", "--batch", stdin=req)
    texts, pos = {}, 0
    for p in paths:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        pos = nl + 1
        if len(header) < 3 or header[1] != b"blob":
            continue
        size = int(header[2])
        texts[p] = out[pos:pos + size].decode("utf-8", "replace")
        pos += size + 1
    return texts


def figures(line):
    """[(start, end, text)] of every figure on a line."""
    return [(m.start(), m.end(), m.group(0)) for m in FIGURE.finditer(line)]


def known_sections(text):
    """[(lineno, line)] of every line inside a "WHAT IS KNOWN." section."""
    out, inside = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if KNOWN_START.match(line):
            inside = True
            out.append((n, line))
            continue
        if inside:
            if not line.lstrip().startswith("#") or KNOWN_END.match(line):
                inside = False
                continue
            out.append((n, line))
    return out


def load_allowlist(path):
    """[(path_glob, literal, reason)]: `path<TAB>literal<TAB>reason`, '#' comments.

    An entry clears a figure on a line of a matching file when the figure lies
    inside an occurrence of the literal on that line. The reason is mandatory:
    an exemption nobody can explain is not one.
    """
    entries = []
    if not os.path.exists(path):
        return entries
    for n, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3 or not all(x.strip() for x in parts):
            raise ValueError("%s:%d: want path<TAB>literal<TAB>reason" % (path, n))
        entries.append((parts[0].strip(), parts[1], parts[2].strip()))
    return entries


def cleared(path, line, span, allow):
    s, e = span
    for glob, literal, _reason in allow:
        if not fnmatch.fnmatch(path, glob):
            continue
        start = line.find(literal)
        while start != -1:
            if start <= s and e <= start + len(literal):
                return True
            start = line.find(literal, start + 1)
    return False


def is_doc(path):
    return path != "README.md" and any(fnmatch.fnmatch(path, g) for g in DOC_GLOBS)


def is_harness(path):
    return any(fnmatch.fnmatch(os.path.basename(path), g) for g in HARNESS_GLOBS)


def guarded_lines(path, text):
    """[(lineno, line)] of the text in `path` the figure checks apply to."""
    if is_doc(path):
        return list(enumerate(text.splitlines(), 1))
    if is_harness(path) and "WHAT IS KNOWN" in text:
        return known_sections(text)
    return []


def occurrences(path, text):
    return [(n, line, s, e, fig) for n, line in guarded_lines(path, text) for s, e, fig in figures(line)]


def check_paths(paths):
    return ["PATHS  %s  is where the tooling writes evaluation output" % p
            for p in paths if any(rx.search(p) for rx in FORBIDDEN)]


def check_figures(repo, rev, base, paths, allow, audit):
    """Figures the guarded text at rev adds against base (or all of them, with audit)."""
    guarded = [p for p in paths if is_doc(p) or is_harness(p)]
    head = read_blobs(repo, rev, guarded)
    old = read_blobs(repo, base, guarded) if base and not audit else {}
    found = []
    for p in guarded:
        if p not in head:
            continue
        kind = "DOCS" if is_doc(p) else "KNOWN"
        before = collections.Counter(fig for *_x, fig in occurrences(p, old.get(p, "")))
        for n, line, s, e, fig in occurrences(p, head[p]):
            if before[fig] > 0:
                before[fig] -= 1
                continue
            if not cleared(p, line, (s, e), allow):
                found.append("%s  %s:%d  %r in: %s" % (kind, p, n, fig, line.strip()[:140]))
    return found


def check_commits(repo, spec):
    """Figures in the messages of the commits `git rev-list <spec>` names."""
    shas = git(repo, "rev-list", *shlex.split(spec)).decode().split()
    found = []
    for sha in shas:
        msg = git(repo, "log", "-1", "--format=%B", sha).decode("utf-8", "replace")
        for n, line in enumerate(msg.splitlines(), 1):
            for _s, _e, fig in figures(line):
                found.append("COMMIT  %s:%d  %r in: %s" % (sha[:8], n, fig, line.strip()[:140]))
    return found


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--rev", default="HEAD", help="the tree to check (default HEAD)")
    ap.add_argument("--base", help="the reviewed tree to compare against")
    ap.add_argument("--commits", help='a git rev-list spec whose commit messages to check, e.g. "A..B"')
    ap.add_argument("--audit", action="store_true", help="list every figure in the guarded text")
    ap.add_argument("--allowlist", default=ALLOWLIST)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # a Windows console is not UTF-8

    allow = load_allowlist(a.allowlist)
    paths = tree_paths(a.repo, a.rev)
    found = check_paths(paths)
    if a.base or a.audit:
        found += check_figures(a.repo, a.rev, a.base, paths, allow, a.audit)
    else:
        print("results_guard: no --base, so figures in the guarded text are not checked (paths only)")
    if a.commits:
        found += check_commits(a.repo, a.commits)

    for f in found:
        print("  FAIL " + f)
    if found:
        print("RESULT: FAIL -- %d finding(s). Name the record instead of quoting it; a design value goes into"
              " scripts/ci/figure-allowlist.txt with its reason." % len(found))
        return 1
    print("RESULT: PASS -- no new figure in the guarded text, none in the commit messages,"
          " and no evaluation output in the tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
