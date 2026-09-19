#!/usr/bin/env python3
"""render_badges.py -- derive README's Phase badge from the status table.

    usage: python scripts/ci/render_badges.py --check    # CI: fail on drift
           python scripts/ci/render_badges.py --write    # rewrite the badge row

WHY THIS EXISTS. The Phase badge and the Status table were two hand-maintained
copies of the same fact, and they drifted: the badge announced "Phase 0 -
Bootstrap" long after the table had moved on, and later announced "Phase 3b
native QHV" after "native QHV" (v1) had been superseded by A6. A badge that is
typed by hand will drift again. So the table is the single source of truth and
the badge is generated from it; --check makes divergence a build failure.

THE TABLE IS THE SOURCE because it is the thing reviewers actually update when
a phase moves, and it carries evidence links per row. The badge carries no
information of its own.

The badge names the phase only -- not the architecture. Architecture ids (A1-A6,
v1) move independently of phases and belong in the body, where they can be
struck through and dated. That is exactly how "native QHV" went stale.
"""
import argparse
import io
import os
import re
import sys

DONE, IN_PROGRESS, NOT_STARTED = "✅", "\U0001f7e1", "⬜"

ROW_RE = re.compile(r"^\|\s*\*\*([0-9]+b?)\*\*[^|]*\|\s*(\S+)", re.M)
PHASE_BADGE_RE = re.compile(r"^!\[Phase\]\(https://img\.shields\.io/badge/[^)]*\)\s*$", re.M)


def read(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def parse_status_table(readme_text):
    """[(phase_id, state)] in document order, state in done/in-progress/not-started."""
    rows = []
    for phase, symbol in ROW_RE.findall(readme_text):
        head = symbol[0]
        state = {DONE: "done", IN_PROGRESS: "in-progress", NOT_STARTED: "not-started"}.get(head)
        if state:
            rows.append((phase, state))
    return rows


def current_phase(rows):
    """The first in-progress phase; if none, the last completed one.

    'First in-progress' rather than 'highest numbered': 3b and 4 are both in
    flight, and the badge should name where the work actually is.
    """
    for phase, state in rows:
        if state == "in-progress":
            return phase
    done = [p for p, s in rows if s == "done"]
    if done:
        return done[-1]
    raise ValueError("no phase rows found in the status table")


def badge_line(phase):
    return "![Phase](https://img.shields.io/badge/Phase-%s-blue)" % phase.replace(" ", "%20")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--readme", default="README.md")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    a = ap.parse_args()

    text = read(a.readme)
    rows = parse_status_table(text)
    if not rows:
        print("FAIL: no status table rows found in %s" % a.readme)
        return 1

    phase = current_phase(rows)
    want = badge_line(phase)

    print("status table: %s" % ", ".join("%s=%s" % r for r in rows))
    print("derived phase: %s" % phase)
    print("expected badge: %s" % want)

    found = PHASE_BADGE_RE.search(text)
    if not found:
        print("FAIL: no Phase badge line found in %s" % a.readme)
        return 1
    have = found.group(0).strip()
    print("actual badge  : %s" % have)

    if have == want:
        print("ok -- badge matches the status table")
        return 0
    if a.check:
        print("FAIL: the Phase badge and the status table disagree.")
        print("      Run: python scripts/ci/render_badges.py --write")
        return 1

    new = PHASE_BADGE_RE.sub(want, text, count=1)
    with io.open(a.readme, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)
    print("rewrote the Phase badge in %s" % os.path.basename(a.readme))
    return 0


if __name__ == "__main__":
    sys.exit(main())
