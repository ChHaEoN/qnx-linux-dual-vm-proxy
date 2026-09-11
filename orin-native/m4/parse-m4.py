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
  parse-m4.py size-r1 --r0-parse LOG [--out FILE]
  parse-m4.py size-r2 --r1-parse LOG --r0-parse LOG [--out FILE] [--accept-low-n]
  parse-m4.py series --parse-logs L1 L2 L3 L4 L5 --csv FILE --cloud-csv FILE --out-dir DIR
  parse-m4.py selftest --fixtures DIR [--m4c FILE] --out-dir DIR
  parse-m4.py regress-7b --listing FILE --out-dir DIR
  parse-m4.py kshcheck FILE | --selftest
  parse-m4.py synth-com3 --listing FILE --rung r0|r1 --out-dir DIR [...]   (test input, §14)

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
import hashlib
import importlib.util
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


TOKEN_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("([^"]*)"|\S*)|(\S+)')


def parse_kv(text):
    """key=value tokens (a value may be "quoted") and bare tokens."""
    d = {}
    bare = []
    for m in TOKEN_RE.finditer(text):
        if m.group(1) is not None:
            d.setdefault(m.group(1), m.group(3) if m.group(3) is not None else m.group(2))
        else:
            bare.append(m.group(4))
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
        self.long_lines = 0
        self.oor = 0
        self.cps = DEFAULT_CPS
        self.cps_header = False
        self.seen_event = False
        self.ts = TimeState()
        self.cpu = [{"events": 0, "first_seq": 0, "last_seq": 0, "prev_seq": 0, "kept": 0, "gaps": 0,
                     "restarts": 0, "max_events": 0, "first_t": None, "last_t": None,
                     "restart_seen": False, "restart_t": None, "wrapped": False} for _ in range(MAX_CPUS)]
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
        out = []
        for ch in line:
            if ch in "\n\r\0" or len(out) >= SAMPLE_CHARS:
                break
            out.append("'" if ch == '"' else ch)
        self.samples.append((sub, "".join(out)))

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
                   ("unformatted", self.unformatted), ("long_lines", self.long_lines),
                   ("cpu_out_of_range", self.oor), ("cps", self.cps),
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
        add("RING", [("state", self.ring), ("wrapped_cpus", ",".join(wrapped) or "none"),
                     ("seq1_cpus", ",".join(seq1) or "none")])
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
        self.stops = {}
        self.kevfile = {}
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
    R = Records(texts)
    all_texts = [t for off, t in com3_all if not excluded(off)] + ([t for _, t in bb_all] if bb_all else [])
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
    cmark = rec_first(run_main, "MARK")
    assume_end = None
    if v_capped and cmark and cmark.get("end_t", "-") not in ("-", ""):
        assume_end = int(cmark["end_t"], 16)
        log("xcheck_window", "counter-end-marker(v-capped)")
    if v_body is not None and v_status == "ok":
        L = Listing(start_marker, end_marker, e3_status0=e3, assume_end_t=assume_end).feed_bytes(v_body)
        for name, f in L.records(label="pc", quiet=False):
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
        for raw in iter_raw_lines(c_body):
            parts = raw.decode("latin-1").split()
            if len(parts) != 9 or parts[0] != "c":
                continue
            _, k, cls, elig, dwell, cx, ce, hw, dt = parts
            c_lines[(to_int(dt), to_int(cx))] = (cls, elig, dwell, cx, ce)
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
        compared = 0
        bad = 0
        for p in L.pairs:
            if p["a"] is None or p["b"] is None or p["a"] < L.start_t or p["b"] > limit:
                continue
            key = ((p["a"] - L.start_t), p["cpu_exit"])
            got = c_lines.get(key)
            if got is None:
                if not c_capped:
                    bad += 1
                continue
            compared += 1
            want = ("unk" if p["cls"].startswith("unk") else p["cls"], "1" if p["reason"] == "eligible" else "0",
                    str(p["dwell"]) if p["dwell"] is not None else "-", str(p["cpu_exit"]), str(p["cpu_entry"]))
            if got != want:
                bad += 1
        xp = f"match compared={compared}" if bad == 0 else f"differ({bad}) compared={compared}"
    log("xcheck_pairs", xp)

    p1zero = []
    qv = rec_first(run_main, "QVM") or {}
    ring_t = (rec_first(run_main, "RING") or {}).get("state")
    for key, idname in (("enter", "id0"), ("exit", "id1"), ("cycles", "id7")):
        if to_int(qv.get(key), -1) == 0:
            ok = v_complete and ring_t == "held" and L is not None and L.q[key] == 0
            p1zero.append(f"{idname}:{'yes' if ok else 'no'}")
    log("p1_zero_verified", ",".join(p1zero) or "n/a(no-zero)")

    # Step 6: the verdict.
    crits = []

    def crit(key, ok, why="", na=None):
        if na:
            crits.append((key, f"n/a({na})"))
        else:
            crits.append((key, "pass" if ok else ("fail(" + why + ")" if why else "fail")))

    def has(sub):
        return any(sub in t for t in all_texts)

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
        cfg_rung = R.config.get("rung")
        if cfg_rung != rung and not (a.rehearsal and cfg_rung in (f"tcg-{variant}", rung)):
            why1.append("config-rung")
        if R.config.get("mode") != "full":
            why1.append("config-mode")
        for c in ("md5_pre guest", "md5_pre disk", "md5_pre conf", "disk_copy", "md5_post guest", "md5_post disk"):
            if c not in R.checks:
                why1.append(c.replace(" ", "_"))
        if not has("BWAIT path hit=/dev/qvmdisk0"):
            why1.append("qvmdisk0")
        ql, bn = R.stamps.get("qvm_launch"), R.stamps.get("banner")
        if ql is None or bn is None or bn <= ql:
            why1.append("stamps")
        if not any(BANNER_RE.search(t) for t in all_texts):
            why1.append("banner")
        client = R.bwait_for("qnx-host-client")
        if (client is None or client["rc"] != 0 or client["killed"] != 0 or R.samples is None
                or R.sentinel is None or R.samples + R.sentinel != iters):
            why1.append("ipc")
        if "banner" not in R.mem:
            why1.append("mem_banner")
        if not states_in_order(order_full) or R.fail_state != "none":
            why1.append("states")
        crit("crit_1", not why1, "+".join(why1[:12]))
        why2 = []
        if not R.trace_arm:
            why2.append("arm")
        if R.stops.get("t") != "stop":
            why2.append("stop")
        if to_int(R.kevfile.get("t"), 0) <= 0:
            why2.append("kevfile")
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
            crit("crit_3", not why3, "+".join(why3))
            crit("crit_4", ring_t == "held", f"ring:{ring_t}")
            why5 = []
            if not xp.startswith("match"):
                why5.append("xcheck_pairs")
            if v_complete and xs != "match":
                why5.append("xcheck_stats")
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
        crit("crit_bb", bb is not None and len(bb) < BB_GATE, f"blackbox:{'none' if bb is None else len(bb)}")
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
        if samples <= 0:
            csv_note = "skipped(no-samples)"
        elif not p2p3:
            csv_note = "skipped(p2-or-p3)"
        elif not a.rehearsal and cps_list != BOARD_CPS:
            csv_note = f"refused(cps:{cps_list})"
        else:
            if c_stat == "match":
                pool, cps_c = pc_from_c["clean"]
                n = len(pool)
                p50, p99, mx = (ticks_ns(pool[rank(50, n) - 1], cps_c), ticks_ns(pool[rank(99, n) - 1], cps_c),
                                ticks_ns(pool[-1], cps_c))
                log("csv_source", "pc-recount-of-c")
            else:
                p50, p99, mx = stat.get("p50_ns"), stat.get("p99_ns"), stat.get("max_ns")
                log("csv_source", "target")
            ts_ = iso_epoch(cap.get("end_iso"))
            if ts_ is None:
                ts_ = int(os.path.getmtime(a.com3))
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


