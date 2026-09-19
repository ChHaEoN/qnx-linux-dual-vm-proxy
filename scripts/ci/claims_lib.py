#!/usr/bin/env python3
"""claims_lib.py -- pure helpers for re-deriving README numbers from raw data.

Every function here is deliberately free of I/O side effects beyond reading a
path that is handed to it, so the unit tests in tests/ can exercise the real
logic against small fixtures instead of the committed corpus.

UNITS ARE NOT UNIFORM IN THIS REPO and that is the whole point of the gate:

    results/{cloud,hw}/*.csv          p50_ns / p99_ns / max_ns   NANOSECONDS
    logs/sample-boot/*-boot-times-*   "run N: 12345 ms"          MILLISECONDS
    results/.../lat-*.json            p50_ms etc.                MILLISECONDS
    monitor console "us="                                        MICROSECONDS

A claim that quotes "33 ms" against a source measured in seconds is wrong even
if the digits match, so unit identity is checked separately from value equality.

One trap encoded here on purpose: `cycles_per_sec` in the IPC CSVs is a
hardcoded 1000000000 placeholder on the hw leg (its own notes field says
"clock_gettime-ns-not-cycles"). It is NEVER a cycles->time conversion factor.
"""
import io
import os
import re

# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------


def median(values):
    """Median of a non-empty sequence of numbers.

    Even-length input averages the two middle values, which is why this is not
    simply `sorted(v)[len(v) // 2]`.
    """
    if not values:
        raise ValueError("median of empty sequence")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def mean(values):
    if not values:
        raise ValueError("mean of empty sequence")
    return float(sum(values)) / len(values)


def pct_delta(base, other):
    """Percentage change from base to other, the formula in scripts/twin/delta.awk.

    Returns 0.0 for a zero base, matching that file rather than raising, so the
    two implementations cannot disagree on the edge case.
    """
    base = float(base)
    if base == 0:
        return 0.0
    return (float(other) - base) / base * 100.0


def ratio(base, other):
    """other / base -- the "2.15x slower" shape."""
    base = float(base)
    if base == 0:
        raise ZeroDivisionError("ratio against a zero base")
    return float(other) / base


def span(values):
    """max - min. Used for the "span 33 ms" claim."""
    if not values:
        raise ValueError("span of empty sequence")
    return max(values) - min(values)


def close_enough(claimed, recomputed, decimals):
    """Does `recomputed`, rounded to the precision README quotes, equal `claimed`?

    README quotes "+24.9%", not "+24.9012%". Demanding exact equality would fail
    on every correctly rounded figure, so the comparison is made at the claim's
    own stated precision. round() here is Python's banker's rounding; for the
    one-decimal comparisons in use that is not a practical difference, and the
    test suite pins the behaviour either way.
    """
    return round(float(recomputed), decimals) == round(float(claimed), decimals)


# --------------------------------------------------------------------------
# parsers
# --------------------------------------------------------------------------

_RUN_RE = re.compile(r"^run\s+(\d+):\s*(\d+)\s*(ms|s|us|ns)\b", re.M)


def parse_boot_times(path):
    """Parse a logs/sample-boot/*-boot-times-n5.txt series.

    Returns (values, unit). Comment lines beginning '#' are skipped, which
    matters because those headers quote *other* runs' medians in prose and a
    naive number-grab would pick them up as data.
    """
    text = _read(path)
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    matches = _RUN_RE.findall(body)
    if not matches:
        raise ValueError("no 'run N: <value> <unit>' lines in %s" % path)
    units = {u for _, _, u in matches}
    if len(units) != 1:
        raise ValueError("mixed units %s in %s" % (sorted(units), path))
    values = [int(v) for _, v, _ in matches]
    return values, units.pop()


IPC_FIELDS = (
    "unix_ts",
    "samples",
    "payload_bytes",
    "p50_ns",
    "p99_ns",
    "max_ns",
    "cycles_per_sec",
    "notes",
)
IPC_HEADER = ",".join(IPC_FIELDS)


