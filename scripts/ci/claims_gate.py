#!/usr/bin/env python3
"""claims_gate.py -- check README.md against committed data, and the repo's prose.

    usage: python scripts/ci/claims_gate.py [--readme README.md] [--repo .]

Exit 0 if every check passes, 1 otherwise. Always prints a claimed-vs-
recomputed table so a human can read the check, not just its exit code.

WHAT THIS GATE IS FOR. This repo's central rule is "never write 'it works'
without a log, a number, or a diff". The risk it does not address is a number
that was true when written and drifted afterwards -- a figure edited in prose,
a data file appended to, a claim carried forward past the run it came from.
Two published numbers in this repo were once found wrong that way, by hand.
This gate makes that class of error fail the build.

WHAT README QUOTES NOW: NO RESULTS. Clause 4.6(i) of the QNX Development
License Agreement (Non-Commercial/Academic Licence Class, v7) bars making the
results of any performance or functional evaluation of the software available
to a third party without BlackBerry's prior written approval. On 2026-09-27 the
owner withdrew every measured and functional result from the public tree: the
run records, CSVs and logs that README's figures used to be re-derived from are
held locally and are no longer committed. build_claims() is therefore empty,
and the FIGURES check below makes that state enforceable rather than hoped for:
a number with a unit in README fails the build unless a claim re-derives it
from committed data -- which today means any figure at all. The claim machinery
(Claim, run_claims) is kept, and unit-tested against synthetic fixtures, so a
figure published later with written approval comes back under the same check.

FAILURES, all hard:
  1. VALUE     -- README's figure does not match the recomputation, at README's
                  own stated precision.
  2. UNIT      -- README's unit does not match the unit of the source data.
                  "40 ms" against a source in seconds is wrong even if the digits
                  agree. This is a failure, never a warning.
  3. FIGURE    -- a number with a unit in README that no claim re-derives.
  4. DENYLIST  -- an ASSERTED claim string the committed record does not support.
  5. OVERWRITE -- a strike-through in a current-state file.
  6. DESCRIPTION -- the pinned GitHub "About" text fails the denylist, quotes a
                  figure, or (outside --no-network) differs from the live value.

WHAT IT CANNOT DO is printed in the NOT CHECKED section of every run: a result
held locally has nothing in the tree to be checked against.
"""
import argparse
import os
import re
import sys
from re import error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claims_lib as C  # noqa: E402

# Current-state files: they say what is true now, and nothing else. Adding a
# file here is a commitment to rewrite it rather than annotate it.
#
# README.md joined on 2026-09-21, and it should have been here first. Deferring
# it produced exactly the failure the rule exists to stop: an owner decision was
# patched into one sentence of a section that still carried six older
# corrections, so README ended up saying both "whether the TCG twin legs survive
# is one of the open choices" and "the TCG twin legs do NOT survive" -- a
# contradiction introduced by annotating instead of overwriting.
#
# CLAUDE.md was here until 2026-09-21, when the AI briefings were unpublished:
# they are development tooling, and a repo should carry ONE public statement of
# current state, not two that can drift. README is that statement.
#
# docs/architecture.md joined on 2026-09-21, once it was rewritten: 511 lines and
# 52 strike markers down to 189 and none. It states current architecture, so it
# earns the same rule -- and adding it here is what stops it drifting back.
OVERWRITE_ONLY = ("README.md", "docs/architecture.md")


class ClaimNotFound(Exception):
    """README no longer contains the sentence a claim was anchored to."""


