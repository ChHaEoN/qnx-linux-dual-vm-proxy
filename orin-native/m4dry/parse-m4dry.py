#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""parse-m4dry.py: the PC parser for the Phase 3b checklist 7b dry run.

Implements results/orin-native-port/20260909T1100Z/m4-dryrun-design.md §5.7
(revision 2), with the verdict rules of §1.2, the payload rules of §1.3 and
the attempt-1 fixes of §13: classification by printed name only (D-a, D-b),
64-bit host time rebuilt from CONTROL TIME events (D-c), INTERRUPT events
counted by class (D-d), and the filter-byte check of D-h.

    parse-m4dry.py --attempt N --serial FILE --launch FILE --run-dir DIR
                   --out-dir DIR [--traceprinter EXE]
                   [--parse-log NAME.log] [--serial-copy NAME.log|none]

--parse-log and --serial-copy name the two outputs inside --out-dir; the
defaults are attempt<N>-parse.log and attempt<N>-serial.log. A re-parse of an
earlier attempt passes a new --run-dir, a new --parse-log and
--serial-copy none, so nothing that attempt wrote is overwritten.

Steps, numbered as the design's §5.7:
   1. read the raw serial log as bytes, decoded latin-1 (lossless)
   2. write the elided copy, out/attempt<N>-serial.log: base64 elided, <user>
   3. decode each KEV block into run/<name>.kev, md5-checked at both layers
   4. rebuild the FLT block into run/w2.flt; md5, POSIX cksum and line count
   5. parse the record lines; derive w1_covers_banner, ipc_after_guest_ready, ipc
   6. host cross-check: three traceprinter.exe passes per decoded .kev, each
      bounded at 300 s, recounted with exactly the on-target counter's rules
   7. PC-only analysis, every figure tcg_shape_only=1: thread attribution,
      triples, offset order, pairs, dwell, preemption, fallback, transport shape
   8. clock: every clkcmp sample and verdict recomputed; the external reference
   9. the verdict line, plus an ACTION line for an unverified FAIL or PARTIAL
  10. out/attempt<N>-parse.log: M4D-PC key=value lines, headed by input sha256s

What it deliberately does not do: it never trusts a verdict the target printed
(it recomputes), never corrects a target/PC difference (it reports it), never
writes .csv or .txt into out/ (neither is git-ignored), and never writes to
results/hw/. Every figure is evaluation output under NC QDL v7 4.6(i).

Standard library only. Exit 0 when parsing completed, whatever the verdict;
1 on an input error or when a step raised.
"""

import argparse
import base64
import binascii
import gzip
import hashlib
import math
import os
import re
import subprocess
import sys
import time
import zlib

TP_BOUND_S = 300                    # one host traceprinter pass (§5.7 step 6)
IPC_ITERS = 15                      # qnx-host-client 15 /dev/ttyp0 5 (M3's completion rule)
WINDOWS = ("w1", "w2")
PASS_IDS = (0, 1, 7)
P_FORMAT = "M4H|%C|%Z|%z|"          # the on-target counter's own format; no %e (§13 D-a)
M64 = 1 << 64

# Printed subtype name -> Class-10 event ID: m4dry-count.awk's table (§13 D-a, D-b).
# The constants are sys/trace.h:286-293. GUEST_ENTER, GUEST_EXIT, CREATE_VCPU_THREAD
# and CYCLES printed as their suffixes (VERIFIED, attempt 1). The interrupt events
# printed as INTR_RAISE/INTR_LOWER, the reverse word order of RAISE_INTR/LOWER_INTR;
# mapping them to 3 and 4 is HYPOTHESIS. No timer event appeared, so both word
# orders are accepted for 5 and 6 (HYPOTHESIS).
ID = {"GUEST_ENTER": 0, "GUEST_EXIT": 1, "CREATE_VCPU_THREAD": 2,
      "INTR_RAISE": 3, "RAISE_INTR": 3, "INTR_LOWER": 4, "LOWER_INTR": 4,
      "TIMER_CREATE": 5, "CREATE_TIMER": 5, "TIMER_FIRE": 6, "FIRE_TIMER": 6,
      "CYCLES": 7}

PLAN_RE = re.compile(r"QVM|Class 10|GUEST")                 # the plan's filter, plan:395
CORR_RE = re.compile(r"QVM *:")                             # the corrected filter, D1
QCLASS_RE = re.compile(r"QVM|HYP|CLASS[ _]*0*10([^0-9]|$)")  # m4dry-count.awk's class test
NONZERO_RE = re.compile(r"[1-9a-fA-F]")
MSB_RE = re.compile(r"msb:0x([0-9a-fA-F]+)")                        # CONTROL TIME's high word (D-c)
BUFSEQ_RE = re.compile(r"sequence = (\d+), num_events = (\d+)")    # CONTROL BUFFER
TPFMT_T_RE = re.compile(r"\bt:0x([0-9a-fA-F]+)")                    # M4D TPFMT lines (D-h)
HEXVAL = {n: re.compile(re.escape(n) + r":0x([0-9a-fA-F]+)")
          for n in ("at_entry", "at_exit", "clockcycles_offset", "status")}
# traceprinter's default format, "t:0x%08c CPU:%02C %-16Z:%-18z", with -n arguments after it.
EV_RE = re.compile(r"^t:0x([0-9a-fA-F]+)\s+CPU:\s*(\d+)\s+([^:]*?)\s*:(\S*)(.*)$")
ARG_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):(0x[0-9a-fA-F]+|-?[0-9]+)")
KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(\S*)")

KEV_BEGIN = re.compile(r"M4D KEV BEGIN name=(\S+) bytes=(\d+) md5=([0-9a-fA-F]+) "
                       r"gz_bytes=(\d+) gz_md5=([0-9a-fA-F]+) enc=(\S+)")
KEV_END = re.compile(r"M4D KEV END name=(\S+)")
KEV_SKIP = re.compile(r"M4D KEV SKIP name=(\S+) reason=(\S+)")
FLT_BEGIN = re.compile(r"M4D FLT BEGIN name=(\S+) lines=(\d+) of=(\d+) bytes=(\d+) "
                       r"md5=([0-9a-fA-F]+) cksum=(\d+) (\d+)")
FLT_SKIP = re.compile(r"M4D FLT SKIP name=(\S+)")
B64_LINE = re.compile(r"[A-Za-z0-9+/=]*")
BWAIT_RUN = re.compile(r"BWAIT run prog=(\S+) rc=(-?\d+) sig=(\d+) killed=([01]) ms=(\d+)")
CLK_RE = re.compile(r"CLK (HDR|S|VERDICT|SKIP|EXT|NOTE|ERROR)\b ?(.*)$")
MARK_RE = re.compile(r"^MARK (\S+) pc_ms=(\d+)")


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


def iter_lines(path):
    with open(path, "rb") as f:
        for raw in f:
            yield raw.decode("latin-1").rstrip("\r\n")


def to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def kv(text):
    return {k: v for k, v in KV_RE.findall(text)}


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
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ CRC_TABLE[((crc >> 24) ^ b) & 0xFF]
    n = len(data)
    while n:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ CRC_TABLE[((crc >> 24) ^ (n & 0xFF)) & 0xFF]
        n >>= 8
    return (~crc) & 0xFFFFFFFF, len(data)


def mid(a, b):
    """floor((a + b) / 2), the way clkcmp computes it."""
    return a // 2 + b // 2 + (a % 2 + b % 2) // 2


def percentile(sorted_vals, p):
    """Nearest rank."""
    if not sorted_vals:
        return None
    k = max(0, math.ceil(p / 100.0 * len(sorted_vals)) - 1)
    return sorted_vals[min(k, len(sorted_vals) - 1)]


def cycles_to_ns(v, cps):
    if cps is None or cps <= 0:
        return None
    return v * 10**9 // cps if v >= 0 else -((-v) * 10**9 // cps)


class Emitter:
    def __init__(self):
        self.lines = []

    def __call__(self, key, value, shape=False):
        line = f"M4D-PC {key}={value}"
        if shape:
            line += " tcg_shape_only=1"
        self.lines.append(redact(line))

    def raw(self, text):
        self.lines.append(redact("M4D-PC " + text))


# ------------------------------------------------------------------ steps 1-4

def read_serial(path):
    with open(path, "rb") as f:
        data = f.read()
    lines = data.decode("latin-1").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [l.strip("\r") for l in lines]


def split_blocks(lines, attempt):
    """Step 2's elided copy, plus the KEV and FLT blocks found on the way."""
    elided = []
    kev = {}
    flt = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = KEV_BEGIN.search(line)
        if m:
            name = m.group(1)
            blk = {"name": name, "bytes": int(m.group(2)), "md5": m.group(3).lower(),
                   "gz_bytes": int(m.group(4)), "gz_md5": m.group(5).lower(), "enc": m.group(6),
                   "payload": [], "ended": False}
            elided.append(line)
            j = i + 1
            while j < n:
                e = KEV_END.search(lines[j])
                if e and e.group(1) == name:
                    blk["ended"] = True
                    break
                if not B64_LINE.fullmatch(lines[j]):
                    break
                blk["payload"].append(lines[j])
                j += 1
            elided.append(f"[parse-m4dry: {len(blk['payload'])} base64 lines elided; "
                          f"decoded to qhv/m4dry/attempt{attempt}/{name}.kev]")
            kev[name] = blk
            if blk["ended"]:
                elided.append(lines[j])
                i = j + 1
            else:
                i = j
            continue
        m = KEV_SKIP.search(line)
        if m and m.group(1) not in kev:
            kev[m.group(1)] = {"name": m.group(1), "status": f"skipped({m.group(2)})"}
        m = FLT_BEGIN.search(line)
        if m and flt is None:
            name = m.group(1)
            flt = {"name": name, "lines": int(m.group(2)), "of": int(m.group(3)),
                   "bytes": int(m.group(4)), "md5": m.group(5).lower(),
                   "cksum": int(m.group(6)), "cksum_len": int(m.group(7)),
                   "body": [], "ended": False}
            elided.append(line)
            end_line = f"M4D FLT END name={name}"
            j = i + 1
            while j < n:
                if lines[j].rstrip() == end_line:
                    flt["ended"] = True
                    break
                flt["body"].append(lines[j])
                elided.append(lines[j])
                j += 1
            if flt["ended"]:
                elided.append(lines[j])
                i = j + 1
            else:
                i = j
            continue
        if FLT_SKIP.search(line) and flt is None:
            flt = {"skipped": True}
        elided.append(line)
        i += 1
    return elided, kev, flt