def cmd_size_r1(a):
    try:
        r0 = read_parse_log(a.r0_parse)
        if r0.get("rung") != "r0":
            raise InputError(f"{a.r0_parse} is not an r0 parse log (rung={r0.get('rung')})")
        if r0.get("run_verdict") != "pass":
            print(f"SIZE r1 refused: r0 did not pass ({r0.get('run_verdict')}); the owner reviews r0 first")
            return 3
        cps = to_int(parse_composite(r0.get("cnt_l0_in")).get("cps"), DEFAULT_CPS)
        b0 = 0.0
        for key, val in r0.items():
            m = re.match(r"cnt_l0_rate_cpu(\d+)$", key)
            if not m:
                continue
            f = parse_composite(val)
            span = to_int(f.get("span_ticks"))
            bufs = to_int(f.get("bufs_in_window"), 0)
            if span:
                b0 = max(b0, (bufs + 1) / (span / cps))
        if b0 <= 0:
            raise InputError("no L0 RATE records with a span")
        probe_cost = max(0.0, num(r0, "mem_probe_pre") - num(r0, "mem_probe_armed"))
        tp0 = parse_composite(r0.get("tp_l0"))
        cn0 = parse_composite(r0.get("cnt_l0"))
        tp_bps0 = num(r0, "kevfile_l0") / max(to_int(tp0.get("ms"), 1), 1) * 1000
        cnt_bps0 = num(r0, "text_l0") / max(to_int(cn0.get("ms"), 1), 1) * 1000
        tcu_bps0 = num(r0, "tcu_v_bytes_sent") / max(num(r0, "tcu_v_ms"), 1) * 1000
    except InputError as e:
        print(f"parse-m4: input error: {e}", file=sys.stderr)
        return 1
    need1 = math.ceil(16 * b0 * 60) + 2
    k1 = 256 if need1 <= 256 else (512 if need1 <= 512 else "lin")
    kk = 512 if k1 == "lin" else k1
    while 4 * s_mb(kk) * MIB / tp_bps0 > 600:
        if k1 == 512:
            k1 = kk = 256
            continue
        print(f"SIZE r1 owner: traceprinter would need more than 600 s at K={k1} (raise TP_BOUND; §2.4 step 4)")
        return 3
    s = s_mb(kk)
    cnt_bound = 120 if 4 * 5 * s * MIB / cnt_bps0 <= 120 else 300
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
            print("SIZE r1 owner: a block cannot be sent within 600 s at the 65,536 B floor (§2.4 step 6)")
            return 3
        worst = ksh_worst_full(240, 240, 600, cnt_bound, send_v, send_c)
        guard = guard_for(worst)
        if guard <= 2700:
            break
        if cap_v <= 65536 and cap_c <= 65536:
            print(f"SIZE r1 owner: the guard {guard} s exceeds 2,700 s at the cap floor (§2.4 step 7)")
            return 3
        cap_v, cap_c = max(65536, cap_v // 2), max(65536, cap_c // 2)
    ipc = 240
    values = {
        "image": f"m4-r1-{'lin' if k1 == 'lin' else 'k%d' % k1}", "rung": "r1", "mode": "full", "p": 4,
        "kind": "linear" if k1 == "lin" else "ring", "k": k1, "s_mb": s,
        "tl_args": f"-c -S {s}M" if k1 == "lin" else f"-r -k {k1} -M -S {s}M",
        "tl_bound": 2 + ipc + 5 + 160 + 30, "trace_need_mb": trace_need_mb(kk, probe_cost),
        "fmt_need_mb": fmt_need_mb(s, cap_v, cap_c), "cnt_need_mb": cnt_need_mb(cap_v, cap_c),
        "iters": 15, "ipc_bound": ipc, "banner_bound": 240, "grace": 90, "tp_bound": 600, "cnt_bound": cnt_bound,
        "hash_bound": 20, "forms": "v c", "cap_v": cap_v, "cap_c": cap_c, "send_v": send_v, "send_c": send_c,
        "send_t_v": send_v - 5, "send_t_c": send_c - 5, "clean_pred": "-", "p2_reachable": "-",
        "p99_reachable": "-", "accept_low_n": "-", "ksh_worst_s": worst, "guard_s": guard,
        "return_bound_s": guard + 300, "capture_s": guard + 3300,
        "size_from_r0_parse_sha256": sha256_file(a.r0_parse), "size_b0": f"{b0:.3f}", "size_need1": need1,
        "size_probe_cost_mb": f"{probe_cost:.1f}", "size_tp_bps0": f"{tp_bps0:.0f}", "size_cnt_bps0": f"{cnt_bps0:.0f}",
        "size_tcu_bps0": f"{tcu_bps0:.0f}"}
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


def cmd_size_r2(a):
    try:
        r0 = read_parse_log(a.r0_parse)
        r1 = read_parse_log(a.r1_parse)
        if r1.get("rung") != "r1" or r0.get("rung") != "r0":
            raise InputError("size-r2 needs an r1 parse log and an r0 parse log")
        if r1.get("run_verdict") != "pass":
            print(f"SIZE r2 refused: r1 did not pass ({r1.get('run_verdict')})")
            return 3
        if parse_composite(r1.get("cnt_t_ring")).get("state") != "held":
            print("SIZE r2 owner: r1's ring was not held (§2.4 step 1)")
            return 3
        clean1 = to_int(parse_composite(r1.get("cnt_t_pairs")).get("clean"), 0)
        p1 = clean1 / 20
        if p1 <= 0:
            print("SIZE r2 owner: r1 had no eligible clean pair (§2.4 step 1)")
            return 3
        seq_max = 0
        for key, val in r1.items():
            if re.match(r"cnt_t_buf_cpu\d+$", key):
                seq_max = max(seq_max, to_int(parse_composite(val).get("last_seq"), 0))
        beta = seq_max / 20
        fc = parse_composite(r1.get("cnt_t_flt_c"))
        pairs_all1 = to_int(fc.get("pairs_total"), 0)
        bpp1 = to_int(fc.get("bytes"), 0) / max(to_int(fc.get("pairs_written"), 0), 1)
        probe_cost = max(0.0, num(r0, "mem_probe_pre") - num(r0, "mem_probe_armed"))
        tp_ms1 = to_int(parse_composite(r1.get("tp_t")).get("ms"), 0)
        cnt_ms1 = to_int(parse_composite(r1.get("cnt_t")).get("ms"), 0)
        s1 = to_int(r1.get("param_s_mb"), 0)
        rates = []
        for b in ("v", "c"):
            sent = to_int(r1.get(f"tcu_{b}_bytes_sent"))
            ms = to_int(r1.get(f"tcu_{b}_ms"))
            if sent and ms:
                rates.append((sent, sent / ms * 1000))
        if not rates or s1 <= 0:
            raise InputError("r1's parse log lacks the tcu rates or param_s_mb")
        tcu_bps1 = max(rates)[1]
    except InputError as e:
        print(f"parse-m4: input error: {e}", file=sys.stderr)
        return 1
    n_pairs = max(15, math.ceil(15000 / p1) - 5)
    n2 = min(n_pairs, 13200)
    target = "p99"
    while True:
        k2 = max(256, math.ceil(1.5 * beta * (n2 + 5)) + 2) if beta > 0 else 256
        lin = False
        if k2 > 512:
            n_ring = math.floor(510 / (1.5 * beta)) - 5
            if n_ring * p1 >= 1200:
                n2, k2, target = n_ring, 512, "ring-limited"
            else:
                lin = True
        kk = 512 if lin else k2
        s2 = s_mb(kk)
        ipc2 = 240 + (5 * n2 + 99) // 100          # ceil(0.05 x N2) in integers, as the generator recomputes it
        tp2 = min(900, max(120, math.ceil(4 * tp_ms1 / 1000 * s2 / s1) + 60))
        cnt2 = min(600, max(60, math.ceil(4 * cnt_ms1 / 1000 * s2 / s1) + 30))
        cap_c, cap_v = 1048576, 131072
        send_c, send_v = send_s(cap_c, tcu_bps1), send_s(cap_v, tcu_bps1)
        while send_c > 600 and cap_c > 65536:
            cap_c //= 2
            send_c = send_s(cap_c, tcu_bps1)
        while send_v > 600 and cap_v > 65536:
            cap_v //= 2
            send_v = send_s(cap_v, tcu_bps1)
        worst = ksh_worst_full(240, ipc2, tp2, cnt2, send_v, send_c)
        guard2 = guard_for(worst)
        if guard2 <= 3600 or n2 <= 15:
            break
        n2 = max(15, math.floor(n2 * 0.9))
    if guard2 > 3600 or send_c > 600 or send_v > 600:
        print(f"SIZE r2 owner: no N2 fits the 3,600 s guard or the 600 s send bound (guard {guard2})")
        return 3
    clean_pred = math.floor(p1 * (n2 + 5))
    p2 = "yes" if clean_pred >= 1200 else "no"
    p99 = "yes" if clean_pred >= 15000 else ("short-margin" if clean_pred >= 10000 else "no")
    c_capped_pred = "yes" if 1.5 * (pairs_all1 / 20) * (n2 + 5) * bpp1 > cap_c else "no"
    print(f"SIZE clean_pred={clean_pred} p2_reachable={p2} p99_reachable={p99} p99_target={target}")
    if p2 == "no":
        print("SIZE r2 owner: predicted to miss P2 (clean_pred below 1,200); no size file written (§2.4 step 11)")
        return 3
    if p99 == "no" and not a.accept_low_n:
        print("SIZE r2 owner: P99 not quotable at this yield; pass --accept-low-n to build anyway (§2.4 step 11)")
        return 3
    image = f"m4-r2-{'lin' if lin else 'k%d' % k2}-n{n2}"
    values = {
        "image": image, "rung": "r2", "mode": "full", "p": 4, "kind": "linear" if lin else "ring",
        "k": "lin" if lin else k2, "s_mb": s2, "tl_args": f"-c -S {s2}M" if lin else f"-r -k {k2} -M -S {s2}M",
        "tl_bound": 2 + ipc2 + 5 + 160 + 30, "trace_need_mb": trace_need_mb(kk, probe_cost),
        "fmt_need_mb": fmt_need_mb(s2, cap_v, cap_c), "cnt_need_mb": cnt_need_mb(cap_v, cap_c),
        "iters": n2, "ipc_bound": ipc2, "banner_bound": 240, "grace": 90, "tp_bound": tp2, "cnt_bound": cnt2,
        "hash_bound": 20, "forms": "c v", "cap_v": cap_v, "cap_c": cap_c, "send_v": send_v, "send_c": send_c,
        "send_t_v": send_v - 5, "send_t_c": send_c - 5, "clean_pred": clean_pred, "p2_reachable": p2,
        "p99_reachable": p99, "accept_low_n": 1 if (p99 == "no" and a.accept_low_n) else 0,
        "ksh_worst_s": worst, "guard_s": guard2, "return_bound_s": guard2 + 300, "capture_s": guard2 + 3300,
        "size_from_r0_parse_sha256": sha256_file(a.r0_parse), "size_from_r1_parse_sha256": sha256_file(a.r1_parse),
        "size_p99_target": target, "size_c_capped_predicted": c_capped_pred, "size_beta": f"{beta:.3f}",
        "size_p1": f"{p1:.3f}", "size_tcu_bps1": f"{tcu_bps1:.0f}"}
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
    for i in (1, 2, 3, 4):
        name = f"m4fix-{i}.txt"
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

def cmd_synth_com3(a):
    base = os.path.normcase(os.path.abspath(os.path.join(REPO, "qhv")))
    if not os.path.normcase(os.path.abspath(a.out_dir)).startswith(base + os.sep):
        print("parse-m4: refused: synth-com3 writes under qhv/ only", file=sys.stderr)
        return 2
    try:
        data = read_bytes(a.listing)
    except InputError as e:
        print(f"parse-m4: input error: {e}", file=sys.stderr)
        return 1
    # A target traceprinter writes LF only. The 7b listings were re-made on the PC by
    # traceprinter.exe and end every line in CRLF, so a synthetic target block built
    # from them would carry CR bytes the real one never has, and the PC's CR strip
    # (section 6.2) would then fail flt_v on every fault. Normalise first; the crlf
    # fault still injects CR on the capture side.
    data = data.replace(b"\r\n", b"\n")
    w = "l0" if a.rung == "r0" else "t"
    L = Listing(a.start_marker, a.end_marker, e3_status0=(a.e3 == "status0")).feed_bytes(data)
    vbody, vst = verbatim_selection(data, L, a.vcap)
    cbody, cst = compact_list(L, a.ccap, w)
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
    blocks = [("v", vbody)] if a.rung == "r0" else [("v", vbody), ("c", cbody)]
    # Every console line below is invented plumbing around the listing (SYNTHETIC, never a record);
    # it lets run's criteria see the lines a board run would print.
    mode = "trace" if a.rung == "r0" else "full"
    console = ["M4 STATE config",
               f"M4 CONFIG rung={a.rung} mode={mode} synthetic=1 clock=unverified transport={a.transport}",
               "M4 STATE preflight", "M4 MEM boot 900MB/992MB", "M4 STATE rate_pre", "M4 RATES r0 skipped",
               "M4 STATE integrity_pre", "M4 CHECK md5_pre guest ok", "M4 CHECK md5_pre disk ok",
               "M4 CHECK md5_pre conf ok"]
    if a.rung == "r0":
        console += ["M4 STATE clock"]
        console += [f"CLK VERDICT mode={m} usable=5 strict=5 res=5 result=agree" for m in ("same0", "same1", "cross")]
        console += ["M4 STATE fixtures"]
        for i in (1, 2, 3, 4):
            FL = Listing("m4-fix-start", "m4-fix-end").feed_file(os.path.join(HERE, "fixtures", f"m4fix-{i}.txt"))
            frecs = FL.records(label="fix", quiet=True)
            for fname, ff in frecs:
                if fname == "IN":
                    ff["path"] = f"/proc/boot/m4fix-{i}.txt"
            console += render_records(frecs) + ["M4C END w=fix rc=0 reason=ok"]
        console += ["M4 STATE disk", "M4 CHECK disk_copy ok", "BWAIT path hit=/dev/qvmdisk0 ms=5",
                    "M4 MEM disk 750MB/992MB", "M4 STATE probe", "M4 MEM probe_pre 750MB/992MB",
                    "M4 MEM probe_armed 746MB/992MB", "TRCCTL stop rc=0 errno=0", "M4 STOP p by=stop",
                    "M4 MEM probe_stopped 742MB/992MB", "M4 STATE l0", "M4 STOP l0 by=self",
                    "M4 STATE teardown", "M4 STATE release", "M4 MEM released 880MB/992MB",
                    "M4 STATE rate_post", "M4 RATES r1 skipped", "M4 STATE format"]
        runs = [("p", False), (w, True)]
    else:
        console += ["M4 STATE disk", "M4 CHECK disk_copy ok", "BWAIT path hit=/dev/qvmdisk0 ms=5",
                    "M4 MEM disk 750MB/992MB", "M4 STATE hostcheck", "M4 STATE window", "M4 STATE report",
                    "STAMP qvm_launch cycles=1000 cps=31250000 cpu=0 mono_ns=0 bytes=0",
                    "STAMP banner cycles=2000 cps=31250000 cpu=0 mono_ns=0 bytes=0",
                    "QNX qnx-guest 8.0.0 synthetic ARMv8_Foundation_Model aarch64le",
                    "M4 MEM banner 200MB/992MB", "M4 STATE ipc", "M4 MEM trace_pre 200MB/992MB",
                    "M4 TRACE ARM kind=ring args='synthetic' file=/dev/shmem/t.kev bound=797",
                    "M4 STATE report_ipc", "TRCCTL insert id=20 text=m4-ipc-start rc=0 errno=0",
                    "TRCCTL insert id=21 text=m4-ipc-end rc=0 errno=0", "TRCCTL stop rc=0 errno=0",
                    "M4 STOP t by=stop", "samples=15 payload=48 cps=31250000",
                    "sentinel_recoveries=0 sentinel_bounces=0",
                    "BWAIT run prog=qnx-host-client rc=0 sig=0 killed=0 ms=1000",
                    "M4 STATE teardown", "M4 STATE integrity_post", "M4 CHECK md5_post guest ok",
                    "M4 CHECK md5_post disk ok", "M4 STATE release", "M4 MEM released 880MB/992MB",
                    "M4 STATE rate_post", "M4 RATES r1 skipped", "M4 STATE format"]
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
            console += render_records([fv] + ([fc] if a.rung != "r0" else []))
        console += [f"M4C END w={rw} rc=0 reason=ok"]
    console += ["M4 STATE summary", "M4 FAIL_STATE none", "M4 STATE send"]
    pre = "\n".join(console) + "\n"
    com3 = bytearray()
    bb = bytearray(pre.encode())
    com3 += pre.encode()
    for name, body in blocks:
        body_out = body
        if a.fault == "crlf":
            body_out = body.replace(b"\n", b"\r\n")
        crc, ln = posix_cksum(body)
        nlines = body.count(b"\n")
        hashes = ["BWAIT run prog=md5sum rc=0 sig=0 killed=0 ms=10",
                  "BWAIT run prog=toybox rc=0 sig=0 killed=0 ms=10",
                  "BWAIT run prog=toybox rc=0 sig=0 killed=0 ms=10",
                  f"M4 FLT BEGIN name={name} rung={a.rung} lines={nlines} bytes={ln} wc_bytes={ln} "
                  f"md5={hashlib.md5(body).hexdigest()} cksum={crc}"]
        text = "\n".join(hashes) + "\n"
        bb += text.encode()
        com3 += text.encode()
        if a.fault == "corrupt-v" and name == "v" and len(body_out) > 10:
            body_out = body_out[:5] + (b"X" if body_out[5:6] != b"X" else b"Y") + body_out[6:]
        com3 += f"=M4FLT= BEGIN name={name} rung={a.rung}\n".encode() + body_out
        if not (a.fault == "truncate-c" and name == "c"):
            com3 += f"=M4FLT= END name={name}\n".encode()
        tail = []
        if a.transport == "tcu":
            tail = [f"BWAIT run prog=tcu-cat rc=0 sig=0 killed=0 ms=100",
                    f"tcu-cat: bytes_in=33 bytes_sent=33 drops=0 timeouts=0 max_consecutive=0 aborted=0 deadline=0 ms=5 rc=0",
                    f"BWAIT run prog=tcu-cat rc=0 sig=0 killed=0 ms=10000",
                    f"tcu-cat: bytes_in={ln} bytes_sent={ln} drops=0 timeouts=0 max_consecutive=0 aborted=0 deadline=0 ms=10000 rc=0",
                    f"BWAIT run prog=tcu-cat rc=0 sig=0 killed=0 ms=100",
                    f"tcu-cat: bytes_in=20 bytes_sent=20 drops=0 timeouts=0 max_consecutive=0 aborted=0 deadline=0 ms=5 rc=0"]
        tail.append(f"M4 FLT END name={name} rc=0")
        text = "\n".join(tail) + "\n"
        bb += text.encode()
        com3 += text.encode()
    post = "M4 STATE diag\nM4 FAIL_STATE none\nM4 STATE end\n"
    bb += post.encode()
    com3 += post.encode()
    if a.fault == "bb-cut":
        bb = bb[:len(bb) // 2]
    now = int(datetime.now(timezone.utc).timestamp())
    iso = datetime.fromtimestamp(now, timezone.utc).isoformat()
    head = f"--- raw capture started on COM3 at 115200, {iso} epoch={now} seconds=6000 ---\n".encode()
    endl = f"\n--- raw capture ended {iso} bytes={len(com3)} ---\n".encode()
    params = {"image": "synthetic", "rung": a.rung, "mode": "trace" if a.rung == "r0" else "full", "p": 2,
              "variant": "synthetic", "synthetic": 1, "transport": a.transport, "iters": 15, "guard_s": "-",
              "start_marker": a.start_marker, "end_marker": a.end_marker, "e3": a.e3,
              "fixtures": "m4fix-1.txt,m4fix-2.txt,m4fix-3.txt,m4fix-4.txt"}
    try:
        write_bytes(os.path.join(a.out_dir, "synthetic-com3.log"), head + bytes(com3) + endl)
        write_bytes(os.path.join(a.out_dir, "synthetic-blackbox.log"), bytes(bb))
        write_text(os.path.join(a.out_dir, "synthetic.params"),
                   "# SYNTHETIC test input built by parse-m4.py synth-com3 from a TCG listing; not a record.\n" +
                   "".join(f"{k}={v}\n" for k, v in params.items()))
    except Refused as e:
        print(f"parse-m4: refused: {e}", file=sys.stderr)
        return 2
    print(f"SYNTH wrote {rel_repo(a.out_dir)}/synthetic-com3.log, synthetic-blackbox.log, synthetic.params "
          f"(fault={a.fault}, v_bytes={len(vbody)}, c_bytes={len(cbody)})")
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