class Claim(object):
    """One README figure and how to re-derive it.

    THE CLAIMED VALUE IS READ OUT OF README.md, never hardcoded here. An earlier
    draft of this file stored the figure as a Python constant and compared that
    constant against the data -- so editing README changed nothing and the gate
    passed no matter what the document said. It was caught only by deliberately
    corrupting a number and noticing the gate stayed green. `anchor` is what
    fixes that: a regex whose group(1) is the number as README writes it and,
    where README writes one, whose group('unit') is its unit token.

    `expect_unit` is the unit README is required to use; `source_unit` is the
    unit the data file is measured in. Both are checked. A claim that says
    "40 s" over data measured in ms is wrong even though the digits match.
    """

    def __init__(self, cid, what, anchor, decimals, expect_unit, source_unit, sources, fn, note=""):
        self.cid = cid
        self.what = what
        self.anchor = re.compile(anchor)
        self.decimals = decimals
        self.expect_unit = expect_unit
        self.source_unit = source_unit
        self.sources = sources
        self.fn = fn
        self.note = note

    def read_claim(self, readme_text):
        """(value, unit_as_written) straight out of README.md.

        Whitespace is collapsed before matching. README wraps prose, so an
        anchor like /rebuilt startup, ([0-9,]+) bytes/ silently stopped matching
        the moment a rewrite put "rebuilt" at the end of one line and "startup,"
        at the start of the next -- the claim was still there and still true, and
        the gate reported it as removed. A claim must not depend on where the
        text happens to wrap.
        """
        m = self.anchor.search(" ".join(readme_text.split()))
        if not m:
            raise ClaimNotFound(
                "%s: no sentence in README matches /%s/ -- the claim was reworded or "
                "removed, so the gate can no longer verify it" % (self.cid, self.anchor.pattern)
            )
        raw = m.group(1).replace(",", "")
        try:
            unit = m.group("unit")
        except (IndexError, error):
            unit = None
        return float(raw), (unit.strip() if unit else None)


def build_claims(repo):
    """The README figures that CAN be re-derived from committed data: none.

    Every claim that used to live here -- boot-time deltas, IPC percentiles, the
    attribution ladder, the pinned-load and shared-memory contrasts, serial byte
    counts, recovery counts -- was re-derived from run records that are now held
    locally (NC QDL v7 4.6(i); see the module docstring), and README quotes none
    of them. A claim is added back here only together with committed data that
    backs it. Each entry is a Claim: an anchor regex over README, the decimals
    README quotes, README's unit, the data's unit, the source files, and a
    zero-argument function returning (recomputed value, source unit); `repo` is
    what a claim's data paths resolve against.
    """
    return []


# Claims README makes with NO committed backing. Listed so the gate reports them
# rather than leaving a reader to assume they were checked.
UNBACKED = [
    ("every measured and functional result", "held locally, not in the tree: NC QDL v7 4.6(i) (2026-09-27)"),
    ("3.3 V USB-TTL on J14", "hardware prerequisite, no artefact"),
]