def decode_kev(blk, run_dir):
    if "status" in blk:
        return
    if not blk["ended"]:
        blk["status"] = "truncated"
        return
    try:
        gz = base64.b64decode("".join(blk["payload"]), validate=False)
    except (binascii.Error, ValueError):
        blk["status"] = "gz-md5-mismatch"
        return
    if len(gz) != blk["gz_bytes"] or hashlib.md5(gz).hexdigest() != blk["gz_md5"]:
        blk["status"] = "gz-md5-mismatch"
        return
    try:
        data = gzip.decompress(gz)
    except (OSError, EOFError, zlib.error):
        blk["status"] = "md5-mismatch"
        return
    if len(data) != blk["bytes"] or hashlib.md5(data).hexdigest() != blk["md5"]:
        blk["status"] = "md5-mismatch"
        return
    path = os.path.join(run_dir, blk["name"] + ".kev")
    with open(path, "wb") as f:
        f.write(data)
    blk["status"] = "ok"
    blk["path"] = path
    blk["sha256"] = hashlib.sha256(data).hexdigest()


def check_flt(flt, run_dir):
    if flt is None or flt.get("skipped"):
        return "absent"
    body = flt["body"]
    data = ("\n".join(body) + "\n").encode("latin-1") if body else b""
    with open(os.path.join(run_dir, "w2.flt"), "wb") as f:
        f.write(data)
    if not flt["ended"]:
        return "truncated"
    bad = []
    if len(body) != flt["lines"]:
        bad.append("lines")
    if len(data) != flt["bytes"]:
        bad.append("bytes")
    if hashlib.md5(data).hexdigest() != flt["md5"]:
        bad.append("md5")
    crc, ln = posix_cksum(data)
    if crc != flt["cksum"] or ln != flt["cksum_len"]:
        bad.append("cksum")
    return "ok" if not bad else "mismatch(" + "+".join(bad) + ")"


# ------------------------------------------------------------------ step 5

class ClkRun:
    def __init__(self):
        self.hdr = None
        self.samples = []
        self.verdicts = {}
        self.skips = []
        self.errors = []


class Records:
    def __init__(self):
        self.states = []
        self.state_idx = {}
        self.config = {}
        self.stops = {}
        self.probe = None
        self.w2f = None
        self.kevfile = {}
        self.planfilter = {}
        self.corrfilter = {}
        self.qvm = {}
        self.qvmother = {}
        self.qvmfields = {}
        self.markers = {}
        self.hist = {}
        self.qvmtid = {}
        self.samples_seen = {}
        self.reap = {}
        self.tpfmt = []
        self.qpid = None
        self.clkload_done = None
        self.clkload_timeout = False
        self.clksum = []
        self.fails = []
        self.fail_state = []
        self.bwait = []
        self.proc_bwait = {"w1": [], "w2": []}
        self.trcctl = []
        self.samples = None
        self.sentinel = None
        self.p50_seen = False
        self.qvm_rc = None
        self.pos = {}
        self.clk = {"pre": ClkRun(), "load": ClkRun(), "post": ClkRun()}
        self.clk_ext = {}

    def parse(self, lines):
        state = None
        clk_run = None
        for idx, line in enumerate(lines):
            k = line.find("M4D ")
            if k >= 0:
                clk_run, state = self._m4d(idx, line[k + 4:], state, clk_run)
                continue
            k = line.find("CLK ")
            if k >= 0:
                m = CLK_RE.match(line[k:])
                if m:
                    self._clk(m.group(1), m.group(2), clk_run)
                    continue
            k = line.find("TRCCTL ")
            if k >= 0:
                self.trcctl.append((idx, state, line[k:]))
                continue
            m = BWAIT_RUN.search(line)
            if m:
                rec = {"idx": idx, "state": state, "prog": m.group(1), "rc": int(m.group(2)),
                       "sig": int(m.group(3)), "killed": int(m.group(4)), "ms": int(m.group(5))}
                self.bwait.append(rec)
                if state in ("process_w1", "process_w2") and rec["prog"] == "ksh":
                    self.proc_bwait[state[-2:]].append(rec)
                continue
            m = re.search(r"(?:^|\s)samples=(\d+) payload=", line)
            if m and self.samples is None:
                self.samples = int(m.group(1))
            m = re.search(r"sentinel_recoveries=(\d+) sentinel_bounces=(\d+)", line)
            if m and self.sentinel is None:
                self.sentinel = (int(m.group(1)), int(m.group(2)))
            if "P50=" in line:
                self.p50_seen = True
            m = re.fullmatch(r"\s*rc=(-?\d+)\s*", line)
            if m and self.qvm_rc is None:
                self.qvm_rc = int(m.group(1))
            # echo_up is the guest echo server announcing /dev/vcon2
            # (ipc-test/qnx-server/server.c:61), the endpoint the client's /dev/ttyp0
            # reaches. Attempt 1 printed it; ipc_after_guest_ready needs it.
            for key, needle in (("qvm_launch", "=== launching qvm @g2.conf"),
                                ("echo_up", "server: echo endpoint up"),
                                ("guest_banner", "QNX qnx-guest")):
                if key not in self.pos and needle in line:
                    self.pos[key] = idx

    def _m4d(self, idx, body, state, clk_run):
        head, _, rest = body.partition(" ")
        if head == "STATE":
            name = rest.split()[0] if rest.split() else ""
            self.states.append((idx, name))
            self.state_idx.setdefault(name, idx)
            state = name
            clk_run = {"clock_pre": "pre", "clock_post": "post"}.get(name)
        elif head == "CLKLOAD":
            clk_run = "load"
            d = kv(rest)
            if "done_at_w1_stop" in d:
                self.clkload_done = d["done_at_w1_stop"]
            if d.get("wait") == "timeout":
                self.clkload_timeout = True
        elif head == "CONFIG" and not self.config:
            self.config = kv(rest)
        elif head == "STOP":
            parts = rest.split()
            if parts:
                self.stops.setdefault(parts[0], (idx, kv(rest).get("by", "")))
        elif head == "PROBE" and self.probe is None:
            self.probe = kv(rest)
        elif head == "W2F" and self.w2f is None:
            self.w2f = kv(rest)
        elif head in ("KEVFILE", "PLANFILTER", "CORRFILTER", "QVM", "QVMOTHER", "QVMFIELDS",
                      "MARKERS", "HIST", "QVMTID", "SAMPLE", "REAP"):
            parts = rest.split(" ", 1)
            w = parts[0]
            tail = parts[1] if len(parts) > 1 else ""
            if head == "KEVFILE":
                d = kv(tail)
                m = re.search(r"cksum=(\d+) (\d+)", tail)
                if m:
                    d["cksum"], d["cksum_len"] = m.group(1), m.group(2)
                self.kevfile.setdefault(w, d)
            elif head == "PLANFILTER":
                m = re.search(r"lines=(\d*) bytes=(\d*)", tail)
                self.planfilter.setdefault(w, (to_int(m.group(1)), to_int(m.group(2))) if m else (None, None))
            elif head == "CORRFILTER":
                m = re.search(r"lines=(\d*) bytes=(\d*)", tail)
                self.corrfilter.setdefault(w, (to_int(m.group(1)), to_int(m.group(2))) if m else (None, None))
            elif head == "QVM":
                self.qvm.setdefault(w, kv(tail))
            elif head == "QVMOTHER":
                d = kv(tail)
                self.qvmother.setdefault(w, []).append((d.get("sub", ""), to_int(d.get("n"), 0)))
            elif head == "QVMFIELDS":
                self.qvmfields.setdefault(w, kv(tail))
            elif head == "MARKERS":
                self.markers.setdefault(w, kv(tail))
            elif head == "HIST":
                key, _, cnt = tail.rpartition(" ")
                self.hist.setdefault(w, []).append((key, to_int(cnt, 0)))
            elif head == "QVMTID":
                self.qvmtid.setdefault(w, []).append(kv(tail))
            elif head == "SAMPLE":
                self.samples_seen[w] = self.samples_seen.get(w, 0) + 1
            elif head == "REAP":
                pass_name, _, left = tail.partition(" ")
                self.reap.setdefault(w, []).append((pass_name, kv(left).get("left", "")))
        elif head == "TPFMT":
            self.tpfmt.append(rest)
        elif head == "QPID" and self.qpid is None:
            self.qpid = rest.strip()
        elif head == "CLKSUM":
            self.clksum.append(kv(rest))
        elif head == "FAIL":
            self.fails.append(rest.strip())
        elif head == "FAIL_STATE":
            self.fail_state.append(rest.strip())
        return clk_run, state

    def _clk(self, kind, rest, clk_run):
        if kind == "EXT":
            which, _, tail = rest.partition(" ")
            self.clk_ext.setdefault(which, kv(tail))
            return
        if clk_run is None:
            return
        run = self.clk[clk_run]
        d = kv(rest)
        if kind == "HDR" and run.hdr is None:
            run.hdr = d
        elif kind == "S":
            run.samples.append(d)
        elif kind == "VERDICT":
            run.verdicts.setdefault(d.get("mode", "?"), d)
        elif kind == "SKIP":
            run.skips.append(d)
        elif kind in ("NOTE", "ERROR"):
            run.errors.append(kind + " " + rest)