def parse_ipc_csv(path):
    """Parse an IPC results CSV into a list of dicts.

    Handles the structural asymmetry between the two committed files: the cloud
    CSV carries a header row, the hw CSV does not (its header lives in a sibling
    header.csv). A header row is detected and dropped rather than assumed.
    """
    rows = []
    for line in _read(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line == IPC_HEADER:
            continue
        parts = line.split(",", len(IPC_FIELDS) - 1)
        if len(parts) != len(IPC_FIELDS):
            raise ValueError("malformed row in %s: %r" % (path, line[:80]))
        row = dict(zip(IPC_FIELDS, parts))
        for k in ("unix_ts", "samples", "payload_bytes", "p50_ns", "p99_ns", "max_ns", "cycles_per_sec"):
            row[k] = int(row[k])
        rows.append(row)
    if not rows:
        raise ValueError("no data rows in %s" % path)
    return rows


def last_row(rows):
    """The row scripts/twin/diff-results.sh compares: the last one.

    Kept as a named function because "which row" is a real decision -- the hw
    CSV holds two 100,000-sample rows and one 15-sample row, and picking a
    different one changes the published delta.
    """
    return rows[-1]


def count_rows_with_samples(rows, samples):
    return sum(1 for r in rows if r["samples"] == samples)


_MARKER_RE = re.compile(r"^###\s*serial bytes:\s*(\d+)\s*$", re.M)


def serial_byte_markers(path):
    """Every '### serial bytes: N' marker in a capture, in order."""
    return [int(m) for m in _MARKER_RE.findall(_read(path))]


_RECOVERY_RE = re.compile(r"sentinel_recoveries=(\d+)")
_BOUNCE_RE = re.compile(r"sentinel_bounces=(\d+)")


def sentinel_counts(path):
    """(recoveries, bounces) summed over a capture."""
    text = _read(path)
    rec = sum(int(v) for v in _RECOVERY_RE.findall(text))
    bounce = sum(int(v) for v in _BOUNCE_RE.findall(text))
    return rec, bounce


def file_size(path):
    return os.path.getsize(path)


# --------------------------------------------------------------------------
# claim-text analysis
# --------------------------------------------------------------------------

# Negation or strike-through: the sentence denies the claim rather than making it.
NEGATION_RE = re.compile(
    r"\b(no|not|none|never|nothing|without|neither|nor|cannot|can't|lacks?)\b"
    r"|~~|≠|non-metal|non-commercial",
    re.I,
)
# Explicitly marked as planned / intended / not built.
PLANNED_RE = re.compile(
    r"\b(planned|design intent|intended|never built|not built|would have|aspiration|"
    r"stretch|not run|design called for|superseded)\b",
    re.I,
)

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(markdown_text):
    """Reflow markdown to sentences.

    LINE-BASED MATCHING IS WRONG HERE and this function exists to prevent it.
    README wraps prose, so "Not a reproduction of DRIVE OS, and not a" ends one
    line and "certified hypervisor." begins the next. A line-based denylist
    flags that second line as an asserted certification claim -- failing the
    build for one of the most honest sentences in the document. Collapsing
    whitespace first puts the negation and the keyword in the same span.
    """
    flat = re.sub(r"\s+", " ", markdown_text)
    return [s.strip() for s in _SENT_SPLIT_RE.split(flat) if s.strip()]


def classify_sentence(sentence):
    """'negated' | 'planned' | 'asserted' -- only 'asserted' is a gate failure."""
    if NEGATION_RE.search(sentence):
        return "negated"
    if PLANNED_RE.search(sentence):
        return "planned"
    return "asserted"


def load_denylist(path):
    """Read the plain-text denylist.

    Format, one rule per line:   <regex><TAB or 2+ spaces><why it is banned>
    '#' comments and blank lines are ignored, so the file can be extended by
    anyone without touching Python.
    """
    rules = []
    for raw in _read(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"\t|\s{2,}", line, maxsplit=1)
        pattern = parts[0].strip()
        why = parts[1].strip() if len(parts) > 1 else ""
        rules.append((pattern, why))
    return rules


def scan_denylist(markdown_text, rules):
    """Return [(pattern, why, sentence)] for ASSERTED matches only.

    A mention inside a denial or a planned-marking is not a violation; this repo
    documents what it does NOT demonstrate, and that prose must stay legal.
    """
    hits = []
    for sentence in split_sentences(markdown_text):
        for pattern, why in rules:
            if re.search(pattern, sentence, re.I) and classify_sentence(sentence) == "asserted":
                hits.append((pattern, why, sentence))
    return hits


# --------------------------------------------------------------------------


def _read(path):
    """UTF-8 always.

    The status table uses emoji; on a cp950/cp1252 console the default encoding
    raises UnicodeDecodeError or mangles them. CI runs UTF-8, so a default-
    encoding bug here would pass in Actions and fail only on the owner's Windows
    machine -- the worst failure shape available.
    """
    with io.open(path, "r", encoding="utf-8") as fh:
        return fh.read()
