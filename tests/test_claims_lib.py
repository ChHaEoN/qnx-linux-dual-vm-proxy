"""Unit tests for the claims-gate helpers.

These test the LOGIC, against small synthetic fixtures, not the committed
corpus. A test that asserted "the A2 delta is 24.9%" would fail the day a new
run is appended, which is the gate's job, not a unit test's.
"""
import os

import pytest

import claims_lib as C


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------


def test_median_odd_and_even():
    assert C.median([3, 1, 2]) == 2.0
    # The even case is why this is not sorted(v)[len(v)//2].
    assert C.median([1, 2, 3, 4]) == 2.5
    assert C.median([5]) == 5.0


def test_median_does_not_mutate_input():
    values = [3, 1, 2]
    C.median(values)
    assert values == [3, 1, 2]


def test_median_empty_raises():
    with pytest.raises(ValueError):
        C.median([])


def test_pct_delta_basic_and_negative():
    assert C.pct_delta(100, 125) == pytest.approx(25.0)
    assert C.pct_delta(100, 75) == pytest.approx(-25.0)
    assert C.pct_delta(100, 100) == pytest.approx(0.0)


def test_pct_delta_zero_base_matches_delta_awk():
    # delta.awk returns 0 for a zero base rather than dividing; the two
    # implementations must agree on the edge case or CI and the published
    # report could disagree.
    assert C.pct_delta(0, 500) == 0.0


def test_ratio():
    assert C.ratio(2, 5) == pytest.approx(2.5)
    with pytest.raises(ZeroDivisionError):
        C.ratio(0, 5)


def test_span():
    assert C.span([1040, 1000, 1020]) == 40


def test_close_enough_respects_claim_precision():
    # README quotes +24.9%; the recomputation is 24.8992...
    assert C.close_enough(24.9, 24.89923, 1)
    # ... but a genuinely different number must not pass at that precision.
    assert not C.close_enough(24.9, 25.4, 1)
    assert C.close_enough(2.15, 2.1526, 2)
    assert not C.close_enough(2.15, 2.19, 2)


# --------------------------------------------------------------------------
# boot-times parsing
# --------------------------------------------------------------------------


def test_parse_boot_times_reads_runs_and_unit(fixtures_dir):
    values, unit = C.parse_boot_times(os.path.join(fixtures_dir, "boot-times-hostA-n5.txt"))
    assert values == [1000, 1010, 1020, 1030, 1040]
    assert unit == "ms"


def test_parse_boot_times_ignores_numbers_in_comments(fixtures_dir):
    """The header quotes 'median 99999 ms' in prose; it must not become data."""
    values, _ = C.parse_boot_times(os.path.join(fixtures_dir, "boot-times-hostA-n5.txt"))
    assert 99999 not in values
    assert len(values) == 5


def test_parse_boot_times_reports_seconds_as_seconds(fixtures_dir):
    """The unit is carried, not assumed -- this is what makes the unit gate real."""
    values, unit = C.parse_boot_times(os.path.join(fixtures_dir, "boot-times-seconds-n3.txt"))
    assert unit == "s"
    assert values == [1000, 1020, 1040]


def test_boot_times_fixture_pair_gives_exact_delta_and_ratio(fixtures_dir):
    a, _ = C.parse_boot_times(os.path.join(fixtures_dir, "boot-times-hostA-n5.txt"))
    b, _ = C.parse_boot_times(os.path.join(fixtures_dir, "boot-times-hostB-n5.txt"))
    assert C.median(a) == 1020
    assert C.median(b) == 1275
    assert C.pct_delta(C.median(a), C.median(b)) == pytest.approx(25.0)
    assert C.ratio(C.median(a), C.median(b)) == pytest.approx(1.25)