def derived(rec, emit):
    banner = rec.pos.get("guest_banner")
    echo = rec.pos.get("echo_up")
    stop_w1 = rec.stops.get("w1")
    if stop_w1 is None:
        w1_covers = "unknown"
    elif banner is None:
        w1_covers = "no"
    else:
        w1_covers = "yes" if banner < stop_w1[0] else "no"
    emit("w1_covers_banner", w1_covers)
    ipc_state = rec.state_idx.get("ipc")
    if ipc_state is None:
        ready = "n/a"
    else:
        ready = "yes" if (banner is not None and echo is not None
                          and banner < ipc_state and echo < ipc_state) else "no"
    emit("ipc_after_guest_ready", ready)
    client = next((b for b in rec.bwait if b["prog"] == "qnx-host-client"), None)
    if client is None:
        ipc = "skipped"
    else:
        rcv = rec.sentinel[0] if rec.sentinel else None
        ok = (client["rc"] == 0 and client["killed"] == 0 and rec.samples is not None
              and rcv is not None and rec.samples + rcv == IPC_ITERS)
        ipc = "ok" if ok else "failed"
        emit("ipc_client_bwait", f"rc:{client['rc']},killed:{client['killed']}")
        emit("ipc_samples", "none" if rec.samples is None else rec.samples)
        emit("ipc_sentinel_recoveries", "none" if rcv is None else rcv)
    emit("ipc", ipc)
    return w1_covers, ready, ipc


# ------------------------------------------------------------------ step 6

def trim(s):
    return s.strip(" \t")


def hexval(line, name):
    m = HEXVAL[name].search(line)
    return m.group(1) if m else ""


def canon(h):
    h = h.lower().lstrip("0")
    return h if h else "0"


class Counter:
    """m4dry-count.awk, rule for rule (design §5.4 as amended in §13), over the -n -p output."""

    def __init__(self):
        self.n = [0] * 8
        self.qother = self.qvm = self.nonqvm = self.events = self.unformatted = 0
        self.other = {}
        self.cyc_ok = self.cyc_bad = self.off_seen = self.status0 = 0
        self.offs = set()
        self.hist = {}
        self.mk_w1 = self.mk_is = self.mk_ie = 0

    def feed(self, line):
        if "m4d-w1-start" in line:
            self.mk_w1 += 1
        if "m4d-ipc-start" in line:
            self.mk_is += 1
        if "m4d-ipc-end" in line:
            self.mk_ie += 1
        f = line.split("|")
        if f[0] != "M4H":
            self.unformatted += 1
            return
        f += [""] * (5 - len(f))
        self.events += 1
        cls, st = trim(f[2]), trim(f[3])
        key = cls + "|" + st
        self.hist[key] = self.hist.get(key, 0) + 1
        isq = QCLASS_RE.search(cls.upper()) is not None
        cid = ID.get(st, -1)
        if not (isq or cid >= 0):
            self.nonqvm += 1
            return
        self.qvm += 1
        if cid >= 0:
            self.n[cid] += 1
        else:
            self.qother += 1
            self.other[st] = self.other.get(st, 0) + 1
        if cid == 7:
            e = hexval(line, "at_entry")
            x = hexval(line, "at_exit")
            if e and x and NONZERO_RE.search(e) and NONZERO_RE.search(x):
                self.cyc_ok += 1
            else:
                self.cyc_bad += 1
        if cid == 1:
            o = hexval(line, "clockcycles_offset")
            if o:
                self.off_seen += 1
                self.offs.add(canon(o))
            s = hexval(line, "status")
            if s and not NONZERO_RE.search(s):
                self.status0 += 1


def parse_args(rest):
    d = {}
    for k, v in ARG_RE.findall(rest):
        d.setdefault(k, v)
    return d


def argval(args, key):
    v = args.get(key)
    if v is None:
        return None
    try:
        return int(v, 16) if v[:2] in ("0x", "0X") else int(v, 10) % M64
    except ValueError:
        return None


def thread_of(args):
    pid = argval(args, "pid")
    tid = argval(args, "tid")
    if pid is None or tid is None:
        return None
    return (pid, tid)


class Clock64:
    """64-bit host cycles per CPU, rebuilt from traceprinter's CONTROL TIME events (§13 D-c).

    The host traceprinter.exe prints t: as the low 32 bits of the cycle count; its
    -p '%016c' prints the same value zero-padded (checked on this PC against
    attempt 1's w2.kev), although the target binary's use text calls %c the
    64-bit cycle count. Every CONTROL TIME event carries its CPU's high word as
    msb:, and traceprinter emits one when the low word wraps. As a safety net, a
    drop of more than half the 32-bit range between two events on one CPU is also
    taken as a wrap; a smaller drop is only counted, as a backstep.
    """

    def __init__(self):
        self.msb = {}
        self.last = {}
        self.time_events = 0
        self.wraps = 0
        self.backsteps = 0
        self.unknown = 0

    def update(self, cpu, lsb, cls, st, rest):
        prev = self.last.get(cpu)
        self.last[cpu] = lsb
        if cls == "CONTROL" and st == "TIME":
            m = MSB_RE.search(rest)
            if m:
                self.msb[cpu] = int(m.group(1), 16)
                self.time_events += 1
                return (self.msb[cpu] << 32) | lsb
        if prev is not None and lsb < prev:
            if prev - lsb > (1 << 31):
                if cpu in self.msb:
                    self.msb[cpu] += 1
                    self.wraps += 1
            else:
                self.backsteps += 1
        if cpu not in self.msb:
            self.unknown += 1
            return None
        return (self.msb[cpu] << 32) | lsb

    def summary(self):
        return (f"time_events:{self.time_events},wraps_inferred:{self.wraps},"
                f"backsteps:{self.backsteps},unknown:{self.unknown}")