def run_claims(claims, readme):
    """Check each claim against README, print one table row per claim.

    Returns (failures, unit_rows, derived): failure messages; (cid, README unit,
    source unit, ok) for the unit summary; and (value, unit) for every figure
    successfully re-derived, which the FIGURES and description checks accept.
    Kept apart from main() so the tests can drive it with synthetic claims over
    tests/fixtures -- the committed README quotes none to drive it with.
    """
    failures = []
    unit_rows = []
    derived = []
    for claim in claims:
        # 1. What does README actually say, right now?
        try:
            claimed, claimed_unit = claim.read_claim(readme)
        except ClaimNotFound as exc:
            print("%-6s %-44s %10s %12s %-9s %s" % (claim.cid, claim.what[:44], "?", "-", "-", "FAIL not found"))
            failures.append(str(exc))
            continue

        # 2. What does the committed data say?
        try:
            recomputed, source_unit = claim.fn()
        except Exception as exc:  # noqa: BLE001 - any failure to re-derive is a gate failure
            print("%-6s %-44s %10s %12s %-9s %s" % (claim.cid, claim.what[:44], claimed, "ERROR", "-", exc))
            failures.append("%s: could not re-derive (%s)" % (claim.cid, exc))
            continue

        # 3. Units, both sides. A unit mismatch is a HARD failure, not a warning.
        readme_unit_ok = claimed_unit is None or claimed_unit == claim.expect_unit
        source_unit_ok = source_unit == claim.source_unit
        value_ok = C.close_enough(claimed, recomputed, claim.decimals)

        if not readme_unit_ok:
            verdict = "FAIL unit: README writes %r, expected %r" % (claimed_unit, claim.expect_unit)
            failures.append("%s: README unit %r != expected %r" % (claim.cid, claimed_unit, claim.expect_unit))
        elif not source_unit_ok:
            verdict = "FAIL unit: source data is in %r, claim assumes %r" % (source_unit, claim.source_unit)
            failures.append("%s: source unit %r != %r" % (claim.cid, source_unit, claim.source_unit))
        elif not value_ok:
            verdict = "FAIL value"
            failures.append("%s: README says %s %s, recomputed %s"
                            % (claim.cid, claimed, claimed_unit or claim.expect_unit,
                               round(recomputed, claim.decimals + 2)))
        else:
            verdict = "ok"

        print("%-6s %-44s %10s %12s %-11s %s"
              % (claim.cid, claim.what[:44], claimed, round(recomputed, claim.decimals + 2),
                 claimed_unit or claim.expect_unit, verdict))
        if claim.note:
            print("%-6s   %s" % ("", claim.note))
        unit_rows.append((claim.cid, claimed_unit or claim.expect_unit, claim.source_unit,
                          readme_unit_ok and source_unit_ok))
        # Every value this gate successfully re-derived, with its unit. README's
        # FIGURES check and the repository description are both checked against
        # this set: a number there is a claim and must come from committed data.
        derived.append((round(recomputed, claim.decimals), claim.expect_unit))
    return failures, unit_rows, derived


