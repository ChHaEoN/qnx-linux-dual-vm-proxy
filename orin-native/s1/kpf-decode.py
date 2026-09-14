#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""kpf-decode.py: the page-frame snapshot decoder of S1-F's writer diagnosis (Phase 3b).

Implements results/orin-native-port/20260909T1100Z/s1-design.md §15.5 A2 (revision
3): class counts from the raw /proc/kpageflags and /proc/kpagecount slices that
s1-board.sh's b_kpf_snap takes before and after the quiesce (§15.4.3 phase A step
2). Standard library only.

  kpf-decode.py HEADER [HEADER]
  kpf-decode.py --selftest

A decode is a record only (R45): it describes Linux's CPU-side page ownership at
the snapshot moment and carries no evidential weight on H1 or on where a device
writes after kexec.

Header format (version 1). b_kpf_snap writes one ASCII text file per snapshot
beside its two slice files. One record per line, LF endings, a final newline, no
blank lines, no comments; every record is key=value with no spaces in a value.
The first line is exactly kpf_header=1 (a file that does not start with
kpf_header= is not a header). Scalar lines, each exactly once:

  kpf_header=1
  tag=prequiesce|postquiesce
  boot_id=<the 36-character /proc/sys/kernel/random/boot_id>
  uptime_s=<the first field of /proc/uptime>
  page_size=4096
  flags_file=<basename of the kpageflags slice>
  flags_sha256=<64 lowercase hex>
  count_file=<basename of the kpagecount slice>
  count_sha256=<64 lowercase hex>

optional, each at most once, a _file always with its _sha256:

  utc=YYYYMMDDTHHMMSSZ
  zoneinfo_file=... zoneinfo_sha256=...      (one line each; verified, not decoded)
  buddyinfo_file=... buddyinfo_sha256=...

and one range line per range, tokens in this order:

  range=c1 pfn_start=0xbd000 pfn_count=4096 src_offset=0x5e8000 slice_offset=0
  range=w2 pfn_start=0x100000 pfn_count=565248 src_offset=0x800000 slice_offset=32768

Numbers are decimal or 0x-prefixed lowercase hex. Exactly the ranges c1 (canary
c1's page frames) and w2 (window 2's, which hold c2 and c3), with the design
constants below. src_offset is the byte offset read in /proc (pfn_start * 8).
slice_offset is the range's byte offset inside BOTH slice files: the slices are the
ranges concatenated in header order, so the first range starts at 0 and each next
one where the previous ends. Each slice entry is one u64, little-endian as the
board writes it. File names are bare basenames resolved in the header's directory
(a leading letter or digit, then [A-Za-z0-9._-]).

Classes, first match wins in this order (s1-design §15.5 A2's list; bits 0-26
VENDOR_CLAIM, docs.kernel.org pagemap; bit 32 HYPOTHESIS, R61):

  buddy         BUDDY (10)
  slab          SLAB (7)
  pgtable       PGTABLE (26)
  lru_anon      LRU (5) and ANON (12)        } the design's "LRU anon or file"
  lru_file      LRU (5) without ANON         }
  comp_head     COMPOUND_HEAD (15)           } the design's "compound head or tail"
  comp_tail     COMPOUND_TAIL (16)           }
  nopage        NOPAGE (20)
  reserved      bit 32
  held_other    kpagecount >= 1 and none of the above
  free_or_tail  kpagecount 0 and none of the above

free = buddy or free_or_tail; held = every class except free and nopage.

Output, key=value lines: the limit sentence first; a class legend; per snapshot a
snapshot line, a canary line for c1-c3, 16 mib lines per canary, and 138 w2map
lines (window 2 in 16 MiB buckets, dominant class, ties to the earlier class); then
one transition line for c2 (prequiesce to postquiesce: held_to_free, free_to_held,
held_to_held, plus free_to_free and nopage_either so the fields sum to the page
count), labelled record_only=yes, or result=not-computed with one snapshot; then
decode result=ok. Two headers must share boot_id, carry one tag each, and have
the postquiesce uptime above the prequiesce one. No path other than a basename
is ever printed.

Refusals print decode result=refused reason=R and no class line. R is one of
header-missing, header-malformed, page-size, tag, range, slice-layout,
slice-missing, size-not-multiple-of-8, entry-count, sha256, boot-id-mismatch,
uptime-order. Every input is checked before anything is decoded.