class Analysis:
    """Step 7, and the name-only reading of step 6, in one pass over <name>.n.txt."""

    def __init__(self):
        self.events = 0
        self.unformatted = 0
        self.name_n = [0] * 8
        self.nonqvm = 0
        self.corr_lines = 0
        self.corr_bytes = 0
        self.corr_between_bytes = 0
        self.corr_t64_extra = 0         # D-h: the bytes a 64-bit t: field would add
        self.corr_t64_unknown = 0
        self.clock = Clock64()          # D-c
        self.buffers = {}               # cpu -> [(sequence, num_events)] from CONTROL BUFFER
        self.tmin = None
        self.tmax = None
        self.mk = {"w1_start": None, "ipc_start": None, "ipc_end": None}
        self.running = {}
        self.cur = {}
        self.thr_count = {}
        self.run_cyc = {}
        self.intr = {}                  # D-d: INTERRUPT-class events while a tid runs
        self.intr_by = {}               # tid -> {subtype: count}
        self.intr_sub = {}              # every INTERRUPT-class event, by subtype
        self.thread_events = 0
        self.cycles_threads = {}
        self.unattributed = 0
        self.seq = {}
        self.triples = 0
        self.triples_alt = 0
        self.out_of_order = 0
        self.off_ok = 0
        self.off_bad = 0
        self.off_missing = 0
        self.pairs = 0
        self.pairs_between = 0
        self.dwell = []
        self.dwell_preempted = 0
        self.watch = {}

    def _close(self, cpu, cyc):
        run = self.cur.get(cpu)
        if run is not None:
            th, start = run
            if cyc is not None and start is not None and cyc >= start:
                self.run_cyc[th] = self.run_cyc.get(th, 0) + (cyc - start)
            self.cur[cpu] = None

    def _reset(self, s):
        s["enter"] = None
        s["cycles"] = None
        s["exit"] = None

    def _broken(self, th, s):
        self.out_of_order += 1
        self._reset(s)
        s["last"] = None
        s["prev"] = None
        self.watch.pop(th, None)

    def feed(self, line):
        m = EV_RE.match(line)
        if not m:
            self.unformatted += 1
            return
        self.events += 1
        idx = self.events
        lsb_text = m.group(1)
        cpu = int(m.group(2))
        cls = m.group(3).strip()
        st = m.group(4)
        rest = m.group(5)
        # 64-bit host cycles (D-c); None until this CPU's first CONTROL TIME event.
        cyc = self.clock.update(cpu, int(lsb_text, 16), cls, st, rest)
        if cyc is not None:
            self.tmin = cyc if self.tmin is None else min(self.tmin, cyc)
            self.tmax = cyc if self.tmax is None else max(self.tmax, cyc)
        if cls == "CONTROL" and st == "BUFFER":
            b = BUFSEQ_RE.search(rest)
            if b:
                self.buffers.setdefault(cpu, []).append((int(b.group(1)), int(b.group(2))))
        for key, needle in (("w1_start", "m4d-w1-start"), ("ipc_start", "m4d-ipc-start"),
                            ("ipc_end", "m4d-ipc-end")):
            if self.mk[key] is None and needle in line:
                self.mk[key] = (idx, cyc)
        if CORR_RE.search(line):
            self.corr_lines += 1
            self.corr_bytes += len(line) + 1
            if cyc is None:
                self.corr_t64_unknown += 1
            else:
                self.corr_t64_extra += len("%08x" % cyc) - len(lsb_text)
            if self.mk["ipc_start"] is not None and self.mk["ipc_end"] is None:
                self.corr_between_bytes += len(line) + 1
        nid = ID.get(st, -1)
        isq = QCLASS_RE.search(cls.upper()) is not None
        if nid >= 0:
            self.name_n[nid] += 1
        if not (isq or nid >= 0):
            self.nonqvm += 1

        # THREAD class: THRUNNING and the thread-state events (all TH*).
        if cls.upper() == "THREAD" or st.startswith("TH"):
            self.thread_events += 1
            th = thread_of(parse_args(rest))
            if th is None:
                return
            if st == "THRUNNING":
                # Ends whatever ran on this CPU, and this thread's own interval on
                # any other CPU (a THREAD-class event for that tid, §5.7 step 7).
                for c, run in list(self.cur.items()):
                    if run is not None and (c == cpu or run[0] == th):
                        self._close(c, cyc)
                self.cur[cpu] = (th, cyc)
                self.running[cpu] = th
                self.thr_count[th] = self.thr_count.get(th, 0) + 1
                for wth, w in self.watch.items():
                    if w[0] == cpu and wth != th:
                        w[1] = True
            else:
                for c, run in list(self.cur.items()):
                    if run is not None and run[0] == th:
                        self._close(c, cyc)
            return

        # INTERRUPT events, matched by class (D-d): attempt 1's only subtype,
        # INT_DELIVER, missed the design's subtype pattern. Every subtype is reported.
        if cls.upper() == "INTERRUPT":
            self.intr_sub[st] = self.intr_sub.get(st, 0) + 1
            run = self.cur.get(cpu)
            if run is not None:
                self.intr[run[0]] = self.intr.get(run[0], 0) + 1
                by = self.intr_by.setdefault(run[0], {})
                by[st] = by.get(st, 0) + 1
            return

        if nid not in (0, 1, 7):
            return
        th = self.running.get(cpu)
        if th is None:
            self.unattributed += 1
            return
        args = parse_args(rest)
        s = self.seq.get(th)
        if s is None:
            s = self.seq[th] = {"enter": None, "cycles": None, "exit": None,
                                "last": None, "prev": None, "prev_pre": False}
        if nid == 7:
            self.cycles_threads[th] = self.cycles_threads.get(th, 0) + 1
        if nid == 0:
            if s["enter"] is not None:
                self._broken(th, s)
            s["prev"] = s["last"]
            s["last"] = None
            w = self.watch.pop(th, None)
            s["prev_pre"] = bool(w[1]) if w is not None else False
            s["enter"] = (idx, cyc, cpu, self.mk["ipc_end"] is None)
            s["cycles"] = None
            s["exit"] = None
        elif nid == 7:
            ae = argval(args, "at_entry")
            ax = argval(args, "at_exit")
            if s["enter"] is not None and s["cycles"] is None and s["exit"] is None:
                s["cycles"] = (ae, ax)
            elif s["enter"] is not None and s["cycles"] is None and s["exit"] is not None:
                # GUEST_ENTER, GUEST_EXIT, CYCLES: counted, never paired (the
                # design's triple is ENTER, CYCLES, EXIT).
                self.triples_alt += 1
                self._reset(s)
                s["prev"] = None
            else:
                self._broken(th, s)
        else:
            off = argval(args, "clockcycles_offset")
            if s["enter"] is not None and s["cycles"] is not None and s["exit"] is None:
                self._complete(th, s, cyc, cpu, off)
            elif s["enter"] is not None and s["cycles"] is None and s["exit"] is None:
                s["exit"] = (idx, cyc, cpu, off)
            else:
                self._broken(th, s)

    def _complete(self, th, s, t_exit, cpu, off):
        _, t_enter, _, enter_before_end = s["enter"]
        ae, ax = s["cycles"]
        self.triples += 1
        if ae is None or ax is None or off is None or t_enter is None or t_exit is None:
            self.off_missing += 1
        else:
            # [tsc]: host = guest - offset, the offset signed, with 64-bit wrap. t_enter
            # and t_exit are the rebuilt 64-bit host cycles (D-c), not the 32-bit t: word.
            so = off - M64 if off >= (1 << 63) else off
            he = (ae - so) % M64
            hx = (ax - so) % M64
            if t_enter <= he <= hx <= t_exit:
                self.off_ok += 1
            else:
                self.off_bad += 1
        cur = {"ae": ae, "ax": ax, "after_start": self.mk["ipc_start"] is not None}
        prev = s["prev"]
        if prev is not None and prev["ax"] is not None and ae is not None:
            d = (ae - prev["ax"]) % M64
            if d >= 1 << 63:
                d -= M64
            self.pairs += 1
            self.dwell.append(d)
            if s["prev_pre"]:
                self.dwell_preempted += 1
            if prev["after_start"] and enter_before_end:
                self.pairs_between += 1
        s["last"] = cur
        s["prev"] = None
        self._reset(s)
        self.watch[th] = [cpu, False]


