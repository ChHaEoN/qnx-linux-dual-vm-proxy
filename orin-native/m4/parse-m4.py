#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""parse-m4.py: the PC side of M4 (Phase 3b).

Implements results/orin-native-port/20260909T1100Z/m4-design.md (revision 2):
§6.2-6.5 (run, the block checks, the CSV writer, the series), §2.4 (size-r1,
size-r2), §3.4 step 9 (kshcheck), §4.5.9 (selftest) and §11 (the rehearsal's
parse), with the implementation notes of that file's §14. Standard library only.

  parse-m4.py run --params P --blackbox FILE|none --com3 FILE --run-id ID --out-dir DIR
                  [--csv FILE] [--com3-format capture|qemu-serial] [--rehearsal]
                  [--reset-reason TEXT] [--fixtures DIR]
                  [--blackbox-board-sha256 HEX|none] [--run-end-epoch SECONDS]
  parse-m4.py size-r1 --r0-parse LOG [--out FILE]
  parse-m4.py size-r2 --r1-parse LOG --r0-parse LOG [--out FILE] [--accept-low-n]
  parse-m4.py series --parse-logs L1 L2 L3 L4 L5 --csv FILE --cloud-csv FILE --out-dir DIR
  parse-m4.py selftest --fixtures DIR [--m4c FILE] --out-dir DIR
  parse-m4.py regress-7b --listing FILE --out-dir DIR
  parse-m4.py kshcheck FILE | --selftest
  parse-m4.py synth-com3 --listing FILE --rung r0|r1 --out-dir DIR [--profile tcg|board] [...]   (test input, §14)

Output rules (§6.2). Every file written must satisfy git check-ignore -q (a
read-only query) and must not lie under results/hw/ or results/cloud/; anything
else is refused with exit 2. Results are M4PC key=value lines headed by the
sha256 of this parser and of each input; user names become <user>. kshcheck
writes no file.

The listing analysis (class Listing) is written from the design's §4.5 text, not
from tools/m4count.c, so the two implementations can catch each other's defects
(risk M29). Every figure it prints from a board run is evaluation output under
NC QDL v7 4.6(i): the orchestrator, not this tool, moves any of it to a branch.

Exit: 0 done (run: whatever the verdict); 1 an input error or a failed step;
2 a refused output path or a usage error; 3 a sizing rule that goes to the owner
(size-r1, size-r2).
"""

import argparse
import bisect
import contextlib
import hashlib
import importlib.util
import io
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

M64 = 1 << 64
LONG_LINE = 1023            # fgets(1024): a line of 1023 or more bytes before its newline is long
MAX_CPUS = 8
HIST_SLOTS = 16384
HIST_PRINT = 48
QOTHER_KEEP = 64
QOTHER_PRINT = 8
SAMPLE_MAX = 12
SAMPLE_CHARS = 160
OFFSETS_KEEP = 64
STATUS_KEEP = 64            # m4-design.md 14.7: distinct GUEST_EXIT status values kept
STATUS_PRINT = 16           # ... and printed as STATUS lines, first-seen order
SEQ_KEEP = 4096
QUOTABLE_N = 10000
DEFAULT_CPS = 31250000
BOARD_CPS = 31250000
NS_PER_S = 10 ** 9
MIB = 1 << 20
FLT_MARK = "=M4FLT="
BB_GATE = 60000
CNT_MB = 270
RUNNING, READY, OTHER = 0, 1, 2
CLASSES = ("clean", "pre", "blk", "mig")
STAT_CLASSES = ("clean", "pre", "blk", "mig", "nonblk")
REASONS = ("eligible", "broken_between", "order_violated", "status_nonzero", "negative",
           "out_of_window", "not_held", "untimed", "capped")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))


class Refused(Exception):
    pass


class InputError(Exception):
    pass


# ------------------------------------------------------------------ small helpers

def _user_names():
    names = set()
    for v in (os.environ.get("USERNAME"), os.environ.get("USER")):
        if v:
            names.add(v)
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    if home:
        leaf = os.path.basename(home.rstrip("\\/"))
        if leaf:
            names.add(leaf)
    return sorted((n for n in names if len(n) >= 3), key=len, reverse=True)


USER_NAMES = _user_names()


def redact(s):
    for n in USER_NAMES:
        s = re.sub(re.escape(n), "<user>", s, flags=re.IGNORECASE)
    return s


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_repo(path):
    try:
        return os.path.relpath(os.path.abspath(path), REPO).replace("\\", "/")
    except ValueError:
        return os.path.abspath(path).replace("\\", "/")


def check_out_path(path):
    """§6.2 output rule: git-ignored, and never under results/hw or results/cloud."""
    rel = rel_repo(path)
    low = rel.lower()
    for bad in ("results/hw", "results/cloud"):
        if low == bad or low.startswith(bad + "/"):
            raise Refused(f"{rel} lies under {bad}")
    try:
        cp = subprocess.run(["git", "-C", REPO, "check-ignore", "-q", "--", os.path.abspath(path)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused(f"git check-ignore could not run for {rel}: {e}")
    if cp.returncode != 0:
        raise Refused(f"{rel} is not git-ignored (git check-ignore exit {cp.returncode})")


def write_bytes(path, data):
    check_out_path(path)
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def write_text(path, text):
    write_bytes(path, text.encode("utf-8"))


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise InputError(f"cannot read {path}: {e}")


def to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def hexs(v):
    return "-" if v is None else "0x%x" % v


def _crc_table():
    table = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) if (c & 0x80000000) else (c << 1)
        table.append(c & 0xFFFFFFFF)
    return table


CRC_TABLE = _crc_table()


def posix_cksum(data):
    """POSIX cksum: CRC-32 (0x04C11DB7, MSB first) with the length appended, inverted."""
    crc = 0
    tab = CRC_TABLE
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ tab[((crc >> 24) ^ b) & 0xFF]
    n = len(data)
    while n:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ tab[((crc >> 24) ^ (n & 0xFF)) & 0xFF]
        n >>= 8
    return (~crc) & 0xFFFFFFFF, len(data)


def iter_raw_lines(data):
    """Lines of a byte string, each with its b'\\n' when present (fgets does the same)."""
    pos = 0
    n = len(data)
    while pos < n:
        nl = data.find(b"\n", pos)
        if nl < 0:
            yield data[pos:]
            return
        yield data[pos:nl + 1]
        pos = nl + 1


def split_lines(data, start=0, end=None):
    """(offset, text) per line of data[start:end], decoded latin-1, every CR removed."""
    if end is None:
        end = len(data)
    out = []
    pos = start
    while pos < end:
        nl = data.find(b"\n", pos, end)
        stop = end if nl < 0 else nl
        out.append((pos, data[pos:stop].decode("latin-1").replace("\r", "")))
        pos = end if nl < 0 else nl + 1
    return out


TOKEN_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("([^"]*)"|\'([^\']*)\'|\S*)|(\S+)')


def parse_kv(text):
    """key=value tokens (a value may be "quoted" or 'quoted') and bare tokens.

    I30 (m4-design.md 14.9 item 3): only the double-quoted form was read, but
    the board writes single quotes - `M4 CONFIG startup='…' tl_args='…'
    forms='…'` and `M4 TRACE ARM args='…'`. Those values were being cut at
    their first space, with the opening quote kept, so `forms='v c'` read as
    `'v`. Nothing consumed them, which is why no gate saw it; crit_1 compares
    them against the params file now, so they have to be the value.
    """
    d = {}
    bare = []
    for m in TOKEN_RE.finditer(text):
        if m.group(1) is not None:
            quoted = m.group(3) if m.group(3) is not None else m.group(4)
            d.setdefault(m.group(1), quoted if quoted is not None else m.group(2))
        else:
            bare.append(m.group(5))
    return d, bare


def parse_m4c(text):
    """'M4C REC w=.. k=v ..' -> (REC, fields, bare tokens), or None."""
    if not text.startswith("M4C "):
        return None
    rest = text[4:]
    name, _, tail = rest.partition(" ")
    if not name:
        return None
    d, bare = parse_kv(tail)
    return name, d, bare


def composite(pairs):
    return ",".join(f"{k}:{v}" for k, v in pairs)


def parse_composite(value):
    out = {}
    for part in (value or "").split(","):
        k, sep, v = part.partition(":")
        if sep:
            out[k] = v
    return out


def sample_text(line):
    """A SAMPLE's text, as m4count.c's sample_copy: up to the line end or SAMPLE_CHARS, " as '."""
    out = []
    for ch in line:
        if ch in "\n\r\0" or len(out) >= SAMPLE_CHARS:
            break
        out.append("'" if ch == '"' else ch)
    return "".join(out)


class Log:
    def __init__(self):
        self.lines = []

    def __call__(self, key, value):
        self.lines.append(redact(f"M4PC {key}={value}"))

    def text(self):
        return "\n".join(self.lines) + "\n"


# ------------------------------------------------------------------ kshcheck (§3.4 step 9)

KSH_WORD_RE = re.compile(r"\b(waitfor|eval)\b")
KSH_NEST_RE = re.compile(r"\b(ksh|sh)\s+-c\b")
KSH_WORD_START = set(" \t;&|(){}")


def kshcheck_text(text):
    """Violations as (line, rule): 1 a pipe, 2 a substitution, 3 a nested shell or foreign text.

    The file is read as ksh quotes it: '...' single-quoted; "..." double-quoted
    with a backslash escaping the next character; elsewhere a backslash escapes
    one character; a # that starts a word begins a comment; quote state carries
    across lines. Every || is removed before the pipe test.
    """
    out = set()
    masked = []
    state = "normal"
    line = 1
    buf = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "\n":
            masked.append((line, "".join(buf)))
            buf = []
            line += 1
            if state == "comment":
                state = "normal"
            i += 1
            continue
        if state == "comment":
            i += 1
            continue
        if state == "single":
            buf.append("'" if ch == "'" else " ")
            if ch == "'":
                state = "normal"
            i += 1
            continue
        if state == "double":
            if ch == "\\":
                if nxt == "\n":
                    i += 1
                    continue
                buf.append("  ")
                i += 2
                continue
            if ch == "$" and nxt == "(":
                out.add((line, 2))
            if ch == "`":
                out.add((line, 2))
            buf.append('"' if ch == '"' else " ")
            if ch == '"':
                state = "normal"
            i += 1
            continue
        if ch == "'":
            state = "single"
            buf.append("'")
            i += 1
            continue
        if ch == '"':
            state = "double"
            buf.append('"')
            i += 1
            continue
        if ch == "\\":
            if nxt == "\n":
                i += 1
                continue
            buf.append("  ")
            i += 2
            continue
        prev = text[i - 1] if i > 0 else "\n"
        if ch == "#" and (prev == "\n" or prev in KSH_WORD_START):
            state = "comment"
            i += 1
            continue
        if ch == "$" and nxt == "(":
            out.add((line, 2))
        if ch == "`":
            out.add((line, 2))
        if ch == "<" and nxt == "<":
            out.add((line, 3))
        if ch == "|":
            if nxt == "|":
                buf.append("  ")
                i += 2
                continue
            out.add((line, 1))
        buf.append(ch)
        i += 1
    if buf:
        masked.append((line, "".join(buf)))
    for ln, m in masked:
        if KSH_WORD_RE.search(m) or KSH_NEST_RE.search(m):
            out.add((ln, 3))
    return sorted(out)


KSH_ACCEPT = ["a || b", "grep -E 'x|y' f", 'say "p|q"', "f=${l#*FreeMem:}", "x # a | b"]
KSH_REJECT = ["a | b", "a|b", "a |& b", 'case "$v" in a|b) x ;; esac', "x=$(y)", 'say "$(y)"',
              "x=`y`", "waitfor /dev/x 5", "eval x", "ksh -c 'a | b'", "cat <<E"]


def cmd_kshcheck(a):
    if a.selftest:
        ok = True
        for s in KSH_ACCEPT:
            r = kshcheck_text(s + "\n")
            print(f"KSHCHECK selftest accept {'ok' if not r else 'FAIL'} {s!r}")
            ok = ok and not r
        for s in KSH_REJECT:
            r = kshcheck_text(s + "\n")
            print(f"KSHCHECK selftest reject {'ok' if r else 'FAIL'} {s!r}")
            ok = ok and bool(r)
        print(f"KSHCHECK selftest {'ok' if ok else 'fail'}")
        return 0 if ok else 1
    if not a.file:
        print("KSHCHECK usage: kshcheck FILE | --selftest", file=sys.stderr)
        return 2
    try:
        text = read_bytes(a.file).decode("latin-1")
    except InputError as e:
        print(f"KSHCHECK error {e}", file=sys.stderr)
        return 1
    v = kshcheck_text(text)
    name = rel_repo(a.file)
    for ln, rule in v:
        print(f"KSHCHECK violation file={name} line={ln} rule={rule}")
    if not v:
        print("KSHCHECK ok")
    return 1 if v else 0


# ------------------------------------------------------------------ the listing (§4.5)

EV_HEAD = re.compile(r"t:0x([0-9a-fA-F]{1,16})[ \t]+CPU: *([0-9]{1,3})[ \t]")
HEX16 = re.compile(r"[0-9a-fA-F]{1,16}")
DEC20 = re.compile(r"[0-9]{1,20}")


class Ev:
    __slots__ = ("tval", "tdigits", "cpu", "cls", "sub", "args")


def parse_event(line):
    """§4.5.2: t:0x<hex> CPU:<n> <CLASS>:<SUBTYPE> <arguments>, or None."""
    m = EV_HEAD.match(line)
    if m is None:
        return None
    p = m.end() - 1
    colon = line.find(":", p)
    if colon < 0:
        return None
    cls = line[p:colon].strip(" \t")
    if not cls:
        return None
    se = colon + 1
    n = len(line)
    while se < n and line[se] not in " \t\r\n\0":
        se += 1
    e = Ev()
    e.tval = int(m.group(1), 16)
    e.tdigits = len(m.group(1))
    e.cpu = int(m.group(2))
    e.cls = cls[:31]
    e.sub = line[colon + 1:se][:47]
    e.args = line[se:]
    return e


def arg_u64(args, name):
    nl = len(name)
    i = args.find(name)
    while i >= 0:
        if i > 0 and args[i - 1] in " \t" and args[i + nl:i + nl + 1] == ":":
            q = i + nl + 1
            if args[q:q + 1] == "0" and args[q + 1:q + 2] in ("x", "X"):
                m = HEX16.match(args, q + 2)
                if m:
                    return int(m.group(0), 16)
            else:
                m = DEC20.match(args, q)
                if m:
                    return int(m.group(0)) % M64
        i = args.find(name, i + 1)
    return None


def arg_str(args):
    p = args.find('STR:"')
    if p < 0:
        return None
    q = args.find('"', p + 5)
    if q < 0:
        return None
    return args[p + 5:q]


def decimal_after(args, key):
    p = args.find(key)
    if p < 0:
        return None
    m = DEC20.match(args, p + len(key))
    return int(m.group(0)) % M64 if m else None


def last_decimal(line):
    runs = re.findall(r"[0-9]+", line)
    if not runs:
        return None
    return int(runs[-1][:20]) % M64


class TimeState:
    """§4.5.3, per CPU, in file order."""

    def __init__(self):
        self.msb = [None] * MAX_CPUS
        self.prev_low = [None] * MAX_CPUS
        self.last = [None] * MAX_CPUS
        self.time_events = 0
        self.mismatches = 0
        self.wraps = 0
        self.backsteps = 0
        self.backsteps64 = 0
        self.unknown = 0
        self.n_t64 = 0
        self.n_rebuilt = 0

    def time(self, e):
        c = e.cpu
        is_time = e.cls == "CONTROL" and e.sub == "TIME"
        if is_time:
            msb = arg_u64(e.args, "msb")
            if msb is not None:
                self.msb[c] = msb
                self.time_events += 1
        v = e.tval
        if e.tdigits > 8:
            if self.msb[c] is not None:
                hi = v >> 32
                if hi != self.msb[c] and hi != (self.msb[c] + 1) % M64:
                    self.mismatches += 1
            self.prev_low[c] = v & 0xFFFFFFFF
            t = v
            self.n_t64 += 1
        else:
            low = v & 0xFFFFFFFF
            if not is_time and self.prev_low[c] is not None and low < self.prev_low[c]:
                if self.prev_low[c] - low > 0x80000000:
                    if self.msb[c] is not None:
                        self.msb[c] = (self.msb[c] + 1) % M64
                        self.wraps += 1
                else:
                    self.backsteps += 1
            self.prev_low[c] = low
            if self.msb[c] is None:
                self.unknown += 1
                return None
            t = ((self.msb[c] << 32) | low) % M64
            self.n_rebuilt += 1
        if self.last[c] is not None and t < self.last[c]:
            self.backsteps64 += 1
        self.last[c] = t
        return t

    def mode(self):
        if self.n_t64 + self.n_rebuilt == 0:
            return "none"
        if self.n_rebuilt == 0:
            return "t64"
        if self.n_t64 == 0:
            return "rebuilt"
        return "mixed"


def rank(p, n):
    k = (p * n + 99) // 100
    return min(max(k, 1), n)


