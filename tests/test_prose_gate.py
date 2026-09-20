"""Proof for the prose surfaces the gate did not used to see.

Until 2026-09-20 the claims gate read exactly one file: README.md. A repo-wide
sweep that day found the rot was somewhere else entirely -- 9 of 17 confirmed
findings were in scripts/, none of which was scanned by anything:

  * scripts/twin/diff-results.sh printed "host: Graviton3 Neoverse-V1 (cloud)"
    directly beneath the published deltas. That CSV was recorded on the owner's
    local x86_64 Windows PC under QEMU TCG. docs/ had corrected the same
    sentence twice; neither correction ever reached the script.
  * scripts/bootstrap-runtime-host.sh told the user "confirm the instance type
    supports KVM (c7g.* should)" at the exact moment the probe failed -- on the
    one instance class the project had itself proven exposes no /dev/kvm.
  * scripts/README.md promised the same step "verifies that /dev/kvm is
    exposed", two lines after telling the reader to launch a c7g.large.

A false sentence in a doc is read. A false sentence in a script is executed.
That is why scripts/ is a hard failure here and docs/ is warn-only.

The second half of this module pins the Graviton rule's NARROWING. The rule was
a bare \\bGraviton\\b, correct when written because every Graviton sentence in
the repo was then false. On 2026-09-19 a QNX guest booted under KVM on a1.metal
and a true, assertable Graviton fact came into existence -- at which point the
rule was banning the project's own cross-vendor evidence along with the lie.
Narrowing a denylist rule to let one's own new sentence through is exactly how
a gate rots, so both directions are pinned: the dangerous claims must still
fail, and the true one must pass.
"""
import io
import os
import subprocess
import sys

import claims_lib as C

DENYLIST = os.path.join("scripts", "ci", "claim-denylist.txt")
GATE = os.path.join("scripts", "ci", "claims_gate.py")
STAGED_SCRIPT = os.path.join("scripts", "prose-gate-test.sh")

# Sentences that assert a Graviton LEG or a Graviton NUMBER. None of this ever
# existed: no cloud leg was built and no timing, latency or throughput figure
# was ever taken on AWS.
MUST_BLOCK = [
    "The cloud twin runs on a Graviton c7g.large runtime host.",
    "Latency was measured on Graviton and on the Orin.",
    "Graviton gives us the cloud leg of the twin.",
    "We benchmarked the QNX guest on AWS Graviton.",
    "Boot time on Graviton was 29 s.",
    "Graviton produced a p50 figure of 2.0 ms.",
    "The Graviton runtime host recorded the cloud numbers.",
    "We measured throughput on Graviton.",
]

# True statements, all backed by logs/sample-boot/aws-a1-metal-kvm-*.log. These
# are the project's cross-vendor evidence: the same defect, and the same fix,
# on Cortex-A72 as on the Orin's A78AE. A rule that blocks these is wrong.
MUST_ALLOW = [
    "The one QNX ships hangs under KVM, on Orin and on AWS Graviton alike.",
    "The same hang reproduces on AWS Graviton1 silicon, a different vendor.",
    "A QNX guest booted under KVM on AWS Graviton bare metal.",
]


def _rules(repo_root):
    return C.load_denylist(os.path.join(repo_root, DENYLIST))


def _fires(sentence, rules):
    return bool(C.scan_denylist(sentence, rules))


# --------------------------------------------------------------------------
# the narrowed Graviton rule, both directions


def test_graviton_leg_and_figure_claims_still_fail(repo_root):
    rules = _rules(repo_root)
    leaked = [s for s in MUST_BLOCK if not _fires(s, rules)]
    assert not leaked, "narrowing let a Graviton leg/figure claim through: %r" % leaked


def test_the_cross_vendor_defect_evidence_is_allowed(repo_root):
    rules = _rules(repo_root)
    blocked = [s for s in MUST_ALLOW if _fires(s, rules)]
    assert not blocked, "rule blocks a true, logged Graviton statement: %r" % blocked