def tp_env(exe):
    env = dict(os.environ)
    qhost = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(exe)), "..", ".."))
    if not env.get("QNX_HOST"):
        env["QNX_HOST"] = qhost
    if not env.get("QNX_TARGET"):
        env["QNX_TARGET"] = os.path.normpath(os.path.join(qhost, "..", "..", "..", "target", "qnx"))
    return env


def run_tp(exe, args, out_path, env, log_path):
    cmd = [exe] + args + ["-o", out_path]
    t0 = time.time()
    res = {"cmd": " ".join(cmd), "rc": None, "timeout": False, "err": ""}
    try:
        with open(log_path, "wb") as lf:
            cp = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.PIPE,
                                timeout=TP_BOUND_S, env=env)
        res["rc"] = cp.returncode
        res["err"] = cp.stderr[:256].decode("latin-1", "replace").strip()
    except subprocess.TimeoutExpired:
        res["timeout"] = True
    except OSError as e:
        res["err"] = str(e)
    fresh = os.path.exists(out_path) and os.path.getmtime(out_path) >= t0 - 2
    res["ok"] = res["rc"] == 0 and not res["timeout"] and fresh
    return res


def cross_check(name, blk, exe, run_dir, emit):
    """Returns the PC recount for one window, or None."""
    out = {"status": None, "events": 0, "non_qvm": 0, "ids": [0] * 8, "counter": None,
           "analysis": None, "plan": (None, None), "corr": (None, None),
           "plan_t64": (None, None), "corr_t64": (None, None)}
    if blk is None or blk.get("status") != "ok":
        why = "kev-" + (blk.get("status", "absent") if blk else "absent")
        out["status"] = f"none({why})"
        return out
    if not exe:
        out["status"] = "none(no-traceprinter)"
        return out
    env = tp_env(exe)
    kev = blk["path"]
    txt = os.path.join(run_dir, name + ".txt")
    ntxt = os.path.join(run_dir, name + ".n.txt")
    ptxt = os.path.join(run_dir, name + ".p.txt")
    passes = {
        "plain": run_tp(exe, ["-f", kev], txt, env, os.path.join(run_dir, name + ".tp-plain.log")),
        "n": run_tp(exe, ["-n", "-f", kev], ntxt, env, os.path.join(run_dir, name + ".tp-n.log")),
        "p": run_tp(exe, ["-n", "-p", P_FORMAT, "-f", kev], ptxt, env, os.path.join(run_dir, name + ".tp-p.log")),
    }
    for k, r in passes.items():
        emit(f"tp_{name}_{k}", f"rc:{r['rc']},timeout:{int(r['timeout'])},ok:{int(r['ok'])}")
        if r["err"]:
            emit(f"tp_{name}_{k}_stderr_head", r["err"].replace(" ", "_")[:200])
    if passes["plain"]["ok"]:
        lines = byts = extra = unknown = 0
        clk = Clock64()
        for l in iter_lines(txt):
            m = EV_RE.match(l)
            t64 = None
            if m:
                t64 = clk.update(int(m.group(2)), int(m.group(1), 16), m.group(3).strip(), m.group(4), m.group(5))
            if PLAN_RE.search(l):
                lines += 1
                byts += len(l) + 1
                if m and t64 is None:
                    unknown += 1
                elif m:
                    extra += len("%08x" % t64) - len(m.group(1))
        out["plan"] = (lines, byts)
        # D-h: the same byte count, as if t: carried the full 64-bit cycle count.
        out["plan_t64"] = (byts + extra, unknown)
    counter = None
    if passes["p"]["ok"]:
        counter = Counter()
        for l in iter_lines(ptxt):
            counter.feed(l)
        out["counter"] = counter
    analysis = None
    if passes["n"]["ok"]:
        analysis = Analysis()
        for l in iter_lines(ntxt):
            analysis.feed(l)
        out["analysis"] = analysis
        out["corr"] = (analysis.corr_lines, analysis.corr_bytes)
        out["corr_t64"] = (analysis.corr_bytes + analysis.corr_t64_extra, analysis.corr_t64_unknown)
    p_complete = counter is not None and counter.events > 0 and counter.unformatted <= counter.events
    n_ok = analysis is not None and analysis.events > 0
    if p_complete:
        out["status"] = "complete"
        out["events"] = counter.events
        out["non_qvm"] = counter.nonqvm
    elif n_ok:
        out["status"] = "name-only"
        out["events"] = analysis.events
        out["non_qvm"] = analysis.nonqvm
    else:
        out["status"] = "none(tp-failed)"
    for i in range(8):
        a = counter.n[i] if counter is not None else 0
        b = analysis.name_n[i] if analysis is not None else 0
        out["ids"][i] = max(a, b)
    return out


# ------------------------------------------------------------------ step 7 output

def emit_analysis(name, pcw, rec, cps, emit):
    a = pcw.get("analysis") if pcw else None
    if a is None:
        emit(f"analysis_{name}", "none", shape=True)
        return "partial(no-extraction)"
    emit(f"analysis_{name}_events", a.events, shape=True)
    emit(f"analysis_{name}_unformatted_lines", a.unformatted, shape=True)
    emit(f"time64_{name}", a.clock.summary(), shape=True)
    if a.tmin is not None:
        emit(f"span_{name}_cycles", a.tmax - a.tmin, shape=True)
    for c in sorted(a.buffers):
        seqs = [q for q, _ in a.buffers[c]]
        emit(f"buffers_{name}_cpu{c}", f"records:{len(seqs)},seq_first:{seqs[0]},seq_last:{seqs[-1]},"
                                       f"seq_max:{max(seqs)}", shape=True)
    emit(f"intr_subtypes_{name}", ",".join(f"{k}:{v}" for k, v in sorted(a.intr_sub.items())) or "none",
         shape=True)
    vcpus = sorted(a.cycles_threads)
    emit(f"analysis_{name}_vcpu_threads", ",".join(f"{p}/{t}" for p, t in vcpus) or "none", shape=True)
    qpid = to_int(rec.qpid)
    if qpid is None and vcpus:
        pids = [p for p, _ in vcpus]
        qpid = max(set(pids), key=pids.count)
    emit(f"analysis_{name}_qvm_pid", "unknown" if qpid is None else qpid, shape=True)
    emit(f"analysis_{name}_unattributed", a.unattributed, shape=True)
    emit(f"analysis_{name}_triples", a.triples, shape=True)
    emit(f"analysis_{name}_triples_enter_exit_cycles", a.triples_alt, shape=True)
    emit(f"analysis_{name}_out_of_order", a.out_of_order, shape=True)
    emit(f"offset_order_{name}", f"ok:{a.off_ok},violated:{a.off_bad},missing:{a.off_missing}", shape=True)
    emit(f"pairs_{name}", a.pairs, shape=True)
    if name == "w2":
        between = a.pairs_between if (a.mk["ipc_start"] and a.mk["ipc_end"]) else "unknown"
        emit(f"pairs_between_markers_{name}", between, shape=True)
    negatives = sum(1 for d in a.dwell if d < 0)
    emit(f"dwell_{name}_negative", negatives, shape=True)
    if a.dwell:
        sv = sorted(a.dwell)
        stats = {"min": sv[0], "p50": percentile(sv, 50), "p99": percentile(sv, 99), "max": sv[-1]}
        emit(f"dwell_guest_cycles_{name}", ",".join(f"{k}:{v}" for k, v in stats.items()), shape=True)
        if cps:
            emit(f"dwell_ns_{name}", ",".join(f"{k}:{cycles_to_ns(v, cps)}" for k, v in stats.items()), shape=True)
    emit(f"dwell_preempted_{name}", a.dwell_preempted, shape=True)

    tids = vcpus or sorted(th for th in a.thr_count if qpid is not None and th[0] == qpid)
    for th in tids:
        subs = "+".join(f"{k}/{v}" for k, v in sorted(a.intr_by.get(th, {}).items())) or "none"
        emit(f"fallback_{name}_{th[0]}_{th[1]}",
             f"thrunning:{a.thr_count.get(th, 0)},running_cycles:{a.run_cyc.get(th, 0)},"
             f"intr:{a.intr.get(th, 0)},intr_subtypes:{subs}", shape=True)
    if a.thread_events == 0:
        fb = "impossible(no-thread-events)"
    elif not tids:
        fb = "impossible(no-qvm-thread)"
    else:
        fb = "characterised"
    emit(f"fallback_{name}", fb, shape=True)

    if name == "w2":
        # §13.3: the span the ring kept against W2 tracelogger's own run, so a wrap
        # shows even when both IPC markers were overwritten (attempt 1).
        tl = next((b for b in rec.bwait if b["prog"] == "tracelogger" and b["state"] == "w2_stop"), None)
        kept = (a.tmax - a.tmin) * 1000 // cps if (cps and a.tmin is not None) else "unknown"
        emit("ring_w2_kept", f"span_ms:{kept},tracelogger_ms:{tl['ms'] if tl else 'unknown'}", shape=True)
        corr_bytes = rec.corrfilter.get("w2", (None, None))[1]
        if corr_bytes is None:
            corr_bytes = a.corr_bytes
        emit("flt_bytes_per_pair", f"{corr_bytes / a.pairs:.1f}" if a.pairs else "n/a", shape=True)
        if (a.mk["ipc_start"] and a.mk["ipc_end"] and cps and a.mk["ipc_start"][1] is not None
                and a.mk["ipc_end"][1] is not None):
            span = a.mk["ipc_end"][1] - a.mk["ipc_start"][1]
            secs = span / cps if span > 0 else 0
            emit("flt_bytes_per_s", f"{a.corr_between_bytes / secs:.1f}" if secs > 0 else "n/a", shape=True)
        else:
            emit("flt_bytes_per_s", "n/a", shape=True)
    return fb


