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
    "Graviton produced a p50 figure of 2.0 ms.",
    "The Graviton runtime host recorded the cloud numbers.",
    "We measured throughput on Graviton.",
    "IPC latency on a1.metal was 2.0 ms.",
    "We took a hardware-timed hypervisor number on the board.",
    "The A1 cloud leg ran under KVM.",
]

# True statements, all backed by logs/sample-boot/aws-a1-metal-kvm-*.log. These
# are the project's cross-vendor evidence: the same defect, and the same fix,
# on Cortex-A72 as on the Orin's A78AE. A rule that blocks these is wrong.
MUST_ALLOW = [
    "The one QNX ships hangs under KVM, on Orin and on AWS Graviton alike.",
    "The same hang reproduces on AWS Graviton1 silicon, a different vendor.",
    "A QNX guest booted under KVM on AWS Graviton bare metal.",
    # Moved here from MUST_BLOCK on 2026-09-20, and the move is the point: on
    # that day a1.metal -- which IS Graviton1 -- produced real boot timings
    # (median 4519.0 ms to the guest banner, n=5). A boot-time claim about
    # Graviton stopped being false by construction, so the rule had to stop
    # banning it. A wrong VALUE is not this file's job; the anchor machinery in
    # claims_gate.py re-derives README's numbers from the committed data.
    "Boot time on Graviton was 4519 ms.",
    # Measurements under KVM exist since 2026-09-19 (guest latency) and
    # 2026-09-20 (boot timing). The blanket "no KVM measurement" ban was
    # removed for exactly this reason.
    "Boot timing under KVM was measured on both hosts.",
    "Guest latency was measured with QNX as a KVM guest.",
    # "cloud leg" is the project's NAME for architecture A1, which ran on the
    # local Windows PC. The rules key on host tokens, never on this word.
    "The cloud-leg IPC benchmark produced its first real numbers.",
]


def _rules(repo_root):
    """Rules AND exemptions -- the gate never uses one without the other."""
    path = os.path.join(repo_root, DENYLIST)
    return C.load_denylist(path), C.load_exemptions(path)


def _fires(sentence, rules):
    return bool(C.scan_denylist(sentence, rules[0], rules[1]))


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
    rules, exempt = _rules(repo_root)
    assert C.scan_denylist(readme, rules, exempt) == []


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
    assert C.scan_denylist(C.strip_superseded("~~%s~~" % live), *rules) == []
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
    rules, exempt = _rules(repo_root)
    globs = ["scripts/**/*.sh", "scripts/**/*.bat", "scripts/**/*.ps1", "scripts/**/*.md"]
    hits = []
    for rel in C.prose_files(repo_root, globs):
        text = C.strip_superseded(C._read(os.path.join(repo_root, rel)))
        for _pattern, why, sentence in C.scan_denylist(text, rules, exempt):
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
                 "# The Graviton runtime host carried the cloud leg.\n"
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


# --------------------------------------------------------------------------
# the scanner fixes of 2026-09-20


def test_link_targets_are_not_scanned(repo_root):
    """A filename is not a claim.

    `adr-003-hardware-timed-qhv.md` exists only as an href, and scanning it
    fired the hardware-timed rule in four documents that each said the opposite
    of what the rule accused them of.
    """
    rules = _rules(repo_root)
    s = "See [ADR-003](adr-003-hardware-timed-qhv.md) for where it could come from."
    assert C.scan_denylist(C.strip_superseded(s), *rules) == []
    assert "ADR-003" in C.strip_superseded(s), "link TEXT must survive"
    assert "certified" not in C.strip_superseded("see https://x.example/a-certified-thing")


def test_sentences_do_not_merge_across_block_boundaries(repo_root):
    """A heading carries no full stop, so joining blocks glued three together.

    Three warnings on 2026-09-20 were that and nothing else: the claim sat in
    one block and its correction in the next, and no sentence held both.
    """
    md = "## A heading with no full stop\n\nWrapped prose that runs\non to here.\n\n| a | b |\n- bullet\n"
    sents = C.split_sentences(md)
    assert "## A heading with no full stop" in sents
    assert "Wrapped prose that runs on to here." in sents, "wrapped prose must still join"
    assert "| a | b |" in sents
    assert "- bullet" in sents


def test_every_exemption_is_justified_and_used(repo_root):
    """An exemption without a reason is a silent special case.

    It is also dead weight if nothing matches it any more -- a stale exemption
    would quietly re-open whatever it was written to allow.
    """
    path = os.path.join(repo_root, DENYLIST)
    exemptions = C.load_exemptions(path)
    assert exemptions, "the file should carry exemptions"
    unjustified = [rx for rx, why in exemptions if not why.strip()]
    assert not unjustified, "exemption with no stated reason: %r" % unjustified

    # Match against the NORMALISED sentences the scanner actually sees, not the
    # raw bytes: the diagram line is "Safety guest:   QNX OS for Safety" with
    # padding spaces, and findings.md wraps "**local Windows host**" across two
    # lines. Checking raw text reports live exemptions as stale.
    sentences = []
    scanned = ["docs/*.md", "README.md", "scripts/**/*.md", "scripts/**/*.sh",
               "scripts/**/*.bat", "scripts/**/*.ps1", "results/**/*.md"]
    for rel in C.prose_files(repo_root, scanned,
                             exclude=("interview-narrative.md", "cv-architecture-brief.md")):
        text = C.strip_superseded(C._read(os.path.join(repo_root, rel)))
        sentences.extend(C.split_sentences(text))
    corpus = chr(10).join(sentences)
    import re as _re
    unused = [rx for rx, _why in exemptions if not _re.search(rx, corpus, _re.I)]
    assert not unused, "exemption no longer matches anything, so it is stale: %r" % unused


# --------------------------------------------------------------------------
# overwrite-only files


def test_readme_carries_no_strike_throughs(repo_root):
    """README states current state, and the rule is enforced, not requested.

    It earned the rule twice over. CLAUDE.md's Phase status had grown to 464 of
    768 lines carrying 42 struck segments; README then took an owner decision as
    a patch into a section that still held six older corrections and ended up
    asserting both sides of it in the same paragraph. docs/findings.md is
    append-only and keeps that history properly; git keeps the rest.

    The AI briefings (CLAUDE.md, AGENTS.md) were unpublished on 2026-09-21 --
    development tooling, and a repo should carry one public statement of current
    state rather than two that can drift -- so README is the file this rule
    protects.
    """
    text = C._read(os.path.join(repo_root, "README.md"))
    # Inline code is excluded: the file documents this very rule and has to be
    # able to name the marker. One stray marker is a failure -- counting spans
    # and halving them reported zero for an unbalanced one, which is the
    # likeliest typo of all.
    assert C.count_strike_markers(text) == 0, (
        "README is overwrite-only: delete the old sentence, do not strike it")


def test_a_strike_through_in_an_overwrite_only_file_fails_the_gate(repo_root):
    """The bite test. A rule nothing enforces is only a preference."""
    target = os.path.join(repo_root, "README.md")
    original = C._read(target)
    try:
        with io.open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(original + "\n~~struck~~ **2026-01-01: replaced**\n")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, os.path.join(repo_root, GATE), "--repo", repo_root,
             "--no-network"],
            cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=env,
        )
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode != 0, (
            "a strike-through in README did not fail the gate:\n" + out)
        assert "strike marker" in out
    finally:
        with io.open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(original)
