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
import ast
import io
import os
import shutil
import subprocess
import sys

import claims_gate as G
import claims_lib as C
import test_prose_gate
from test_prose_gate import STAGED_SCRIPT as PROSE_STAGED

GATE = os.path.join("scripts", "ci", "claims_gate.py")
STAGED = "README-gate-test.md"

# The files the gate reads by name (its --readme, --denylist and --description
# defaults); its globbed surfaces are read from its source by _gate_globs().
NAMED = ("README.md", os.path.join("scripts", "ci", "claim-denylist.txt"),
         os.path.join("docs", "repo-description.md"))
# What another test file writes into the shared tree while it runs, inside the
# gate's surfaces: tests/test_prose_gate.py's two bite tests (the last test below
# holds these two lists to that file's source). The script it stages, a false
# sentence on purpose, is left out of the own tree. README.md, which its
# strike-through test rewrites in place for the length of one gate run, cannot
# be: the own tree copies it as it stands, so that race still reaches the
# committed-README test (partly fixed; the root fix, a tree of its own for
# each writer, is in test_prose_gate.py).
OTHERS_STAGED = (PROSE_STAGED,)
OTHERS_REWRITTEN = ("README.md",)

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


def _run_gate(repo_root, readme_rel, tree=None):
    """repo_root's gate, run over `tree` (the shared tree when None)."""
    tree = repo_root if tree is None else tree
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, os.path.join(repo_root, GATE), "--repo", tree, "--readme", readme_rel,
         "--no-network"],
        cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env,
    )


def _gate_globs(repo_root):
    """The gate's globbed surfaces as its source writes them: every list of glob
    strings in claims_gate.py, so a surface the gate gains is one the own tree
    holds."""
    with io.open(os.path.join(repo_root, GATE), "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    globs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) and "**" in e.value for e in node.elts):
            globs += [e.value for e in node.elts if isinstance(e, ast.Constant)]
    return globs


def _own_tree(src, dest, globs):
    """A tree of the test's own holding the files of `src` the gate reads: its
    named files and every file its own discovery finds over `globs`, but what
    another test file stages into the shared tree while it runs. A file another
    test rewrites in place (OTHERS_REWRITTEN) is copied as it stands."""
    skip = {p.replace(os.sep, "/") for p in OTHERS_STAGED}
    rels = {p.replace(os.sep, "/") for p in NAMED + tuple(G.OVERWRITE_ONLY)
            if os.path.isfile(os.path.join(src, p))}
    rels |= set(C.prose_files(src, globs, exclude=C.LOCAL_ONLY))
    for rel in sorted(rels - skip):
        target = os.path.join(str(dest), *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(src, *rel.split("/")), target)
    return str(dest)


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


def test_the_committed_readme_still_passes(repo_root, tmp_path):
    """The bite above is only meaningful if the real document is green.

    The gate reads a tree of the test's own:
    run in 12 processes by file, a gate over the shared tree read the script
    tests/test_prose_gate.py stages there, or found it gone between its glob and
    its read, and failed. The own tree holds every file of the tree the gate
    reads but that one. It still copies README.md from the shared tree, and
    test_prose_gate.py's strike-through test rewrites that file in place for
    the length of one gate run: a copy taken then carries the strike marker and
    this test fails (OTHERS_REWRITTEN; the race is only partly fixed).
    """
    own = _own_tree(repo_root, tmp_path / "tree", _gate_globs(repo_root))
    proc = _run_gate(repo_root, "README.md", tree=own)
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, out[-3000:]
    assert "RESULT: PASS" in out
    assert "no figure in README without a claim" in out


def test_the_own_tree_holds_the_gates_files_but_what_another_test_stages(repo_root, tmp_path):
    """The tree above: the gate's three globbed surfaces are found in its source,
    and the own tree holds the named files and every file the discovery finds,
    but a file another test file stages (test_prose_gate.py's script)."""
    globs = _gate_globs(repo_root)
    assert {"scripts/**/*.sh", "docs/**/*.md", "results/**/*.md"} <= set(globs), globs
    kept = [g.replace("**/*", "kept") for g in globs]  # one file under each surface: scripts/kept.sh, ...
    src = tmp_path / "src"
    for rel in NAMED + tuple(kept) + (PROSE_STAGED,):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(rel.replace(os.sep, "/") + "\n", encoding="utf-8")
    own = _own_tree(str(src), tmp_path / "own", globs)
    got = sorted(os.path.relpath(os.path.join(d, f), own).replace(os.sep, "/")
                 for d, _dirs, files in os.walk(own) for f in files)
    want = sorted({p.replace(os.sep, "/") for p in NAMED} | set(kept))
    assert got == want, got
    assert all(io.open(os.path.join(own, r), encoding="utf-8").read() == r + "\n" for r in got), got


def _shared_tree_writes(source, consts):
    """The shared-tree paths a test module's source opens for writing: in each
    function, a name bound to os.path.join(repo_root, X), X a string or a name
    in `consts`, then opened by open() or io.open() with a "w" or "a" mode."""
    found = set()
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, ast.FunctionDef):
            continue
        bound = {}
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == "os.path.join"
                    and len(node.value.args) == 2 and ast.unparse(node.value.args[0]) == "repo_root"):
                arg = node.value.args[1]
                rel = arg.value if isinstance(arg, ast.Constant) else consts.get(getattr(arg, "id", ""))
                if isinstance(rel, str):
                    bound[node.targets[0].id] = rel.replace(os.sep, "/")
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and ast.unparse(node.func) in ("open", "io.open") and node.args
                    and isinstance(node.args[0], ast.Name) and node.args[0].id in bound):
                modes = node.args[1:2] + [k.value for k in node.keywords if k.arg == "mode"]
                if any(isinstance(m, ast.Constant) and set(str(m.value)) & set("wa") for m in modes):
                    found.add(bound[node.args[0].id])
    return found


def test_what_test_prose_gate_writes_into_the_shared_tree_is_named_here():
    """OTHERS_STAGED and OTHERS_REWRITTEN name exactly the files
    tests/test_prose_gate.py opens for writing in the shared tree, so what the
    committed-README test says it is safe from, and what still reaches it, stays
    true. The scan is held on a made-up source first."""
    made_up = ("def test_x(repo_root):\n"
               "    a = os.path.join(repo_root, 'read.md')\n    io.open(a, 'r')\n"
               "    b = os.path.join(repo_root, NAME)\n    open(b, mode='a')\n"
               "    c = os.path.join(repo_root, 'w.md')\n    io.open(c, 'w', encoding='utf-8')\n")
    assert _shared_tree_writes(made_up, {"NAME": "x.sh"}) == {"x.sh", "w.md"}
    with io.open(test_prose_gate.__file__, "r", encoding="utf-8") as fh:
        writes = _shared_tree_writes(fh.read(), vars(test_prose_gate))
    named = {p.replace(os.sep, "/") for p in OTHERS_STAGED + OTHERS_REWRITTEN}
    assert writes == named, writes