# ------------------------------------------------------------------ step 8

def clk_verdict(samples_eval):
    usable = [s for s in samples_eval if s["usable"]]
    if any(not s["res"] for s in usable):
        return "disagree", usable
    if len(usable) < 3:
        return "unusable", usable
    if all(s["strict"] for s in usable):
        return "agree", usable
    return "agree-within-resolution", usable


def clock(rec, launch, emit):
    selfcheck = []
    summary = {}
    cps = None
    for run_name in ("pre", "load", "post"):
        run = rec.clk[run_name]
        if run.hdr is None and not run.samples:
            summary[run_name] = "not-run"
            emit(f"clock_{run_name}", "not-run")
            continue
        if run.hdr is None:
            summary[run_name] = "no-header"
            emit(f"clock_{run_name}", "no-header")
            continue
        h = run.hdr
        rcps = to_int(h.get("cps"))
        res = to_int(h.get("res_ns"), 0)
        wide = to_int(h.get("wide_ns"), 0)
        if rcps:
            cps = cps or rcps
        by_mode = {}
        for s in run.samples:
            try:
                c0, c1, m0, m1, m2, m3 = (int(s[k]) for k in ("c0", "c1", "m0", "m1", "m2", "m3"))
            except (KeyError, ValueError):
                selfcheck.append(f"{run_name}:unparsable-sample")
                continue
            cc = ((c1 - c0) % M64) * 10**9 // rcps % M64
            mono = (mid(m2, m3) - mid(m0, m1)) % M64
            diff = cc - mono
            err = max(-(1 << 63), min((1 << 63) - 1, diff))
            wa = (m1 - m0) % M64
            wb = (m3 - m2) % M64
            q = -(-10**9 // rcps)
            tol = mid(wa, wb) + 4 * q
            tolres = tol + 2 * res
            migrated = s.get("why") == "migrated"
            usable = (not migrated) and wa <= wide and wb <= wide
            ev = {"usable": usable, "strict": abs(diff) <= tol, "res": abs(diff) <= tolres}
            why = "migrated" if migrated else ("ok" if usable else "wide")
            printed = {"cc_ns": cc, "mono_ns": mono, "err_ns": err, "wA": wa, "wB": wb, "tol_ns": tol,
                       "tolres_ns": tolres, "usable": int(ev["usable"]), "strict": int(ev["strict"]),
                       "res": int(ev["res"])}
            for k, v in printed.items():
                if to_int(s.get(k)) != v:
                    selfcheck.append(f"{run_name}:{s.get('mode')}:{s.get('rep')}:{k}")
            if s.get("why") != why:
                selfcheck.append(f"{run_name}:{s.get('mode')}:{s.get('rep')}:why")
            by_mode.setdefault(s.get("mode", "?"), []).append(ev)
        parts = []
        for mode in ("same0", "same1", "cross"):
            if mode not in by_mode:
                skipped = any(k.get("mode") == mode for k in run.skips)
                parts.append(f"{mode}:{'skipped' if skipped else 'none'}")
                continue
            verdict, usable = clk_verdict(by_mode[mode])
            parts.append(f"{mode}:{verdict}")
            tv = run.verdicts.get(mode)
            tool = tv.get("result") if tv else None
            if tv is None or tool != verdict or to_int(tv.get("usable")) != len(usable) \
                    or to_int(tv.get("strict")) != sum(1 for u in usable if u["strict"]) \
                    or to_int(tv.get("res")) != sum(1 for u in usable if u["res"]):
                selfcheck.append(f"{run_name}:{mode}:verdict")
            emit(f"clock_{run_name}_{mode}_tool", tool if tool else "none")
        summary[run_name] = ",".join(parts)
        emit(f"clock_{run_name}", summary[run_name])
        if run.errors:
            emit(f"clock_{run_name}_notes", len(run.errors))
    for cs in rec.clksum:
        run_name = cs.get("run")
        if run_name in summary and f"{cs.get('mode')}:{cs.get('result')}" not in summary[run_name].split(","):
            selfcheck.append(f"clksum:{run_name}:{cs.get('mode')}")
    emit("clkcmp_selfcheck", "ok" if not selfcheck else "differs(" + ";".join(selfcheck[:12]) + ")")
    emit("clock_load_done_at_w1_stop", rec.clkload_done or "unknown")
    if rec.clkload_timeout:
        emit("clock_load_wait", "timeout")

    ext = "unavailable"
    end = rec.clk_ext.get("end")
    marks = launch["marks"]
    if end and "clk_ext_start" in marks and "clk_ext_end" in marks:
        pc_ms = marks["clk_ext_end"] - marks["clk_ext_start"]
        tgt = to_int(end.get("dmono_ns"))
        if pc_ms > 0 and tgt:
            ext = f"{(tgt / 1e9) / (pc_ms / 1000.0):.4f}"
    poll = launch.get("poll_ms")
    res_ms = 2 * poll if poll else "unknown"
    emit("clock_ext", f"{ext} resolution_ms={res_ms} coarse=1")
    if cps is None:
        start = rec.clk_ext.get("start")
        cps = to_int(start.get("cps")) if start else None
    return summary, ext, res_ms, cps


# ------------------------------------------------------------------ step 9

def verdict(rec, pc, emit):
    usable = []
    for w in WINDOWS:
        kf = rec.kevfile.get(w)
        if not kf or kf.get("path", "none") == "none" or to_int(kf.get("bytes"), 0) <= 0:
            emit(f"usable_{w}", "no(kevfile)")
            continue
        tq = rec.qvm.get(w)
        t_events = to_int(tq.get("events"), 0) if tq else 0
        pcw = pc.get(w)
        pc_events = pcw["events"] if pcw and pcw["status"] in ("complete", "name-only") else 0
        if t_events <= 0 and pc_events <= 0:
            emit(f"usable_{w}", "no(unparsed)")
            continue
        non = to_int(tq.get("non_qvm"), 0) if (tq and t_events > 0) else (pcw["non_qvm"] if pcw else 0)
        if non <= 0:
            emit(f"usable_{w}", "no(no-non-qvm-events)")
            continue
        emit(f"usable_{w}", "yes")
        usable.append(w)

    def tcount(w, i):
        tq = rec.qvm.get(w)
        return to_int(tq.get(f"id{i}"), 0) if tq else 0

    def pcount(w, i):
        pcw = pc.get(w)
        return pcw["ids"][i] if pcw and pcw["status"] in ("complete", "name-only") else 0

    def complete(w):
        return pc.get(w) is not None and pc[w]["status"] == "complete"

    unverified_windows = [w for w in usable if not complete(w)]
    if not usable:
        v = "INCONCLUSIVE"
    elif any(all(tcount(w, i) >= 1 for i in PASS_IDS) for w in usable):
        v = "PASS"
    elif any(all(max(tcount(w, i), pcount(w, i)) >= 1 for i in PASS_IDS) for w in usable):
        # The target alone did not show all three in one window; the PC recount did.
        v = "PASS(pc-only)"
    else:
        present = {i: any(max(tcount(w, i), pcount(w, i)) >= 1 for w in usable) for i in PASS_IDS}

        def verified_zero(i):
            return all(complete(w) and pcount(w, i) == 0 for w in usable)

        if not any(present.values()):
            v = "FAIL" if all(verified_zero(i) for i in PASS_IDS) else "FAIL(unverified)"
        else:
            absent = [i for i in PASS_IDS if not present[i]]
            v = "PARTIAL" if all(verified_zero(i) for i in absent) else "PARTIAL(unverified)"
    return v, usable, unverified_windows


def fields_verdict(rec, pc, usable, emit):
    ok7 = False
    off_seen = False
    distinct = []
    for w in usable:
        tf = rec.qvmfields.get(w) or {}
        c = pc.get(w, {}).get("counter") if pc.get(w) else None
        cbn = max(to_int(tf.get("cycles_both_nonzero"), 0), c.cyc_ok if c else 0)
        ews = max(to_int(tf.get("exit_with_offset"), 0), c.off_seen if c else 0)
        od = to_int(tf.get("offsets_distinct")) if "offsets_distinct" in tf else (len(c.offs) if c else None)
        st0 = to_int(tf.get("exit_status_zero")) if "exit_status_zero" in tf else (c.status0 if c else None)
        emit(f"fields_{w}", f"cycles_both_nonzero:{cbn},exit_with_offset:{ews},offsets_distinct:{od},exit_status_zero:{st0}")
        ok7 = ok7 or cbn >= 1
        off_seen = off_seen or ews >= 1
        if ews >= 1 and od is not None:
            distinct.append(od)
    missing = []
    if not ok7:
        missing.append("id7-cycles")
    if not off_seen:
        missing.append("id1-offset")
    elif not distinct or any(d != 1 for d in distinct):
        missing.append("id1-offset-not-constant")
    return "OK" if not missing else "MISSING(" + "+".join(missing) + ")"


def ontarget_counter(rec, pc):
    for w in WINDOWS:
        passes = rec.proc_bwait.get(w, [])
        if len(passes) >= 2 and passes[1]["killed"] == 1:
            return "timeout"
    for w in WINDOWS:
        if w not in rec.kevfile or rec.kevfile[w].get("path", "none") == "none":
            continue
        tq = rec.qvm.get(w)
        if not tq:
            return "suspect(format)"
        events = to_int(tq.get("events"), 0)
        if events == 0 or to_int(tq.get("unformatted_lines"), 0) > events:
            return "suspect(format)"
        tf = rec.qvmfields.get(w) or {}
        c = pc.get(w, {}).get("counter") if pc.get(w) else None
        if to_int(tq.get("id7"), 0) > 0 and to_int(tf.get("cycles_both_nonzero"), 0) == 0 and c and c.cyc_ok > 0:
            return "suspect(format)"
    # §13 D-a: the name/number comparison (M4D QVMBY) went with %e. The counter is
    # suspect when any per-ID count differs from a complete PC recount of that window.
    for w in WINDOWS:
        tq = rec.qvm.get(w)
        pcw = pc.get(w)
        if not tq or not pcw or pcw.get("status") != "complete":
            continue
        if any(to_int(tq.get(f"id{i}"), 0) != pcw["ids"][i] for i in range(8)):
            return "suspect(xcheck)"
    return "ok"


def ring_state(rec, pc):
    mk = rec.markers.get("w2")
    s = to_int(mk.get("ipc_start"), 0) if mk else 0
    e = to_int(mk.get("ipc_end"), 0) if mk else 0
    if s == 0 and e == 0:
        a = pc.get("w2", {}).get("analysis") if pc.get("w2") else None
        if a is not None:
            s = 1 if a.mk["ipc_start"] else 0
            e = 1 if a.mk["ipc_end"] else 0
    if s > 0 and e > 0:
        ring = "held"
    elif s == 0 and e > 0:
        ring = "wrapped"
    else:
        ring = "unknown"
    p = rec.probe
    if p and p.get("path", "none") != "none" and to_int(p.get("bytes"), 0) > 0 and p.get("marker") == "absent":
        ring = "unknown"
    return ring


def target_time_field(rec):
    """§13 D-h: how the target traceprinter printed t:, from the probe's M4D TPFMT lines."""
    digits = []
    for t in rec.tpfmt:
        m = TPFMT_T_RE.search(t)
        if m:
            digits.append(len(m.group(1)))
    if not digits:
        return "unknown(no-TPFMT-lines)"
    kind = "64bit" if max(digits) > 8 else "low32-or-msb0"
    return f"{kind} lines:{len(digits)},hex_digits:{min(digits)}-{max(digits)}"


# ------------------------------------------------------------------ main

def read_launch(path):
    info = {"marks": {}, "poll_ms": None, "qemu_version": "unknown", "qemu_stopped": None}
    for line in iter_lines(path):
        m = MARK_RE.match(line)
        if m:
            info["marks"].setdefault(m.group(1), int(m.group(2)))
            continue
        m = re.match(r"poll_ms=(\d+)", line)
        if m:
            info["poll_ms"] = int(m.group(1))
        if line.startswith("qemu_version="):
            info["qemu_version"] = line[len("qemu_version="):].strip()
        if line.startswith("QEMU_STOPPED "):
            info["qemu_stopped"] = line[len("QEMU_STOPPED "):].strip()
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description="PC parser for the Phase 3b checklist 7b dry run.")
    ap.add_argument("--attempt", type=int, required=True)
    ap.add_argument("--serial", required=True)
    ap.add_argument("--launch", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--traceprinter")
    ap.add_argument("--parse-log", help="name inside --out-dir; default attempt<N>-parse.log")
    ap.add_argument("--serial-copy", help="name inside --out-dir, or none; default attempt<N>-serial.log")
    a = ap.parse_args(argv)
    parse_log = a.parse_log or f"attempt{a.attempt}-parse.log"
    serial_copy = a.serial_copy or f"attempt{a.attempt}-serial.log"

    emit = Emitter()
    errors = []
    try:
        for nm in (parse_log, serial_copy):
            if nm != "none" and (os.path.basename(nm) != nm or not nm.endswith(".log")):
                raise OSError(f"output name {nm!r} must be a bare *.log file name")
        if parse_log == "none":
            raise OSError("--parse-log cannot be none")
        lines = read_serial(a.serial)
        launch = read_launch(a.launch)
        os.makedirs(a.run_dir, exist_ok=True)
        if not os.path.isdir(a.out_dir):
            raise OSError(f"--out-dir {a.out_dir} does not exist")
    except OSError as e:
        print(f"parse-m4dry: input error: {e}", file=sys.stderr)
        return 1

    emit("parser_sha256", sha256_file(os.path.abspath(__file__)))
    emit("input_serial", f"{a.serial.replace(chr(92), '/')} sha256:{sha256_file(a.serial)}")
    emit("input_launch", f"{a.launch.replace(chr(92), '/')} sha256:{sha256_file(a.launch)}")
    exe = a.traceprinter if a.traceprinter and os.path.exists(a.traceprinter) else None
    if a.traceprinter:
        emit("input_traceprinter", (a.traceprinter.replace(chr(92), "/") + " sha256:" + sha256_file(exe))
             if exe else f"{a.traceprinter} missing")
    emit("attempt", a.attempt)
    emit("serial_lines", len(lines))

    # Steps 2-4.
    elided, kev, flt = split_blocks(lines, a.attempt)
    if serial_copy != "none":
        with open(os.path.join(a.out_dir, serial_copy), "wb") as f:
            f.write(redact("\n".join(elided) + "\n").encode("latin-1", "replace"))
    emit("serial_copy", serial_copy)
    emit("run_dir", a.run_dir.replace(chr(92), "/"))
    for name in WINDOWS:
        blk = kev.get(name)
        if blk is None:
            emit(f"kev_{name}", "absent")
            continue
        try:
            decode_kev(blk, a.run_dir)
        except Exception as e:      # recorded, never fatal to the other steps
            blk["status"] = "md5-mismatch"
            errors.append(f"decode_{name}:{e!r}")
        emit(f"kev_{name}", blk["status"])
    flt_status = check_flt(flt, a.run_dir)
    emit("flt", flt_status)

    # Step 5.
    rec = Records()
    rec.parse(lines)
    emit("variant", rec.config.get("variant", "unknown"))
    emit("trace_set", rec.config.get("trace_set", "unknown"))
    emit("fail_state", ",".join(rec.fail_state) or "none")
    emit("fails", ",".join(rec.fails) or "none")
    emit("states_seen", ",".join(n for _, n in rec.states) or "none")
    emit("qemu_stopped", launch.get("qemu_stopped") or "unknown")
    derived(rec, emit)
    for w in WINDOWS:
        kf = rec.kevfile.get(w)
        emit(f"kevfile_{w}", "none" if not kf else f"path:{kf.get('path')},bytes:{kf.get('bytes')}")
        tp = rec.proc_bwait.get(w, [])
        if tp:
            emit(f"target_passes_{w}", ",".join(f"rc:{b['rc']}/killed:{b['killed']}" for b in tp))

    # Step 6.
    pc = {}
    for w in WINDOWS:
        try:
            pc[w] = cross_check(w, kev.get(w), exe, a.run_dir, emit)
        except Exception as e:
            errors.append(f"cross_check_{w}:{e!r}")
            pc[w] = {"status": "none(parser-error)", "events": 0, "non_qvm": 0, "ids": [0] * 8,
                     "counter": None, "analysis": None, "plan": (None, None), "corr": (None, None),
                     "plan_t64": (None, None), "corr_t64": (None, None)}
        pcw = pc[w]
        emit(f"pc_recount_{w}", pcw["status"])
        tq = rec.qvm.get(w)
        c = pcw.get("counter")
        pairs = [(f"id{i}", to_int(tq.get(f"id{i}")) if tq else None,
                  pcw["ids"][i] if pcw["status"] in ("complete", "name-only") else None) for i in range(8)]
        pairs += [("planfilter_lines", rec.planfilter.get(w, (None, None))[0], pcw["plan"][0]),
                  ("planfilter_bytes", rec.planfilter.get(w, (None, None))[1], pcw["plan"][1]),
                  ("corrfilter_lines", rec.corrfilter.get(w, (None, None))[0], pcw["corr"][0]),
                  ("corrfilter_bytes", rec.corrfilter.get(w, (None, None))[1], pcw["corr"][1]),
                  # D-h: the PC byte counts recomputed as if t: carried the 64-bit cycle count.
                  ("planfilter_bytes_if_t64", rec.planfilter.get(w, (None, None))[1], pcw["plan_t64"][0]),
                  ("corrfilter_bytes_if_t64", rec.corrfilter.get(w, (None, None))[1], pcw["corr_t64"][0])]
        tf = rec.qvmfields.get(w) or {}
        pairs += [("cycles_both_nonzero", to_int(tf.get("cycles_both_nonzero")), c.cyc_ok if c else None),
                  ("exit_with_offset", to_int(tf.get("exit_with_offset")), c.off_seen if c else None),
                  ("offsets_distinct", to_int(tf.get("offsets_distinct")), len(c.offs) if c else None),
                  ("qvm_other", to_int(tq.get("qvm_other")) if tq else None, c.qother if c else None),
                  ("hist_keys", to_int(tq.get("hist_keys")) if tq else None, len(c.hist) if c else None)]
        for field, t, p in pairs:
            if t is None or p is None:
                emit(f"xcheck_{w}_{field}", "n/a")
            else:
                emit(f"xcheck_{w}_{field}", "match" if t == p else f"differ(target={t},pc={p})")
        if c is not None:
            emit(f"pc_counter_{w}", f"events:{c.events},unformatted_lines:{c.unformatted},non_qvm:{c.nonqvm},"
                                    f"qvm_total:{c.qvm},qvm_other:{c.qother},hist_keys:{len(c.hist)}")
            others = ",".join(f"{k}:{v}" for k, v in sorted(c.other.items()))
            emit(f"pc_qvm_other_names_{w}", others or "none")
            qhist = []
            for k, v in sorted(c.hist.items()):
                hcls, _, hsub = k.partition("|")
                if QCLASS_RE.search(hcls.upper()):
                    qhist.append(f"{hsub}:{v}")
            emit(f"pc_hist_qvm_{w}", ",".join(qhist) or "none")
        if w in rec.qvmother:
            emit(f"target_qvm_other_names_{w}", ",".join(f"{s}:{n}" for s, n in rec.qvmother[w]) or "none")
        if w in rec.reap:
            emit(f"reap_{w}", ",".join(f"{p}:{l}" for p, l in rec.reap[w]))
        t64u = (pcw.get("plan_t64", (None, None))[1], pcw.get("corr_t64", (None, None))[1])
        if t64u != (None, None):
            emit(f"pc_t64_unknown_{w}", f"plan:{t64u[0]},corr:{t64u[1]}")

    # Step 8 (before 7: the dwell figures need cps).
    try:
        clk_summary, clk_ext, clk_res_ms, cps = clock(rec, launch, emit)
    except Exception as e:
        errors.append(f"clock:{e!r}")
        clk_summary, clk_ext, clk_res_ms, cps = {}, "unavailable", "unknown", None

    # Step 7.
    fallback = "partial(no-extraction)"
    for w in WINDOWS:
        try:
            fb = emit_analysis(w, pc.get(w), rec, cps, emit)
        except Exception as e:
            errors.append(f"analysis_{w}:{e!r}")
            fb = "partial(no-extraction)"
        if fb == "characterised" or (fb.startswith("impossible") and fallback.startswith("partial")):
            fallback = fb

    # Step 9.
    try:
        v, usable, unverified = verdict(rec, pc, emit)
        fields = fields_verdict(rec, pc, usable, emit)
        counter = ontarget_counter(rec, pc)
        ring = ring_state(rec, pc)
    except Exception as e:
        errors.append(f"verdict:{e!r}")
        v, usable, unverified, fields, counter, ring = "INCONCLUSIVE", [], [], "MISSING(parser-error)", "ok", "unknown"
    emit("target_tp_time_field", target_time_field(rec))
    probe = rec.probe or {}
    w2f = rec.w2f or {}
    stop_w2 = rec.stops.get("w2", (None, "none"))[1]
    line = (f"VERDICT7B={v} fields={fields} "
            f"pc_recount=w1:{pc['w1']['status']},w2:{pc['w2']['status']} ring={ring} "
            f"probe={probe.get('path', 'none')},{w2f.get('reason', 'none')} stop_w2={stop_w2} "
            f"ontarget_counter={counter} clock_pre={clk_summary.get('pre', 'not-run')} "
            f"clock_load={clk_summary.get('load', 'not-run')} clock_post={clk_summary.get('post', 'not-run')} "
            f"clock_ext={clk_ext} ipc={derived_ipc(rec)} fallback={fallback} "
            f"trace_set={rec.config.get('trace_set', 'unknown')} variant={rec.config.get('variant', 'unknown')} "
            f"qemu={launch.get('qemu_version', 'unknown')}")
    emit.raw(line)
    if v in ("FAIL(unverified)", "PARTIAL(unverified)"):
        emit.raw(f"ACTION inspect-hist-then-rerun windows={','.join(unverified) or 'none'}")
    if errors:
        emit("parser_errors", ";".join(errors).replace(" ", "_")[:1000])

    # Step 10.
    with open(os.path.join(a.out_dir, parse_log), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(emit.lines) + "\n")
    print(redact("M4D-PC " + line))
    return 1 if errors else 0


def derived_ipc(rec):
    client = next((b for b in rec.bwait if b["prog"] == "qnx-host-client"), None)
    if client is None:
        return "skipped"
    rcv = rec.sentinel[0] if rec.sentinel else None
    ok = (client["rc"] == 0 and client["killed"] == 0 and rec.samples is not None
          and rcv is not None and rec.samples + rcv == IPC_ITERS)
    return "ok" if ok else "failed"


if __name__ == "__main__":
    sys.exit(main())