def test_parse_boot_times_rejects_a_file_with_no_runs(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("# only a header\n", encoding="utf-8")
    with pytest.raises(ValueError):
        C.parse_boot_times(str(p))


# --------------------------------------------------------------------------
# IPC CSV parsing -- the two committed files are structurally asymmetric
# --------------------------------------------------------------------------


def test_parse_ipc_csv_with_header_row(fixtures_dir):
    rows = C.parse_ipc_csv(os.path.join(fixtures_dir, "ipc-with-header.csv"))
    assert len(rows) == 1
    assert rows[0]["samples"] == 15
    assert rows[0]["p50_ns"] == 1000000


def test_parse_ipc_csv_without_header_row(fixtures_dir):
    rows = C.parse_ipc_csv(os.path.join(fixtures_dir, "ipc-headerless.csv"))
    assert len(rows) == 3
    assert rows[0]["samples"] == 100000


def test_last_row_is_the_compared_row(fixtures_dir):
    """Row selection changes the answer, so it is pinned by a test.

    The headerless fixture mirrors the real hw CSV: two 100,000-sample rows
    followed by a 15-sample row. diff-results.sh compares the LAST one.
    """
    rows = C.parse_ipc_csv(os.path.join(fixtures_dir, "ipc-headerless.csv"))
    assert C.last_row(rows)["samples"] == 15
    assert C.last_row(rows)["p50_ns"] == 1100000


def test_count_rows_with_samples(fixtures_dir):
    rows = C.parse_ipc_csv(os.path.join(fixtures_dir, "ipc-headerless.csv"))
    assert C.count_rows_with_samples(rows, 100000) == 2
    assert C.count_rows_with_samples(rows, 15) == 1


def test_parse_ipc_csv_rejects_malformed_row(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        C.parse_ipc_csv(str(p))


def test_notes_field_keeps_embedded_commas(tmp_path):
    """notes is free text and the last field; splitting must not truncate it."""
    p = tmp_path / "n.csv"
    p.write_text("1,2,48,3,4,5,1000000000,a,b,c\n", encoding="utf-8")
    rows = C.parse_ipc_csv(str(p))
    assert rows[0]["notes"] == "a,b,c"


# --------------------------------------------------------------------------
# sentence analysis -- the heart of the denylist
# --------------------------------------------------------------------------


def test_split_sentences_reflows_wrapped_prose():
    """A line-based matcher splits this claim from its negation; this must not."""
    text = "Not a reproduction of DRIVE OS, and not a\ncertified hypervisor. Next sentence."
    sentences = C.split_sentences(text)
    assert any("not a certified hypervisor" in s.lower() for s in sentences)


def test_negated_sentences_are_not_assertions():
    for s in [
        "Nothing in it is certified.",
        "No certified Type-1 isolation, no quantified freedom from interference.",
        "This is not DRIVE OS and not a certified hypervisor.",
        "ASIL-D certification | None.",
    ]:
        assert C.classify_sentence(s) == "negated", s


def test_planned_markings_are_not_assertions():
    assert C.classify_sentence("Graviton3 was the design intent.") == "planned"
    assert C.classify_sentence("The Graviton runtime leg was never built.") in ("negated", "planned")


def test_a_real_assertion_is_flagged():
    assert C.classify_sentence("Measured on Graviton under KVM at 1.2 ms.") == "asserted"
    assert C.classify_sentence("The system is ASIL-D certified.") == "asserted"


def test_scan_denylist_ignores_honest_denials_but_catches_claims(tmp_path):
    rules_file = tmp_path / "deny.txt"
    rules_file.write_text(
        "# comment line\n"
        "\\bASIL\\b\tno ASIL claim is supportable\n"
        "\\bGraviton\\b  the Graviton leg was never built\n",
        encoding="utf-8",
    )
    rules = C.load_denylist(str(rules_file))
    assert len(rules) == 2
    assert rules[0][1] == "no ASIL claim is supportable"

    honest = "Nothing here is ASIL-D certified. Graviton3 was the design intent."
    assert C.scan_denylist(honest, rules) == []

    dishonest = "The Safety guest is ASIL-D qualified for production."
    hits = C.scan_denylist(dishonest, rules)
    assert len(hits) == 1
    assert hits[0][0] == "\\bASIL\\b"


def test_load_denylist_skips_comments_and_blanks(tmp_path):
    p = tmp_path / "d.txt"
    p.write_text("\n# just a comment\n\n\\bfoo\\b\twhy foo is banned\n", encoding="utf-8")
    assert C.load_denylist(str(p)) == [("\\bfoo\\b", "why foo is banned")]


# --------------------------------------------------------------------------
# log parsing
# --------------------------------------------------------------------------


def test_serial_byte_markers(tmp_path):
    p = tmp_path / "cap.txt"
    p.write_text(
        "### ARM: control\n### serial bytes: 17\nnoise 999\n### ARM: fix\n### serial bytes: 1301\n",
        encoding="utf-8",
    )
    assert C.serial_byte_markers(str(p)) == [17, 1301]


def test_serial_bytes_are_platform_independent(tmp_path):
    """A serial-byte count must not depend on the checkout's line endings.

    This is a regression test for a real CI failure (2026-09-19): the gate
    derived the "17 bytes" control-arm claim from os.path.getsize(), which
    reads 17 in a CRLF worktree and 16 on a Linux runner for the same commit,
    because .gitattributes normalises the capture to LF. Both spellings below
    must produce the same answer.
    """
    crlf = tmp_path / "crlf.txt"
    crlf.write_bytes(b"FOUND GICv3 ITS\r\n")
    lf = tmp_path / "lf.txt"
    lf.write_bytes(b"FOUND GICv3 ITS\n")

    assert C.serial_bytes_on_the_wire(str(crlf)) == 17
    assert C.serial_bytes_on_the_wire(str(lf)) == 17
    # The naive measure is exactly the trap this replaced.
    assert C.file_size(str(crlf)) != C.file_size(str(lf))


def test_serial_bytes_multi_line_capture(tmp_path):
    p = tmp_path / "m.txt"
    p.write_bytes(b"one\ntwo\n")
    # 3 + 2 + 3 + 2 = 10 on the wire, whatever the checkout produced.
    assert C.serial_bytes_on_the_wire(str(p)) == 10


def test_sentinel_counts(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("sentinel_recoveries=3 sentinel_bounces=0\n", encoding="utf-8")
    assert C.sentinel_counts(str(p)) == (3, 0)


def test_read_is_utf8_regardless_of_platform_default(tmp_path):
    """The status table carries emoji; a cp950/cp1252 default would break here
    on the owner's Windows box while passing in CI -- the worst failure shape."""
    p = tmp_path / "u.txt"
    p.write_bytes("✅ done \U0001f7e1 in progress\n".encode("utf-8"))
    assert "✅" in C._read(str(p))
