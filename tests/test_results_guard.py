"""Tests that results_guard.py fails when a result is on its way into the public tree.

Every repo here is a throwaway one made under tmp_path, with synthetic text only:
no figure below was measured by anything.
"""
import os
import subprocess
import sys

import pytest

import results_guard as G

KNOWN_HEADER = """#!/usr/bin/env bash
# run-x.sh -- a synthetic harness.
#
# WHAT IS KNOWN. The question comes from record 20990101T-a6-x (held locally).
{known}
#
# THE RUN. n = 1000 at 2 ms spacing.
#   P1 median <= -5 us.
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "guard@example.invalid")
    _git(r, "config", "user.name", "guard test")
    _git(r, "config", "commit.gpgsign", "false")
    return r


def _commit(repo, files, message="test: a change"):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        _git(repo, "add", "-f", rel)
    _git(repo, "commit", "-q", "-m", message)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def _guard(repo, *args, allowlist=None):
    return G.main(["--repo", str(repo), "--allowlist", str(allowlist or os.devnull), *args])


def test_figures_are_numbers_with_units_not_glued_to_words():
    got = [f for _s, _e, f in G.figures("at 2 ms, +59.3 us, 12.5µs, 5%, 2.15×, 640 mW")]
    assert got == ["2 ms", "59.3 us", "12.5µs", "5%", "2.15×", "640 mW"]
    assert G.figures("arms t2ms and D200us, register 0x5A, v8.0, sha 8cad8299, k=12") == []


def test_what_is_known_ends_at_a_blank_comment_or_the_next_heading():
    text = KNOWN_HEADER.format(known="# It cost +59.3 us there.")
    lines = [line for _n, line in G.known_sections(text)]
    assert lines[0].startswith("# WHAT IS KNOWN.")
    assert "# It cost +59.3 us there." in lines
    assert not any("THE RUN" in x or "P1" in x for x in lines), "the design and predictions are not in it"
    text2 = "# WHAT IS KNOWN. A.\n# still known 3 ms\n# THE RUN. 2 ms\n"
    assert [line for _n, line in G.known_sections(text2)] == ["# WHAT IS KNOWN. A.", "# still known 3 ms"]


def test_a_figure_added_to_what_is_known_fails_and_the_design_below_it_does_not(repo, capsys):
    base = _commit(repo, {"h/run-x.sh": KNOWN_HEADER.format(known="# It is in the record.")})
    _commit(repo, {"h/run-x.sh": KNOWN_HEADER.format(known="# It cost +59.3 us there.")})
    assert _guard(repo, "--base", base) == 1
    out = capsys.readouterr().out
    assert "KNOWN  h/run-x.sh" in out and "'59.3 us'" in out
    assert "'2 ms'" not in out and "'5 us'" not in out, "THE RUN and P1 are outside the section"


def test_the_reviewed_baseline_passes_and_only_additions_are_questioned(repo, capsys):
    base = _commit(repo, {"docs/a.md": "The board has 8 GB of RAM.\n"})
    _commit(repo, {"docs/a.md": "The board has 8 GB of RAM.\nIt ran 8 GB in a sentence twice: 8 GB.\n"})
    assert _guard(repo, "--base", base) == 1
    out = capsys.readouterr().out
    assert out.count("FAIL DOCS") == 2, "one 8 GB was there before; the two new ones are not"
    head2 = _commit(repo, {"docs/a.md": "The board has 8 GB of RAM.\n"})
    assert _guard(repo, "--base", head2) == 0


def test_the_root_readme_is_claims_gates_and_a_sub_readme_is_guarded(repo, capsys):
    base = _commit(repo, {"README.md": "x\n", "tools/README.md": "x\n"})
    _commit(repo, {"README.md": "p50 181 us\n", "tools/README.md": "p50 182 us\n"})
    assert _guard(repo, "--base", base) == 1
    out = capsys.readouterr().out
    assert "tools/README.md" in out and "FAIL DOCS  README.md" not in out


def test_an_allowlist_entry_clears_only_its_literal(repo, tmp_path, capsys):
    base = _commit(repo, {"docs/a.md": "x\n"})
    _commit(repo, {"docs/a.md": "halt_poll_ns 5000000, a 5 ms window. It saved 33 us.\n"})
    allow = tmp_path / "allow.txt"
    allow.write_text("docs/*.md\ta 5 ms window\tconfigured, not measured\n", encoding="utf-8")
    assert _guard(repo, "--base", base, allowlist=allow) == 1
    out = capsys.readouterr().out
    assert "'33 us'" in out and "'5 ms'" not in out


def test_an_allowlist_entry_without_a_reason_is_refused(tmp_path):
    allow = tmp_path / "allow.txt"
    allow.write_text("docs/*.md\t5 ms\n", encoding="utf-8")
    with pytest.raises(ValueError):
        G.load_allowlist(str(allow))


def test_evaluation_output_in_the_tree_fails_even_without_a_base(repo, capsys):
    _commit(repo, {"results/orin-native-port/20990101T-a6-x/results.md": "x\n",
                   "logs/sample-boot/boot.log": "x\n",
                   "results/cloud/cloud-ipc-latest.csv": "x\n",
                   "results/gicv3-nisv-debug/20990101T000000Z/summary.md": "x\n",
                   "results/orin-native-port/20260909T1100Z/m3-design.md": "a design\n"})
    assert _guard(repo) == 1
    out = capsys.readouterr().out
    assert out.count("FAIL PATHS") == 4, "the four output paths; the design folder is not one"
    assert "m3-design.md" not in out


def test_a_figure_in_a_commit_message_fails(repo, capsys):
    base = _commit(repo, {"a.txt": "x\n"})
    _commit(repo, {"a.txt": "y\n"}, message="a6: record the ladder -- the doorbell is 55 us ahead")
    assert _guard(repo, "--commits", base + "..HEAD") == 1
    assert "COMMIT" in capsys.readouterr().out
    base2 = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                           check=True).stdout.strip()
    _commit(repo, {"a.txt": "z\n"}, message="a6: pre-register the doorbell test (record names only)")
    assert _guard(repo, "--commits", base2 + "..HEAD") == 0


def test_the_pre_push_hook_calls_the_guard_and_parses():
    hook = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "githooks", "pre-push")
    text = open(hook, encoding="utf-8").read()
    assert "results_guard.py" in text and "--base" in text and "--commits" in text
    if sys.platform != "win32":
        assert subprocess.run(["sh", "-n", hook]).returncode == 0
