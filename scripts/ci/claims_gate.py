#!/usr/bin/env python3
"""claims_gate.py -- re-derive every number README.md quotes, from committed data.

    usage: python scripts/ci/claims_gate.py [--readme README.md] [--repo .]

Exit 0 if every claim reproduces, 1 otherwise. Always prints a claimed-vs-
recomputed table so a human can read the check, not just its exit code.

WHAT THIS GATE IS FOR. This repo's central rule is "never write 'it works'
without a log, a number, or a diff". The risk it does not address is a number
that was true when written and drifted afterwards -- a figure edited in prose,
a data file appended to, a claim carried forward past the run it came from.
Two published numbers in this repo were already found wrong that way. This gate
makes that class of error fail the build.

THREE KINDS OF FAILURE, all hard:
  1. VALUE    -- README's figure does not match the recomputation, at README's
                 own stated precision.
  2. UNIT     -- README's unit does not match the unit of the source data.
                 "33 ms" against a source in seconds is wrong even if the digits
                 agree. This is a failure, never a warning.
  3. DENYLIST -- an ASSERTED claim string the data does not support.

WHAT IT CANNOT DO is documented in the epilogue it prints, and in the PR. In
particular, roughly four-fifths of this project's run records are not committed
at all (licensed evaluation output, .gitignore lines 58-63), so the headline
milestone claims have nothing to re-derive from and are reported as UNBACKED
rather than silently passed.
"""
import argparse
import os
import re
import subprocess
import sys
from re import error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claims_lib as C  # noqa: E402

LOGS = "logs/sample-boot"
DELTA_AWK = os.path.join("scripts", "twin", "delta.awk")


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
    "33 s" over data measured in ms is wrong even though the digits match.
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
        """(value, unit_as_written) straight out of README.md."""
        m = self.anchor.search(readme_text)
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


def _ipc_delta_via_shared_awk(repo, cloud_csv, hw_csv):
    """Re-derive the IPC deltas through scripts/twin/delta.awk.

    Deliberately NOT a second implementation of the formula. The shared
    measurement toolchain owns it; CI calls the same file. If someone edits the
    formula, both the published report and this gate move together.
    """
    cloud = C.last_row(C.parse_ipc_csv(os.path.join(repo, cloud_csv)))
    hw = C.last_row(C.parse_ipc_csv(os.path.join(repo, hw_csv)))
    out = subprocess.check_output(
        [
            "awk",
            "-v", "cp50=%d" % cloud["p50_ns"], "-v", "hp50=%d" % hw["p50_ns"],
            "-v", "cp99=%d" % cloud["p99_ns"], "-v", "hp99=%d" % hw["p99_ns"],
            "-v", "cmax=%d" % cloud["max_ns"], "-v", "hmax=%d" % hw["max_ns"],
            "-v", "MODE=csv",
            "-f", os.path.join(repo, DELTA_AWK),
        ],
        stdin=subprocess.DEVNULL,
    ).decode("utf-8")
    pct = {}
    for line in out.strip().splitlines():
        label, _c, _h, _d, p = line.split(",")
        pct[label] = float(p)
    return pct, cloud, hw