def ticks_ns(t, cps):
    return min(t * NS_PER_S // cps, M64 - 1)


class Listing:
    """The design's §4.5 over one traceprinter -n listing, in Python."""

    def __init__(self, start_text, end_text, e3_status0=True, assume_end_t=None):
        self.start_text = start_text
        self.end_text = end_text
        self.e3_status0 = e3_status0
        self.assume_end_t = assume_end_t
        self.lines = 0
        self.bytes = 0
        self.events = 0
        self.unformatted = 0
        # I36 (m4-design.md 14.20), in lockstep with m4count.c: the unformatted
        # lines by kind, and the first one that is neither header nor blank.
        self.unformatted_header = 0
        self.unformatted_blank = 0
        self.unformatted_other = 0
        self.unformatted_sample = None
        self.long_lines = 0
        self.oor = 0
        self.cps = DEFAULT_CPS
        self.cps_header = False
        self.seen_event = False
        self.ts = TimeState()
        self.cpu = [{"events": 0, "first_seq": 0, "last_seq": 0, "prev_seq": 0, "kept": 0, "gaps": 0,
                     "restarts": 0, "max_events": 0, "first_t": None, "last_t": None,
                     "restart_seen": False, "restart_t": None, "wrapped": False,
                     "short_tail": False} for _ in range(MAX_CPUS)]
        self.mk = {"start": None, "end": None}
        self.mk_dup = 0
        self.hist = {}
        self.hist_overflow = 0
        self.q = {"enter": 0, "exit": 0, "cycles": 0, "create_vcpu": 0, "intr_raise": 0, "intr_lower": 0,
                  "timer": 0, "other": 0, "status_nonzero": 0}
        self.qother = {}
        self.samples = []
        self.sampled_running = False
        self.sampled_intr = False
        self.offsets = []
        self.offsets_overflow = False
        # m4-design.md 14.7, in lockstep with m4count.c's status table: every GUEST_EXIT's status.
        self.status = {}
        self.status_missing = 0
        self.status_overflow = 0
        self.exit_status = []
        self.status_win = {}
        self.status_win_other = 0
        self.status_win_missing = 0
        self.thread_ids = {}
        self.thread_list = []
        self.running = [-1] * MAX_CPUS
        self.seqs = {}
        self.triples = []
        self.frags = []
        self.tr_complete = 0
        self.tr_broken = 0
        self.tr_alt = 0
        self.unattributed = 0
        self.th_events = []
        self.intr_events = []
        self.ev_times = [[] for _ in range(MAX_CPUS)]
        self.buf_times = [[] for _ in range(MAX_CPUS)]
        self.anchor_lines = []
        self.pairs = []
        self.window_known = False
        self.start_t = None
        self.end_t = None
        self.ring = "unknown"

    # --- input

    def feed_raw(self, raw):
        self.lines += 1
        self.bytes += len(raw)
        content = len(raw) - (1 if raw.endswith(b"\n") else 0)
        if content >= LONG_LINE:
            self.long_lines += 1
            return
        line = raw.decode("latin-1")
        e = parse_event(line)
        if e is None:
            self.unformatted += 1
            if not self.seen_event:
                self.unformatted_header += 1
            elif line.strip(" \t\r\n") == "":
                self.unformatted_blank += 1
            else:
                self.unformatted_other += 1
                if self.unformatted_sample is None:
                    self.unformatted_sample = sample_text(line)
            if not self.seen_event and "TRACE_CYCLES_PER_SEC" in line:
                v = last_decimal(line)
                if v:
                    self.cps = v
                    self.cps_header = True
            return
        if e.cpu >= MAX_CPUS:
            self.oor += 1
            return
        self.seen_event = True
        self.events += 1
        self._event(e, line, self.lines)

    def feed_bytes(self, data):
        for raw in iter_raw_lines(data):
            self.feed_raw(raw)
        self.finish()
        return self

    def feed_file(self, path):
        with open(path, "rb") as f:
            for raw in f:
                self.feed_raw(raw)
        self.finish()
        return self

    # --- pass 1

    def _thread(self, pid, tid):
        key = (pid, tid)
        th = self.thread_ids.get(key)
        if th is None:
            th = len(self.thread_list)
            self.thread_ids[key] = th
            self.thread_list.append([pid, tid, 0])
        return th

    def _sample(self, sub, line):
        if any(s == sub for s, _ in self.samples) or len(self.samples) >= SAMPLE_MAX:
            return
        self.samples.append((sub, sample_text(line)))

    def _frag(self, th, t):
        self.frags.append((th, t if t is not None else 0))

    def _break(self, s):
        if s["st"] != 0:
            self.tr_broken += 1
            self._frag(s["th"], s["f_t"])
            s["st"] = 0

    def _event(self, e, line, lineno):
        t = self.ts.time(e)
        c = self.cpu[e.cpu]
        key = (e.cls, e.sub)
        if key in self.hist:
            self.hist[key] += 1
        elif len(self.hist) < HIST_SLOTS:
            self.hist[key] = 1
        else:
            self.hist_overflow += 1
        c["events"] += 1
        if t is not None:
            if c["first_t"] is None:
                c["first_t"] = t
            c["last_t"] = t
        self.ev_times[e.cpu].append(t)

        if e.cls == "CONTROL":
            if e.sub == "BUFFER":
                self.buf_times[e.cpu].append(t)
                seq = decimal_after(e.args, "sequence = ")
                if seq is not None:
                    nev = decimal_after(e.args, "num_events = ") or 0
                    if c["kept"] == 0:
                        c["first_seq"] = seq
                        c["last_seq"] = seq
                    elif seq == 1:
                        c["restarts"] += 1
                        if not c["restart_seen"]:
                            c["restart_seen"] = True
                            c["restart_t"] = t
                    elif seq != (c["prev_seq"] + 1) % M64:
                        c["gaps"] += 1
                    if c["kept"] != 0 and not c["restart_seen"]:
                        c["last_seq"] = seq
                    c["prev_seq"] = seq
                    c["kept"] += 1
                    c["max_events"] = max(c["max_events"], nev)
            return

        if e.cls == "USREVENT":
            s = arg_str(e.args)
            if s is not None:
                which = "start" if s == self.start_text else ("end" if s == self.end_text else None)
                if which is not None:
                    if self.mk[which] is not None:
                        self.mk_dup += 1
                    else:
                        self.mk[which] = {"t": t, "cpu": e.cpu, "line": lineno}
            return

        if e.cls == "THREAD" and e.sub.startswith("TH"):
            pid = arg_u64(e.args, "pid")
            tid = arg_u64(e.args, "tid") if pid is not None else None
            th = -1
            if pid is not None and tid is not None:
                th = self._thread(pid & 0xFFFFFFFF, tid & 0xFFFFFFFF)
            if e.sub == "THRUNNING":
                self.running[e.cpu] = th
                if not self.sampled_running:
                    self.sampled_running = True
                    self._sample("THRUNNING", line)
            if th >= 0:
                kind = RUNNING if e.sub == "THRUNNING" else (READY if e.sub == "THREADY" else OTHER)
                self.th_events.append((t, th, e.cpu, kind, lineno))
            return

        if e.cls == "INTERRUPT":
            if not self.sampled_intr and e.sub == "INT_DELIVER":
                self.sampled_intr = True
                self._sample("INT_DELIVER", line)
            self.intr_events.append((t, e.cpu))
            return

        if e.cls != "QVM":
            return
        self._sample(e.sub, line)
        kind = None
        sub = e.sub
        if sub == "GUEST_ENTER":
            self.q["enter"] += 1
            kind = 0
        elif sub == "GUEST_EXIT":
            self.q["exit"] += 1
            st = arg_u64(e.args, "status")
            if st is not None and st != 0:
                self.q["status_nonzero"] += 1
            # 14.7: every GUEST_EXIT, paired or not, in first-seen order (m4count.c status_add).
            if st is None:
                self.status_missing += 1
            elif st in self.status:
                self.status[st] += 1
            elif len(self.status) < STATUS_KEEP:
                self.status[st] = 1
            else:
                self.status_overflow += 1
            self.exit_status.append((t, st))
            off = arg_u64(e.args, "clockcycles_offset")
            if off is not None:
                if off not in self.offsets:
                    if len(self.offsets) < OFFSETS_KEEP:
                        self.offsets.append(off)
                    else:
                        self.offsets_overflow = True
            kind = 1
        elif sub == "CYCLES":
            self.q["cycles"] += 1
            kind = 7
        elif sub == "CREATE_VCPU_THREAD":
            self.q["create_vcpu"] += 1
        elif sub in ("INTR_RAISE", "RAISE_INTR"):
            self.q["intr_raise"] += 1
        elif sub in ("INTR_LOWER", "LOWER_INTR"):
            self.q["intr_lower"] += 1
        elif sub in ("TIMER_CREATE", "CREATE_TIMER", "TIMER_FIRE", "FIRE_TIMER"):
            self.q["timer"] += 1
        else:
            self.q["other"] += 1
            if sub in self.qother:
                self.qother[sub] += 1
            elif len(self.qother) < QOTHER_KEEP:
                self.qother[sub] = 1
        if kind is None:
            return
        th = self.running[e.cpu]
        if th < 0:
            self.unattributed += 1
            return
        skey = (th, e.cpu)
        s = self.seqs.get(skey)
        if s is None:
            if len(self.seqs) >= SEQ_KEEP:
                self.tr_broken += 1
                return
            s = {"st": 0, "th": th, "cpu": e.cpu, "t_enter": None, "f_t": None, "ae": None, "ax": None,
                 "line_enter": 0, "line_cycles": 0}
            self.seqs[skey] = s
        if kind == 0:
            self._break(s)
            s.update(st=1, t_enter=t, f_t=t, line_enter=lineno, ae=None, ax=None)
        elif kind == 7:
            self.thread_list[th][2] += 1
            if s["st"] == 1:
                s.update(st=2, ae=arg_u64(e.args, "at_entry"), ax=arg_u64(e.args, "at_exit"), line_cycles=lineno)
            elif s["st"] == 3:
                self.tr_alt += 1
                self._frag(th, s["f_t"])
                s["st"] = 0
            else:
                self._break(s)
                self.tr_broken += 1
                self._frag(th, t)
        else:
            if s["st"] == 1:
                s["st"] = 3
            elif s["st"] != 2:
                self._break(s)
                self.tr_broken += 1
                self._frag(th, t)
            else:
                st = arg_u64(e.args, "status")
                self.triples.append({
                    "t_enter": s["t_enter"], "t_exit": t, "ae": s["ae"], "ax": s["ax"],
                    "off": arg_u64(e.args, "clockcycles_offset"),
                    "status": (st & 0xFFFFFFFF) if st is not None else None,
                    "hw": arg_u64(e.args, "hw_reason"),
                    "line_enter": s["line_enter"], "line_cycles": s["line_cycles"], "line_exit": lineno,
                    "thread": th, "cpu_enter": s["cpu"], "cpu_exit": s["cpu"], "order_ok": False})
                self.tr_complete += 1
                s["st"] = 0

    # --- between passes, pass 2, pairs

    def finish(self):
        for s in self.seqs.values():
            self._break(s)
        ms, me = self.mk["start"], self.mk["end"]
        start_ok = ms is not None and ms["t"] is not None
        end_ok = me is not None and me["t"] is not None
        if start_ok and not end_ok and self.assume_end_t is not None:
            self.window_known = True
            self.start_t, self.end_t = ms["t"], self.assume_end_t
        elif start_ok and end_ok:
            self.window_known = True
            self.start_t, self.end_t = ms["t"], me["t"]
        self.tr_ok = self.tr_violated = self.tr_in_window = 0
        for x in self.triples:
            ok = all(x[k] is not None for k in ("t_enter", "t_exit", "ae", "ax", "off"))
            if ok:
                he = (x["ae"] - x["off"]) % M64
                hx = (x["ax"] - x["off"]) % M64
                ok = x["t_enter"] <= he <= hx <= x["t_exit"]
            x["order_ok"] = ok
            if ok:
                self.tr_ok += 1
            else:
                self.tr_violated += 1
            if self.window_known and x["t_enter"] is not None and self.start_t <= x["t_enter"] <= self.end_t:
                self.tr_in_window += 1
        self.triples.sort(key=lambda x: (x["thread"], x["t_enter"] if x["t_enter"] is not None else 0,
                                         x["line_enter"]))
        self.frags.sort()

        self.ring = "unknown"
        if self.window_known:
            any_wrapped = False
            clean = True
            for r in self.cpu:
                if r["events"] == 0:
                    continue
                if r["first_t"] is None or r["first_t"] > self.start_t:
                    r["wrapped"] = True
                    any_wrapped = True
                if r["gaps"]:
                    clean = False
                if r["restart_seen"] and (r["restart_t"] is None or r["restart_t"] <= self.end_t):
                    clean = False
                # I27 (m4-design.md 14.9 item 2 and 14.10), in lockstep with
                # m4count.c. A CPU whose events stop before the end marker is
                # recorded, not refused: from the listing alone an idle CPU
                # looks exactly like one that lost its trailing buffer, because
                # flushing writes the buffers that exist and does not create
                # events. Gating on it failed m4fix-1, a healthy window whose
                # CPUs 2 and 3 idle after the start.
                if r["last_t"] is None or r["last_t"] < self.end_t:
                    r["short_tail"] = True
            if any_wrapped:
                self.ring = "wrapped"
            elif self.start_t < self.end_t and clean:
                self.ring = "held"
        elif self.mk["end"] is not None and self.mk["start"] is None:
            # I22 (m4-design.md 14.5), in lockstep with m4count.c: the start marker was overwritten.
            # A CPU whose first kept BUFFER sequence is above 1 lost its earlier buffers.
            any_wrapped = False
            for r in self.cpu:
                if r["events"] and r["kept"] and r["first_seq"] > 1:
                    r["wrapped"] = True
                    any_wrapped = True
            if any_wrapped:
                self.ring = "wrapped"

        if self.window_known:
            T = self.triples
            for x in T:
                if x["t_enter"] is None or x["t_exit"] is None:
                    continue
                if (x["t_enter"] < self.start_t <= x["t_exit"]) or (x["t_enter"] <= self.end_t < x["t_exit"]):
                    self.anchor_lines += [x["line_enter"], x["line_cycles"], x["line_exit"]]
            seen = set()
            for x in T:
                if x["thread"] in seen:
                    continue
                if x["t_enter"] is not None and x["t_enter"] > self.end_t:
                    seen.add(x["thread"])
                    self.anchor_lines += [x["line_enter"], x["line_cycles"], x["line_exit"]]

        vcpu = {i for i, t in enumerate(self.thread_list) if t[2] > 0}
        self.untimed = [0] * MAX_CPUS
        anchor = [None] * MAX_CPUS
        tevs = []
        for t, th, cpu, kind, lineno in self.th_events:
            if kind == RUNNING and t is not None and self.window_known and t < self.start_t:
                if anchor[cpu] is None or t >= anchor[cpu][0]:
                    anchor[cpu] = (t, lineno)
            if kind == RUNNING or th in vcpu:
                if t is None:
                    self.untimed[cpu] += 1
                else:
                    tevs.append((t, cpu, th, kind))
        ievs = []
        for t, cpu in self.intr_events:
            if t is None:
                self.untimed[cpu] += 1
            else:
                ievs.append((t, cpu))
        for a in anchor:
            if a is not None:
                self.anchor_lines.append(a[1])
        self.anchor_lines = sorted(set(self.anchor_lines))
        tevs.sort()
        ievs.sort()
        self.tevs = tevs
        self.tev_t = [x[0] for x in tevs]
        self.ievs = ievs
        self.iev_t = [x[0] for x in ievs]
        self.rate = []
        for c in range(MAX_CPUS):
            if self.cpu[c]["events"] == 0:
                continue
            if self.window_known:
                ev = sum(1 for t in self.ev_times[c] if t is not None and self.start_t <= t <= self.end_t)
                bf = sum(1 for t in self.buf_times[c] if t is not None and self.start_t <= t <= self.end_t)
                self.rate.append((c, bf, ev, self.end_t - self.start_t))
            else:
                self.rate.append((c, 0, 0, None))
        # 14.7: the in-window part of the status table, as m4count.c's pass 2 counts it (status_window).
        self.status_win = {v: 0 for v in list(self.status)[:STATUS_PRINT]}
        if self.window_known:
            for t, st in self.exit_status:
                if t is None or t < self.start_t or t > self.end_t:
                    continue
                if st is None:
                    self.status_win_missing += 1
                elif st in self.status_win:
                    self.status_win[st] += 1
                else:
                    self.status_win_other += 1
        self._pairs()
        self.ev_times = None
        self.buf_times = None
        self.exit_status = None
        return self

    def _frag_between(self, th, lo, hi):
        if hi < lo:
            return False
        i = bisect.bisect_left(self.frags, (th, lo))
        return i < len(self.frags) and self.frags[i][0] == th and self.frags[i][1] <= hi

    def _classify(self, A, B, lo, hi):
        for c in range(MAX_CPUS):
            if self.untimed[c] and (self.cpu[c]["first_t"] is None or lo < self.cpu[c]["first_t"]):
                return "unk_untimed", 0
        cx = A["cpu_exit"]
        mig = B["cpu_enter"] != cx
        blk = pre = False
        i = bisect.bisect_left(self.tev_t, lo)
        while i < len(self.tevs) and self.tevs[i][0] <= hi:
            _, cpu, th, kind = self.tevs[i]
            if th == A["thread"]:
                if kind == RUNNING:
                    if cpu != cx:
                        mig = True
                elif kind == READY:
                    pre = True
                else:
                    blk = True
            elif kind == RUNNING and cpu == cx:
                pre = True
            i += 1
        ni = 0
        i = bisect.bisect_left(self.iev_t, lo)
        while i < len(self.ievs) and self.ievs[i][0] <= hi:
            if self.ievs[i][1] == cx:
                ni += 1
            i += 1
        return ("mig" if mig else "blk" if blk else "pre" if pre else "clean"), ni

    def _pairs(self):
        T = self.triples
        self.p_reason = {r: 0 for r in REASONS}
        self.p_class = {c: 0 for c in CLASSES}
        self.p_intr = {c: 0 for c in CLASSES}
        self.p_unk = 0
        self.p_total = 0
        for i in range(len(T) - 1):
            A, B = T[i], T[i + 1]
            if A["thread"] != B["thread"]:
                continue
            self.p_total += 1
            dwell = None
            if A["ax"] is not None and B["ae"] is not None:
                d = (B["ae"] - A["ax"]) % M64
                dwell = d - M64 if d >= (1 << 63) else d
            a = (A["ax"] - A["off"]) % M64 if A["ax"] is not None and A["off"] is not None else None
            b = (B["ae"] - B["off"]) % M64 if B["ae"] is not None and B["off"] is not None else None
            if a is not None and b is not None:
                lo, hi = (a, b) if a < b else (b, a)
                cls, intr = self._classify(A, B, lo, hi)
            else:
                cls, intr = "unk_untimed", 0
            if cls.startswith("unk"):
                self.p_unk += 1
            lo1 = A["t_exit"] if A["t_exit"] is not None else 0
            hi1 = B["t_enter"] if B["t_enter"] is not None else 0
            if self._frag_between(A["thread"], lo1, hi1):
                reason = "broken_between"
            elif not (A["order_ok"] and B["order_ok"]):
                reason = "order_violated"
            elif self.e3_status0 and (A["status"] is None or A["status"] != 0 or B["status"] is None or B["status"] != 0):
                reason = "status_nonzero"
            elif dwell < 0:
                reason = "negative"
            elif self.window_known and (a < self.start_t or b > self.end_t):
                reason = "out_of_window"
            elif self.ring != "held":
                reason = "not_held"
            elif cls == "unk_untimed":
                reason = "untimed"
            elif cls == "unk_capped":
                reason = "capped"
            else:
                reason = "eligible"
            self.p_reason[reason] += 1
            if reason == "eligible":
                self.p_class[cls] += 1
                self.p_intr[cls] += intr
            in_list = a is not None and self.window_known and self.start_t <= a <= self.end_t
            self.pairs.append({"i": i, "a": a, "b": b, "dwell": dwell, "cls": cls, "reason": reason,
                               "intr": intr, "cpu_exit": A["cpu_exit"], "cpu_entry": B["cpu_enter"],
                               "hw": A["hw"], "thread": A["thread"], "list": in_list})

    # --- records (§4.5.8)

    def stat(self, name):
        want = ("clean", "pre", "mig") if name == "nonblk" else (name,)
        vals = sorted(p["dwell"] for p in self.pairs if p["reason"] == "eligible" and p["cls"] in want)
        n = len(vals)
        q = str(NS_PER_S // self.cps) if NS_PER_S % self.cps == 0 else "inexact"
        if n == 0:
            return [("class", name), ("n", 0), ("p50_ticks", "-"), ("p99_ticks", "-"), ("max_ticks", "-"),
                    ("p50_ns", "-"), ("p99_ns", "-"), ("max_ns", "-"), ("quantum_ns", q), ("p99_quotable", "no")]
        p50 = vals[rank(50, n) - 1]
        p99 = vals[rank(99, n) - 1]
        mx = vals[-1]
        return [("class", name), ("n", n), ("p50_ticks", p50), ("p99_ticks", p99), ("max_ticks", mx),
                ("p50_ns", ticks_ns(p50, self.cps)), ("p99_ns", ticks_ns(p99, self.cps)),
                ("max_ns", ticks_ns(mx, self.cps)), ("quantum_ns", q),
                ("p99_quotable", "yes" if n >= QUOTABLE_N else "no")]

    def records(self, label="pc", quiet=False):
        R = []

        def add(name, fields):
            R.append((name, {"w": label, **{k: str(v) for k, v in fields}}))

        add("IN", [("path", "-"), ("lines", self.lines), ("bytes", self.bytes), ("events", self.events),
                   ("unformatted", self.unformatted), ("unformatted_header", self.unformatted_header),
                   ("unformatted_blank", self.unformatted_blank), ("unformatted_other", self.unformatted_other),
                   ("long_lines", self.long_lines), ("cpu_out_of_range", self.oor), ("cps", self.cps),
                   ("cps_source", "header" if self.cps_header else "default")])
        if not quiet:
            keys = list(self.hist.items())
            for (cls, sub), n in keys[:HIST_PRINT]:
                add("HIST", [("class", cls), ("sub", sub), ("n", n)])
            hs = [("keys", len(keys)), ("printed", min(len(keys), HIST_PRINT))]
            if self.hist_overflow:
                hs.append(("overflow", self.hist_overflow))
            add("HISTSUM", hs)
            add("QVM", list(self.q.items()))
            for sub, n in list(self.qother.items())[:QOTHER_PRINT]:
                add("QVMOTHER", [("sub", sub), ("n", n)])
            for sub, line in self.samples:
                add("SAMPLE", [("sub", sub), ("line", line)])
            # I36: outside SAMPLE_MAX, as m4count.c prints it.
            if self.unformatted_sample is not None:
                add("SAMPLE", [("sub", "unformatted"), ("line", self.unformatted_sample)])
        ts = self.ts
        add("TIME64", [("mode", ts.mode()), ("time_events", ts.time_events), ("mismatches", ts.mismatches),
                       ("wraps", ts.wraps), ("backsteps", ts.backsteps), ("backsteps64", ts.backsteps64),
                       ("unknown", ts.unknown)])
        for c, r in enumerate(self.cpu):
            if r["events"] == 0:
                continue
            add("BUF", [("cpu", c), ("first_seq", r["first_seq"]), ("last_seq", r["last_seq"]), ("kept", r["kept"]),
                        ("gaps", r["gaps"]), ("restarts", r["restarts"]), ("max_events", r["max_events"]),
                        ("first_t", hexs(r["first_t"])), ("last_t", hexs(r["last_t"]))])
        if not quiet:
            ms, me = self.mk["start"], self.mk["end"]
            add("MARK", [("start", "found" if ms else "absent"), ("start_t", hexs(ms["t"]) if ms else "-"),
                         ("start_cpu", ms["cpu"] if ms else "-"), ("end", "found" if me else "absent"),
                         ("end_t", hexs(me["t"]) if me else "-"), ("end_cpu", me["cpu"] if me else "-"),
                         ("dup", self.mk_dup)])
        wrapped = [str(c) for c, r in enumerate(self.cpu) if r["events"] and r["wrapped"]]
        seq1 = [str(c) for c, r in enumerate(self.cpu) if r["kept"] and r["first_seq"] == 1]
        short_tail = [str(c) for c, r in enumerate(self.cpu) if r["events"] and r["short_tail"]]
        add("RING", [("state", self.ring), ("wrapped_cpus", ",".join(wrapped) or "none"),
                     ("seq1_cpus", ",".join(seq1) or "none"),
                     ("short_tail_cpus", ",".join(short_tail) or "none")])
        if not quiet:
            for c, bf, ev, span in self.rate:
                add("RATE", [("cpu", c), ("bufs_in_window", bf), ("events_in_window", ev),
                             ("span_ticks", span if span is not None else "-")])
        vcpus = [i for i, t in enumerate(self.thread_list) if t[2] > 0]
        if vcpus:
            t0 = self.thread_list[vcpus[0]]
            add("VCPU", [("threads", len(vcpus)), ("pid", t0[0]), ("tid", t0[1]), ("cycles_events", t0[2]),
                         ("unattributed_qvm", self.unattributed)])
        else:
            add("VCPU", [("threads", 0), ("pid", "-"), ("tid", "-"), ("cycles_events", 0),
                         ("unattributed_qvm", self.unattributed)])
        if not quiet:
            of = [("distinct", len(self.offsets)), ("value", hexs(self.offsets[0]) if self.offsets else "-")]
            if self.offsets_overflow:
                of.append(("overflow", 1))
            add("OFFSET", of)
        # 14.7: printed with -q too (r0's fixture check reads them), as m4count.c does.
        items = list(self.status.items())
        for v, n in items[:STATUS_PRINT]:
            add("STATUS", [("value", hexs(v)), ("n", n), ("in_window", self.status_win.get(v, 0))])
        ss = [("distinct", len(items)), ("printed", min(len(items), STATUS_PRINT)),
              ("other", self.status_overflow + sum(n for _, n in items[STATUS_PRINT:])),
              ("missing", self.status_missing), ("in_window_other", self.status_win_other),
              ("in_window_missing", self.status_win_missing)]
        if self.status_overflow:
            ss.append(("overflow", self.status_overflow))
        add("STATUSSUM", ss)
        add("TRIPLES", [("complete", self.tr_complete), ("broken", self.tr_broken), ("alt_order", self.tr_alt),
                        ("order_ok", self.tr_ok), ("order_violated", self.tr_violated),
                        ("in_window", self.tr_in_window)])
        pr = self.p_reason
        add("PAIRS", [("total", self.p_total), ("eligible", pr["eligible"]), ("clean", self.p_class["clean"]),
                      ("pre", self.p_class["pre"]), ("blk", self.p_class["blk"]), ("mig", self.p_class["mig"]),
                      ("unk", self.p_unk), ("broken_between", pr["broken_between"]),
                      ("order_violated", pr["order_violated"]), ("status_nonzero", pr["status_nonzero"]),
                      ("negative", pr["negative"]), ("out_of_window", pr["out_of_window"]),
                      ("not_held", pr["not_held"]), ("untimed", pr["untimed"]), ("capped", pr["capped"]),
                      ("intr_clean", self.p_intr["clean"]), ("intr_pre", self.p_intr["pre"]),
                      ("intr_blk", self.p_intr["blk"]), ("intr_mig", self.p_intr["mig"]),
                      ("e3", "status0" if self.e3_status0 else "none")])
        for name in (("clean",) if quiet else STAT_CLASSES):
            add("STAT", self.stat(name))
        if not quiet:
            pm = self.p_class["pre"] + self.p_class["mig"]
            nonblk = self.p_class["clean"] + pm
            if nonblk > 0 and pm * 100 >= nonblk:
                R.append(("WARN", {"w": label, "pre_mig": str(pm), "nonblk": str(nonblk),
                                   "permille": str(pm * 1000 // nonblk)}))
        return R


def render_records(records):
    out = []
    for name, f in records:
        parts = [f"M4C {name}", f"w={f['w']}"]
        if name == "WARN":
            parts.append("clean_tail_bias")
        for k, v in f.items():
            if k == "w":
                continue
            parts.append(f'{k}="{v}"' if name == "SAMPLE" and k == "line" else f"{k}={v}")
        out.append(" ".join(parts))
    return out


def verbatim_selection(data, L, vcap):
    """§4.5.8 form v over the listing bytes, as the counter's pass 3 writes it."""
    ts = TimeState()
    anchors = set(L.anchor_lines)
    # I23 (m4-design.md 14.5), in lockstep with m4count.c: the marker events themselves, always.
    marks = {m["line"] for m in (L.mk["start"], L.mk["end"]) if m is not None}
    out = bytearray()
    st = {"lines": 0, "capped": 0, "sel_lines": 0, "sel_bytes": 0, "last_t": None, "collision": 0, "cr": 0}
    seen_event = False
    lineno = 0
    for raw in iter_raw_lines(data):
        lineno += 1
        if len(raw) - (1 if raw.endswith(b"\n") else 0) >= LONG_LINE:
            continue
        line = raw.decode("latin-1")
        e = parse_event(line)
        sel = False
        t = None
        if e is None:
            sel = not seen_event
        elif e.cpu < MAX_CPUS:
            seen_event = True
            t = ts.time(e)
            if e.cls == "CONTROL":
                sel = True
            elif t is not None and L.window_known and L.start_t <= t <= L.end_t:
                sel = True
            if lineno in anchors or lineno in marks:
                sel = True
        if not sel:
            continue
        if not raw.endswith(b"\n"):
            raw = raw + b"\n"
        if FLT_MARK.encode() in raw:
            st["collision"] += 1
            continue
        st["sel_lines"] += 1
        st["sel_bytes"] += len(raw)
        if st["capped"]:
            continue
        if len(out) + len(raw) > vcap:
            st["capped"] = 1
            continue
        out += raw
        st["lines"] += 1
        st["cr"] += raw.count(b"\r")
        if t is not None:
            st["last_t"] = t
    return bytes(out), st


def compact_list(L, ccap, label):
    """§4.5.8 form c, as the counter writes it."""
    start = hexs(L.start_t) if L.window_known else "-"
    head = (f"# m4count compact w={label} start_t={start} cps={L.cps} "
            f"fields=k,class,elig,dwell_ticks,cpu_exit,cpu_entry,hw_reason,dt_start_ticks\n").encode()
    out = bytearray()
    capped = 0
    lines = 0
    written = 0
    if len(head) <= ccap:
        out += head
        lines = 1
    else:
        capped = 1
    listed = sorted((p for p in L.pairs if p["list"]), key=lambda p: (p["a"], p["thread"], p["i"]))
    for j, p in enumerate(listed):
        if capped:
            break
        dt = (p["a"] - L.start_t) % M64
        dt = dt - M64 if dt >= (1 << 63) else dt
        cls = "unk" if p["cls"].startswith("unk") else p["cls"]
        line = (f"c {j + 1} {cls} {1 if p['reason'] == 'eligible' else 0} "
                f"{p['dwell'] if p['dwell'] is not None else '-'} {p['cpu_exit']} {p['cpu_entry']} "
                f"{'%x' % p['hw'] if p['hw'] is not None else '-'} {dt}\n").encode()
        if len(out) + len(line) > ccap:
            capped = 1
            break
        out += line
        lines += 1
        written += 1
    return bytes(out), {"lines": lines, "capped": capped, "pairs_written": written, "pairs_total": len(listed)}


def compact_rows(body):
    """§4.5.8 form c as the counter wrote it: the rows in file order, and the
    index the cross-check looks pairs up in. The counter writes one row per
    pair, keyed by the entry's offset from start_t and the exit CPU, so that key
    is unique by construction and a missing entry is a disagreement rather than
    a collision."""
    index = {}
    rows = []
    for raw in iter_raw_lines(body):
        parts = raw.decode("latin-1").split()
        if len(parts) != 9 or parts[0] != "c":
            continue
        _, k, cls, elig, dwell, cx, ce, hw, dt = parts
        row = (cls, elig, dwell, cx, ce)
        rows.append(row)
        index[(to_int(dt), to_int(cx))] = row
    return index, rows


def xcheck_pairs_record(L, c_lines, limit, c_capped):
    """§6.2's cross-check of the PC's pairs against the counter's compact block,
    in both directions (I28; m4-design.md 14.9 item 3 and 14.11).

    `limit` is the last time the PC could have seen: the window's end, or the
    delivered listing's last event when block `v` was capped. Both walks bound a
    pair by its exit and by the CPU it exited on, so neither side is compared
    past the data it was given.
    """
    # The bound was the file-order last_t of the verbatim block, but the listing
    # is ordered per CPU buffer: a CPU whose delivered events stop earlier would
    # be compared past its own data, and a pair the PC never saw would count as
    # the counter's fault. Each CPU is bounded by its own last delivered event.
    cpu_limit = {}
    for c, r in enumerate(L.cpu):
        if r["events"] and r["last_t"] is not None:
            cpu_limit[c] = min(limit, r["last_t"])

    def in_range(t, cpu):
        if t is None or t < L.start_t:
            return False
        return t <= cpu_limit.get(cpu, limit)

    compared = 0
    bad = 0
    seen = set()
    # I34 (m4-design.md 14.18): how many pairs each side had inside the range, so
    # a thin comparison shows its denominator and not only its agreement.
    pc_in = 0
    for p in L.pairs:
        if p["a"] is None or p["b"] is None or p["a"] < L.start_t:
            continue
        if not in_range(p["b"], p["cpu_exit"]):
            continue
        pc_in += 1
        key = ((p["a"] - L.start_t), p["cpu_exit"])
        got = c_lines.get(key)
        if got is None:
            if not c_capped:
                bad += 1
            continue
        seen.add(key)
        compared += 1
        want = ("unk" if p["cls"].startswith("unk") else p["cls"], "1" if p["reason"] == "eligible" else "0",
                str(p["dwell"]) if p["dwell"] is not None else "-", str(p["cpu_exit"]), str(p["cpu_entry"]))
        if got != want:
            bad += 1

    # The other direction: a row the counter wrote, inside the range the PC
    # could see, that the PC produced no pair for. A capped compact block is
    # exempt, exactly as the forward walk is.
    #
    # The bound is the row's exit, entry + dwell, and not its entry, because
    # that is what the forward walk bounds a pair by. A row whose entry is
    # inside the range and whose exit is past it is skipped going forward,
    # correctly - the PC holds no exit event to pair with - so counting it
    # coming back would report the truncation as a disagreement. The r1 board
    # record holds exactly one such row (m4-design.md 14.11). A row whose dwell
    # is not a number gives no exit to bound, so it is left alone rather than
    # compared past the PC's data.
    orphan = 0
    c_in = 0
    for key, val in c_lines.items():
        off, cx = key
        dwell = to_int(val[2])
        if off is None or dwell is None:
            continue
        if not in_range(L.start_t + off + dwell, cx):
            continue
        c_in += 1
        if not c_capped and key not in seen:
            orphan += 1

    ranges = f"pc_in_range={pc_in} c_in_range={c_in}"
    if bad == 0 and orphan == 0 and compared > 0:
        return f"match compared={compared} {ranges}"
    if compared == 0:
        return f"empty compared=0 orphan={orphan} {ranges}"
    return f"differ({bad}) orphan={orphan} compared={compared} {ranges}"


def startup_order_bad(texts, p_cpus):
    """§2.2 item 1 / D3 §8 items 1-2: the two orderings `landing_ok` leaves out
    (I30b; m4-design.md 14.9 item 3). That function checks each token is
    present, which a run could satisfy with the lines in the wrong order.

    Positions are read within one ordered source. A token that is absent is left
    to `landing_ok`, which names it; reporting it twice would say less.
    """
    def first(sub):
        for i, t in enumerate(texts):
            if sub in t:
                return i
        return None

    why = []
    for earlier, later, name in (("T234-SHIM", "JUMP", "shim-before-jump"),
                                 (f"t234: all {p_cpus} cpus parked in smp_spin", "Starting next program",
                                  "parked-before-next-program")):
        ai, bi = first(earlier), first(later)
        if ai is not None and bi is not None and ai >= bi:
            why.append(f"order-{name}")
    return why


GUEST_PHASES = ("g_first", "g_devb", "g_net", "g_ifup", "g_sshd", "g_misc", "g_startup_complete")
GUEST_PHASES_REQUIRED = ("g_first", "g_devb", "g_net", "g_startup_complete")


def guest_phase_bad(stamps):
    """D3 §8 item 6: the guest's phases stamped with non-decreasing `cycles=`,
    in order, each at or below `banner` (I30b).

    A missing `g_ifup`, `g_sshd` or `g_misc` is an anomaly the run note records
    and not a failure, so only the phases that are present are ordered. `g_srv`
    is recorded and never gated, which item 6 states outright: the guest starts
    the server in the background and never waits for its line, one TCG run lost
    that line to interleaving while its IPC completed cleanly, and item 8 is the
    evidence the server was up.
    """
    why = []
    for name in GUEST_PHASES_REQUIRED:
        if stamps.get(name) is None:
            why.append(f"phase-{name}-absent")
    present = [(n, stamps[n]) for n in GUEST_PHASES if stamps.get(n) is not None]
    for (n0, c0), (n1, c1) in zip(present, present[1:]):
        if c1 < c0:
            why.append(f"phase-order:{n0}>{n1}")
    banner = stamps.get("banner")
    if banner is not None:
        late = [n for n, c in present if c > banner]
        if late:
            why.append("phase-after-banner:" + ",".join(late[:3]))
    return why


def trcctl_bad(lines, markers):
    """§2.2 item 2, the part the stop ladder cannot show (I30; m4-design.md 14.9
    item 3). The ksh derives `by=stop` from the `.done` file, so a marker insert
    or a stop that returned non-zero still read as a clean stop. The board
    prints one `TRCCTL insert … rc=` line per marker and one `TRCCTL stop … rc=`,
    and these are what they say."""
    seen = {}
    for text in lines:
        if text.startswith("TRCCTL insert"):
            d, _ = parse_kv(text)
            seen[d.get("text", "")] = to_int(d.get("rc"))
        elif text.startswith("TRCCTL stop"):
            seen["\0stop"] = to_int(parse_kv(text)[0].get("rc"))
    why = []
    for want in list(markers) + ["\0stop"]:
        name = "stop" if want == "\0stop" else f"insert:{want}"
        if want not in seen:
            why.append(f"trcctl_{name}_absent")
        elif seen[want] != 0:
            why.append(f"trcctl_{name}_rc:{seen[want]}")
    return why


# I32 (m4-design.md 14.16): the pins D3 §8 item 3 names, as make-m4-images.sh:94-96 holds them.
PIN_GUEST = "968029316b940f53580228f44e393877e032e251d78f3c752600cae726a7cf4f"
PIN_DISK = "cf5b06d0b3cb524201c71440fdda42a18d2636d45938acd8ec95cfa21314216b"
PIN_CLIENT = "52cb4dcad5a3632f88092289ef68668cc1fc604f150f3e2f8b9f31dc82caa7eb"
IPC_PAYLOAD = 48            # FRAME_PAYLOAD_BYTES, the client's `samples=` line (D3 §8 item 8)
IPC_WARMUP = 5              # the warm-up the host script passes: `qnx-host-client @ITERS@ /dev/ttyp0 5` (I40)
KEV_T = "/dev/shmem/t.kev"
PIDIN_HEAD_RE = re.compile(r"^\s*pid\s+tid\s+name\b")
SAMPLES_LINE_RE = re.compile(r"^samples=(\d+) payload=(\d+) cps=(\d+)$")
P50_LINE_RE = re.compile(r"^P50=\d+ ns  P99=\d+ ns  Max=\d+ ns$")
SMP_DONE_RE = re.compile(r"^SMPCHECK done cpu=(\d+) .*\brate=\d+")
STAMP_CPS_RE = re.compile(r"^STAMP (qvm_launch|banner) .*\bcps=(\d+)")


def config_exact_bad(config, p_cpus):
    """D3 §8 item 3's values, where I30b asked only that the fields be present
    (I32; m4-design.md 14.16). The startup line is read by its options, not as a
    whole, so contingency C4's `-vv` image still passes."""
    why = []
    for key, want in (("q", "el2-host"), ("w", "keep"), ("A", "1"), ("clock", "unverified"),
                      ("guest_sha256", PIN_GUEST), ("disk_sha256", PIN_DISK), ("client_sha256", PIN_CLIENT)):
        got = config.get(key)
        if got and got != want:
            why.append(f"config-{key}")
    tok = (config.get("startup") or "").split()
    if tok:
        q = tok.index("-Q") if "-Q" in tok else -1
        if (tok[0] != "startup-t234-orin-nano" or f"-P{p_cpus}" not in tok or q < 0 or tok[q + 1:q + 2] != ["enable,el2-host"]
                or "-Wkeep" not in tok or tok.count("-A") != 1 or "-m992M" not in tok):
            why.append("config-startup")
    return why


def run_lines_bad(src, *, rung, p_cpus, board, cps_want):
    """§2.2 item 1's remaining D3 §8 items, read in one ordered source (I32;
    m4-design.md 14.9 item 3, 14.14, 14.16). Returns the reasons crit_1 fails for.

    Items 5, 7 and 8 hold under TCG too: the banner in the guest stream printed in
    `diag`, not anywhere in the texts; no `rc=` line and no `QVM ended before
    teardown` before `M4 STATE teardown`; a `pidin` listing in `report` and in
    `report_ipc`, counted by its column header, because the host script never
    echoes the command (14.13); `payload=48`; the P50 line. `board` adds what only
    a board image prints: four `SMPCHECK done … rate=` lines before and four after
    (item 10, recorded and not judged for drift), the listing's `cps` on the IPC
    line and on the two stamps (items 5 and 8), and the build script's reset line
    after `M4 STATE end` (item 11)."""
    why = []
    state = None
    teardown = end = False
    early_rc = banner = p50 = reset = False
    pidin = {"report": 0, "report_ipc": 0}
    rates = {"rate_pre": set(), "rate_post": set()}
    samples = None
    stamp_cps = {}
    reset_text = f"T234 M4 {rung} -P{p_cpus}: resetting so the log can be recovered"
    for t in src:
        if t.startswith("M4 STATE "):
            state = t[9:].split(" ")[0]
            teardown = teardown or state == "teardown"
            end = end or state == "end"
            continue
        # Only the host script's own lines: COM3 and the black box also hold
        # Linux's shutdown, the shim and startup before `M4 STATE config`.
        if (state is not None and not teardown
                and (t.startswith("rc=") or t.startswith("M4 QVM ended before teardown"))):
            early_rc = True
        if state in pidin and PIDIN_HEAD_RE.match(t):
            pidin[state] += 1
        if state in rates:
            m = SMP_DONE_RE.match(t)
            if m:
                rates[state].add(int(m.group(1)))
        if state == "diag" and BANNER_RE.search(t):
            banner = True
        m = SAMPLES_LINE_RE.match(t)
        if m and samples is None:
            samples = (int(m.group(2)), int(m.group(3)))
        if P50_LINE_RE.match(t):
            p50 = True
        m = STAMP_CPS_RE.match(t)
        if m:
            stamp_cps.setdefault(m.group(1), int(m.group(2)))
        if end and reset_text in t:
            reset = True
    if early_rc:
        why.append("early-rc")
    for st, n in pidin.items():
        if n < 1:
            why.append(f"pidin-{st}-absent")
    if not banner:
        why.append("banner-guest-stream")
    if samples is None:
        why.append("ipc-samples-line")
    else:
        if samples[0] != IPC_PAYLOAD:
            why.append(f"ipc-payload:{samples[0]}")
        if cps_want is not None and samples[1] != cps_want:
            why.append(f"ipc-cps:{samples[1]}")
    if not p50:
        why.append("ipc-p50-line")
    if board:
        for st in ("rate_pre", "rate_post"):
            miss = [str(c) for c in range(p_cpus) if c not in rates[st]]
            if miss:
                why.append(f"rates-{st[5:]}:" + ",".join(miss))
        for k in ("qvm_launch", "banner"):
            if stamp_cps.get(k) != cps_want:
                why.append(f"stamp-cps:{k}")
        if not reset:
            why.append("reset-line")
    return why


def stamp_ipc_lines(recs):
    """D3 §8 item 11's narrow comparison: the STAMP and IPC lines, in order (I32)."""
    return [t for t in recs if t.startswith(("STAMP ", "samples=", "P50=", "sentinel_", "BWAIT run prog=qnx-host-client "))]


# ------------------------------------------------------------------ run: capture, records, blocks

RECORD_PREFIXES = ("M4 ", "M4C ", "BWAIT ", "TRCCTL ", "STAMP ", "tcu-cat:", "samples=", "P50=", "sentinel_", "CLK ")
HEADER_RE = re.compile(r"^--- raw capture started on (\S+) at (\d+), (\S+) epoch=(\d+) seconds=(\d+) ---$")
FLT_BEGIN_RE = re.compile(r"^M4 FLT BEGIN name=(\S+) rung=(\S*) lines=(\S*) bytes=(\S*) wc_bytes=(\S*) "
                          r"md5=(\S*) cksum=(\S*)")
BWAIT_RUN_RE = re.compile(r"^BWAIT run prog=(\S+) rc=(-?\d+) sig=(\d+) killed=([01]) ms=(\d+)")
MEM_RE = re.compile(r"^M4 MEM (\S+) (\d+)MB")
BANNER_RE = re.compile(r"QNX qnx-guest 8[.]0[.]0 .*ARMv8_Foundation_Model aarch64le")
NEG_FIXED = ['t234: EL1', 't234: EL2', 'hvtimer STOP', 'el2-host requested but', 'continuing despite', 'probe off',
             'ASSERT', 'start failure', 'start timeout', 'released but', 'entered at EL1', 'wake timeout',
             'not awake', 'transfer hook ran', 'PE is not awake', 'does not match cpu 0', 'tick=dead', 'tick=bad',
             'CENSUS FAIL', 'RESULT FAIL', 'BWAIT guard deadline', 'STAMP exec-failed', 'STAMP read-error',
             'Unable to start', '[g2.conf:', 'Could not load library', 'unrecoverable stall',
             'sentinel-recovery exhausted', 'echo seq mismatch', 'killed=1', 'No system file system',
             'Unable to access /dev/hd0', 'BAD-LANDING', 'Shutdown[',
             'by=early', 'by=sigint', 'by=kill', 'by=none', 'path=none', 'aborted=1', 'deadline=1',
             'state=wrapped', 'state=unknown', 'mem_trace', 'mem_format']
NEG_PATTERNS = [r"M4 FAIL([^_]|$)", r"^TRCCTL .*rc=-1", r"mismatches=[1-9]", r"order_violated=[1-9]",
                r"drops=[1-9]", r"marker_collision=[1-9]", r"M4C END w=[A-Za-z0-9_.-]+ rc=[13]"]


def parse_capture(data, fmt):
    cap = {"cs": 0, "ce": len(data), "header": "n/a", "epoch": None, "seconds": None,
           "end_offset": None, "end_iso": None}
    if fmt != "capture":
        return cap
    nl = data.find(b"\n")
    head = data[:nl if nl >= 0 else len(data)].decode("latin-1").rstrip("\r")
    m = HEADER_RE.match(head)
    if m:
        cap.update(header="ok", epoch=int(m.group(4)), seconds=int(m.group(5)))
    elif head.startswith("--- raw capture started"):
        cap["header"] = "no-epoch"
    else:
        cap["header"] = "missing"
    if cap["header"] != "missing":
        cap["cs"] = nl + 1 if nl >= 0 else len(data)
    k = data.rfind(b"--- raw capture ended ")
    if k >= cap["cs"] and (k == 0 or data[k - 1:k] == b"\n"):
        cap["end_offset"] = k
        cap["ce"] = k
        m2 = re.match(rb"--- raw capture ended (\S+) bytes=(\d+) ---", data[k:k + 200])
        if m2:
            cap["end_iso"] = m2.group(1).decode("latin-1")
    return cap


def iso_epoch(iso):
    if not iso:
        return None
    m = re.match(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)?$", iso)
    if not m:
        return None
    tz = m.group(3) or "+00:00"
    if tz == "Z":
        tz = "+00:00"
    try:
        dt = datetime.fromisoformat(m.group(1) + tz)
    except ValueError:
        return None
    return int(dt.timestamp())


def find_end_marker(data, name, pos, end):
    needle = b"=M4FLT= END name=" + name.encode("latin-1")
    while True:
        k = data.find(needle, pos, end)
        if k < 0:
            return -1, -1
        after = data[k + len(needle):k + len(needle) + 1]
        before_ok = k == 0 or data[k - 1:k] == b"\n"
        if after in (b"", b"\r", b"\n", b" ") and before_ok:
            nl = data.find(b"\n", k, end)
            return k, (end if nl < 0 else nl + 1)
        pos = k + 1


def check_block(data, cap, name, ref, search_from, com3_ended):
    """§6.3 steps 1-4 for one block. Returns (status, info)."""
    info = {"range": None, "body": None}
    cs, ce = cap["cs"], cap["ce"]
    full_end = len(data)
    begin = b"=M4FLT= BEGIN name=" + name.encode("latin-1") + b" rung="
    mb = data.find(begin, max(search_from, cs), full_end)
    if mb < 0:
        return "absent", info
    nl = data.find(b"\n", mb, full_end)
    if nl < 0:
        return "truncated", info
    body_start = nl + 1
    me, me_end = find_end_marker(data, name, body_start, full_end)
    if me < 0:
        info["range"] = (mb, full_end)
        if com3_ended is not None and com3_ended <= full_end:
            info["ended_early"] = True
        return "truncated", info
    if cap["end_offset"] is not None and me >= cap["end_offset"]:
        info["ended_early"] = True
    info["range"] = (mb, me_end)
    body = data[body_start:me].replace(b"\r", b"")
    info["body"] = body
    bad = []
    md5 = hashlib.md5(body).hexdigest()
    crc, ln = posix_cksum(body)
    lines = body.count(b"\n")
    if ref.get("md5") != md5:
        bad.append("md5")
    if to_int(ref.get("cksum")) != crc:
        bad.append("cksum")
    if to_int(ref.get("bytes")) != ln or to_int(ref.get("wc_bytes")) != ln:
        bad.append("bytes")
    if to_int(ref.get("lines")) != lines:
        bad.append("lines")
    info.update(md5=md5, crc=crc, bytes=ln, lines=lines)
    return ("ok" if not bad else "mismatch(" + "+".join(bad) + ")"), info


class Records:
    """The console records of one run (§6.2 step 2), in order."""

    def __init__(self, texts):
        self.texts = texts
        self.states = []
        self.config = {}
        self.config_line = ""
        self.checks = set()
        self.fails = []
        self.fail_state = None
        self.mem = {}
        self.trace_arm = False
        self.trace_arm_f = {}
        self.stops = {}
        self.kevfile = {}
        self.kevfile_f = {}
        self.text = {}
        self.bwait = []
        self.tcu = {}
        self.flt_begin = {}
        self.flt_end = {}
        self.flt_skip = {}
        self.samples = None
        self.sentinel = None
        self.stamps = {}
        self.clk = []
        self.guard = None
        self.runs = []
        self.trcctl = []
        state = None
        listing = None
        block = None
        cur = {}
        for text in texts:
            if text.startswith("M4 STATE "):
                state = text[9:].split(" ")[0]
                self.states.append(state)
                listing = None
                continue
            if text.startswith("M4C "):
                p = parse_m4c(text)
                if p is None or state not in ("fixtures", "format"):
                    continue
                name, fields, bare = p
                w = fields.get("w", "")
                run = cur.get(w)
                if run is None:
                    run = {"w": w, "state": state, "recs": []}
                    cur[w] = run
                    self.runs.append(run)
                run["recs"].append((name, fields, bare))
                if name == "END":
                    del cur[w]
                continue
            if text.startswith("M4 CONFIG ") and not self.config:
                self.config, _ = parse_kv(text[10:])
                self.config_line = text
            elif text.startswith("M4 CHECK "):
                parts = text[9:].split()
                if parts and parts[-1] == "ok":
                    self.checks.add(" ".join(parts[:-1]))
            elif text.startswith("M4 FAIL_STATE "):
                self.fail_state = text[14:].strip()
            elif text.startswith("M4 FAIL "):
                self.fails.append(text[8:].strip())
            elif text.startswith("M4 MEM "):
                m = MEM_RE.match(text)
                if m:
                    self.mem.setdefault(m.group(1), int(m.group(2)))
            elif text.startswith("M4 TRACE ARM"):
                if not self.trace_arm:
                    # I33: kind, args and file are compared with the params (crit_2).
                    self.trace_arm_f = parse_kv(text)[0]
                self.trace_arm = True
            elif text.startswith("M4 STOP "):
                parts = text[8:].split()
                if parts:
                    self.stops.setdefault(parts[0], parse_kv(text)[0].get("by", ""))
            elif text.startswith("M4 KEVFILE "):
                parts = text[11:].split()
                if parts:
                    listing = parts[0]
                    d, _ = parse_kv(text)
                    self.kevfile.setdefault(listing, d.get("bytes", d.get("path", "none")))
                    self.kevfile_f.setdefault(listing, d)
            elif text.startswith("M4 TEXT "):
                parts = text[8:].split()
                if parts:
                    self.text.setdefault(parts[0], parse_kv(text)[0].get("bytes", "none"))
            elif text.startswith("M4 FLT BEGIN "):
                m = FLT_BEGIN_RE.match(text)
                if m:
                    block = m.group(1)
                    self.flt_begin.setdefault(block, {"rung": m.group(2), "lines": m.group(3), "bytes": m.group(4),
                                                      "wc_bytes": m.group(5), "md5": m.group(6),
                                                      "cksum": m.group(7)})
            elif text.startswith("M4 FLT END "):
                d, _ = parse_kv(text)
                self.flt_end.setdefault(d.get("name", ""), d.get("rc", ""))
                block = None
            elif text.startswith("M4 FLT SKIP "):
                d, _ = parse_kv(text)
                self.flt_skip.setdefault(d.get("name", ""), d.get("reason", ""))
            elif text.startswith("BWAIT run "):
                m = BWAIT_RUN_RE.match(text)
                if m:
                    self.bwait.append({"prog": m.group(1), "rc": int(m.group(2)), "sig": int(m.group(3)),
                                       "killed": int(m.group(4)), "ms": int(m.group(5)), "state": state,
                                       "listing": listing, "block": block})
                elif "spawn-failed" in text:
                    d, _ = parse_kv(text)
                    self.bwait.append({"prog": d.get("prog", "?"), "rc": -1, "sig": 0, "killed": 0, "ms": 0,
                                       "state": state, "listing": listing, "block": block, "spawn_failed": True})
            elif text.startswith("BWAIT guard armed "):
                self.guard = parse_kv(text)[0].get("secs")
            elif text.startswith("tcu-cat:"):
                d, _ = parse_kv(text[8:])
                self.tcu.setdefault(block or "-", []).append(d)
            elif text.startswith("TRCCTL "):
                self.trcctl.append(text)
            elif text.startswith("STAMP "):
                parts = text.split()
                if len(parts) > 1 and parts[1] not in self.stamps:
                    self.stamps[parts[1]] = to_int(parse_kv(text)[0].get("cycles"))
            elif text.startswith("samples=") and self.samples is None:
                self.samples = to_int(parse_kv(text)[0].get("samples"))
            elif text.startswith("sentinel_recoveries=") and self.sentinel is None:
                self.sentinel = to_int(parse_kv(text)[0].get("sentinel_recoveries"))
            elif text.startswith("CLK VERDICT "):
                self.clk.append(parse_kv(text[12:])[0])

    def run_for(self, w, index=0):
        found = [r for r in self.runs if r["w"] == w]
        return found[index] if len(found) > index else None

    def bwait_for(self, prog, listing=None, block=None):
        for b in self.bwait:
            if b["prog"] == prog and (listing is None or b["listing"] == listing) and (block is None or b["block"] == block):
                return b
        return None


def rec_first(run, name):
    if run is None:
        return None
    for n, f, _ in run["recs"]:
        if n == name:
            return f
    return None


def rec_all(run, name):
    if run is None:
        return []
    return [f for n, f, _ in run["recs"] if n == name]


def fixture_expects(path):
    exp = []
    for raw in iter_raw_lines(read_bytes(path)):
        line = raw.decode("latin-1").rstrip("\r\n")
        if line.startswith("# expect: M4C "):
            p = parse_m4c(line[len("# expect: "):])
            if p:
                exp.append((p[0], p[1]))
    return exp


def check_expects(recs, expects):
    """recs: [(name, fields)]. An expectation holds when some record of that name has every listed field."""
    missing = []
    for name, want in expects:
        if not any(n == name and all(f.get(k) == v for k, v in want.items()) for n, f in recs):
            missing.append(name + ":" + ",".join(f"{k}={v}" for k, v in want.items()))
    return missing


def fixture_runs_from_lines(texts):
    """The counter's w=fix runs from any record text, keyed by fixture basename."""
    runs = {}
    cur = None
    for text in texts:
        p = parse_m4c(text)
        if p is None or p[1].get("w") != "fix":
            continue
        name, fields, _ = p
        if name == "IN":
            cur = os.path.basename(fields.get("path", "?").replace("\\", "/"))
            runs[cur] = []
        if cur is not None:
            runs[cur].append((name, fields))
        if name == "END":
            cur = None
    return runs


def read_params(path):
    params = {}
    for raw in iter_raw_lines(read_bytes(path)):
        line = raw.decode("latin-1").rstrip("\r\n")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        params.setdefault(k.strip(), v)
    return params


def status_window_diffs(t_status, t_sum, p_status, p_sum):
    """m4-design.md 14.7: the target's GUEST_EXIT status records against the PC's reading of block v.

    n, distinct and other cover the whole listing, which v does not hold (as I8), so only the in-window
    part is compared. A printed value's in_window counts every in-window event of that value on either
    side, so a value printed on both sides must agree. When neither side counted an in-window event of an
    unprinted value (in_window_other), the values with in-window events must also be the same.
    """
    if t_sum is None or p_sum is None:
        return ["STATUSSUM.absent"]
    tm = {f.get("value"): to_int(f.get("in_window")) for f in t_status}
    pm = {f.get("value"): to_int(f.get("in_window")) for f in p_status}
    t_other, t_miss = to_int(t_sum.get("in_window_other")), to_int(t_sum.get("in_window_missing"))
    p_other, p_miss = to_int(p_sum.get("in_window_other")), to_int(p_sum.get("in_window_missing"))
    if None in (t_other, t_miss, p_other, p_miss) or None in tm.values() or None in pm.values():
        return ["STATUSSUM.fields"]
    diffs = []
    if t_miss != p_miss:
        diffs.append("STATUSSUM.in_window_missing")
    if sum(tm.values()) + t_other + t_miss != sum(pm.values()) + p_other + p_miss:
        diffs.append("STATUSSUM.in_window")
    for v in sorted(set(tm) & set(pm)):
        if tm[v] != pm[v]:
            diffs.append(f"STATUS.{v}.in_window")
    if t_other == 0 and p_other == 0:
        for v in sorted(set(tm) ^ set(pm)):
            if (tm[v] if v in tm else pm[v]) != 0:
                diffs.append(f"STATUS.{v}.in_window")
    return diffs


def cmd_run(a):
    log = Log()
    try:
        params = read_params(a.params)
        bb = None if a.blackbox == "none" else read_bytes(a.blackbox)
        com3 = read_bytes(a.com3)
    except InputError as e:
        print(f"parse-m4: input error: {e}", file=sys.stderr)
        return 1
    try:
        parse_log = os.path.join(a.out_dir, f"{a.run_id}-parse.log")
        csv_path = a.csv or os.path.join(a.out_dir, "orin-native-qvm-trace-latest.csv")
        check_out_path(parse_log)
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2

    rung = params.get("rung", "?")
    variant = params.get("variant", "")
    mode = params.get("mode", "full" if rung in ("r1", "r2") else "trace")
    p_cpus = to_int(params.get("p"), 4)
    iters = to_int(params.get("iters"), 15)
    transport = params.get("transport", "tcu")
    e3 = params.get("e3", "status0") != "none"
    main_w = "l0" if rung == "r0" else "t"
    start_marker = params.get("start_marker") or ("m4-l0-start" if rung == "r0" else "m4-ipc-start")
    end_marker = params.get("end_marker") or ("m4-l0-end" if rung == "r0" else "m4-ipc-end")
    is_t = bool(re.search(r"-t[1-5]$", a.run_id))
    is_q = a.run_id.endswith("-q")

    log("parser_sha256", sha256_file(os.path.abspath(__file__)))
    log("input_params", f"{os.path.basename(a.params)} sha256:{sha256_file(a.params)}")
    log("input_blackbox", "none" if bb is None else f"{os.path.basename(a.blackbox)} sha256:{sha256_file(a.blackbox)}")
    log("input_com3", f"{os.path.basename(a.com3)} sha256:{sha256_file(a.com3)}")
    # I34 (m4-design.md 14.18): the board's own sha256 of its black box, which the
    # harness read on the board, against the copy this parse reads. The harness's
    # own comparison used to reach the board log only, and gate nothing.
    bb_sha = "n/a(no-blackbox)"
    if bb is not None:
        want_sha = (getattr(a, "blackbox_board_sha256", None) or "").strip().lower()
        if want_sha in ("", "none"):
            bb_sha = "unknown"
        else:
            bb_sha = "equal" if sha256_file(a.blackbox) == want_sha else "differ"
    log("blackbox_board_sha256", bb_sha)
    log("run_id", a.run_id)
    log("rung", rung)
    log("mode", mode)
    log("rehearsal", "yes" if a.rehearsal else "no")
    for k in sorted(params):
        log(f"param_{k}", params[k])

    # Step 1: the capture.
    cap = parse_capture(com3, a.com3_format)
    log("com3_format", a.com3_format)
    log("com3_header", cap["header"])
    log("com3_bytes", len(com3))
    log("blackbox_bytes", "none" if bb is None else len(bb))
    com3_all = split_lines(com3, cap["cs"], cap["ce"])
    bb_all = split_lines(bb) if bb is not None else None

    # Step 3 before 2: the block bodies are excluded from the COM3 records.
    begins_com3 = {}
    for off, text in com3_all:
        m = FLT_BEGIN_RE.match(text)
        if m and m.group(1) not in begins_com3:
            begins_com3[m.group(1)] = (off, {"lines": m.group(3), "bytes": m.group(4), "wc_bytes": m.group(5),
                                             "md5": m.group(6), "cksum": m.group(7)})
    begins_bb = {}
    for _, text in (bb_all or []):
        m = FLT_BEGIN_RE.match(text)
        if m and m.group(1) not in begins_bb:
            begins_bb[m.group(1)] = {"lines": m.group(3), "bytes": m.group(4), "wc_bytes": m.group(5),
                                     "md5": m.group(6), "cksum": m.group(7)}
    blocks = {}
    excl = []
    ended_early = False
    for name in sorted(set(begins_com3) | set(begins_bb)):
        ref = begins_bb.get(name) or begins_com3[name][1]
        start = begins_com3[name][0] if name in begins_com3 else cap["cs"]
        status, info = check_block(com3, cap, name, ref, start, cap["end_offset"])
        blocks[name] = (status, info)
        if info.get("range"):
            excl.append(info["range"])
        if info.get("ended_early"):
            ended_early = True
    log("com3_ended_early", "yes" if ended_early else "no")

    def excluded(off):
        return any(lo <= off < hi for lo, hi in excl)

    com3_recs = [t for off, t in com3_all if not excluded(off) and t.startswith(RECORD_PREFIXES)]
    bb_recs = [t for _, t in bb_all if t.startswith(RECORD_PREFIXES)] if bb_all is not None else None
    if bb_recs is None:
        consistency = "n/a(no-blackbox)"
        texts = com3_recs
    elif bb_recs == com3_recs:
        consistency = "identical"
        texts = com3_recs
    elif (bb_recs and len(bb_recs) <= len(com3_recs) and bb_recs[:-1] == com3_recs[:len(bb_recs) - 1]
          and com3_recs[len(bb_recs) - 1].startswith(bb_recs[-1])):
        consistency = "bb-prefix"
        texts = com3_recs
    else:
        consistency = "differ"
        texts = bb_recs
    log("records_consistency", consistency)
    log("records_source", "blackbox" if texts is bb_recs and bb_recs is not None else "com3")
    # I32 (m4-design.md 14.16). D3 §8 item 11 asks that every STAMP and IPC line be
    # identical on COM3, CR-stripped, and that narrow comparison is what crit_1
    # gates on a board run. `records_consistency` compares every record-prefixed
    # line, which is broader than item 11; it stays a record, and D3 §7's row for
    # `differ` (flag it in the run note) applies to it (14.13).
    if bb_recs is None:
        stamp_ipc = "n/a(no-blackbox)"
    else:
        sb, sc = stamp_ipc_lines(bb_recs), stamp_ipc_lines(com3_recs)
        if not sb and not sc:
            stamp_ipc = "empty"
        else:
            stamp_ipc = "identical" if sb == sc else f"differ(bb:{len(sb)},com3:{len(sc)})"
    log("records_stamp_ipc", stamp_ipc)
    R = Records(texts)
    all_texts = [t for off, t in com3_all if not excluded(off)] + ([t for _, t in bb_all] if bb_all else [])
    # I30b: one ordered source for crit_1's orderings. `all_texts` concatenates
    # the capture and the black box, so a position in it spans two timelines and
    # only accidentally gives the right answer. The capture is the fuller one.
    # I32: unless a block's END marker is missing, which hides the rest of the
    # capture; then the black box, D3 §8's primary record, is read instead.
    order_src = [t for off, t in com3_all if not excluded(off)]
    order_from_bb = bool(bb_all) and (ended_early or not order_src)
    if order_from_bb:
        order_src = [t for _, t in bb_all]
    log("order_source", "blackbox" if order_from_bb else "com3")
    log("states", ",".join(R.states) or "none")
    log("fail_state", R.fail_state or "none")
    log("fails", ";".join(R.fails).replace(" ", "_") or "none")
    for k, v in R.mem.items():
        log(f"mem_{k}", v)
    for k, v in R.stops.items():
        log(f"stop_{k}", v)
    for k, v in R.kevfile.items():
        log(f"kevfile_{k}", v)
    for k, v in R.text.items():
        log(f"text_{k}", v)
    for w in ("p", "l0", "t"):
        tp = R.bwait_for("traceprinter", listing=w)
        cn = R.bwait_for("m4count", listing=w)
        if tp:
            log(f"tp_{w}", composite([("rc", tp["rc"]), ("killed", tp["killed"]), ("ms", tp["ms"])]))
        if cn:
            log(f"cnt_{w}", composite([("rc", cn["rc"]), ("killed", cn["killed"]), ("ms", cn["ms"])]))

    # The counter's records.
    for run in R.runs:
        if run["w"] == "fix":
            continue
        w = run["w"]
        for name, fields, _ in run["recs"]:
            f = {k: v for k, v in fields.items() if k != "w"}
            if name in ("BUF", "RATE"):
                log(f"cnt_{w}_{name.lower()}_cpu{f.get('cpu', '?')}", composite(f.items()))
            elif name == "STAT":
                log(f"cnt_{w}_stat_{f.get('class', '?')}", composite(f.items()))
            elif name == "STATUS":
                log(f"cnt_{w}_status_{f.get('value', '?')}", composite(f.items()))
            elif name == "FLT":
                log(f"cnt_{w}_flt_{f.get('form', '?')}", composite(f.items()))
            elif name in ("IN", "TIME64", "RING", "MARK", "VCPU", "OFFSET", "STATUSSUM", "TRIPLES", "PAIRS", "QVM",
                          "END", "WARN"):
                log(f"cnt_{w}_{name.lower()}", composite(f.items()))
            elif name == "PASS":
                log(f"cnt_{w}_pass", composite(f.items()))

    # Step 3's results.
    tcu_state = {}
    for name in sorted(blocks):
        status, info = blocks[name]
        log(f"flt_{name}", status)
        if info.get("body") is not None:
            log(f"flt_{name}_bytes", info["bytes"])
            log(f"flt_{name}_lines", info["lines"])
            try:
                write_bytes(os.path.join(a.out_dir, f"{a.run_id}-flt-{name}.txt"), info["body"])
            except Refused as e:
                print(f"parse-m4: refused: {e}", file=sys.stderr)
                return 2
        sums = R.tcu.get(name, [])
        if transport != "tcu":
            ts_ = "n/a(console)"
        elif len(sums) < 2:
            ts_ = "absent"
        else:
            body = sums[1]
            drops = to_int(body.get("drops"), -1)
            if to_int(body.get("aborted"), 0):
                ts_ = "aborted"
            elif to_int(body.get("deadline"), 0):
                ts_ = "deadline"
            elif drops != 0:
                ts_ = f"drops({drops})"
            elif to_int(body.get("rc"), -1) != 0:
                ts_ = f"rc({body.get('rc')})"
            else:
                ts_ = "clean"
            log(f"tcu_{name}_bytes_sent", body.get("bytes_sent", "?"))
            log(f"tcu_{name}_ms", body.get("ms", "?"))
        tcu_state[name] = ts_
        log(f"tcu_{name}", ts_)
    for name, why in R.flt_skip.items():
        log(f"flt_{name}_skip", why)

    # Step 4: the independent analysis of block v.
    run_main = R.run_for(main_w)
    flt_v_rec = next((f for f in rec_all(run_main, "FLT") if f.get("form") == "v"), None)
    flt_c_rec = next((f for f in rec_all(run_main, "FLT") if f.get("form") == "c"), None)
    v_status = blocks.get("v", ("absent", {}))[0]
    v_body = blocks.get("v", ("absent", {}))[1].get("body") if "v" in blocks else None
    v_capped = flt_v_rec is not None and flt_v_rec.get("capped") == "1"
    v_complete = flt_v_rec is not None and flt_v_rec.get("capped") == "0" and v_status == "ok"
    log("v_complete", "yes" if v_complete else "no")
    L = None
    pc_v_recs = []
    cmark = rec_first(run_main, "MARK")
    assume_end = None
    if v_capped and cmark and cmark.get("end_t", "-") not in ("-", ""):
        assume_end = int(cmark["end_t"], 16)
        log("xcheck_window", "counter-end-marker(v-capped)")
    if v_body is not None and v_status == "ok":
        L = Listing(start_marker, end_marker, e3_status0=e3, assume_end_t=assume_end).feed_bytes(v_body)
        # I30 (m4-design.md 14.9 item 3): kept for crit_3's confirmation, which
        # runs whether or not v is complete. `pc_first` below is scoped to the
        # v_complete branch, and a quiet call would leave QVM out.
        pc_v_recs = L.records(label="pc", quiet=False)
        for name, f in pc_v_recs:
            if name in ("TIME64", "RING", "MARK", "VCPU", "OFFSET", "STATUSSUM", "TRIPLES", "PAIRS"):
                log(f"pc_v_{name.lower()}", composite((k, v) for k, v in f.items() if k != "w"))
            elif name == "STAT":
                log(f"pc_v_stat_{f['class']}", composite((k, v) for k, v in f.items() if k != "w"))
            elif name == "STATUS":
                log(f"pc_v_status_{f['value']}", composite((k, v) for k, v in f.items() if k != "w"))

    # Step 5: the cross-checks.
    xs = "n/a(v-incomplete)"
    if v_complete and L is not None and run_main is not None:
        diffs = []
        pcrec = L.records(label="pc")

        def pc_first(name, key=None, val=None):
            for n, f in pcrec:
                if n == name and (key is None or f.get(key) == val):
                    return f
            return None
        compare = [("TRIPLES", None, ("in_window",)),
                   ("PAIRS", None, ("eligible", "clean", "pre", "blk", "mig", "intr_clean", "intr_pre",
                                    "intr_blk", "intr_mig")),
                   ("RING", None, ("state", "wrapped_cpus")),
                   ("MARK", None, ("start", "end", "start_t", "end_t"))]
        for name, _, fields in compare:
            t = rec_first(run_main, name) or {}
            p = pc_first(name) or {}
            for k in fields:
                if t.get(k) != p.get(k):
                    diffs.append(f"{name}.{k}")
        for cls in STAT_CLASSES:
            t = next((f for f in rec_all(run_main, "STAT") if f.get("class") == cls), {})
            p = pc_first("STAT", "class", cls) or {}
            for k in ("n", "p50_ticks", "p99_ticks", "max_ticks", "p50_ns", "p99_ns", "max_ns", "quantum_ns",
                      "p99_quotable"):
                if t.get(k) != p.get(k):
                    diffs.append(f"STAT.{cls}.{k}")
        # 14.7: the in-window part of the GUEST_EXIT status records.
        diffs += status_window_diffs(rec_all(run_main, "STATUS"), rec_first(run_main, "STATUSSUM"),
                                     [f for n, f in pcrec if n == "STATUS"], pc_first("STATUSSUM"))
        xs = "match" if not diffs else "differ(" + "+".join(diffs[:20]) + ")"
    log("xcheck_stats", xs)

    c_status = blocks.get("c", ("absent", {}))[0]
    c_body = blocks.get("c", ("absent", {}))[1].get("body") if "c" in blocks else None
    c_lines = {}
    c_stat = "n/a(no-c)"
    pc_from_c = {}
    if c_body is not None and c_status == "ok":
        vals = {cls: [] for cls in CLASSES}
        c_lines, c_rows = compact_rows(c_body)
        for cls, elig, dwell, _cx, _ce in c_rows:
            if elig == "1" and cls in vals and to_int(dwell) is not None:
                vals[cls].append(int(dwell))
        cps_c = to_int((rec_first(run_main, "IN") or {}).get("cps"), DEFAULT_CPS)
        diffs = []
        for cls in STAT_CLASSES:
            pool = sorted(sum((vals[x] for x in (("clean", "pre", "mig") if cls == "nonblk" else (cls,))), []))
            n = len(pool)
            got = {"n": str(n)}
            if n:
                got.update(p50_ticks=str(pool[rank(50, n) - 1]), p99_ticks=str(pool[rank(99, n) - 1]),
                           max_ticks=str(pool[-1]))
            else:
                got.update(p50_ticks="-", p99_ticks="-", max_ticks="-")
            pc_from_c[cls] = (pool, cps_c)
            t = next((f for f in rec_all(run_main, "STAT") if f.get("class") == cls), {})
            for k in ("n", "p50_ticks", "p99_ticks", "max_ticks"):
                if t.get(k) != got[k]:
                    diffs.append(f"{cls}.{k}")
        if flt_c_rec is not None and flt_c_rec.get("capped") == "1":
            c_stat = "partial(capped)"
        else:
            c_stat = "match" if not diffs else "differ(" + "+".join(diffs) + ")"
    log("c_stats", c_stat)

    xp = "n/a(no-v-or-c)"
    if L is not None and c_body is not None and c_status == "ok" and L.window_known:
        last_t = None
        if flt_v_rec is not None and flt_v_rec.get("last_t", "-") not in ("-", ""):
            last_t = int(flt_v_rec["last_t"], 16)
        limit = L.end_t if last_t is None else min(L.end_t, last_t)
        c_capped = flt_c_rec is not None and flt_c_rec.get("capped") == "1"

        xp = xcheck_pairs_record(L, c_lines, limit, c_capped)
    log("xcheck_pairs", xp)

    p1zero = []
    qv = rec_first(run_main, "QVM") or {}
    ring_t = (rec_first(run_main, "RING") or {}).get("state")
    for key, idname in (("enter", "id0"), ("exit", "id1"), ("cycles", "id7")):
        if to_int(qv.get(key), -1) == 0:
            ok = v_complete and ring_t == "held" and L is not None and L.q[key] == 0
            p1zero.append(f"{idname}:{'yes' if ok else 'no'}")
    log("p1_zero_verified", ",".join(p1zero) or "n/a(no-zero)")

    # I33 (m4-design.md 14.17): a linear window's .kev against the budget its -S was
    # sized from (§2.4 step 3). A linear capture that reaches -S is cut (R38,
    # untested), so a file within the 4 MiB margin of -S has outgrown its budget.
    kev_budget = None
    if params.get("kind") == "linear":
        s_lin = to_int(params.get("s_mb"))
        kb = to_int((R.kevfile_f.get("t") or {}).get("bytes"))
        if s_lin is None or s_lin <= LIN_S_MARGIN_MB:
            kev_budget = "unknown"
        elif kb is None:
            kev_budget = "no-kev"
        else:
            kev_budget = "within" if kb < (s_lin - LIN_S_MARGIN_MB) * MIB else "over"
        log("kevfile_t_budget", composite([("kind", "linear"), ("bytes", "-" if kb is None else kb),
                                            ("budget_mb", "-" if s_lin is None else s_lin - LIN_S_MARGIN_MB),
                                            ("state", kev_budget)]))

    # Step 6: the verdict.
    crits = []

    def crit(key, ok, why="", na=None):
        if na:
            crits.append((key, f"n/a({na})"))
        else:
            crits.append((key, "pass" if ok else ("fail(" + why + ")" if why else "fail")))

    def has(sub):
        return any(sub in t for t in all_texts)

    def pcv_first(name):
        """The PC's own record for the delivered block, capped or not (I30)."""
        for n, f in pc_v_recs:
            if n == name:
                return f
        return None

    board = not a.rehearsal
    guard = params.get("guard_s", "?")

    def landing_ok():
        missing = []
        for tok in ("T234-SHIM EL=2", "Enabling EL2 host hypervisor support (VHE)",
                    f"t234: all {p_cpus} cpus parked in smp_spin", "Starting next program",
                    f"T234 M4 {rung} -P{p_cpus}: procnto up", f"BWAIT guard armed secs={guard}",
                    "SMPCHECK census hyp qtime_intr=28 hypinfo_flags=0x1", "SMPCHECK census tick=ok",
                    "SMPCHECK CENSUS PASS"):
            if not has(tok):
                missing.append(tok.split(" ")[0])
        if not any(t.startswith("JUMP") for t in all_texts):
            missing.append("JUMP")
        for n in range(p_cpus):
            hcr = None
            for t in all_texts:
                m = re.search(rf"t234: cpu {n} el2-host EL2 HCR_EL2=(?:0x)?([0-9a-fA-F]+)", t)
                if m:
                    hcr = int(m.group(1), 16)
                    break
            if hcr is None or not (hcr >> 34) & 1 or not (hcr >> 27) & 1:
                missing.append(f"hcr{n}")
            if not has(f"t234: hvtimer cpu {n} verdict=wired"):
                missing.append(f"hvtimer{n}")
        return missing

    def neg_hits():
        src = [t for _, t in bb_all] if bb_all is not None else [t for off, t in com3_all if not excluded(off)]
        # The counter's fixture records carry wrapped rings and order violations on purpose (§4.5.9).
        src = [t for t in src if not (t.startswith("M4C ") and " w=fix " in t + " ")]
        # Under TCG the host boots through QNX's startup-qemu-virt, which prints "** CPU <n> PE is not awake"
        # on every boot: the canonical QHV host and every 7b attempt show it, and no board capture does. The
        # token stays negative on the board, where only our startup could print it (m4-design.md 14.5, I21).
        if a.com3_format == "qemu-serial":
            rx_awake = re.compile(r"^\*\* CPU [0-9]+ PE is not awake$")
            before = len(src)
            src = [t for t in src if not rx_awake.match(t)]
            log("neg_tcg_startup_ignored", before - len(src))
        hits = []
        allowed = {"state=wrapped"} if variant == "k16" else set()
        for tok in NEG_FIXED:
            if tok in allowed:
                continue
            if any(tok in t for t in src):
                hits.append(tok)
        for pat in NEG_PATTERNS:
            rx = re.compile(pat)
            if any(rx.search(t) for t in src):
                hits.append(pat)
        return hits

    order_trace = ["config", "preflight", "rate_pre", "integrity_pre", "clock", "fixtures", "disk", "probe", "l0",
                   "teardown", "release", "rate_post", "format", "summary", "send", "diag", "end"]
    order_full = ["config", "preflight", "rate_pre", "integrity_pre", "disk", "hostcheck", "window", "report", "ipc",
                  "report_ipc", "teardown", "integrity_post", "release", "rate_post", "format", "summary", "send",
                  "diag", "end"]

    def states_in_order(expected):
        pos = -1
        for s in R.states:
            if s in expected:
                i = expected.index(s)
                if i < pos:
                    return False
                pos = i
        return bool(R.states) and R.states[-1] == "end"

    def counter_ok(run, *, window_marks=True, held=True, kept_max=None, gaps0=True, mismatch0=True):
        why = []
        if run is None:
            return ["no-counter-run"]
        mk = rec_first(run, "MARK") or {}
        if window_marks and not (mk.get("start") == "found" and mk.get("end") == "found"):
            why.append("markers")
        if held and (rec_first(run, "RING") or {}).get("state") != "held":
            why.append("ring")
        for b in rec_all(run, "BUF"):
            if kept_max is not None and to_int(b.get("kept"), 10 ** 9) > kept_max:
                why.append(f"kept{b.get('cpu')}")
            if gaps0 and b.get("gaps") != "0":
                why.append(f"gaps{b.get('cpu')}")
        if mismatch0 and (rec_first(run, "TIME64") or {}).get("mismatches") != "0":
            why.append("mismatches")
        return why

    fixtures_dir = a.fixtures or os.path.join(HERE, "fixtures")

    if rung == "r0":
        crit("crit_1", not (miss := landing_ok()), "+".join(miss[:8]) if board else "", None if board else "tcg")
        crit("crit_2", states_in_order(order_trace) and R.fail_state == "none",
             f"states-or-fail_state:{R.fail_state}")
        verdicts = [v.get("result") for v in R.clk]
        crit("crit_3", len(verdicts) == 3 and all(v in ("agree", "agree-within-resolution") for v in verdicts),
             "clk:" + ",".join(str(v) for v in verdicts))
        fx_runs = fixture_runs_from_lines(texts)
        fx_bad = []
        # I24 (m4-design.md 14.5): expect the fixtures this image carried. Images built before I24 have no
        # fixtures key and shipped m4fix-1 to m4fix-3; m4fix-4 (I22) is expected only where it was shipped.
        fx_names = [n for n in params.get("fixtures", "").split(",") if n] or \
            ["m4fix-1.txt", "m4fix-2.txt", "m4fix-3.txt"]
        log("fixtures_expected", ",".join(fx_names))
        for fname in fx_names:
            try:
                exp = fixture_expects(os.path.join(fixtures_dir, fname))
            except InputError:
                fx_bad.append(f"{fname}:no-fixture")
                continue
            got = fx_runs.get(fname)
            if got is None:
                fx_bad.append(f"{fname}:absent")
            elif check_expects(got, exp):
                fx_bad.append(f"{fname}:differ")
        crit("crit_4", not fx_bad, "+".join(fx_bad))
        run_p = R.run_for("p")
        why5 = ([] if R.stops.get("p") == "stop" else ["stop"]) + counter_ok(run_p, kept_max=65)
        crit("crit_5", not why5, "+".join(why5))
        crit("crit_6", all(k in R.mem for k in ("probe_pre", "probe_armed", "probe_stopped")), "mem-lines")
        run_l0 = R.run_for("l0")
        why7 = ([] if R.stops.get("l0") == "self" else ["stop"]) + counter_ok(run_l0, held=False, mismatch0=False)
        cpus_seen = {b.get("cpu") for b in rec_all(run_l0, "BUF")}
        if not all(str(c) in cpus_seen for c in range(p_cpus)):
            why7.append("buf-cpus")
        if not rec_all(run_l0, "RATE"):
            why7.append("rate")
        crit("crit_7", not why7, "+".join(why7))
        tp = R.bwait_for("traceprinter", listing="l0")
        cn = R.bwait_for("m4count", listing="l0")
        crit("crit_8", tp is not None and cn is not None and tp["killed"] == 0 and cn["killed"] == 0, "bwait")
        why9 = []
        if "v" not in R.flt_begin:
            why9.append("begin")
        if blocks.get("v", ("absent",))[0] != "ok":
            why9.append("flt_v")
        if transport == "tcu" and tcu_state.get("v") != "clean":
            why9.append("tcu_v")
        crit("crit_9", not why9, "+".join(why9))
    else:
        why1 = []
        if board:
            why1 += landing_ok()
            why1 += startup_order_bad(order_src, p_cpus)
        cfg_rung = R.config.get("rung")
        if cfg_rung != rung and not (a.rehearsal and cfg_rung in (f"tcg-{variant}", rung)):
            why1.append("config-rung")
        if R.config.get("mode") != "full":
            why1.append("config-mode")
        # I30b (m4-design.md 14.9 item 3, D3 §8 items 3 and 6). These are the
        # board run's own evidence, so they are asked of a board run only: the
        # §11 rehearsal's record is built by `synth-com3`, whose invented
        # `M4 CONFIG` line carries `synthetic=1` and none of these fields, and
        # whose console stamps no guest phase. Asking there would fail the
        # rehearsal for being a rehearsal.
        if board:
            # rung and mode were the whole of it. The image records its own
            # build in `M4 CONFIG`, and the PC holds the `.params` it sized that
            # image with, so the two are compared field by field: an image built
            # from other parameters than the ones this parse assumes is a
            # failure rather than a silent mismatch. The generator enforces
            # these at build time; this is the run's evidence that the image on
            # the board is that image.
            for ck, pk in (("cpus", "p"), ("kind", "kind"), ("iters", "iters"), ("forms", "forms"),
                           ("transport", "transport"), ("trace_need_mb", "trace_need_mb"), ("tl_args", "tl_args")):
                want = params.get(pk)
                if want is not None and R.config.get(ck) != want:
                    why1.append(f"config-{ck}")
            # The fields no params file carries: they must at least be recorded,
            # so the startup line, the -Q mode, the -W policy and the four
            # sha256s are in the record the run leaves behind (item 3).
            for ck in ("startup", "q", "w", "A", "cpus", "guest_sha256", "disk_sha256", "conf_sha256",
                       "client_sha256", "clock"):
                if not R.config.get(ck):
                    why1.append(f"config-{ck}-absent")
            # Item 6, the guest's phases. `g_srv` is recorded and never gated,
            # which item 6 states outright: the guest starts the server in the
            # background and one TCG run lost the line to interleaving while its
            # IPC completed cleanly. Item 8 is the evidence the server was up.
            why1 += guest_phase_bad(R.stamps)
        for c in ("md5_pre guest", "md5_pre disk", "md5_pre conf", "disk_copy", "md5_post guest", "md5_post disk"):
            if c not in R.checks:
                why1.append(c.replace(" ", "_"))
        if not has("BWAIT path hit=/dev/qvmdisk0"):
            why1.append("qvmdisk0")
        ql, bn = R.stamps.get("qvm_launch"), R.stamps.get("banner")
        if ql is None or bn is None or bn <= ql:
            why1.append("stamps")
        # I32: the banner is no longer searched over every text; run_lines_bad
        # reads it in the guest stream `diag` prints (D3 §8 item 5). The client's
        # bwait line must also show no signal (item 8).
        client = R.bwait_for("qnx-host-client")
        # I40 (m4-design.md 14.25): a recovered iteration yields no sample, warm-up
        # or timed (client.c:342-345, :376), and sentinel_recoveries counts both, so
        # D3 §8 item 8's samples + recoveries = iters misfires when a stall hits a
        # warm-up iteration (the §11 lin rehearsal did). The timed run completed when
        # samples <= iters <= samples + recoveries <= iters + the host script's warm-up.
        if (client is None or client["rc"] != 0 or client["sig"] != 0 or client["killed"] != 0
                or R.samples is None or R.sentinel is None
                or not (R.samples <= iters <= R.samples + R.sentinel <= iters + IPC_WARMUP)):
            why1.append("ipc")
        why1 += run_lines_bad(order_src, rung=rung, p_cpus=p_cpus, board=board,
                              cps_want=BOARD_CPS if board else None)
        if board:
            # I32: item 3's values, not only their presence, and item 11's narrow
            # comparison of the STAMP and IPC lines across the two records.
            why1 += config_exact_bad(R.config, p_cpus)
            if stamp_ipc != "identical":
                why1.append("stamp-ipc:" + stamp_ipc.split("(")[0])
        if "banner" not in R.mem:
            why1.append("mem_banner")
        if not states_in_order(order_full) or R.fail_state != "none":
            why1.append("states")
        # I30b: the order walk only positions the states that are present, so a
        # run that skipped one entirely still passed. Every state of the rung's
        # sequence has to appear.
        missing_states = [s for s in order_full if s not in R.states]
        if missing_states:
            why1.append("states-missing:" + ",".join(missing_states[:4]))
        crit("crit_1", not why1, "+".join(why1[:12]))
        why2 = []
        if not R.trace_arm:
            why2.append("arm")
        else:
            # I33 (m4-design.md 14.17): the arm line was a presence test. What was
            # armed must be what the image was sized for, and the file it names
            # must be the one formatted afterwards.
            arm = R.trace_arm_f
            if params.get("kind") and arm.get("kind") != params["kind"]:
                why2.append("arm-kind")
            if params.get("tl_args") and arm.get("args") != params["tl_args"]:
                why2.append("arm-args")
            if arm.get("file") != KEV_T:
                why2.append("arm-file")
        if R.stops.get("t") != "stop":
            why2.append("stop")
        if to_int(R.kevfile.get("t"), 0) <= 0:
            why2.append("kevfile")
        elif (R.kevfile_f.get("t") or {}).get("path") != KEV_T:
            why2.append("kevfile-path")
        if kev_budget is not None and kev_budget != "within":
            why2.append("kevfile-over-budget" if kev_budget == "over" else f"kevfile-budget-{kev_budget}")
        # I30: presence was the whole test. Both markers and the stop now have
        # to have returned 0, read from trcctl's own lines.
        why2 += trcctl_bad(R.trcctl, (start_marker, end_marker))
        crit("crit_2", not why2, "+".join(why2))
        if variant == "k16":
            why3 = []
            ring = rec_first(run_main, "RING") or {}
            if ring.get("state") != "wrapped" or ring.get("wrapped_cpus") in (None, "none"):
                why3.append("ring")
            if (rec_first(run_main, "PAIRS") or {}).get("eligible") != "0":
                why3.append("eligible")
            pc_wrapped = (",".join(str(c) for c, r in enumerate(L.cpu) if r["events"] and r["wrapped"]) or "none") \
                if L is not None else None
            if L is None or L.ring != ring.get("state") or pc_wrapped != ring.get("wrapped_cpus") \
                    or str(L.p_reason["eligible"]) != (rec_first(run_main, "PAIRS") or {}).get("eligible"):
                why3.append("pc-agree")
            if (rec_first(run_main, "END") or {}).get("rc") != "0":
                why3.append("end")
            crit("crit_k16", not why3, "+".join(why3))
        else:
            why3 = []
            if not all(to_int(qv.get(k), 0) > 0 for k in ("enter", "exit", "cycles")):
                why3.append("qvm-ids")
            if (rec_first(run_main, "VCPU") or {}).get("threads") != "1":
                why3.append("vcpu")
            if (rec_first(run_main, "OFFSET") or {}).get("distinct") != "1":
                why3.append("offset")
            if (rec_first(run_main, "TRIPLES") or {}).get("order_violated") != "0":
                why3.append("order")
            if (rec_first(run_main, "TIME64") or {}).get("mismatches") != "0":
                why3.append("mismatches")
            # I30 (m4-design.md 14.9 item 3). Two gaps: TIME64's mismatch check
            # passes a listing that carries no TIME event at all, and P1 rested
            # on the counter's own assertion. §2.2 item 3 reads as P1 "on the
            # board", and D2's premise is that the PC checks the counter without
            # trusting it, so the PC's reading of the delivered block has to
            # agree. Only properties a capped block can support are checked:
            # counts over the whole listing could not match and are not asked.
            if to_int((rec_first(run_main, "TIME64") or {}).get("time_events"), 0) <= 0:
                why3.append("time_events")
            if L is None:
                why3.append("pc-absent")
            else:
                pcq = pcv_first("QVM") or {}
                if not all(to_int(pcq.get(k), 0) > 0 for k in ("enter", "exit", "cycles")):
                    why3.append("pc-qvm-ids")
                if (pcv_first("VCPU") or {}).get("threads") != "1":
                    why3.append("pc-vcpu")
                if (pcv_first("OFFSET") or {}).get("distinct") != "1":
                    why3.append("pc-offset")
                if (pcv_first("TRIPLES") or {}).get("order_violated") != "0":
                    why3.append("pc-order")
                if (pcv_first("TIME64") or {}).get("mismatches") != "0":
                    why3.append("pc-mismatches")
                # I34 (m4-design.md 14.18): the PC's own complete triples and TIME
                # events, as the counter's are asked for. A mismatch count of zero
                # over no TIME event confirms nothing, on either side.
                if to_int((pcv_first("TRIPLES") or {}).get("complete"), 0) <= 0:
                    why3.append("pc-triples")
                if to_int((pcv_first("TIME64") or {}).get("time_events"), 0) <= 0:
                    why3.append("pc-time_events")
            crit("crit_3", not why3, "+".join(why3))
            crit("crit_4", ring_t == "held", f"ring:{ring_t}")
            why5 = []
            if not xp.startswith("match"):
                # I28: "empty compared=0" lands here too. A comparison of
                # nothing used to read as a match and pass.
                why5.append("xcheck_pairs")
            if v_complete and xs != "match":
                why5.append("xcheck_stats")
            # I28: the compact block's own recount was computed, logged, and
            # gated by nothing, although section 9 treats c_stats=differ as a
            # stop before r2.
            if c_stat.startswith("differ"):
                why5.append("c_stats")
            crit("crit_5", not why5, "+".join(why5))
            why6 = []
            for b in ("v", "c"):
                if blocks.get(b, ("absent",))[0] != "ok":
                    why6.append(f"flt_{b}")
                if transport == "tcu" and tcu_state.get(b) != "clean":
                    why6.append(f"tcu_{b}")
            if (rec_first(run_main, "END") or {}).get("rc") != "0":
                why6.append("end")
            crit("crit_6", not why6, "+".join(why6))
            if rung == "r2":
                clean_n = to_int((rec_first(run_main, "PAIRS") or {}).get("clean"), 0)
                crit("crit_p2", clean_n >= 1000, f"eligible_clean:{clean_n}")
                crit("crit_p3", all(blocks.get(b, ("absent",))[0] == "ok" for b in ("c", "v")), "blocks")
    if board:
        crit("crit_reset", (a.reset_reason or "").strip() == "MAINSWRST", f"reset:{a.reset_reason or 'unknown'}")
        # I34 (m4-design.md 14.18): the size gate, and the board's own sha256 of
        # its black box against the copy this parse read.
        crit("crit_bb", bb is not None and len(bb) < BB_GATE and bb_sha == "equal",
             f"blackbox:{'none' if bb is None else len(bb)}+sha:{bb_sha.split('(')[0]}")
    else:
        crit("crit_reset", True, na="tcg")
        crit("crit_bb", True, na="tcg")
    hits = neg_hits()
    crit("crit_neg", not hits, "+".join(h.replace(" ", "_") for h in hits[:10]))
    for k, s in crits:
        log(k, s)
    failed = [k for k, s in crits if s.startswith("fail")]
    verdict = "pass" if not failed else "fail(" + ",".join(failed) + ")"
    log("run_verdict", verdict)

    # Step 7: the CSV (§6.4).
    csv_note = "skipped(not-a-t-run)"
    if is_t or a.rehearsal:
        stat = next((f for f in rec_all(run_main, "STAT") if f.get("class") == "clean"), None)
        samples = to_int(stat.get("n"), 0) if stat else 0
        cps_list = to_int((rec_first(run_main, "IN") or {}).get("cps"), DEFAULT_CPS)
        p2p3 = all(s == "pass" for k, s in crits if k in ("crit_p2", "crit_p3")) if not a.rehearsal else \
            blocks.get("c", ("absent",))[0] == "ok"
        # I39 (m4-design.md 6.4, 14.23): unix_ts is the run's end. The harness parses
        # while the capture still runs, so a harness parse never sees the capture's
        # end line; it passes the PC clock at its return instead. A file's mtime is
        # not a defined source on a board run and is kept for a rehearsal only.
        ts_, ts_src = None, "none"
        if getattr(a, "run_end_epoch", None) is not None:
            ts_, ts_src = a.run_end_epoch, "run-end-epoch"
        elif iso_epoch(cap.get("end_iso")) is not None:
            ts_, ts_src = iso_epoch(cap.get("end_iso")), "capture-end-line"
        elif a.rehearsal:
            ts_, ts_src = int(os.path.getmtime(a.com3)), "com3-mtime(rehearsal)"
        if samples <= 0:
            csv_note = "skipped(no-samples)"
        elif not p2p3:
            csv_note = "skipped(p2-or-p3)"
        elif not a.rehearsal and cps_list != BOARD_CPS:
            csv_note = f"refused(cps:{cps_list})"
        elif ts_ is None:
            csv_note = "refused(no-timestamp)"
        else:
            log("csv_ts_source", ts_src)
            if c_stat == "match":
                pool, cps_c = pc_from_c["clean"]
                n = len(pool)
                p50, p99, mx = (ticks_ns(pool[rank(50, n) - 1], cps_c), ticks_ns(pool[rank(99, n) - 1], cps_c),
                                ticks_ns(pool[-1], cps_c))
                log("csv_source", "pc-recount-of-c")
            else:
                p50, p99, mx = stat.get("p50_ns"), stat.get("p99_ns"), stat.get("max_ns")
                log("csv_source", "target")
            if a.rehearsal:
                notes = "m4-tcg-rehearsal;emulated;not-a-result"
                cps_out = cps_list
            else:
                notes = f"orin-native-el2host-qvm-class10-dwell;clock={R.config.get('clock', 'unverified')}"
                if samples < QUOTABLE_N:
                    notes += ";p99=low-n"
                cps_out = BOARD_CPS
            row = f"{ts_},{samples},0,{p50},{p99},{mx},{cps_out},{notes}"
            ledger = os.path.join(a.out_dir, "csv-rows.log")
            done = set()
            if os.path.exists(ledger):
                for raw in iter_raw_lines(read_bytes(ledger)):
                    done.add(raw.decode("latin-1").split(" ")[0])
            if a.run_id in done:
                csv_note = "refused(duplicate-run-id)"
            else:
                try:
                    check_out_path(csv_path)
                    check_out_path(ledger)
                    old = read_bytes(csv_path) if os.path.exists(csv_path) else b""
                    if old and not old.endswith(b"\n"):
                        old += b"\n"
                    write_bytes(csv_path, old + (row + "\n").encode())
                    prev = read_bytes(ledger) if os.path.exists(ledger) else b""
                    write_bytes(ledger, prev + f"{a.run_id} {rel_repo(csv_path)}\n".encode())
                    csv_note = "written"
                    log("csv_row", row)
                except Refused as e:
                    print(f"parse-m4: refused: {e}", file=sys.stderr)
                    return 2
    log("csv", csv_note)

    try:
        write_text(parse_log, log.text())
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    print(redact(f"M4PC run_verdict={verdict}"))
    print(redact(f"M4PC parse_log={rel_repo(parse_log)}"))
    return 0


# ------------------------------------------------------------------ sizing (§2.4)

def read_parse_log(path):
    d = {}
    for raw in iter_raw_lines(read_bytes(path)):
        line = raw.decode("latin-1").rstrip("\r\n")
        if line.startswith("M4PC "):
            k, _, v = line[5:].partition("=")
            d.setdefault(k, v)
    return d


def ring_mb(k):
    return math.ceil(k * 16 * 4 / 1024)


def s_mb(k):
    return ring_mb(k) + 4


def trace_need_mb(k, probe_cost_mb):
    cost = max(ring_mb(k), math.ceil(probe_cost_mb * k / 64))
    return cost + s_mb(k) + 32


TL_K_DEFAULT = 8   # tracelogger's usage message: -k defaults to 8 kernel buffers per CPU


def trace_need_mb_lin(s, probe_cost_mb):
    # I26: a linear capture (-c -S, no -k) keeps the default kernel buffers, fewer than r0's 64-buffer
    # probe, so the probe's cost bounds it; the file itself grows to -S.
    cost = max(ring_mb(TL_K_DEFAULT), math.ceil(probe_cost_mb))
    return cost + s + 32


BUF_KB = 16                 # [use-tl]: about 16 KB per kernel buffer (§2.4 step 3)
LIN_S_MARGIN_MB = 4         # -S is the budgeted file plus 4 MiB, as a ring's is (§2.4 step 3, §4.2)
P_BOARD = 4                 # the board image's -P4
TEXT_PER_KEV = 5            # budget: text listing bytes per .kev byte (§2.4 step 5, §8.2)
MEM_WINDOW_MB = 992         # -m992M: a memory need at or above it can never pass its gate


def lin_s_mb(bufs_total):
    """I37 (m4-design.md 2.4 step 3, 14.21): a linear window's -S from the buffers its
    budget allows, summed over the CPUs, plus the ring's 4 MiB margin."""
    return math.ceil(bufs_total * BUF_KB / 1024) + LIN_S_MARGIN_MB


def fmt_need_mb(s, cap_v, cap_c):
    return 5 * s + CNT_MB + math.ceil((cap_v + cap_c) / MIB) + 32


def cnt_need_mb(cap_v, cap_c):
    return CNT_MB + math.ceil((cap_v + cap_c) / MIB) + 32


def ksh_worst_full(banner, ipc, tp, cnt, send_v, send_c):
    return 736 + banner + ipc + tp + cnt + send_v + send_c


def guard_for(worst):
    return math.ceil((worst + 125 + 240) / 300) * 300


def send_s(cap, bps):
    return math.ceil(cap / max(0.5 * bps, 2000)) + 15


def size_lines(values):
    order = ["image", "rung", "mode", "p", "kind", "k", "s_mb", "tl_args", "tl_bound", "trace_need_mb", "fmt_need_mb",
             "cnt_need_mb", "iters", "ipc_bound", "banner_bound", "grace", "tp_bound", "cnt_bound", "hash_bound",
             "forms", "cap_v", "cap_c", "send_v", "send_c", "send_t_v", "send_t_c", "clean_pred", "p2_reachable",
             "p99_reachable", "accept_low_n", "ksh_worst_s", "guard_s", "return_bound_s", "capture_s"]
    out = ["# M4 size file (m4-design.md §2.4), written by orin-native/m4/parse-m4.py; git-ignored,",
           "# evaluation-derived values under NC QDL v7 4.6(i). make-m4-images.sh --from-size reads it."]
    for k in order:
        out.append(f"{k}={values[k]}")
    for k in sorted(values):
        if k not in order:
            out.append(f"{k}={values[k]}")
    return "\n".join(out) + "\n"


def num(d, key):
    v = d.get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        raise InputError(f"the parse log has no numeric {key} (value {v!r})")


def size_r1_values(r0):
    """§2.4 from r0 to r1 over an r0 parse log's M4PC keys: (rc, values, message).
    rc 3 is a rule that goes to the owner; InputError is a log that cannot be sized from.
    A pure function, so selftest checks the rule against hand-computed values (I37)."""
    if r0.get("rung") != "r0":
        raise InputError(f"not an r0 parse log (rung={r0.get('rung')})")
    if r0.get("run_verdict") != "pass":
        return 3, None, f"SIZE r1 refused: r0 did not pass ({r0.get('run_verdict')}); the owner reviews r0 first"
    cps = to_int(parse_composite(r0.get("cnt_l0_in")).get("cps"), DEFAULT_CPS)
    rate = {}
    for key, val in r0.items():
        m = re.match(r"cnt_l0_rate_cpu(\d+)$", key)
        if not m:
            continue
        f = parse_composite(val)
        span = to_int(f.get("span_ticks"))
        bufs = to_int(f.get("bufs_in_window"), 0)
        if span:
            rate[int(m.group(1))] = (bufs + 1) / (span / cps)
    b0 = max(rate.values(), default=0.0)
    if b0 <= 0:
        raise InputError("no L0 RATE records with a span")
    # Whole MiB: the MEM lines are whole MB, and the generator recomputes the rule in integers (I37).
    probe_cost = max(0, math.ceil(num(r0, "mem_probe_pre") - num(r0, "mem_probe_armed")))
    tp0 = parse_composite(r0.get("tp_l0"))
    cn0 = parse_composite(r0.get("cnt_l0"))
    tp_bps0 = num(r0, "kevfile_l0") / max(to_int(tp0.get("ms"), 1), 1) * 1000
    cnt_bps0 = num(r0, "text_l0") / max(to_int(cn0.get("ms"), 1), 1) * 1000
    tcu_bps0 = num(r0, "tcu_v_bytes_sent") / max(num(r0, "tcu_v_ms"), 1) * 1000
    if min(tp_bps0, cnt_bps0, tcu_bps0) <= 0:
        raise InputError("a zero traceprinter, counter or tcu rate")
    need1 = math.ceil(16 * b0 * 60) + 2
    k1 = 256 if need1 <= 256 else (512 if need1 <= 512 else "lin")
    # I37 (§2.4 step 3, 14.21): a linear window's file holds every buffer every CPU writes, so its
    # budget is a sum over the CPUs; a CPU with no RATE record takes the busiest CPU's rate.
    bufs_lin = sum(math.ceil(16 * rate.get(c, b0) * 60) + 2 for c in range(P_BOARD))

    def s_for(k):
        return lin_s_mb(bufs_lin) if k == "lin" else s_mb(k)

    while 4 * s_for(k1) * MIB / tp_bps0 > 600:
        if k1 == 512:
            k1 = 256
            continue
        return 3, None, f"SIZE r1 owner: traceprinter would need more than 600 s at K={k1} (raise TP_BOUND; §2.4 step 4)"
    s = s_for(k1)
    cnt_bound = 120 if 4 * TEXT_PER_KEV * s * MIB / cnt_bps0 <= 120 else 300
    cap_v, cap_c = 1048576, 524288
    while True:
        send_v, send_c = send_s(cap_v, tcu_bps0), send_s(cap_c, tcu_bps0)
        if send_v > 600 and cap_v > 65536:
            cap_v //= 2
            continue
        if send_c > 600 and cap_c > 65536:
            cap_c //= 2
            continue
        if send_v > 600 or send_c > 600:
            return 3, None, "SIZE r1 owner: a block cannot be sent within 600 s at the 65,536 B floor (§2.4 step 6)"
        worst = ksh_worst_full(240, 240, 600, cnt_bound, send_v, send_c)
        guard = guard_for(worst)
        if guard <= 2700:
            break
        if cap_v <= 65536 and cap_c <= 65536:
            return 3, None, f"SIZE r1 owner: the guard {guard} s exceeds 2,700 s at the cap floor (§2.4 step 7)"
        cap_v, cap_c = max(65536, cap_v // 2), max(65536, cap_c // 2)
    trace_need = trace_need_mb_lin(s, probe_cost) if k1 == "lin" else trace_need_mb(k1, probe_cost)
    fmt_need = fmt_need_mb(s, cap_v, cap_c)
    if trace_need >= MEM_WINDOW_MB or fmt_need >= MEM_WINDOW_MB:
        return 3, None, (f"SIZE r1 owner: trace_need_mb={trace_need} or fmt_need_mb={fmt_need} is not below "
                         f"{MEM_WINDOW_MB} MiB and can never pass its gate (§2.4 step 5, I37)")
    ipc = 240
    values = {
        "image": f"m4-r1-{'lin' if k1 == 'lin' else 'k%d' % k1}", "rung": "r1", "mode": "full", "p": P_BOARD,
        "kind": "linear" if k1 == "lin" else "ring", "k": k1, "s_mb": s,
        "tl_args": f"-c -S {s}M" if k1 == "lin" else f"-r -k {k1} -M -S {s}M",
        "tl_bound": 2 + ipc + 5 + 160 + 30,
        "trace_need_mb": trace_need,
        "fmt_need_mb": fmt_need, "cnt_need_mb": cnt_need_mb(cap_v, cap_c),
        "iters": 15, "ipc_bound": ipc, "banner_bound": 240, "grace": 90, "tp_bound": 600, "cnt_bound": cnt_bound,
        "hash_bound": 20, "forms": "v c", "cap_v": cap_v, "cap_c": cap_c, "send_v": send_v, "send_c": send_c,
        "send_t_v": send_v - 5, "send_t_c": send_c - 5, "clean_pred": "-", "p2_reachable": "-",
        "p99_reachable": "-", "accept_low_n": "-", "ksh_worst_s": worst, "guard_s": guard,
        "return_bound_s": guard + 300, "capture_s": guard + 3300,
        "size_b0": f"{b0:.3f}", "size_need1": need1,
        "size_probe_cost_mb": probe_cost, "size_lin_bufs": bufs_lin if k1 == "lin" else "-",
        "size_tp_bps0": f"{tp_bps0:.0f}", "size_cnt_bps0": f"{cnt_bps0:.0f}", "size_tcu_bps0": f"{tcu_bps0:.0f}"}
    return 0, values, ""


def cmd_size_r1(a):
    try:
        rc, values, msg = size_r1_values(read_parse_log(a.r0_parse))
    except InputError as e:
        print(f"parse-m4: input error: {a.r0_parse}: {e}", file=sys.stderr)
        return 1
    if rc:
        print(msg)
        return rc
    values["size_from_r0_parse_sha256"] = sha256_file(a.r0_parse)
    out = a.out or os.path.join(REPO, "orin-native", "shim", "out", "m4", values["image"] + ".size")
    try:
        write_text(out, size_lines(values))
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    for k in ("image", "k", "s_mb", "cnt_bound", "cap_v", "cap_c", "send_v", "send_c", "guard_s", "capture_s"):
        print(f"SIZE {k}={values[k]}")
    print(f"SIZE file={rel_repo(out)}")
    print(f"SIZE next: BSP=... QNX_BASE=... ./orin-native/startup/make-m4-images.sh m4-r1 --from-size {rel_repo(out)}")
    return 0


def size_r2_values(r0, r1, accept_low_n):
    """§2.4 from r1 to r2 over the two parse logs' M4PC keys: (rc, values, lines to print).
    A pure function, so selftest checks the rule against hand-computed values (I37)."""
    if r1.get("rung") != "r1" or r0.get("rung") != "r0":
        raise InputError("size-r2 needs an r1 parse log and an r0 parse log")
    if r1.get("run_verdict") != "pass":
        return 3, None, [f"SIZE r2 refused: r1 did not pass ({r1.get('run_verdict')})"]
    if parse_composite(r1.get("cnt_t_ring")).get("state") != "held":
        return 3, None, ["SIZE r2 owner: r1's ring was not held (§2.4 step 1)"]
    clean1 = to_int(parse_composite(r1.get("cnt_t_pairs")).get("clean"), 0)
    p1 = clean1 / 20
    if p1 <= 0:
        return 3, None, ["SIZE r2 owner: r1 had no eligible clean pair (§2.4 step 1)"]
    seq = {}
    for key, val in r1.items():
        m = re.match(r"cnt_t_buf_cpu(\d+)$", key)
        if m:
            seq[int(m.group(1))] = to_int(parse_composite(val).get("last_seq"), 0)
    beta = max(seq.values(), default=0) / 20
    beta_c = {c: v / 20 for c, v in seq.items()}
    fc = parse_composite(r1.get("cnt_t_flt_c"))
    pairs_all1 = to_int(fc.get("pairs_total"), 0)
    bpp1 = to_int(fc.get("bytes"), 0) / max(to_int(fc.get("pairs_written"), 0), 1)
    probe_cost = max(0, math.ceil(num(r0, "mem_probe_pre") - num(r0, "mem_probe_armed")))
    tp_ms1 = to_int(parse_composite(r1.get("tp_t")).get("ms"), 0)
    cnt_ms1 = to_int(parse_composite(r1.get("cnt_t")).get("ms"), 0)
    # I37 (§2.4 r2 steps 6-7, 14.21): what r1 measured, not what a full ring would have held.
    kev1 = num(r1, "kevfile_t")
    text1 = num(r1, "text_t")
    if kev1 <= 0 or text1 <= 0:
        raise InputError("r1's KEVFILE or TEXT bytes are zero")
    rho1 = text1 / kev1
    mem1 = to_int(r1.get("mem_trace_pre"))
    if mem1 is None:
        raise InputError("r1's parse log has no mem_trace_pre")
    rates = []
    for b in ("v", "c"):
        sent = to_int(r1.get(f"tcu_{b}_bytes_sent"))
        ms = to_int(r1.get(f"tcu_{b}_ms"))
        if sent and ms:
            rates.append((sent, sent / ms * 1000))
    if not rates:
        raise InputError("r1's parse log lacks the tcu rates")
    tcu_bps1 = max(rates)[1]
    n_pairs = max(15, math.ceil(15000 / p1) - 5)
    n2 = min(n_pairs, 13200)
    target = "p99"
    while True:
        k2 = max(256, math.ceil(1.5 * beta * (n2 + 5)) + 2) if beta > 0 else 256
        lin = False
        if k2 > 512:
            n_ring = math.floor(510 / (1.5 * beta)) - 5
            # I37: a ring-limited N2 below the 15 timed iterations is no r2; the generator refuses it.
            if n_ring >= 15 and n_ring * p1 >= 1200:
                n2, k2, target = n_ring, 512, "ring-limited"
            else:
                lin = True
        # Each CPU's buffers over N2 + 5 iterations, a CPU without a BUF record at the busiest rate.
        need_c = [math.ceil(1.5 * beta_c.get(c, beta) * (n2 + 5)) + 2 for c in range(P_BOARD)]
        if lin:
            bufs2 = sum(need_c)
            s2 = lin_s_mb(bufs2)
            need2 = trace_need_mb_lin(s2, probe_cost)
        else:
            bufs2 = sum(min(k2, x) for x in need_c)
            s2 = s_mb(k2)
            need2 = trace_need_mb(k2, probe_cost)
        kev2 = min(s2 * MIB, bufs2 * BUF_KB * 1024)
        tp_raw = math.ceil(4 * tp_ms1 / 1000 * kev2 / kev1) + 60
        cnt_raw = math.ceil(4 * cnt_ms1 / 1000 * kev2 * max(TEXT_PER_KEV, rho1) / text1) + 30
        tp2, cnt2 = max(120, tp_raw), max(60, cnt_raw)
        ipc2 = 240 + (5 * n2 + 99) // 100          # ceil(0.05 x N2) in integers, as the generator recomputes it
        cap_c, cap_v = 1048576, 131072
        send_c, send_v = send_s(cap_c, tcu_bps1), send_s(cap_v, tcu_bps1)
        while send_c > 600 and cap_c > 65536:
            cap_c //= 2
            send_c = send_s(cap_c, tcu_bps1)
        while send_v > 600 and cap_v > 65536:
            cap_v //= 2
            send_v = send_s(cap_v, tcu_bps1)
        fmt2 = fmt_need_mb(s2, cap_v, cap_c)
        worst = ksh_worst_full(240, ipc2, tp2, cnt2, send_v, send_c)
        guard2 = guard_for(worst)
        misfit = []
        if guard2 > 3600:
            misfit.append(f"guard:{guard2}")
        if tp_raw > 900:
            misfit.append(f"tp_bound:{tp_raw}")
        if cnt_raw > 600:
            misfit.append(f"cnt_bound:{cnt_raw}")
        if need2 > mem1:
            misfit.append(f"trace_need_mb:{need2}>trace_pre:{mem1}")
        if fmt2 >= MEM_WINDOW_MB:
            misfit.append(f"fmt_need_mb:{fmt2}")
        if not misfit or n2 <= 15:
            break
        n2 = max(15, math.floor(n2 * 0.9))
    if misfit or send_c > 600 or send_v > 600:
        why = "+".join(misfit) or "send-bound"
        return 3, None, [f"SIZE r2 owner: no N2 fits ({why}; §2.4 steps 6, 7 and 10)"]
    clean_pred = math.floor(p1 * (n2 + 5))
    p2 = "yes" if clean_pred >= 1200 else "no"
    p99 = "yes" if clean_pred >= 15000 else ("short-margin" if clean_pred >= 10000 else "no")
    c_capped_pred = "yes" if 1.5 * (pairs_all1 / 20) * (n2 + 5) * bpp1 > cap_c else "no"
    lines = [f"SIZE clean_pred={clean_pred} p2_reachable={p2} p99_reachable={p99} p99_target={target}"]
    if p2 == "no":
        return 3, None, lines + ["SIZE r2 owner: predicted to miss P2 (clean_pred below 1,200); no size file written (§2.4 step 11)"]
    if p99 == "no" and not accept_low_n:
        return 3, None, lines + ["SIZE r2 owner: P99 not quotable at this yield; pass --accept-low-n to build anyway (§2.4 step 11)"]
    values = {
        "image": f"m4-r2-{'lin' if lin else 'k%d' % k2}-n{n2}", "rung": "r2", "mode": "full", "p": P_BOARD,
        "kind": "linear" if lin else "ring",
        "k": "lin" if lin else k2, "s_mb": s2, "tl_args": f"-c -S {s2}M" if lin else f"-r -k {k2} -M -S {s2}M",
        "tl_bound": 2 + ipc2 + 5 + 160 + 30,
        "trace_need_mb": need2, "fmt_need_mb": fmt2, "cnt_need_mb": cnt_need_mb(cap_v, cap_c),
        "iters": n2, "ipc_bound": ipc2, "banner_bound": 240, "grace": 90, "tp_bound": tp2, "cnt_bound": cnt2,
        "hash_bound": 20, "forms": "c v", "cap_v": cap_v, "cap_c": cap_c, "send_v": send_v, "send_c": send_c,
        "send_t_v": send_v - 5, "send_t_c": send_c - 5, "clean_pred": clean_pred, "p2_reachable": p2,
        "p99_reachable": p99, "accept_low_n": 1 if (p99 == "no" and accept_low_n) else 0,
        "ksh_worst_s": worst, "guard_s": guard2, "return_bound_s": guard2 + 300, "capture_s": guard2 + 3300,
        "size_p99_target": target, "size_c_capped_predicted": c_capped_pred, "size_beta": f"{beta:.3f}",
        "size_p1": f"{p1:.3f}", "size_tcu_bps1": f"{tcu_bps1:.0f}", "size_probe_cost_mb": probe_cost,
        "size_lin_bufs": bufs2 if lin else "-", "size_kev2_pred_bytes": kev2, "size_text_ratio1": f"{rho1:.2f}",
        "size_mem_trace_pre1": mem1}
    return 0, values, lines


def cmd_size_r2(a):
    try:
        rc, values, lines = size_r2_values(read_parse_log(a.r0_parse), read_parse_log(a.r1_parse), a.accept_low_n)
    except InputError as e:
        print(f"parse-m4: input error: {e}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    if rc:
        return rc
    values["size_from_r0_parse_sha256"] = sha256_file(a.r0_parse)
    values["size_from_r1_parse_sha256"] = sha256_file(a.r1_parse)
    image = values["image"]
    out = a.out or os.path.join(REPO, "orin-native", "shim", "out", "m4", image + ".size")
    try:
        write_text(out, size_lines(values))
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    for k in ("image", "k", "iters", "tp_bound", "cnt_bound", "cap_c", "cap_v", "send_c", "send_v", "guard_s"):
        print(f"SIZE {k}={values[k]}")
    print(f"SIZE file={rel_repo(out)}")
    print(f"SIZE next: BSP=... QNX_BASE=... ./orin-native/startup/make-m4-images.sh m4-r2 --from-size {rel_repo(out)}")
    return 0


# ------------------------------------------------------------------ series (§6.5)

def cmd_series(a):
    log = Log()
    try:
        logs = [read_parse_log(p) for p in a.parse_logs]
    except InputError as e:
        print(f"parse-m4: input error: {e}", file=sys.stderr)
        return 1
    out = os.path.join(a.out_dir, "series-parse.log")
    try:
        check_out_path(out)
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    log("parser_sha256", sha256_file(os.path.abspath(__file__)))
    for p in a.parse_logs:
        log("input_parse_log", f"{os.path.basename(p)} sha256:{sha256_file(p)}")
    kimgs = {d.get("param_kimg_sha256", "?") for d in logs}
    log("series_kimg", "one" if len(kimgs) == 1 and "?" not in kimgs else "differ")
    p50 = []
    for d in logs:
        f = parse_composite(d.get("cnt_t_stat_clean"))
        p50.append(to_int(f.get("p50_ns")))
    if None in p50 or len(kimgs) != 1:
        log("p4", "fail(missing-p50-or-kimg)")
        p4 = "fail"
    else:
        s = sorted(p50)
        med = s[2]
        within = all(abs(v - med) * 5 <= med for v in p50)
        p4 = "pass" if within else "fail"
        log("series_p50_ns", ",".join(str(v) for v in p50))
        log("series_p50_median_ns", med)
        log("series_p50_min_ns", s[0])
        log("series_p50_max_ns", s[-1])
        log("p4", p4)
    p5 = "fail"
    try:
        cp = subprocess.run(["bash", os.path.join(REPO, "scripts", "twin", "diff-results.sh"), a.cloud_csv, a.csv],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        text = cp.stdout.decode("latin-1", "replace")
        if cp.returncode == 0 and all(re.search(rf"^\s*{k}\s+cloud=", text, re.M) for k in ("P50", "P99", "Max")):
            p5 = "pass"
        log("p5_exit", cp.returncode)
        log("p5_note", "diff-results.sh's closing warning describes the IPC legs and mislabels a dwell row")
    except (OSError, subprocess.TimeoutExpired) as e:
        log("p5_error", str(e).replace(" ", "_")[:200])
    log("p5", p5)
    try:
        write_text(out, log.text())
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    print(f"M4PC series p4={p4} p5={p5}")
    return 0


# ------------------------------------------------------------------ selftest (§4.5.9)

RUN_CASE_OPS = ("sub", "sub-com3", "resub", "add-after", "del", "del-first", "del-last", "vbody-del", "param", "arg",
                "expect")


def read_run_cases(path):
    """fixtures/m4run-cases.txt (I35): one run-level case per new rule. The grammar is in the file's header."""
    cases = []
    cur = None
    for raw in iter_raw_lines(read_bytes(path)):
        line = raw.decode("latin-1").rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        op, _, rest = line.partition(" ")
        if op == "case":
            cur = {"name": rest.strip(), "edits": [], "vdel": [], "params": {}, "args": {}, "exact": {},
                   "contains": {}}
            cases.append(cur)
            continue
        if cur is None or op not in RUN_CASE_OPS:
            raise InputError(f"{os.path.basename(path)}: cannot read '{line}'")
        if op in ("sub", "sub-com3", "resub", "add-after"):
            x, sep, y = rest.partition(" => ")
            if not sep or not x:
                raise InputError(f"{os.path.basename(path)}: '{line}' has no ' => '")
            cur["edits"].append((op, x, y))
        elif op in ("del", "del-first", "del-last"):
            cur["edits"].append((op, rest, None))
        elif op == "vbody-del":
            cur["vdel"].append(rest)
        elif op in ("param", "arg"):
            k, sep, v = rest.partition("=")
            if not sep:
                raise InputError(f"{os.path.basename(path)}: '{line}' has no '='")
            cur["params" if op == "param" else "args"][k.strip()] = v
        else:
            m = re.match(r"^([A-Za-z0-9_]+)([=~])(.*)$", rest)
            if not m:
                raise InputError(f"{os.path.basename(path)}: cannot read '{line}'")
            cur["exact" if m.group(2) == "=" else "contains"][m.group(1)] = m.group(3)
    return cases


def run_case(case, fixtures, out_dir):
    """One run-level case: a SYNTHETIC board r1 record from m4fix-1, the case's edits, then
    `run` on it (I35). Returns the reasons the case fails, empty when it holds."""
    name = case["name"]
    try:
        listing = read_bytes(os.path.join(fixtures, "m4fix-1.txt"))
        com3, bb, params, changed = synth_record(listing, rung="r1", profile="board", e3="none",
                                                 start_marker="m4-fix-start", end_marker="m4-fix-end",
                                                 transport="tcu", edits=case["edits"], vbody_del=case["vdel"],
                                                 params_over=case["params"])
    except (InputError, re.error) as e:
        return [f"build:{e}"]
    labels = [f"{op}:{x}" for op, x, _ in case["edits"]] + [f"vbody-del:{t}" for t in case["vdel"]]
    idle = [lab for lab, n in zip(labels, changed) if n == 0]
    if idle:
        return ["edit-changed-nothing:" + ";".join(idle)]
    d = os.path.join(out_dir, "runfix", name)
    paths = {k: os.path.join(d, f"runfix-{name}-{k}.log") for k in ("com3", "blackbox", "params")}
    try:
        write_bytes(paths["com3"], com3)
        write_bytes(paths["blackbox"], bb)
        write_text(paths["params"], "# SYNTHETIC run-level case (fixtures/m4run-cases.txt); not a record.\n" +
                   "".join(f"{k}={v}\n" for k, v in params.items()))
    except Refused as e:
        return [f"refused:{e}"]
    sha = case["args"].get("blackbox_board_sha256", "auto")
    if sha == "auto":
        sha = hashlib.sha256(bb).hexdigest()
    ns = argparse.Namespace(params=paths["params"], blackbox=paths["blackbox"], com3=paths["com3"],
                            run_id=f"runfix-{name}", out_dir=d, csv=None, com3_format="capture", rehearsal=False,
                            reset_reason=case["args"].get("reset_reason", "MAINSWRST"), fixtures=fixtures,
                            blackbox_board_sha256=sha, run_end_epoch=None)
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        rc = cmd_run(ns)
    if rc != 0:
        return [f"run-exit:{rc}:{sink.getvalue().strip()[:160]}"]
    pl = read_parse_log(os.path.join(d, f"runfix-{name}-parse.log"))
    why = []
    for k, v in case["exact"].items():
        if pl.get(k) != v:
            why.append(f"{k}:got:{pl.get(k)}")
    for k, v in case["contains"].items():
        got = pl.get(k)
        if got is None or v not in got or (k.startswith("crit_") and not got.startswith("fail")):
            why.append(f"{k}:got:{got}")
    for k, v in pl.items():
        if (k.startswith("crit_") and k not in case["exact"] and k not in case["contains"]
                and v != "pass" and not v.startswith("n/a")):
            why.append(f"{k}:unexpected:{v}")
    return why


def sizing_cases():
    """I37 (m4-design.md 2.4, 14.21): invented parse-log keys, and the values §2.4 gives for
    them, computed by hand from the design's text and not by the code under test. The
    inputs are chosen so every division and ceiling is exact in binary floating point."""
    def rate(c, bufs):
        return f"cpu:{c},bufs_in_window:{bufs},events_in_window:10,span_ticks:250000000"

    def buf(c, seq):
        return f"cpu:{c},first_seq:1,last_seq:{seq},kept:{seq},gaps:0"

    r0 = {"rung": "r0", "run_verdict": "pass", "cnt_l0_in": "cps:31250000", "mem_probe_pre": "750",
          "mem_probe_armed": "746", "tp_l0": "rc:0,killed:0,ms:1000", "cnt_l0": "rc:0,killed:0,ms:1000",
          "kevfile_l0": "10485760", "text_l0": "52428800", "tcu_v_bytes_sent": "500000", "tcu_v_ms": "100000"}
    r0_ring = dict(r0, **{f"cnt_l0_rate_cpu{c}": rate(c, 1) for c in range(4)})
    # CPU 3 has no RATE record, so it is budgeted at the busiest CPU's rate: 722 + 242 + 242 + 722.
    r0_lin = dict(r0, cnt_l0_rate_cpu0=rate(0, 5), cnt_l0_rate_cpu1=rate(1, 1), cnt_l0_rate_cpu2=rate(2, 1))
    r1_ring = {"rung": "r1", "run_verdict": "pass", "cnt_t_ring": "state:held,wrapped_cpus:none",
               "cnt_t_pairs": "total:700,eligible:650,clean:600", "cnt_t_buf_cpu0": buf(0, 40),
               "cnt_t_buf_cpu1": buf(1, 20), "cnt_t_buf_cpu2": buf(2, 10), "cnt_t_buf_cpu3": buf(3, 10),
               "cnt_t_flt_c": "form:c,bytes:100000,pairs_written:2000,pairs_total:2000",
               "tp_t": "rc:0,killed:0,ms:2000", "cnt_t": "rc:0,killed:0,ms:3000", "kevfile_t": "2097152",
               "text_t": "10485760", "tcu_v_bytes_sent": "1000000", "tcu_v_ms": "100000", "mem_trace_pre": "300"}
    r1_lin = dict(r1_ring, cnt_t_pairs="total:70,eligible:65,clean:60", cnt_t_buf_cpu0=buf(0, 20),
                  cnt_t_buf_cpu1=buf(1, 0), cnt_t_buf_cpu2=buf(2, 0), cnt_t_buf_cpu3=buf(3, 0),
                  tp_t="rc:0,killed:0,ms:1000", cnt_t="rc:0,killed:0,ms:1000", mem_trace_pre="900")
    return [
        # need1 = 16 x 0.25 x 60 + 2 = 242: K1 = 256, S = 20, need = 16 + 20 + 32; the caps halve once for the guard.
        ("r1_ring", lambda: size_r1_values(r0_ring),
         {"image": "m4-r1-k256", "k": "256", "s_mb": "20", "tl_args": "-r -k 256 -M -S 20M", "trace_need_mb": "68",
          "fmt_need_mb": "403", "cap_v": "524288", "cap_c": "262144", "guard_s": "2700", "size_lin_bufs": "-",
          "size_probe_cost_mb": "4"}),
        # need1 = 722 > 512: lin. bufs = 1928, S = ceil(30.125) + 4 = 35, need = max(1, 4) + 35 + 32.
        ("r1_lin", lambda: size_r1_values(r0_lin),
         {"image": "m4-r1-lin", "k": "lin", "s_mb": "35", "tl_args": "-c -S 35M", "trace_need_mb": "71",
          "fmt_need_mb": "478", "guard_s": "2700", "size_lin_bufs": "1928"}),
        # p1 = 30, beta = 2: ring-limited at N2 = 165, K2 = 512. bufs2 = 512 + 257 + 130 + 130 = 1029, kev2 =
        # 16859136 B = 8.0390625 x kev1; TP = ceil(8 x 8.0390625) + 60, CNT = ceil(12 x 8.0390625) + 30.
        ("r2_ring", lambda: size_r2_values(r0_ring, r1_ring, True),
         {"image": "m4-r2-k512-n165", "k": "512", "s_mb": "36", "iters": "165", "tp_bound": "125",
          "cnt_bound": "127", "trace_need_mb": "100", "fmt_need_mb": "484", "guard_s": "2400",
          "size_kev2_pred_bytes": "16859136", "accept_low_n": "1"}),
        # p1 = 3, beta = 1: N_ring = 335 gives 1005 clean pairs, below 1200, so D1(b) at N2 = 4995. bufs2 = 7502 + 3 x 2,
        # S = ceil(117.3125) + 4 = 122, need = 4 + 122 + 32; kev2 = 58.65625 x kev1, so TP = 235 + 60 and CNT = 235 + 30.
        ("r2_lin", lambda: size_r2_values(r0_ring, r1_lin, False),
         {"image": "m4-r2-lin-n4995", "k": "lin", "s_mb": "122", "tl_args": "-c -S 122M", "trace_need_mb": "158",
          "tp_bound": "295", "cnt_bound": "265", "fmt_need_mb": "914", "guard_s": "2700", "size_lin_bufs": "7508"}),
        # r1 had 20 MiB free at its gate: no N2 down to 15 fits, so the owner decides.
        ("r2_memory_owner", lambda: size_r2_values(r0_ring, dict(r1_lin, mem_trace_pre="20"), True),
         {"rc": "3", "lines~": "trace_need_mb:"}),
    ]


def cmd_selftest(a):
    log = Log()
    out = os.path.join(a.out_dir, "selftest.log")
    try:
        check_out_path(out)
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    ok = True
    board_runs = None
    if a.m4c:
        try:
            texts = [t for _, t in split_lines(read_bytes(a.m4c))]
        except InputError as e:
            print(f"parse-m4: input error: {e}", file=sys.stderr)
            return 1
        board_runs = fixture_runs_from_lines(texts)
    for name in FIXTURE_NAMES:
        path = os.path.join(a.fixtures, name)
        try:
            exp = fixture_expects(path)
            L = Listing("m4-fix-start", "m4-fix-end").feed_file(path)
        except (InputError, OSError) as e:
            log(f"selftest_{name}", f"error({str(e).replace(' ', '_')[:80]})")
            ok = False
            continue
        miss = check_expects(L.records(label="fix"), exp)
        log(f"selftest_pc_{name}", "ok" if not miss else "fail(" + ";".join(miss).replace(" ", "_") + ")")
        ok = ok and not miss and bool(exp)
        if board_runs is not None:
            got = board_runs.get(name)
            if got is None:
                log(f"selftest_m4c_{name}", "absent")
                ok = False
            else:
                miss = check_expects(got, exp)
                log(f"selftest_m4c_{name}", "ok" if not miss else "fail(" + ";".join(miss).replace(" ", "_") + ")")
                ok = ok and not miss
    # I29 (m4-design.md 14.12): the cross-check itself, which no fixture reaches.
    # The fixtures are listings with no compact block, so `run`'s xcheck_pairs
    # reads n/a throughout selftest and the rule was exercised only by hand, on
    # the board's r1 record. Here the compact block is generated from the PC's
    # own pairs and then mutated, so each case names one behaviour of the rule.
    XL = None
    try:
        XL = Listing("m4-fix-start", "m4-fix-end").feed_file(os.path.join(a.fixtures, "m4fix-1.txt"))
        index, _rows = compact_rows(compact_list(XL, 1 << 20, "fix")[0])
    except (InputError, OSError) as e:
        log("selftest_xcheck", f"error({str(e).replace(' ', '_')[:80]})")
        ok = False
    if XL is not None and XL.window_known and index:
        k0 = sorted(index)[0]
        v0 = index[k0]
        differ = dict(index)
        differ[k0] = ("blk" if v0[0] != "blk" else "clean",) + v0[1:]
        extra = dict(index)
        extra[(k0[0] + 1, k0[1])] = v0
        cases = [("agree", XL.end_t, index, False, "match compared="),
                 ("differ", XL.end_t, differ, False, "differ(1) orphan=0 compared="),
                 ("orphan", XL.end_t, extra, False, "differ(0) orphan=1 compared="),
                 ("capped", XL.end_t, extra, True, "match compared="),
                 ("empty", XL.start_t - 1, index, False, "empty compared=0")]
        # I28's regression guard. A row whose entry is inside the range and whose
        # exit is past it is the truncation, not a disagreement: the first form
        # of the reverse walk called it an orphan and failed a board record that
        # had passed. The bound is set at such a row's entry, with at least one
        # whole pair below it so the comparison is not empty.
        straddle = None
        for p in sorted((q for q in XL.pairs if q["list"] and q["a"] is not None and q["b"] is not None
                         and q["dwell"] is not None and q["dwell"] > 0), key=lambda q: q["a"]):
            if any(q["a"] is not None and q["b"] is not None and q["a"] >= XL.start_t and q["b"] <= p["a"]
                   for q in XL.pairs):
                straddle = p["a"]
                break
        if straddle is None:
            log("selftest_xcheck_straddle", "fail(no-case-in-fixture)")
            ok = False
        else:
            cases.append(("straddle", straddle, index, False, "match compared="))
        for name, lim, idx, capped, want in cases:
            got = xcheck_pairs_record(XL, idx, lim, capped)
            # I34: every form also names both sides' in-range counts.
            good = got.startswith(want) and " pc_in_range=" in got and " c_in_range=" in got
            log(f"selftest_xcheck_{name}", "ok" if good else f"fail(got:{got.replace(' ', '_')})")
            ok = ok and good
    # I31 (m4-design.md 14.13 and 14.14): the gate helpers I30 and I30b added
    # were checked once, by hand, against mutated copies of a board capture that
    # were scratch inputs and were not kept. These are those checks, made
    # permanent and compared exactly rather than by prefix, because each helper
    # returns the list of reasons a criterion will fail for.
    #
    # They cover the helpers only. The wiring into crit_1, crit_2 and crit_3 is
    # covered by I35's run-level cases below, on a synthetic board record.
    MK = ("m4-ipc-start", "m4-ipc-end")
    TRC_OK = ["TRCCTL insert id=20 text=m4-ipc-start rc=0 errno=0",
              "TRCCTL insert id=21 text=m4-ipc-end rc=0 errno=0",
              "TRCCTL stop rc=0 errno=0"]
    PH_OK = {"g_first": 10, "g_devb": 20, "g_net": 30, "g_ifup": 40, "g_sshd": 50,
             "g_misc": 60, "g_startup_complete": 70, "g_srv": 65, "banner": 80}

    def ph(**over):
        d = dict(PH_OK)
        for k, v in over.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        return d

    order_ok = ["T234-SHIM EL=2", "JUMP", "t234: all 4 cpus parked in smp_spin", "Starting next program"]
    gate_cases = [
        # trcctl: presence was the whole test before I30; the rc is now read.
        ("trcctl_clean", trcctl_bad(TRC_OK, MK), []),
        ("trcctl_stop_rc", trcctl_bad([t.replace("stop rc=0", "stop rc=1") for t in TRC_OK], MK),
         ["trcctl_stop_rc:1"]),
        ("trcctl_marker_rc", trcctl_bad([t.replace("id=20 text=m4-ipc-start rc=0",
                                                   "id=20 text=m4-ipc-start rc=2") for t in TRC_OK], MK),
         ["trcctl_insert:m4-ipc-start_rc:2"]),
        ("trcctl_marker_absent", trcctl_bad(TRC_OK[:1] + TRC_OK[2:], MK),
         ["trcctl_insert:m4-ipc-end_absent"]),
        ("trcctl_silent", trcctl_bad([], MK),
         ["trcctl_insert:m4-ipc-start_absent", "trcctl_insert:m4-ipc-end_absent", "trcctl_stop_absent"]),
        # startup order: landing_ok proves presence, these two prove order.
        ("order_clean", startup_order_bad(order_ok, 4), []),
        ("order_reversed", startup_order_bad([order_ok[1], order_ok[0], order_ok[3], order_ok[2]], 4),
         ["order-shim-before-jump", "order-parked-before-next-program"]),
        ("order_absent", startup_order_bad(["nothing here"], 4), []),
        # guest phases: D3 item 6, including the two things it says not to gate.
        ("phase_clean", guest_phase_bad(PH_OK), []),
        ("phase_out_of_order", guest_phase_bad(ph(g_net=15)), ["phase-order:g_devb>g_net"]),
        ("phase_required_absent", guest_phase_bad(ph(g_devb=None)), ["phase-g_devb-absent"]),
        ("phase_optional_absent", guest_phase_bad(ph(g_ifup=None, g_sshd=None, g_misc=None)), []),
        ("phase_srv_late", guest_phase_bad(ph(g_srv=999)), []),
        ("phase_after_banner", guest_phase_bad(ph(g_misc=999)),
         ["phase-order:g_misc>g_startup_complete", "phase-after-banner:g_misc"]),
    ]
    for name, got, want in gate_cases:
        good = list(got) == want
        log(f"selftest_gate_{name}", "ok" if good else f"fail(got:{'+'.join(got) or 'none'})")
        ok = ok and good
    # I35 (m4-design.md 14.19): the run-level cases. Each builds a SYNTHETIC board
    # r1 record, applies one rule's edit and runs `run` over it, so a rule that is
    # written but not read by its criterion fails here, which the helper cases
    # above cannot show.
    try:
        run_cases = read_run_cases(os.path.join(a.fixtures, "m4run-cases.txt"))
    except InputError as e:
        log("selftest_run_cases", f"error({str(e).replace(' ', '_')[:120]})")
        run_cases = []
    if not run_cases:
        ok = False
    for case in run_cases:
        why = run_case(case, a.fixtures, a.out_dir)
        log(f"selftest_run_{case['name']}", "ok" if not why else "fail(" + "+".join(why).replace(" ", "_")[:400] + ")")
        ok = ok and not why
    # I37 (m4-design.md 14.21): the sizing rules, which no test reached before (14.8).
    for name, fn, want in sizing_cases():
        try:
            rc, values, lines = fn()
        except InputError as e:
            log(f"selftest_size_{name}", f"error({str(e).replace(' ', '_')[:80]})")
            ok = False
            continue
        bad = []
        for k, v in want.items():
            if k == "rc":
                got = str(rc)
            elif k == "lines~":
                got = v if any(v in line for line in lines) else "+".join(lines)
            else:
                got = "-rc%d-" % rc if rc else str(values.get(k))
            if got != v:
                bad.append(f"{k}:got:{got}")
        log(f"selftest_size_{name}", "ok" if not bad else "fail(" + "+".join(bad).replace(" ", "_")[:300] + ")")
        ok = ok and not bad
    log("selftest", "pass" if ok else "fail")
    try:
        write_text(out, log.text())
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    for line in log.lines:
        print(line)
    return 0 if ok else 1


# ------------------------------------------------------------------ regress-7b (§6.5)

def cmd_regress_7b(a):
    base = os.path.normcase(os.path.abspath(os.path.join(REPO, "qhv", "m4tcg", "regress")))
    if not os.path.normcase(os.path.abspath(a.out_dir)).startswith(base):
        print("parse-m4: refused: regress-7b writes under qhv/m4tcg/regress/ only", file=sys.stderr)
        return 2
    log = Log()
    path7 = os.path.join(REPO, "orin-native", "m4dry", "parse-m4dry.py")
    try:
        spec = importlib.util.spec_from_file_location("parse_m4dry", path7)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # recorded: an import failure is the result
        print(f"parse-m4: cannot import {path7}: {e}", file=sys.stderr)
        return 1
    L = Listing(a.start_marker, a.end_marker, e3_status0=(a.e3 == "status0")).feed_file(a.listing)
    A7 = mod.Analysis()
    with open(a.listing, "rb") as f:
        for raw in f:
            A7.feed(raw.decode("latin-1").rstrip("\r\n"))
    log("parser_sha256", sha256_file(os.path.abspath(__file__)))
    log("input_listing", f"{os.path.basename(a.listing)} sha256:{sha256_file(a.listing)}")
    log("m4_complete_triples", L.tr_complete)
    log("m4dry_complete_triples", A7.triples)
    log("complete_triples", "equal" if L.tr_complete == A7.triples else "differ")
    log("m4_offset_order", composite([("ok", L.tr_ok), ("violated", L.tr_violated)]))
    log("m4dry_offset_order", composite([("ok", A7.off_ok), ("violated", A7.off_bad), ("missing", A7.off_missing)]))
    log("offset_order", "equal" if (L.tr_ok == A7.off_ok and L.tr_violated == A7.off_bad + A7.off_missing) else "differ")
    d4 = sorted(p["dwell"] for p in L.pairs if p["dwell"] is not None)
    d7 = sorted(A7.dwell)
    log("m4_pairs_with_dwell", len(d4))
    log("m4dry_pairs", len(d7))
    log("dwell_multiset", "equal" if d4 == d7 else "differ")
    if d4 != d7:
        only4 = len(d4) - len(set(d4) & set(d7))
        only7 = len(d7) - len(set(d4) & set(d7))
        log("dwell_multiset_note", f"distinct-values-only-in-m4:{only4},only-in-m4dry:{only7};"
                                   "file-order-pairing(m4dry)-against-time-order-pairing(m4)")
    for name, f in L.records(label="regress"):
        if name in ("TIME64", "RING", "TRIPLES", "PAIRS", "VCPU", "STATUSSUM"):
            log(f"m4_{name.lower()}", composite((k, v) for k, v in f.items() if k != "w"))
        elif name == "STATUS":
            log(f"m4_status_{f['value']}", composite((k, v) for k, v in f.items() if k != "w"))
    out = os.path.join(a.out_dir, "regress-7b-parse.log")
    try:
        write_text(out, log.text())
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    for line in log.lines:
        print(line)
    return 0


# ------------------------------------------------------------------ synth-com3 (§14: a test input, never a record)

FIXTURE_NAMES = tuple(f"m4fix-{i}.txt" for i in range(1, 7))

SYNTH_EDIT_OPS = ("sub", "sub-com3", "resub", "del", "del-first", "del-last", "add-after")


def apply_synth_edits(items, edits, side):
    """The run-level cases' edits (fixtures/m4run-cases.txt) over one record's console
    lines; a framed block body is never edited. Returns the lines and, per edit, how
    many lines it changed on this side."""
    out = list(items)
    changed = [0] * len(edits)
    for i, (op, x, y) in enumerate(edits):
        if op == "sub-com3" and side != "com3":
            continue
        if op in ("sub", "sub-com3", "resub"):
            rx = re.compile(x) if op == "resub" else None
            new = []
            for it in out:
                if isinstance(it, str):
                    t2 = rx.sub(y, it) if rx else it.replace(x, y)
                    if t2 != it:
                        changed[i] += 1
                        it = t2
                new.append(it)
            out = new
        elif op in ("del", "del-first", "del-last"):
            idx = [j for j, it in enumerate(out) if isinstance(it, str) and it.lstrip().startswith(x)]
            idx = idx[:1] if op == "del-first" else (idx[-1:] if op == "del-last" else idx)
            changed[i] += len(idx)
            drop = set(idx)
            out = [it for j, it in enumerate(out) if j not in drop]
        elif op == "add-after":
            for j, it in enumerate(out):
                if it == x:
                    out.insert(j + 1, y)
                    changed[i] += 1
                    break
        else:
            raise InputError(f"unknown synthetic edit {op}")
    return out, changed


def synth_record(data, *, rung, profile="tcg", e3="status0", start_marker="m4d-ipc-start", end_marker="m4d-ipc-end",
                 vcap=1048576, ccap=524288, transport="console", fault="none", edits=(), vbody_del=(),
                 params_over=None):
    """A SYNTHETIC COM3 capture, black box and params around one listing: a test input
    for the parser's plumbing, never a record (§14, I10). Returns (com3, bb, params,
    changed), where changed counts, per edit and then per vbody_del entry, the lines
    it changed on either record.

    profile `tcg` is what the §11 rehearsal parse (--rehearsal) reads. profile
    `board` (I35, m4-design.md 14.19) adds every line a board r1 run prints that the
    board-only criteria read - landing, the image's own CONFIG, rate lines, guest
    phases, the reset line - so a record built from a fixture can be parsed as a
    board run and each rule shown to be wired into its criterion."""
    board = profile == "board"
    if board and rung != "r1":
        raise InputError("the board profile builds an r1 record only")
    # A target traceprinter writes LF only. The 7b listings were re-made on the PC by
    # traceprinter.exe and end every line in CRLF, so a synthetic target block built
    # from them would carry CR bytes the real one never has, and the PC's CR strip
    # (section 6.2) would then fail flt_v on every fault. Normalise first; the crlf
    # fault still injects CR on the capture side.
    data = data.replace(b"\r\n", b"\n")
    w = "l0" if rung == "r0" else "t"
    mode = "trace" if rung == "r0" else "full"
    L = Listing(start_marker, end_marker, e3_status0=(e3 == "status0")).feed_bytes(data)
    vbody, vst = verbatim_selection(data, L, vcap)
    vdel_changed = []
    for text in vbody_del:
        kept = [raw for raw in iter_raw_lines(vbody) if text.encode("latin-1") not in raw]
        vdel_changed.append(len(list(iter_raw_lines(vbody))) - len(kept))
        vbody = b"".join(kept)
    cbody, cst = compact_list(L, ccap, w)
    recs = L.records(label=w)
    for name, f in recs:
        if name == "IN":
            f["path"] = f"/dev/shmem/{w}.txt"
    fv = ("FLT", {"w": w, "form": "v", "file": "/dev/shmem/flt.v", "lines": str(vst["lines"]),
                  "bytes": str(len(vbody)), "capped": str(vst["capped"]), "sel_lines": str(vst["sel_lines"]),
                  "sel_bytes": str(vst["sel_bytes"]), "last_t": hexs(vst["last_t"]),
                  "marker_collision": str(vst["collision"]), "cr_bytes": str(vst["cr"])})
    fc = ("FLT", {"w": w, "form": "c", "file": "/dev/shmem/flt.c", "lines": str(cst["lines"]),
                  "bytes": str(len(cbody)), "capped": str(cst["capped"]),
                  "pairs_written": str(cst["pairs_written"]), "pairs_total": str(cst["pairs_total"])})
    blocks = [("v", vbody)] if rung == "r0" else [("v", vbody), ("c", cbody)]
    params = {"image": "synthetic", "rung": rung, "mode": mode, "p": 4 if board else 2,
              "variant": "synthetic-board" if board else "synthetic", "synthetic": 1, "transport": transport,
              "iters": 15, "guard_s": 2700 if board else "-", "start_marker": start_marker, "end_marker": end_marker,
              "e3": e3, "fixtures": ",".join(FIXTURE_NAMES)}
    if board:
        params.update({"image": "m4-r1-k256", "kind": "ring", "k": 256, "s_mb": 20,
                       "tl_args": "-r -k 256 -M -S 20M", "trace_need_mb": 68, "forms": "v c"})
    # Every console line below is invented plumbing around the listing (SYNTHETIC, never a record);
    # it lets run's criteria see the lines a board run would print. The console follows the params
    # as built here; params_over changes only the params file, so a case can make them disagree.
    console = []
    if board:
        console += ["T234-SHIM EL=2 synthetic", "JUMP 0x80080000 synthetic", "Enabling EL2 host hypervisor support (VHE)"]
        console += [f"t234: cpu {n} el2-host EL2 HCR_EL2=0x408000000" for n in range(4)]
        console += [f"t234: hvtimer cpu {n} verdict=wired" for n in range(4)]
        console += ["t234: all 4 cpus parked in smp_spin", "Starting next program", f"T234 M4 {rung} -P4: procnto up",
                    "BWAIT guard armed secs=2700", "SMPCHECK census hyp qtime_intr=28 hypinfo_flags=0x1",
                    "SMPCHECK census tick=ok", "SMPCHECK CENSUS PASS", "M4 STATE config",
                    f"M4 CONFIG rung={rung} mode={mode} startup='startup-t234-orin-nano -vvv -P4 -Q enable,el2-host "
                    f"-m992M -Wkeep -A -Dtcu' q=el2-host w=keep A=1 cpus=4 guest_sha256={PIN_GUEST} "
                    f"disk_sha256={PIN_DISK} conf_sha256={'0' * 64} client_sha256={PIN_CLIENT} clock=unverified "
                    f"kind={params['kind']} tl_args='{params['tl_args']}' iters=15 forms='{params['forms']}' "
                    f"trace_need_mb={params['trace_need_mb']} transport={transport}"]
    else:
        console += ["M4 STATE config",
                    f"M4 CONFIG rung={rung} mode={mode} synthetic=1 clock=unverified transport={transport}"]

    def rates(tag):
        if not board:
            return [f"M4 RATES {tag} skipped"]
        return [f"SMPCHECK done cpu={c} secs=20 elapsed_ms=20000 samples=20 misplaced=0 backwards=0 iters=20 "
                f"rate=1 timer0_ms=0 timer0_cpu={c} timer1_ms=0 timer1_cpu={c} pin=ok end=ok" for c in range(4)]

    console += ["M4 STATE preflight", "M4 MEM boot 900MB/992MB", "M4 STATE rate_pre"] + rates("r0")
    console += ["M4 STATE integrity_pre", "M4 CHECK md5_pre guest ok", "M4 CHECK md5_pre disk ok",
                "M4 CHECK md5_pre conf ok"]
    stamps, ipc_lines = [], []
    if rung == "r0":
        console += ["M4 STATE clock"]
        console += [f"CLK VERDICT mode={m} usable=5 strict=5 res=5 result=agree" for m in ("same0", "same1", "cross")]
        console += ["M4 STATE fixtures"]
        for fxname in FIXTURE_NAMES:
            FL = Listing("m4-fix-start", "m4-fix-end").feed_file(os.path.join(HERE, "fixtures", fxname))
            frecs = FL.records(label="fix", quiet=True)
            for fname, ff in frecs:
                if fname == "IN":
                    ff["path"] = f"/proc/boot/{fxname}"
            console += render_records(frecs) + ["M4C END w=fix rc=0 reason=ok"]
        console += ["M4 STATE disk", "M4 CHECK disk_copy ok", "BWAIT path hit=/dev/qvmdisk0 ms=5",
                    "M4 MEM disk 750MB/992MB", "M4 STATE probe", "M4 MEM probe_pre 750MB/992MB",
                    "M4 MEM probe_armed 746MB/992MB", "TRCCTL stop rc=0 errno=0", "M4 STOP p by=stop",
                    "M4 MEM probe_stopped 742MB/992MB", "M4 STATE l0", "M4 STOP l0 by=self",
                    "M4 STATE teardown", "M4 STATE release", "M4 MEM released 880MB/992MB",
                    "M4 STATE rate_post"] + rates("r1") + ["M4 STATE format"]
        runs = [("p", False), (w, True)]
    else:
        pidin = ["     pid tid name               cpu  ", "  700000   1 qvm                  0  "]
        stamps = ["STAMP qvm_launch cycles=1000 cps=31250000 cpu=0 mono_ns=0 bytes=0"]
        if board:
            stamps += [f"STAMP {n} cycles={c} cps=31250000 cpu=0 mono_ns=0 bytes=0"
                       for n, c in (("g_first", 1100), ("g_devb", 1200), ("g_net", 1300), ("g_ifup", 1400),
                                    ("g_sshd", 1500), ("g_misc", 1600), ("g_srv", 1650), ("g_startup_complete", 1700))]
        stamps += ["STAMP banner cycles=2000 cps=31250000 cpu=0 mono_ns=0 bytes=0"]
        ipc_lines = ["samples=15 payload=48 cps=31250000", "P50=1000 ns  P99=2000 ns  Max=2000 ns",
                     "sentinel_recoveries=0 sentinel_bounces=0",
                     "BWAIT run prog=qnx-host-client rc=0 sig=0 killed=0 ms=1000"]
        arm_kind = params.get("kind", "ring")
        arm_args = params.get("tl_args", "synthetic")
        console += ["M4 STATE disk", "M4 CHECK disk_copy ok", "BWAIT path hit=/dev/qvmdisk0 ms=5",
                    "M4 MEM disk 750MB/992MB", "M4 STATE hostcheck", "M4 STATE window", "M4 STATE report"]
        console += stamps + ["M4 MEM banner 200MB/992MB"] + pidin
        console += ["M4 STATE ipc", "M4 MEM trace_pre 200MB/992MB",
                    f"M4 TRACE ARM kind={arm_kind} args='{arm_args}' file=/dev/shmem/t.kev bound=437",
                    "M4 STATE report_ipc", f"TRCCTL insert id=20 text={start_marker} rc=0 errno=0",
                    f"TRCCTL insert id=21 text={end_marker} rc=0 errno=0", "TRCCTL stop rc=0 errno=0",
                    "M4 STOP t by=stop"] + ipc_lines + pidin
        console += ["M4 STATE teardown", "rc=3", "M4 STATE integrity_post", "M4 CHECK md5_post guest ok",
                    "M4 CHECK md5_post disk ok", "M4 STATE release", "M4 MEM released 880MB/992MB",
                    "M4 STATE rate_post"] + rates("r1") + ["M4 STATE format"]
        runs = [(w, True)]
    for rw, is_main in runs:
        rrecs = L.records(label=rw)
        for rname, rf in rrecs:
            if rname == "IN":
                rf["path"] = f"/dev/shmem/{rw}.txt"
        console += [f"M4 KEVFILE {rw} path=/dev/shmem/{rw}.kev bytes={len(data) // 4}",
                    f"M4 MEM preformat_{rw} 600MB/992MB",
                    "BWAIT run prog=traceprinter rc=0 sig=0 killed=0 ms=1000",
                    f"M4 TEXT {rw} bytes={len(data)}",
                    f"M4 MEM formatted_{rw} 500MB/992MB",
                    "BWAIT run prog=m4count rc=0 sig=0 killed=0 ms=500",
                    f"M4C PASS w={rw} pass=1 lines={L.lines} ms=1",
                    f"M4C PASS w={rw} pass=2 lines={L.lines} ms=1"]
        console += render_records(rrecs)
        if is_main:
            console += [f"M4C PASS w={rw} pass=3 lines={L.lines} ms=1"]
            console += render_records([fv] + ([fc] if rung != "r0" else []))
        console += [f"M4C END w={rw} rc=0 reason=ok"]
    console += ["M4 STATE summary"] + stamps + ipc_lines + ["M4 FAIL_STATE none", "M4 STATE send"]
    items = list(console)
    for name, body in blocks:
        crc, ln = posix_cksum(body)
        items += ["BWAIT run prog=md5sum rc=0 sig=0 killed=0 ms=10",
                  "BWAIT run prog=toybox rc=0 sig=0 killed=0 ms=10",
                  "BWAIT run prog=toybox rc=0 sig=0 killed=0 ms=10",
                  f"M4 FLT BEGIN name={name} rung={rung} lines={body.count(chr(10).encode())} bytes={ln} wc_bytes={ln} "
                  f"md5={hashlib.md5(body).hexdigest()} cksum={crc}"]
        items.append(("BODY", name, body))
        if transport == "tcu":
            items += ["BWAIT run prog=tcu-cat rc=0 sig=0 killed=0 ms=100",
                      "tcu-cat: bytes_in=33 bytes_sent=33 drops=0 timeouts=0 max_consecutive=0 aborted=0 deadline=0 ms=5 rc=0",
                      "BWAIT run prog=tcu-cat rc=0 sig=0 killed=0 ms=10000",
                      f"tcu-cat: bytes_in={ln} bytes_sent={ln} drops=0 timeouts=0 max_consecutive=0 aborted=0 deadline=0 ms=10000 rc=0",
                      "BWAIT run prog=tcu-cat rc=0 sig=0 killed=0 ms=100",
                      "tcu-cat: bytes_in=20 bytes_sent=20 drops=0 timeouts=0 max_consecutive=0 aborted=0 deadline=0 ms=5 rc=0"]
        items.append(f"M4 FLT END name={name} rc=0")
    items += ["M4 STATE diag"]
    if rung != "r0":
        items += ["QNX qnx-guest 8.0.0 synthetic ARMv8_Foundation_Model aarch64le", "M4 MEM end 880MB/992MB"]
    items += ["M4 FAIL_STATE none", "M4 STATE end"]
    if board:
        items += [f"T234 M4 {rung} -P4: resetting so the log can be recovered"]

    com3_items, ch_com3 = apply_synth_edits(items, list(edits), "com3")
    bb_items, ch_bb = apply_synth_edits(items, list(edits), "bb")

    def render(side_items, with_bodies):
        buf = bytearray()
        for it in side_items:
            if isinstance(it, str):
                buf += (it + "\n").encode("latin-1")
                continue
            if not with_bodies:
                continue
            _, name, body = it
            body_out = body.replace(b"\n", b"\r\n") if fault == "crlf" else body
            if fault == "corrupt-v" and name == "v" and len(body_out) > 10:
                body_out = body_out[:5] + (b"X" if body_out[5:6] != b"X" else b"Y") + body_out[6:]
            buf += f"=M4FLT= BEGIN name={name} rung={rung}\n".encode() + body_out
            if not (fault == "truncate-c" and name == "c"):
                buf += f"=M4FLT= END name={name}\n".encode()
        return bytes(buf)

    com3 = render(com3_items, True)
    bb = render(bb_items, False)
    if fault == "bb-cut":
        bb = bb[:len(bb) // 2]
    now = int(datetime.now(timezone.utc).timestamp())
    iso = datetime.fromtimestamp(now, timezone.utc).isoformat()
    head = f"--- raw capture started on COM3 at 115200, {iso} epoch={now} seconds=6000 ---\n".encode()
    endl = f"\n--- raw capture ended {iso} bytes={len(com3)} ---\n".encode()
    params.update(params_over or {})
    changed = [max(a, b) for a, b in zip(ch_com3, ch_bb)] + vdel_changed
    return head + com3 + endl, bb, params, changed


def cmd_synth_com3(a):
    base = os.path.normcase(os.path.abspath(os.path.join(REPO, "qhv")))
    if not os.path.normcase(os.path.abspath(a.out_dir)).startswith(base + os.sep):
        print("parse-m4: refused: synth-com3 writes under qhv/ only", file=sys.stderr)
        return 2
    try:
        com3, bb, params, _ = synth_record(read_bytes(a.listing), rung=a.rung, profile=a.profile, e3=a.e3,
                                           start_marker=a.start_marker, end_marker=a.end_marker, vcap=a.vcap,
                                           ccap=a.ccap, transport=a.transport, fault=a.fault)
    except InputError as e:
        print(f"parse-m4: input error: {e}", file=sys.stderr)
        return 1
    try:
        write_bytes(os.path.join(a.out_dir, "synthetic-com3.log"), com3)
        write_bytes(os.path.join(a.out_dir, "synthetic-blackbox.log"), bb)
        write_text(os.path.join(a.out_dir, "synthetic.params"),
                   "# SYNTHETIC test input built by parse-m4.py synth-com3 from a listing; not a record.\n" +
                   "".join(f"{k}={v}\n" for k, v in params.items()))
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    print(f"SYNTH wrote {rel_repo(a.out_dir)}/synthetic-com3.log, synthetic-blackbox.log, synthetic.params "
          f"(profile={a.profile}, fault={a.fault}, com3_bytes={len(com3)}, blackbox_bytes={len(bb)})")
    return 0


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description="The PC side of M4 (m4-design.md §6).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--params", required=True)
    r.add_argument("--blackbox", required=True)
    r.add_argument("--com3", required=True)
    r.add_argument("--run-id", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--csv")
    r.add_argument("--com3-format", choices=("capture", "qemu-serial"), default="capture")
    r.add_argument("--rehearsal", action="store_true")
    r.add_argument("--reset-reason")
    r.add_argument("--fixtures")
    r.add_argument("--blackbox-board-sha256")   # I34: the board's own sha256 of its black box
    r.add_argument("--run-end-epoch", type=int)  # I39: the run's end, for a T-run's CSV row

    s1 = sub.add_parser("size-r1")
    s1.add_argument("--r0-parse", required=True)
    s1.add_argument("--out")

    s2 = sub.add_parser("size-r2")
    s2.add_argument("--r1-parse", required=True)
    s2.add_argument("--r0-parse", required=True)
    s2.add_argument("--out")
    s2.add_argument("--accept-low-n", action="store_true")

    se = sub.add_parser("series")
    se.add_argument("--parse-logs", nargs=5, required=True)
    se.add_argument("--csv", required=True)
    se.add_argument("--cloud-csv", required=True)
    se.add_argument("--out-dir", required=True)

    st = sub.add_parser("selftest")
    st.add_argument("--fixtures", required=True)
    st.add_argument("--m4c")
    st.add_argument("--out-dir", required=True)

    rg = sub.add_parser("regress-7b")
    rg.add_argument("--listing", required=True)
    rg.add_argument("--out-dir", required=True)
    rg.add_argument("--start-marker", default="m4d-ipc-start")
    rg.add_argument("--end-marker", default="m4d-ipc-end")
    rg.add_argument("--e3", choices=("status0", "none"), default="status0")

    kc = sub.add_parser("kshcheck")
    kc.add_argument("file", nargs="?")
    kc.add_argument("--selftest", action="store_true")

    sy = sub.add_parser("synth-com3")
    sy.add_argument("--listing", required=True)
    sy.add_argument("--rung", choices=("r0", "r1"), required=True)
    sy.add_argument("--out-dir", required=True)
    sy.add_argument("--start-marker", default="m4d-ipc-start")
    sy.add_argument("--end-marker", default="m4d-ipc-end")
    sy.add_argument("--e3", choices=("status0", "none"), default="status0")
    sy.add_argument("--vcap", type=int, default=1048576)
    sy.add_argument("--ccap", type=int, default=524288)
    sy.add_argument("--transport", choices=("tcu", "console"), default="console")
    sy.add_argument("--fault", choices=("none", "corrupt-v", "truncate-c", "crlf", "bb-cut"), default="none")
    sy.add_argument("--profile", choices=("tcg", "board"), default="tcg")   # I35

    a = ap.parse_args(argv)
    handlers = {"run": cmd_run, "size-r1": cmd_size_r1, "size-r2": cmd_size_r2, "series": cmd_series,
                "selftest": cmd_selftest, "regress-7b": cmd_regress_7b, "kshcheck": cmd_kshcheck,
                "synth-com3": cmd_synth_com3}
    try:
        return handlers[a.cmd](a)
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    except InputError as e:
        print(f"parse-m4: input error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
