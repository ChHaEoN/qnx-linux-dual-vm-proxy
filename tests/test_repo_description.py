"""The repository description is a claim, and until 2026-09-20 nothing checked it.

THE FAILURE CLASS. The GitHub "About" field is the highest-exposure sentence
this project has -- GitHub search, the owner's profile and every link preview
show it -- and it was the one surface the gate structurally could not see,
because it is repository metadata rather than a file in the tree. It drifted for
exactly that reason: it described an AWS Graviton cloud twin long after
README.md and docs/findings.md had recorded that no cloud leg was ever built and
that every figure labelled "cloud" came from a local Windows PC. No commit could
have caught it, because nothing was looking, and no commit can fix it either --
it is changed in settings.

THE FIX is a pin. docs/repo-description.md holds the authoritative text and gets
the same denylist and the same figure verification as README; the live value is
compared against it on push and on a weekly schedule.

WHY NOT SUBSTRING MATCHING, which is the obvious implementation. A substring
deny on "Graviton" fails the CURRENT, CORRECT description, whose Graviton clause
is this project's cross-vendor defect evidence: "the one QNX ships hangs under
KVM, on this board and on AWS Graviton alike." The distinction between that and
a claim of a Graviton *leg* is the entire point of the check, and only a
sentence-level classifier can express it. test_the_live_graviton_clause_is_not_a
_violation pins that, because a future reader will be tempted by the simpler
implementation.
"""
import io
import os
import subprocess
import sys

import claims_lib as C

DENYLIST = os.path.join("scripts", "ci", "claim-denylist.txt")
PINNED = os.path.join("docs", "repo-description.md")
GATE = os.path.join("scripts", "ci", "claims_gate.py")
STAGED = "repo-description-test.md"


def _rules(repo_root):
    path = os.path.join(repo_root, DENYLIST)
    return C.load_denylist(path), C.load_exemptions(path)


def _stage(repo_root, text):
    """A pinned-description file carrying `text`. Never touches the real one."""
    path = os.path.join(repo_root, STAGED)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# staged for a test\n\n```text\n%s\n```\n" % text)
    return path


def _run_gate(repo_root, description_rel):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, os.path.join(repo_root, GATE), "--repo", repo_root,
         "--description", description_rel, "--no-network"],
        cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env,
    )


# --------------------------------------------------------------------------
# the pin itself


def test_the_pinned_file_parses_and_is_one_line(repo_root):
    text = C.read_pinned_description(os.path.join(repo_root, PINNED))
    assert text, "the fenced block is empty"
    assert "\n" not in text, "the About field is a single line"
    assert len(text) <= 350, "GitHub truncates past 350 characters: %d" % len(text)


def test_the_pinned_description_passes_its_own_denylist(repo_root):
    rules, exempt = _rules(repo_root)
    text = C.read_pinned_description(os.path.join(repo_root, PINNED))
    assert C.scan_denylist(text, rules, exempt) == []


def test_the_live_graviton_clause_is_not_a_violation(repo_root):
    """The reason this check is a classifier and not a substring scan.

    Both sentences contain "Graviton". One is the project's cross-vendor defect
    evidence and one is a claim of a leg that was never built. A substring deny
    cannot tell them apart; that is why it was not used.
    """
    rules, exempt = _rules(repo_root)
    evidence = ("Booting it needed a startup we rebuilt: the one QNX ships hangs "
                "under KVM, on this board and on AWS Graviton alike.")
    a_leg = "The cloud twin runs on a Graviton c7g.large runtime host."
    assert C.scan_denylist(evidence, rules, exempt) == []
    assert C.scan_denylist(a_leg, rules, exempt) != []


# --------------------------------------------------------------------------
# live vs pinned


def test_matching_live_and_pinned_is_clean(repo_root):
    assert C.describe_drift("same text", "same text") == []
    assert C.describe_drift(" same text ", "same text") == [], "compared stripped"


def test_drift_is_reported_with_both_strings_visible(repo_root):
    drift = C.describe_drift("the pinned wording", "the drifted wording", "live (o/r)")
    assert drift, "a difference must be reported"
    blob = "\n".join(drift)
    assert "the pinned wording" in blob and "the drifted wording" in blob
    assert "docs/repo-description.md" in blob and "live (o/r)" in blob


def test_an_unreachable_api_is_not_a_pass(repo_root):
    """Degrade honestly: no value means SKIPPED, never silent success."""
    value, why = C.github_description("ChHaEoN/this-repository-does-not-exist-xyz")
    assert value is None
    assert why, "a skip must carry its reason"
    # and a None live value can never be mistaken for agreement
    assert C.describe_drift("anything", None) == []


# --------------------------------------------------------------------------
# the gate, end to end, hermetic


def test_a_denied_phrase_in_the_pinned_file_fails_the_gate(repo_root):
    staged = _stage(repo_root, "The cloud twin runs on a Graviton c7g.large runtime host.")
    try:
        proc = _run_gate(repo_root, STAGED)
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode != 0, "a denied phrase in the pin did not fail:\n" + out
        assert "repo-description" in out.lower() or "REPO DESCRIPTION" in out
    finally:
        os.remove(staged)


def test_an_unverifiable_number_in_the_description_fails(repo_root):
    """A number in the About field is a claim, exactly as in README."""
    staged = _stage(repo_root, "QNX boots as a KVM guest in 1234 ms on the board.")
    try:
        proc = _run_gate(repo_root, STAGED)
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode != 0, "an unverifiable figure did not fail:\n" + out
        assert "1234" in out and "re-derive" in out
    finally:
        os.remove(staged)


def test_a_version_string_is_not_treated_as_a_figure(repo_root):
    """"SDP 8.0" and "R36.4.7" are versions, not measurements.

    A figure is a number with a UNIT. Without that rule the real description --
    which names SDP 8.0 -- would fail for quoting its own toolchain version.
    """
    assert C.extract_figures("QNX SDP 8.0 on L4T R36.4.7") == []
    assert C.extract_figures("4519 ms, 2.45x, 1 GB") == [
        ("4519", "ms"), ("2.45", "x"), ("1", "GB")]


def test_the_committed_pin_passes_the_gate(repo_root):
    """The real file, hermetically. If this fails, the repo is inconsistent."""
    proc = _run_gate(repo_root, PINNED)
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert "SKIPPED live comparison (--no-network)" in out