def unbacked_figures(text, derived):
    """[(value, unit)] for every number-with-unit in `text` that no claim re-derived.

    A figure is what C.extract_figures finds: a number followed by a unit
    (ms, us, %, x, GB, ...). Versions carry no unit and are never figures. Link
    targets and bare URLs are dropped first, as they are for the denylist: an
    href is not a claim.
    """
    out = []
    for value, unit in C.extract_figures(C.strip_link_targets(text)):
        if not any(C.close_enough(value, dv, 2) and unit.lower() == (du or "").lower()
                   for dv, du in derived):
            out.append((value, unit))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--readme", default="README.md")
    ap.add_argument("--denylist", default=os.path.join("scripts", "ci", "claim-denylist.txt"))
    ap.add_argument("--description", default=os.path.join("docs", "repo-description.md"),
                    help="the pinned About text (a ```text fenced block)")
    ap.add_argument("--no-network", action="store_true",
                    help="skip the live GitHub comparison. Pull requests run with this: a PR "
                         "must never fail for a repository-settings change it did not make.")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    readme_path = os.path.join(repo, a.readme)
    readme = C._read(readme_path)

    print("=" * 100)
    print("CLAIMS GATE -- every README figure must be recomputed from committed data in this repo")
    print("=" * 100)
    print()
    print("%-6s %-44s %10s %12s %-11s %s" % ("id", "claim", "README", "recomputed", "unit", "verdict"))
    print("-" * 100)

    claims = build_claims(repo)
    if not claims:
        print("  (no claims: README quotes no results -- they are held locally under NC QDL v7 4.6(i))")
    failures, unit_rows, derived = run_claims(claims, readme)

    # --- unit summary ------------------------------------------------------
    print()
    print("-" * 100)
    print("UNIT CHECK -- the unit README writes vs the unit the data is measured in")
    print("-" * 100)
    if not unit_rows:
        print("  (no claims to check)")
    for cid, readme_unit, source_unit, ok in unit_rows:
        print("  %-6s README writes %-11s source measured in %-9s %s"
              % (cid, readme_unit, source_unit, "ok" if ok else "FAIL"))

    # --- figures -----------------------------------------------------------
    # A number with a unit in README is a claim, exactly as in the pinned
    # description below. Anchored claims above re-derive theirs; anything else
    # has nothing in the tree behind it. Since 2026-09-27 that is every figure:
    # results are held locally, so README must quote none.
    print()
    print("-" * 100)
    print("FIGURES -- every number with a unit in README must be re-derived by a claim above")
    print("-" * 100)
    loose = unbacked_figures(readme, derived)
    if not loose:
        print("  ok     no figure in README without a claim")
    for value, unit in loose:
        print("  FAIL   figure %s %s in README cannot be re-derived from committed data" % (value, unit))
        failures.append("README figure %s %s not re-derivable" % (value, unit))

    # --- denylist ----------------------------------------------------------
    print()
    print("-" * 100)
    print("DENYLIST -- asserted claim strings the committed record does not support")
    print("-" * 100)
    rules = C.load_denylist(os.path.join(repo, a.denylist))
    # Exemptions are sentences inspected and found already correct -- an
    # out-of-scope list, a quoted study, a self-correction. Each is written down
    # with its reason in the same file as the rules, so the judgement is
    # reviewable rather than a silent special case.
    exempt = C.load_exemptions(os.path.join(repo, a.denylist))
    hits = C.scan_denylist(readme, rules, exempt)
    print("  %d rules and %d exemption(s) loaded from %s"
          % (len(rules), len(exempt), a.denylist))
    if hits:
        for pattern, why, sentence in hits:
            print("  FAIL /%s/ -- %s" % (pattern, why))
            print("       %s" % sentence[:160])
            failures.append("denylist /%s/: %s" % (pattern, sentence[:90]))
    else:
        print("  ok -- no asserted violation (mentions inside denials or planned-markings are exempt by design)")

    # --- prose beyond README ------------------------------------------------
    # README was never the only text a reader acts on, and scripts/ is the worse
    # surface, because those files are INSTRUCTIONS. Three of them told the
    # reader to provision a Graviton runtime host and then probe for /dev/kvm on
    # an instance type that has none; one printed a false host attribution
    # directly beneath the published deltas. A false sentence in a script is
    # executed, not merely read, so scripts/ is a hard failure.
    #
    # docs/ is WARN ONLY. It carries the project's superseded record on purpose,
    # so its backlog is a migration to make, not a build to break.
    #
    # Struck-out text is removed before scanning, everywhere: this repo marks
    # superseded prose with tildes and keeps it deliberately, and a scanner that
    # read it as live text would report the honest record as a violation.
    print()
    print("-" * 100)
    print("PROSE BEYOND README -- runnable trees hard-fail; docs/ and results/ warn")
    print("-" * 100)
    # gitignored, local-only: CI never sees them, so a local run must not either
    skip = C.LOCAL_ONLY
    for label, globs, hard in (
            # Widened 2026-09-21 from scripts/ alone. orin-native/ holds 32
            # tracked files (16 shell) and ipc-test/ 6, every .md among them a
            # README a reader follows -- the same "instructions a reader
            # executes" category that made scripts/ hard-fail, and none of it
            # had ever been scanned. It was clean at the time of widening
            # (0 asserted hits), so this costs nothing and closes the gap
            # before something drifts into it.
            ("runnable/", ["scripts/**/*.sh", "scripts/**/*.bat",
                           "scripts/**/*.ps1", "scripts/**/*.md",
                           "orin-native/**/*.sh", "orin-native/**/*.md",
                           "ipc-test/**/*.sh", "ipc-test/**/*.md"], True),
            # docs/**, not docs/*: the FuSa, Cyber and TARA gate material under
            # docs/fusa|cyber|tara and docs/middleware are published prose making
            # claims, and were never scanned until 2026-09-21. README said "docs/**"
            # while the gate read "docs/*" -- the README was the accurate one.
            ("docs/", ["docs/**/*.md"], False),
            # results/ was the last unscanned prose surface. A record that
            # misstates what was done is as misleading as a doc that does --
            # results/cloud/ is named "cloud" although its runs were recorded on
            # a Windows PC. Warn, not fail -- these are dated records, and
            # correcting one is an edit to history that wants a human deciding it.
            ("results/", ["results/**/*.md"], False)):
        files = C.prose_files(repo, globs, exclude=skip)
        found = []
        for rel in files:
            text = C.strip_superseded(C._read(os.path.join(repo, rel)))
            for _pattern, why, sentence in C.scan_denylist(text, rules, exempt):
                found.append((rel, why, " ".join(sentence.split())))
        print("  %-9s %3d files, %d asserted hit(s)%s"
              % (label, len(files), len(found), "" if hard else "   [warn only]"))
        for rel, why, sentence in found:
            print("  %s %s -- %s" % ("FAIL" if hard else "WARN", rel, why))
            print("       %s" % sentence[:150])
            if hard:
                failures.append("%s: %s" % (rel, sentence[:90]))
        if found and not hard:
            print("  ^ not failures: docs/ keeps superseded prose on purpose. This is the")
            print("    migration backlog -- text a reader would still take as current.")

    # --- overwrite-only files ----------------------------------------------
    # Some files are the RECORD and some are the CURRENT STATE, and the two want
    # opposite disciplines. docs/findings.md is append-only: dated, never
    # rewritten, and its strike-throughs are the project's honest history.
    # A briefing is the opposite. When a current-state file accumulates
    # "~~old claim~~ **2026-xx-xx: new claim**", answering "what is true now"
    # costs a full read of the file and fails silently when one line is missed.
    # That is not hypothetical: it is how docs/architecture.md came to say
    # "Current: A4" nine lines above a paragraph saying A6 is current, and how
    # CLAUDE.md's Phase status grew to 464 lines carrying 42 struck segments.
    #
    # Files listed here state the current truth and nothing else. History for
    # them lives in git and in docs/findings.md.
    print()
    print("-" * 100)
    print("OVERWRITE-ONLY FILES -- current state, no accumulated strike-throughs")
    print("-" * 100)
    for rel in OVERWRITE_ONLY:
        full = os.path.join(repo, rel)
        if not os.path.exists(full):
            print("  skipped %s (not present)" % rel)
            continue
        n = C.count_strike_markers(C._read(full))
        if n:
            print("  FAIL   %-28s %d strike marker(s)" % (rel, n))
            print("         This file states current state. Delete the old sentence and write")
            print("         the new one; git and docs/findings.md keep the history.")
            failures.append("%s: %d strike-through segment(s) in an overwrite-only file" % (rel, n))
        else:
            print("  ok     %-28s no strike markers outside inline code" % rel)

    # --- the repository description ----------------------------------------
    # This was the one surface the gate structurally could not see, because it
    # is GitHub metadata rather than a file -- and it drifted for exactly that
    # reason, describing an AWS Graviton cloud twin for weeks after README and
    # findings.md had recorded that no cloud leg was ever built.
    #
    # The fix is a PIN: docs/repo-description.md holds the authoritative text,
    # gets the same denylist and the same figure verification as README, and is
    # compared against the live value. The pinned file is a hard failure because
    # it is committed and a commit can fix it. The live comparison is a hard
    # failure too, but only where it can be acted on -- see --no-network.
    #
    # Matching is the same SENTENCE-level classifier used everywhere else, not a
    # substring scan. A substring deny on "Graviton" would also fail a correct
    # sentence that merely names the hardware -- an a1.metal instance IS
    # Graviton1 -- where what is banned is a Graviton *leg* or runtime host. The
    # distinction between the two is the whole point, and only a classifier can
    # express it.
    print()
    print("-" * 100)
    print("REPO DESCRIPTION -- the highest-exposure text, pinned and verified")
    print("-" * 100)
    desc_path = os.path.join(repo, a.description)
    pinned = None
    try:
        pinned = C.read_pinned_description(desc_path)
        print("  pinned : %s" % a.description)
        print("           %s" % pinned)
    except (IOError, OSError, ValueError) as exc:
        print("  FAIL   cannot read the pinned description: %s" % exc)
        failures.append("repo-description: %s" % exc)

    if pinned is not None:
        # (a) the same denylist, on the pinned text
        phits = C.scan_denylist(pinned, rules, exempt)
        if phits:
            for pattern, why_banned, sentence in phits:
                print("  FAIL   /%s/ -- %s" % (pattern, why_banned))
                print("         %s" % sentence[:160])
                failures.append("repo-description denylist: %s" % sentence[:90])
        else:
            print("  ok     no asserted violation in the pinned text")

        # (b) a number in the description is a claim, exactly as in README
        figs = C.extract_figures(pinned)
        if not figs:
            print("  ok     no figures in the description to verify")
        else:
            for value, unit in figs:
                match = any(C.close_enough(value, dv, 2) and unit.lower() == (du or "").lower()
                            for dv, du in derived)
                if match:
                    print("  ok     figure %s %s is re-derivable from committed data" % (value, unit))
                else:
                    print("  FAIL   figure %s %s in the description cannot be re-derived" % (value, unit))
                    failures.append("repo-description figure %s %s not re-derivable" % (value, unit))

    # (c) live vs pinned
    if a.no_network:
        print("  SKIPPED live comparison (--no-network): pull requests do not fail on a")
        print("          settings change they did not make. Push and the weekly run do check it.")
    else:
        slug = C.repo_slug_from_git(repo)
        if not slug:
            print("  SKIPPED live comparison: could not determine owner/name from git")
        else:
            live, why = C.github_description(slug)
            if live is None:
                # Degrade honestly. An unreachable API is not a pass.
                print("  SKIPPED live comparison (%s): %s" % (slug, why))
                print("          This is NOT a pass. The pinned text was checked; the live value was not.")
            elif pinned is None:
                print("  SKIPPED live comparison: nothing pinned to compare against")
            else:
                drift = C.describe_drift(pinned, live, "live (%s)" % slug)
                if not drift:
                    print("  ok     live description matches the pin (%s)" % slug)
                else:
                    print("  FAIL   live description has drifted from the pin")
                    for line in drift:
                        print("         %s" % line)
                    print("         Fix it in repository settings, or update the pin and commit.")
                    failures.append("repo-description: live value has drifted from the pin")
                # the live value gets the denylist too, not just the pin
                for pattern, why_banned, sentence in C.scan_denylist(live, rules, exempt):
                    print("  FAIL   live /%s/ -- %s" % (pattern, why_banned))
                    print("         %s" % sentence[:160])
                    failures.append("live description denylist: %s" % sentence[:90])

    # --- what this gate did NOT check --------------------------------------
    print()
    print("-" * 100)
    print("NOT CHECKED -- claims with no committed data to re-derive from")
    print("-" * 100)
    for what, why in UNBACKED:
        print("  unbacked  %-46s %s" % (what[:46], why))

    print()
    print("=" * 100)
    if failures:
        print("RESULT: FAIL -- %d problem(s)" % len(failures))
        for f in failures:
            print("  - %s" % f)
        print("=" * 100)
        return 1
    print("RESULT: PASS -- README's figures, prose and description all check out against the tree")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    # The scanned prose carries characters the owner's console encoding cannot
    # represent (cp950 chokes on U+2265 in the FuSa worksheets). Without this,
    # the gate CRASHES locally on text it prints fine in Actions, which is the
    # CI-passes/local-fails shape claims_lib._read already warns about, only on
    # the output side. errors="replace" keeps the console's own encoding and
    # substitutes the few glyphs it cannot draw, rather than reconfiguring to
    # UTF-8 and printing mojibake.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # pragma: no cover - old/odd streams
            pass
    sys.exit(main())
