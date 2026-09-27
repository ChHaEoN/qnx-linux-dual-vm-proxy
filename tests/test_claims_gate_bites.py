"""Proof that the claims gate fails when it should.

These encode the ways a README figure can go wrong, each demonstrated by hand
on 2026-09-19 before being written down here:

  A. the VALUE drifts                  -> FAIL value
  B. only the UNIT changes             -> FAIL unit   (digits identical)
  C. the claim is reworded or deleted  -> FAIL not found
  D. a figure appears with no claim    -> FAIL figure

C is the one that closes the obvious evasion: if softening a sentence made the
gate green, the cheapest way past a failing check would be to delete the claim.

WHY A-C RUN ON A SYNTHETIC README. Since 2026-09-27 the committed README quotes
no result (NC QDL v7 4.6(i); the run data is held locally), so there is no real
claim left to corrupt. A-C therefore drive the gate's own run_claims() with
claims built over tests/fixtures -- synthetic boot-time series whose median
delta, ratio and span are exact by construction -- against a synthetic README
text. D runs end to end on the committed README: planting one figure in it must
fail the build, because nothing in the tree could back it.

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

import claims_gate as G
import claims_lib as C

GATE = os.path.join("scripts", "ci", "claims_gate.py")
STAGED = "README-gate-test.md"

# Synthetic: fixture host B's median (1275 ms) is exactly +25.0% over host A's
# (1020 ms), and host A's five runs span exactly 40 ms.
SYNTHETIC_README = ("Fixture only. Host B is **+25.0%** slower than host A at median, "
                    "and host A's five runs span 40 ms.\n")


def _boot(fixtures_dir, name):
    return C.parse_boot_times(os.path.join(fixtures_dir, name))


def _delta_claim(fixtures_dir):
    def fn():
        a, ua = _boot(fixtures_dir, "boot-times-hostA-n5.txt")
        b, ub = _boot(fixtures_dir, "boot-times-hostB-n5.txt")
        assert ua == ub, "unit mismatch between the two fixture series"
        return C.pct_delta(C.median(a), C.median(b)), ua
    return G.Claim("T1", "fixture: host B vs host A, median",
                   r"Host B is \*\*\+([0-9.]+)(?P<unit>%)\*\* slower", 1, "%", "ms",
                   ["boot-times-hostA-n5.txt", "boot-times-hostB-n5.txt"], fn)


def _span_claim(fixtures_dir, series="boot-times-hostA-n5.txt"):
    def fn():
        v, u = _boot(fixtures_dir, series)
        return C.span(v), u
    return G.Claim("T2", "fixture: host A span",
                   r"five runs span ([0-9]+)\s*(?P<unit>ms|s|us|ns)\b", 0, "ms", "ms",
                   [series], fn)


def _check(fixtures_dir, readme, claims=None):
    claims = claims if claims is not None else [_delta_claim(fixtures_dir), _span_claim(fixtures_dir)]
    return G.run_claims(claims, readme)


def test_the_synthetic_claims_pass_and_are_derived(fixtures_dir, capsys):
    """The other synthetic tests mean something only if the clean text is green."""
    failures, unit_rows, derived = _check(fixtures_dir, SYNTHETIC_README)
    assert failures == [], failures
    assert [ok for _cid, _ru, _su, ok in unit_rows] == [True, True]
    assert (25.0, "%") in derived and (40, "ms") in derived
    assert "ok" in capsys.readouterr().out
    # ... and a derived figure is exactly what the FIGURES check accepts.
    assert G.unbacked_figures(SYNTHETIC_README, derived) == []
    assert G.unbacked_figures(SYNTHETIC_README, []) == [("25.0", "%"), ("40", "ms")]


def test_a_wrong_value_fails(fixtures_dir, capsys):
    failures, _u, _d = _check(fixtures_dir, SYNTHETIC_README.replace("**+25.0%**", "**+31.5%**"))
    out = capsys.readouterr().out
    assert "FAIL value" in out
    assert any("31.5" in f for f in failures), failures


def test_b_unit_change_alone_is_a_hard_failure(fixtures_dir, capsys):
    """Same digits, different unit. This must fail, not warn."""
    failures, _u, _d = _check(fixtures_dir, SYNTHETIC_README.replace("span 40 ms", "span 40 s"))
    assert "FAIL unit" in capsys.readouterr().out
    assert any("README unit" in f for f in failures), failures


def test_b_source_in_another_unit_is_a_hard_failure(fixtures_dir, capsys):
    """README's digits and unit both right, the DATA in seconds: still a failure."""
    claim = _span_claim(fixtures_dir, series="boot-times-seconds-n3.txt")
    failures, _u, _d = _check(fixtures_dir, SYNTHETIC_README, claims=[claim])
    assert "FAIL unit: source data" in capsys.readouterr().out
    assert any("source unit" in f for f in failures), failures


def test_c_rewording_a_claim_away_fails(fixtures_dir, capsys):
    """Deleting or softening a number must not buy a green build."""
    failures, _u, _d = _check(fixtures_dir, SYNTHETIC_README.replace("**+25.0%** slower", "noticeably slower"))
    assert "FAIL not found" in capsys.readouterr().out
    assert any("reworded or removed" in f for f in failures), failures


def _run_gate(repo_root, readme_rel):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, os.path.join(repo_root, GATE), "--repo", repo_root, "--readme", readme_rel,
         "--no-network"],
        cwd=repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env,
    )


def test_d_a_figure_with_no_claim_fails_the_gate(repo_root):
    """End to end on the committed README: one planted figure fails the build.

    README quotes no result, so no claim re-derives anything; a number with a
    unit in it has nothing in the tree behind it. The figure is synthetic.
    """
    with io.open(os.path.join(repo_root, "README.md"), "r", encoding="utf-8") as fh:
        text = fh.read()
    staged = os.path.join(repo_root, STAGED)
    with io.open(staged, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n\nThe round trip to the guest takes 1234 us at p50.\n")
    try:
        proc = _run_gate(repo_root, STAGED)
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode == 1, out[-2000:]
        assert "FAIL   figure 1234 us in README" in out
    finally:
        os.remove(staged)


def test_the_committed_readme_still_passes(repo_root):
    """The bite above is only meaningful if the real document is green."""
    proc = _run_gate(repo_root, "README.md")
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, out[-3000:]
    assert "RESULT: PASS" in out
    assert "no figure in README without a claim" in out