def build_claims(repo):
    """The claims that CAN be re-derived from committed data."""

    def boot(rel):
        return C.parse_boot_times(os.path.join(repo, LOGS, rel))

    # --- A2 plain-IFS boot, Windows vs Orin -------------------------------
    def a2_median_delta():
        w, wu = boot("windows-tcg-qnx-boot-times-n5.txt")
        o, ou = boot("orin-tcg-qnx-boot-times-n5.txt")
        assert wu == ou, "unit mismatch between the two A2 series"
        return C.pct_delta(C.median(w), C.median(o)), wu

    def a2_mean_vs_median_pp():
        w, wu = boot("windows-tcg-qnx-boot-times-n5.txt")
        o, _ = boot("orin-tcg-qnx-boot-times-n5.txt")
        med = C.pct_delta(C.median(w), C.median(o))
        avg = C.pct_delta(C.mean(w), C.mean(o))
        return abs(med - avg), wu

    def a2_windows_span_without_outlier():
        w, wu = boot("windows-tcg-qnx-boot-times-n5.txt")
        rest = sorted(w)[:-1]  # drop the single cold-start outlier
        return C.span(rest), wu

    # --- A3 QHV leg, release-aligned pair only -----------------------------
    # Six of the eight boot-times files are superseded; pairing them naively
    # produces a wrong ratio. These two filenames are pinned on purpose.
    def a3_ratio():
        w, wu = boot("windows-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt")
        o, ou = boot("orin-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt")
        assert wu == ou, "unit mismatch between the two A3 series"
        return C.ratio(C.median(w), C.median(o)), wu

    def a3_same_host_control():
        ctl, cu = boot("windows-qhv-tcg-rng-snapshot-segments-boot-times-n5.txt")
        q111, qu = boot("windows-qhv-tcg-q111-rng-snapshot-segments-boot-times-n5.txt")
        assert cu == qu
        return C.pct_delta(C.median(ctl), C.median(q111)), cu

    # --- IPC, through the shared awk --------------------------------------
    def ipc(label):
        def f():
            pct, _c, _h = _ipc_delta_via_shared_awk(
                repo, "results/cloud/cloud-ipc-latest.csv", "results/hw/orin-ipc-latest.csv"
            )
            return pct[label], "ns"
        return f

    def ipc_samples_per_side():
        cloud = C.last_row(C.parse_ipc_csv(os.path.join(repo, "results/cloud/cloud-ipc-latest.csv")))
        hw = C.last_row(C.parse_ipc_csv(os.path.join(repo, "results/hw/orin-ipc-latest.csv")))
        assert cloud["samples"] == hw["samples"], "the compared rows are not the same size"
        return cloud["samples"], "samples"

    def hw_100k_runs():
        rows = C.parse_ipc_csv(os.path.join(repo, "results/hw/orin-ipc-latest.csv"))
        return C.count_rows_with_samples(rows, 100000), "runs"

    # --- KVM control/test serial byte counts ------------------------------
    def control_bytes():
        # Counted on the wire (CRLF), NOT os.path.getsize: git normalises this
        # capture's line endings on checkout, so a file size answers 17 on
        # Windows and 16 on Linux for the same commit. See claims_lib.
        return C.serial_bytes_on_the_wire(
            os.path.join(repo, LOGS, "orin-kvm-nisv-control-shipped-startup.log")
        ), "bytes"

    def fix_bytes():
        markers = C.serial_byte_markers(os.path.join(repo, LOGS, "aws-a1-metal-kvm-fix-crossvendor.log"))
        assert len(markers) == 2, "expected one control and one fix marker, got %r" % markers
        return markers[1], "bytes"

    def control_bytes_marker():
        markers = C.serial_byte_markers(os.path.join(repo, LOGS, "aws-a1-metal-kvm-fix-crossvendor.log"))
        return markers[0], "bytes"

    # --- sentinel recovery ------------------------------------------------
    def sentinel_recoveries():
        total_rec, total_bounce = 0, 0
        for rel in (
            "qhv-tcg-sentinel-recovery-diag300-run1.log",
            "qhv-tcg-sentinel-recovery-diag300-run2.log",
            "qhv-tcg-sentinel-recovery-diag300-run3.log",
            "qhv-tcg-rq2-shmem-roundtrip-success.log",
        ):
            rec, bounce = C.sentinel_counts(os.path.join(repo, LOGS, rel))
            total_rec += rec
            total_bounce += bounce
        assert total_bounce == 0, "sentinel_bounces should be 0, got %d" % total_bounce
        return total_rec, "stalls"

    # Each anchor is matched against README.md verbatim. group(1) is the number;
    # a named (?P<unit>...) group, where README writes a unit, is compared with
    # expect_unit so that changing "33 ms" to "33 s" is a hard failure.
    return [
        Claim("C11", "A2 boot, Orin vs Windows, median",
              r"Orin \*\*\+([0-9.]+)(?P<unit>%)\*\* median", 1, "%", "ms",
              ["windows-tcg-qnx-boot-times-n5.txt", "orin-tcg-qnx-boot-times-n5.txt"], a2_median_delta),
        Claim("C11b", "A2 mean delta agrees with median to",
              r"mean delta agrees to ([0-9.]+)\s*(?P<unit>pp)", 1, "pp", "ms",
              ["windows-tcg-qnx-boot-times-n5.txt", "orin-tcg-qnx-boot-times-n5.txt"], a2_mean_vs_median_pp),
        Claim("C12", "A2 Windows span, cold-start outlier dropped",
              r"other four runs span ([0-9]+)\s*(?P<unit>ms|s|us|ns)\b", 0, "ms", "ms",
              ["windows-tcg-qnx-boot-times-n5.txt"], a2_windows_span_without_outlier),
        Claim("C16", "A3 QHV leg, Orin / Windows median ratio",
              r"Orin \*\*([0-9.]+)(?P<unit>×)\*\* slower", 2, "×", "ms",
              ["windows-qhv-tcg-q111-...-n5.txt", "orin-qhv-tcg-q111-...-n5.txt"], a3_ratio),
        Claim("C17", "A3 same-host control bounds build component at",
              r"bounds the build component at \+([0-9.]+)(?P<unit>%)", 1, "%", "ms",
              ["windows-qhv-tcg-rng-snapshot-segments-...", "windows-qhv-tcg-q111-..."], a3_same_host_control),
        Claim("C13a", "IPC P50, cloud -> hw",
              r"P50 \+([0-9.]+)(?P<unit>%), P99", 1, "%", "ns",
              ["results/cloud/cloud-ipc-latest.csv", "results/hw/orin-ipc-latest.csv"], ipc("P50"),
              note="via scripts/twin/delta.awk"),
        Claim("C13b", "IPC P99, cloud -> hw",
              r"P99 \+([0-9.]+)(?P<unit>%)", 1, "%", "ns",
              ["results/cloud/cloud-ipc-latest.csv", "results/hw/orin-ipc-latest.csv"], ipc("P99"),
              note="via scripts/twin/delta.awk"),
        Claim("C13c", "IPC samples per side (the compared row)",
              r"IPC round-trip\*\*, n=([0-9]+)/(?P<unit>side)", 0, "side", "samples",
              ["results/cloud/cloud-ipc-latest.csv", "results/hw/orin-ipc-latest.csv"], ipc_samples_per_side),
        Claim("C7", "hw leg 100,000-iteration runs",
              r"HW leg: ([0-9]+) × 100,000 (?P<unit>iterations)", 0, "iterations", "runs",
              ["results/hw/orin-ipc-latest.csv"], hw_100k_runs),
        Claim("C8", "KVM control arm, shipped startup, serial bytes",
              r"shipped startup, ([0-9,]+) (?P<unit>bytes)", 0, "bytes", "bytes",
              ["orin-kvm-nisv-control-shipped-startup.log"], control_bytes),
        Claim("C8b", "a1.metal control arm marker, serial bytes",
              r"shipped startup, ([0-9,]+) (?P<unit>bytes)", 0, "bytes", "bytes",
              ["aws-a1-metal-kvm-fix-crossvendor.log"], control_bytes_marker),
        Claim("C9", "a1.metal fix arm, rebuilt startup, serial bytes",
              r"rebuilt startup, ([0-9,]+) (?P<unit>bytes)", 0, "bytes", "bytes",
              ["aws-a1-metal-kvm-fix-crossvendor.log"], fix_bytes),
        Claim("C20", "sentinel recoveries, zero bounces",
              r"recovered ([0-9]+)/19 real (?P<unit>stalls)", 0, "stalls", "stalls",
              ["qhv-tcg-sentinel-recovery-diag300-run{1,2,3}.log", "qhv-tcg-rq2-shmem-roundtrip-success.log"],
              sentinel_recoveries),
    ]