Exit: 0 decoded; 1 an input error (a file present but unreadable); 2 refused, or
a usage error. Every figure from a run is evaluation output under NC QDL v7
4.6(i) and stays in the git-ignored record.
"""

import argparse
import array
import contextlib
import hashlib
import io
import os
import re
import shutil
import struct
import sys
import tempfile

# ------------------------------------------------------------------ design constants

# §15.5 A2: printed by every decode, word for word.
LIMIT = ("kpageflags describe Linux's CPU-side ownership only; they cannot name the device that holds "
         "a page or predict where a device writes after kexec")

PAGE = 4096
MIB = 1 << 20
PAGES_PER_MIB = MIB // PAGE
CANARY_SIZE = 16 * MIB
BUCKET_SIZE = 16 * MIB
W2_BASE = 0x100000000
W2_SIZE = 0x8A000000
# §3.3: the three canaries; c1 sits in window 1, c2 at window 2's base, c3 at its top.
CANARIES = (("c1", 0xBD000000), ("c2", 0x100000000), ("c3", 0x189000000))
# The header's ranges, in the order b_kpf_snap concatenates them: (name, pfn_start, pfn_count).
RANGES = (("c1", 0xBD000000 // PAGE, CANARY_SIZE // PAGE), ("w2", W2_BASE // PAGE, W2_SIZE // PAGE))
CANARY_RANGE = {"c1": "c1", "c2": "w2", "c3": "w2"}
TAGS = ("prequiesce", "postquiesce")
TRANSITION_CANARY = "c2"

KPF_LRU, KPF_SLAB, KPF_BUDDY, KPF_ANON = 5, 7, 10, 12
KPF_COMPOUND_HEAD, KPF_COMPOUND_TAIL, KPF_NOPAGE, KPF_PGTABLE = 15, 16, 20, 26
KPF_RESERVED = 32  # HYPOTHESIS (R61): not in the documented 0-26 set

CLASSES = ("buddy", "slab", "pgtable", "lru_anon", "lru_file", "comp_head", "comp_tail",
           "nopage", "reserved", "held_other", "free_or_tail")
CI = {name: i for i, name in enumerate(CLASSES)}
FREE = frozenset((CI["buddy"], CI["free_or_tail"]))
NOPAGE = CI["nopage"]

REQUIRED = ("kpf_header", "tag", "boot_id", "uptime_s", "page_size",
            "flags_file", "flags_sha256", "count_file", "count_sha256")
OPTIONAL = ("utc", "zoneinfo_file", "zoneinfo_sha256", "buddyinfo_file", "buddyinfo_sha256")
RANGE_KEYS = ("range", "pfn_start", "pfn_count", "src_offset", "slice_offset")

HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
BOOT_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
UPTIME_RE = re.compile(r"^[0-9]+(\.[0-9]+)?$")
NUM_RE = re.compile(r"^(0x[0-9a-f]+|[0-9]+)$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
UTC_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
TOKEN_RE = re.compile(r"^([a-z0-9_]+)=([A-Za-z0-9._:+-]+)$")


class Refused(Exception):
    def __init__(self, reason, detail=""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class InputError(Exception):
    pass


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def q(s):
    """A value for a key=value line: ASCII only, single-quoted when it has a space."""
    s = str(s).encode("ascii", "backslashreplace").decode("ascii").replace("'", '"')
    return f"'{s}'" if (not s or re.search(r"\s", s)) else s


def to_num(s):
    return int(s, 16) if s.startswith("0x") else int(s)


# ------------------------------------------------------------------ classes

def classify(flags, count):
    """One page's class index from its kpageflags and kpagecount entries (first match wins)."""
    if flags >> KPF_BUDDY & 1:
        return CI["buddy"]
    if flags >> KPF_SLAB & 1:
        return CI["slab"]
    if flags >> KPF_PGTABLE & 1:
        return CI["pgtable"]
    if flags >> KPF_LRU & 1:
        return CI["lru_anon"] if flags >> KPF_ANON & 1 else CI["lru_file"]
    if flags >> KPF_COMPOUND_HEAD & 1:
        return CI["comp_head"]
    if flags >> KPF_COMPOUND_TAIL & 1:
        return CI["comp_tail"]
    if flags >> KPF_NOPAGE & 1:
        return NOPAGE
    if flags >> KPF_RESERVED & 1:
        return CI["reserved"]
    if count >= 1:
        return CI["held_other"]
    return CI["free_or_tail"]


def u64_entries(data):
    """The slice's little-endian u64 entries."""
    a = array.array("Q")
    if a.itemsize != 8:
        return list(struct.unpack(f"<{len(data) // 8}Q", data))
    a.frombytes(data)
    if sys.byteorder != "little":
        a.byteswap()
    return a


