"""Proof that the claims gate fails when it should.

These encode the three ways a README figure can go wrong, each demonstrated by
hand on 2026-09-19 before being written down here:

  A. the VALUE drifts                 -> FAIL value
  B. only the UNIT changes            -> FAIL unit   (digits identical)
  C. the claim is reworded or deleted -> FAIL not found

C is the one that closes the obvious evasion: if softening a sentence made the
gate green, the cheapest way past a failing check would be to delete the claim.

These tests exist because an earlier draft of the gate stored each claimed value
as a Python constant and compared that constant against the data -- so editing
README changed nothing and the gate passed unconditionally. It was caught only
by deliberately corrupting a number. Never delete these tests; a gate that has
only ever passed is not evidence of anything.
"""
import io
import os
import subprocess
import sys

GATE = os.path.join("scripts", "ci", "claims_gate.py")
STAGED = "README-gate-test.md"


def _run_gate(repo_root, readme_rel):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, os.path.join(repo_root, GATE), "--repo", repo_root, "--readme", readme_rel],
        cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env,
    )


def _stage(repo_root, old, new):
    """Write a copy of README with `old` replaced by `new`. Never touches README.md."""
    src = os.path.join(repo_root, "README.md")
    with io.open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert text.count(old) == 1, "anchor text %r is not unique in README.md" % old
    staged = os.path.join(repo_root, STAGED)
    with io.open(staged, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text.replace(old, new))
    return staged


def test_a_wrong_value_fails(repo_root):
    staged = _stage(repo_root, "Orin **+24.9%** median", "Orin **+31.5%** median")
    try:
        proc = _run_gate(repo_root, STAGED)
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode == 1, out[-2000:]
        assert "FAIL value" in out
        assert "31.5" in out
    finally:
        os.remove(staged)


def test_b_unit_change_alone_is_a_hard_failure(repo_root):
    """Same digits, different unit. This must fail, not warn."""
    staged = _stage(repo_root, "other four runs span 33 ms", "other four runs span 33 s")
    try:
        proc = _run_gate(repo_root, STAGED)
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode == 1, out[-2000:]
        assert "FAIL unit" in out
    finally:
        os.remove(staged)


def test_c_rewording_a_claim_away_fails(repo_root):
    """Deleting or softening a number must not buy a green build."""
    staged = _stage(repo_root, "Orin **2.15×** slower", "Orin noticeably slower")
    try:
        proc = _run_gate(repo_root, STAGED)
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode == 1, out[-2000:]
        assert "FAIL not found" in out
    finally:
        os.remove(staged)


def test_the_committed_readme_still_passes(repo_root):
    """The other three tests are only meaningful if the real document is green."""
    proc = _run_gate(repo_root, "README.md")
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, out[-3000:]
    assert "RESULT: PASS" in out