# Claims that are real but have NO committed backing, because the run records
# are licensed evaluation output excluded by .gitignore lines 58-63. Listed so
# the gate reports them rather than leaving a reader to assume they were checked.
UNBACKED = [
    ("ten-minute Linux-guest hold (S1-F/B4)", "results/orin-native-port/*/s1/ is gitignored"),
    ("two-guest rung B5 ran and passed", "results/orin-native-port/*/s1/ is gitignored"),
    ("M5-F UEFI cold boot, one attended session", "results/orin-native-port/*/m5/ is gitignored"),
    ("M4-F two runs under frozen instruments", "results/orin-native-port/*/m4/ is gitignored"),
    ("M3 native qvm boots the cloud-leg guest", "results/orin-native-port/*/m3/ is gitignored"),
    ("~50 GB free disk prerequisite", "environment prerequisite, no artefact"),
    ("3.3 V USB-TTL on J14", "hardware prerequisite, no artefact"),
    ("cloud-leg stall rate, now quoted as 0.98-2.62%",
     "derivable but not anchored: 3/8/7 recoveries in 305 attempts across three diag300 logs"),
    ("100k runs: no mismatch or I/O error reported",
     "the CSV schema carries no error field; the evidence is one sentence in "
     "orin-tcg-qnx-ipc-client1.log plus sentinel_bounces=0, and that single capture backs both 100k rows"),
]


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

    failures = []

    print("=" * 100)
    print("CLAIMS GATE -- every figure below is recomputed from committed data in this repo")
    print("=" * 100)
    print()
    print("%-6s %-44s %10s %12s %-11s %s" % ("id", "claim", "README", "recomputed", "unit", "verdict"))
    print("-" * 100)

    unit_rows = []
    derived = []
    for claim in build_claims(repo):
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
        # Every value this gate successfully re-derived, with its unit. The
        # repository description is checked against this set: a number there is
        # a claim, exactly as in README, and must come from committed data.
        derived.append((round(recomputed, claim.decimals), claim.expect_unit))

    # --- unit summary ------------------------------------------------------
    print()
    print("-" * 100)
    print("UNIT CHECK -- the unit README writes vs the unit the data is measured in")
    print("-" * 100)
    for cid, readme_unit, source_unit, ok in unit_rows:
        print("  %-6s README writes %-11s source measured in %-9s %s"
              % (cid, readme_unit, source_unit, "ok" if ok else "FAIL"))

    # --- denylist ----------------------------------------------------------
    print()
    print("-" * 100)
    print("DENYLIST -- asserted claim strings the data does not support")
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
    print("PROSE BEYOND README -- scripts/ is instructions (hard fail); docs/ and results/ warn")
    print("-" * 100)
    # gitignored, local-only: CI never sees them, so a local run must not either
    skip = ("interview-narrative.md", "cv-architecture-brief.md")
    for label, globs, hard in (
            ("scripts/", ["scripts/**/*.sh", "scripts/**/*.bat",
                          "scripts/**/*.ps1", "scripts/**/*.md"], True),
            ("docs/", ["docs/*.md"], False),
            # results/ was the last unscanned prose surface. A run record that
            # misstates what was measured is as misleading as a doc that does,
            # and results/cloud/ is the standing example: a directory named
            # "cloud" whose one CSV was recorded on a Windows PC. Warn, not
            # fail -- these are dated records, and correcting one is an edit to
            # history that wants a human deciding it.
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
    # substring scan. A substring deny on "Graviton" would fail the current,
    # correct description, whose Graviton clause is the project's cross-vendor
    # defect evidence ("the one QNX ships hangs under KVM ... on AWS Graviton
    # alike"). The distinction between that and a Graviton *leg* is the whole
    # point, and only a classifier can express it.
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
    print("RESULT: PASS -- every re-derivable README figure matches the committed data")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