def classify_slice(flags_bytes, count_bytes):
    """A bytearray holding one class index per page."""
    out = bytearray(len(flags_bytes) // 8)
    cache = {}
    for i, (fl, ct) in enumerate(zip(u64_entries(flags_bytes), u64_entries(count_bytes))):
        k = fl if ct == 0 else ~fl
        v = cache.get(k)
        if v is None:
            v = cache[k] = classify(fl, ct)
        out[i] = v
    return out


def class_counts(cls):
    return [cls.count(i) for i in range(len(CLASSES))]


def fmt_counts(counts):
    return " ".join(f"{name}={counts[i]}" for i, name in enumerate(CLASSES))


def held_free(counts):
    free = sum(counts[i] for i in FREE)
    return sum(counts) - free - counts[NOPAGE], free


def dominant(counts):
    best = max(counts)
    return CLASSES[counts.index(best)]


# ------------------------------------------------------------------ header and slices

def read_header(path):
    base = os.path.basename(path)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raise Refused("header-missing", f"{base} not found")
    except OSError as e:
        raise InputError(f"{base}: {e.strerror}")
    if not raw.startswith(b"kpf_header="):
        raise Refused("header-missing", f"{base} is not a kpf header")
    if any(b > 0x7E or (b < 0x20 and b != 0x0A) for b in raw):
        raise Refused("header-malformed", f"{base}: a CR, NUL, control or non-ASCII byte")
    if not raw.endswith(b"\n"):
        raise Refused("header-malformed", f"{base}: no final newline")
    lines = raw.decode("ascii")[:-1].split("\n")
    if lines[0] != "kpf_header=1":
        raise Refused("header-malformed", f"{base}: header version is not 1")

    kv, ranges = {}, []
    for n, line in enumerate(lines, 1):
        tokens = line.split(" ")
        pairs = []
        for t in tokens:
            m = TOKEN_RE.match(t)
            if not m:
                raise Refused("header-malformed", f"{base} line {n}: not key=value")
            pairs.append((m.group(1), m.group(2)))
        if pairs[0][0] == "range":
            if tuple(k for k, _ in pairs) != RANGE_KEYS:
                raise Refused("header-malformed", f"{base} line {n}: range tokens not {','.join(RANGE_KEYS)}")
            rng = dict(pairs)
            for k in RANGE_KEYS[1:]:
                if not NUM_RE.match(rng[k]):
                    raise Refused("header-malformed", f"{base} line {n}: {k} not a number")
            ranges.append((rng["range"], to_num(rng["pfn_start"]), to_num(rng["pfn_count"]),
                           to_num(rng["src_offset"]), to_num(rng["slice_offset"])))
            continue
        if len(pairs) != 1:
            raise Refused("header-malformed", f"{base} line {n}: more than one token")
        k, v = pairs[0]
        if k not in REQUIRED and k not in OPTIONAL:
            raise Refused("header-malformed", f"{base} line {n}: unknown key {k}")
        if k in kv:
            raise Refused("header-malformed", f"{base} line {n}: duplicate key {k}")
        kv[k] = v

    for k in REQUIRED:
        if k not in kv:
            raise Refused("header-malformed", f"{base}: missing {k}")
    for stem in ("zoneinfo", "buddyinfo"):
        if (f"{stem}_file" in kv) != (f"{stem}_sha256" in kv):
            raise Refused("header-malformed", f"{base}: {stem}_file and {stem}_sha256 come together")
    checks = [("boot_id", BOOT_ID_RE), ("uptime_s", UPTIME_RE), ("page_size", NUM_RE)]
    checks += [(k, NAME_RE) for k in kv if k.endswith("_file")]
    checks += [(k, HEX64_RE) for k in kv if k.endswith("_sha256")]
    if "utc" in kv:
        checks.append(("utc", UTC_RE))
    for k, rx in checks:
        if not rx.match(kv[k]):
            raise Refused("header-malformed", f"{base}: {k} malformed")
    names = [kv[k] for k in kv if k.endswith("_file")]
    if len(set(names)) != len(names) or base in names:
        raise Refused("header-malformed", f"{base}: a file named twice, or the header named as a slice")

    if to_num(kv["page_size"]) != PAGE:
        raise Refused("page-size", f"{base}: page_size={kv['page_size']}, the design reads 4 KiB pages")
    if kv["tag"] not in TAGS:
        raise Refused("tag", f"{base}: tag={kv['tag']}, not prequiesce or postquiesce")

    if [r[0] for r in ranges] != [r[0] for r in RANGES]:
        raise Refused("range", f"{base}: ranges {','.join(r[0] for r in ranges) or 'none'}, the design reads c1,w2")
    offset = 0
    for (name, start, count, src, slice_off), (_, want_start, want_count) in zip(ranges, RANGES):
        if (start, count) != (want_start, want_count):
            raise Refused("range", f"{base}: range {name} is not the design's page frames")
        if src != start * 8:
            raise Refused("range", f"{base}: range {name} src_offset is not pfn_start*8")
        if slice_off != offset:
            raise Refused("slice-layout", f"{base}: range {name} slice_offset is not {offset}")
        offset += count * 8
    return {"base": base, "dir": os.path.dirname(os.path.abspath(path)), "sha256": sha256(raw),
            "kv": kv, "ranges": ranges, "bytes": offset}


def read_slice(hdr, key, want_bytes):
    name = hdr["kv"][f"{key}_file"]
    path = os.path.join(hdr["dir"], name)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        raise Refused("slice-missing", f"{hdr['base']}: {name} not found")
    except OSError as e:
        raise InputError(f"{name}: {e.strerror}")
    if want_bytes is not None:
        if len(data) % 8:
            raise Refused("size-not-multiple-of-8", f"{name}: {len(data)} bytes")
        if len(data) != want_bytes:
            raise Refused("entry-count", f"{name}: {len(data) // 8} entries, header {want_bytes // 8}")
    if sha256(data) != hdr["kv"][f"{key}_sha256"]:
        raise Refused("sha256", f"{name}: sha256 differs from the header")
    return data


def load_snapshot(path):
    hdr = read_header(path)
    hdr["flags"] = read_slice(hdr, "flags", hdr["bytes"])
    hdr["count"] = read_slice(hdr, "count", hdr["bytes"])
    for stem in ("zoneinfo", "buddyinfo"):
        if f"{stem}_file" in hdr["kv"]:
            read_slice(hdr, stem, None)
    return hdr


# ------------------------------------------------------------------ decode

def canary_pages(snap, canary):
    """The class indices of one canary's pages."""
    base = dict(CANARIES)[canary]
    rname = CANARY_RANGE[canary]
    cls = snap["cls"][rname]
    start = dict((r[0], r[1]) for r in RANGES)[rname]
    first = base // PAGE - start
    return cls[first:first + CANARY_SIZE // PAGE]


def snapshot_lines(snap):
    kv = snap["kv"]
    tag = kv["tag"]
    out = [f"snapshot tag={tag} header={q(snap['base'])} boot_id={kv['boot_id']} uptime_s={kv['uptime_s']} "
           f"header_sha256={snap['sha256']} flags_sha256={kv['flags_sha256']} count_sha256={kv['count_sha256']} "
           f"sha256_check=ok entries={snap['bytes'] // 8} ranges={','.join(r[0] for r in RANGES)}"]
    for name, base in CANARIES:
        counts = class_counts(canary_pages(snap, name))
        held, free = held_free(counts)
        out.append(f"canary tag={tag} name={name} phys={base:#x} size={CANARY_SIZE:#x} pages={sum(counts)} "
                   f"held={held} free={free} {fmt_counts(counts)}")
    for name, base in CANARIES:
        pages = canary_pages(snap, name)
        for i in range(CANARY_SIZE // MIB):
            counts = class_counts(pages[i * PAGES_PER_MIB:(i + 1) * PAGES_PER_MIB])
            out.append(f"mib tag={tag} name={name} index={i} phys={base + i * MIB:#x} pages={sum(counts)} "
                       f"{fmt_counts(counts)}")
    w2 = snap["cls"]["w2"]
    per_bucket = BUCKET_SIZE // PAGE
    at = {base: name for name, base in CANARIES}
    for b in range(W2_SIZE // BUCKET_SIZE):
        counts = class_counts(w2[b * per_bucket:(b + 1) * per_bucket])
        phys = W2_BASE + b * BUCKET_SIZE
        out.append(f"w2map tag={tag} bucket={b} phys={phys:#x} pages={sum(counts)} canary={at.get(phys, '-')} "
                   f"dominant={dominant(counts)} {fmt_counts(counts)}")
    return out


def transition_line(pre, post):
    a = canary_pages(pre, TRANSITION_CANARY)
    b = canary_pages(post, TRANSITION_CANARY)
    n = {"held_to_free": 0, "free_to_held": 0, "held_to_held": 0, "free_to_free": 0, "nopage_either": 0}
    for x, y in zip(a, b):
        if x == NOPAGE or y == NOPAGE:
            n["nopage_either"] += 1
        else:
            n[("free" if x in FREE else "held") + "_to_" + ("free" if y in FREE else "held")] += 1
    fields = " ".join(f"{k}={v}" for k, v in n.items())
    return (f"transition name={TRANSITION_CANARY} from=prequiesce to=postquiesce pages={len(a)} {fields} "
            f"record_only=yes")


def decode(paths):
    """(exit code, output lines). Every input is checked before any class line is made."""
    lines = [f"limit: {LIMIT}"]
    try:
        snaps = [load_snapshot(p) for p in paths]
        if len(snaps) == 2:
            tags = sorted(s["kv"]["tag"] for s in snaps)
            if tags != sorted(TAGS):
                raise Refused("tag", "two headers need one prequiesce and one postquiesce")
            if snaps[0]["kv"]["boot_id"] != snaps[1]["kv"]["boot_id"]:
                raise Refused("boot-id-mismatch", "the two snapshots come from different boots")
            snaps.sort(key=lambda s: TAGS.index(s["kv"]["tag"]))
            if float(snaps[1]["kv"]["uptime_s"]) <= float(snaps[0]["kv"]["uptime_s"]):
                raise Refused("uptime-order", "postquiesce uptime is not above prequiesce uptime")
    except Refused as e:
        lines.append(f"decode result=refused reason={e.reason} detail={q(e.detail)}")
        return 2, lines
    except InputError as e:
        lines.append(f"decode result=input-error detail={q(e)}")
        return 1, lines

    for s in snaps:
        offs = {r[0]: r[4] for r in s["ranges"]}
        s["cls"] = {}
        for name, _, count in RANGES:
            lo, hi = offs[name], offs[name] + count * 8
            s["cls"][name] = classify_slice(s["flags"][lo:hi], s["count"][lo:hi])
    bits = (f"buddy:{KPF_BUDDY},slab:{KPF_SLAB},pgtable:{KPF_PGTABLE},lru:{KPF_LRU},anon:{KPF_ANON},"
            f"comp_head:{KPF_COMPOUND_HEAD},comp_tail:{KPF_COMPOUND_TAIL},nopage:{KPF_NOPAGE},"
            f"reserved:{KPF_RESERVED}")
    lines.append(f"classes order={','.join(CLASSES)} precedence=first-match bits={bits} "
                 f"held_other=count>=1 free_or_tail=count=0 free=buddy,free_or_tail "
                 f"evidence='bits 0-26 VENDOR_CLAIM (docs.kernel.org pagemap); bit 32 HYPOTHESIS (R61)'")
    for s in snaps:
        lines.extend(snapshot_lines(s))
    if len(snaps) == 2:
        lines.append(transition_line(snaps[0], snaps[1]))
    else:
        lines.append(f"transition name={TRANSITION_CANARY} result=not-computed reason=one-snapshot record_only=yes")
    lines.append(f"decode result=ok snapshots={len(snaps)}")
    lines.append(f"limit: {LIMIT}")
    return 0, lines


def cmd_decode(paths):
    rc, lines = decode(paths)
    for ln in lines:
        print(ln)
    if rc:
        print(f"kpf-decode: {lines[-1]}", file=sys.stderr)
    return rc


# ------------------------------------------------------------------ selftest (synthetic inputs only)

def BIT(b):
    return 1 << b


FIX_BOOT = "00000000-1111-4222-8333-444444444444"
FIX_BOOT2 = "00000000-1111-4222-8333-555555555555"


def _fill(buf, first_page, pages, value):
    buf[first_page * 8:(first_page + pages) * 8] = struct.pack("<Q", value) * pages


class _Snap:
    """Synthetic flags and count slices for c1 and w2, as b_kpf_snap concatenates them."""

    def __init__(self):
        self.flags = {name: bytearray(count * 8) for name, _, count in RANGES}
        self.count = {name: bytearray(count * 8) for name, _, count in RANGES}

    def set(self, rname, first_page, pages, flags, count=0):
        _fill(self.flags[rname], first_page, pages, flags)
        _fill(self.count[rname], first_page, pages, count)

    def blobs(self):
        return (b"".join(bytes(self.flags[r[0]]) for r in RANGES),
                b"".join(bytes(self.count[r[0]]) for r in RANGES))


def _header_text(tag, boot_id, uptime, ff, fsha, cf, csha, ranges=None, extra=()):
    lines = ["kpf_header=1", f"tag={tag}", f"boot_id={boot_id}", f"uptime_s={uptime}", "page_size=4096",
             f"flags_file={ff}", f"flags_sha256={fsha}", f"count_file={cf}", f"count_sha256={csha}"]
    lines += list(extra)
    if ranges is None:
        ranges, off = [], 0
        for name, start, count in RANGES:
            ranges.append(f"range={name} pfn_start={start:#x} pfn_count={count} src_offset={start * 8:#x} "
                          f"slice_offset={off}")
            off += count * 8
    lines += ranges
    return "\n".join(lines) + "\n"


def _kv(line):
    return dict(t.split("=", 1) for t in line.split(" ") if "=" in t)


def _find(lines, prefix):
    hits = [ln for ln in lines if ln.startswith(prefix + " ") or ln == prefix]
    return _kv(hits[0]) if len(hits) == 1 else None


def selftest():
    results = []

    def check(name, cond):
        results.append(bool(cond))
        print(f"KPF-SELFTEST {name} {'ok' if cond else 'FAIL'}")

    # ---- constants
    check("constants c2 at window 2's base", dict(CANARIES)["c2"] == W2_BASE)
    check("constants c3 is window 2's top 16 MiB", dict(CANARIES)["c3"] + CANARY_SIZE == W2_BASE + W2_SIZE)
    check("constants c1 range is c1's page frames", RANGES[0] == ("c1", 0xBD000, 4096))
    check("constants w2 range is window 2's page frames", RANGES[1] == ("w2", 0x100000, 0x8A000))
    check("constants 138 buckets of 16 MiB", W2_SIZE % BUCKET_SIZE == 0 and W2_SIZE // BUCKET_SIZE == 138)
    check("constants limit sentence", LIMIT == "kpageflags describe Linux's CPU-side ownership only; they cannot "
          "name the device that holds a page or predict where a device writes after kexec")

    # ---- classes, one per class, then precedence
    table = [
        ("buddy", BIT(10), 0), ("slab", BIT(7), 0), ("pgtable", BIT(26), 1),
        ("lru_anon", BIT(5) | BIT(12), 1), ("lru_file", BIT(5), 1), ("comp_head", BIT(15), 0),
        ("comp_tail", BIT(16), 0), ("nopage", BIT(20), 0), ("reserved", BIT(32), 0),
        ("held_other", BIT(2) | BIT(3), 2), ("free_or_tail", 0, 0), ("free_or_tail", BIT(3), 0),
        ("slab", BIT(7) | BIT(16), 0), ("slab", BIT(7) | BIT(5), 1), ("buddy", BIT(10) | BIT(7), 0),
        ("lru_anon", BIT(5) | BIT(12) | BIT(15), 1), ("pgtable", BIT(26) | BIT(32), 1),
        ("reserved", BIT(32), 3), ("nopage", BIT(20), 1),
    ]
    for want, flags, count in table:
        check(f"class {want} flags={flags:#x} count={count}", CLASSES[classify(flags, count)] == want)
    check("class every class reachable", {w for w, _, _ in table} == set(CLASSES))
    sl = classify_slice(struct.pack("<3Q", BIT(7), 0, BIT(5)), struct.pack("<3Q", 0, 1, 0))
    check("class slice decode matches classify", list(sl) == [CI["slab"], CI["held_other"], CI["lru_file"]])

    tdir = tempfile.mkdtemp(prefix="kpf-selftest-")
    try:
        _selftest_files(tdir, check)
    finally:
        shutil.rmtree(tdir, ignore_errors=True)

    ok = all(results)
    print(f"KPF-SELFTEST result={'ok' if ok else 'fail'} cases={len(results)} failed={results.count(False)}")
    return 0 if ok else 1


def _selftest_files(tdir, check):
    c2_first = 0  # c2 is w2's first page
    c3_first = (dict(CANARIES)["c3"] - W2_BASE) // PAGE
    per_bucket = BUCKET_SIZE // PAGE

    def mib(i):
        return c2_first + i * PAGES_PER_MIB

    # prequiesce: c2 holds one MiB of each class, the rest free_or_tail; precedence pages inside MiB 0 and 3
    pre = _Snap()
    pre.set("c1", 0, 4096, BIT(10))
    for i, (flags, count) in enumerate([(BIT(7), 0), (BIT(10), 0), (BIT(26), 1), (BIT(5) | BIT(12), 1),
                                        (BIT(5), 1), (BIT(15), 0), (BIT(16), 0), (BIT(20), 0),
                                        (BIT(32), 0), (BIT(2) | BIT(3), 2)]):
        pre.set("w2", mib(i), PAGES_PER_MIB, flags, count)
    pre.set("w2", mib(0), 1, BIT(7) | BIT(16))
    pre.set("w2", mib(0) + 1, 1, BIT(7) | BIT(5), 1)
    pre.set("w2", mib(3), 1, BIT(5) | BIT(12) | BIT(15), 1)
    pre.set("w2", c3_first, 4096, BIT(5), 1)
    pre.set("w2", 1 * per_bucket, per_bucket, BIT(7))
    pre.set("w2", 2 * per_bucket, per_bucket // 2, BIT(26), 1)
    pre.set("w2", 2 * per_bucket + per_bucket // 2, per_bucket // 2, BIT(5) | BIT(12), 1)

    # postquiesce: c2 MiB by MiB, the expected transition noted
    post = _Snap()
    post.set("w2", mib(0), PAGES_PER_MIB, BIT(10))           # slab -> buddy          held_to_free
    post.set("w2", mib(1), PAGES_PER_MIB, BIT(7))            # buddy -> slab          free_to_held
    post.set("w2", mib(2), PAGES_PER_MIB, BIT(26), 1)        # pgtable -> pgtable     held_to_held
    #                                                          lru_anon -> free_or_tail held_to_free
    post.set("w2", mib(4), PAGES_PER_MIB, BIT(5), 1)         # lru_file -> lru_file   held_to_held
    post.set("w2", mib(5), PAGES_PER_MIB, BIT(15))           # comp_head -> comp_head held_to_held
    post.set("w2", mib(6), PAGES_PER_MIB, BIT(10))           # comp_tail -> buddy     held_to_free
    post.set("w2", mib(7), PAGES_PER_MIB, BIT(20))           # nopage -> nopage       nopage_either
    post.set("w2", mib(8), PAGES_PER_MIB, BIT(32))           # reserved -> reserved   held_to_held
    post.set("w2", mib(9), PAGES_PER_MIB, 0, 1)              # held_other -> held_other held_to_held
    post.set("w2", mib(10), PAGES_PER_MIB, BIT(20))          # free_or_tail -> nopage nopage_either
    #                                                          MiB 11-15 free -> free  free_to_free

    def write(name, data):
        with open(os.path.join(tdir, name), "wb") as fh:
            fh.write(data)
        return sha256(data)

    def header(name, text):
        p = os.path.join(tdir, name)
        with open(p, "wb") as fh:
            fh.write(text.encode("latin-1") if isinstance(text, str) else text)
        return p

    pf, pc = pre.blobs()
    qf, qc = post.blobs()
    pfs, pcs = write("t-kpf-prequiesce.flags.bin", pf), write("t-kpf-prequiesce.count.bin", pc)
    qfs, qcs = write("t-kpf-postquiesce.flags.bin", qf), write("t-kpf-postquiesce.count.bin", qc)
    zs = write("t-kpf-prequiesce.zoneinfo.txt", b"Node 0, zone Normal\n")
    pre_text = _header_text("prequiesce", FIX_BOOT, "100.25", "t-kpf-prequiesce.flags.bin", pfs,
                            "t-kpf-prequiesce.count.bin", pcs,
                            extra=("utc=20260914T120000Z", "zoneinfo_file=t-kpf-prequiesce.zoneinfo.txt",
                                   f"zoneinfo_sha256={zs}"))
    post_text = _header_text("postquiesce", FIX_BOOT, "240.5", "t-kpf-postquiesce.flags.bin", qfs,
                             "t-kpf-postquiesce.count.bin", qcs)
    pre_h = header("t-kpf-prequiesce.hdr", pre_text)
    post_h = header("t-kpf-postquiesce.hdr", post_text)

    # ---- a two-snapshot decode
    rc, lines = decode([pre_h, post_h])
    check("decode pair exit 0", rc == 0)
    check("decode pair limit sentence first and last", lines[0] == f"limit: {LIMIT}" and lines[-1] == lines[0])
    check("decode pair result line", _find(lines, "decode result=ok snapshots=2") is not None)
    check("decode pair prints no directory", not any(tdir in ln or os.path.basename(tdir) in ln for ln in lines))
    c2 = _find(lines, "canary tag=prequiesce name=c2")
    want_c2 = {"buddy": 256, "slab": 256, "pgtable": 256, "lru_anon": 256, "lru_file": 256, "comp_head": 256,
               "comp_tail": 256, "nopage": 256, "reserved": 256, "held_other": 256, "free_or_tail": 1536}
    check("decode c2 prequiesce class counts (every class)",
          c2 is not None and all(int(c2[k]) == v for k, v in want_c2.items()))
    check("decode c2 prequiesce held and free", c2 is not None and (c2["held"], c2["free"], c2["pages"]) ==
          ("2048", "1792", "4096"))
    c1 = _find(lines, "canary tag=prequiesce name=c1")
    check("decode c1 prequiesce all buddy", c1 is not None and c1["buddy"] == "4096" and c1["phys"] == "0xbd000000")
    c3 = _find(lines, "canary tag=prequiesce name=c3")
    check("decode c3 prequiesce all lru_file", c3 is not None and c3["lru_file"] == "4096" and
          c3["phys"] == "0x189000000")
    c1post = _find(lines, "canary tag=postquiesce name=c1")
    check("decode c1 postquiesce all free_or_tail", c1post is not None and c1post["free_or_tail"] == "4096")
    m0 = _find(lines, "mib tag=prequiesce name=c2 index=0")
    check("decode mib c2 index 0 slab with precedence pages", m0 is not None and m0["slab"] == "256" and
          m0["pages"] == "256" and m0["phys"] == "0x100000000")
    m3 = _find(lines, "mib tag=prequiesce name=c2 index=3")
    check("decode mib c2 index 3 lru_anon", m3 is not None and m3["lru_anon"] == "256" and m3["phys"] == "0x100300000")
    m15 = _find(lines, "mib tag=prequiesce name=c3 index=15")
    check("decode mib c3 index 15", m15 is not None and m15["lru_file"] == "256" and m15["phys"] == "0x189f00000")
    check("decode 48 mib lines per snapshot", sum(ln.startswith("mib tag=prequiesce ") for ln in lines) == 48)
    check("decode 138 w2map lines per snapshot", sum(ln.startswith("w2map tag=postquiesce ") for ln in lines) == 138)
    b0 = _find(lines, "w2map tag=prequiesce bucket=0")
    check("decode w2map bucket 0 is c2", b0 is not None and b0["canary"] == "c2" and b0["dominant"] == "free_or_tail")
    b1 = _find(lines, "w2map tag=prequiesce bucket=1")
    check("decode w2map bucket 1 dominant slab", b1 is not None and b1["dominant"] == "slab" and b1["slab"] == "4096")
    b2 = _find(lines, "w2map tag=prequiesce bucket=2")
    check("decode w2map tie goes to the earlier class", b2 is not None and b2["dominant"] == "pgtable" and
          b2["lru_anon"] == "2048")
    b137 = _find(lines, "w2map tag=prequiesce bucket=137")
    check("decode w2map bucket 137 is c3", b137 is not None and b137["canary"] == "c3" and
          b137["phys"] == "0x189000000")
    tr = _find(lines, "transition name=c2 from=prequiesce to=postquiesce")
    want_tr = {"pages": "4096", "held_to_free": "768", "free_to_held": "256", "held_to_held": "1280",
               "free_to_free": "1280", "nopage_either": "512", "record_only": "yes"}
    check("decode c2 transition counts", tr is not None and all(tr.get(k) == v for k, v in want_tr.items()))
    snap = _find(lines, "snapshot tag=prequiesce")
    check("decode snapshot stamps", snap is not None and snap["boot_id"] == FIX_BOOT and
          snap["sha256_check"] == "ok" and snap["entries"] == str(4096 + 0x8A000) and
          snap["header_sha256"] == sha256(pre_text.encode("ascii")))
    rc2, lines2 = decode([post_h, pre_h])
    check("decode order of the two headers does not matter", rc2 == 0 and lines2 == lines)

    # ---- a one-snapshot decode
    rc, lines = decode([post_h])
    check("decode single exit 0 and limit sentence", rc == 0 and lines[0] == f"limit: {LIMIT}")
    check("decode single transition not computed",
          _find(lines, "transition name=c2 result=not-computed reason=one-snapshot record_only=yes") is not None)
    check("decode single has no prequiesce line", not any("tag=prequiesce" in ln for ln in lines))

    # ---- refusals
    def refused(label, paths, reason):
        rc_, lines_ = decode(paths)
        ok_ = (rc_ == 2 and lines_[0] == f"limit: {LIMIT}" and
               lines_[-1].startswith(f"decode result=refused reason={reason} ") and
               not any(ln.startswith(("canary ", "mib ", "w2map ", "transition ", "snapshot ")) for ln in lines_) and
               not any(tdir in ln for ln in lines_))
        check(f"refuse {label}", ok_)

    def variant(label, text, reason, name=None):
        refused(label, [header(name or "v.hdr", text)], reason)

    def swap(old, new, text=post_text):
        assert old in text, old
        return text.replace(old, new, 1)

    refused("header file absent", [os.path.join(tdir, "absent.hdr")], "header-missing")
    refused("a slice passed as the header", [os.path.join(tdir, "t-kpf-postquiesce.flags.bin")], "header-missing")
    variant("empty header", "", "header-missing")
    variant("CR in header", post_text.replace("\n", "\r\n"), "header-malformed")
    variant("no final newline", post_text[:-1], "header-malformed")
    variant("header version 2", swap("kpf_header=1", "kpf_header=2"), "header-malformed")
    variant("blank line", swap("tag=postquiesce\n", "tag=postquiesce\n\n"), "header-malformed")
    variant("unknown key", post_text + "comment=x\n", "header-malformed")
    variant("duplicate key", post_text + "tag=postquiesce\n", "header-malformed")
    variant("missing boot_id", swap(f"boot_id={FIX_BOOT}\n", ""), "header-malformed")
    variant("space in a value", swap("uptime_s=240.5", "uptime_s=240 5"), "header-malformed")
    variant("slice name with a path", swap("flags_file=t-kpf", "flags_file=../t-kpf"), "header-malformed")
    variant("slice name dot-dot", swap("flags_file=t-kpf-postquiesce.flags.bin", "flags_file=.."),
            "header-malformed")
    variant("sha256 not hex64", swap(f"count_sha256={qcs}", "count_sha256=abc"), "header-malformed")
    variant("zoneinfo without its sha256", post_text + "zoneinfo_file=t-kpf-prequiesce.zoneinfo.txt\n",
            "header-malformed")
    variant("range tokens out of order",
            swap("range=c1 pfn_start=0xbd000 pfn_count=4096", "range=c1 pfn_count=4096 pfn_start=0xbd000"),
            "header-malformed")
    variant("page size 16 KiB", swap("page_size=4096", "page_size=16384"), "page-size")
    variant("tag probe", swap("tag=postquiesce", "tag=probe"), "tag")
    variant("range pfn_start moved", swap("pfn_start=0x100000", "pfn_start=0x100001"), "range")
    variant("range count short", swap("pfn_count=565248", "pfn_count=565247"), "range")
    variant("range w2 missing", "".join(ln + "\n" for ln in post_text.splitlines() if not ln.startswith("range=w2")),
            "range")
    variant("range src_offset wrong", swap("src_offset=0x800000", "src_offset=0x800008"), "range")
    variant("range slice_offset wrong", swap("slice_offset=32768", "slice_offset=0"), "slice-layout")
    variant("slice file absent", swap("count_file=t-kpf-postquiesce.count.bin", "count_file=absent.bin"),
            "slice-missing")
    write("odd.bin", b"\0" * 13)
    variant("size not a multiple of 8", swap("flags_file=t-kpf-postquiesce.flags.bin", "flags_file=odd.bin"),
            "size-not-multiple-of-8")
    write("short.bin", b"\0" * 16)
    variant("flags entry count differs from header",
            swap("flags_file=t-kpf-postquiesce.flags.bin", "flags_file=short.bin"), "entry-count")
    variant("count entry count differs from header",
            swap("count_file=t-kpf-postquiesce.count.bin", "count_file=short.bin"), "entry-count")
    bad = qfs[:-1] + ("0" if qfs[-1] != "0" else "1")
    variant("flags sha256 differs", swap(f"flags_sha256={qfs}", f"flags_sha256={bad}"), "sha256")
    variant("zoneinfo sha256 differs", swap("zoneinfo_sha256=" + zs, "zoneinfo_sha256=" + "0" * 64, pre_text),
            "sha256")
    refused("two postquiesce headers", [post_h, post_h], "tag")
    other = header("t-other-boot.hdr", swap(f"boot_id={FIX_BOOT}", f"boot_id={FIX_BOOT2}", pre_text))
    refused("boot_id mismatch", [other, post_h], "boot-id-mismatch")
    late = header("t-late.hdr", swap("uptime_s=100.25", "uptime_s=300", pre_text))
    refused("postquiesce uptime not above prequiesce", [late, post_h], "uptime-order")

    for label, argv in (("three headers", [pre_h, post_h, pre_h]), ("no header", []),
                        ("--selftest with a header", ["--selftest", pre_h])):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = main(argv)
        check(f"usage {label} exit 2", rc == 2 and "usage:" in err.getvalue())


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Decode S1-F kpageflags snapshots (s1-design.md §15.5 A2).")
    ap.add_argument("--selftest", action="store_true", help="synthetic slices: every class, refusal and transition")
    ap.add_argument("header", nargs="*", help="one snapshot header, or a prequiesce and a postquiesce header")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if a.selftest:
        if a.header:
            ap.print_usage(sys.stderr)
            return 2
        return selftest()
    if len(a.header) not in (1, 2):
        ap.print_usage(sys.stderr)
        return 2
    return cmd_decode(a.header)


if __name__ == "__main__":
    sys.exit(main())