def test_narrowing_did_not_widen_the_readme_surface(repo_root):
    """README must stay clean under the new rules, as it was under the old one."""
    readme = C._read(os.path.join(repo_root, "README.md"))
    assert C.scan_denylist(readme, _rules(repo_root)) == []


# --------------------------------------------------------------------------
# helpers the wider scan depends on


def test_struck_through_text_is_not_scanned(repo_root):
    """This repo keeps superseded prose on purpose, marked with tildes.

    Reading it as live text would report the honest record as a violation --
    which is the opposite of what the gate is for.
    """
    rules = _rules(repo_root)
    live = "Latency was measured on Graviton and on the Orin."
    assert _fires(live, rules)
    assert C.scan_denylist(C.strip_superseded("~~%s~~" % live), rules) == []
    # text outside the markers survives untouched
    assert "keep" in C.strip_superseded("keep ~~drop~~ keep")
    assert "drop" not in C.strip_superseded("keep ~~drop~~ keep")


def test_local_only_files_are_excluded_from_discovery(repo_root):
    """A gitignored file must not make a developer's run disagree with CI's.

    docs/interview-narrative.md and docs/cv-architecture-brief.md exist on the
    owner's machine and in no clone. If the gate scanned them, a local failure
    would be unreproducible in Actions -- the worst failure shape available.
    """
    skip = ("interview-narrative.md", "cv-architecture-brief.md")
    found = C.prose_files(repo_root, ["docs/*.md"], exclude=skip)
    assert found, "discovery returned nothing at all"
    assert all(os.path.basename(p) not in skip for p in found)
    assert all(p.startswith("docs/") and "\\" not in p for p in found)


# --------------------------------------------------------------------------
# the scripts/ surface itself


def test_scripts_tree_is_currently_clean(repo_root):
    """Regression guard on the 2026-09-20 cleanup.

    Every executable and README under scripts/ was corrected that day so this
    surface could be made a hard failure. If this list ever grows again, the
    fix is the sentence, not this test.
    """
    rules = _rules(repo_root)
    globs = ["scripts/**/*.sh", "scripts/**/*.bat", "scripts/**/*.ps1", "scripts/**/*.md"]
    hits = []
    for rel in C.prose_files(repo_root, globs):
        text = C.strip_superseded(C._read(os.path.join(repo_root, rel)))
        for _pattern, why, sentence in C.scan_denylist(text, rules):
            hits.append("%s: %s (%s)" % (rel, " ".join(sentence.split())[:90], why))
    assert hits == [], "asserted claims the data does not support:\n  " + "\n  ".join(hits)


def test_a_false_sentence_in_a_script_fails_the_gate(repo_root):
    """The bite test: scripts/ is a hard failure, not a warning.

    Without this, 'scripts/ is scanned' could be true while the result was
    discarded -- which is how the surface came to be unscanned in the first
    place.
    """
    staged = os.path.join(repo_root, STAGED_SCRIPT)
    with io.open(staged, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("#!/usr/bin/env bash\n"
                 "# Boot time on Graviton was 29 s.\n"
                 "exit 0\n")
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, os.path.join(repo_root, GATE), "--repo", repo_root],
            cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=env,
        )
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode != 0, "a false sentence in scripts/ did not fail the gate:\n" + out
        assert "prose-gate-test.sh" in out
    finally:
        os.remove(staged)


def test_docs_are_reported_but_never_fail_the_build(repo_root):
    """docs/ carries the project's superseded record deliberately.

    Failing a pull request over that backlog would make every honest history
    entry a build break, so those hits are printed and never counted.
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, os.path.join(repo_root, GATE), "--repo", repo_root],
        cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env,
    )
    out = proc.stdout.decode("utf-8", "replace")
    assert "PROSE BEYOND README" in out
    assert "[warn only]" in out
    assert proc.returncode == 0, "the committed tree must pass:\n" + out
