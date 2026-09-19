"""Tests that the claims gate actually fails when it should.

A gate that has only ever passed is unproven. These tests break things on
purpose -- a wrong number, a wrong unit, an unsupported claim -- and assert a
non-zero exit. If any of them starts passing-when-it-should-fail, the gate has
become decoration.

Each test copies the repo's README to a temporary file and edits the copy;
nothing here mutates the working tree.
"""
import io
import os
import shutil
import subprocess
import sys

GATE = os.path.join("scripts", "ci", "claims_gate.py")


def _run_gate(repo_root, readme_rel):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, os.path.join(repo_root, GATE), "--repo", repo_root, "--readme", readme_rel],
        cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env,
    )


def _readme_copy(repo_root, tmp_path, transform):
    src = os.path.join(repo_root, "README.md")
    with io.open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    text = transform(text)
    dst = tmp_path / "README-under-test.md"
    with io.open(str(dst), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    # The gate resolves --readme relative to --repo, so stage the copy inside it.
    staged = os.path.join(repo_root, "README-under-test.md")
    shutil.copyfile(str(dst), staged)
    return "README-under-test.md", staged


def test_gate_passes_on_the_committed_readme(repo_root):
    proc = _run_gate(repo_root, "README.md")
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, out[-3000:]
    assert "RESULT: PASS" in out


def test_gate_prints_a_claimed_vs_recomputed_table(repo_root):
    """The table is a requirement in its own right: a human must be able to read
    the check, not just its exit code."""
    out = _run_gate(repo_root, "README.md").stdout.decode("utf-8", "replace")
    assert "README" in out and "recomputed" in out
    assert "UNIT CHECK" in out
    assert "DENYLIST" in out
    assert "NOT CHECKED" in out


def test_gate_reports_unbacked_claims_rather_than_silently_passing(repo_root):
    out = _run_gate(repo_root, "README.md").stdout.decode("utf-8", "replace")
    assert "unbacked" in out
    assert "gitignored" in out


def test_denylist_fires_on_an_asserted_claim(repo_root, tmp_path):
    """Plant a claim the data does not support; the gate must fail."""
    rel, staged = _readme_copy(
        repo_root, tmp_path,
        lambda t: t + "\n\nThe Graviton runtime leg sustained 12000 samples under KVM.\n",
    )
    try:
        proc = _run_gate(repo_root, rel)
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode == 1, out[-3000:]
        assert "denylist" in out.lower()
    finally:
        os.remove(staged)


def test_denylist_does_not_fire_on_an_honest_denial(repo_root, tmp_path):
    """The exemption must hold: adding more honest framing must not break CI."""
    rel, staged = _readme_copy(
        repo_root, tmp_path,
        lambda t: t + "\n\nNothing here is ASIL-D certified, and no Graviton leg was ever built.\n",
    )
    try:
        proc = _run_gate(repo_root, rel)
        assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-3000:]
    finally:
        os.remove(staged)
